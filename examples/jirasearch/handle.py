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

import pprint
import math
import urllib.request, urllib.error, urllib.parse
import sys
import traceback
import re
import time
import urllib.parse
import types
import json
import string
import copy
import threading
import localconstants
import util
import random
import datetime
import http.cookies

"""
Handles incoming queries for the search UI.
"""

TRACE = False

if not localconstants.isDev:
  TRACE = False

allProjects = ('Tika', 'Solr', 'Lucene', 'Infrastructure')

DO_PROX_HIGHLIGHT = False

MAX_INT = (1 << 31) - 1

def isCommitUser(userName):
  for s in ('Commit Tag Bot', 'ASF subversion and git services', 'ASF GitHub Bot'):
    if s in userName:
      return True
  return False

class UISpec:
  doAutoComplete = False
  groups = None
  sorts = None
  perPageList = 7
  perPageGrid = 15
  
  def finish(self):
    self.facetByID = {}
    for userLabel, field, isHierarchy, sort, doMorePopup in self.facetFields:
      self.facetByID[field] = (isHierarchy, userLabel, sort, doMorePopup)

    self.groupByID = {}
    if self.groups is not None:
      for id, userLabel, facetField in self.groups:
        if id in self.groupByID:
          raise RuntimeError('duplicate group ID %s' % id)
        self.groupByID[id] = (userLabel, facetField)

    self.sortByID = {}
    for id, userLabel, field, reverse in self.sorts:
      if id in self.sortByID:
        raise RuntimeError('duplicate sort ID %s' % id)
      self.sortByID[id] = (userLabel, field, reverse)

  def buildTextQuery(self, text):
    q = {'class': 'BooleanQuery',
         'disableCoord': False
         }
    l0 = []
    q['subQueries'] = l0
    for field in self.textQueryFields:
      l0.append({'occur': 'should',
                 'query': {'class': 'text',
                           'field': field,
                           'text': text}})
    return q

class JIRASpec(UISpec):

  def buildBrowseOnlyQuery(self):
    # Match all on both parent (in case it has no comments yet) and children:
    return {'class': 'BooleanQuery',
            'subQueries': [{'occur': 'should',
                            'query': {'class': 'ToParentBlockJoinQuery',
                                      'childQuery': {'class': 'BooleanQuery',
                                                     'subQueries': [{'occur': 'must',
                                                                     'query': 'MatchAllDocsQuery'},
                                                                    {'occur': 'must_not',
                                                                     'query': {'class': 'BooleanFieldQuery',
                                                                               'field': 'parent'}}]},
                                      'parentsFilter': {'class': 'BooleanFieldQuery', 'field': 'parent'},
                                      'scoreMode': 'Max',
                                      'childHits': {'maxChildren': 2,
                                                    'sort': [{'field': 'created', 'reverse': True}]}}},
                           {'occur': 'should',
                            'query': {'class': 'BooleanFieldQuery',
                                      'field': 'parent'}}]}

  def buildTextQuery(self, text):
    l0 = []
    q = {'class': 'BooleanQuery',
         'disableCoord': False,
         'subQueries': l0
         }
    lowerText = text.lower()

    l2 = []
    for field in ('summary', 'description', 'key', 'allUsers', 'otherText'):
      if field in ('summary', 'key'):
        boost = 3.0
      else:
        boost = 1.0

      if field == 'key':
        text0 = lowerText
      else:
        text0 = text
        
      l2.append({'occur': 'should',
                 'query': {'class': 'text',
                           'boost': boost,
                           'field': field,
                           'text': text0}})

    # match parent fields only; make sure we only match parent docs
    # with this part of the query:

    l0.append(
      {'occur': 'should',
       'query': {'class': 'BooleanQuery',
                 'disableCoord': True,
                 'subQueries': [{'query': {'class': 'BooleanQuery',
                                           'subQueries': l2},
                                 'occur': 'must'},
                                {'query': {'class': 'BooleanFieldQuery',
                                           'field': 'parent'},
                                 'occur': 'filter'}]}})

    # Also match text fields on child docs (each comment on the issue)
    # and Join up to the issue:
    l0.append({'occur': 'should',
               'query':
                 {'class': 'ToParentBlockJoinQuery',
                  'childQuery':
                  {'class': 'BooleanQuery',
                   'subQueries': [{'occur': 'should', 'query': {'class': 'text', 'field': 'body', 'text': text}},
                                  {'occur': 'should', 'query': {'class': 'text', 'field': 'author', 'text': text}},
                                  {'occur': 'should', 'query': {'class': 'text', 'field': 'childKey', 'text': lowerText, 'boost': 3.0}}]},
                  'parentsFilter': {'class': 'BooleanFieldQuery', 'field': 'parent'},
                  'scoreMode': 'Max',
                  'childHits': {
                     'maxChildren': 3
                     }}})
                       
    return q

  def dateToString(self, dt):
    return '%04d%02d%02d' % (dt.year, dt.month, dt.day)
  
  updatedMapValue = None
  updateMapLock = threading.Lock()
  
  def getUpdatedMap(self):
    now = datetime.datetime.now()
    s = self.dateToString(now)
    self.updateMapLock.acquire()
    try:
      if s == self.updatedMapValue:
        return self.updatedMap
    finally:
      self.updateMapLock.release()
    
    d = {}
    oneDay = datetime.timedelta(days=1)
    for i in range(0, 30):
      labels = []
      if i == 0:
        labels.add('Today')
      if i <= 1:
        labels.add('Past 2 days')
      if i <= 2:
        labels.add('Past 3 days')
      if i <= 6:
        labels.add('Past week')
      if i <= 13:
        labels.add('Past 2 weeks')
      if i <= 29:
        labels.add('Past month')

      dt = now - i*oneDay

      d[self.dateToString(dt)] = tuple(labels)

    try:
      self.updateMapValue = s
      self.updatedMap = d
    finally:
      self.updateMapLock.release()

    return d

jiraSpec = JIRASpec()
jiraSpec.doAutoComplete = True
jiraSpec.showGridOrList = False
jiraSpec.indexName = 'jira'
jiraSpec.itemLabel = 'issues'

if False:
  # (field, userLabel, facetField)
  jiraSpec.groups = (
    ('assignee', 'assignee', 'assignee'),
    ('facetPriority', 'priority', 'facetPriority'),
    )

# (id, userLabel, field, reverse):
jiraSpec.sorts = (
  ('relevanceRecency', 'relevance + recency', 'blendRecencyRelevance', True),
  ('relevance', 'pure relevance', None, False),
  ('oldest', 'oldest', 'created', False),
  ('commentCount', 'most comments', 'commentCount', True),
  ('voteCount', 'most votes', 'voteCount', True),
  ('watchCount', 'most watches', 'watchCount', True),
  ('newest', 'newest', 'created', True),
  ('priority', 'priority', 'priority', False),
  #('notRecentlyUpdated', 'not recently updated', 'updated', False),
  ('recentlyUpdated', 'recently updated', 'updated', True),
  #('keyNum', 'issue number', 'keyNum', False),
  )

jiraSpec.retrieveFields = (
  'key',
  'updated',
  'created',
  {'field': 'allUsers', 'highlight': 'whole'},
  'status',
  'author',
  'commentID',
  'commentCount',
  'voteCount',
  'watchCount',
  'commitURL',
  {'field': 'summary', 'highlight': 'whole'},
  {'field': 'description', 'highlight': 'snippets'},
  {'field': 'body', 'highlight': 'snippets'},
  )

jiraSpec.highlighter = {
  'class': 'PostingsHighlighter',
  'passageScorer.b': 0.75,
  'maxPassages': 3,
  'maxLength': 1000000}

