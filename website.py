#!/usr/bin/env python

from flask import Flask, escape, redirect, render_template, request, session, url_for

from twitter import *

import hashlib
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

@app.route("/intersect", methods=['POST'])
def intersect():
    if not 'oauth_token' in session or not 'oauth_secret' in session:
        return redirect(url_for('index'))

    oauth_token = session.get('oauth_token', None)
    oauth_secret = session.get('oauth_secret', None)

    user = get_user_info(oauth_token, oauth_secret)
    other_name = request.form.get('other_name', None)
    if not other_name or other_name == user['screen_name']:
        return redirect(url_for('index'))

    my_list = get_follower_ids(oauth_token, oauth_secret, user['screen_name'])
    their_list = get_follower_ids(oauth_token, oauth_secret, other_name)

    i = set(my_list).intersection(set(their_list))
    users = user_lookup(oauth_token, oauth_secret, i)
    users.sort(key=lambda x: x['name'].lower())

    stats = { 'me': len(my_list),
              'other': len(their_list),
              'both': len(users),
              'name': other_name,
            }

    return render_template("list.html", user=user, users=users, stats=stats)


### Twitter methods

def get_user_info(oauth_token, oauth_secret):
    u = mc.get(str(oauth_token)+":user")
    if not u:
        t = Twitter(auth=OAuth(oauth_token, oauth_secret, consumer_key, consumer_secret))
        u = t.account.settings()
        mc.set(str(oauth_token)+":user", dict(u))
    return u

def get_follower_ids(oauth_token, oauth_secret, screen_name=None):
    # TODO fix the key for memcache - currently we're leaking protected user follower lists
    f = mc.get(str("%s:followers_l" % screen_name))

    if not f:
        print "Fetching from Twitter"
        t = Twitter(auth=OAuth(oauth_token, oauth_secret, consumer_key, consumer_secret))
        f = []

        cursor = -1
        while cursor:
            print "Fetching follower IDs with screen_name %s cursor %s" % (screen_name, cursor)
            r = t.followers.ids(screen_name=screen_name, cursor=cursor)

            print r
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
            users.extend(list(t.users.lookup(user_id=user_ids)))

        # TODO? split up users into their own memcache key
        mc.set(key, users)

    return users

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
    
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug = True)

