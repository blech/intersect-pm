#!/usr/bin/python

other = 'joshuanguyen'

from twitter import *
from auth import *

t = Twitter(auth=OAuth(oauth_token, oauth_secret, consumer_key, consumer_secret))

blech_f = t.followers.ids()
print "Fetched %s users following blech" % len(blech_f['ids'])
other_f = t.followers.ids(screen_name=other)
print "Fetched %s users following %s" % (len(other_f['ids']), other)

i = set(blech_f['ids']).intersection(set(other_f['ids']))
user_ids = ','.join([str(x) for x in i])

users = t.users.lookup(user_id=user_ids)
print "Found %s overlapping users:" % len(users)
users_summary = [(x['screen_name'], x['name']) for x in users]
for user_summary in users_summary:
    print "%s: %s" % (user_summary[0], user_summary[1])
