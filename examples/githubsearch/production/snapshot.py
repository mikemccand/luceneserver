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

import os
import datetime

"""
This runs on the production box and makes a full backup of src/ui in case we need to rollback.
"""

def run(cmd):
  if os.system(cmd):
    raise RuntimeError('%s failed' % cmd)

# Take snapshot in case we need to fallback:
os.chdir('../..')
dt = datetime.datetime.now().date()
upto = 0
while True:
  if upto == 0:
    fileName = 'ui.%04d%02d%02d.tar.bz2' % (dt.year, dt.month, dt.day)
  else:
    fileName = 'ui.%04d%02d%02d-%d.tar.bz2' % (dt.year, dt.month, dt.day, upto)
  if not os.path.exists(fileName):
    run('tar cjf %s ui' % fileName)
    print('snapshot to ../%s' % fileName)
    break
  upto += 1

