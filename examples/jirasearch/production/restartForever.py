import os
import time
import datetime

while True:
  mb = float(os.popen('ps axuww | grep org.apache.lucene.server.Server | grep -v grep').read().split()[5])/1024.
  if mb > 375.0:
    print('%s: now restart @ %.1f MB' % (datetime.datetime.now(), mb))
    os.system('python3 -u restart.py')
  time.sleep(10.0)


                            
