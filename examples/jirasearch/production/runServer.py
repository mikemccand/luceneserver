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

import threading
import os
import time
import shutil
import subprocess
import sys
import datetime
import signal

sys.path.insert(0, '..')

import localconstants

"""
Python wrapper that spawns the Java lucene server process and restarts it if it dies.
"""

LUCENE_SERVER_VERSION = localconstants.LUCENE_SERVER_VERSION

def readServerOutput(p, port, startupEvent, failureEvent, eachLine):
  while True:
    l = p.stdout.readline().decode('utf-8')
    if l == '':
      if not startupEvent.isSet():
        failureEvent.set()
        startupEvent.set()
        raise RuntimeError('Server failed to start')
      else:
        break
    if 'listening on' in l:
      startupEvent.set()
    if eachLine is None:
      print('SVR: %s' % l.rstrip())
    else:
      eachLine(l.rstrip())

class RunServer:

  """
  Spawns java subprocess to run the Lucene server.
  """

  def __init__(self, port, path, eachLine=None):
    self.port = port
    startupEvent = threading.Event()
    failureEvent = threading.Event()

    #VERSION = '4.2.0-ALPHA'
    #VERSION = '4.2-SNAPSHOT'

    HEAP = localconstants.HEAP

    # -agentlib:yjpagent=sampling,disablej2ee
    cmd = '%s -Xms%s -Xmx%s -Xss228k -cp "../luceneserver/lib/*" org.apache.lucene.server.Server -maxHTTPThreadCount 2 -ipPort localhost:%s -stateDir %s' % (localconstants.JAVA_EXE, HEAP, HEAP, port, localconstants.ROOT_INDICES_PATH)

    print('SERVER CMD: %s' % cmd)

    self.p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    t = threading.Thread(target=readServerOutput, args=(self.p, port, startupEvent, failureEvent, eachLine))
    t.setDaemon(True)
    t.start()

    startupEvent.wait()
    if failureEvent.isSet():
      sys.exit(0)

  def isAlive(self):
    return self.p.poll() is None

  def killServer(self):
    try:
      self.send('shutdown', {})
    except:
      pass
    print('Find server pid to kill...')
    for line in os.popen('ps auxww | grep java | grep server.Server | grep "port %s" | grep -v grep' % self.port).readlines():
      pid = line.strip().split()[1]
      print('Kill server pid %s' % pid)
      try:
        os.kill(int(pid), signal.SIGKILL)
      except:
        pass

if __name__ == '__main__':

  while True:
    print()
    print('%s: START SERVER' % datetime.datetime.now())
    svr = RunServer(localconstants.SERVER_PORT, localconstants.ROOT_INDICES_PATH)
    
    try:
      while True:
        time.sleep(.2)
        if not svr.isAlive():
          print('NOT ALIVE')
          break
    finally:
      svr.killServer()

    time.sleep(1)