# (userLabel, fieldName, isHierarchy, sort, doMorePopup)
jiraSpec.facetFields = (
  ('Status', 'status', False, None, False),
  ('Project', 'project', False, None, False),
  ('Updated', 'updated', False, None, False),
  ('Updated ago', 'updatedAgo', False, None, False),
  ('User', 'allUsers', False, None, True),
  ('Committed by', 'committedBy', False, None, True),
  ('Last comment user', 'lastContributor', False, None, True),
  ('Fix version', 'fixVersions', True, '-int', True),
  ('Committed paths', 'committedPaths', True, None, False),
  ('Component', 'facetComponents', True, None, True),
  ('Type', 'issueType', False, None, True),
  ('Priority', 'facetPriority', False, None, False),
  ('Labels', 'labels', False, None, True),
  ('Attachment?', 'attachments', False, None, False),
  ('Commits?', 'hasCommits', False, None, False),
  ('Has votes?', 'hasVotes', True, None, False),
  ('Reporter', 'reporter', False, None, True),
  ('Assignee', 'assignee', False, None, True),
  ('Resolution', 'resolution', False, None, False),
  #('Created', 'facetCreated', True, None, False),
  )

jiraSpec.textQueryFields = ['summary', 'description']
# nocommit can we do key descending as number...?
jiraSpec.browseOnlyDefaultSort = 'recentlyUpdated'
jiraSpec.finish()

escape = util.escape

chars = string.ascii_lowercase + string.digits

def makeID():
  return ''.join(random.choice(chars) for x in range(12))

def prettyPrintJSON(obj):
  print(json.dumps(obj,
                   sort_keys=True,
                   indent=4, separators=(',', ': ')))

def facetEscape(s):
  #print('%s, %s' % (type(s), s))
  return s.replace('\\', '\\\\').replace('/', '\\/')

def facetUnescape(s):
  # madness, but it works:
  return s.replace('\\/', '/').replace('\\\\', '\\')

def facetPathToString(tup):
  return '/'.join([facetEscape(x) for x in tup])

def facetStringToPath(s):
  l = s.split('/')
  upto = 0
  while upto < len(l):
    p = l[upto]
    if p[-1:] == '\\' and p[-2:-1] != '\\':
      l[upto] = l[upto] + '/' + l[upto+1]
      del l[upto+1]
    else:
      l[upto] = facetUnescape(l[upto])
      upto += 1
  return tuple(l)
  
def facetCommaEscape(s):
  # madness, but it works:
  return s.replace('\\', '\\\\').replace(',', '\\,')

def facetCommaUnescape(s):
  # madness, but it works:
  return s.replace('\\,', ',').replace('\\\\', '\\')

def facetValuesToString(tup):
  return ','.join([facetCommaEscape(x) for x in tup])

def facetStringToValues(s):
  l = s.split(',')
  upto = 0
  while upto < len(l):
    p = l[upto]
    if p[-1:] == '\\' and p[-2:-1] != '\\':
      l[upto] = l[upto] + ',' + l[upto+1]
      del l[upto+1]
    else:
      l[upto] = facetCommaUnescape(l[upto])
      upto += 1
  return tuple(l)

def justText(s):
  if s is None:
    return 'N/A'
  elif type(s) is list:
    w = []
    if len(s) != 1:
      raise RuntimeError('this text was snippeted')
    snippet = s[0]
    if type(snippet) is dict:
      snippet = snippet['parts']
    for part in snippet:
      if type(part) is str:
        if type(part) is bytes:
          part = part.decode('utf-8')
        w.append(part)
      else:
        text = part['text']
        if text is bytes:
          text = text.decode('utf-8')
        w.append(text)

    return ''.join(w)
  else:
    return s

def renderPagination(w, page, endPage, totalHits, itemLabel):
  #print('PAGE: page=%s endPage=%s' % (page, endPage))
  w('<div class="pagination">')
  w('<ul>')
  start = max(page - 2, 0)
  end = start + 5
  if end > endPage:
    end = endPage
    start = endPage - 5
    if start < 0:
      limit = 5 + start
      start = 0
    else:
      limit = 5
  else:
    limit = 5
  if page > 0:
    w('<li><a href="javascript:g(\'prev\')">&laquo;</a></li>')
  else:
    w('<li class=disabled><a href="#">&laquo;</a></li>')
  for i in range(limit):
    p2 = start + i
    if p2 == page:
      c = ' class=active'
    else:
      c = ''
    w('<li%s><a href="javascript:g(\'page\',%d)">%s</a></li>' % (c, p2, p2+1))
  if page+1 < endPage:
    w('<li><a href="javascript:g(\'next\')">&raquo;</a></li>')
  else:
    w('<li class=disabled><a href="#">&raquo;</a></li>')
  w('</ul>')
  w('<p class="pull-right">%s %s</p>' % (addCommas(totalHits), itemLabel))
  w('</div>')

def addCommas(x):
  x = str(x)
  s = x[-3:]
  x = x[:-3]
  while len(x) > 0:
    s = x[-3:] + ',' + s
    x = x[:-3]
  return s

def sortByUser(s, userDrillDowns):
  if type(s) is list:
    l = []
    for s0 in s:
      key = s0
      if type(key) is list:
        key = unHilite(key)
        if len(s0) == 1 and key in userDrillDowns:
          s0 = [{'text': key, 'term': key}]
      tup = key.split()
      if len(tup) > 1:
        key = '%s %s' % (tup[-1], ' '.join(tup[:-1]))
      l.append((key, s0))
    l.sort()
    s = [x[1] for x in l]
  return s

def unHilite(l):
  s = []
  for x in l:
    if type(x) is str:
      s.append(x)
    else:
      s.append(x['text'])
  return ''.join(s)

reIssue = re.compile('([A-Z]+-\d+)')

def issueToURL(g):
  s = g.group(1)
  return '<a href="https://issues.apache.org/jira/browse/%s">%s</a>' % (s, s)

def fixHilite(s, groupDDField=None, doNonBreakingSpace=False):
  s = _fixHilite(s, groupDDField, doNonBreakingSpace)
  s = reIssue.sub(issueToURL, s)
  return s
  
def _fixHilite(s, groupDDField=None, doNonBreakingSpace=False):
  #return str(s)
  if s is None:
    return 'N/A'
  elif type(s) is list:
    w = []
    for snippet in s:
      # print '  snippet %s' % snippet
      if len(w) > 0:
        if groupDDField is not None:
          w.append(',&nbsp;')
        else:
          w.append('&nbsp;<b>...</b>&nbsp;')
      if groupDDField is not None:
        justText = []
        for part in snippet:
          if type(part) is str:
            if type(part) is bytes:
              part = part.decode('utf-8')
            justText.append(part)
          else:
            text = part['text']
            if text is bytes:
              text = text.decode('utf-8')
            justText.append(text)
        s0 = ''.join(justText)
        if doNonBreakingSpace:
          s0 = nonBreakingSpace(s0)
        w.append('<a class="facet" href="javascript:g(\'dds\', \'%s\', \'%s\')">' % (groupDDField, s0))
      if type(snippet) is dict:
        snippet = snippet['parts']
        
      for part in snippet:
        if type(part) is str:
          if type(part) is bytes:
            part = part.decode('utf-8')
          w.append(escape(part))
        else:
          text = part['text']
          if text is bytes:
            text = text.decode('utf-8')
          w.append('<b>%s</b>' % escape(text))

      if groupDDField is not None:
        w.append('</a>')
          
    return ''.join(w)
  elif groupDDField is not None:
    s0 = escape(s)
    if doNonBreakingSpace:
      s0 = nonBreakingSpace(s0)
    return '<a class="facet" href="javascript:g(\'dds\', \'%s\', \'%s\')">%s</a>' % (groupDDField, s, s0)
  else:
    return escape(s)

