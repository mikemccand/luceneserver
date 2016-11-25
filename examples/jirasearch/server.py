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

import datetime
import io
import gzip
import mimetypes
import types
import traceback
import urllib.parse
import pickle
import json
import threading
import http.client
import urllib.request, urllib.error, urllib.parse
import subprocess
import shutil
import math
import signal
import pickle
import http.client
import os
import sys
from threading import Thread
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler
import time
import imp
import wsgiref.simple_server
import util
import search
import suggest
import moreFacets

sys.path.insert(0, '/home/changingbits/src/ui')
import handle
import localconstants

"""
Entry point when you run the UI server from the command-line (not via Apache).
"""

LUCENE_SERVER_VERSION = localconstants.LUCENE_SERVER_VERSION
isDev = localconstants.isDev

if False:
  # TODO: messy
  reload(sys)
  sys.setdefaultencoding('utf-8')

lastImportTime = time.time()

class ChunkedSend:

  def __init__(self, server, command, chunkSize):
    self.server = server
    self.h = http.client.HTTPConnection('localhost', server.port)
    self.h.putrequest('POST', '/%s' % command)
    self.h.putheader('Transfer-Encoding', 'chunked')
    self.h.endheaders()
    self.chunkSize = chunkSize
    self.pending = []
    self.pendingBytes = 0

  def add(self, data):
    self.pending.append(data)
    self.pendingBytes += len(data)
    self.sendChunks(False)

  def sendChunks(self, finish):
    if self.pendingBytes == 0:
      return
    
    if finish or self.pendingBytes > self.chunkSize:
      s = ''.join(self.pending)
      upto = 0
      while True:
        chunk = s[self.chunkSize*upto:self.chunkSize*(1+upto)]
        if len(chunk) == 0:
          break
        if not finish and len(chunk) < self.chunkSize:
          break
        m = []
        m.append('%s\r\n' % hex(len(chunk))[2:])
        m.append(chunk)
        #print 'send: %s' % chunk
        m.append('\r\n')
        try:
          self.h.send(''.join(m).encode('utf-8'))
        except:
          # Something went wrong; see if server told us what:
          r = self.h.getresponse()
          s = r.read()
          raise RuntimeError('\n\nServer error:\n%s' % s.decode('utf-8'))
        upto += 1
      del self.pending[:]
      self.pending.append(chunk)
      self.pendingBytes = len(chunk)

  def finish(self):
    """
    Finishes the request and returns the resonse.
    """

    self.sendChunks(True)

    # End chunk marker:
    self.h.send(b'0\r\n\r\n')

    return self.server.processResponse(self.h)
  
monthname = (None,
             'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')

weekdayname = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

def dateTimeString(t):
  year, month, day, hh, mm, ss, wd, y, z = time.gmtime(t)
  return '%s, %02d %3s %4d %02d:%02d:%02d GMT' % (
          weekdayname[wd],
          day, monthname[month], year,
          hh, mm, ss)

# WSGI application entry point:
def application(environ, startResponse):
  global handle
  global lastImportTime

  if isDev:
    t = os.path.getmtime('handle.py')
    if t > lastImportTime:
      print('Reload handle.py')
      handle = imp.reload(handle)
      lastImportTime = t

  if environ['PATH_INFO'] == '/search.py':
    return search.application(environ, startResponse)
  elif environ['PATH_INFO'] == '/suggest.py':
    return suggest.application(environ, startResponse)
  elif environ['PATH_INFO'] == '/moreFacets.py':
    return moreFacets.application(environ, startResponse)
  else:
    # Serve static file:
    headers = []
    path = environ['PATH_INFO']

    fileName = 'static/%s' % path[1:]
    if path != '/' and os.path.exists(fileName):
      headers.append(('Content-Type', mimetypes.guess_type(fileName)[0]))
      f = open(fileName, 'rb')
      fs = os.fstat(f.fileno())      
      bytes = f.read()
      HTTP_CACHE_SECONDS = 60
      headers.append(('Content-Length', str(len(bytes))))
      headers.append(('Last-Modified', dateTimeString(fs.st_mtime)))
      t = time.time()
      headers.append(('Expires', dateTimeString(t+HTTP_CACHE_SECONDS)))
      headers.append(('Cache-Control', 'private, max-age=%s' % HTTP_CACHE_SECONDS))
      startResponse('200 OK', headers)
      return [bytes]
    else:
      startResponse('404 Not Found', [])
      return [('Path %s not found' % path).encode('utf-8')]
      
def main():

  if False:
    import runServer
    svr = runServer.RunServer(localconstants.SERVER_PORT, localconstants.rootPath)

  try:
    #for index in ('books', 'wiki', 'jira'):
    for index in ('jira',):
      try:
        print('%s: %s' % (index.upper(), util.ServerClient().send('startIndex', '{"indexName": "%s"}' % index)))
      except:
        pass

    try:
      idx = sys.argv.index('-port')
    except ValueError:
      if isDev:
        port = 10001
      else:
        port = 10000
    else:
      port = int(sys.argv[idx+1])

    httpd = wsgiref.simple_server.make_server('10.17.4.93', port, application)

    print('Ready on port %s' % port)
    httpd.serve_forever()
  finally:
    if isDev:
      svr.killServer()

if __name__ == '__main__':
  main()
