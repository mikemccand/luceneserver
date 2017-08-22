#!/usr/bin/env python3

import zipfile
import re
import json
import time
import threading
import queue
import shutil
import subprocess
import multiprocessing
import sys
import os
import urllib.request

deps = [
  #('org.codehaus.jackson', 'jackson-core-asl', '1.9.13'),
  #('org.codehaus.jackson', 'jackson-mapper-asl', '1.9.13'),
  ('com.fasterxml.jackson.core', 'jackson-core', '2.8.2'),
  #('com.fasterxml.jackson.core', 'jackson-mapper', '2.8.2'),
  ('commons-codec', 'commons-codec', '1.10'),
  ('net.minidev', 'json-smart', '1.2')
  ]

testDeps = [
  ('de.thetaphi', 'forbiddenapis', '2.2'),
  ('com.carrotsearch.randomizedtesting', 'junit4-ant', '2.4.0'),
  ('com.carrotsearch.randomizedtesting', 'randomizedtesting-runner', '2.4.0'),
  ('junit', 'junit', '4.10')
  ]
  
LUCENE_VERSION = '6.3.0-SNAPSHOT'
LUCENE_SERVER_BASE_VERSION = '0.1.1'
LUCENE_SERVER_VERSION = '%s-SNAPSHOT' % LUCENE_SERVER_BASE_VERSION

luceneDeps = ('core',
              'analyzers-common',
              'analyzers-icu',
              'facet',
              'codecs',
              'grouping',
              'highlighter',
              'join',
              'misc',
              'queries',
              'queryparser',
              'suggest',
              'expressions',
              'replicator',
              'sandbox')

luceneTestDeps = ('test-framework',)

TEST_HEAP = '512m'

printLock = threading.Lock()
lastRunningPrint = None

def message(s, includeNewline=True):
  with printLock:
    if includeNewline:
      s += '\n'
    sys.stdout.write(s)
    sys.stdout.flush()

def unescape(s):
  return s.replace('%0A', '\n').replace('%09', '\t')

def addRunning(running, name):
  running[name] = time.time()
  #printRunning(running, force=True)

def removeRunning(running, name):
  del running[name]
  #printRunning(running, force=True)

def printRunning(running, force=False):
  global lastRunningPrint
  with printLock:
    now = time.time()
    if force or now - lastRunningPrint > 1.0:
      l = list(running.items())
      # Sort by longest running first:
      l.sort(key=lambda x: x[1])
      #print('%5.1fs: %s...' % (now - testsStartTime, ', '.join(['%s (%.1fs)' % (x[0], now-x[1]) for x in l])))
      print('%5.1fs: %s...' % (now - testsStartTime, ', '.join([x[0] for x in l])))
      lastRunningPrint = now