class RenderFacets:

  def __init__(self, w, spec, drillDowns, facets, treeFacetMap, ddExtraMap, moreFacetsURL):
    self.w = w
    self.spec = spec
    self.drillDowns = drillDowns
    self.facets = facets
    self.treeFacetMap = treeFacetMap
    self.ddExtraMap = ddExtraMap
    self.moreFacetsURL = moreFacetsURL

  def render(self, name, path, index, doNumericSort=False, reverseSort=False, treeFacetMap=None, allFacets=None, doMorePopup=False):
    w = self.w
    drillDowns = self.drillDowns
    if self.facets[index] is None:
      # This dim had no facet counts
      return
    values = self.facets[index]['counts']
    totalNumValues = self.facets[index]['childCount']
    allFacets = self.facets
    treeFacetMap = self.treeFacetMap

    if len(values) < 2:
      return

    w('<tr>')
    if len(path) == 1:
      w('<td style="padding-bottom:10px">')
    else:
      w('<td>')
    ddName = path[0]
    top = values[0]
    topCount = top[1]
    values = values[1:]
    hasExtra = False
    #print('check extra %s vs %s' % (ddName, self.ddExtraMap))
    if ddName in self.ddExtraMap:
      extra = self.facets[self.ddExtraMap[ddName]]['counts'][1:]
      #print '  filtered %s' % extra
      if len(extra) > 0:
        seen = set([x[0] for x in values])
        #print ' seen: %s %s' % (len(seen), seen)
        for v, count in extra:
          if v not in seen:
            values.append((v, count))
        hasExtra = True
        #print '  path: %s' % str(path)
        #print '  add extra; now: %s' % values

    if name == 'Optical zoom':
      values.sort(key=opticalZoomSort)
    elif name == 'Weight':
      values.sort(key=weightSort)
    elif doNumericSort:
      if reverseSort:
        values.sort(key=toNumberReverse)
      else:
        values.sort(key=toNumber)
    elif hasExtra:
      values.sort(key=toCount)

    ddValues = None
    for field, ddv in drillDowns:
      if field == ddName:
        ddValues = ddv
        break

    if len(path) == 1:
      if path[0] == 'fixVersions':
        extras = values[5:]
        values = values[:5]
        if ddValues is not None:
          byValue = {}
          for v, c in extras:
            byValue[v] = c
          changed = False
          for ddValue in ddValues:
            for v, c in values:
              if ddValue[0] == v:
                break
            else:
              changed = True
              values.append((ddValue[0], byValue.get(ddValue[0], 0)))
          if changed:
            values.sort(key=toNumberReverse)
              
      if ddValues is None:
        color = 'black'
      else:
        color = 'red'
      w('<a name="%s"><font color=%s><b>%s</b></font></a>' % (path[0], color, name))
      w('<table class=facet cellpadding=0 cellspacing=0>')
      w('<tr>')
      w('<td>')
      if ddValues is None:
        w(CHECKMARK)
      w('</td>')
      w('<td>')
      w('<nobr><a class="facet" href="javascript:g(\'du\', \'%s\')"><b><em>All</em></b></a></nobr>' % ddName)
      w('</td>')
      w('</tr>')

    for label, count in values:
      if len(path) > 1:
        newPath = tuple(path[1:] + [label])
      else:
        newPath = (label,)

      if label == '1':
        label = 'Yes'
      elif label == '0':
        label = 'No'

      w('<tr>')
      w('<td>')
      if ddValues is not None and newPath in ddValues:
        w(CHECKMARK)
      else:
        w('&nbsp;&nbsp;')
      w('</td>')
      w('<td>')
      w('&nbsp;&nbsp;&nbsp;' * (len(path)-1))
      if len(label) > 25:
        shortLabel = label[:22] + '...'
      else:
        shortLabel = label
      w('<nobr><a class="facet" href="" onclick="g(fcmd(event), \'%s\', \'%s\');return false;">%s</a> <font size=-2 color="#888888">(%d)</font></nobr>' % \
        (ddName, facetPathToString(newPath).replace('\'', '\\\''), shortLabel, count))
      w('</td>')
      if self.spec.facetByID[path[0]][0]:
        # recurse
        #print '%s, %s' % (ddName, label)
        idx = treeFacetMap.get((ddName, newPath))
        if idx is not None:
          #print '  do recurse'
          self.render(name, path + [label], idx, doNumericSort=doNumericSort, reverseSort=reverseSort)

      w('</tr>')

    if doMorePopup and totalNumValues > len(values):
      w('<tr><td></td><td>')
      w('<br>')
      w('<a data-toggle="modal" role="button" data-target="#pickMore%s" href="%s&dim=%s"><em>See all %d...</em></a>' % (path[0], self.moreFacetsURL, ddName, totalNumValues))
      w('<div id="pickMore%s" class="modal hide fade in">' % path[0])
      w('<div class="modal-header">')
      w('<h3 id="myModalLabel">All %s values</h3>' % name)
      w('</div>')
      w('<div class="modal-body">')
      w('<em>Loading...</em>')
      w('</div>')
      w('<div class="modal-footer">')
      w('<button class="btn" data-dismiss="modal" aria-hidden="true">Cancel</button>')
      w('</div>')
      w('</div>')
      w('</td></tr>')

    if len(path) == 1:
      w('</table>')
      w('</td>')
      w('</tr>')

class Buffer:
  def __init__(self):
    self.l = []

  def add(self, s):
    self.l.append(str(s))

CHECKMARK = '&#x2713;'

reNumber = re.compile(r'^[\-0-9]+\.[0-9]+')

def toNumber(x):
  try:
    return float(reNumber.search(x[0]).group(0))
  except:
    return float('inf')

def toNumberReverse(x):
  try:
    return -float(reNumber.search(x[0]).group(0))
  except:
    return float('inf')

opticalZoomSortOrder = [
  '1x',
  '1x-3x',
  '3x-6x',
  '6x-10x',
  '10x-20x',
  'Over 20x',
  ]

def opticalZoomSort(x):
  return opticalZoomSortOrder.index(x[0])

weightSortOrder = [
  '0 - .25',
  '.25 - .50',
  '.50 - .75',
  '.75 - 1.0',
  'Over 1.0',
  ]

def weightSort(x):
  return weightSortOrder.index(x[0])

def toCount(x):
  return -x[1]

def handleSuggest(path, isMike, environ):

  send = util.ServerClient().send

  i = path.find('?')
  if i != -1:
    args = urllib.parse.parse_qs(path[i+1:])
    path = path[:i]
  else:
    args = {}

  index = 'jira'

  spec = jiraSpec
  
  #print 'suggest: %s' % args
  t0 = time.time()
  if 'term' not in args:
    return '', []
  text = args['term'][0].strip()

  projectPrefixes = []
  while True:
    for project in allProjects:
      if text.lower().startswith(project.lower() + ' '):
        projectPrefixes.append(project)
        text = text[len(project)+1:]
        break
    else:
      break
        
  source = args['source'][0]
  req = {'indexName': spec.indexName,
         'suggestName': source,
         'text': text,
         'highlight': True,
         'count': 10}

  if len(projectPrefixes) > 0:
    req['contexts'] = projectPrefixes
  elif 'contexts' in args:
    req['contexts'] = args['contexts'][0].split(',')
  
  if source.endswith('.infix'):
    req['allTermsRequired'] = True

  res = send('suggestLookup', req)
  
  l = []
  for hit in res['results']:
    #print('HIT: %s' % hit)
    d = {}
    d['label'] = renderSuggestHighlight(hit['key'])
    payload = hit.get('payload')
    if payload is not None:
      if payload[:5] == 'user ':
        # A username
        d['user'] = payload[5:]
        d['label'] = 'user: \"%s\"' % d['label']
      elif payload[:8] == 'project ':
        # A project
        d['project'] = payload[8:]
        d['label'] = 'project: %s' % d['label']
      else:
        # An issue
        d['volLink'] = 'http://issues.apache.org/jira/browse/%s' % payload.upper()
    #l.append(hit['key'])
    #l.append('<img src=%s/> %s' % (tup[1], tup[0]))
    l.append(d)
  s = json.dumps(l)
  # print('RET: %s' % s)
  util.log('%.1f msec' % (1000*(time.time()-t0)))
  return s, []

def renderSuggestHighlight(o):
  #print("FRAGS: %s" % o)
  if type(o) is list:
    s = []
    for fragment in o:
      if fragment['isHit']:
        s.append('<font color="red">')
      s.append(fragment['text'])
      if fragment['isHit']:
        s.append('</font>')
    return ''.join(s)
  else:
    return o

def makeSort(spec, sort):
  userLabel, field, reverse = spec.sortByID[sort]
  d = {'field': field}
  if field not in ('docid', 'score'):
    d['reverse'] = reverse
  return {'fields': [d]}

def getUTCOffset():
  if time.localtime(time.time()).tm_isdst and time.daylight:
    return time.altzone
  else:
    return time.timezone

def addUnit(x, unit):
  if str(x) == '1.0':
    return '1 %s' % unit
  elif str(x).endswith('.0'):
    return '%s %ss' % (x[:-2], unit)
  else:
    return '%s %ss' % (x, unit)

