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

"""
Silly tool necessary if your one-time run of loadAllJiraIssues.py crashed and you had to restart it and it loaded some duplicate issues into allIssues.txt
"""

with open('allIssues.txt', 'rb') as f, open('allIssues.dedup.txt', 'wb') as fOut:
  seen = set()
  while True:
    l = f.readline()
    if l == b'':
      break
    i = l.find(b':')
    key = l[:i]
    if key not in seen:
      seen.add(key)
      fOut.write(l)
    else:
      print('skip dup %s' % key)
