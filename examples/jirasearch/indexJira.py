import sqlite3
import shutil
import traceback
import re
import time
import sys
import pickle
import urllib.request, urllib.error, urllib.parse
import math
import json
import server
import os
import datetime
import localconstants
import util
import gitHistory

"""
This tool uses Jira's JSON REST search API to download all Jira issues for
certain Apache projects.  The raw json is stored in a on-disk sqlite3
database, kept up to date by periodically asking Jira for which issues
changed in the last 30 seconds.  Then we iterate the issues from that
db into the lucene server index.

A luceneserver instance (default localhost) should already be running
when you run this.
"""

# fields to add
#   - has votes / vote count facet

allProjects = ('Infrastructure', 'Tika', 'Solr', 'Lucene')

reCommitURL = re.compile(r'\[(.*?)\]')
reSVNCommitURL = re.compile('(http://svn\.apache\.org/viewvc.*?)$', re.MULTILINE)
reInBranch = re.compile("in branch '(.*?)'")
reInBranch2 = re.compile(r'\[(.*?) commit\]')
reInGitBranch = re.compile("'s branch (.*?) from")
reQuote = re.compile('{quote}.*?{quote}', re.DOTALL)
reBQ = re.compile(r'bq\. .*?$', re.MULTILINE)
reCode1 = re.compile('{{(.*?)}}', re.DOTALL)
reCode2 = re.compile('{code}(.*?){code}', re.DOTALL)
reUserName = re.compile(r'(\[~.*?\])')

DB_PATH = localconstants.DB_PATH

MY_EPOCH = datetime.datetime(year=2014, month=1, day=1)

issueToCommitPaths = gitHistory.parseLog()
try:
  with open('%s/userNamesMap.pk' % localconstants.ROOT_STATE_PATH, 'rb') as f:
    userNameToDisplayName = pickle.loads(f.read())
except FileNotFoundError:
  userNameToDisplayName = {}
except:
  print('WARNING: unable to load prior user names map; starting new one')
  userNameToDisplayName = {}

# For some insane reason, Doug has no display name ;)
userNameToDisplayName['cutting@apache.org'] = 'Doug Cutting'

def prettyPrintJSON(obj):
  print(json.dumps(obj,
                   sort_keys=True,
                   indent=4, separators=(',', ': ')))

def parseDateTime(s):
  if s.endswith('+0000'):
    s = s[:-5]
  i = s.find('.')
  if i != -1:
    fraction = float(s[i:])
    s = s[:i]
  else:
    fraction = 0.0
  dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
  return dt + datetime.timedelta(microseconds=int(fraction*1000000))

ICU_RULES = open('Latin-dont-break-issues.rbbi').read()

# Latn customized to keep AAAA-NNNN tokens:
ICU_TOKENIZER_KEEP_ISSUES = {
  'class': 'icu',
  'rules': [{'script': 'Latn', 'rules': ICU_RULES}]}

