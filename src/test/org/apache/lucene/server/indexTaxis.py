import socket
import struct
import time
import sys
import json
import os
import subprocess
import threading
import http.client

# TODO
#   - index lat/lon as geopoint!

#host1 = '10.17.4.92'
host1 = '127.0.0.1'
host2 = '10.17.4.12'
#host2 = '127.0.0.1'

DO_REPLICA = False
DO_SEARCH = False

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

def launchServer(host, stateDir, port):
  command = r'ssh mike@%s "cd /l/newluceneserver/lucene; java -Xmx4g -cp build/replicator/lucene-replicator-7.0.0-SNAPSHOT.jar:build/facet/lucene-facet-7.0.0-SNAPSHOT.jar:build/highlighter/lucene-highlighter-7.0.0-SNAPSHOT.jar:build/expressions/lucene-expressions-7.0.0-SNAPSHOT.jar:build/analysis/common/lucene-analyzers-common-7.0.0-SNAPSHOT.jar:build/analysis/icu/lucene-analyzers-icu-7.0.0-SNAPSHOT.jar:build/queries/lucene-queries-7.0.0-SNAPSHOT.jar:build/join/lucene-join-7.0.0-SNAPSHOT.jar:build/queryparser/lucene-queryparser-7.0.0-SNAPSHOT.jar:build/suggest/lucene-suggest-7.0.0-SNAPSHOT.jar:build/core/lucene-core-7.0.0-SNAPSHOT.jar:build/server/lucene-server-7.0.0-SNAPSHOT.jar:server/lib/\* org.apache.lucene.server.Server -port %s -stateDir %s -interface %s"' % (host, port, stateDir, host)
  print('%s: server command %s' % (host, command))
  p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

  # Read lines until we see the server is started, then launch bg thread to read future lines:
  while True:
    line = p.stdout.readline()
    line = line.decode('utf-8')
    if line == '':
      raise RuntimeError('server on %s failed to start' % host)
    print('%s: %s' % (host, line))

    if 'listening on port' in line:
      x = line.split()[-1]
      x = x.replace('.', '')
      ports = (int(y) for y in x.split('/'))
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
    command += ' >> %s 2>&1' % logFile
  print('RUN: %s' % command)
  result = subprocess.call(command, shell=True)
  if result != 0:
    if logFile is not None:
      print(open(logFile).read())
    raise RuntimeError('command failed with result %s: %s' % (result, command))

def rmDir(host, path):
  run('ssh %s rm -rf %s' % (host, path))

os.chdir('/l/newluceneserver/lucene')
if '-rebuild' in sys.argv:
  run('ant clean jar', 'ant.log')
  #run('ssh %s rm -rf /l/newluceneserver' % host2)
  for host in (host1, host2):
    if host not in ('10.17.4.92', '127.0.0.1'):
      run('rsync -a /l/newluceneserver/ mike@%s:/l/newluceneserver/' % host)

ROOT_DIR = '/c/taxis'

rmDir(host1, '%s/server1' % ROOT_DIR)

if DO_REPLICA:
  rmDir(host2, '%s/server2' % ROOT_DIR)

port1, binaryPort1 = launchServer(host1, '%s/server1/state' % ROOT_DIR, 4000)
if DO_REPLICA:
  port2, binaryPort2 = launchServer(host2, '%s/server2/state' % ROOT_DIR, 5000)

