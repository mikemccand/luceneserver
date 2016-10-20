import threading
import os
import time
import server
import shutil
import subprocess
import sys
import datetime
import signal

import localconstants

LUCENE_SERVER_VERSION = localconstants.LUCENE_SERVER_VERSION
isDev = localconstants.isDev

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
    if l.find('listening on port %s' % port) != -1:
      startupEvent.set()
    if eachLine is None:
      print('SVR: %s' % l.rstrip())
    else:
      eachLine(l.rstrip())

def getClassPath():
  cp = []
  seen = set()
  if localconstants.serverBuildDir is not None:
    for module in ('core', 'highlighter',
                   'expressions', 'facet',
                   'server', 'grouping',
                   'join', 'queries',
                   'queryparser', 'suggest',
                   'analysis/common', 'analysis/icu',
                   'misc'):
      if module.startswith('analysis/'):
        module2 = module.replace('analysis/', 'analyzers-')
      else:
        module2 = module
      cp.append('%s/%s/lucene-%s-%s.jar' % (localconstants.serverBuildDir, module, module2, LUCENE_SERVER_VERSION))

      path = '%s/../%s/lib' % (localconstants.serverBuildDir, module)
      if os.path.exists(path):
        for fileName in os.listdir(path):
          if fileName.endswith('.jar'):
            if fileName not in seen:
              seen.add(fileName)
              cp.append('%s/../%s/lib/%s' % (localconstants.serverBuildDir, module, fileName))
  else:
    for fileName in os.listdir('server'):
      if fileName.endswith('.jar'):
        cp.append('server/%s' % fileName)
  return cp

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

    cp = getClassPath()
      
    HEAP = localconstants.HEAP
    print('CP: %s' % cp)

    # -agentlib:yjpagent=sampling,disablej2ee
    env = {'CLASSPATH': ':'.join(cp)}
    #cmd = '%s -XX:+UseCompressedOops -XX:MaxPermSize=60m -XX:+HeapDumpOnOutOfMemoryError -verbose:gc -ea:org.apache.lucene... -Xmx%s org.apache.lucene.server.Server -port %s -stateDir %s' % (localconstants.JAVA_EXE, HEAP, port, localconstants.rootPath)
    cmd = '%s -Xms%s -Xmx%s org.apache.lucene.server.Server -port %s -stateDir %s' % (localconstants.JAVA_EXE, HEAP, HEAP, port, localconstants.rootPath)

    print('SERVER CMD: %s' % cmd)

    self.p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

    t = threading.Thread(target=readServerOutput, args=(self.p, port, startupEvent, failureEvent, eachLine))
    t.setDaemon(True)
    t.start()

    startupEvent.wait()
    if failureEvent.isSet():
      sys.exit(0)

  def isAlive(self):
    return self.p.poll() is None

  def killServer(self):
    # nocommit
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
    svr = RunServer(localconstants.SERVER_PORT, localconstants.rootPath)

    try:
      while True:
        time.sleep(.2)
        if not svr.isAlive():
          print('NOT ALIVE')
          break
    finally:
      svr.killServer()

    time.sleep(1)