def createSchema(svr):

  path = '%s/jira' % localconstants.ROOT_INDICES_PATH

  if os.path.exists(path):
    shutil.rmtree(path)

  svr.send('createIndex', {'indexName': 'jira', 'rootDir': path})
  #svr.send('settings', {'indexName': 'jira', 'index.verbose': True})
  svr.send('settings', {'indexName': 'jira', 'directory': 'MMapDirectory', 'nrtCachingDirectory.maxMergeSizeMB': 0.0})
  #svr.send('settings', {'indexName': 'jira', 'directory': 'NIOFSDirectory', 'nrtCachingDirectory.maxMergeSizeMB': 0.0})
  svr.send('startIndex', {'indexName': 'jira'})

  analyzer = {
    'charFilters': [{'class': 'Mapping',
                     'mappingFileContents': '"LUCENE-" => "LUCENE"\n"lucene-" => "lucene"\n"SOLR-" => "SOLR"\n"solr-" => "solr"\n"INFRA-" => "INFRA"\n"infra-" => "infra"'}],
    'tokenizer': ICU_TOKENIZER_KEEP_ISSUES,
    'tokenFilters': ['EnglishPossessive',
                     {'class': 'WordDelimiter',
                      'splitOnNumerics': 0,
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
                        {'input': ['mike', 'michael'], 'output': 'michael'},
                        {'input': ['npe', 'nullpointerexception'], 'output': 'npe'},
                        {'input': ['hilite', 'highlight'], 'output': 'highlight'},
                        {'input': ['iw', 'IndexWriter'], 'output': 'IndexWriter'},
                        {'input': ['replicator', 'replication'], 'output': 'replication'},
                        {'input': ['join', 'joining'], 'output': 'join'},
                        {'input': ['jvm', 'java virtual machine'], 'output': 'jvm'},
                        {'input': ['drill down', 'drilldown'], 'output': 'drilldown'},
                        {'input': ['ms', 'microsoft'], 'output': 'microsoft'},
                        {'input': ['segv', 'segmentation fault', 'sigsegv'], 'output': 'segv'},
                        {'input': ['pnp', 'progress not perfection'], 'output': 'pnp'},
                        {'input': ['ssd', 'solid state disk'], 'output': 'ssd'},
                        {'input': ['nrt', 'near-real-time', 'near real-time', 'near-real time', 'near real time'], 'output': 'nrt'},
                        # nocommit is doc values / docvalues working "for free"?
                        {'input': ['doc values', 'docvalue'], 'output': 'docvalue'},
                        {'input': ['js', 'javascript'], 'output': 'javascript'},
                        {'input': ['smoke tester', 'smokeTester'], 'output': 'smokeTester'},
                        ]},
                     'Stop',
                     'EnglishMinimalStem']}

  #print('TOKENS')
  #prettyPrintJSON(svr.send('analyze', {'analyzer': analyzer, 'indexName': 'jira', 'text': 'foo LUCENE-444 lucene-1123 AnalyzingInfixSuggester'}))

  fields = {'key': {'type': 'atom',
                    'sort': True,
                    'store': True},
            'childKey': {'type': 'atom'},
            'otherText': {'type': 'text',
                          'analyzer': analyzer,
                          'multiValued': True},
            'keyNum': {'type': 'int',
                       'search': False,
                       'sort': True},
            'allUsers': {'type': 'text',
                         'highlight': True,
                         'store': True,
                         'facet': 'flat',
                         'analyzer': analyzer,
                         'multiValued': True},
            'committedPaths': {'type': 'atom',
                               'search': False,
                               'multiValued': True,
                               'facet': 'hierarchy'},
            'attachments': {'type': 'atom',
                            'multiValued': True,
                            'facet': 'flat'},
            'hasCommits': {'type': 'boolean',
                           'facet': 'flat'},
            'commentCount': {'type': 'int',
                             'sort': True,
                             'store': True},
            'voteCount': {'type': 'int',
                          'sort': True,
                          'store': True},
            'watchCount': {'type': 'int',
                           'sort': True,
                           'store': True},
            'project': {'type': 'atom',
                        'facet': 'flat'},
            'labels': {'type': 'atom',
                       'multiValued': True,
                       'facet': 'flat'},
            'created': {'type': 'long',
                        'store': True,
                        'sort': True},
            'facetCreated': {'type': 'atom',
                             'search': False,
                             'facet': 'hierarchy'},
            'updated': {'type': 'long',
                        'sort': True,
                        'store': True,
                        'search': True,
                        'facet': 'numericRange'},
            'updatedAgo': {'type': 'long',
                           'sort': True,
                           'store': True,
                           'search': True,
                           'facet': 'numericRange'},
            'parent': {'type': 'boolean'},
            'status': {'type': 'atom',
                       'store': True,
                       'facet': 'flat'},
            'resolution': {'type': 'atom',
                           'facet': 'flat'},
            'reporter': {'type': 'atom',
                         'facet': 'flat'},
            'assignee': {'type': 'atom',
                         'facet': 'flat',
                         'group': True},
            'priority': {'type': 'int',
                         'sort': True},
            'issueType': {'type': 'atom',
                          'facet': 'flat'},
            'facetPriority': {'type': 'atom',
                              'group': True,
                              'facet': 'flat'},
            'fixVersions': {'type': 'atom',
                            'facet': 'flat',
                            'multiValued': True},
            'components': {'type': 'atom',
                           'search': True,
                           'store': True,
                           'multiValued': True},
            'facetComponents': {'type': 'atom',
                                'search': False,
                                'store': False,
                                'facet': 'hierarchy',
                                'multiValued': True},
            'committedBy': {'type': 'atom',
                            'multiValued': True,
                            'facet': 'flat',
                            'search': True},
            'summary': {'type': 'text',
                        'search': True,
                        'store': True,
                        'highlight': True,
                        'similarity': {'class': 'BM25Similarity'},
                        'analyzer': analyzer},
            'description': {'type': 'text',
                            'search': True,
                            'highlight': True,
                            'similarity': {'class': 'BM25Similarity'},
                            'analyzer': analyzer},
            'hasVotes': {'type': 'boolean',
                         'search': False,
                         'facet': 'flat'},
            # who last commented on the issue
            'lastContributor': {'type': 'atom',
                                'facet': 'flat',
                                'store': True},
            #'blendRecencyRelevance': {'type': 'virtual',
            #                          'recencyScoreBlend': {'timeStampField': 'updated',
            #                                                'maxBoost': 2.0,
            #                                                'range': 30*24*3600}},
            # For comment sub-docs:
            'author': {'type': 'atom',
                       'facet': 'flat',
                       'store': True},
            'commitURL': {'type': 'atom',
                          'search': False,
                          'store': True},
            'commentID': {'type': 'atom',
                          'search': False,
                          'store': True},
            'body': {'type': 'text',
                     'highlight': True,
                     'similarity': {'class': 'BM25Similarity'},
                     'store': True,
                     'analyzer': analyzer},
            }

  result = svr.send('registerFields', {'indexName': 'jira', 'fields': fields})
  print('Done register')

