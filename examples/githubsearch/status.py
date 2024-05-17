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

import os
import sys
sys.path.insert(0, '/home/ec2-user/src/github-ui')
import time

import re
import urllib.request
import urllib.parse
import threading
import datetime
import submit

TESLAMATE_STATE_FILE = submit.TESLAMATE_STATE_FILE
HOME_DOOR_MOTION_STATE_FILE = submit.HOME_DOOR_MOTION_STATE_FILE

# assume we start up OK
status_github_actions = ['OK', time.time()]
status_lucene_benchmarks = ['OK', time.time()]

def get_nrt_log_status(site):
  age_sec = time.time() - os.path.getmtime(f'/home/ec2-user/state/{site}/logs/nrt.log')
  if age_sec >= 60:
    http_status = f'500 {site}-nrt log age is {age_sec:.2f} seconds'
  else:
    http_status = f'200 OK {site}-nrt log age is {age_sec:.2f} seconds'
  return http_status

re_last_table_row = re.compile(r'(\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d),.*?\\n"\s*,\s*\{\s*"?title')

def check_one_benchy_page(page_name, expected_chart_count):
  now = datetime.datetime.now()
  max_age = datetime.timedelta(seconds=0)
  count = 0
  with urllib.request.urlopen(f'https://home.apache.org/~mikemccand/{page_name}.html') as response:
    html = response.read().decode('utf-8')
    matches = re_last_table_row.findall(html)
    if len(matches) != expected_chart_count:
      raise RuntimeError(f'expected {expected_chart_count} tables in {page_name}.html but found {len(matches)}')
    for timestamp in matches:
      dt = datetime.datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
      age = now - dt
      # 24 hours plus how long benchy takes to run (18 hours should be plenty for that)
      too_old = datetime.timedelta(hours=42)
      if age > too_old:
        raise RuntimeError(f'{page_name} chart is {age} old, more than the expected {too_old}')
      max_age = max(max_age, age)
      count += 1
  return max_age, count

def check_all_benchy():
  ages = []
  total_count = 0
  for name, expected_count in (('lucenebench/indexing', 6),
                               ('lucenebench/nad_facet_benchmarks', 5),
                               ('lucenebench/stored_fields_benchmarks', 3),
                               ('geobench', 10),
                               ('lucenebench/sparseResults', 16),
                               ('lucenebench/checkIndexTime', 1),
                               ('lucenebench/github_pr_counts', 1)):

    t0 = time.time()
    print(f'now check {name}, expected_count={expected_count}')
    max_age, count = check_one_benchy_page(name, expected_count)
    ages.append(f'{max_age.total_seconds()/3600:.2f}')
    print(f'  took {time.time()-t0:.2f} sec; age {max_age.total_seconds():.2f} sec')
    total_count += count
  return ', '.join(ages), total_count

# Entry point in production:
def application(environ, start_response):

  qs = environ['QUERY_STRING']

  args = urllib.parse.parse_qs(qs)
  if 'what' in args:
    what = args['what'][0]
  else:
    what = 'github-actions'

  body = None

  if what == 'github-actions':
    age = time.time() - status_github_actions[1]

    if age > 120:
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
  elif what == 'lucene-benchmarks':
    age = time.time() - status_lucene_benchmarks[1]

    if age > 900:
      # background status thread died!
      http_status = f'500 Thread died {age:.2f} seconds ago'
    else:
      # background thread still running, but what is status?
      if status_lucene_benchmarks[0].startswith('OK'):
        http_status = f'200 OK {status_lucene_benchmarks[0]} checked {age:.2f} seconds ago'
      else:
        http_status = f'500 {status_lucene_benchmarks[0]} checked {age:.2f} seconds ago'
  elif what == 'teslamate':

    mod_time = os.path.getmtime(TESLAMATE_STATE_FILE)
    age = time.time() - mod_time
    if age > 60:
      # updater died!
      http_status = f'500 updater died {age=}'
    else:
      state = open(TESLAMATE_STATE_FILE, 'r').read()
      # updater still running, but what is status?
      if state.startswith('OK'):
        http_status = f'200 OK {state} checked {age:.2f} seconds ago'
      else:
        http_status = f'500 {state} checked {age:.2f} seconds ago'
  elif what == 'homedoormotion':

    mod_time = os.path.getmtime(HOME_DOOR_MOTION_STATE_FILE)
    age = time.time() - mod_time
    if age > 60:
      # updater died!
      http_status = f'500 updater died {age=}'
    else:
      state = open(HOME_DOOR_MOTION_STATE_FILE, 'r').read()

      state_lines = state.splitlines()
      
      # updater still running, but what is status?
      if state_lines[0].startswith('OK'):
        http_status = f'200 OK {state_lines[0]} checked {age:.2f} seconds ago'
      else:
        http_status = f'500 {state_lines[0]} checked {age:.2f} seconds ago'

      body = state
      
  else:
    http_status = f'500 unknown status what={what}; must be one of: github-actions, lucene-benchmarks, jira-nrt, github-nrt, teslamate, homedoormotion'

  print(f'top status {what=} {http_status=}')

  if body is None:
    bytes = http_status.encode('utf-8')
  else:
    bytes = body.encode('utf-8')
  headers = []
  headers.append(('Content-Length', str(len(bytes))))
  start_response(http_status, headers)
  return [bytes]

def check_lucene_benchmarks_status():
  
  while True:
    try:
      now = time.time()
      status_lucene_benchmarks[1] = now
      # TODO: need timeout
      print(f'NOW CHECK LUCENE BENCHY STATUS {os.getpid()}')

      ages, total_count = check_all_benchy()
      status_lucene_benchmarks[0] = f'OK: {total_count} charts ages: {ages}'
    except KeyboardInterrupt:
      raise
    except:
      status_lucene_benchmarks[0] = f'FAILED: exception {sys.exception()}'

    print(f'status is {status_lucene_benchmarks=}')

    # only check every 10 minutes
    time.sleep(600)

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
        elif now - last_zero_count_time > 300:
          # the auto-approver bot waits ~10-20 seconds between checking, but maybe several approvals show up at once, and
          # they seem to come in pairs anyways
          status_github_actions[0] = f'STALE {(now - last_zero_count_time):.2f} sec since no approvals'
        else:
          status_github_actions[0] = f'OK: {(now - last_zero_count_time):.2f} sec since no approvals'
    except KeyboardInterrupt:
      raise
    except:
      status_github_actions[0] = f'FAILED: exception {sys.exception()}'

    print(f'status is {status_github_actions=}')
    time.sleep(30)

print('NOW START STATUS THREADS')

github_actions_status_thread = threading.Thread(target=check_github_actions_status)
github_actions_status_thread.daemon = True
github_actions_status_thread.start()

lucene_benchmarks_status_thread = threading.Thread(target=check_lucene_benchmarks_status)
lucene_benchmarks_status_thread.daemon = True
lucene_benchmarks_status_thread.start()

if __name__ == '__main__':
    while True:
        print(f'github actions status: {status_github_actions[0]}: {(time.time() - status_github_actions[1])} seconds ago')
        print(f'lucene benchmarks status: {status_lucene_benchmarks[0]}: {(time.time() - status_lucene_benchmarks[1])} seconds ago')
        time.sleep(1)