class RunTestsJVM(threading.Thread):

  def __init__(self, id, jobs, classPath, verbose, seed, doPrintOutput, testMethod, running):
    threading.Thread.__init__(self)
    self.id = id
    self.jobs = jobs
    self.classPath = classPath
    self.verbose = verbose
    self.seed = seed
    self.testMethod = testMethod
    self.testCount = 0
    self.suiteCount = 0
    self.failCount = 0
    self.doPrintOutput = doPrintOutput
    self.running = running

  def run(self):
    cmd = ['java']
    cmd.append('-Xmx%s' % TEST_HEAP)
    cmd.append('-cp')
    cmd.append(':'.join(self.classPath))

    if self.verbose:
      cmd.append('-Dtests.verbose=true')
    cmd.append('-Djava.util.logging.config=lib/logging.properties')
    cmd.append('-DtempDir=build/temp')
    if self.seed is not None:
      cmd.append('-Dtests.seed=%s' % self.seed)

    if self.testMethod is not None:
      cmd.append('-Dtests.method=%s' % self.testMethod)

    if self.verbose:
      cmd.append('-Dtests.verbose=true')

    cmd.append('-ea')
    cmd.append('-esa')
    cmd.append('com.carrotsearch.ant.tasks.junit4.slave.SlaveMainSafe')

    eventsFile = 'build/test/%d.events' % self.id
    if os.path.exists(eventsFile):
      os.remove(eventsFile)
    cmd.append('-eventsfile')
    cmd.append(eventsFile)

    cmd.append('-flush')
    cmd.append('-stdin')

    #print('COMMAND: %s' % ' '.join(cmd))

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    events = ReadEvents(p, eventsFile)
    events.waitIdle()

    while True:
      job = self.jobs.get()
      if job is None:
        break

      self.suiteCount += 1

      testSuiteName = job[25:]
      #message('%s...' % testSuiteName)
      events.testSuiteName = testSuiteName
      addRunning(self.running, testSuiteName)

      p.stdin.write((job + '\n').encode('utf-8'))
      p.stdin.flush()
      lines = []

      pendingOutput = []

      didFail = False
      testCaseFailed = False
      testCaseName = None
      
      while True:
        l = events.readline()
        l = l.rstrip()
        if l == ']':
          lines.append(l)
          #print('DECODE:\n%s' % '\n'.join(lines))
          if lines[1] == '[':
            #print('  DO LOOK')
            event = json.loads('\n'.join(lines))
            if event[0] in ('APPEND_STDOUT', 'APPEND_STDERR'):
              chunk = unescape(event[1]['chunk'])
              if testCaseFailed or self.doPrintOutput:
                chunk = fixupReproLine(chunk)
                message(chunk, False)
              else:
                pendingOutput.append(chunk)
            elif event[0] == 'TEST_FINISHED':
              if self.doPrintOutput:
                s = event[1]['description']
                s = s[s.find('#')+1:]
                s = s[:s.find('(')]
                message('\nNOTE: test case done: %.3f sec for %s\n' % (event[1]['executionTime']/1000., s))
            elif event[0] in ('TEST_FAILURE', 'SUITE_FAILURE'):
              details = event[1]
              s = '\n!! %s.%s FAILED !!:\n\n' % (job[25:], testCaseName)
              s += ''.join(pendingOutput)
              if 'message' in details:
                s += '\n%s\n' % details['message']
              s += '\n%s' % details['trace']
              message(s)
              testCaseFailed = True
              if not didFail:
                self.failCount += 1
                didFail = True
            elif event[0] == 'TEST_STARTED':
              self.testCount += 1
              testCaseFailed = False
              #testCaseName = event[1]['description']
              testCaseName = event[1]
              i = testCaseName.find('#')
              j = testCaseName.find('(')
              testCaseName = testCaseName[i+1:j]
              if self.doPrintOutput:
                message('\nNOTE: start test case %s' % testCaseName)
              events.testCaseName = testCaseName
              events.testCaseStartTime = time.time()
            elif event[0] == 'IDLE':
              break
          lines = []
        else:
          lines.append(l)
      removeRunning(self.running, testSuiteName)

    # closes stdin, which randomizedrunning detects as the end, then process cleanly shuts down with no zombie:
    p.communicate()

reReproLine = re.compile('^NOTE: reproduce with: ant test (.*?)$', re.MULTILINE)
reTestClass = re.compile('-Dtestcase=(.*?)[ $]')
reTestMethod = re.compile('-Dtests.method=(.*?)[ $]')
reTestSeed = re.compile('-Dtests.seed=(.*?)[ $]')

def fixupReproLine(s):
  """
  Replaces the 'NOTE: reproduce with: ant test -D...' with 'NOTE: reproduce with ./build.py TestFoobar.testFooBaz'
  """
  m = reReproLine.search(s)
  if m is not None:
    s2 = m.group(1)
    m2 = reTestClass.search(s2)
    if m2 is None:
      # wtf?
      return s
    testLine = m2.group(1)
    m2 = reTestMethod.search(s2)
    if m2 is not None:
      testLine += '.' + m2.group(1)
    m2 = reTestSeed.search(s2)
    if m2 is not None:
      testLine += ' -seed %s' % m2.group(1)
    # TODO: locale, asserts, file encoding
    return s[:m.start()] + ('**NOTE**: reproduce with: ./build.py %s\n' % testLine) + s[m.end():]
  else:
    # No repro line in this fragment
    return s

