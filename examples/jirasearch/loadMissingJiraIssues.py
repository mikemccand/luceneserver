# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sqlite3
import localconstants
import urllib.parse
import time
import urllib.request
import pprint
import pickle
import json
import traceback
import sys

"""
For some reason, the initial scroll through all Jira issues was
missing some.  This silly tool finds the missing ones and loads them
directly.
"""

DB_PATH = localconstants.DB_PATH

db = sqlite3.connect(DB_PATH)
c = db.cursor()
maxByProject = {}
keys = set()
renamedIssues = {}

for key, body in c.execute('select key, body from issues'):
  key = key.decode('utf-8')
  keys.add(key)

  issue = pickle.loads(body)

  for ent in issue['changelog']['histories']:
    for d in ent['items']:
      if d['field'] == 'Key':
        renamedIssues[d['fromString']] = d['toString']
        print('  %s renamed to %s' % (d['fromString'], d['toString']))
  project, number = key.split('-')
  number = int(number)
  maxByProject[project] = max(number, maxByProject.get(project, 0))

knownLost = set()
with open('lostIssues.txt', 'rb') as f:
  for line in f.readlines():
    knownLost.add(line.strip().decode('utf-8'))

alreadyFoundIssues = set()
with open('missingIssues.txt', 'rb') as f:
  for line in f.readlines():
    line = line.decode('utf-8')
    i = line.find(':')
    key = line[:i].strip()
    alreadyFoundIssues.add(key)

missing = []
for project, maxNumber in maxByProject.items():
  print('missing in %s:' % project)
  for i in range(1, maxNumber+1):
    key = '%s-%s' % (project, i)
    if key in knownLost:
      print('  known lost: %s' % key)
    elif key in renamedIssues:
      print('  renamed: %s -> %s' % (key, renamedIssues[key]))
    elif key in alreadyFoundIssues:
      print('  recovered: %s' % key)
    elif key not in keys:
      print('  missing: %s' % key)
      if project == 'INFRA':
        missing.append(key)
db.close()

with open('missingIssues.txt', 'ab') as f, open('lostIssues.txt', 'ab') as fLost:

  upto = 0
  while upto < len(missing):

    issue = missing[upto]

    print('\ncycle')
    print('  load %s' % issue)

    if False:
      args = {
        'jql': 'KEY in (%s)' % issue,
        'expand': 'changelog',
        'maxResults': '200',
        'fields': '*all',
        }
      url = 'https://issues.apache.org/jira/rest/api/2/search?%s' % urllib.parse.urlencode(args)
    else:
      url = 'https://issues.apache.org/jira/rest/api/2/issue/%s?expand=changelog' % issue
    print('  url: %s' % url)
    skip = False
    while True:
      try:
        s = urllib.request.urlopen(url).read().decode('utf-8')
      except urllib.error.HTTPError as e:
        print('    lost to Jira: %s' % e)
        fLost.write(('%s\n' % issue).encode('utf-8'))
        fLost.flush()
        upto += 1
        time.sleep(5.0)
        skip = True
        break
      except:
        print('FAILED: wait then retry...\n')
        traceback.print_exc()
        time.sleep(30.0)
      else:
        break

    if skip:
      continue

    o = json.loads(s)
    #print('dir: %s' % o.keys())
    if False:
      numIssues = len(o['issues'])
      print('    %d results; %.1f KB' % (numIssues, len(s)/1024.))
      if numIssues == 0:
        fLost.write(('%s\n' % issue).encode('utf-8'))
        fLost.flush()
      else:
        for x in o['issues']:
          print('      loaded %s' % x['key'])
          f.write(('%s: %s\n' % (x['key'], json.dumps(x))).encode('utf-8'))
        f.flush()
    print('  %d bytes' % len(s))
    f.write(('%s: %s\n' % (issue, json.dumps(o))).encode('utf-8'))
    upto += 1
    time.sleep(5.0)

