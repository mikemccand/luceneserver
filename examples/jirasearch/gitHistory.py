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

"""
Handles NRT 'updates' to the gitHistory.log, which indexJira.py parses
to build the issue -> commit path mapping, as well as the 'Committed
by' facets.

Create the initial gitHistory.log by running:

  git log --reverse --name-status
"""

import types
import os
import io
import re
import localconstants

GIT_HISTORY_FILE = localconstants.GIT_HISTORY_FILE

reIssue = re.compile('(lucene|solr)-\d+', re.IGNORECASE)
rePath = re.compile('^(lucene|solr)/([^/]*?)/src/(java|test|test-files|resources)/org/apache/(lucene|solr)/')
rePath2 = re.compile('^(lucene|solr)/([^/]*?)/([^/]*?)/src/(java|test|test-files)/org/apache/(lucene|solr)/')
rePath3 = re.compile('^solr/contrib/([^/]*?)/src/(java|test|test-files|resources)/org/apache/(lucene|solr)/')

def fixPath(path):

  # print('PATH in %s' % path)

  i = path.find(' (from ')
  if i != -1:
    path = path[:i]

  for prefix in ('/lucene/dev/trunk/',
                 '/lucene/dev/branches/branch_3x',
                 '/lucene/dev/branches/lucene_solr_3_1',
                 '/lucene/dev/branches/realtime_search/'):
    if path.startswith(prefix):
      path = path[len(prefix):]

  if path.find('lucene') != -1:
    path = path.replace('/contrib', '')

  if path[0] == '/':
    path = path[1:]
    
  if path.startswith('lucene/src/'):
    path = 'lucene/core/' + path[7:]

  path = path.replace('modules/', 'lucene/')
  path = path.replace('src/', '')
  path = path.replace('org/apache/lucene/', '')
  path = path.replace('org/apache/solr/', '')

  if False:

    m = rePath.search(path)
    if m is not None:
      #print '  case 1'
      project = m.group(1)
      sub = m.group(3)
      module = m.group(2)
      if sub == 'java':
        path = '%s-%s/%s' % (project, module, path[m.end(0):])
      else:
        path = '%s-%s-test/%s' % (project, module, path[m.end(0):])
    else:
      # EG lucene/analysis/icu or solr/contrib/clustering
      m = rePath2.search(path)
      if m is not None:
        #print '  case 2: %s' % str(m.groups())
        sub = m.group(4)
        project = m.group(1)
        module = '%s-%s' % (m.group(2), m.group(3))
        if sub == 'java':
          path = '%s-%s/%s' % (project, module, path[m.end(0):])
        else:
          path = '%s-%s-test/%s' % (project, module, path[m.end(0):])
      else:
        #print '  case 3'
        m = rePath3.search(path)
        if m is not None:
          project = 'solr'
          sub = m.group(3)
          module = 'contrib-%s' % m.group(1)
          if sub == 'java':
            path = '%s-%s/%s' % (project, module, path[m.end(0):])
          else:
            path = '%s-%s-test/%s' % (project, module, path[m.end(0):])

  if path.find('CHANGES.txt') != -1:
    return None

  if path.endswith('org/apache/lucene'):
    return None

  if path.endswith('org/apache/solr'):
    return None

  if path.endswith('src'):
    return None

  if path in ('lucene/dev/trunk', 'modules'):
    return None

  if path.find('.gitignore') != -1:
    return None

  if path.find('.hgignore') != -1:
    return None
  
  #print('  -> %s' % path)
  return path

def parseLog(f=None):
  global maxRev, issueToPaths

  if f is None:
    f = open(GIT_HISTORY_FILE, 'r')
    changedIssues = None
    maxRev = 0
  else:
    changedIssues = set()

  issues = []
  issueToPaths = {}
  author = None
  while True:
    line = f.readline()
    #line = line.decode('utf-8')
    if line == '':
      break
    line = line.rstrip()
    if line.startswith('commit '):
      maxRev = rev = line[7:].strip()
      issues.clear()
      author = None
    elif len(line) == 0:
      pass
    elif line.startswith('Author: '):
      # TODO: we could offer facets on this?
      author = line[8:line.find(' <')].strip()
    elif line.startswith('Date'):
      pass
    elif line.startswith('    '):
      # commit comment
      m = reIssue.search(line)
      if m is not None:
        issue = m.group(0).upper()
        issues.append(issue)
        if changedIssues is not None:
          changedIssues.add(issue)
        if issue not in issueToPaths:
          # common case: only one author; store as string in that case
          issueToPaths[issue] = [author]
        elif type(issueToPaths[issue][0]) is str:
          if issueToPaths[issue][0] != author:
            # uncommon case: upgrade string to set
            s = set()
            s.add(issueToPaths[issue][0])
            s.add(author)
            issueToPaths[issue][0] = s
        else:
          # already a set
          issueToPaths[issue][0].add(author)
    else:
      letter = line[0]
      if letter not in ('M', 'A', 'D', 'R'):
        raise RuntimeError('WEIRD LETTER %s in line %s' % (letter, line))
      path = line[1:].strip()
      fixed = fixPath(path)
      if fixed is not None:
        s = '%s:%s' % (letter, fixed)
        for issue in issues:
          issueToPaths[issue].append(s)

  print('gitHistory: after parseLog maxRev=%s' % maxRev)

  if changedIssues is not None:
    return issueToPaths, changedIssues
  else:
    return issueToPaths

def refresh():
  print('refresh: maxRev=%s' % maxRev)
  cwd = os.getcwd()
  try:
    os.chdir(localconstants.LUCENE_TRUNK_GIT_CLONE)
    if os.system('git pull origin master') == 0:
      s = os.popen('git log --reverse --name-status %s..HEAD' % maxRev).read()
      open(GIT_HISTORY_FILE, 'ab').write(s.encode('utf-8'))
      f = io.StringIO(s)
      return parseLog(f)
    else:
      print('WARNING: failed to run "git fetch origin master"')
      return {}, set()
  finally:
    os.chdir(cwd)

if __name__ == '__main__':
  f = open(GIT_HISTORY_FILE, 'r')
  x, changedIssues = parseLog(f)
  f.close()
  print('%d issues' % len(x))
  sum = 0
  for k, v in x.items():
    #print('%s' % k)
    sum += len(v)
    #for x in v:
      #print('  %s' % x[1])
  print('  %d total paths' % sum)

  x, changedIssues = refresh()
  print('changed %d' % len(changedIssues))