class ReadEvents:

  testSuiteName = None
  testCaseName = None
  testCaseStartTime = None
  nextHeartBeat = 1.0

  def __init__(self, process, fileName):
    self.process = process
    self.fileName = fileName
    while True:
      try:
        self.f = open(self.fileName, 'rb')
      except IOError:
        time.sleep(.01)
      else:
        break
    self.f.seek(0)
    
  def readline(self):
    while True:
      pos = self.f.tell()
      l = self.f.readline().decode('utf-8')
      if l == '' or not l.endswith('\n'):
        time.sleep(.01)
        now = time.time()
        if self.testCaseName is not None and now > self.testCaseStartTime + self.nextHeartBeat:
          #print('HEARTBEAT @ %.1f sec: %s.%s' % (now - self.testCaseStartTime, self.testSuiteName, self.testCaseName))
          self.nextHeartBeat += 1.0
        p = self.process.poll()
        if p is not None:
          raise RuntimeError('process exited with status %s' % str(p))
        self.f.seek(pos)
      else:
        return l

  def waitIdle(self):
    lines = []
    while True:
      l = self.readline()
      if l.find('"IDLE",') != -1:
        return lines
      else:
        lines.append(l)

def fetchMavenJAR(org, name, version, destFileName):
  url = 'http://central.maven.org/maven2/%s/%s/%s/%s-%s.jar' % (org.replace('.', '/'), name, version, name, version)
  print('Download %s -> %s...' % (url, destFileName))
  urllib.request.urlretrieve(url, destFileName)
  print('  done: %.1f KB' % (os.path.getsize(destFileName)/1024.))

def run(command):
  p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
  out, err = p.communicate()
  if p.returncode != 0:
    if len(command) < 256:
      s = str(command)
    else:
      s = str(command)[:256] + '...'
    print('\nERROR: command "%s" failed:\n%s' % (s, out.decode('utf-8')))
    raise RuntimeError('command "%s" failed' % s)

def anyChanges(srcDir, destJAR):
  if not os.path.exists(destJAR):
    return True

  t1 = os.path.getmtime(destJAR)

  for root, dirNames, fileNames in os.walk(srcDir):
    for fileName in fileNames:
      if fileName.startswith('.#'):
        # emacs silliness
        continue
      path = '%s/%s' % (root, fileName)
      if not os.path.exists(path):
        # silly corner case: if you copy over a lucene clone to another env and symlink into your .ivy2 cache breaks:
        return True
      if os.path.getmtime(path) > t1:
        return True

  return False

def compileLuceneModules(deps):
  os.chdir('lucene6x/lucene')
  for dep in deps:
    if dep.startswith('analyzers-'):
      # lucene analyzers have two level hierarchy!
      part = dep[10:]
      if anyChanges('analysis/%s' % part, 'build/analysis/%s/lucene-%s-%s.jar' % (part, dep, LUCENE_VERSION)):
        print('build lucene %s JAR...' % dep)
        os.chdir('analysis/%s' % part)
        run('ant jar')
        os.chdir('../..')
    elif anyChanges(dep, 'build/%s/lucene-%s-%s.jar' % (dep, dep, LUCENE_VERSION)):
      print('build lucene %s JAR...' % dep)
      os.chdir(dep)
      run('ant jar')
      os.chdir('..')
  os.chdir(ROOT_DIR)

def compileChangedSources(srcPath, destPath, classPath):
  changedSources = []
  for root, dirNames, fileNames in os.walk(srcPath):
    for fileName in fileNames:
      if fileName.endswith('.java') and not fileName.startswith('.#'):
        classFileName = 'build/classes/%s.class' % ('%s/%s' % (root, fileName))[4:-5]
        if not os.path.exists(classFileName) or os.path.getmtime(classFileName) < os.path.getmtime('%s/%s' % (root, fileName)):
          changedSources.append('%s/%s' % (root, fileName))

  if len(changedSources) > 0:
    cmd = ['javac', '-Xmaxerrs', '10000', '-d', destPath]
    cmd.append('-cp')
    cmd.append(':'.join(classPath))
    cmd.extend(changedSources)
    if False:
      print('compile sources:')
      for fileName in changedSources:
        print('  %s' % fileName)
    else:
      print('compile %d sources' % len(changedSources))
    run(' '.join(cmd))

