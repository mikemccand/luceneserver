import pprint
import random
import gzip
import socket
import struct
import time
import sys
import json
import os
import subprocess
import threading
import http.client
import getpass
import urllib.request
import urllib.parse

LUCENE_SERVER_BASE_VERSION = '0.1.1'

#JVM_OPTIONS = '-XX:+AlwaysPreTouch -Xms2g -Xmx2g'
JVM_OPTIONS = '-Xms2g -Xmx2g'

# killall java; ssh 10.17.4.12 killall java; rm -rf /c/taxis; ssh 10.17.4.12 "rm -rf /l/taxis"; python3 -u scripts/indexTaxis.py -rebuild -ip 10.17.4.92 -installPath /c/taxis -replica 10.17.4.12:/l/taxis

# TODO
#   - index lat/lon as geopoint!

LOCALHOST = '127.0.0.1'

IS_INSTALLED = os.path.exists('lib/luceneserver-%s.jar' % LUCENE_SERVER_BASE_VERSION) or \
               os.path.exists('lib/luceneserver-%s-SNAPSHOT.jar' % LUCENE_SERVER_BASE_VERSION)

DEFAULT_PORT = 4000

PACKAGE_FILE = os.path.abspath('build/luceneserver-%s-SNAPSHOT.zip' % LUCENE_SERVER_BASE_VERSION)

USER_NAME = getpass.getuser()

BINARY_CSV = True

USE_JSON = False

class BinarySend:
  def __init__(self, host, port, command):
    self.socket = socket.socket()
    self.socket.connect((host, port))
    # BINARY_MAGIC header:
    self.socket.sendall(struct.pack('>i', 0x3414f5c))
    command = 'bulkCSVAddDocument'.encode('utf-8')
    self.socket.sendall(('%c' % len(command)).encode('utf-8'))
    self.socket.sendall(command)

  def add(self, bytes):
    self.socket.sendall(bytes)

  def finish(self):
    self.socket.shutdown(socket.SHUT_WR)

  def close(self):
    self.socket.close()

class ChunkedHTTPSend:
  def __init__(self, host, port, command, args):
    self.conn = http.client.HTTPConnection(host, port)
    url = '/%s' % command
    if len(args) > 0:
      url += '?%s' % urllib.parse.urlencode(args)
    print('URL: %s' % url)
    self.conn.putrequest('POST', url)
    self.conn.putheader('Transfer-Encoding', 'chunked')
    self.conn.endheaders()

  def add(self, data):
    self.conn.send(("%s\r\n" % hex(len(data))[2:]).encode('UTF-8'))
    self.conn.send(data)
    self.conn.send('\r\n'.encode('UTF-8'))

  def finish(self):
    r = self.conn.getresponse()
    s = r.read()
    if r.status != 200:
      raise RuntimeError('FAILED:\n%s' % s.decode('utf-8'))
    else:
      return s.decode('utf-8')
    self.conn.close()

