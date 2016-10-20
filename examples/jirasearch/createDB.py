import json
import sqlite3
import pickle
import os
import sys
import localconstants
import datetime

"""
Turns allIssues.txt -> sqlite3 DB
"""

print('Building DB %s...' % localconstants.DB_PATH)

if os.path.exists(localconstants.DB_PATH):
  os.remove(localconstants.DB_PATH)

db = sqlite3.connect(localconstants.DB_PATH)
c = db.cursor()
c.execute('DROP TABLE IF EXISTS issues')
c.execute('CREATE TABLE IF NOT EXISTS issues (key text PRIMARY KEY, body text)')
c.execute('CREATE UNIQUE INDEX idx_issues_key ON issues(key)')
with open('/lucenedata/jirasearch/allIssues.20161017.txt', 'rb') as f:
  while True:
    l = f.readline()
    if l == b'':
      break
    i = l.find(b':')
    key = l[:i]
    value = l[i+1:].strip()
    c.execute('INSERT INTO issues (key, body) VALUES (?, ?)', (key, pickle.dumps(json.loads(value.decode('utf-8')))))
c.execute('CREATE TABLE IF NOT EXISTS lastUpdate (lastUpdate text)')
c.execute('INSERT INTO lastUpdate VALUES (?)', (pickle.dumps(datetime.datetime(year=2016, month=10, day=17)),))
db.commit()
