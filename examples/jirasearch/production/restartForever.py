import os
import time
import datetime

while True:
  try:
    mb = float(os.popen('ps axuww | grep org.apache.lucene.server.Server | grep -v grep').read().split()[5])/1024.
   except IndexError:
     print('FAILED to find server process; retry in 10s')
     time.sleep(10.0)
     continue
    
  if mb > 375.0:
    print('%s: now restart @ %.1f MB' % (datetime.datetime.now(), mb))
    os.system('python3 -u restart.py')

  time.sleep(10.0)


                            
