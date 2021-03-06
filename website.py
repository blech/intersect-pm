#!/usr/bin/env python

from flask import Flask, escape, redirect, render_template, request, session, url_for
from werkzeug.exceptions import NotFound as WerkzeugNotFound

from twitter import *

import hashlib
import json
import math
import memcache
import os

app = Flask(__name__)
app.secret_key = os.environ['app_secret']

consumer_key = os.environ['consumer_key']
consumer_secret = os.environ['consumer_secret']

mc = memcache.Client(['127.0.0.1:11211'], debug=0)

@app.route("/")
def index():
    if not 'oauth_token' in session or not 'oauth_secret' in session:
        return render_template("auth.html")

    oauth_token = session.get('oauth_token', None)
    oauth_secret = session.get('oauth_secret', None)

    user = get_user_info(oauth_token, oauth_secret)
    return render_template("index.html", user=user)

@app.route("/", methods=['POST'])
def intersect():
    if not 'oauth_token' in session or not 'oauth_secret' in session:
        return redirect(url_for('index'))

    them = request.form.get('them', None)
    if not them:
        return redirect(url_for('index'))

    return redirect(url_for('permalink', them=them, me='me'))

@app.route("/<me>/<them>/", methods=['GET'])
def permalink(me, them):
    if not 'oauth_token' in session or not 'oauth_secret' in session:
        session['return_to'] = request.full_path
        return redirect(url_for('index'))

    return _intersect(me=me, them=them)

def _intersect(them, me=None):
    oauth_token = session.get('oauth_token', None)
    oauth_secret = session.get('oauth_secret', None)

    user = get_user_info(oauth_token, oauth_secret)

    if not me or me == "me":
        me = user['screen_name']

    if me == them:
       return redirect(url_for('index'))

    my_list = get_follower_ids(oauth_token, oauth_secret, me)
    their_list = get_follower_ids(oauth_token, oauth_secret, them)

    i = set(my_list).intersection(set(their_list))
    users = user_lookup(oauth_token, oauth_secret, i)
    users.sort(key=lambda x: x['screen_name'].lower())

    dist = distance(len(my_list), len(their_list), len(users)) #, show_working=True)

    stats = { 'me': me,
              'mine': len(my_list),
              'them': them,
              'theirs': len(their_list),
              'both': len(users),
              'distance': dist,
            }

    return render_template("list.html", user=user, users=users, stats=stats)

@app.route("/intersect/<me>/<them>/", methods=['GET'])
def old_permalink(me, them):
    return redirect(url_for('permalink', them=them, me=me))

@app.route("/limits")
def limits():
    if not 'oauth_token' in session or not 'oauth_secret' in session:
        session['return_to'] = request.full_path
        return redirect(url_for('index'))

    user = get_user_info(oauth_token, oauth_secret)
    limits = get_rate_limits(oauth_token, oauth_secret)
    return render_template("limits.html", user=user, limits=limits)

### error handlers

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404
    
@app.errorhandler(500)
def internal_error(e):
    return render_template('500.html'), 500

def handle_twitter_exception(e):
    # handle TwitterHTTPError
    # TODO use type() matching not duck typing, maybe?
    if hasattr(e, 'response_data'):
        error = None
        full = json.loads(e.response_data)

        if 'error' in full:
            error = full['error']
        elif 'errors' in full:
            error = ', '.join([e['message'] for e in full['errors']])

        if error:
            print "Handled Twitter error. Details: %r" % full
            return render_template('500.html', error=error, type='twitter'), 500
        else:
            print "Got unhandled Twitter error. Details: %r" % full
            return render_template('500.html'), 500

    print "Got unknown exception %s %r" % (type(e), e)
    raise e
app.handle_exception = handle_twitter_exception


### Twitter methods

def get_user_info(oauth_token, oauth_secret):
    u = mc.get(str(oauth_token)+":user")
    if not u:
        t = Twitter(auth=OAuth(oauth_token, oauth_secret, consumer_key, consumer_secret))
        u = t.account.settings()
        print "Twitter account.settings call made, with %s requests remaining" % u.rate_limit_remaining
        mc.set(str(oauth_token)+":user", dict(u))
    return u

def get_follower_ids(oauth_token, oauth_secret, screen_name=None):
    # TODO fix the key for memcache - currently we're leaking protected user follower lists
    f = mc.get(str("%s:followers_l" % screen_name))

    if not f:
        t = Twitter(auth=OAuth(oauth_token, oauth_secret, consumer_key, consumer_secret))
        f = []

        cursor = -1
        while cursor:
            r = t.followers.ids(screen_name=screen_name, cursor=cursor)
            print "Twitter followers.ids call made, with %s requests remaining" % r.rate_limit_remaining
            f.extend(r['ids'])
            cursor = r['next_cursor']

        mc.set(str("%s:followers_l" % screen_name), list(f))

    return f