def toAgo(seconds):
  seconds = float(seconds)
  if seconds < 60:
    return addUnit(int(seconds), 'second')
  elif seconds < 3600:
    return addUnit('%.1f' % (seconds/60), 'minute')
  elif seconds < 24*3600:
    return addUnit('%.1f' % (seconds/3600), 'hour')
  elif seconds < 30.5*24*3600:
    return addUnit('%.1f' % (seconds/24/3600), 'day')
  elif seconds < 365*24*3600:
    return addUnit('%.1f' % (seconds/24/3600/30.5), 'month')
  else:
    return addUnit('%.1f' % (seconds/24/3600/365), 'year')

def renderNavSummary(w, facets, drillDowns):
  w('<b>Filters:</b>&nbsp;')
  for idx, (userLabel, dim, ign, facetSort, doMorePopup) in enumerate(jiraSpec.facetFields):
    if facets[idx] is None:
      # no facet counts for this dim for this query
      continue
    if idx > 0:
      w(',&nbsp;&nbsp;')
    if False:
      w('<select name=%s>' % dim)
      w('<option>%s</option>' % userLabel)
      w('</select>')

    ddValues = None
    for field, ddv in drillDowns:
      if field == dim:
        ddValues = ddv
        break

    if ddValues is not None:
      w('<a href="#%s"><b><font color=red>%s (%s)</font></b></a>' % (dim, userLabel, ','.join([x[0] for x in ddValues])))
    else:
      w('<a href="#%s">%s</a>' % (dim, userLabel))
      
  w('<br>')
  
def renderJiraHits(w, text, groups, userDrillDowns):

  now = int(time.time() + getUTCOffset())

  lowerText = text.strip().lower().replace('-', ' ')

  # Each group is a Jira issue; each (child) doc is a comment on that issue
  for group in groups:
    fields = group['fields']
    key = fields['key'].upper()

    # hack alert!  really i should index a separate text+highlight field for this...
    if key.lower().replace('-', ' ') == lowerText:
      key = '<b>%s</b>' % key
    
    if fields['status'] in ('Open', 'Reopened', 'In Progress'):
      skey = key
    else:
      skey = '<s>%s</s>' % key

    w('<tr><td><br><a href="http://issues.apache.org/jira/browse/%s"><font size=+2>%s: %s</font></a></td></tr>' % \
      (key, skey, fixHilite(fields['summary'])))

    w('<tr><td><em><font size=-1>%s ago&nbsp;&nbsp;%d comments&nbsp;&nbsp;%d votes&nbsp;&nbsp;%d watches&nbsp;&nbsp;%s</em></font></td></tr>' % \
      (toAgo(now-fields['updated']),
       fields['commentCount'],
       fields['voteCount'],
       fields['watchCount'],
       fixHilite(sortByUser(fields['allUsers'], userDrillDowns), 'allUsers')))
    w('<tr><td>')
    s = fixHilite(fields.get('description', ''))
    issueURL = 'http://issues.apache.org/jira/browse/%s' % key
    w('<a class="commentsnippet" href="%s">%s</a>' % (issueURL, s))
    w('</td></tr>')
    
    # Each hit is a comment under one issue:
    w('<tr>')
    w('<td>')
    w('<table>')
    for hitIdx, hit in enumerate(group['hits']):
      fields = hit['fields']
      w('<tr>')
      w('<td>')
      author = fields.get('author')
      if isCommitUser(author):
        author = 'commitbot'
      if 'commitURL' in fields:
        commentURL = fields['commitURL']
        if 'git-wip-us' in commentURL:
          commentURL += ';a=commitdiff'
      else:
        commentURL = 'http://issues.apache.org/jira/browse/%s?focusedCommentId=%s&page=com.atlassian.jira.plugin.system.issuetabpanels:comment-tabpanel#comment-%s' % \
                     (key, fields['commentID'], fields['commentID'])

      #authorDD = '<a href="" onclick="g(fcmd(event), \'allUsers\', \'%s\');return false;"><b>%s</b></a>' % (author, nonBreakingSpace(fixHilite(author, 'allUsers')))
      authorDD = '<b>%s</b>' % fixHilite(author, 'allUsers', True)
      w('&nbsp;&nbsp;&nbsp;&nbsp;%s&nbsp;<em>%s&nbsp;ago</em>:&nbsp;&nbsp;</td><td><a class="commentsnippet" href="%s">%s</a>' % \
        (authorDD,
         nonBreakingSpace(toAgo(now - fields['created'])), commentURL, fixHilite(fields.get('body'))))
      w('</td>')
      w('</tr>')
    w('</table>')
    w('</td>')
    w('</tr>')

def nonBreakingSpace(s):
  return s.replace(' ', '&nbsp;')  
      
def renderCamHits(w, hits):

  now = int(time.time() + getUTCOffset())
  w('<tr>')
  w('<th>Image</th>')
  w('<th>Camera</th>')
  w('<th>Announced</th>')
  w('<th>Weight (lb)</th>')
  w('</tr>')
  today = datetime.datetime.now().date()
  twoYears = datetime.timedelta(days=365*2)

  for hit in hits:
    fields = hit['fields']
    w('<tr>')
    w('<td>')
    if 'Image' in fields:
      w('<img src="%s">'% fields['Image'].replace('dpreview/images', 'cams/images'))
    w('</td>')
    x = '<font size=+1>%s</font>' % fields['Name']
    url = fields.get('DPReviewURL')
    if url is not None:
      #x = '<a href="%s">%s</a>' % (url, x)
      #print('HERE: %s' % urllib.parse.quote_plus(fields['Name']))
      x = '<a href="http://www.bing.com/search?q=%s">%s</a>' % (urllib.parse.quote_plus(fields['Name']), x)
    v = fields.get('Megapixels')
    if v is not None:
      x += '<br>%.1f mp' % v
      v = fields.get('Sensor')
      if v is not None:
        x += ', %s' % v
        if v == '1':
          x += '"'
      v = fields.get('OpticalZoom')
      if v is not None:
        x += ', %gx zoom' % v

    v = fields.get('Lens')
    if v is not None:
      x += '<br>%s' % v

    #v = fields.get('Type')
    #if v is not None:
    #  x += '<br>%s' % v
    w('<td>%s</td>' % x)

    x = fields.get('Announced')
    if x is not None:
      x = datetime.datetime.fromtimestamp(x).date()
      gap = today - x
      if gap > twoYears:
        s = '%s' % x.year
      else:
        s = x.strftime('%b %Y')
    else:
      s = ''
    w('<td>%s</td>' % s)

    x = fields.get('Weight')
    if x is not None:
      s = '%.2f' % x
    else:
      s = ''
    w('<td>%s</td>' % s)
      
    w('</tr>')
   
def renderGroupHeader(w, group, groupDDField, hitsPerGroup):
  w('<tr><td>&nbsp;</td></tr>')
  count = group['totalHits']
  w('<tr><td colspan=4 width=100%% bgcolor="#dddddd"><font size=+1>%s</font> (1-%d of %d <a class="facet" href="javascript:document.forms[0].group.value=\'None\';g(\'dds\', \'%s\', \'%s\')">See all</a>)</td></tr>' % \
    (escape(group['groupValue']),
     min(count, hitsPerGroup),
     count,
     groupDDField,
     group['groupValue']))