def removeAllGhosts():
  # Remove ghost of renamed issues:
  db = sqlite3.connect(DB_PATH)
  try:
    toDelete = []
    for k, v in c.execute('SELECT key, body FROM issues'):
      print('check %s' % k)
      v = pickle.loads(v)
      for ent in v['changelog']['histories']:
        for d in ent['items']:
          if d['field'] == 'Key':
            oldKey = d['fromString']
            print('issue %s renamed to %s; now remove %s' % (oldKey, k, oldKey))
            toDelete.append(oldKey)
    for k in toDelete:
      c.execute('DELETE FROM issues WHERE key = ?', (k,))
    db.commit()
  finally:
    db.close()

def allIssues():
  db = sqlite3.connect(DB_PATH)
  try:
    c = db.cursor()
    for k, v in c.execute('SELECT key, body FROM issues'):
      try:
        yield pickle.loads(v)
      except:
        traceback.print_exc()
        print(k)
        raise
  finally:
    db.close()

def specificIssues(issues):
  db = sqlite3.connect(DB_PATH)
  try:
    c = db.cursor()
    for issue in issues:
      for k, v in c.execute('SELECT key, body FROM issues where key = ?', (issue,)):
        try:
          yield pickle.loads(v)
        except:
          traceback.print_exc()
          print(k)
          raise
  finally:
    db.close()

