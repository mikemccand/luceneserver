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

# TODO
#   - index lat/lon as geopoint!

#host1 = '10.17.4.92'
host1 = '127.0.0.1'
host2 = '10.17.4.12'
#host2 = '127.0.0.1'

DO_REPLICA = False
DO_SEARCH = False

LOCALHOST = '127.0.0.1'

DEFAULT_PORT = 4000

PACKAGE_FILE = os.path.abspath('build/luceneserver-0.1.0-SNAPSHOT.zip')

USER_NAME = getpass.getuser()

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

def launchServer(host, installDir, port):
  os.makedirs(installDir)
  zipFileName = os.path.split(PACKAGE_FILE)[1]

  # copy install bits over
  if host != LOCALHOST:
    run('scp %s %s@%s:/tmp' % (PACKAGE_FILE, USER_NAME, host))
    # unzip it
    run('ssh %s@%s "mkdir -p %s; cd %s; unzip /tmp/%s"' % (USER_NAME, host, installDir, installDir, zipFileName))
  else:
    run('cd %s; unzip %s' % (installDir, PACKAGE_FILE))

  serverDirName = zipFileName[:-4]

  if host != LOCALHOST:
    command = r'ssh %s@%s "cd %s/%s; java -Xms4g -Xmx4g -cp lib/\* org.apache.lucene.server.Server -stateDir %s/state -ipPort %s:%s"' % (USER_NAME, host, installDir, serverDirName, installDir, host, port)
  else:
    command = r'cd %s/%s; java -Xms4g -Xmx4g -cp lib/\* org.apache.lucene.server.Server -stateDir %s/state -ipPort %s:%s' % (installDir, serverDirName, installDir, host, port)

  #print('%s: server command %s' % (host, command))
  p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

  # Read lines until we see the server is started, then launch bg thread to read future lines:
  while True:
    line = p.stdout.readline()
    line = line.decode('utf-8')
    if line == '':
      raise RuntimeError('server on %s failed to start' % host)
    #print('%s: %s' % (host, line))

    if 'Server main: listening on' in line:
      line = p.stdout.readline().strip().decode('utf-8')
      i = line.find(':')
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
  print('RUN: %s' % command)
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
    i = sys.argv.indexOf(option)
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

  if not os.path.exists('src/java/org/apache/lucene/server/Server.java'):
    print('\nERROR: please run this from the luceneserver working directory\n')
    sys.exit(1)

  if getFlag('-rebuild') or not os.path.exists('build/luceneserver-0.1.0-SNAPSHOT.zip'):
    print('Building server release artifact...')
    run('python3 -u build.py package', 'package.log')

  primaryInstallPath = getArg('-installPath')
  if primaryInstallPath is None:
    primaryInstallPath = os.path.abspath('install')

  if os.path.exists(primaryInstallPath):
    raise RuntimeError('primary install path %s already exists; please remove it and rerun' % primaryInstallPath)

  replicas = []
  while True:
    s = getArg('-replica')
    if s is not None:
      tup = s.split(':')
      if len(tup) == 2:
        replicas.append((replicaHost, DEFAULT_PORT, replicaInstallPath))
      elif len(tup) == 3:
        replicas.append((replicaHost, int(tup[1]), replicaInstallPath))
      else:
        raise RuntimeError('-replica should be host:installPath or host:port:installPath')
    else:
      break

  for host, port, installPath in replicas:
    s = os.popen('ssh %s@%s ls %s' % (USER_NAME, host, installPath)).read()
    if 'no such file or directory' not in s.lower():
      raise RuntimeError('path %s on replica %s already exists; please remove it and rerun' % (installPath, host))
    
  os.makedirs(primaryInstallPath)
  for host, port, path in replicas:
    run('ssh %s@%s mkdir -p %s' % (USER_NAME, host, path))

  primaryPorts = launchServer(LOCALHOST, '%s/server0' % primaryInstallPath, 4000)

  replicaPorts = []
  for i, (host, port, installPath) in enumerate(replicas):
    replicaPorts.append((i+1, host, installPath) + launchServer(host, '%s/server%s' % (installPath, i+1), port))

  try:
    send(LOCALHOST, primaryPorts[0], 'createIndex', {'indexName': 'index', 'rootDir': '%s/server0/index' % primaryInstallPath})
    for id, host, installPath, port, binaryPort in replicaPorts:
      send(host, port, 'createIndex', {'indexName': 'index', 'rootDir': '%s/server%s/index' % (installPath, id)})

    # Turn off refreshes to maximize indexing throughput:
    send(LOCALHOST, primaryPorts[0], "liveSettings", {'indexName': 'index', 'index.ramBufferSizeMB': 1024., 'maxRefreshSec': 100000.0})

    fields = {'indexName': 'index',
              'fields':
              {
                'vendor_id': {'type': 'atom', 'sort': True},
                'vendor_name': {'type': 'text'},
                'cab_color': {'type': 'atom', 'sort': True},
                'pick_up_date_time': {'type': 'long', 'search': True, 'sort': True},
                'drop_off_date_time': {'type': 'long', 'search': True, 'sort': True},
                'passenger_count': {'type': 'int', 'search': True, 'sort': True},
                'trip_distance': {'type': 'double', 'search': True, 'sort': True},
                'pick_up_lat': {'type': 'double', 'search': True, 'sort': True},
                'pick_up_lon': {'type': 'double', 'search': True, 'sort': True},
                'drop_off_lat': {'type': 'double', 'search': True, 'sort': True},
                'drop_off_lon': {'type': 'double', 'search': True, 'sort': True},
                'payment_type': {'type': 'atom', 'sort': True},
                'trip_type': {'type': 'atom', 'sort': True},
                'rate_code': {'type': 'atom', 'sort': True},
                'fare_amount': {'type': 'double', 'search': True, 'sort': True},
                'surcharge': {'type': 'double', 'search': True, 'sort': True},
                'mta_tax': {'type': 'double', 'search': True, 'sort': True},
                'extra': {'type': 'double', 'search': True, 'sort': True},
                'ehail_fee': {'type': 'double', 'search': True, 'sort': True},
                'improvement_surcharge': {'type': 'double', 'search': True, 'sort': True},
                'tip_amount': {'type': 'double', 'search': True, 'sort': True},
                'tolls_amount': {'type': 'double', 'search': True, 'sort': True},
                'total_amount': {'type': 'double', 'search': True, 'sort': True},
                'store_and_fwd_flag': {'type': 'atom', 'sort': True}}}

    send(LOCALHOST, primaryPorts[0], 'registerFields', fields)
    for id, host, installPath, port, binaryPort in replicaPorts:
      send(host, port, 'registerFields', fields)

    send(LOCALHOST, primaryPorts[0], "settings", {'indexName': 'index',
                                    #'indexSort': [{'field': 'pick_up_lon'}],
                                    'index.verbose': False,
                                    'directory': 'MMapDirectory',
                                    'nrtCachingDirectory.maxSizeMB': 0.0,
                                    #'index.merge.scheduler.auto_throttle': False,
                                    })

    for id, host, installPath, port, binaryPort in replicaPorts:
      send(host, port, "settings", {'indexName': 'index',
                                    'index.verbose': False,
                                    'directory': 'MMapDirectory',
                                    'nrtCachingDirectory.maxSizeMB': 0.0,
                                    #'index.merge.scheduler.auto_throttle': False,
                                    })

    if len(replicas) > 0:
      send(LOCALHOST, primaryPorts[0], 'startIndex', {'indexName': 'index', 'mode': 'primary', 'primaryGen': 0})
      for id, host, installPath, port, binaryPort in replicaPorts:
        send(host2, port2, 'startIndex', {'indexName': 'index', 'mode': 'replica', 'primaryAddress': host1, 'primaryGen': 0, 'primaryPort': binaryPort1})
    else:
      send(LOCALHOST, primaryPorts[0], 'startIndex', {'indexName': 'index'})

    b1 = BinarySend(LOCALHOST, primaryPorts[1], 'bulkCSVAddDocument')
    b1.add(b'index\n')

    id = 0
    tStart = time.time()
    nextPrint = 250000
    replicaStarted = False

    docSource = '/lucenedata/nyc-taxi-data/alltaxis.csv.blocks'
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
              print('  %.1f MB or 154.0 MB...' % (netBytes/1024./1024.))
              nextPrint += 5*1024*1024
        print('  done: %.1f MB' % (os.path.getsize(docSource)/1024./1024.))

    #with open('/lucenedata/nyc-taxi-data/alltaxis.csv.blocks', 'rb') as f:
    totBytes = 0
    chunkCount = 0

    with open(docSource, 'rb') as f:
    #with open('/b/alltaxis.csv.blocks', 'rb') as f:
      csvHeader = f.readline()
      b1.add(csvHeader)
      while True:
        header = f.readline()
        if len(header) == 0:
          break
        byteCount, docCount = (int(x) for x in header.strip().split())
        bytes = f.read(byteCount)
        totBytes += byteCount
        b1.add(bytes)
        chunkCount += 1
        #print('doc: %s' % doc)
        id += docCount
        if id >= nextPrint:
          delay = time.time()-tStart
          dps = id / delay
          if DO_SEARCH:
            if DO_REPLICA:
              x = json.loads(send(host2, port2, 'search', {'indexName': 'index', 'queryText': '*:*'}));
            else:
              x = json.loads(send(host1, port1, 'search', {'indexName': 'index', 'queryText': '*:*'}));
            print('%6.1f sec: %d hits, %.1f M docs... %.1f docs/sec, %.1f MB/sec' % (delay, x['totalHits'], id/1000000., dps, (totBytes/1024./1024.)/delay))
          else:
            print('%6.1f sec: %.1f M docs... %.1f docs/sec, %.1f MB/sec' % (delay, id/1000000., dps, (totBytes/1024./1024.)/delay))

          while nextPrint <= id:
            nextPrint += 250000

    b1.finish()

    bytes = b1.socket.recv(4)
    size = struct.unpack('>i', bytes)
    bytes = b1.socket.recv(size[0])
    print('Indexing done; result: %s' % bytes.decode('utf-8'))
    b1.close()

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
    [-installDir /path/to/install] install the server and state directory to this path; ./install by default
    [-rebuild] rebuild luceneserver artifact first; default will do this if it does not already exist
    [-replica hostName:installPath or hostName:serverPort:installPath] remote host name and path to install and launch a replica server; your current user must have passwordless ssh access for this to work.  More than one -replica may be specified.
    [-help] prints this message
''')
  main()