def launchServer(host, installDir, port, ip=None):

  if IS_INSTALLED:
    cwd = '.'
  else:

    zipFileName = os.path.split(PACKAGE_FILE)[1]
    # copy install bits over
    if host != LOCALHOST:
      run('scp %s %s@%s:/tmp' % (PACKAGE_FILE, USER_NAME, host))
      # unzip it
      run('ssh %s@%s "mkdir -p %s; cd %s; unzip /tmp/%s"' % (USER_NAME, host, installDir, installDir, zipFileName))
    else:
      os.makedirs(installDir)
      run('cd %s; unzip %s' % (installDir, PACKAGE_FILE))

    serverDirName = zipFileName[:-4]
    cwd = '%s/%s' % (installDir, serverDirName)

  if host != LOCALHOST:
    command = r'ssh %s@%s "cd %s; java %s -cp lib/\* org.apache.lucene.server.Server -stateDir %s/state -ipPort %s:%s"' % (USER_NAME, host, cwd, JVM_OPTIONS, installDir, host, port)
  else:
    #command = r'cd %s; java -XX:MaxInlineSize=0 -agentlib:yjpagent=sampling -Xms4g -Xmx4g -cp lib/\* org.apache.lucene.server.Server -stateDir %s/state -ipPort %s:%s' % (cwd, installDir, host, port)
    command = r'cd %s; java %s -cp lib/\* org.apache.lucene.server.Server -stateDir %s/state -ipPort %s:%s' % (cwd, JVM_OPTIONS, installDir, host, port)

  if ip is not None:
    command += ' -ipPort %s:%s' % (ip, port)

  print('%s: server command %s' % (host, command))
  p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

  # Read lines until we see the server is started, then launch bg thread to read future lines:
  pending = []
  while True:
    line = p.stdout.readline()
    line = line.decode('utf-8')
    if line == '':
      print('ERROR: server on %s fail to start:' % host)
      print('\n'.join(pending))
      raise RuntimeError('server on %s failed to start' % host)
    print('%s: %s' % (host, line))
    pending.append(line)

    if 'node main: listening on' in line:
      line = p.stdout.readline().strip().decode('utf-8')
      i = line.find(':')
      print('%s: %s' % (host, line))
      ports = list(int(x) for x in line[i+1:].split('/'))
      break
    
  thread = threading.Thread(target=readServerOutput, args=(host, p))
  thread.start()
  return ports

def readServerOutput(host, p):
  while True:
    line = p.stdout.readline()
    if line == b'':
      break
    print('%s: %s' % (host, line.decode('utf-8').rstrip()))

def send(host, port, command, args):
  args = json.dumps(args).encode('utf-8')
  h = http.client.HTTPConnection(host, port)
  h.request('POST', '/%s' % command, args, {'Content-Length': str(len(args))})
  r = h.getresponse()
  s = r.read()
  if r.status != 200:
    raise RuntimeError('FAILED: %s:%s:\n%s' % (host, port, s.decode('utf-8')))
    
  return s.decode('utf-8')

def run(command, logFile = None):
  if logFile is not None:
    command += ' > %s 2>&1' % logFile
  print('\nRUN: %s' % command)
  result = subprocess.call(command, shell=True)
  if result != 0:
    if logFile is not None:
      print(open(logFile).read())
    raise RuntimeError('command failed with result %s: %s' % (result, command))

def rmDir(host, path):
  if host == LOCALHOST:
    run('rm -rf %s' % path)
  else:
    run('ssh %s rm -rf %s' % (host, path))

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