def issuesUpdatedAfter(minTimeStamp):
  db = sqlite3.connect(DB_PATH)
  try:
    c = db.cursor()
    for k, v in c.execute('SELECT key, body FROM issues'):
      issue = pickle.loads(v)
      fields = issue['fields']
      updated = parseDateTime(fields['created'])
      for x in fields['comment']['comments']:
        if x['body'].find('Closed after release.') == -1:
          updated = max(updated, parseDateTime(x['created']))
      # nocommit illegal clock comparison here!  minTimeStamp is local
      # time, updated is jira server time!
      if updated >= minTimeStamp:
        print('%s updated after %s' % (k, minTimeStamp))
        try:
          yield issue
        except KeyboardInterrupt:
          raise
        except:
          traceback.print_exc()
          print(k)
  finally:
    db.close()
    

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
  server = getArg('-server')
  if server is None:
    server = '127.0.0.1'

  tup = server.split(':')
  host = tup[0]
  if len(tup) == 1:
    port = 4000
  elif len(tup) == 2:
    port = int(tup[1])
  else:
    raise RuntimeError('-server should be host or host:port; got "%s"' % server)

  svr = util.ServerClient(host, port)

  #removeAllGhosts()

  if getFlag('-reindex'):
    fullReindex(svr, getFlag('-delete'))
  elif svr.send('indexStatus', {'indexName': 'jira'})['status'] != 'started':
    svr.send('startIndex', {'indexName': 'jira'})

  if getFlag('-buildFullSuggest'):
    buildFullSuggest(svr)
    
  if getFlag('-nrt'):

    now = datetime.datetime.now()

    # First, catch up since last commit:
    commitUserData = svr.send('getCommitUserData', {'indexName': 'jira'})
    lastCommitTime = pickle.loads(eval(commitUserData['lastCommitTime']))
    print('Last commit time %s (%s ago); now catch up' %
          (lastCommitTime, now - lastCommitTime))
    indexDocs(svr, issuesUpdatedAfter(lastCommitTime), updateSuggest=True)

    db = sqlite3.connect(DB_PATH)
    try:
      c = db.cursor()
      lastUpdate = None
      for v in c.execute('select * from lastUpdate'):
        lastUpdate = pickle.loads(v[0])
        print('Last Jira update: %s' % lastUpdate)
        break
      if lastUpdate is None:
        lastUpdate = now - datetime.timedelta(days=10)
    finally:
      db.close()
      db = None

    first = False
    lastSuggestBuild = time.time()
    lastGITBuild = 0
    lastCommit = time.time()
    # Force a git refresh on startup:
    anyUpdatesSinceGIT = True

    while True:

      delay = now - lastUpdate
      minutes = delay.days * 24 * 60 + delay.seconds / 60.

      # nocommit sorta silly, but this 1+ and minute quantization
      # means whenever an issue is updated, we are indexing it at least
      # 2X times:
      age = '-%dm' % (int(1+minutes))

      args = {
        'jql': '(project="Solr" OR project="Lucene - Core" OR project="Tika") AND updated > %s ORDER BY key ASC' % age,
        #'jql': '(project="Solr" OR project="Lucene - Core") AND updated > %s ORDER BY key ASC' % age,
        'expand': 'changelog',
        'maxResults': '1000',
        'fields': '*all',
        }
      startAt = 0

      print()
      now = datetime.datetime.now()        
      print('%s: nrt index' % now)

      print('  use age=%s' % age)
      while True:
        args['startAt'] = str(startAt)
        url = 'https://issues.apache.org/jira/rest/api/2/search?%s' % urllib.parse.urlencode(args)
        t0 = time.time()
        try:
          s = urllib.request.urlopen(url, timeout=60).read().decode('utf-8')
        except:
          print('WARNING: exception loading JSON from Jira')
          traceback.print_exc()
          break

        t1 = time.time()
        print('  %.1f sec to load results' % (t1-t0))
        #prettyPrintJSON(json.loads(s))
        try:
          o = json.loads(s)
        except:
          print('WARNING: exception parsing JSON from Jira')
          traceback.print_exc()
          break
        numIssues = len(o['issues'])
        total = o['total']
        indexDocs(svr, o['issues'], printIssue=True, updateSuggest=True)
        db = sqlite3.connect(DB_PATH)
        try:
          c = db.cursor()
          c.execute('DELETE FROM lastUpdate')
          c.execute('INSERT INTO lastUpdate VALUES (?)', (pickle.dumps(now),))
          for issue in o['issues']:
            anyUpdatesSinceGIT = True
            c.execute('INSERT OR REPLACE INTO issues (key, body) VALUES (?, ?)', (issue['key'].encode('utf-8'), pickle.dumps(issue)))
            # Remove ghost of any just renamed issues:
            for ent in issue['changelog']['histories']:
              for d in ent['items']:
                if d['field'] == 'Key':
                  oldKey = d['fromString']
                  print('issue %s renamed to %s; now remove %s' % (oldKey, issue['key'], oldKey))
                  c.execute('DELETE FROM issues WHERE key = ?', (oldKey,))
          db.commit()
        finally:
          db.close()
          db = None
        lastUpdate = now
        print('  %s: %d results of %d' % (startAt, numIssues, total))
        print('  %.1f sec to index' % (time.time()-t1))
        startAt += numIssues
        if startAt >= total:
          break
        time.sleep(10.0)

      # Check for git commits every 30 minutes:
      if time.time() - lastGITBuild > 30*60 and anyUpdatesSinceGIT:
        lastGITBuild = time.time()
        newIssueToCommitPaths, committedIssues = gitHistory.refresh()
        # merge new git history into our in-memory version:
        mergeIssueCommits(issueToCommitPaths, newIssueToCommitPaths)
        print('  update from git commits...')
        indexDocs(svr, specificIssues(committedIssues), printIssue=True)
        print('  done update from git commits...')
        anyUpdatesSinceGIT = False

      # Commit once per day, so if server goes down we only need to
      # reindex at most past day's worth of updated issues:
      if now - lastCommitTime > datetime.timedelta(days=1):
        commit(svr, now)
        lastCommitTime = now

      time.sleep(30.0)