try:
  send(host1, port1, 'createIndex', {'indexName': 'index', 'rootDir': '%s/server1/index' % ROOT_DIR})
  if DO_REPLICA:
    send(host2, port2, 'createIndex', {'indexName': 'index', 'rootDir': '%s/server2/index' % ROOT_DIR})
  send(host1, port1, "liveSettings", {'indexName': 'index', 'index.ramBufferSizeMB': 1024., 'maxRefreshSec': 100000.0})
  if DO_REPLICA:
    send(host2, port2, "settings", {'indexName': 'index',
                                    'index.verbose': False,
                                    'directory': 'MMapDirectory',
                                    'nrtCachingDirectory.maxSizeMB': 0.0,
                                    #'index.merge.scheduler.auto_throttle': False,
                                    })
  send(host1, port1, "settings", {'indexName': 'index',
                                  'index.verbose': False,
                                  'directory': 'MMapDirectory',
                                  'nrtCachingDirectory.maxSizeMB': 0.0,
                                  #'index.merge.scheduler.auto_throttle': False,
                                  })
  

  fields = {'indexName': 'index',
            'fields':
            {
              'vendor_id': {'type': 'atom', 'sort': True, 'multiValued': True},
              'vendor_name': {'type': 'text'},
              'cab_color': {'type': 'atom', 'sort': True, 'multiValued': True},
              'pick_up_date_time': {'type': 'long', 'search': True, 'sort': True, 'multiValued': True},
              'drop_off_date_time': {'type': 'long', 'search': True, 'sort': True, 'multiValued': True},
              'passenger_count': {'type': 'int', 'search': True, 'sort': True, 'multiValued': True},
              'trip_distance': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'pick_up_lat': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'pick_up_lon': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'drop_off_lat': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'drop_off_lon': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'payment_type': {'type': 'atom', 'sort': True, 'multiValued': True},
              'trip_type': {'type': 'atom', 'sort': True, 'multiValued': True},
              'rate_code': {'type': 'atom', 'sort': True, 'multiValued': True},
              'fare_amount': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'surcharge': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'mta_tax': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'extra': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'ehail_fee': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'improvement_surcharge': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'tip_amount': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'tolls_amount': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'total_amount': {'type': 'double', 'search': True, 'sort': True, 'multiValued': True},
              'store_and_fwd_flag': {'type': 'atom', 'sort': True, 'multiValued': True}}}

  send(host1, port1, 'registerFields', fields)
  if DO_REPLICA:
    send(host2, port2, 'registerFields', fields)

  if DO_REPLICA:
    send(host1, port1, 'startIndex', {'indexName': 'index', 'mode': 'primary', 'primaryGen': 0})
    send(host2, port2, 'startIndex', {'indexName': 'index', 'mode': 'replica', 'primaryAddress': host1, 'primaryGen': 0, 'primaryPort': binaryPort1})
  else:
    send(host1, port1, 'startIndex', {'indexName': 'index'})

  b1 = BinarySend(host1, binaryPort1, 'bulkCSVAddDocument')
  b1.add(b'index\n')
  #b2 = BinarySend(host1, binaryPort1, 'bulkCSVAddDocument')
  #b2.add(b'index\n')

  id = 0
  tStart = time.time()
  nextPrint = 100000
  replicaStarted = False

  totBytes = 0
  chunkCount = 0
  with open('/lucenedata/nyc-taxi-data/alltaxis.csv.blocks', 'rb') as f:
  #with open('/b/alltaxis.csv.blocks', 'rb') as f:
    while True:
      header = f.readline()
      if len(header) == 0:
        break
      byteCount, docCount = (int(x) for x in header.strip().split())
      bytes = f.read(byteCount)
      totBytes += byteCount
      if True or chunkCount & 1 == 0:
        b1.add(bytes)
        if False and chunkCount == 0:
          # copy the CSV header for b2 as well:
          s = bytes.decode('utf-8')
          i = s.find('\n')
          b2.add(s[:i+1].encode('utf-8'))
      else:
        b2.add(bytes)
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
          print('%6.1f sec: %d hits, %d docs... %.1f docs/sec, %.1f MB/sec' % (delay, x['totalHits'], id, dps, (totBytes/1024./1024.)/delay))
        else:
          print('%6.1f sec: %d docs... %.1f docs/sec, %.1f MB/sec' % (delay, id, dps, (totBytes/1024./1024.)/delay))

        while nextPrint <= id:
          nextPrint += 100000

  b1.finish()
  #b2.finish()
  
  bytes = b1.socket.recv(4)
  size = struct.unpack('>i', bytes)
  bytes = b1.socket.recv(size[0])
  print('GOT ANSWER:\n%s' % bytes.decode('utf-8'))
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
  send(host1, port1, 'stopIndex', {'indexName': 'index'})
  print('Done stop index...')
  
finally:
  # nocommit why is this leaving leftover files?  it should close all open indices gracefully?
  send(host1, port1, 'shutdown', {})
  if DO_REPLICA:
    send(host2, port2, 'shutdown', {})