def getCompileClassPath():
  l = []
  for org, name, version in deps:
    l.append('lib/%s-%s.jar' % (name, version))
  for dep in luceneDeps:
    if dep.startswith('analyzers-'):
      l.append('lucene6x/lucene/build/analysis/%s/lucene-%s-%s.jar' % (dep[10:], dep, LUCENE_VERSION))
      libDir = 'lucene6x/lucene/analysis/%s/lib' % dep[10:]
    else:
      l.append('lucene6x/lucene/build/%s/lucene-%s-%s.jar' % (dep, dep, LUCENE_VERSION))
      libDir = 'lucene6x/lucene/%s/lib' % dep
    if os.path.exists(libDir):
      l.append('%s/*' % libDir)
    
  return l

def getTestClassPath():
  l = getCompileClassPath()
  l.append('build/classes/java')
  for org, name, version in testDeps:
    l.append('lib/%s-%s.jar' % (name, version))
  for dep in luceneTestDeps:
    if dep.startswith('analyzers-'):
      l.append('lucene6x/lucene/build/analysis/%s/lucene-%s-%s.jar' % (dep[10:], dep, LUCENE_VERSION))
    else:
      l.append('lucene6x/lucene/build/%s/lucene-%s-%s.jar' % (dep, dep, LUCENE_VERSION))
  return l

def getArg(option):
  if option in sys.argv:
    i = sys.argv.index(option)
    if i + 2 > len(sys.argv):
      raise RuntimeError('command line option %s requires an argument' % option)
    value = sys.argv[i+1]
    del sys.argv[i:i+2]
    return value
  else:
    return None

def getFlag(option):
  if option in sys.argv:
    sys.argv.remove(option)
    return True
  else:
    return False

def compileSourcesAndDeps(jarVersion):
  if not os.path.exists('lib'):
    print('init: create ./lib directory...')
    os.makedirs('lib')

  if not os.path.exists('build'):
    os.makedirs('build/classes/java')
    os.makedirs('build/classes/test')

  for dep in deps:
    destFileName = 'lib/%s-%s.jar' % (dep[1], dep[2])
    if not os.path.exists(destFileName):
      fetchMavenJAR(*(dep + (destFileName,)))

  if not os.path.exists('lucene6x'):
    print('init: cloning lucene branch_6x to ./lucene6x...')
    run('git clone -b branch_6_3 https://github.com/apache/lucene-solr.git lucene6x')

  compileLuceneModules(luceneDeps)

  # compile luceneserver sources
  jarFileName = 'build/luceneserver-%s.jar' % jarVersion

  l = getCompileClassPath()
  l.append('build/classes/java')
  compileChangedSources('src/java', 'build/classes/java', l)

  if anyChanges('build/classes/java', jarFileName):
    print('build %s' % jarFileName)
    gitHash = os.popen('git rev-parse --short HEAD').readline().strip()
    modifiedFileCount = 0
    with os.popen('git ls-files -m') as p:
      while True:
        line = p.readline()
        if line == '':
          break
        modifiedFileCount += 1
        
    with open('build/manifest.mf', 'w') as f:
      f.write('Extension-Name: org.apache.lucene.server\n')
      f.write('Specification-Title: Thin HTTP/REST server wrapper for Apache Lucene\n')
      f.write('Specification-Vendor: Mike McCandless\n')
      f.write('Specification-Version: %s\n' % LUCENE_SERVER_BASE_VERSION)
      f.write('Implementation-Title: org.apache.lucene.server\n')
      f.write('Implementation-Vendor: Mike McCandless\n')
      if modifiedFileCount > 0:
        if '-SNAPSHOT' not in jarVersion:
          raise RuntimeError('there are modified sources; cannot build releasable JAR')
        f.write('Implementation-Version: %s %s; %d source files modified\n' % (jarVersion, gitHash, modifiedFileCount))
      else:
        f.write('Implementation-Version: %s %s\n' % (jarVersion, gitHash))
      
    run('jar cefm org.apache.lucene.server.Server %s build/manifest.mf -C build/classes/java  .' % jarFileName)

  return jarFileName