def mergeIssueCommits(issueToCommitPaths, newIssueToCommitPaths):
  for issue, ent in newIssueToCommitPaths.items():
    old = issueToCommitPaths.get(issue)
    if old is None:
      issueToCommitPaths[issue] = ent
    else:
      # merge authors
      s = old[0]
      if type(s) is str:
        s = set(s)
      s2 = ent[0]
      if type(s2) is str:
        s2 = set(s2)
      s.update(s2)
      if len(s) == 1:
        s = list(s)[0]
      old[0] = s
      old.extend(ent[1:])

def buildFullSuggest(svr):
  print('Build suggest...')
  t0 = time.time()
  suggestFile = open('%s/jira.suggest' % localconstants.ROOT_STATE_PATH, 'wb')
  allUsers = {}
  for issue in allIssues():
    key = issue['key'].lower()
    fields = issue['fields']
    project = fixProject(fields['project']['name'])
    addUser(allUsers, fields['reporter'], project, key)
    assignee = fields['assignee']
    if assignee is not None:
      addUser(allUsers, assignee, project, key)
    
    #print('issue: %s' % key)
    updated = parseDateTime(fields['created'])
    for x in fields['comment']['comments']:
      if x['body'] != 'Closed after release.':
        updated = max(updated, parseDateTime(x['created']))
      addUser(allUsers, x['author'], project, key)

    for change in issue['changelog']['histories']:
      didAttach = False
      for item in change['items']:
        if item['field'] == 'Attachment':
          didAttach = True

      if didAttach:
        #prettyPrintJSON(change)
        if 'author' in change:
          addUser(allUsers, change['author'], project, key)

    weight = (updated-MY_EPOCH).total_seconds()

    # Index project as a context, so we can suggest within project:
    suggestFile.write(('%d\x1f%s: %s\x1f%s\x1f%s\n' % (weight, key.upper(), fields['summary'], key, project)).encode('utf-8'))

  for userDisplayName, (count, projects) in sorted(allUsers.items(), key = lambda x: (-x[1][0], x[0])):
    suggestFile.write(('%d\x1f%s\x1fuser %s\x1f%s\n' % \
                       (count, userDisplayName, userDisplayName, '\x1f'.join(projects))).encode('utf-8'))

  for project in allProjects:
    suggestFile.write(('1000000000\x1f%s\x1fproject %s\x1f%s\n' % (project, project, '\x1f'.join(allProjects))).encode('utf-8'))
  
  suggestFile.close()

  # Use ICU so we split on '.', e.g. Directory.fileExists
  # Don't do WDF preserveOriginal at query time else no suggestions for fileExists

  fullSuggestPath = os.path.abspath(suggestFile.name)

  # Build infix title suggest
  res = svr.send('buildSuggest',
                    {'indexName': 'jira',
                     'suggestName': 'titles_infix',
                     'source': {'localFile': fullSuggestPath},
                     'class': 'InfixSuggester',
                     'indexAnalyzer': {
                        'tokenizer': ICU_TOKENIZER_KEEP_ISSUES,
                        #'tokenizer': 'Standard',
                        'tokenFilters': ['EnglishPossessive',
                                         {'class': 'WordDelimiter',
                                          'preserveOriginal': 1},
                                         'LowerCase',
                                         'Stop',
                                         'EnglishMinimalStem']},
                     'queryAnalyzer': {
                        'tokenizer': ICU_TOKENIZER_KEEP_ISSUES,
                        #'tokenizer': 'Standard',
                        'tokenFilters': ['EnglishPossessive',
                                         'LowerCase',
                                         'SuggestStop',
                                         'EnglishMinimalStem']}
                     })
  print('Took %.1f sec:\n%s' % (time.time()-t0, res))