def main():

  if not os.path.exists('src/java/org/apache/lucene/server/Server.java') and not IS_INSTALLED:
    print('\nERROR: please run this from the luceneserver working directory (git clone) or an installation\n')
    sys.exit(1)

  if IS_INSTALLED:
    if getFlag('-rebuild'):
      raise RuntimeError('cannot rebuild from a binary installation')
    primaryInstallPath = '.'
  elif getFlag('-rebuild') or not os.path.exists('build/luceneserver-%s-SNAPSHOT.zip' % LUCENE_SERVER_BASE_VERSION):
    print('Building server release artifact...')
    run('python3 -u build.py package')

  primaryInstallPath = getArg('-installPath')
  if primaryInstallPath is None:
    primaryInstallPath = os.path.abspath('install')

  if os.path.exists(primaryInstallPath):
    raise RuntimeError('primary install path %s already exists; please remove it and rerun' % primaryInstallPath)

  os.makedirs(primaryInstallPath)

  replicas = []
  primaryIP = getArg('-ip')
  
  while True:
    s = getArg('-replica')
    if s is not None:
      if IS_INSTALLED:
        raise RuntimeError('-replica does not yet work when installed; try running from a git clone instead')
      if primaryIP is None:
        raise RuntimeError('you must specify -ip if there are any -replica')
      tup = s.split(':')
      if len(tup) == 2:
        replicas.append((tup[0], DEFAULT_PORT, tup[1]))
      elif len(tup) == 3:
        replicas.append((tup[0], int(tup[2]), tup[1]))
      else:
        raise RuntimeError('-replica should be host:installPath or host:port:installPath')
    else:
      break

  for host, port, installPath in replicas:
    s = os.popen('ssh %s@%s ls %s 2>&1' % (USER_NAME, host, installPath)).read()
    if 'no such file or directory' not in s.lower():
      raise RuntimeError('path %s on replica %s already exists; please remove it and rerun' % (installPath, host))
    
  for host, port, path in replicas:
    print('mkdir %s on %s' % (path, host))
    run('ssh %s@%s mkdir -p %s' % (USER_NAME, host, path))

  primaryPorts = launchServer(LOCALHOST, '%s/server0' % primaryInstallPath, 4000, primaryIP)
  if len(replicas) != 0:
    print('Done launch primary')

  replicaPorts = []
  for i, (host, port, installPath) in enumerate(replicas):
    replicaPorts.append((i+1, host, installPath) + tuple(launchServer(host, '%s/server%s' % (installPath, i+1), port)))

  if len(replicas) != 0:
    print('Done launch replicas')

  try:
    send(LOCALHOST, primaryPorts[0], 'createIndex', {'indexName': 'index', 'rootDir': '%s/server0/index' % primaryInstallPath})
    for id, host, installPath, port, binaryPort in replicaPorts:
      send(host, port, 'createIndex', {'indexName': 'index', 'rootDir': '%s/server%s/index' % (installPath, id)})

    if len(replicaPorts) > 0:
      refreshSec = 1.0
    else:
      refreshSec = 5.0
    send(LOCALHOST, primaryPorts[0], "liveSettings", {'indexName': 'index', 'index.ramBufferSizeMB': 256., 'maxRefreshSec': refreshSec})

    fields = {'indexName': 'index',
              'fields':
              {
                'vendor_id': {'type': 'atom', 'sort': True},
                'vendor_name': {'type': 'text'},
                'cab_color': {'type': 'atom', 'sort': True},
                'pick_up_date_time': {'type': 'long', 'search': True, 'sort': True},
                'drop_off_date_time': {'type': 'long', 'search': True, 'sort': True},
                'passenger_count': {'type': 'int', 'search': True, 'sort': True},
                'trip_distance': {'type': 'float', 'search': True, 'sort': True},
                'pick_up_lat': {'type': 'float', 'search': True, 'sort': True},
                'pick_up_lon': {'type': 'float', 'search': True, 'sort': True},
                'drop_off_lat': {'type': 'float', 'search': True, 'sort': True},
                'drop_off_lon': {'type': 'float', 'search': True, 'sort': True},
                'payment_type': {'type': 'atom', 'sort': True},
                'trip_type': {'type': 'atom', 'sort': True},
                'rate_code': {'type': 'atom', 'sort': True},
                'fare_amount': {'type': 'float', 'search': True, 'sort': True},
                'surcharge': {'type': 'float', 'search': True, 'sort': True},
                'mta_tax': {'type': 'float', 'search': True, 'sort': True},
                'extra': {'type': 'float', 'search': True, 'sort': True},
                'ehail_fee': {'type': 'float', 'search': True, 'sort': True},
                'improvement_surcharge': {'type': 'float', 'search': True, 'sort': True},
                'tip_amount': {'type': 'float', 'search': True, 'sort': True},
                'tolls_amount': {'type': 'float', 'search': True, 'sort': True},
                'total_amount': {'type': 'float', 'search': True, 'sort': True},
                'store_and_fwd_flag': {'type': 'atom', 'sort': True}}}

    send(LOCALHOST, primaryPorts[0], 'registerFields', fields)
    for id, host, installPath, port, binaryPort in replicaPorts:
      send(host, port, 'registerFields', fields)

    send(LOCALHOST, primaryPorts[0], "settings", {'indexName': 'index',
                                    #'indexSort': [{'field': 'pick_up_lon'}],
                                    'index.verbose': False,
                                    'directory': 'MMapDirectory',
                                    'nrtCachingDirectory.maxSizeMB': 0.0,
                                    'index.merge.scheduler.auto_throttle': False,
                                    'concurrentMergeScheduler.maxMergeCount': 16,
                                    'concurrentMergeScheduler.maxThreadCount': 8,
                                    })

    for id, host, installPath, port, binaryPort in replicaPorts:
      send(host, port, "settings", {'indexName': 'index',
                                    'directory': 'MMapDirectory',
                                    'nrtCachingDirectory.maxSizeMB': 0.0
                                    })

    if len(replicas) > 0:
      send(LOCALHOST, primaryPorts[0], 'startIndex', {'indexName': 'index', 'mode': 'primary', 'primaryGen': 0})
      for id, host2, installPath, port2, binaryPort2 in replicaPorts:
        send(host2, port2, 'startIndex', {'indexName': 'index', 'mode': 'replica', 'primaryAddress': primaryIP, 'primaryGen': 0, 'primaryPort': primaryPorts[1]})
    else:
      send(LOCALHOST, primaryPorts[0], 'startIndex', {'indexName': 'index'})

    id = 0
    tStart = time.time()
    nextPrint = 250000
    replicaStarted = False

    if USE_JSON:
      docSource = '/b/alltaxis.luceneserver.json'
    else:
      #docSource = '/lucenedata/nyc-taxi-data/alltaxis.csv.blocks'
      docSource = '/b/alltaxis.csv.blocks'
      #docSource = '/l/data/alltaxis.csv.blocks'
    if not os.path.exists(docSource):
      # Not Mike's home computer!
      docSource = 'data/alltaxis.1M.csv.blocks'
      if not os.path.exists(docSource):
        if not os.path.exists('data'):
          os.makedirs('data')
        url = 'https://www.dropbox.com/s/dwglqya3rjlborf/alltaxis.1M.csv.blocks.gz?dl=1'
        print('Downloading and decompressing first 1M NYC taxi documents from %s to %s...' % (url, docSource))
        with open(docSource, 'wb') as fOut, gzip.open(urllib.request.urlopen(url)) as fIn:
          netBytes = 0
          nextPrint = 5*1024*1024
          while True:
            b = fIn.read(16384)
            if b == b'':
              break
            fOut.write(b)
            netBytes += len(b)
            if netBytes > nextPrint:
              print('  %.1f MB of 154.0 MB...' % (netBytes/1024./1024.))
              nextPrint += 5*1024*1024
        print('  done: %.1f MB' % (os.path.getsize(docSource)/1024./1024.))

    #with open('/lucenedata/nyc-taxi-data/alltaxis.csv.blocks', 'rb') as f:
    totBytes = 0

    doSearch = len(replicaPorts) > 0

    dps = getArg('-dps')
    if dps is not None:
      dps = float(dps)

    if USE_JSON:
      c = ChunkedHTTPSend(LOCALHOST, primaryPorts[0], 'bulkAddDocument2', {'indexName': 'index'})
    elif BINARY_CSV:
      b1 = BinarySend(LOCALHOST, primaryPorts[1], 'bulkCSVAddDocument')
      b1.add(b',index\n')
    else:
      # nocommit why no errors detected with \t not ,?
      c = ChunkedHTTPSend(LOCALHOST, primaryPorts[0], 'bulkCSVAddDocument2', {'indexName': 'index', 'delimChar': ','})

    with open(docSource, 'rb') as f:
      if USE_JSON:
        pass
      else:
        csvHeader = f.readline()
        if BINARY_CSV:      
          b1.add(csvHeader)
        else:
          c.add(csvHeader)

      while True:
        if USE_JSON:
          b = f.read(8)
          if len(b) == 0:
            break
          docCount, byteCount = struct.unpack('ii', b)
          totBytes += byteCount
          #print('docCount %s, byteCount %s' % (docCount, byteCount))
          bytes = f.read(byteCount)
          try:
            c.add(bytes)
          except:
            print('FAILED:')
            print(c.finish())
            raise
        else:
          header = f.readline()
          if len(header) == 0:
            break
          byteCount, docCount = (int(x) for x in header.strip().split())
          bytes = f.read(byteCount)
          totBytes += byteCount
          if BINARY_CSV:      
            b1.add(bytes)
          else:
            try:
              c.add(bytes)
            except:
              print('FAILED:')
              print(c.finish())
              raise
        #print('doc: %s' % doc)
        id += docCount
        if id >= nextPrint:
          delay = time.time()-tStart
          dps = id / delay
          if doSearch:
            replica = random.choice(replicaPorts)
            x = json.loads(send(replica[1], replica[3], 'search', {'indexName': 'index', 'queryText': '*:*'}));
            print('%6.1f sec: %.2fM hits on replica, %.2f M docs... %.1f docs/sec, %.1f MB/sec' % (delay, x['totalHits']/1000000., id/1000000., dps, (totBytes/1024./1024.)/delay))
          else:
            print('%6.1f sec: %.2f M docs... %.1f docs/sec, %.1f MB/sec' % (delay, id/1000000., dps, (totBytes/1024./1024.)/delay))
          result = json.loads(send(LOCALHOST, primaryPorts[0], 'stats', {'indexName': 'index'}))
          print(json.dumps(result, sort_keys=True, indent=4))
          x = json.loads(send(LOCALHOST, primaryPorts[0], 'search2', {'indexNames': ['index'], 'queryText': '*:*'}));
          print('%d hits...' % x['totalHits'])
          while nextPrint <= id:
            nextPrint += 250000

        if dps is not None:
          now = time.time()
          expected = tStart + (id / dps)
          if expected > now:
            time.sleep(expected-now)

    if BINARY_CSV:      
      b1.finish()
      status = b1.socket.recv(1)
      bytes = b1.socket.recv(4)
      size = struct.unpack('>i', bytes)
      bytes = b1.socket.recv(size[0])
      b1.close()
      result = bytes.decode('UTF-8')
    else:
      c.add(b'')
      result = c.finish()
    print('Indexing done; status: %s, result: %s' % (status, result))

    if False:
      bytes = b2.socket.recv(4)
      size = struct.unpack('>i', bytes)
      bytes = b2.socket.recv(size[0])
      print('GOT ANSWER:\n%s' % bytes.decode('utf-8'))
      b2.close()

    dps = id / (time.time()-tStart)
    print('Total: %.1f docs/sec' % dps)

    print('Now stop index...')
    send(LOCALHOST, primaryPorts[0], 'stopIndex', {'indexName': 'index'})
    print('Done stop index...')

  finally:
    # nocommit why is this leaving leftover files?  it should close all open indices gracefully?
    send(LOCALHOST, primaryPorts[0], 'shutdown', {})
    for id, host, installPath, port, binaryPort in replicaPorts:
      send(host, port, 'shutdown', {})

if __name__ == '__main__':
  if '-help' in sys.argv:
    print('''
Usage: python3 scripts/indexTaxis.py <options>:
    [-installPath /path/to/install] install the server and state directory to this path; ./install by default
    [-rebuild] rebuild luceneserver artifact first; default will do this if it does not already exist
    [-replica hostName:installPath or hostName:installPath:serverPort] remote host name and path to install and launch a replica server; your current user must have passwordless ssh access for this to work.  More than one -replica may be specified.
    [-ip ip] which IP to bind to, in addition to 127.0.0.1; this is required if you use -replica
    [-help] prints this message
''')
  main()
