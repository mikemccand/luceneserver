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

import io
import os
import gzip
import traceback
import sys
sys.path.insert(0, '/home/ec2-user/src/github-ui')
import util
import handle
import time

import time
import re
import urllib.request
import urllib.parse
import threading
import sys

# assume we start up OK
status_github_actions = ['OK', time.time()]

def get_nrt_log_status(site):
  age_sec = time.time() - os.path.getmtime(f'/home/ec2-user/state/{site}/logs/nrt.log')
  if age_sec >= 60:
    http_status = f'500 {site}-nrt log age is {age_sec:.2f} seconds'
  else:
    http_status = f'200 OK {site}-nrt log age is {age_sec:.2f} seconds'
  return http_status

# Entry point in production:
def application(environ, start_response):

  qs = environ['QUERY_STRING']

  args = urllib.parse.parse_qs(qs)
  if 'what' in args:
    what = args['what'][0]
  else:
    what = 'github-actions'

  if what == 'github-actions':
    age = time.time() - status_github_actions[1]

    if age > 15:
      # background status thread died!
      http_status = f'500 Thread died {age:.2f} seconds ago'
    else:
      # background thread still running, but what is status?
      if status_github_actions[0].startswith('OK'):
        http_status = f'200 OK {status_github_actions[0]} checked {age:.2f} seconds ago'
      else:
        http_status = f'500 {status_github_actions[0]} checked {age:.2f} seconds ago'
  elif what == 'jira-nrt':
    http_status = get_nrt_log_status('jira')
  elif what == 'github-nrt':
    http_status = get_nrt_log_status('github')
  else:
    http_status = f'500 unknown status what={what}'
        
  headers = []
  bytes = http_status.encode('utf-8')
  headers.append(('Content-Length', str(len(bytes))))
  start_response(http_status, headers)
  return [bytes]

def check_github_actions_status():
  last_zero_count_time = time.time()
  
  while True:

    try:
      now = time.time()
      status_github_actions[1] = now
      # TODO: need timeout
      print(f'NOW CHECK GH ACTIONS STATUS {os.getpid()}')
      with urllib.request.urlopen('https://github.com/apache/lucene/actions?query=is%3Aaction_required') as response:
        html = response.read().decode('utf-8')
      m = re.search(r'<strong>(\d+) workflow run results</strong>', html)
      if m is None:
        status_github_actions[0] = 'FAILED: could not find count in https://github.com/apache/lucene/actions?query=is%3Aaction_required'
      else:
        count = int(m.group(1))
        if count == 0:
          # yay
          last_zero_count_time = now
          status_github_actions[0] = 'OK'
        elif now - last_zero_count_time > 30:
          # the auto-approver bot waits ~10-20 seconds between checking
          status_github_actions[0] = f'STALE {(now - last_zero_count_time):.2f} sec since no approvals'
        else:
          status_github_actions[0] = f'OK: {(now - last_zero_count_time):.2f} sec since no approvals'
    except KeyboardInterrupt:
      raise
    except:
      status_github_actions[0] = f'FAILED: exception {sys.exception()}'

    print(f'status is {status_github_actions=}')
    time.sleep(10)

github_actions_status_thread = threading.Thread(target=check_github_actions_status)
github_actions_status_thread.daemon = True
github_actions_status_thread.start()
print('NOW START STATUS THREAD')

if __name__ == '__main__':
    while True:
        print(f'status: {status_github_actions[0]}: {(time.time() - status_github_actions[1])}')
        time.sleep(1)