def fullReindex(svr, doDelete):

  startTime = datetime.datetime.now()

  if doDelete:
    try:
      isStarted = svr.send('indexStatus', {'indexName': 'jira'})['status'] == 'started'
    except:
      traceback.print_exc()
      isStarted = False
      
    if isStarted:
      print('Rollback index...')
      try:
        svr.send('rollbackIndex', {'indexName': 'jira'})
      except:
        traceback.print_exc()
      print('Stop index...')
      try:
        svr.send('stopIndex', {'indexName': 'jira'})
      except:
        traceback.print_exc()
    print('Delete index...')
    try:
      svr.send('deleteIndex', {'indexName': 'jira'})
    except:
      traceback.print_exc()

    print('Create schema...')
    createSchema(svr)

    #svr.send('deleteAllDocuments', {'indexName': 'jira'})

  indexDocs(svr, allIssues(), updateSuggest=False)
  buildFullSuggest(svr)

  print('Done full index')
  commit(svr, startTime)

  open('%s/userNamesMap.pk' % localconstants.ROOT_STATE_PATH, 'wb').write(pickle.dumps(userNameToDisplayName))

def commit(svr, timeStamp):
  t0 = time.time()
  svr.send('setCommitUserData', {'indexName': 'jira',
                                 'userData': {'lastCommitTime': repr(pickle.dumps(timeStamp))}})
  svr.send('commit', {'indexName': 'jira'})
  print('Commit took %.1f msec' % (1000*(time.time()-t0)))

def isCommitUser(userName):
  for s in ('Commit Tag Bot', 'ASF subversion and git services', 'ASF GitHub Bot'):
    if s in userName:
      return True
  return False

def addUser(allUsers, userMap, project, key=None):
  displayName = userMap['displayName']
  if displayName == 'cutting@apache.org':
    displayName = 'Doug Cutting'
  if isCommitUser(displayName):
    displayName = 'commitbot'
    user = 'commitbot'
  else:
    user = userMap['name']
  if displayName not in allUsers:
    allUsers[displayName] = [0, set()]
  l = allUsers[displayName]
  l[0] += 1
  l[1].add(project)

  userNameToDisplayName[user] = displayName

def fixProject(name):
  if name == 'Lucene - Core':
    name = 'Lucene'
  return name