def handleMoreFacets(path, isMike, environ):

  send = util.ServerClient().send

  i = path.find('?')
  if i != -1:
    args = urllib.parse.parse_qs(path[i+1:])
    path = path[:i]
  else:
    args = {}

  # print('moreFacets args: %s' % args)

  index = 'jira'

  spec = jiraSpec
  
  _l = []
  w = _l.append

  dim = args['dim'][0]
  query = {}
  query['indexName'] = spec.indexName
  if 'text' in args:
    query['query'] = spec.buildTextQuery(args['text'][0])
  else:
    query['query'] = {'class': 'BooleanFieldQuery', 'field': 'parent'}

  now = int(time.time() + getUTCOffset())
  
  drillDowns = []

  if 'dd' in args:
    for v in args['dd']:
      field, values = v.split(':', 1)
      drillDowns.append((field, [facetStringToPath(x) for x in facetStringToValues(values)]))
    
    l2 = []
    for field, values in drillDowns:
      for value in values:
        if field == 'updated':
          # nocommit should use the 'now' as of when the query had started!
          for d in getTimeFacets(now):
            if d['label'] == value[0]:
              l2.append({'field': field,
                         'numericRange': d})
              break
          else:
            raise RuntimeError('failed to find numericRange label %s' % value)
        elif field == 'updatedAgo':
          for d in getOldTimeFacets(now):
            if d['label'] == value[0]:
              l2.append({'field': 'updated',
                         'numericRange': d})
              break
          else:
            raise RuntimeError('failed to find numericRange label %s' % value)
        else:
          l2.append({'field': field, 'value': value})

    query['drillDowns'] = l2

  query['facets'] = [{'dim': dim, 'topN': MAX_INT}]

  query['facets'].append({'dim': 'updated', 'numericRanges': getTimeFacets(now)})

  if TRACE:
    print('MoreFacets query:')
    prettyPrintJSON(query)

  result = send('search', query)

  if TRACE:
    print('MoreFacets response:')
    prettyPrintJSON(result)
    
  values = result['facets'][0]['counts'][1:]
  values.sort()
  for label, count in values:
    newPath = [label]
    w('<br><nobr><a class="facet" href="" onclick="g(fcmd(event), \'%s\', \'%s\');return false;">%s</a> <font size=-2 color="#888888">(%d)</font></nobr>' % \
      (dim, facetPathToString(newPath).replace('\'', '\\\''), label, count))
  
  return ''.join(_l), []

def getTimeFacets(now):
  return [
    {'label': 'Past day', 'min': now-24*3600, 'max': now, 'minInclusive': True, 'maxInclusive': True},
    {'label': 'Past 2 days', 'min': now-2*24*3600, 'max': now, 'minInclusive': True, 'maxInclusive': True},
    {'label': 'Past 3 days', 'min': now-3*24*3600, 'max': now, 'minInclusive': True, 'maxInclusive': True},
    {'label': 'Past week', 'min': now-7*24*3600, 'max': now, 'minInclusive': True, 'maxInclusive': True},
    {'label': 'Past month', 'min': int(now-30.5*24*3600), 'max': now, 'minInclusive': True, 'maxInclusive': True},
    ]

def getOldTimeFacets(now):
  return [
    {'label': '> 1 day ago', 'min': 0, 'max': now-24*3600, 'minInclusive': True, 'maxInclusive': True},
    {'label': '> 2 days ago', 'min': 0, 'max': now-2*24*3600, 'minInclusive': True, 'maxInclusive': True},
    {'label': '> 3 days ago', 'min': 0, 'max': now-3*24*3600, 'minInclusive': True, 'maxInclusive': True},
    {'label': '> 1 week ago', 'min': 0, 'max': now-7*24*3600, 'minInclusive': True, 'maxInclusive': True},
    {'label': '> 1 month ago', 'min': 0, 'max': int(now-30.5*24*3600), 'minInclusive': True, 'maxInclusive': True},
    {'label': '> 3 months ago', 'min': 0, 'max': int(now-3*30.5*24*3600), 'minInclusive': True, 'maxInclusive': True},
    {'label': '> 1 year ago', 'min': 0, 'max': int(now-365.25*24*3600), 'minInclusive': True, 'maxInclusive': True},
    ]

def printTokens(send):
  ICU_RULES = open('Latin-dont-break-issues.rbbi').read()
  #ICU_RULES = open('/l/luceneserver/lucene6x/lucene/analysis/icu/src/test/org/apache/lucene/analysis/icu/segmentation/Latin-dont-break-on-hyphens.rbbi').read()

  # Latn customized to keep AAAA-NNNN tokens:
  ICU_TOKENIZER_KEEP_ISSUES = {
    'class': 'icu',
    'rules': [{'script': 'Latn', 'rules': ICU_RULES}]}

  analyzer = {
    'tokenizer': ICU_TOKENIZER_KEEP_ISSUES,
    #'tokenizer': 'Standard',
    'tokenFilters': ['EnglishPossessive',
                     {'class': 'WordDelimiter',
                      'preserveOriginal': 1},
                     'LowerCase',
                     {'class': 'Synonym',
                      'analyzer': {
                        'tokenizer': ICU_TOKENIZER_KEEP_ISSUES,
                        'tokenFilters': ['EnglishPossessive',
                                         'LowerCase']},
                      'synonyms': [
                        {'input': ['oom', 'oome', 'OutOfMemory', 'OutOfMemoryError', 'OutOfMemoryException'], 'output': 'OutOfMemoryError'},
                        {'input': ['ir', 'IndexReader'], 'output': 'IndexReader'},
                        {'input': ['rob', 'robert'], 'output': 'robert'},
                        {'input': ['hilite', 'highlight'], 'output': 'highlight'},
                        {'input': ['iw', 'IndexWriter'], 'output': 'IndexWriter'},
                        {'input': ['replicator', 'replication'], 'output': 'replication'},
                        {'input': ['join', 'joining'], 'output': 'join'},
                        {'input': ['drill down', 'drilldown'], 'output': 'drilldown'},
                        {'input': ['ms', 'microsoft'], 'output': 'microsoft'},
                        {'input': ['ssd', 'solid state disk'], 'output': 'ssd'},
                        {'input': ['nrt', 'near-real-time', 'near real-time', 'near-real time', 'near real time'], 'output': 'nrt'},
                        # nocommit is doc values / docvalues working "for free"?
                        {'input': ['doc values', 'docvalue'], 'output': 'docvalue'},
                        {'input': ['js', 'javascript'], 'output': 'javascript'},
                        {'input': ['smoke tester', 'smokeTester'], 'output': 'smokeTester'},
                        ]},
                     'Stop',
                     'EnglishMinimalStem']}

  print('TOKENS')
  prettyPrintJSON(send('analyze', {'analyzer': analyzer, 'indexName': 'jira', 'text': 'Commit ebb2127cca54e49ed5c7462d11ee8dda6125e287'}))

