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
import gzip
import traceback
import os
import json
import http.client
import localconstants
import threading
import datetime

local = threading.local()
  
nonceLock = threading.Lock()
nonce = 0

if not os.path.exists(localconstants.logDir):
  os.makedirs(localconstants.logDir)

now = datetime.datetime.now()
suffix = ''
while True:
  fileName = '%s/%04d%02d%02d-%02d%02d%02d%s.log' % \
             (localconstants.logDir, now.year, now.month, now.day, now.hour, now.minute, now.second, suffix)
  if os.path.exists(fileName):
    if suffix == '':
      suffix = '-0'
    else:
      suffix = '-%d' % (int(suffix[1:])+1)
  else:
    break

logFile = open(fileName, 'wb')

logFileLock = threading.Lock()

def setNonce(environ):
  global nonce
  
  with nonceLock:
    myNonce = nonce
    nonce += 1

  local.nonce = myNonce
  if environ['HTTP_USER_AGENT'].find('httpMonitor') != -1:
    local.skipLog = True
  else:
    local.skipLog = False

  remoteIP = environ['REMOTE_ADDR']
  if remoteIP == '127.0.0.1':
    remoteIP = environ['HTTP_X_FORWARDED_FOR']
  path = environ['PATH_INFO']
  if path == '':
    path = environ['SCRIPT_NAME']
  qs = environ['QUERY_STRING']
  if qs != '':
    path += '?' + qs

  log('REQ %s %s %s' % (remoteIP, datetime.datetime.now(), path))

def log(message):
  global logFile
  if local.skipLog:
    return
  with logFileLock:
    message = '[%05d] %s' % (local.nonce, message)
    logFile.write(message.encode('utf-8'))
    logFile.write(b'\n')
  logFile.flush()

class ServerClient:

  """
  Simple client API to send requests to the Lucene server.
  """

  def __init__(self, host=None, port=None):
    if host is None:
      host = 'localhost'
      port = localconstants.SERVER_PORT
    self.host = host
    self.port = port
    
  def send(self, command, data):
    #print '\nSEND %s, %s' % (command, data)
    #print 'SEND: %d bytes' % len(data)

    if type(data) is dict:
      data = json.dumps(data)

    if True:
      # TODO: persistent http connection
      h = http.client.HTTPConnection(self.host, self.port)
      if False and command == 'search':
        s = 'UI: POST /%s to server; data=%s' % (command, data)
        #print s
        log(s)
      try:
        h.request('POST', '/%s' % command, data)
        return self.processResponse(h)
      except:
        print('  FAILED')
        traceback.print_exc()
        raise

    else:
      u = urllib.request.urlopen('http://%s:%s/%s' % (self.host, self.port, command), data)
      s = u.read()
      print(s)
      return json.loads(s)

  def processResponse(self, h):
    r = h.getresponse()
    if r.status == 200:
      size = r.getheader('Content-Length')
      s = r.read().decode('utf-8')
      h.close()
      return json.loads(s)
    elif r.status == http.client.BAD_REQUEST:
      s = r.read()
      h.close()
      raise RuntimeError('\n\nServer error:\n%s' % s.decode('utf-8'))
    else:
      s = r.read()
      h.close()
      raise RuntimeError('Server returned HTTP %s, %s:\n%s' % (r.status, r.reason, s.decode('utf-8')))

def handleOnePage(environ, startResponse, handler):
  setNonce(environ)

  path = environ['PATH_INFO']
  qs = environ['QUERY_STRING']
  if qs != '':
    path += '?' + qs

  remoteIP = environ['REMOTE_ADDR']
  if remoteIP == '127.0.0.1':
    remoteIP = environ['HTTP_X_FORWARDED_FOR']

  isMike = remoteIP.startswith('10.17.4') or remoteIP == '96.237.189.17'

  try:
    html, headers = handler(path, isMike, environ)
    if headers == None:
      print('GOT NONE HEADERS %s' % handler)
  except:
    s = traceback.format_exc()
    print('EXC: %s' % s)
    log('EXC %s' % s.replace('\n', '\\n'))
    html = '<pre>%s</pre>' % escape(s)
    headers = []

  allHeaders = []
  allHeaders.append(('Content-Type', 'text/html; charset=utf8'))
  acceptEnc = environ.get('HTTP_ACCEPT_ENCODING')
    
  if acceptEnc is not None and acceptEnc.find('gzip') != -1:
    doGzip = True
    allHeaders.append(('Content-Encoding', 'gzip'))
  else:
    doGzip = False

  bytes = html.encode('utf-8')
  if doGzip:
    buf = io.BytesIO()
    zfile = gzip.GzipFile(mode = 'wb', fileobj = buf, compresslevel = 9)
    zfile.write(bytes)
    zfile.close()
    bytes = buf.getvalue()
    endBytes = len(bytes)

  allHeaders.append(('Content-Length', str(len(bytes))))
  allHeaders.extend(headers)
  startResponse('200 OK', allHeaders)
  return [bytes]

def escape(s):
  s = s.replace('&', '&amp;')
  s = s.replace('<', '&lt;')  
  s = s.replace('>', '&gt;')
  s = s.replace('"', '&quot;')
  return s