def indexDocs(svr, issues, printIssue=False, updateSuggest=False):

  bulk = server.ChunkedSend(svr, 'bulkUpdateDocuments', 32768)
  bulk.add('{"indexName": "jira", "documents": [')

  if updateSuggest:
    suggestFile = open('%s/jiranrt.suggest' % localconstants.ROOT_STATE_PATH, 'wb')

  now = datetime.datetime.now()

  first = True
  for issue in issues:
    key = issue['key'].lower()
    #print(key)

    debug = False and key.upper() == 'INFRA-10234' and localconstants.isDev
    
    if debug:
      print()
      print('ORIG ISSSUE:')
      prettyPrintJSON(issue)
      
    if printIssue:
      print('  %s' % key)

    fields = issue['fields']
    project = fixProject(fields['project']['name'])
    if project not in allProjects:
      # This can happen when the issue is renamed to a project outside
      # of the ones we index:
      continue

    created = fields['created']
    desc = fields['description']

    # All users who have done something on this issue:
    allUsers = {}

    doc = {'key': key,
           'keyNum': int(key[key.find('-')+1:]),
           'parent': True,
           'summary': fields['summary'],
           'hasVotes': fields['votes']['votes'] != 0}
    if desc is not None:
      doc['description'] = cleanJiraMarkup(key, desc)

    doc['issueType'] = fields['issuetype']['name']
    doc['project'] = project

    l = []
    for x in fields['fixVersions']:
      l.append(x['name'])
    doc['fixVersions'] = l
    #print(key)
    p = fields['priority']
    if p is not None:
      doc['facetPriority'] = p['name']
      doc['priority'] = int(p['id'])

    doc['reporter'] = fields['reporter']['displayName']
    addUser(allUsers, fields['reporter'], project)
    assignee = fields['assignee']
    if assignee is not None:
      doc['assignee'] = assignee['displayName']
      addUser(allUsers, assignee, project)
    else:
      doc['assignee'] = 'Unassigned'
    dt = parseDateTime(created)
    doc['created'] = int(float(dt.strftime('%s.%f')))

    #dt = parseDateTime(updated)
    updated = dt

    doc['status'] = fields['status']['name']
    if fields['resolution'] is not None:
      doc['resolution'] = fields['resolution']['name']
    else:
      doc['resolution'] = 'Unresolved'

    doc['labels'] = fields['labels']

    try:
      paths = issueToCommitPaths[key.upper()]
    except KeyError:
      pass
    else:
      cps = []
      if type(paths[0]) is str:
        authors = [paths[0]]
      else:
        authors = list(paths[0])
      doc['committedBy'] = authors
      for path in paths[1:]:
        i = path.find(':')
        path = path[i+1:]
        cps.append(path.split('/'))
      doc['committedPaths'] = cps
      
    l = []
    l2 = []
    for x in fields['components']:
      l2.append(x['name'])
      l.append(list(x['name'].split('/')))

    doc['facetComponents'] = l
    doc['components'] = l2

    attachments = set()
    #print('\nISSUE: %s' % key.upper())
    for change in issue['changelog']['histories']:
      #print('  change: %s' % str(change))
      didAttach = False
      for item in change['items']:
        if item['field'] == 'Attachment':
          didAttach = True
          if 'toString' in item and item['toString'] is not None:
            name = item['toString'].lower()
            if '.patch' in name or '.diff' in name:
              attachments.add('Patch')
            elif name.endswith('.png') or name.endswith('.gif') or name.endswith('.jpg'):
              attachments.add('Image')
            elif name.endswith('.java'):
              attachments.add('Java Source')
            elif name.endswith('.bz2') or name.endswith('.rar') or name.endswith('.tgz') or name.endswith('.tar.gz') or name.endswith('.zip') or name.endswith('.tar'):
              attachments.add('Archive')
            elif name.endswith('.jar'):
              attachments.add('JAR')
            elif name.endswith('.txt'):
              attachments.add('Text File')
            else:
              attachments.add('Other')
          else:
            attachments.add('Other')

      if didAttach:
        #prettyPrintJSON(change)
        if 'author' in change:
          addUser(allUsers, change['author'], project)
    if len(attachments) == 0:
      attachments.add('None')
    doc['attachments'] = list(attachments)
                
    comments = fields.get('comment', '')
    subDocs = []
    hasCommits = False
    doc['voteCount'] = fields['votes']['votes']
    doc['watchCount'] = fields['watches']['watchCount']
    doc['commentCount'] = len(comments['comments'])
    commentsText = []
    lastContributor = None
    for x in comments['comments']:
      subDoc = {}
      subDoc['author'] = x['author']['displayName']
      isCommit = isCommitUser(subDoc['author'])
      body = x['body']
      if isCommit:
        subDoc['author'] = 'commitbot'
        hasCommits = True
        m = reCommitURL.findall(body)
        if len(m) > 0:
          for y in m:
            if 'git-wip-us' in y or 'svn.apache.org/r' in y:
              subDoc['commitURL'] = y.strip()
              #print('GIT: %s' % subDoc['commitURL'])
              break
        if 'commitURL' not in subDoc:
          m = reSVNCommitURL.search(body)
          if m is not None:
            subDoc['commitURL'] = m.group(1).strip()
            #print('SVN: %s' % subDoc['commitURL'])

        branch = reInBranch.search(body)
        if branch is not None:
          branch = branch.group(1)
          branch = branch.replace('dev/', '')
          branch = branch.replace('branches/', '')
        else:
          branch = reInBranch2.search(body)
          if branch is not None:
            branch = branch.group(1)
          else:
            branch = reInGitBranch.search(body)
            if branch is not None:
              branch = branch.group(1)
              branch = branch.replace('refs/heads/', '')

        # drop first 2 not-so-useful lines of the commit message,
        # because we separately extract this info:
        #   Commit XXX in lucene-solr's branch YYY from ZZZ
        #   [ <url> ]
        
        body = '\n'.join(body.split('\n')[2:])
        if branch is not None:
          body = '%s: %s' % (branch, body)
      elif subDoc['author'] is not None:
        lastContributor = subDoc['author']

      addUser(allUsers, x['author'], project)
      subDoc['body'] = cleanJiraMarkup(key, body)
      if debug:
        print('  after clean: %s' % subDoc['body'])
      commentsText.append(subDoc['body'])
      
      subDoc['commentID'] = x['id']
      dt = parseDateTime(x['created'])
      # Disregard the bulk-update after 4.3 release:
      if subDoc['body'] != 'Closed after release.':
        updated = max(updated, dt)
      subDoc['created'] = int(float(dt.strftime('%s.%f')))
      subDoc['key'] = key
      subDoc['childKey'] = key
      subDocs.append({'fields': subDoc})

    # Compute our own updated instead of using Jira's, to be max(createTime, comments):
    doc['updated'] = int(float(updated.strftime('%s.%f')))

    # TODO: maybe lucene server needs a copy field:
    doc['updatedAgo'] = doc['updated']

    if lastContributor is not None:
      doc['lastContributor'] = lastContributor

    if updateSuggest:
      weight = (updated-MY_EPOCH).total_seconds()
      suggestFile.write(('%d\x1f%s: %s\x1f%s\x1f%s\n' % (weight, key.upper(), fields['summary'], key, project)).encode('utf-8'))
    
    l = [(y[0], x) for x, y in list(allUsers.items())]
    l.sort(reverse=True)
    doc['allUsers'] = [x for y, x in l]
    doc['hasCommits'] = hasCommits

    otherText = []
    otherText.append(doc['key'])
    otherText.extend(doc['key'].split('-'))
    otherText.extend(doc['components'])
    #print('%s: other %s' % (key, otherText))

    # NOTE: wasteful ... ideally, we could somehow make queries run "against" the parent doc?
    otherText.extend(commentsText)
    doc['otherText'] = otherText
    # print('%s: other: %s' % (doc['key'], otherText))
    #if key == 'lucene-4987':
    #  print('OTHER: %s' % otherText)

    if not first:
      bulk.add(',')
    first = False

    update = {'term': {'field': 'key', 'term': key}, 'parent': {'fields': doc}, 'children': subDocs}
    #print("DOC: %s" % update)
    
    if debug:
      print()
      print('Indexed document:')
      prettyPrintJSON(update)

    bulk.add(json.dumps(update))

  bulk.add(']}')

  bulk.finish()

  if updateSuggest:
    suggestFile.close()
    if not first:
      res = svr.send('updateSuggest',
                      {'indexName': 'jira',
                       'suggestName': 'titles_infix',
                       'source': {'localFile': os.path.abspath(suggestFile.name)}})
      print('updateSuggest: %s' % res)

def mapUserName(user):
  user = user.group(1)
  mapped = userNameToDisplayName.get(user[2:-1])
  if mapped is not None:
    #print('map %s to %s' % (user, mapped))
    return '[%s]' % mapped
  else:
    return user

def cleanJiraMarkup(key, s):
  s = s.replace(key.upper() + ':', '')
  s = s.replace('{noformat}', ' ')

  # Don't index quoted parts from prior comments into the current comment:
  s = reQuote.sub(' ', s)
  s = reBQ.sub(' ', s)
  
  s = s.replace('\\', '')
  s = reCode1.sub(r'\1', s)
  s = reCode2.sub(r'\1', s)
  s = reUserName.sub(mapUserName, s)
  s = s.strip()
  return s

if __name__ == '__main__':
  if '-help' in sys.argv:
    print('''
Usage: python3 indexJira.py <options>:
    -server host[:port]  Where Lucene Server is running
    -reindex  Fully reindex
    -nrt  Run forever, indexing jira issues as they are changed
    -delete  If -reindex is specified, this will first delete the entire index, instead of updating it in place
    -buildFullSuggest  Rebuild the infix suggester
    [-help] prints this message
''')
    sys.exit(0)
    
  main()
