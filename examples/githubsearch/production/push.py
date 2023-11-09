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

import traceback
import sys
import time
import urllib.request, urllib.error, urllib.parse
import os
import shutil
import signal
import runServer

sys.path.insert(0, '..')
import localconstants

def run(cmd):
  if os.system(cmd):
    raise RuntimeError('%s failed; cwd=%s' % (cmd, os.getcwd()))

if len(sys.argv) == 1:
  doServer = True
  doUI = True
  doReindex = False
else:
  doServer = False
  doUI = False
  doReindex = False

  for arg in sys.argv[1:]:
    if arg == '-ui':
      doUI = True
    elif arg == '-server':
      doServer = True
    elif arg == '-reindex':
      doReindex = True
    else:
      raise RuntimeError('unknown arg %s' % arg)

userHost = 'changingbits@web504.webfaction.com'
#userHost = 'mike@10.17.4.12'
sshIdent = ''
#sshIdent = '-i /home/mike/.ssh/aws_changingbits.pem'

print()
print('Snapshot')
run('ssh -t %s %s "cd src/ui/production; python3 -u snapshot.py"' % (sshIdent, userHost))

if doServer:
  serverDistPath = '/l/luceneserver/build/luceneserver-%s.zip' % localconstants.LUCENE_SERVER_VERSION
  print()
  print('Copy %s' % serverDistPath)
  run('scp %s %s %s:src/ui' % (sshIdent, serverDistPath, userHost))
  run('ssh %s %s "cd src/ui; rm -rf luceneserver; unzip luceneserver-%s.zip; mv luceneserver-%s luceneserver; rm luceneserver-%s.zip"' % (sshIdent, userHost, localconstants.LUCENE_SERVER_VERSION, localconstants.LUCENE_SERVER_VERSION, localconstants.LUCENE_SERVER_VERSION))

if doUI:
  print('Push UI/indexing scripts')
  run('scp %s -r ../gitHistory.py ../handle.py ../indexJira.py ../Latin-dont-break-issues.rbbi ../server.py ../moreFacets.py ../search.py ../static ../production ../suggest.py ../util.py %s:src/ui' % (sshIdent, userHost))

if doReindex:
  extra = ' -reindex'
else:
  extra = ''
run('ssh -t %s %s "cd src/ui/production; python3 -u restart.py%s"' % (sshIdent, userHost, extra))

print()
print('Verify')
while True:
  try:
    s = urllib.request.urlopen('http://jirasearch.mikemccandless.com/search.py').read().decode('utf-8')
  except:
    print()
    print('Failed to load search.py... will retry:')
    traceback.print_exc()
  else:
    if s.find('<b>Updated</b>') != -1:
      print('  success!')
      break
    elif s.find('isn\'t started: cannot search'):
      time.sleep(0.5)
    else:
      print('GOT %s' % s)
      raise RuntimeError('server is not working?')