def user_lookup(oauth_token, oauth_secret, intersect):
    user_ids = ','.join([str(x) for x in intersect])
    key = hashlib.md5(user_ids).hexdigest()

    users = mc.get(key)
    if not users:
        users = []
        t = Twitter(auth=OAuth(oauth_token, oauth_secret, consumer_key, consumer_secret))

        chunks = [list(intersect)[i:i+100] for i in range(0, len(intersect), 100)]
        for chunk in chunks:
            user_ids = ','.join([str(x) for x in chunk])
            r = t.users.lookup(user_id=user_ids)
            print "Twitter users.lookup call made, with %s requests remaining" % r.rate_limit_remaining
            users.extend(list(r))

        # TODO? split up users into their own memcache key
        mc.set(key, users)

    return users


### maths nonsense (calculates distance for overlapping circles)

def area(d, r1, r2, show_working):
    # http://mathworld.wolfram.com/Circle-CircleIntersection.html eqn 14
    r1c = (d**2+r1**2-r2**2)/(2*d*r1)
    r2c = (d**2+r2**2-r1**2)/(2*d*r2)
    rm = (0-d+r1+r2)*(d+r1-r2)*(d-r1+r2)*(d+r1+r2)

    if show_working: print "area calc has r1c, r2c, rm: %s, %s, %s" % (r1c, r2c, rm)

    na = (r1**2)*math.acos(r1c)+(r2**2)*math.acos(r2c)-(0.5*math.sqrt(rm))
    return na

def distance(me, them, desired, show_working=False):
    r1 = math.sqrt(float(me)/math.pi)
    r2 = math.sqrt(float(them)/math.pi)
    
    if show_working: print "%s -> %s; %s -> %s" % (me, r1, them, r2)

    if desired == 0:
        if show_working: print "No overlap, returning 0"
        return r1+r2+((r1+r2)/100)

    # here comes the infinite series, concentrate
    scale = 0.5; change = 0.5
    maximum = r1+r2; minimum = abs(r1-r2)
    diff = maximum-minimum

    overlap = 0

    # binary search ahoy
    # the condition should be a fraction, but this kind of works
    while abs(desired-overlap) > .25:
        d = diff*scale+minimum
        change = change/2

        if show_working: print "Starting scale %s distance %s" % (scale, d)

        overlap = area(d, r1, r2, show_working)
        if show_working: print " ... calculated overlap %s (want %s)" % (overlap, desired)

        if overlap > desired:
            scale = scale+change
        else:
            scale = scale-change

        if not change:
            break # must be close enough by now

    if show_working: print " ... returning distance %s (r1 %s, r2 %s)" % (d, r1, r2)
    return d


### utility auth method

def parse_oauth_tokens(result):
    for r in result.split('&'):
        k, v = r.split('=')
        if k == 'oauth_token':
            oauth_token = v
        elif k == 'oauth_token_secret':
            oauth_token_secret = v
    return oauth_token, oauth_token_secret


### /auth and /callback required for logging in to Twitter

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    twitter = Twitter(auth=OAuth('', '', consumer_key, consumer_secret), format='', api_version=None)

    oauth_callback = request.host_url + 'callback'
    request_token = twitter.oauth.request_token(oauth_callback=oauth_callback)
    oauth_token, oauth_token_secret = parse_oauth_tokens(request_token)

    session['temp_token'] = oauth_token
    session['temp_secret'] = oauth_token_secret

    return redirect("http://api.twitter.com/oauth/authorize?oauth_token=" + oauth_token)

@app.route('/callback', methods=['GET', 'POST'])
def callback():
    temp_token = request.args.get('oauth_token', None)
    temp_secret = session.get('temp_secret', None)
    oauth_verifier = request.args.get('oauth_verifier', None)

    if not temp_token or not temp_secret:
        # TODO error messaging?
        redirect(url_for('auth'))

    twitter = Twitter(auth=OAuth(session['temp_token'], session['temp_secret'], consumer_key, 
                                 consumer_secret), 
                      format='', api_version=None)

    tokens = twitter.oauth.access_token(oauth_verifier=oauth_verifier)
    (session['oauth_token'], session['oauth_secret']) = parse_oauth_tokens(tokens)

    session.pop('temp_token', None)
    session.pop('temp_secret', None)
    
    return_to = session.pop('return_to', None)
    if return_to:
        return redirect(return_to)

    return redirect(url_for('index'))


### logout might be a good idea
@app.route('/forget')
def forget():
    for var in ('temp_token', 'temp_secret', 'oauth_token', 'oauth_secret'):
        session.pop(var, None)

    return redirect(url_for('index'))


if __name__ == "__main__":
    app.run(debug = True)