def handleQuery(path, isMike, environ):

  send = util.ServerClient().send
  #printTokens(send)

  t0 = time.time()

  # TODO: do "full browse" UI if no search yet

  origPath = path
  
  i = path.find('?')
  if i != -1:
    args = urllib.parse.parse_qs(path[i+1:])
    path = path[:i]
  else:
    args = {}

  index = 'jira'

  spec = jiraSpec

  _l = Buffer()
  w = _l.add

  if 'format' in args:
    format = args['format'][0]
  elif spec.showGridOrList:
    format = 'grid'
  else:
    format = 'list'

  # print 'path %s, args %s' % (path, args)

  if False:
    print()
    print('ARGS: path=%s, %s' % (path, args))

  if 'text' in args:
    text = args['text'][0]
  else:
    text = None

  if format == 'list':
    perPage = spec.perPageList
  else:
    perPage = spec.perPageGrid
    
  if 'page' in args:
    page = int(args['page'][0])
  else:
    page = 0

  if 'infixSuggest' in args:
    infixSuggest = args['infixSuggest'][0] == 'on'
  else:
    infixSuggest = True

  if 'sort' in args:
    sort = args['sort'][0]
  else:
    sort = 'relevanceRecency'

  if 'group' in args:
    groupBy = args['group'][0]
    if groupBy == 'None':
      groupBy = None
  else:
    groupBy = None

  if 'groupSort' in args:
    groupSort = args['groupSort'][0]
  else:
    groupSort = 'relevance'

  # TODO: support multi-select

  headers = []

  # TODO: must escape embedded ;,:!
  drillDowns = []
  if 'dd' in args:
    for v in args['dd']:
      field, values = v.split(':', 1)
      drillDowns.append((field, [facetStringToPath(x) for x in facetStringToValues(values)]))

  if 'chg' in args:
    command = args['chg'][0]
    if command == 'new':
      # Start a new search
      page = 0
      if False:
        drillDowns = [x for x in drillDowns if x[0] in ('project', 'status')]
        if 'status' not in [x[0] for x in drillDowns]:
          drillDowns.append(('status', [('Open',)]))

      sort = 'relevanceRecency'
    elif command == 'next':
      # Next page
      page += 1
    elif command == 'prev':
      # Previous page
      page -= 1
    elif command == 'page':
      # Set page
      page = int(args['a1'][0])
    elif command == 'dds':
      # Drill down, single-select
      page = 0
      field = args['a1'][0]
      label = facetStringToPath(args['a2'][0])
      for idx, (field2, values) in enumerate(drillDowns):
        if field2 == field:
          # Replace existing drill down on this field:
          drillDowns[idx] = (field, [label])
          break
      else:
        # First drill down on this field:
        drillDowns.append((field, [label]))
      
    elif command == 'ddm':
      # Drill down, multi-select (user did shift + click):
      page = 0
      field = args['a1'][0]
      label = facetStringToPath(args['a2'][0])
      for idx, (field2, values) in enumerate(drillDowns):
        if field2 == field:
          if label in values:
            # Exact match; toggle:
            values.remove(label)
            if len(values) == 0:
              del drillDowns[idx]
          elif spec.facetByID[field][0]:
            upto = 0
            while upto < len(values):
              v = values[upto]
              if len(label) > len(v) and label[:len(v)] == v:
                # Refining to child:
                values.remove(v)
              elif len(v) > len(label) and v[:len(label)] == label:
                # Un-refining back to parent:
                values.remove(v)
              else:
                upto += 1
            values.append(label)
          else:
            values.append(label)
          break
      else:
        drillDowns.append((field, [label]))
    elif command == 'du':
      # Drill up
      field = args['a1'][0]
      drillDowns = [x for x in drillDowns if x[0] != field]
  else:
    command = None
    field = None

  if command != 'du' or field != 'project':
    cookie = environ.get('HTTP_COOKIE')
    if cookie is not None:
      c = http.cookies.SimpleCookie(cookie)
      c = c.get('lastProject')
      if c is not None:
        lastProject = c.value
        if len(lastProject) > 0:
          # Insert lastProject via cookie, if current query didn't drill-down on project yet:
          for field, values in drillDowns:
            if field == 'project':
              break
          else:
            util.log('add lastProject=%s from cookie' % lastProject)
            drillDowns.append(('project', [(x,) for x in lastProject.split(',')]))

  if groupBy is not None:
    groupDDField = spec.groupByID[groupBy][1]
  else:
    groupDDField = None

  query = {}
  query['indexName'] = spec.indexName
  
  if text in ('*', '*:*'):
    text = None

  if text is not None:
    query['query'] = spec.buildTextQuery(text)
  else:
    query['query'] = spec.buildBrowseOnlyQuery()
    
  # nocommit must 'fix' now when session starts but ... aggressively reset it:
  now = int(time.time() + getUTCOffset())

  # nocommit why?
  #query['query'] = {'class': 'BooleanFieldQuery', 'field': 'parent'}

  thirtyDays = 30*24*3600.0

  # If the issue was updated less than 30 days ago, boost linearly
  # up to 2 * score (for an issue updated 0 seconds ago) to 1 *
  # score (for an issue updated 30 days ago):
  #print('now=%s' % now)
  query['virtualFields'] = [
    {'name': 'scoreOrig', 'expression': '_score'},
    {'name': 'age', 'expression': '%s - updated' % now},
    {'name': 'boost', 'expression': '(age >= %s) ? 1.0 : (1.0 + (%s - age)/%s)' % (thirtyDays, thirtyDays, thirtyDays)},
    {'name': 'blendRecencyRelevance', 'expression': 'boost * _score'}]
      
  if text is None:
    text = ''

  if text == '':
    if sort.startswith('relevance'):
      sort = spec.browseOnlyDefaultSort
    if groupSort.startswith('relevance'):
      groupSort = spec.browseOnlyDefaultSort

  # print 'sort2 %s' % sort
    
  query['topHits'] = (page+1)*perPage

  if sort != 'relevance':
    query['sort'] = makeSort(spec, sort)

  if format == 'list':
    groupsPerPage = 2
    hitsPerGroup = 2
  else:
    groupsPerPage = 4
    hitsPerGroup = 4

  if groupBy is not None:
    query['grouping'] = {'field': groupBy,
                         'groupStart': page * groupsPerPage,
                         'hitsPerGroup': hitsPerGroup,
                         'groupsPerPage': (page+1)*groupsPerPage,
                         'doTotalGroupCount': True}
    if groupSort != 'relevance':
      query['grouping']['sort'] = makeSort(spec, groupSort)['fields']

  #query['retrieveFields'] = ['thumbnailURL', 'title', 'previewURL', 'volURL', 'description']
  query['retrieveFields'] = spec.retrieveFields + ('age', 'boost',
                                                   'blendRecencyRelevance', 'scoreOrig')
  #query['retrieveFields'] = ['thumbnailURL', {'field': 'title', 'highlight': True, 'snippet': False}, 'previewURL', 'volURL', 'description']

  if page > 0:
    if groupBy is None:
      query['startHit'] = page*perPage

  l = []
  sawGroupDDField = False

  for userLabel, dim, ign, ign, doMorePopup in spec.facetFields:
    if dim in ('fixVersions', 'committedPaths', 'attachments'):
      topN = MAX_INT
    else:
      topN = 7
    if dim == 'updated':
      d = {'dim': dim, 'numericRanges': getTimeFacets(now)}
    elif dim == 'updatedAgo':
      d = {'dim': 'updatedAgo', 'numericRanges': getOldTimeFacets(now)}
    else:
      d = {'dim': dim, 'topN': topN}
    l.append(d)
    if dim == groupDDField:
      sawGroupDDField = True

  treeFacetMap = {}

  for field, values in drillDowns:
    if spec.facetByID[field][0]:
      for tup in values:
        assert type(tup) is tuple, 'got %s' % str(tup)
        for i in range(len(tup)):
          treeFacetMap[(field, tup[:i+1])] = len(l)
          if field in ('committedPaths',):
            topN = MAX_INT
          else:
            topN = 7
          l.append({'dim': field,
                    'path': list(tup[:i+1]),
                    'topN': topN})
          if field == groupDDField:
            sawGroupDDField = True

  if groupDDField is not None and not sawGroupDDField:
    l.append({'dim': groupDDField, 'topN': 7})
    
  # print('facets request: %s' % l)
  ddExtraMap = {}
  if len(drillDowns) > 0:
    l2 = []
    for field, values in drillDowns:
      for value in values:
        if field == 'updated':
          # nocommit should use the 'now' as of when the query had started!
          for d in getTimeFacets(now):
            if d['label'] == value[0]:
              l2.append({'field': field,
                         'numericRange': d})
              break
          else:
            raise RuntimeError('failed to find numericRange label %s' % value)
        elif field == 'updatedAgo':
          for d in getOldTimeFacets(now):
            if d['label'] == value[0]:
              l2.append({'field': 'updatedAgo',
                         'numericRange': d})
              break
          else:
            raise RuntimeError('failed to find numericRange label %s' % value)
        else:
          l2.append({'field': field, 'value': value})

      if field not in ('updated', 'updatedAgo') and not spec.facetByID[field][0]:
        ddExtraMap[field] = len(l)
        l.append({'dim': field, 'labels': values[0]})
                  
    query['drillDowns'] = l2

  query['facets'] = l

  if spec.highlighter is not None:
    query['highlighter'] = spec.highlighter

  ta = time.time()
  if TRACE:
    print()
    print('REQUEST')
    prettyPrintJSON(query)
  result = send('search', query)
  if TRACE:
    print()
    print('RESPONSE')
    prettyPrintJSON(result)
    print()
    print('STATS')
    prettyPrintJSON(send('stats', {'indexName': spec.indexName}))

  if DO_PROX_HIGHLIGHT:

    if spec.highlighter is None:
      h = {'passageScorer.proxScoring': False,
           'class': 'PostingsHighlighter'}
    else:
      h = copy.deepcopy(spec.highlighter)
      h['passageScorer.proxScoring'] = False
    query['highlighter'] = h

    print('send2')
    resultNoProx = send('search', query)
    hitsNoProx = resultNoProx['hits']
    if TRACE:
      print()
      print('RESPONSE NO PROX')
      prettyPrintJSON(resultNoProx)
  else:
    hitsNoProx = None
    
  searchTime = time.time()-ta
  
  # print 'results: %s' % result

  w('<!DOCTYPE html>')
  w('<html lang="en">')
  w('<head>')
  w('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
  w('<meta charset="utf-8"/>')
  w('<link rel="stylesheet" href="bootstrap/css/bootstrap-responsive.min.css" media="screen"/>')
  #w('<link rel="stylesheet" href="bootstrap/css/bootstrap-responsive.css" media="screen"/>')
  w('<link rel="stylesheet" href="bootstrap/css/bootstrap.min.css"/>')
  w('<link rel="stylesheet" href="css/ui-lightness/jquery-ui-1.10.1.custom.min.css" />')
  #w('<link rel="stylesheet" href="select2/select2.css"/>')
  #w('<script src="bootstrap/js/bootstrap.min.js"/>')
  w('<script src="js/jquery-1.9.1.js"></script>')
  #w('<script src="select2/select2.min.js"></script>')
  w('<script src="js/jquery-ui-1.10.1.custom.min.js"></script>')
  w('<script src="bootstrap/js/bootstrap.js"></script>')

  contexts = []
  userDrillDowns = set()
  project = None
  if len(drillDowns) > 0:
    for field, values in drillDowns:
      if field == 'project':
        contexts = [x[0] for x in values]
        project = ','.join(contexts)
      elif field == 'allUsers':
        for x in values:
          userDrillDowns.add(x[0])

  # print('userDrillDowns=%s' % str(userDrillDowns))
  
  if spec.doAutoComplete:
    if True:
      w('''
      <script>
      $(document).ready(      
        function() {
        $("#textid").keydown(function(event){
          // Crazy logic so "tab" jumps to first suggestion:
          var newEvent = $.Event('keydown', {
            keyCode: event.keyCode
          });

          if (newEvent.keyCode !== $.ui.keyCode.TAB) {
            return;
          }

          newEvent.keyCode = $.ui.keyCode.DOWN;
          $(this).trigger(newEvent);

          newEvent.keyCode = $.ui.keyCode.ENTER;
          $(this).trigger(newEvent);
          return false;
          });
        $( "#textid" ).autocomplete({
          delay: 0,
          source: function(request, response) {
            var type = "infix";
            /*
            if (document.forms[0].infixSuggest.checked) {
              type = "infix";
            } else {
              type = "prefix";
            }
            */
            request.source = "titles_" + type;
            request.contexts = "%s";
            $.getJSON("/suggest.py", request, response);
          },
          focus: function(event, ui) {
            return false;
          },
          select: function(event, ui) {
            //var s = ui.item.label;
            //s = s.replace(/<b>/g, "");
            //s = s.replace(/<\/b>/g, "");
            //$("#textid").val("");
            //event.stopPropagation();
            if (ui.item.user !== undefined) {
              g("dds", "allUsers", ui.item.user);
            } else if (ui.item.project !== undefined) {
              g("dds", "project", ui.item.project);
            } else {
              window.location = ui.item.volLink;
            }
            event.preventDefault();
          }
        }).data("ui-autocomplete")._renderItem = function(ul, item) {
          if (item.thumb === undefined) {
            return $("<li>").append("<a>" + item.label + "</a>").appendTo(ul);
          } else {
            return $("<li>").append("<a href=" + item.volLink + "><img src=" + item.thumb + "/><div style=\\"display:inline-block;vertical-align:middle\\">" + item.label + "</div></a>").appendTo(ul);
          }
        };
      });
      </script>''' % ','.join(contexts))

  w('\n')
  w('<style>')
  #w('html *\n')
  #w('{\n')
  #w('    font-size: 1em;\n')
  #w('    color: #000;\n')
  #w('    font-family: Arial;\n')
  #w('}\n')

  w('a.commentsnippet {')
  w('  color:black;\n')
  w('}')
  
  w('a.facet {')
  #w('  color:blue;\n')
  w('  cursor:default;\n')
  w('  line-height: 15px;\n')
  #w('  font-size: 7;\n')
  w('  text-decoration:none;\n')
  w('}\n')

  w('img {')
  w('  max-width: 100%;')
  w('}')

  w('table.facet {')
  #w('  color:blue;\n')
  w('  border-collapse: collapse;\n')
  w('  font-size: 13px;\n')
  w('  cursor:default;\n')
  w('  line-height: 10px;\n')
  #w('  font-size: 7;\n')
  #w('  text-decoration:none;\n')
  w('}\n')

  w('a.facet:hover {')
  w('  color:red;\n')
  w('  cursor:default;\n')
  w('  text-decoration:underline;\n')
  w('}\n')

  w('</style>')
  
  w('<script language="JavaScript">\n')

  w('  function fcmd(event) {\n')
  w('    if (event.shiftKey) {\n')
  w('      return "ddm";\n')
  w('    } else {\n')
  w('      return "dds";\n')
  w('    }\n')
  w('  }\n')
  
  w('  function g(chg, a1, a2) {\n')
  w('    document.forms[0].chg.value = chg;\n')
  w('    document.forms[0].a1.value = a1;\n')
  w('    document.forms[0].a2.value = a2;\n')
  w('    document.forms[0].submit();\n')
  w('  }\n')

  w('  function setGrouping(group) {\n')
  w('    document.forms[0].page.value=0;\n')
  w('    document.forms[0].group.value=group;\n')
  w('    document.forms[0].submit();\n')
  w('  }\n')

  w('  function setGroupSort(sort) {\n')
  w('    document.forms[0].page.value=0;\n')
  w('    document.forms[0].groupSort.value=sort;\n')
  w('    document.forms[0].submit();\n')
  w('  }\n')
  
  w('  function setSort(sort) {\n')
  w('    document.forms[0].page.value=0;\n')
  w('    document.forms[0].sort.value=sort;\n')
  w('    document.forms[0].submit();\n')
  w('  }\n')

  w('  function setFormat(format) {\n')
  w('    document.forms[0].page.value=0;\n')
  w('    document.forms[0].format.value=format;\n')
  w('    document.forms[0].submit();\n')
  w('  }\n')

  w('</script>')
  w('''
    <style>
      body {
        padding-top: 60px; /* 60px to make the container go all the way to the bottom of the topbar */
      }
    </style>''')
  w('<script>')
  #w('$(document).ready(function() { $("#cat").select2({placeholder: "See more...", width: "element"}); });')
  w('$(function() {$("#textid").focus();});')
  w('</script>')
  w('</head>')
  w('<body>')

  # Top (black) navbar:
  w('<div class="navbar navbar-inverse navbar-fixed-top">')
  w('  <div class="navbar-inner">')
  w('        <ul class="nav">')
  w('<li class="active pull-left"><a href="/search.py">All Issues</a></li>')
  w('<li><a href="/about.html">About</a></li>')
  w('        </ul>')
  w('  </div>')
  w('</div>')
  
  w('<table>')
  w('<tr>')
  # Spacer
  w('<td>&nbsp;&nbsp</td>')
  w('<td valign=top>')

  # Facets
  w('<table>')
  facets = result['facets']
  args = []
  args.append('text=%s' % urllib.parse.quote(text))
  for field, values in drillDowns:
    #print 'field %s, values %s' % (field, values)
    args.append('dd=%s' % urllib.parse.quote('%s:%s' % (field, facetValuesToString([facetPathToString(x) for x in values]))))

  f = RenderFacets(w, spec, drillDowns, facets, treeFacetMap, ddExtraMap, '/moreFacets.py?%s' % '&'.join(args))
  for idx, (userLabel, dim, ign, facetSort, doMorePopup) in enumerate(spec.facetFields):
    if userLabel is None:
      continue
    f.render(userLabel, [dim], idx,
             facetSort is not None,
             facetSort == '-int',
             doMorePopup = doMorePopup)

  # End facets
  w('</table>')
  w('</td>')

  # Spacer
  w('<td>&nbsp;&nbsp;</td>')
  
  #w('<td colspan=2></td>')
  w('<td valign=top>')
  if False and spec.doAutoComplete:
    w('<div class="ui-widget">')

  w('<div class="navbar">')
  w('<div class="navbar-inner">')
  w('<form class="navbar-form" method=GET action="search.py">\n')
  w('<input type=hidden name=chg value="">\n')
  w('<input type=hidden name=text value="%s">' % escape(text))
  w('<input type=hidden name=a1 value="">')
  w('<input type=hidden name=a2 value="">')
  w('<input type=hidden name=page value=%d>' % page)
  w('<input type=hidden name=searcher value="%s">' % result['searchState']['searcher'])
  if spec.groups is not None:
    w('<input type=hidden name=group value=%s>' % groupBy)
    w('<input type=hidden name=groupSort value=%s>' % groupSort)
  w('<input type=hidden name=sort value=%s>' % sort)
  w('<input type=hidden name=format value=%s>' % format)
  id = makeID()
  util.log('id %s' % id)
  w('<input type=hidden name=id value=%s>' % id)
  if len(drillDowns) > 0:
    for field, values in drillDowns:
      w('<input type=hidden name="dd" value="%s:%s">' % (field, facetValuesToString([facetPathToString(x) for x in values])))

  w('<ul class="nav">')
  w('<li>')
  w('<input autocomplete=off id=textid class="span4" placeholder="Search" type=text name=newText value="%s">\n' % escape(text))
  #w('<input type=submit value="Search" onclick="javascript:document.forms[0].text.value = document.forms[0].newText.value;document.forms[0].chg.value=\'new\';">\n')
  w('<button type="submit" class="btn" onclick="javascript:document.forms[0].text.value = document.forms[0].newText.value;document.forms[0].chg.value=\'new\';">Search</button>')
  w('</li>')

  if False and spec.doAutoComplete:
    w('</div>')
    if False:
      if infixSuggest:
        s = ' checked'
      else:
        s = '' 
      w('Infix suggestions? <input type=checkbox name=infixSuggest %s>' % s)

  #print('result:');
  #pprint.pprint(result)
  
  totalHits = result['totalGroupCount']

  lastPage = int(math.ceil(float(totalHits)/perPage))

  if False:
    w('<select name="sort" onchange="javascript:document.forms[0].page.value=0;javascript:document.forms[0].submit()">')
    for key, val, ign, ign in spec.sorts:
      if text == '' and key == 'relevance':
        continue
      if key == sort:
        s = ' selected'
      else:
        s = ''
      w('<option value="%s"%s>Sort by %s</option>' % (key, s, val))
    w('</select>')
  else:
    w('<li class="dropdown">')
    w('  <a href="#" class="dropdown-toggle" data-toggle="dropdown">')
    for key, label, ign, ign in spec.sorts:
      #print 'label %s' % label
      if text == '' and label.startswith('relevance'):
        continue
      if key == sort:
        w('Sort by %s' % label)
        w('    <b class="caret"></b>')
        w('</a>')
        break
    w('<ul class="dropdown-menu">')
    for key, label, ign, ign in spec.sorts:
      if text == '' and key.startswith('relevance'):
        continue
      if key != sort:
        w('<li><a href="javascript:setSort(\'%s\')">Sort by %s</a></li>' % (key, label))
    w('</ul>')
    w('</li>')
    
  if spec.groups is not None:
    if False:
      w('<select name="group" onchange="javascript:document.forms[0].page.value=0;javascript:document.forms[0].submit()">')
      for key, label, facetField in ((None, 'No grouping', None),) + spec.groups:
        if key == groupBy:
          s = ' selected'
        else:
          s = ''
        if label != 'No grouping':
          label = 'Group by ' + label
        w('<option value="%s"%s>%s</option>' % (key, s, label))
      w('</select>')
    else:
      w('<li class="dropdown">')
      w('  <a href="#" class="dropdown-toggle" data-toggle="dropdown">')
      for key, label, facetField in ((None, 'No grouping', None),) + spec.groups:
        if label != 'No grouping':
          label = 'Group by ' + label
        if key == groupBy:
          w('%s' % label)
          w('    <b class="caret"></b>')
          w('</a>')
          break
      w('<ul class="dropdown-menu">')
      for key, label, facetField in ((None, 'No grouping', None),) + spec.groups:
        if label != 'No grouping':
          label = 'Group by ' + label
        if key != groupBy:
          w('<li><a href="javascript:setGrouping(\'%s\')">%s</a></li>' % (key, label))
      w('</ul>')
      w('</li>')

  if False:
    w('''<ul class="nav">
    <li class="dropdown">
      <a href="#" class="dropdown-toggle" data-toggle="dropdown">
        Account
        <b class="caret"></b>
      </a>
      <ul class="dropdown-menu">
        <li><a href="#">foobar</a></li>
        <li><a href="#">foobar</a></li>
      </ul>
    </li>
  </ul>''')    

  if groupBy is not None:
    if False:
      w('<select name="groupSort" onchange="javascript:document.forms[0].page.value=0;javascript:document.forms[0].submit()">')
      for key, label, field, reverse in spec.sorts:
        if text == '' and key == 'relevance':
          continue
        if key == groupSort:
          s = ' selected'
        else:
          s = ''
        w('<option value="%s"%s>Sort groups by %s</option>' % (key, s, label))
      w('</select>')
    else:
      w('<li class="dropdown">')
      w('  <a href="#" class="dropdown-toggle" data-toggle="dropdown">')
      for key, label, field, reverse in spec.sorts:
        if text == '' and key.startswith('relevance'):
          continue
        if key == groupSort:
          w('Sort groups by %s' % label)
          w('    <b class="caret"></b>')
          w('</a>')
          break
      w('<ul class="dropdown-menu">')
      for key, label, field, reverse in spec.sorts:
        if text == '' and key.startswith('relevance'):
          continue
        if key != groupBy:
          w('<li><a href="javascript:setGroupSort(\'%s\')">%s</a></li>' % (key, label))
      w('</ul>')
      w('</li>')

  if spec.showGridOrList:
    # Format
    w('<li class="dropdown">')
    w('  <a href="#" class="dropdown-toggle" data-toggle="dropdown">')
    if format == 'list':
      w('<i class=icon-list></i>&nbsp;List')
    else:
      w('<i class=icon-th></i>&nbsp;Grid')
    w('    <b class="caret"></b>')
    w('</a>')
    w('<ul class="dropdown-menu">')
    if format == 'list':
      w('<li><a href="javascript:setFormat(\'grid\')"><i class=icon-th></i>&nbsp;Grid</a></li>')
    else:
      w('<li><a href="javascript:setFormat(\'list\')"><i class=icon-list></i>&nbsp;List</a></li>')
    w('</ul>')
    w('</li>')

  # End navbar
  w('</ul>')

  w('</div>')
  w('</div>')

  w('</form>')

  if totalHits == 0:
    w('<br>No results<br>')
  else:

    #w('<br>')
    #w('<div class=container>')
    w('<table>')
    if groupBy is not None:
      for group in result['groups']:
        renderGroupHeader(w, group, groupDDField, hitsPerGroup)
        renderJiraHits(w, text, group['hits'], userDrillDowns)
    else:
      renderNavSummary(w, facets, drillDowns)
      renderJiraHits(w, text, result['groups'], userDrillDowns)

    #w('</div>')
    w('</table>')
    
    # Hits
    if groupBy is not None:
      renderPagination(w, page, lastPage, totGroups, 'groups')
    else:
      renderPagination(w, page, lastPage, totalHits, spec.itemLabel)

  w('<br><em>[$$msec$$]</em>')
  w('</td>')

  w('</tr>')
  w('</table>')
  w('&nbsp;&nbsp;')

  w('</body>')
  w('</html>')
  #print _l.l

  if isMike:
    if localconstants.isDev:
      s = ', <a href="http://jirasearch.mikemccandless.com%s">to prod</a>' % origPath
    else:
      s = ', <a href="http://10.17.4.91:10001/search.py?%s">to dev</a>' % origPath[1:]
  else:
    s = ''
  timeDetails = '%.1f msec search, %.1f msec total' % (1000*searchTime, 1000*(time.time()-t0))
  details = '%s%s' % (timeDetails, s)
  util.log(timeDetails)

  headers = []
  c = http.cookies.SimpleCookie()
  if project is not None:
    c['lastProject'] = project
  else:
    c['lastProject'] = ''
  lines = str(c)
  headers.append(('Set-Cookie', str(c)[11:].strip()))

  return ''.join(_l.l).replace('$$msec$$', details), headers