def main():
  global testsStartTime, lastRunningPrint
  
  global ROOT_DIR
  ROOT_DIR = os.getcwd()
  upto = 1
  while upto < len(sys.argv):
    what = sys.argv[upto]
    upto += 1
    
    if what == 'clean':
      print('cleaning...')
      if os.path.exists('build'):
        shutil.rmtree('build')
    elif what == 'cleanlucene':
      os.chdir('lucene6x')
      run('ant clean')
      os.chdir(ROOT_DIR)
    elif what == 'forbidden':
      jarVersion = getArg('-version')
      if jarVersion is None:
        jarVersion = LUCENE_SERVER_VERSION
      jarFileName = compileSourcesAndDeps(jarVersion)
      testCP = getTestClassPath()
      testCP.append('build/classes/test')
      testCP.append(jarFileName)
      compileChangedSources('src/test', 'build/classes/test', testCP)
      cmd = "java -jar lib/forbiddenapis-2.2.jar -c '%s' -d build/classes -b jdk-system-out -b jdk-non-portable -b jdk-reflection -b jdk-unsafe-1.8 -b jdk-deprecated-1.8 -b jdk-internal-1.8" % (':'.join(getTestClassPath()))
      print('cmd %s' % cmd)
      run(cmd)

    elif what == 'package':

      jarVersion = getArg('-version')
      if jarVersion is None:
        jarVersion = LUCENE_SERVER_VERSION
      
      jarFileName = compileSourcesAndDeps(jarVersion)

      destFileName = 'build/luceneserver-%s.zip' % jarVersion
      rootDirName = 'luceneserver-%s' % jarVersion

      with zipfile.ZipFile(destFileName, 'w') as z:
        z.write(jarFileName, '%s/lib/luceneserver-%s.jar' % (rootDirName, jarVersion))
        for org, name, version in deps:
          z.write('lib/%s-%s.jar' % (name, version), '%s/lib/%s-%s.jar' % (rootDirName, name, version))
        for dep in luceneDeps:
          if dep.startswith('analyzers-'):
            z.write('lucene6x/lucene/build/analysis/%s/lucene-%s-%s.jar' % (dep[10:], dep, LUCENE_VERSION), '%s/lib/lucene-%s-%s.jar' % (rootDirName, dep, LUCENE_VERSION))
            libDir = 'lucene6x/lucene/analysis/%s/lib' % dep[10:]
          else:
            z.write('lucene6x/lucene/build/%s/lucene-%s-%s.jar' % (dep, dep, LUCENE_VERSION), '%s/lib/lucene-%s-%s.jar' % (rootDirName, dep, LUCENE_VERSION))
            libDir = 'lucene6x/lucene/%s/lib' % dep
          if os.path.exists(libDir):
            for name in os.listdir(libDir):
              z.write('%s/%s' % (libDir, name), '%s/lib/%s' % (rootDirName, name))
        z.write('scripts/indexTaxis.py', '%s/scripts/indexTaxis.py' % rootDirName)
        z.write('CHANGES.txt', '%s/CHANGES.txt' % rootDirName)
        z.write('README.md', '%s/README.md' % rootDirName)

        print('\nWrote %s (%.1f MB)\n' % (destFileName, os.path.getsize(destFileName)/1024./1024.))

    elif what == 'test' or what.startswith('Test'):

      if what.startswith('Test'):
        upto -= 1

      seed = getArg('-seed')
      verbose = getFlag('-verbose')

      jarFileName = compileSourcesAndDeps(LUCENE_SERVER_VERSION)

      compileLuceneModules(luceneTestDeps)

      for dep in testDeps:
        destFileName = 'lib/%s-%s.jar' % (dep[1], dep[2])
        if not os.path.exists(destFileName):
          fetchMavenJAR(*(dep + (destFileName,)))

      testCP = getTestClassPath()
      testCP.append('build/classes/test')
      testCP.append(jarFileName)
      compileChangedSources('src/test', 'build/classes/test', testCP)
      for extraFile in ('MockPlugin-hello.txt', 'MockPlugin-lucene-server-plugin.properties'):
        if not os.path.exists('build/classes/test/org/apache/lucene/server/%s' % extraFile):
          shutil.copy('src/test/org/apache/lucene/server/%s' % extraFile,
                      'build/classes/test/org/apache/lucene/server/%s' % extraFile)

      if upto == len(sys.argv):
        # Run all tests
        testSubString = None
        testMethod = None
      elif upto == len(sys.argv)-1:
        testSubString = sys.argv[upto]
        if testSubString != 'package':
          if '.' in testSubString:
            parts = testSubString.split('.')
            if len(parts) != 2:
              raise RuntimeError('test fragment should be either TestFoo or TessFoo.testMethod')
            testSubString = parts[0]
            testMethod = parts[1]
          else:
            testMethod = None
          upto += 1
        else:
          testSubString = None
          testMethod = None
      else:
        raise RuntimeError('at most one test substring can be specified')

      testClasses = []
      for root, dirNames, fileNames in os.walk('build/classes/test'):
        for fileName in fileNames:
          if fileName.startswith('Test') and fileName.endswith('.class') and '$' not in fileName:
            fullPath = '%s/%s' % (root, fileName)
            if testSubString is None or testSubString in fullPath:
              className = fullPath[19:-6].replace('/', '.')
              if testSubString is not None and len(testClasses) == 1:
                raise RuntimeError('test name fragment "%s" is ambiguous, matching at least %s and %s' % (testSubString, testClasses[0], className))
              testClasses.append(className)

      # TODO: generalize this silliness
      # Get these slow tests to run first:
      for testCase in ('TestIndexing', 'TestReplication', 'TestServer'):
        s = 'org.apache.lucene.server.' + testCase
        if s in testClasses:
          testClasses.remove(s)
          testClasses = [s] + testClasses

      if len(testClasses) == 0:
        if testSubString is None:
          raise RuntimeError('no tests found (wtf?)')
        else:
          raise RuntimeError('no tests match substring "%s"' % testSubString)

      # TODO: also detect if no tests matched the tests.method!

      jvmCount = min(multiprocessing.cpu_count(), len(testClasses))

      if testSubString is not None:
        if testMethod is not None:
          print('Running test %s, method %s' % (testClasses[0], testMethod))
        else:
          print('Running test %s' % testClasses[0])
        printOutput = True
      else:
        print('Running %d tests in %d JVMs' % (len(testClasses), jvmCount))
        printOutput = False

      if not os.path.exists('build/test'):
        os.makedirs('build/test')

      t0 = time.time()
      jobs = queue.Queue()

      running = {}
      lastRunningPrint = time.time()
      testsStartTime = time.time()

      jvms = []
      for i in range(jvmCount):
        jvm = RunTestsJVM(i, jobs, testCP, verbose, seed, printOutput, testMethod=testMethod, running=running)
        jvm.start()
        jvms.append(jvm)

      for s in testClasses:
        jobs.put(s)

      for i in range(jvmCount):
        jobs.put(None)

      failCount = 0
      testCount = 0
      suiteCount = 0
      while True:
        for jvm in jvms:
          if jvm.isAlive():
            break
        else:
          break
        time.sleep(0.1)
        printRunning(running)

      for jvm in jvms:
        failCount += jvm.failCount
        testCount += jvm.testCount
        suiteCount += jvm.suiteCount

      totalSec = time.time() - t0
      
      if failCount > 0:
        print('\nFAILURE [%d of %d test cases in %d suites failed in %.1f sec]' % (failCount, testCount, suiteCount, totalSec))
        sys.exit(1)
      elif testCount == 0:
        print('\nFAILURE: no tests ran!')
      else:
        print('\nSUCCESS [%d test cases in %d suites in %.1f sec]' % (testCount, suiteCount, totalSec))
        sys.exit(0)
      
    else:
      raise RuntimeError('unknown target %s' % what)
      
if __name__ == '__main__':
  if len(sys.argv) == 1:
    print('''
    Usage:

      ./build.py clean

        Removes all artifacts.

      ./build.py test

        Runs all tests.

      ./build.py package

        Build install zip to build/luceneserver-VERSION.zip

      ./build.py TestFoo[.testBar]

        Runs a single test class and optionally method.

    You can also combine them, e.g. "clean test package".
     ''')
    sys.exit(1)
    
  main()
