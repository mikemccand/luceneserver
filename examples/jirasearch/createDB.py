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

import json
import sqlite3
import pickle
import os
import sys
import localconstants
import datetime

"""
One time conversion, to turn allIssues.txt (exported via
loadAllJiraIssues) -> sqlite3 DB used by indexJira.py for NRT updates.
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
