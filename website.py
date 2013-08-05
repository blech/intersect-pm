#!/usr/bin/env python

from flask import Flask, escape, redirect, render_template, request, session, url_for

from twitter import *
from auth import *

import hashlib
import memcache

app = Flask(__name__)
app.secret_key = app_secret

mc = memcache.Client(['127.0.0.1:11211'], debug=0)

def parse_oauth_tokens(result):
    for r in result.split('&'):
        k, v = r.split('=')
        if k == 'oauth_token':
            oauth_token = v
        elif k == 'oauth_token_secret':
            oauth_token_secret = v
    return oauth_token, oauth_token_secret

@app.route("/")
def index():
    if not 'oauth_token' in session or not 'oauth_secret' in session:
        # return render_template("auth.html")
        return 'Click here to auth <a href="/auth">auth!</a>'

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

    i = set(my_list['ids']).intersection(set(their_list['ids']))
    users = user_lookup(oauth_token, oauth_secret, i)
    print "%r" % users

    return render_template("list.html", users=users)


### Twitter methods

def get_user_info(oauth_token, oauth_secret):
    u = mc.get(str(oauth_token)+":user")
    if not u:
        t = Twitter(auth=OAuth(oauth_token, oauth_secret, consumer_key, consumer_secret))
        u = t.account.settings()
        mc.set(str(oauth_token)+":user", dict(u))
    return u

def get_follower_ids(oauth_token, oauth_secret, screen_name=None):
    f = mc.get(str("%s:followers" % screen_name))
    if not f:
        t = Twitter(auth=OAuth(oauth_token, oauth_secret, consumer_key, consumer_secret))
        if screen_name:
            f = t.followers.ids(screen_name=screen_name)
        else:
            f = t.followers.ids()
        mc.set(str("%s:followers" % screen_name), dict(f))
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
        mc.set(key, users)
    return users

### /auth and /callback required for logging in to Twitter

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    twitter = Twitter(auth=OAuth('', '', consumer_key, consumer_secret), format='', api_version=None)
    oauth_token, oauth_token_secret = parse_oauth_tokens(twitter.oauth.request_token())

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

