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

import sys
sys.path.insert(0, '/home/ec2-user/src/github-ui')
import time
import pickle

import urllib.parse
import datetime
import base64

TESLAMATE_STATE_FILE = '/var/www/status/html/teslamate_status.txt'

# Entry point in production:
def application(environ, start_response):

  qs = environ['QUERY_STRING']

  args = urllib.parse.parse_qs(qs)
  what = args['what'][0]
  payload = args['payload'][0]

  s = base64.urlsafe_b64decode(payload)
  status = pickle.loads(s)

  if what == 'teslamate':
    min_age = None
    l = []
    for table_name, age in status.items():
      l.append(f'{table_name} was last updated {age} ago')
      if min_age is None or min_age < age:
        min_age = age
    message = ';'.join(l)
    if min_age > datetime.timedelta(hours=4):
      state = f'STALE: {message}'
    else:
      state = f'OK: {message}'

    open(TESLAMATE_STATE_FILE, 'w').write(state)
    print(f'now set status_teslamate {state}')
  else:
    raise RuntimeError(f'unknown {what=}')

  bytes = f'OK {state=}'.encode('utf-8')

  headers = []
  headers.append(('Content-Length', str(len(bytes))))
  start_response(f'200 OK [state={state}]', headers)
  return [bytes]
  
