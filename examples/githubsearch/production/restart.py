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

import time
import urllib.request, urllib.error, urllib.parse
import os
import sys
import shutil
import signal

sys.path.insert(0, '..')
import localconstants

PORT = localconstants.SERVER_PORT

"""
Production script to restart Lucene server and the UI.
"""

doReindex = '-reindex' in sys.argv
doServer = '-server' in sys.argv

def run(cmd):
  if os.system(cmd):
    raise RuntimeError('%s failed' % cmd)

if doServer:
  print()
  print('Kill current runServer process')

  # kill runServer wrapper:
  found = False
  for line in os.popen('ps auxww | grep runServer.py | grep -v grep | grep -v /bin/sh').readlines():
    pid = line.strip().split()[1]
    print('  kill server pid %s: %s' % (pid, line.strip()))
    if found:
      raise RuntimeError('found two pids!')
    try:
      run('kill -9 %d' % int(pid))
    except:
      print('FAILED:')
      traceback.print_exc()
    found = True

  if not found:
    raise RuntimeError('could not find existing runServer.py process')

  print()
  print('Kill current java server process')

  # kill java process
  found = False
  for line in os.popen('ps auxww | grep java | grep server.Server | grep "ipPort localhost:%s" | grep -v grep | grep -v /bin/sh' % PORT).readlines():
    pid = line.strip().split()[1]
    print('  kill server pid %s: %s' % (pid, line.strip()))
    if found:
      raise RuntimeError('found two pids!')
    try:
      run('kill -9 %d' % int(pid))
    except:
      print('FAILED:')
      traceback.print_exc()
    found = True

  if not found:
    raise RuntimeError('could not find existing java server.Server process')

  print()
  print('Start new java server process')

  run(f'nohup {localconstants.PYTHON_EXE} -u runServer.py > {localconstants.GLOBAL_LOG_DIR}/luceneserver.log 2>&1 &')

  # Wait until server is really ready:
  server_log_file = f'{localconstants.GLOBAL_LOG_DIR}/luceneserver.log'
  while True:
    if os.path.exists(server_log_file):
      s = open(server_log_file, 'rb').read()
      if s.find(('listening on').encode('utf-8')) != -1:
        break
    time.sleep(1.0)

  print()
  print('Restart Apache httpd')

  run('sudo apachectl restart')

print()
print('Kill current Indexer')
for line in os.popen('ps auxww | grep python | grep index_github.py | grep -v grep | grep -v ssh').readlines():
  pid = line.strip().split()[1]
  print('  kill indexJira process pid %s [%s]' % (pid, line))
  try:
    run('kill -9 %d' % int(pid))
  except:
    pass

if doReindex:
  extra = ' -reindex -delete'
else:
  extra = ''

print()
print('Start new Indexer')
os.chdir('..')
run(f'nohup {localconstants.PYTHON_EXE} -u index_github.py -server localhost:{PORT} -nrt{extra} > {localconstants.STATE_LOG_DIR}/nrt.log 2>&1 &')

print()
print('Wait 5 seconds')
time.sleep(5.0)
