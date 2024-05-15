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
HOME_DOOR_MOTION_STATE_FILE = '/var/www/status/html/home_door_motion_status.txt'

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
    message = '; '.join(l)
    if min_age > datetime.timedelta(hours=24):
      state = f'STALE: {message}'
    else:
      state = f'OK: {message}'

    open(TESLAMATE_STATE_FILE, 'w').write(state)
    print(f'now set status_teslamate {state}')
  elif what == 'homedoormotion':
    l = []
    now = datetime.datetime.now()

    stale_reasons = []
    for device_name, age in status.items():
      if device_name in ('Foyer Motion', 'Basement Stairs Top Motion', 'Basement Door', 'Basement Motion', 'Garage Motion', 'Garage Motion 2', 'Outer Garage Door', 'Car Garage Door (left)', 'Car Garage Door (right', 'Inner Garage Door'):
          max_age = datetime.timedelta(hours=24)
      elif device_name in ('Car Garage Door (left)',):
          max_age = datetime.timedelta(days=3)
      elif device_name in ('Front Porch Motion', 'Front Porch Motion 2', 'Front Door'):
          max_age = datetime.timedelta(days=3)
      elif device_name in ('Back Door',):
          max_age = datetime.timedelta(days=7)

      if age is None:
        reason = f'{device_name} was never touched'
        stale_reasons.append(reason)
      elif age > max_age:
        reason = f'{device_name} is stale ({age} > {max_age})'
        stale_reasons.append(reason)
      else:
        reason = f'{device_name} is fresh ({age} <= {max_age})'
        l.append(reason)
        
    message = '\n'.join(l)
    if len(stale_reasons) > 0:
      stale_message = '\n'.join(stale_reasons)
      state = f'STALE:\n{stale_message}\n{message}'
    else:
      state = f'OK\n{message}'

    open(HOME_DOOR_MOTION_STATE_FILE, 'w').write(state)
    print(f'now set status_homedoormotion {state}')
  else:
    raise RuntimeError(f'unknown {what=}')

  bytes = f'OK {state=}'.encode('utf-8')

  headers = []
  headers.append(('Content-Length', str(len(bytes))))
  start_response(f'200 OK', headers)
  return [bytes]
  
