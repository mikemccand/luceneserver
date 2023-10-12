import sqlite3
import shutil
import traceback
import github
import re
import time
import sys
import pickle
import urllib.request, urllib.error, urllib.parse
import pprint
import math
import json
import server
import os
import datetime
import localconstants
import util
import gitHistory
from direct_load_all_github_issues import http_load_as_json, load_full_issue

from util import get_or_none

"""
This tool uses GitHub's JSON REST search API to download all issues for
certain Apache projects.  The raw pickled GitHub objects are stored in
an on-disk sqlite3 database, kept up to date by periodically asking GitHub
for which issues changed in the last N seconds.  Then we iterate the
issues from that db into the lucene server index.

A luceneserver instance (default localhost) should already be running
when you run this.
"""

# TODO
#   - separate out tool to incrementally update the sqllite DB, from NRT indexing?  but share its code, or maybe just return list of issues updated
#   - pull out mentions / @calls
#   - hmm: fix suggest to build jira AND github
#   - separate user login vs display name more consistently
#   - parse legacy jira attachments comment, but also new github issue attachments
#   - add
#     - has votes / vote count facet

# all_projects = ('Infrastructure', 'Tika', 'Solr', 'Lucene')
all_projects = ('lucene',)

# e.g.: "Migrated from [LUCENE-373](https://issues.apache.org/jira/browse/LUCENE-373) by Andrew Stevens, 1 vote, updated Jul 28 2015"
# e.g.: "Migrated from [LUCENE-2160](https://issues.apache.org/jira/browse/LUCENE-2160) by John Wang"

re_jira_migrated = re.compile(r'Migrated from \[(LUCENE-\d+)\].*? by (.*?)(?:, (\d+) votes?)?(?:, (resolved|updated) (.*))?$', re.MULTILINE)
re_jira_creator = re.compile(r'(.*?) \(@(.*?)\)')
re_github_issue_url = re.compile('^https://api.github.com/repos/apache/(.*?)/issues')
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
GITHUB_API_TOKEN = localconstants.GITHUB_API_TOKEN

MY_EPOCH = datetime.datetime(year=2014, month=1, day=1)

if True:
  issueToCommitPaths = gitHistory.parseLog()
else:
  issueToCommitPaths = {}

try:
  with open('%s/userNamesMap.pk' % localconstants.ROOT_STATE_PATH, 'rb') as f:
    login_to_name = pickle.loads(f.read())
except FileNotFoundError:
  login_to_name = {}
except:
  print('WARNING: unable to load prior user names map; starting new one')
  login_to_name = {}
    
# For some insane reason, Doug has no display name ;)
login_to_name['cutting@apache.org'] = 'Doug Cutting'

def prettyPrintJSON(obj):
  print(json.dumps(obj,
                   sort_keys=True,
                   indent=4, separators=(',', ': ')))

def parse_date_time(s):
  if False:
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

  # GitHub uses ISO8601:
  return datetime.datetime.fromisoformat(s)

ICU_RULES = open('Latin-dont-break-issues.rbbi').read()

# Latn customized to keep AAAA-NNNN tokens:
ICU_TOKENIZER_KEEP_ISSUES = {
  'class': 'icu',
  'rules': [{'script': 'Latn', 'rules': ICU_RULES}]}

def create_schema(svr):

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
                        {'input': ['gc', 'garbage collection', 'G1GC'], 'output': 'IndexReader'},
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
            'old_jira_id': {'type': 'atom',
                            'store': True},
            'child_key': {'type': 'atom'},
            'other_text': {'type': 'text',
                           'analyzer': analyzer,
                           'multiValued': True},
            'number': {'type': 'int',
                       'search': False,
                       'sort': True},
            'all_users': {'type': 'text',
                         'highlight': True,
                         'store': True,
                         'facet': 'flat',
                         'analyzer': analyzer,
                         'multiValued': True},
            'committed_paths': {'type': 'atom',
                                'search': False,
                                'multiValued': True,
                                'facet': 'hierarchy'},
            'attachments': {'type': 'atom',
                            'multiValued': True,
                            'facet': 'flat'},
            'has_commits': {'type': 'boolean',
                           'facet': 'flat'},
            'is_draft': {'type': 'boolean',
                         'facet': 'flat'},
            'comment_count': {'type': 'int',
                              'sort': True,
                              'store': True},
            'reaction_count': {'type': 'int',
                               'sort': True,
                               'store': True},
            'vote_count': {'type': 'int',
                           'sort': True,
                           'store': True},
            'watch_count': {'type': 'int',
                            'sort': True,
                            'store': True},
            'project': {'type': 'atom',
                        'facet': 'flat',
                        'store': True},
            'labels': {'type': 'atom',
                       'multiValued': True,
                       'facet': 'flat'},
            'reactions': {'type': 'atom',
                          'multiValued': True,
                          'facet': 'flat'},
            'created': {'type': 'long',
                        'store': True,
                        'sort': True},
            'closed': {'type': 'long',
                       'store': True,
                       'sort': True},
            'updated': {'type': 'long',
                        'sort': True,
                        'store': True,
                        'search': True,
                        'facet': 'numericRange'},
            'facet_created': {'type': 'atom',
                              'search': False,
                              'facet': 'hierarchy'},
            'updated_ago': {'type': 'long',
                            'sort': True,
                            'store': True,
                            'search': True,
                            'facet': 'numericRange'},
            'has_reactions': {'type': 'boolean',
                              'store': True,
                              'facet': 'flat'},
            'is_pull_request': {'type': 'boolean',
                                'store': True,
                                'facet': 'flat'},
            'parent': {'type': 'boolean'},
            'milestone': {'type': 'atom',
                          'store': True,
                          'facet': 'flat'},
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
            'closed_by': {'type': 'atom',
                          'facet': 'flat'},
            'priority': {'type': 'int',
                         'sort': True},
            'issue_type': {'type': 'atom',
                           'facet': 'flat'},
            'facet_priority': {'type': 'atom',
                               'group': True,
                               'facet': 'flat'},
            'fix_versions': {'type': 'atom',
                             'facet': 'flat',
                             'multiValued': True},
            'legacy_jira_resolution': {'type': 'atom',
                                       'facet': 'flat'},
            'legacy_jira_priority': {'type': 'atom',
                                     'facet': 'flat'},
            'legacy_jira_labels': {'type': 'atom',
                                   'multiValued': True,
                                   'facet': 'flat'},
            'modules': {'type': 'atom',
                        'search': True,
                        'store': True,
                        'multiValued': True},
            'facet_modules': {'type': 'atom',
                              'search': False,
                              'store': False,
                              'facet': 'hierarchy',
                              'multiValued': True},
            'committed_by': {'type': 'atom',
                             'multiValued': True,
                             'facet': 'flat',
                             'search': True},
            'title': {'type': 'text',
                      'search': True,
                      'store': True,
                      'highlight': True,
                      'similarity': {'class': 'BM25Similarity'},
                      'analyzer': analyzer},
            'body': {'type': 'text',
                     'search': True,
                     'highlight': True,
                     'similarity': {'class': 'BM25Similarity'},
                     'analyzer': analyzer},
            'has_votes': {'type': 'boolean',
                          'search': False,
                          'facet': 'flat'},
            # who last commented on the issue
            'last_contributor': {'type': 'atom',
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
            'commit_url': {'type': 'atom',
                          'search': False,
                          'store': True},
            'comment_id': {'type': 'long',
                          'search': False,
                          'store': True},
            'comment_body': {'type': 'text',
                             'highlight': True,
                             'similarity': {'class': 'BM25Similarity'},
                             'store': True,
                             'analyzer': analyzer},
            }

  result = svr.send('registerFields', {'indexName': 'jira', 'fields': fields})
  print('Done register')

def removeAllGhosts():
  # Remove ghost of renamed issues:

  # we need read/write access here:
  db = sqlite3.connect(DB_PATH)
  
  try:
    toDelete = []
    for k, v in c.execute('SELECT key, body FROM issues'):
      print('check %s' % k)
      v = pickle.loads(v)
      for ent in v['changelog']['histories']:
        for d in ent['items']:
          if 'field' in d and d['field'] == 'Key':
            oldKey = d['fromString']
            print('issue %s renamed to %s; now remove %s' % (oldKey, k, oldKey))
            toDelete.append(oldKey)
    for k in toDelete:
      c.execute('DELETE FROM issues WHERE key = ?', (k,))
    db.commit()
  finally:
    db.close()

def connect_db_readonly():
  path = f'file:{DB_PATH}?mode=ro'
  return sqlite3.connect(path, uri=True, timeout=120)

def all_issues():
  db = connect_db_readonly()
  try:
    c = db.cursor()
    for k, v in c.execute('SELECT key, pickle FROM issues'):
      if k in ('last_update', 'page_upto'):
        continue
      try:
        yield pickle.loads(v)
      except:
        traceback.print_exc()
        print(k)
        raise
  finally:
    db.close()

def specificIssues(issues):
  db = connect_db_readonly()
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
  db = connect_db_readonly()
  try:
    c = db.cursor()
    for k, v in c.execute('SELECT key, pickle FROM issues'):
      # nocommit fixme
      issue, labels, all_comments, all_events = pickle.loads(v)
      fields = issue['fields']
      updated = parse_date_time(fields['created'])
      for x in fields['comment']['comments']:
        if x['comment_body'].find('Closed after release.') == -1:
          updated = max(updated, parse_date_time(x['created']))
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

  github_access_token = getArg('-github_access_token')

  tup = server.split(':')
  host = tup[0]
  if len(tup) == 1:
    port = 8888
  elif len(tup) == 2:
    port = int(tup[1])
  else:
    raise RuntimeError('-server should be host or host:port; got "%s"' % server)

  svr = util.ServerClient(host, port)

  #removeAllGhosts()

  if getFlag('-reindex'):
    full_reindex(svr, getFlag('-delete'))
  elif svr.send('indexStatus', {'indexName': 'jira'})['status'] != 'started':
    svr.send('startIndex', {'indexName': 'jira'})

  if getFlag('-build_full_suggest'):
    build_full_suggest(svr)
    
  if getFlag('-nrt'):
    nrtIndexForever()


def nrtIndexForever():
  now = datetime.datetime.utcnow()

  # First, catch up since last commit:
  if False:
    commitUserData = svr.send('getCommitUserData', {'indexName': 'jira'})
    last_commit_time = pickle.loads(eval(commitUserData['last_commit_time']))
    print('Last commit time %s (%s ago); now catch up' %
          (last_commit_time, now - last_commit_time))
    index_docs(svr, issuesUpdatedAfter(last_commit_time), updateSuggest=True)

  # not read only, because we write new issue/pr updates into it:
  db = sqlite3.connect(DB_PATH)
  c = db.cursor()

  last_update_utc = None
  rows = c.execute('SELECT pickle FROM issues WHERE key="last_update"').fetchall()
  if len(rows) == 1:
    last_update_utc = pickle.loads(rows[0][0])
  else:
    raise RuntimeError(f'should be one row with "last_update" key but found {len(rows)}')
  if last_update_utc is None:
    print('WARNING: no last_update -- crawling all updates from two weeks ago until now')
    last_update_utc = now - datetime.timedelta(days=14)

  first = False
  lastSuggestBuild = time.time()
  lastGITBuild = 0
  lastCommit = time.time()
  # Force a git refresh on startup:
  any_updates_since_git = True

  while True:

    nrt_started_utc = datetime.datetime.utcnow()

    since_utc = last_update_utc - datetime.timedelta(seconds=60)

    print('\n%s: nrt index' % datetime.datetime.now())
    print(f'  use since={since_utc} ({(nrt_started_utc-since_utc).total_seconds()} seconds ago)')
    print(f'  GitHub rate_limit={g.get_rate_limit()}')

    page = 1

    # in case we need to load multiple pages to get the updated issues:
    while True:

      # hopefully we never wind up throttling here due to too many issue updates versus GitHub API rate limit!
      batch = http_load_as_json(f'https://api.github.com/repos/apache/lucene/issues?state=all&per_page=100&direction=asc&since={since_utc.isoformat()}&page={page}')
      if page == 1:
        total_count = batch['total_count']
      print(f'  {total_count} issues updated to load')

      full_issues = []

      for issue in batch:
        any_updates_since_git = True

        now = datetime.datetime.now()

        comments, events, reactions, timeline = load_full_issue(issue)

        c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)',
                  (str(issue.number), pickle.dumps((issue, comments, events, reactions, timeline))))
        full_issues.append((issue, comments, events, reactions, timeline))

        # Remove ghost of any just renamed issues:
        # nocommit TODO
        if False:
          for ent in issue['changelog']['histories']:
            for d in ent['items']:
              if 'field' in d and d['field'] == 'Key':
                oldKey = d['fromString']
                print('issue %s renamed to %s; now remove %s' % (oldKey, issue['key'], oldKey))
                c.execute('DELETE FROM issues WHERE key = ?', (oldKey,))

      page += 1
      if not batch['incomplete_results']:
        break

    if len(full_issues) != total_count:
      print(f'WARNING: iterated through {len(full_issues)} issues but GitHub issues API claimed we would see {total_count}')

    index_start_time_sec = time.time()
    index_docs(svr, full_issues, printIssue=True, updateSuggest=True)
    print(f'  {(time.time() - index_start_time_sec):.1f} sec to index')

    c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)', ('last_update', pickle.dumps(nrt_started_utc),))
    db.commit()

    total_issue_count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]

    last_update_utc = nrt_started_utc

    print(f'  loaded and indexed {len(full_issues)} issues; {total_issue_count} issues in DB')

    # Check for git commits every 30 minutes:
    if time.time() - lastGITBuild > 30*60 and any_updates_since_git:
      lastGITBuild = time.time()
      newIssueToCommitPaths, committedIssues = gitHistory.refresh()
      # merge new git history into our in-memory version:
      mergeIssueCommits(issueToCommitPaths, newIssueToCommitPaths)
      print('  update from git commits...')
      index_docs(svr, specificIssues(committedIssues), printIssue=True)
      print('  done update from git commits...')
      any_updates_since_git = False

    # Commit once per day, so if server goes down we only need to
    # reindex at most past day's worth of updated issues:
    if now - last_commit_time > datetime.timedelta(days=1):
      commit(svr, now)
      last_commit_time = now

    time.sleep(5.0)
  
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

def build_full_suggest(svr):
  print('Build suggest...')
  t0 = time.time()
  suggestFile = open('%s/jira.suggest' % localconstants.ROOT_STATE_PATH, 'wb')
  allUsers = {}

  for issue, comments, events, reactions, timeline in all_issues():
    key = issue['number']
    project = extract_project(issue)
    reporter = extract_reporter(issue)
    add_user(allUsers, reporter, project, key)

    if issue['assignees'] is not None and len(issue['assignees']) > 0:
      for x in issue['assignees']:
        add_user(all_users, x, project, key)
    
    updated = parse_date_time(fields['created_at'])
    for comment in comments:
      if comment['body'] != 'Closed after release.':
        updated = max(updated, parse_date_time(comment['created']))
      add_user(allUsers, comment['user'], project, key)

    for change in events:
      didAttach = False
      for item in change['items']:
        if 'field' in item and item['field'] == 'Attachment':
          didAttach = True

      if didAttach:
        #prettyPrintJSON(change)
        if 'author' in change:
          add_user(allUsers, change['author'], project, key)

    weight = (updated-MY_EPOCH).total_seconds()

    # Index project as a context, so we can suggest within project:
    suggestFile.write(('%d\x1f%s: %s\x1f%s\x1f%s\n' % (weight, key.upper(), fields['title'], key, project)).encode('utf-8'))

  for userDisplayName, (count, projects) in sorted(allUsers.items(), key = lambda x: (-x[1][0], x[0])):
    suggestFile.write(('%d\x1f%s\x1fuser %s\x1f%s\n' % \
                       (count, userDisplayName, userDisplayName, '\x1f'.join(projects))).encode('utf-8'))

  for project in all_projects:
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

def full_reindex(svr, doDelete):

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
    create_schema(svr)

    #svr.send('deleteAllDocuments', {'indexName': 'jira'})

  index_docs(svr, all_issues(), updateSuggest=False)
  build_full_suggest(svr)

  print('Done full index')
  commit(svr, startTime)

  open('%s/userNamesMap.pk' % localconstants.ROOT_STATE_PATH, 'wb').write(pickle.dumps(login_to_name))

def commit(svr, timeStamp):
  t0 = time.time()
  svr.send('setCommitUserData', {'indexName': 'jira',
                                 'userData': {'lastCommitTime': repr(pickle.dumps(timeStamp))}})
  svr.send('commit', {'indexName': 'jira'})
  print('Commit took %.1f msec' % (1000*(time.time()-t0)))

def is_commit_user(user):
  #print(f'{user=}')
  for s in ('Commit Tag Bot', 'ASF subversion and git services', 'ASF GitHub Bot'):
    if ('name' in user and user['name'] is not None and s in user['name']) or \
       ('login' in user and user['login'] is not None and s in user['login']):
      return True
  return False

def add_user(all_users, user, project, key=None):
  if hasattr(user, 'name') and user.name is not None:
    display_name = user.name
  else:
    display_name = '???'

  if hasattr(user, 'login') and user.login is not None:
    login = user.login
  else:
    login = '???'
    
  if display_name == 'cutting@apache.org':
    display_name = 'Doug Cutting'
  if is_commit_user(user):
    display_name = 'commitbot'
  if display_name not in all_users:
    all_users[display_name] = [0, set()]
  l = all_users[display_name]
  l[0] += 1
  l[1].add(project)

  if login != '???' and display_name != '???':
    login_to_name[login] = display_name

class User:
  name = None
  login = None

  def __init__(self, name, login):
    self.name = name
    self.login = login

def extract_project(issue):
  m = re_github_issue_url.match(issue['url'])
  assert m is not None
  return m.group(1)

def extract_reporter(issue):
  if issue['body'] is not None:
    m = re_jira_migrated.search(issue['body'])
    if m is not None:
      m2 = re_jira_creator.match(m.group(2))
      if m2 is not None:
        name = m2.group(1)
        login = m2.group(2)
      else:
        name = m.group(2)
        login = None
      return {'name': name, 'login': login}
  # print(json.dumps(issue, indent=2))
  return {'name': None, 'login': issue['user']['login']}

def index_docs(svr, issues, printIssue=False, updateSuggest=False):

  bulk = server.ChunkedSend(svr, 'bulkUpdateDocuments', 32768)
  bulk.add('{"indexName": "jira", "documents": [')

  if False and updateSuggest:
    suggestFile = open('%s/jiranrt.suggest' % localconstants.ROOT_STATE_PATH, 'wb')

  now = datetime.datetime.now()

  issue_count = 0
  first = True
  
  for issue, comments, events, reactions, timeline in issues:

    project = extract_project(issue)

    if project not in all_projects:
      # This can happen when the issue is renamed to a project outside
      # of the ones we index:
      continue

    issue_count += 1

    number = issue['number']

    print(f'\n\nnow index issue {number}')
    #print(json.dumps(issue, indent=2))

    if printIssue:
      print(f'  {number}')

    # All users who have done something on this issue:
    all_users = {}

    # TODO: break out issue type by the labels?
    # TODO: break out issue module by the labels?

    # TODO: does issue title have markup?

    key = str(number)

    doc = {'key': str(number),
           'number': number,
           'parent': True,
           'title': issue['title']}

    reaction_count = issue['reactions']['total_count']
    doc['reaction_count'] = reaction_count
    
    if reactions is not None and len(reactions) > 0:
      print(f'reactions: {reactions}')
      if reaction_count != len(reactions):
        print(f'WARNING: issue {issue["number"]} claims {reaction_count} reactions but saw {len(reactions)}')
      if len(reactions) > 0:
        print(json.dumps(issue, indent=2))
      reaction_names = set()
      for k, v in issue['reactions'].items():
        if k in ('url', 'total_count'):
          continue
        assert type(v) is int
        if v > 0:
          reaction_names.add(k)
      doc['reactions'] = list(reaction_names)

    for event in events:
      #if event['event'] != 'closed':
        #print(f'event: {json.dumps(event, indent=2)}')
      #print(f'event: {event.actor.login} {event.event} {event.created_at} {event.label} {event.assignee} {event.assigner} {event.review_requester} {event.requested_reviewer} {event.dismissed_review} {getattr(event, "team", None)} {event.milestone} {event.rename} {event.lock_reason}')

      add_user(all_users, event['actor'], project)

    # who opened the issue/PR
    if issue['user'] is not None:
      doc['reporter'] = issue['user']['login']
      add_user(all_users, issue['user'], project)

    # TODO: what is body vs body_text?  markup removed?
    if issue['body'] is not None:
      doc['body'] = clean_github_markdown(number, issue['body'])

    if issue['locked']:
      doc['locked'] = issue['lock_reason']

    doc['project'] = project

    doc['status'] = issue['state']
    if 'state_reason' in issue and issue['state_reason'] is not None:
      doc['status'] += f' ({issue["state_reason"]})'

    if False:
      p = fields['priority']
      if p is not None:
        doc['facetPriority'] = p['name']
        doc['priority'] = int(p['id'])

    # milestone
    if issue['milestone'] is not None:
      doc['milestone'] = issue['milestone']['title']

    # assignee / assignees
    # TODO: what to do about multiple assignees?  does it really happen?
    if issue['assignees'] is not None and len(issue['assignees']) > 0:
      assignees = []
      #print(f'multiple assignees!! {len(issue["assignees"])}')
      #print(f'  assignee={issue["assignee"]}')
      if len(issue['assignees']) > 1:
        print(f'multiple assignees!! {len(issue["assignees"])}')
        print(f'  assignees={json.dumps(issue["assignees"], indent=2)}')
        print(f'  assignee={json.dumps(issue["assignee"], indent=2)}')
        
      for x in issue['assignees']:
        assignees.append(x['login'])
        add_user(all_users, x, project)
        doc['assignee'] = x['login']
    elif issue['assignee'] is not None:
      doc['assignee'] = issue['assignee']['login']
      add_user(all_users, issue['assignee'], project)
    else:
      doc['assignee'] = 'Unassigned'

    if issue['body'] is not None:
      m = re_jira_migrated.search(issue['body'])
      if m is not None:
        # try to preserve original Jira metadata if possible:
        doc['old_jira_id'] = m.group(1)

        # TODO: turn into datetime or long?
        if m.group(3) is not None:
          if 'reaction_count' in doc:
            doc['reaction_count'] += int(m.group(3))
          else:
            doc['reaction_count'] = int(m.group(3))
        if m.group(4) == 'resolved':
          closed_dt = datetime.datetime.strptime(m.group(5).strip(), '%b %d %Y')
          #doc['closed'] = int(float(closed_dt.timestamp()))
          doc['closed'] = int(closed_dt.timestamp())
    else:
      # this is OK, e.g. https://github.com/apache/lucene/pull/945
      # print(f'WARNING: issue {number} has no body!')
      pass

    reporter = extract_reporter(issue)
    if reporter['login'] is not None:
      s = reporter['login']
    else:
      s = reporter['name']
    if s is not None:
      doc['reporter'] = s

    doc['has_reactions'] = doc.get('reaction_count', 0) > 0

    # TODO
    if False:
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
        doc['committed_paths'] = cps

    if False:
      # TODO!!
      l = []
      l2 = []
      for x in fields['components']:
        l2.append(x['name'])
        l.append(list(x['name'].split('/')))

      doc['facetComponents'] = l
      doc['components'] = l2

    if False:
      attachments = set()
      #print('\nISSUE: %s' % key.upper().strip())
      for change in issue['changelog']['histories']:
        #print('  change: %s' % str(change))
        didAttach = False
        for item in change['items']:
          if 'field' in item and item['field'] == 'Attachment':
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
            add_user(all_users, change['author'], project)
      if len(attachments) == 0:
        attachments.add('None')
      doc['attachments'] = list(attachments)
                
    subDocs = []

    has_commits = False
    
    doc['comment_count'] = issue['comments']
    doc['is_pull_request'] = 'pull_request' in issue
    # TODO: merged_at?

    if issue['created_at'] is not None:
      print(f'{issue["created_at"]}')
      doc['created'] = int(parse_date_time(issue['created_at']).timestamp())
    if issue['closed_at'] is not None:
      doc['closed'] = int(parse_date_time(issue['closed_at']).timestamp())
    updated = parse_date_time(issue['updated_at'])
    doc['updated'] = int(updated.timestamp())

    # TODO: is there a closed_by user?

    if 'draft' in issue:
      print('NOTE HAS DRAFT')
      doc['is_draft'] = issue['draft']

    labels = []
    facet_modules = []
    jira_resolution = None
    for x in issue['labels']:
      if type(x) is str:
        label = x
      else:
        label = x['name']
      print(f'  label: {label}')
      if label.startswith('type:'):
        if 'issue_type' in doc:
          print(f'more than one issue_type?  {doc["issue_type"]} and {label[5:]}')
        if 'issue_type' not in doc:
          doc['issue_type'] = []
        # doc['issue_type'].append(label[5:])
        doc['issue_type'] = label[5:]
      elif label.startswith('module:'):
        if 'modules' not in doc:
          doc['modules'] = []
        module = label[7:]
        doc['modules'].append(module)
        facet_modules.append(list(module.split('/')))
      elif label.startswith('legacy-jira-resolution:'):
        assert jira_resolution is None
        jira_resolution = label[23:]
        doc['status'] += f' {jira_resolution}'
      elif label.startswith('legacy-jira-priority:'):
        assert 'legacy_jira_priority' not in doc
        doc['legacy_jira_priority'] = label[21:]
      elif label.startswith('legacy-jira-label:'):
        if 'legacy_jira_labels' not in doc:
          doc['legacy_jira_labels'] = []
        doc['legacy_jira_labels'].append(label[18:])
      else:
        labels.append(label)
    doc['labels'] = labels
    doc['facet_modules'] = facet_modules
    comments_text = []
    last_contributor = None

    # for i, comment in enumerate(comments):
    for comment in comments:
      # print(f'comment: {comment}')
      add_user(all_users, comment['user'], project)

      # TODO: we don't bother loading these from GitHub now:
      if False:
        # each comment has an array of reactions:
        for reaction in list(comment_reactions[i]):
          print(f'  comment reaction: {reaction.user} {reaction.content} {reaction.created_at}')
          add_user(all_users, reaction.user, project)

      subDoc = {}
      subDoc['author'] = comment['user']['login']

      # TODO: fixme to detect migrated Jira comment, and new GitHub style commit comment
      isCommit = is_commit_user(comment['user'])
      body = comment['body']
      if isCommit:
        subDoc['author'] = 'commitbot'
        has_commits = True
        m = reCommitURL.findall(body)
        if len(m) > 0:
          for y in m:
            if 'git-wip-us' in y or 'svn.apache.org/r' in y:
              subDoc['commit_url'] = y.strip()
              #print('GIT: %s' % subDoc['commitURL'])
              break
        if 'commit_url' not in subDoc:
          # back compat: try old SVN commit Jira comment syntax
          m = reSVNCommitURL.search(body)
          if m is not None:
            subDoc['commit_url'] = m.group(1).strip()
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
        last_contributor = subDoc['author']

      subDoc['comment_body'] = clean_github_markdown(number, body)
      comments_text.append(subDoc['comment_body'])

      subDoc['comment_id'] = comment['id']
      # Disregard the bulk-update after X.Y release:
      if subDoc['comment_body'] != 'Closed after release.':
        updated = max(updated, parse_date_time(comment['created_at']))
      subDoc['created'] = int(float(parse_date_time(comment['created_at']).strftime('%s.%f')))

      # TODO: why store this twice in each child doc!?
      subDoc['key'] = key
      subDoc['child_key'] = key
      subDocs.append({'fields': subDoc})

    # Compute our own updated instead of using Jira's, to be max(createTime, comments):
    # nocommit: is github's updated_at more trustworthy?
    # doc['updated'] = int(updated.timestamp())
    print(f'updated: {doc["updated"]} vs recomputed {int(updated.timestamp())}')

    # TODO: maybe lucene server needs a copy field:
    # nocommit: hmm why is this a separate field?  looks identical to "updated"?
    doc['updated_ago'] = doc['updated']

    if last_contributor is not None:
      doc['last_contributor'] = last_contributor

    if updateSuggest:
      weight = (updated-MY_EPOCH).total_seconds()
      suggestFile.write(('%d\x1f%s: %s\x1f%s\x1f%s\n' % (weight, key.upper(), fields['title'], key, project)).encode('utf-8'))

    l = [(y[0], x) for x, y in list(all_users.items())]
    l.sort(reverse=True)
    doc['all_users'] = [x for y, x in l]
    doc['has_commits'] = has_commits

    other_text = []
    other_text.append(doc['key'])
    other_text.extend(doc['key'].split('-'))
    other_text.append(' '.join(doc['labels']))
    print(f'{number}: other {other_text}')

    # NOTE: wasteful ... ideally, we could somehow make queries run "against" the parent doc?
    # TODO: why not just index child doc text field!?  block join would take care...
    other_text.extend(comments_text)
    doc['other_text'] = other_text

    update = {'term': {'field': 'number', 'term': str(number)}, 'parent': {'fields': doc}, 'children': subDocs}
    # print(f'\nDOC: {json.dumps(update, indent=2)}')

    if False:
      print(f'\n\n{number}:')
      pprint.pprint(doc)
    
    if False and debug:
      print()
      print('Indexed document:')
      prettyPrintJSON(update)

    if not first:
      bulk.add(',')
    first = False
    
    bulk.add(json.dumps(update))

  print(f'{issue_count} issues indexed')

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
  mapped = login_to_name.get(user[2:-1])
  if mapped is not None:
    #print('map %s to %s' % (user, mapped))
    return '[%s]' % mapped
  else:
    return user

re_github_md_link = re.compile(r'\[(.*?)\]\((.*?)\)')

def clean_github_markdown(key, s):
  # TODO: fixme!!
  s0 = re_github_md_link.sub(r'\1', s)

  if False:
    if s != s0:
      print(f'\nfixed link(s) from {s} to {s0}')
    
  return s0

if __name__ == '__main__':
  if '-help' in sys.argv:
    print('''
Usage: python3 index_github.py <options>:
    -server host[:port]  Where Lucene Server is running
    -reindex  Fully reindex
    -nrt  Run forever, indexing jira issues as they are changed
    -delete  If -reindex is specified, this will first delete the entire index, instead of updating it in place
    -build_full_suggest  Rebuild the infix suggester
    [-help] prints this message
''')
    sys.exit(0)
    
  main()



# Schema for an issue (from https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28#list-repository-issues):

'''
{
  "type": "array",
  "items": {
    "title": "Issue",
    "description": "Issues are a great way to keep track of tasks, enhancements, and bugs for your projects.",
    "type": "object",
    "properties": {
      "id": {
        "type": "integer"
      },
      "node_id": {
        "type": "string"
      },
      "url": {
        "description": "URL for the issue",
        "type": "string",
        "format": "uri",
        "examples": [
          "https://api.github.com/repositories/42/issues/1"
        ]
      },
      "repository_url": {
        "type": "string",
        "format": "uri"
      },
      "labels_url": {
        "type": "string"
      },
      "comments_url": {
        "type": "string",
        "format": "uri"
      },
      "events_url": {
        "type": "string",
        "format": "uri"
      },
      "html_url": {
        "type": "string",
        "format": "uri"
      },
      "number": {
        "description": "Number uniquely identifying the issue within its repository",
        "type": "integer",
        "examples": [
          42
        ]
      },
      "state": {
        "description": "State of the issue; either 'open' or 'closed'",
        "type": "string",
        "examples": [
          "open"
        ]
      },
      "state_reason": {
        "description": "The reason for the current state",
        "type": [
          "string",
          "null"
        ],
        "enum": [
          "completed",
          "reopened",
          "not_planned",
          null
        ],
        "examples": [
          "not_planned"
        ]
      },
      "title": {
        "description": "Title of the issue",
        "type": "string",
        "examples": [
          "Widget creation fails in Safari on OS X 10.8"
        ]
      },
      "body": {
        "description": "Contents of the issue",
        "type": [
          "string",
          "null"
        ],
        "examples": [
          "It looks like the new widget form is broken on Safari. When I try and create the widget, Safari crashes. This is reproducible on 10.8, but not 10.9. Maybe a browser bug?"
        ]
      },
      "user": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          }
        ]
      },
      "labels": {
        "description": "Labels to associate with this issue; pass one or more label names to replace the set of labels on this issue; send an empty array to clear all labels from the issue; note that the labels are silently dropped for users without push access to the repository",
        "type": "array",
        "items": {
          "oneOf": [
            {
              "type": "string"
            },
            {
              "type": "object",
              "properties": {
                "id": {
                  "type": "integer",
                  "format": "int64"
                },
                "node_id": {
                  "type": "string"
                },
                "url": {
                  "type": "string",
                  "format": "uri"
                },
                "name": {
                  "type": "string"
                },
                "description": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "color": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "default": {
                  "type": "boolean"
                }
              }
            }
          ]
        },
        "examples": [
          "bug",
          "registration"
        ]
      },
      "assignee": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          }
        ]
      },
      "assignees": {
        "type": [
          "array",
          "null"
        ],
        "items": {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      },
      "milestone": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Milestone",
            "description": "A collection of related issues and pull requests.",
            "type": "object",
            "properties": {
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/repos/octocat/Hello-World/milestones/1"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat/Hello-World/milestones/v1.0"
                ]
              },
              "labels_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/repos/octocat/Hello-World/milestones/1/labels"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1002604
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDk6TWlsZXN0b25lMTAwMjYwNA=="
                ]
              },
              "number": {
                "description": "The number of the milestone.",
                "type": "integer",
                "examples": [
                  42
                ]
              },
              "state": {
                "description": "The state of the milestone.",
                "type": "string",
                "enum": [
                  "open",
                  "closed"
                ],
                "default": "open",
                "examples": [
                  "open"
                ]
              },
              "title": {
                "description": "The title of the milestone.",
                "type": "string",
                "examples": [
                  "v1.0"
                ]
              },
              "description": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "Tracking milestone for version 1.0"
                ]
              },
              "creator": {
                "anyOf": [
                  {
                    "type": "null"
                  },
                  {
                    "title": "Simple User",
                    "description": "A GitHub user.",
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "email": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "login": {
                        "type": "string",
                        "examples": [
                          "octocat"
                        ]
                      },
                      "id": {
                        "type": "integer",
                        "examples": [
                          1
                        ]
                      },
                      "node_id": {
                        "type": "string",
                        "examples": [
                          "MDQ6VXNlcjE="
                        ]
                      },
                      "avatar_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://github.com/images/error/octocat_happy.gif"
                        ]
                      },
                      "gravatar_id": {
                        "type": [
                          "string",
                          "null"
                        ],
                        "examples": [
                          "41d064eb2195891e12d0413f63227ea7"
                        ]
                      },
                      "url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat"
                        ]
                      },
                      "html_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://github.com/octocat"
                        ]
                      },
                      "followers_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/followers"
                        ]
                      },
                      "following_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/following{/other_user}"
                        ]
                      },
                      "gists_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/gists{/gist_id}"
                        ]
                      },
                      "starred_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                        ]
                      },
                      "subscriptions_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/subscriptions"
                        ]
                      },
                      "organizations_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/orgs"
                        ]
                      },
                      "repos_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/repos"
                        ]
                      },
                      "events_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/events{/privacy}"
                        ]
                      },
                      "received_events_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/received_events"
                        ]
                      },
                      "type": {
                        "type": "string",
                        "examples": [
                          "User"
                        ]
                      },
                      "site_admin": {
                        "type": "boolean"
                      },
                      "starred_at": {
                        "type": "string",
                        "examples": [
                          "\"2020-07-09T00:17:55Z\""
                        ]
                      }
                    },
                    "required": [
                      "avatar_url",
                      "events_url",
                      "followers_url",
                      "following_url",
                      "gists_url",
                      "gravatar_id",
                      "html_url",
                      "id",
                      "node_id",
                      "login",
                      "organizations_url",
                      "received_events_url",
                      "repos_url",
                      "site_admin",
                      "starred_url",
                      "subscriptions_url",
                      "type",
                      "url"
                    ]
                  }
                ]
              },
              "open_issues": {
                "type": "integer",
                "examples": [
                  4
                ]
              },
              "closed_issues": {
                "type": "integer",
                "examples": [
                  8
                ]
              },
              "created_at": {
                "type": "string",
                "format": "date-time",
                "examples": [
                  "2011-04-10T20:09:31Z"
                ]
              },
              "updated_at": {
                "type": "string",
                "format": "date-time",
                "examples": [
                  "2014-03-03T18:58:10Z"
                ]
              },
              "closed_at": {
                "type": [
                  "string",
                  "null"
                ],
                "format": "date-time",
                "examples": [
                  "2013-02-12T13:22:01Z"
                ]
              },
              "due_on": {
                "type": [
                  "string",
                  "null"
                ],
                "format": "date-time",
                "examples": [
                  "2012-10-09T23:39:01Z"
                ]
              }
            },
            "required": [
              "closed_issues",
              "creator",
              "description",
              "due_on",
              "closed_at",
              "id",
              "node_id",
              "labels_url",
              "html_url",
              "number",
              "open_issues",
              "state",
              "title",
              "url",
              "created_at",
              "updated_at"
            ]
          }
        ]
      },
      "locked": {
        "type": "boolean"
      },
      "active_lock_reason": {
        "type": [
          "string",
          "null"
        ]
      },
      "comments": {
        "type": "integer"
      },
      "pull_request": {
        "type": "object",
        "properties": {
          "merged_at": {
            "type": [
              "string",
              "null"
            ],
            "format": "date-time"
          },
          "diff_url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri"
          },
          "html_url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri"
          },
          "patch_url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri"
          },
          "url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri"
          }
        },
        "required": [
          "diff_url",
          "html_url",
          "patch_url",
          "url"
        ]
      },
      "closed_at": {
        "type": [
          "string",
          "null"
        ],
        "format": "date-time"
      },
      "created_at": {
        "type": "string",
        "format": "date-time"
      },
      "updated_at": {
        "type": "string",
        "format": "date-time"
      },
      "draft": {
        "type": "boolean"
      },
      "closed_by": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          }
        ]
      },
      "body_html": {
        "type": "string"
      },
      "body_text": {
        "type": "string"
      },
      "timeline_url": {
        "type": "string",
        "format": "uri"
      },
      "repository": {
        "title": "Repository",
        "description": "A repository on GitHub.",
        "type": "object",
        "properties": {
          "id": {
            "description": "Unique identifier of the repository",
            "type": "integer",
            "examples": [
              42
            ]
          },
          "node_id": {
            "type": "string",
            "examples": [
              "MDEwOlJlcG9zaXRvcnkxMjk2MjY5"
            ]
          },
          "name": {
            "description": "The name of the repository.",
            "type": "string",
            "examples": [
              "Team Environment"
            ]
          },
          "full_name": {
            "type": "string",
            "examples": [
              "octocat/Hello-World"
            ]
          },
          "license": {
            "anyOf": [
              {
                "type": "null"
              },
              {
                "title": "License Simple",
                "description": "License Simple",
                "type": "object",
                "properties": {
                  "key": {
                    "type": "string",
                    "examples": [
                      "mit"
                    ]
                  },
                  "name": {
                    "type": "string",
                    "examples": [
                      "MIT License"
                    ]
                  },
                  "url": {
                    "type": [
                      "string",
                      "null"
                    ],
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/licenses/mit"
                    ]
                  },
                  "spdx_id": {
                    "type": [
                      "string",
                      "null"
                    ],
                    "examples": [
                      "MIT"
                    ]
                  },
                  "node_id": {
                    "type": "string",
                    "examples": [
                      "MDc6TGljZW5zZW1pdA=="
                    ]
                  },
                  "html_url": {
                    "type": "string",
                    "format": "uri"
                  }
                },
                "required": [
                  "key",
                  "name",
                  "url",
                  "spdx_id",
                  "node_id"
                ]
              }
            ]
          },
          "organization": {
            "anyOf": [
              {
                "type": "null"
              },
              {
                "title": "Simple User",
                "description": "A GitHub user.",
                "type": "object",
                "properties": {
                  "name": {
                    "type": [
                      "string",
                      "null"
                    ]
                  },
                  "email": {
                    "type": [
                      "string",
                      "null"
                    ]
                  },
                  "login": {
                    "type": "string",
                    "examples": [
                      "octocat"
                    ]
                  },
                  "id": {
                    "type": "integer",
                    "examples": [
                      1
                    ]
                  },
                  "node_id": {
                    "type": "string",
                    "examples": [
                      "MDQ6VXNlcjE="
                    ]
                  },
                  "avatar_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://github.com/images/error/octocat_happy.gif"
                    ]
                  },
                  "gravatar_id": {
                    "type": [
                      "string",
                      "null"
                    ],
                    "examples": [
                      "41d064eb2195891e12d0413f63227ea7"
                    ]
                  },
                  "url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat"
                    ]
                  },
                  "html_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://github.com/octocat"
                    ]
                  },
                  "followers_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/followers"
                    ]
                  },
                  "following_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/following{/other_user}"
                    ]
                  },
                  "gists_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/gists{/gist_id}"
                    ]
                  },
                  "starred_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                    ]
                  },
                  "subscriptions_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/subscriptions"
                    ]
                  },
                  "organizations_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/orgs"
                    ]
                  },
                  "repos_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/repos"
                    ]
                  },
                  "events_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/events{/privacy}"
                    ]
                  },
                  "received_events_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/received_events"
                    ]
                  },
                  "type": {
                    "type": "string",
                    "examples": [
                      "User"
                    ]
                  },
                  "site_admin": {
                    "type": "boolean"
                  },
                  "starred_at": {
                    "type": "string",
                    "examples": [
                      "\"2020-07-09T00:17:55Z\""
                    ]
                  }
                },
                "required": [
                  "avatar_url",
                  "events_url",
                  "followers_url",
                  "following_url",
                  "gists_url",
                  "gravatar_id",
                  "html_url",
                  "id",
                  "node_id",
                  "login",
                  "organizations_url",
                  "received_events_url",
                  "repos_url",
                  "site_admin",
                  "starred_url",
                  "subscriptions_url",
                  "type",
                  "url"
                ]
              }
            ]
          },
          "forks": {
            "type": "integer"
          },
          "permissions": {
            "type": "object",
            "properties": {
              "admin": {
                "type": "boolean"
              },
              "pull": {
                "type": "boolean"
              },
              "triage": {
                "type": "boolean"
              },
              "push": {
                "type": "boolean"
              },
              "maintain": {
                "type": "boolean"
              }
            },
            "required": [
              "admin",
              "pull",
              "push"
            ]
          },
          "owner": {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          },
          "private": {
            "description": "Whether the repository is private or public.",
            "default": false,
            "type": "boolean"
          },
          "html_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://github.com/octocat/Hello-World"
            ]
          },
          "description": {
            "type": [
              "string",
              "null"
            ],
            "examples": [
              "This your first repo!"
            ]
          },
          "fork": {
            "type": "boolean"
          },
          "url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://api.github.com/repos/octocat/Hello-World"
            ]
          },
          "archive_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/{archive_format}{/ref}"
            ]
          },
          "assignees_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/assignees{/user}"
            ]
          },
          "blobs_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/blobs{/sha}"
            ]
          },
          "branches_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/branches{/branch}"
            ]
          },
          "collaborators_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/collaborators{/collaborator}"
            ]
          },
          "comments_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/comments{/number}"
            ]
          },
          "commits_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/commits{/sha}"
            ]
          },
          "compare_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/compare/{base}...{head}"
            ]
          },
          "contents_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/contents/{+path}"
            ]
          },
          "contributors_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/contributors"
            ]
          },
          "deployments_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/deployments"
            ]
          },
          "downloads_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/downloads"
            ]
          },
          "events_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/events"
            ]
          },
          "forks_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/forks"
            ]
          },
          "git_commits_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/commits{/sha}"
            ]
          },
          "git_refs_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/refs{/sha}"
            ]
          },
          "git_tags_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/tags{/sha}"
            ]
          },
          "git_url": {
            "type": "string",
            "examples": [
              "git:github.com/octocat/Hello-World.git"
            ]
          },
          "issue_comment_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/issues/comments{/number}"
            ]
          },
          "issue_events_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/issues/events{/number}"
            ]
          },
          "issues_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/issues{/number}"
            ]
          },
          "keys_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/keys{/key_id}"
            ]
          },
          "labels_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/labels{/name}"
            ]
          },
          "languages_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/languages"
            ]
          },
          "merges_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/merges"
            ]
          },
          "milestones_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/milestones{/number}"
            ]
          },
          "notifications_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/notifications{?since,all,participating}"
            ]
          },
          "pulls_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/pulls{/number}"
            ]
          },
          "releases_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/releases{/id}"
            ]
          },
          "ssh_url": {
            "type": "string",
            "examples": [
              "git@github.com:octocat/Hello-World.git"
            ]
          },
          "stargazers_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/stargazers"
            ]
          },
          "statuses_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/statuses/{sha}"
            ]
          },
          "subscribers_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/subscribers"
            ]
          },
          "subscription_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/subscription"
            ]
          },
          "tags_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/tags"
            ]
          },
          "teams_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/teams"
            ]
          },
          "trees_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/trees{/sha}"
            ]
          },
          "clone_url": {
            "type": "string",
            "examples": [
              "https://github.com/octocat/Hello-World.git"
            ]
          },
          "mirror_url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri",
            "examples": [
              "git:git.example.com/octocat/Hello-World"
            ]
          },
          "hooks_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/hooks"
            ]
          },
          "svn_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://svn.github.com/octocat/Hello-World"
            ]
          },
          "homepage": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri",
            "examples": [
              "https://github.com"
            ]
          },
          "language": {
            "type": [
              "string",
              "null"
            ]
          },
          "forks_count": {
            "type": "integer",
            "examples": [
              9
            ]
          },
          "stargazers_count": {
            "type": "integer",
            "examples": [
              80
            ]
          },
          "watchers_count": {
            "type": "integer",
            "examples": [
              80
            ]
          },
          "size": {
            "description": "The size of the repository. Size is calculated hourly. When a repository is initially created, the size is 0.",
            "type": "integer",
            "examples": [
              108
            ]
          },
          "default_branch": {
            "description": "The default branch of the repository.",
            "type": "string",
            "examples": [
              "master"
            ]
          },
          "open_issues_count": {
            "type": "integer",
            "examples": [
              0
            ]
          },
          "is_template": {
            "description": "Whether this repository acts as a template that can be used to generate new repositories.",
            "default": false,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "topics": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "has_issues": {
            "description": "Whether issues are enabled.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "has_projects": {
            "description": "Whether projects are enabled.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "has_wiki": {
            "description": "Whether the wiki is enabled.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "has_pages": {
            "type": "boolean"
          },
          "has_downloads": {
            "description": "Whether downloads are enabled.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "has_discussions": {
            "description": "Whether discussions are enabled.",
            "default": false,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "archived": {
            "description": "Whether the repository is archived.",
            "default": false,
            "type": "boolean"
          },
          "disabled": {
            "type": "boolean",
            "description": "Returns whether or not this repository disabled."
          },
          "visibility": {
            "description": "The repository visibility: public, private, or internal.",
            "default": "public",
            "type": "string"
          },
          "pushed_at": {
            "type": [
              "string",
              "null"
            ],
            "format": "date-time",
            "examples": [
              "2011-01-26T19:06:43Z"
            ]
          },
          "created_at": {
            "type": [
              "string",
              "null"
            ],
            "format": "date-time",
            "examples": [
              "2011-01-26T19:01:12Z"
            ]
          },
          "updated_at": {
            "type": [
              "string",
              "null"
            ],
            "format": "date-time",
            "examples": [
              "2011-01-26T19:14:43Z"
            ]
          },
          "allow_rebase_merge": {
            "description": "Whether to allow rebase merges for pull requests.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "template_repository": {
            "type": [
              "object",
              "null"
            ],
            "properties": {
              "id": {
                "type": "integer"
              },
              "node_id": {
                "type": "string"
              },
              "name": {
                "type": "string"
              },
              "full_name": {
                "type": "string"
              },
              "owner": {
                "type": "object",
                "properties": {
                  "login": {
                    "type": "string"
                  },
                  "id": {
                    "type": "integer"
                  },
                  "node_id": {
                    "type": "string"
                  },
                  "avatar_url": {
                    "type": "string"
                  },
                  "gravatar_id": {
                    "type": "string"
                  },
                  "url": {
                    "type": "string"
                  },
                  "html_url": {
                    "type": "string"
                  },
                  "followers_url": {
                    "type": "string"
                  },
                  "following_url": {
                    "type": "string"
                  },
                  "gists_url": {
                    "type": "string"
                  },
                  "starred_url": {
                    "type": "string"
                  },
                  "subscriptions_url": {
                    "type": "string"
                  },
                  "organizations_url": {
                    "type": "string"
                  },
                  "repos_url": {
                    "type": "string"
                  },
                  "events_url": {
                    "type": "string"
                  },
                  "received_events_url": {
                    "type": "string"
                  },
                  "type": {
                    "type": "string"
                  },
                  "site_admin": {
                    "type": "boolean"
                  }
                }
              },
              "private": {
                "type": "boolean"
              },
              "html_url": {
                "type": "string"
              },
              "description": {
                "type": "string"
              },
              "fork": {
                "type": "boolean"
              },
              "url": {
                "type": "string"
              },
              "archive_url": {
                "type": "string"
              },
              "assignees_url": {
                "type": "string"
              },
              "blobs_url": {
                "type": "string"
              },
              "branches_url": {
                "type": "string"
              },
              "collaborators_url": {
                "type": "string"
              },
              "comments_url": {
                "type": "string"
              },
              "commits_url": {
                "type": "string"
              },
              "compare_url": {
                "type": "string"
              },
              "contents_url": {
                "type": "string"
              },
              "contributors_url": {
                "type": "string"
              },
              "deployments_url": {
                "type": "string"
              },
              "downloads_url": {
                "type": "string"
              },
              "events_url": {
                "type": "string"
              },
              "forks_url": {
                "type": "string"
              },
              "git_commits_url": {
                "type": "string"
              },
              "git_refs_url": {
                "type": "string"
              },
              "git_tags_url": {
                "type": "string"
              },
              "git_url": {
                "type": "string"
              },
              "issue_comment_url": {
                "type": "string"
              },
              "issue_events_url": {
                "type": "string"
              },
              "issues_url": {
                "type": "string"
              },
              "keys_url": {
                "type": "string"
              },
              "labels_url": {
                "type": "string"
              },
              "languages_url": {
                "type": "string"
              },
              "merges_url": {
                "type": "string"
              },
              "milestones_url": {
                "type": "string"
              },
              "notifications_url": {
                "type": "string"
              },
              "pulls_url": {
                "type": "string"
              },
              "releases_url": {
                "type": "string"
              },
              "ssh_url": {
                "type": "string"
              },
              "stargazers_url": {
                "type": "string"
              },
              "statuses_url": {
                "type": "string"
              },
              "subscribers_url": {
                "type": "string"
              },
              "subscription_url": {
                "type": "string"
              },
              "tags_url": {
                "type": "string"
              },
              "teams_url": {
                "type": "string"
              },
              "trees_url": {
                "type": "string"
              },
              "clone_url": {
                "type": "string"
              },
              "mirror_url": {
                "type": "string"
              },
              "hooks_url": {
                "type": "string"
              },
              "svn_url": {
                "type": "string"
              },
              "homepage": {
                "type": "string"
              },
              "language": {
                "type": "string"
              },
              "forks_count": {
                "type": "integer"
              },
              "stargazers_count": {
                "type": "integer"
              },
              "watchers_count": {
                "type": "integer"
              },
              "size": {
                "type": "integer"
              },
              "default_branch": {
                "type": "string"
              },
              "open_issues_count": {
                "type": "integer"
              },
              "is_template": {
                "type": "boolean"
              },
              "topics": {
                "type": "array",
                "items": {
                  "type": "string"
                }
              },
              "has_issues": {
                "type": "boolean"
              },
              "has_projects": {
                "type": "boolean"
              },
              "has_wiki": {
                "type": "boolean"
              },
              "has_pages": {
                "type": "boolean"
              },
              "has_downloads": {
                "type": "boolean"
              },
              "archived": {
                "type": "boolean"
              },
              "disabled": {
                "type": "boolean"
              },
              "visibility": {
                "type": "string"
              },
              "pushed_at": {
                "type": "string"
              },
              "created_at": {
                "type": "string"
              },
              "updated_at": {
                "type": "string"
              },
              "permissions": {
                "type": "object",
                "properties": {
                  "admin": {
                    "type": "boolean"
                  },
                  "maintain": {
                    "type": "boolean"
                  },
                  "push": {
                    "type": "boolean"
                  },
                  "triage": {
                    "type": "boolean"
                  },
                  "pull": {
                    "type": "boolean"
                  }
                }
              },
              "allow_rebase_merge": {
                "type": "boolean"
              },
              "temp_clone_token": {
                "type": "string"
              },
              "allow_squash_merge": {
                "type": "boolean"
              },
              "allow_auto_merge": {
                "type": "boolean"
              },
              "delete_branch_on_merge": {
                "type": "boolean"
              },
              "allow_update_branch": {
                "type": "boolean"
              },
              "use_squash_pr_title_as_default": {
                "type": "boolean"
              },
              "squash_merge_commit_title": {
                "type": "string",
                "enum": [
                  "PR_TITLE",
                  "COMMIT_OR_PR_TITLE"
                ],
                "description": "The default value for a squash merge commit title:\n\n- `PR_TITLE` - default to the pull request's title.\n- `COMMIT_OR_PR_TITLE` - default to the commit's title (if only one commit) or the pull request's title (when more than one commit)."
              },
              "squash_merge_commit_message": {
                "type": "string",
                "enum": [
                  "PR_BODY",
                  "COMMIT_MESSAGES",
                  "BLANK"
                ],
                "description": "The default value for a squash merge commit message:\n\n- `PR_BODY` - default to the pull request's body.\n- `COMMIT_MESSAGES` - default to the branch's commit messages.\n- `BLANK` - default to a blank commit message."
              },
              "merge_commit_title": {
                "type": "string",
                "enum": [
                  "PR_TITLE",
                  "MERGE_MESSAGE"
                ],
                "description": "The default value for a merge commit title.\n\n- `PR_TITLE` - default to the pull request's title.\n- `MERGE_MESSAGE` - default to the classic title for a merge message (e.g., Merge pull request #123 from branch-name)."
              },
              "merge_commit_message": {
                "type": "string",
                "enum": [
                  "PR_BODY",
                  "PR_TITLE",
                  "BLANK"
                ],
                "description": "The default value for a merge commit message.\n\n- `PR_TITLE` - default to the pull request's title.\n- `PR_BODY` - default to the pull request's body.\n- `BLANK` - default to a blank commit message."
              },
              "allow_merge_commit": {
                "type": "boolean"
              },
              "subscribers_count": {
                "type": "integer"
              },
              "network_count": {
                "type": "integer"
              }
            }
          },
          "temp_clone_token": {
            "type": "string"
          },
          "allow_squash_merge": {
            "description": "Whether to allow squash merges for pull requests.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "allow_auto_merge": {
            "description": "Whether to allow Auto-merge to be used on pull requests.",
            "default": false,
            "type": "boolean",
            "examples": [
              false
            ]
          },
          "delete_branch_on_merge": {
            "description": "Whether to delete head branches when pull requests are merged",
            "default": false,
            "type": "boolean",
            "examples": [
              false
            ]
          },
          "allow_update_branch": {
            "description": "Whether or not a pull request head branch that is behind its base branch can always be updated even if it is not required to be up to date before merging.",
            "default": false,
            "type": "boolean",
            "examples": [
              false
            ]
          },
          "use_squash_pr_title_as_default": {
            "type": "boolean",
            "description": "Whether a squash merge commit can use the pull request title as default. **This property has been deprecated. Please use `squash_merge_commit_title` instead.",
            "default": false,
            "deprecated": true
          },
          "squash_merge_commit_title": {
            "type": "string",
            "enum": [
              "PR_TITLE",
              "COMMIT_OR_PR_TITLE"
            ],
            "description": "The default value for a squash merge commit title:\n\n- `PR_TITLE` - default to the pull request's title.\n- `COMMIT_OR_PR_TITLE` - default to the commit's title (if only one commit) or the pull request's title (when more than one commit)."
          },
          "squash_merge_commit_message": {
            "type": "string",
            "enum": [
              "PR_BODY",
              "COMMIT_MESSAGES",
              "BLANK"
            ],
            "description": "The default value for a squash merge commit message:\n\n- `PR_BODY` - default to the pull request's body.\n- `COMMIT_MESSAGES` - default to the branch's commit messages.\n- `BLANK` - default to a blank commit message."
          },
          "merge_commit_title": {
            "type": "string",
            "enum": [
              "PR_TITLE",
              "MERGE_MESSAGE"
            ],
            "description": "The default value for a merge commit title.\n\n- `PR_TITLE` - default to the pull request's title.\n- `MERGE_MESSAGE` - default to the classic title for a merge message (e.g., Merge pull request #123 from branch-name)."
          },
          "merge_commit_message": {
            "type": "string",
            "enum": [
              "PR_BODY",
              "PR_TITLE",
              "BLANK"
            ],
            "description": "The default value for a merge commit message.\n\n- `PR_TITLE` - default to the pull request's title.\n- `PR_BODY` - default to the pull request's body.\n- `BLANK` - default to a blank commit message."
          },
          "allow_merge_commit": {
            "description": "Whether to allow merge commits for pull requests.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "allow_forking": {
            "description": "Whether to allow forking this repo",
            "type": "boolean"
          },
          "web_commit_signoff_required": {
            "description": "Whether to require contributors to sign off on web-based commits",
            "default": false,
            "type": "boolean"
          },
          "subscribers_count": {
            "type": "integer"
          },
          "network_count": {
            "type": "integer"
          },
          "open_issues": {
            "type": "integer"
          },
          "watchers": {
            "type": "integer"
          },
          "master_branch": {
            "type": "string"
          },
          "starred_at": {
            "type": "string",
            "examples": [
              "\"2020-07-09T00:17:42Z\""
            ]
          },
          "anonymous_access_enabled": {
            "type": "boolean",
            "description": "Whether anonymous git access is enabled for this repository"
          }
        },
        "required": [
          "archive_url",
          "assignees_url",
          "blobs_url",
          "branches_url",
          "collaborators_url",
          "comments_url",
          "commits_url",
          "compare_url",
          "contents_url",
          "contributors_url",
          "deployments_url",
          "description",
          "downloads_url",
          "events_url",
          "fork",
          "forks_url",
          "full_name",
          "git_commits_url",
          "git_refs_url",
          "git_tags_url",
          "hooks_url",
          "html_url",
          "id",
          "node_id",
          "issue_comment_url",
          "issue_events_url",
          "issues_url",
          "keys_url",
          "labels_url",
          "languages_url",
          "merges_url",
          "milestones_url",
          "name",
          "notifications_url",
          "owner",
          "private",
          "pulls_url",
          "releases_url",
          "stargazers_url",
          "statuses_url",
          "subscribers_url",
          "subscription_url",
          "tags_url",
          "teams_url",
          "trees_url",
          "url",
          "clone_url",
          "default_branch",
          "forks",
          "forks_count",
          "git_url",
          "has_downloads",
          "has_issues",
          "has_projects",
          "has_wiki",
          "has_pages",
          "homepage",
          "language",
          "archived",
          "disabled",
          "mirror_url",
          "open_issues",
          "open_issues_count",
          "license",
          "pushed_at",
          "size",
          "ssh_url",
          "stargazers_count",
          "svn_url",
          "watchers",
          "watchers_count",
          "created_at",
          "updated_at"
        ]
      },
      "performed_via_github_app": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "GitHub app",
            "description": "GitHub apps are a new way to extend GitHub. They can be installed directly on organizations and user accounts and granted access to specific repositories. They come with granular permissions and built-in webhooks. GitHub apps are first class actors within GitHub.",
            "type": "object",
            "properties": {
              "id": {
                "description": "Unique identifier of the GitHub app",
                "type": "integer",
                "examples": [
                  37
                ]
              },
              "slug": {
                "description": "The slug name of the GitHub app",
                "type": "string",
                "examples": [
                  "probot-owners"
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDExOkludGVncmF0aW9uMQ=="
                ]
              },
              "owner": {
                "anyOf": [
                  {
                    "type": "null"
                  },
                  {
                    "title": "Simple User",
                    "description": "A GitHub user.",
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "email": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "login": {
                        "type": "string",
                        "examples": [
                          "octocat"
                        ]
                      },
                      "id": {
                        "type": "integer",
                        "examples": [
                          1
                        ]
                      },
                      "node_id": {
                        "type": "string",
                        "examples": [
                          "MDQ6VXNlcjE="
                        ]
                      },
                      "avatar_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://github.com/images/error/octocat_happy.gif"
                        ]
                      },
                      "gravatar_id": {
                        "type": [
                          "string",
                          "null"
                        ],
                        "examples": [
                          "41d064eb2195891e12d0413f63227ea7"
                        ]
                      },
                      "url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat"
                        ]
                      },
                      "html_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://github.com/octocat"
                        ]
                      },
                      "followers_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/followers"
                        ]
                      },
                      "following_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/following{/other_user}"
                        ]
                      },
                      "gists_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/gists{/gist_id}"
                        ]
                      },
                      "starred_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                        ]
                      },
                      "subscriptions_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/subscriptions"
                        ]
                      },
                      "organizations_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/orgs"
                        ]
                      },
                      "repos_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/repos"
                        ]
                      },
                      "events_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/events{/privacy}"
                        ]
                      },
                      "received_events_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/received_events"
                        ]
                      },
                      "type": {
                        "type": "string",
                        "examples": [
                          "User"
                        ]
                      },
                      "site_admin": {
                        "type": "boolean"
                      },
                      "starred_at": {
                        "type": "string",
                        "examples": [
                          "\"2020-07-09T00:17:55Z\""
                        ]
                      }
                    },
                    "required": [
                      "avatar_url",
                      "events_url",
                      "followers_url",
                      "following_url",
                      "gists_url",
                      "gravatar_id",
                      "html_url",
                      "id",
                      "node_id",
                      "login",
                      "organizations_url",
                      "received_events_url",
                      "repos_url",
                      "site_admin",
                      "starred_url",
                      "subscriptions_url",
                      "type",
                      "url"
                    ]
                  }
                ]
              },
              "name": {
                "description": "The name of the GitHub app",
                "type": "string",
                "examples": [
                  "Probot Owners"
                ]
              },
              "description": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "The description of the app."
                ]
              },
              "external_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://example.com"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/apps/super-ci"
                ]
              },
              "created_at": {
                "type": "string",
                "format": "date-time",
                "examples": [
                  "2017-07-08T16:18:44-04:00"
                ]
              },
              "updated_at": {
                "type": "string",
                "format": "date-time",
                "examples": [
                  "2017-07-08T16:18:44-04:00"
                ]
              },
              "permissions": {
                "description": "The set of permissions for the GitHub app",
                "type": "object",
                "properties": {
                  "issues": {
                    "type": "string"
                  },
                  "checks": {
                    "type": "string"
                  },
                  "metadata": {
                    "type": "string"
                  },
                  "contents": {
                    "type": "string"
                  },
                  "deployments": {
                    "type": "string"
                  }
                },
                "additionalProperties": {
                  "type": "string"
                },
                "example": {
                  "issues": "read",
                  "deployments": "write"
                }
              },
              "events": {
                "description": "The list of events for the GitHub app",
                "type": "array",
                "items": {
                  "type": "string"
                },
                "examples": [
                  "label",
                  "deployment"
                ]
              },
              "installations_count": {
                "description": "The number of installations associated with the GitHub app",
                "type": "integer",
                "examples": [
                  5
                ]
              },
              "client_id": {
                "type": "string",
                "examples": [
                  "\"Iv1.25b5d1e65ffc4022\""
                ]
              },
              "client_secret": {
                "type": "string",
                "examples": [
                  "\"1d4b2097ac622ba702d19de498f005747a8b21d3\""
                ]
              },
              "webhook_secret": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "\"6fba8f2fc8a7e8f2cca5577eddd82ca7586b3b6b\""
                ]
              },
              "pem": {
                "type": "string",
                "examples": [
                  "\"-----BEGIN RSA PRIVATE KEY-----\\nMIIEogIBAAKCAQEArYxrNYD/iT5CZVpRJu4rBKmmze3PVmT/gCo2ATUvDvZTPTey\\nxcGJ3vvrJXazKk06pN05TN29o98jrYz4cengG3YGsXPNEpKsIrEl8NhbnxapEnM9\\nJCMRe0P5JcPsfZlX6hmiT7136GRWiGOUba2X9+HKh8QJVLG5rM007TBER9/z9mWm\\nrJuNh+m5l320oBQY/Qq3A7wzdEfZw8qm/mIN0FCeoXH1L6B8xXWaAYBwhTEh6SSn\\nZHlO1Xu1JWDmAvBCi0RO5aRSKM8q9QEkvvHP4yweAtK3N8+aAbZ7ovaDhyGz8r6r\\nzhU1b8Uo0Z2ysf503WqzQgIajr7Fry7/kUwpgQIDAQABAoIBADwJp80Ko1xHPZDy\\nfcCKBDfIuPvkmSW6KumbsLMaQv1aGdHDwwTGv3t0ixSay8CGlxMRtRDyZPib6SvQ\\n6OH/lpfpbMdW2ErkksgtoIKBVrDilfrcAvrNZu7NxRNbhCSvN8q0s4ICecjbbVQh\\nnueSdlA6vGXbW58BHMq68uRbHkP+k+mM9U0mDJ1HMch67wlg5GbayVRt63H7R2+r\\nVxcna7B80J/lCEjIYZznawgiTvp3MSanTglqAYi+m1EcSsP14bJIB9vgaxS79kTu\\noiSo93leJbBvuGo8QEiUqTwMw4tDksmkLsoqNKQ1q9P7LZ9DGcujtPy4EZsamSJT\\ny8OJt0ECgYEA2lxOxJsQk2kI325JgKFjo92mQeUObIvPfSNWUIZQDTjniOI6Gv63\\nGLWVFrZcvQBWjMEQraJA9xjPbblV8PtfO87MiJGLWCHFxmPz2dzoedN+2Coxom8m\\nV95CLz8QUShuao6u/RYcvUaZEoYs5bHcTmy5sBK80JyEmafJPtCQVxMCgYEAy3ar\\nZr3yv4xRPEPMat4rseswmuMooSaK3SKub19WFI5IAtB/e7qR1Rj9JhOGcZz+OQrl\\nT78O2OFYlgOIkJPvRMrPpK5V9lslc7tz1FSh3BZMRGq5jSyD7ETSOQ0c8T2O/s7v\\nbeEPbVbDe4mwvM24XByH0GnWveVxaDl51ABD65sCgYB3ZAspUkOA5egVCh8kNpnd\\nSd6SnuQBE3ySRlT2WEnCwP9Ph6oPgn+oAfiPX4xbRqkL8q/k0BdHQ4h+zNwhk7+h\\nWtPYRAP1Xxnc/F+jGjb+DVaIaKGU18MWPg7f+FI6nampl3Q0KvfxwX0GdNhtio8T\\nTj1E+SnFwh56SRQuxSh2gwKBgHKjlIO5NtNSflsUYFM+hyQiPiqnHzddfhSG+/3o\\nm5nNaSmczJesUYreH5San7/YEy2UxAugvP7aSY2MxB+iGsiJ9WD2kZzTUlDZJ7RV\\nUzWsoqBR+eZfVJ2FUWWvy8TpSG6trh4dFxImNtKejCR1TREpSiTV3Zb1dmahK9GV\\nrK9NAoGAbBxRLoC01xfxCTgt5BDiBcFVh4fp5yYKwavJPLzHSpuDOrrI9jDn1oKN\\nonq5sDU1i391zfQvdrbX4Ova48BN+B7p63FocP/MK5tyyBoT8zQEk2+vWDOw7H/Z\\nu5dTCPxTIsoIwUw1I+7yIxqJzLPFgR2gVBwY1ra/8iAqCj+zeBw=\\n-----END RSA PRIVATE KEY-----\\n\""
                ]
              }
            },
            "required": [
              "id",
              "node_id",
              "owner",
              "name",
              "description",
              "external_url",
              "html_url",
              "created_at",
              "updated_at",
              "permissions",
              "events"
            ]
          }
        ]
      },
      "author_association": {
        "title": "author_association",
        "type": "string",
        "description": "How the author is associated with the repository.",
        "enum": [
          "COLLABORATOR",
          "CONTRIBUTOR",
          "FIRST_TIMER",
          "FIRST_TIME_CONTRIBUTOR",
          "MANNEQUIN",
          "MEMBER",
          "NONE",
          "OWNER"
        ],
        "examples": [
          "OWNER"
        ]
      },
      "reactions": {
        "title": "Reaction Rollup",
        "type": "object",
        "properties": {
          "url": {
            "type": "string",
            "format": "uri"
          },
          "total_count": {
            "type": "integer"
          },
          "+1": {
            "type": "integer"
          },
          "-1": {
            "type": "integer"
          },
          "laugh": {
            "type": "integer"
          },
          "confused": {
            "type": "integer"
          },
          "heart": {
            "type": "integer"
          },
          "hooray": {
            "type": "integer"
          },
          "eyes": {
            "type": "integer"
          },
          "rocket": {
            "type": "integer"
          }
        },
        "required": [
          "url",
          "total_count",
          "+1",
          "-1",
          "laugh",
          "confused",
          "heart",
          "hooray",
          "eyes",
          "rocket"
        ]
      }
    },
    "required": [
      "assignee",
      "closed_at",
      "comments",
      "comments_url",
      "events_url",
      "html_url",
      "id",
      "node_id",
      "labels",
      "labels_url",
      "milestone",
      "number",
      "repository_url",
      "state",
      "locked",
      "title",
      "url",
      "user",
      "author_association",
      "created_at",
      "updated_at"
    ]
  }
}
'''




# Schema for an isue comment from https://docs.github.com/en/rest/issues/comments?apiVersion=2022-11-28:

'''
{
  "title": "Issue Comment",
  "description": "Comments provide a way for people to collaborate on an issue.",
  "type": "object",
  "properties": {
    "id": {
      "description": "Unique identifier of the issue comment",
      "type": "integer",
      "examples": [
        42
      ]
    },
    "node_id": {
      "type": "string"
    },
    "url": {
      "description": "URL for the issue comment",
      "type": "string",
      "format": "uri",
      "examples": [
        "https://api.github.com/repositories/42/issues/comments/1"
      ]
    },
    "body": {
      "description": "Contents of the issue comment",
      "type": "string",
      "examples": [
        "What version of Safari were you using when you observed this bug?"
      ]
    },
    "body_text": {
      "type": "string"
    },
    "body_html": {
      "type": "string"
    },
    "html_url": {
      "type": "string",
      "format": "uri"
    },
    "user": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time",
      "examples": [
        "2011-04-14T16:00:49Z"
      ]
    },
    "updated_at": {
      "type": "string",
      "format": "date-time",
      "examples": [
        "2011-04-14T16:00:49Z"
      ]
    },
    "issue_url": {
      "type": "string",
      "format": "uri"
    },
    "author_association": {
      "title": "author_association",
      "type": "string",
      "description": "How the author is associated with the repository.",
      "enum": [
        "COLLABORATOR",
        "CONTRIBUTOR",
        "FIRST_TIMER",
        "FIRST_TIME_CONTRIBUTOR",
        "MANNEQUIN",
        "MEMBER",
        "NONE",
        "OWNER"
      ],
      "examples": [
        "OWNER"
      ]
    },
    "performed_via_github_app": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "GitHub app",
          "description": "GitHub apps are a new way to extend GitHub. They can be installed directly on organizations and user accounts and granted access to specific repositories. They come with granular permissions and built-in webhooks. GitHub apps are first class actors within GitHub.",
          "type": "object",
          "properties": {
            "id": {
              "description": "Unique identifier of the GitHub app",
              "type": "integer",
              "examples": [
                37
              ]
            },
            "slug": {
              "description": "The slug name of the GitHub app",
              "type": "string",
              "examples": [
                "probot-owners"
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDExOkludGVncmF0aW9uMQ=="
              ]
            },
            "owner": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "Simple User",
                  "description": "A GitHub user.",
                  "type": "object",
                  "properties": {
                    "name": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "email": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "login": {
                      "type": "string",
                      "examples": [
                        "octocat"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDQ6VXNlcjE="
                      ]
                    },
                    "avatar_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/images/error/octocat_happy.gif"
                      ]
                    },
                    "gravatar_id": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "41d064eb2195891e12d0413f63227ea7"
                      ]
                    },
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat"
                      ]
                    },
                    "followers_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/followers"
                      ]
                    },
                    "following_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/following{/other_user}"
                      ]
                    },
                    "gists_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/gists{/gist_id}"
                      ]
                    },
                    "starred_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                      ]
                    },
                    "subscriptions_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/subscriptions"
                      ]
                    },
                    "organizations_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/orgs"
                      ]
                    },
                    "repos_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/repos"
                      ]
                    },
                    "events_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/events{/privacy}"
                      ]
                    },
                    "received_events_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/received_events"
                      ]
                    },
                    "type": {
                      "type": "string",
                      "examples": [
                        "User"
                      ]
                    },
                    "site_admin": {
                      "type": "boolean"
                    },
                    "starred_at": {
                      "type": "string",
                      "examples": [
                        "\"2020-07-09T00:17:55Z\""
                      ]
                    }
                  },
                  "required": [
                    "avatar_url",
                    "events_url",
                    "followers_url",
                    "following_url",
                    "gists_url",
                    "gravatar_id",
                    "html_url",
                    "id",
                    "node_id",
                    "login",
                    "organizations_url",
                    "received_events_url",
                    "repos_url",
                    "site_admin",
                    "starred_url",
                    "subscriptions_url",
                    "type",
                    "url"
                  ]
                }
              ]
            },
            "name": {
              "description": "The name of the GitHub app",
              "type": "string",
              "examples": [
                "Probot Owners"
              ]
            },
            "description": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "The description of the app."
              ]
            },
            "external_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://example.com"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/apps/super-ci"
              ]
            },
            "created_at": {
              "type": "string",
              "format": "date-time",
              "examples": [
                "2017-07-08T16:18:44-04:00"
              ]
            },
            "updated_at": {
              "type": "string",
              "format": "date-time",
              "examples": [
                "2017-07-08T16:18:44-04:00"
              ]
            },
            "permissions": {
              "description": "The set of permissions for the GitHub app",
              "type": "object",
              "properties": {
                "issues": {
                  "type": "string"
                },
                "checks": {
                  "type": "string"
                },
                "metadata": {
                  "type": "string"
                },
                "contents": {
                  "type": "string"
                },
                "deployments": {
                  "type": "string"
                }
              },
              "additionalProperties": {
                "type": "string"
              },
              "example": {
                "issues": "read",
                "deployments": "write"
              }
            },
            "events": {
              "description": "The list of events for the GitHub app",
              "type": "array",
              "items": {
                "type": "string"
              },
              "examples": [
                "label",
                "deployment"
              ]
            },
            "installations_count": {
              "description": "The number of installations associated with the GitHub app",
              "type": "integer",
              "examples": [
                5
              ]
            },
            "client_id": {
              "type": "string",
              "examples": [
                "\"Iv1.25b5d1e65ffc4022\""
              ]
            },
            "client_secret": {
              "type": "string",
              "examples": [
                "\"1d4b2097ac622ba702d19de498f005747a8b21d3\""
              ]
            },
            "webhook_secret": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "\"6fba8f2fc8a7e8f2cca5577eddd82ca7586b3b6b\""
              ]
            },
            "pem": {
              "type": "string",
              "examples": [
                "\"-----BEGIN RSA PRIVATE KEY-----\\nMIIEogIBAAKCAQEArYxrNYD/iT5CZVpRJu4rBKmmze3PVmT/gCo2ATUvDvZTPTey\\nxcGJ3vvrJXazKk06pN05TN29o98jrYz4cengG3YGsXPNEpKsIrEl8NhbnxapEnM9\\nJCMRe0P5JcPsfZlX6hmiT7136GRWiGOUba2X9+HKh8QJVLG5rM007TBER9/z9mWm\\nrJuNh+m5l320oBQY/Qq3A7wzdEfZw8qm/mIN0FCeoXH1L6B8xXWaAYBwhTEh6SSn\\nZHlO1Xu1JWDmAvBCi0RO5aRSKM8q9QEkvvHP4yweAtK3N8+aAbZ7ovaDhyGz8r6r\\nzhU1b8Uo0Z2ysf503WqzQgIajr7Fry7/kUwpgQIDAQABAoIBADwJp80Ko1xHPZDy\\nfcCKBDfIuPvkmSW6KumbsLMaQv1aGdHDwwTGv3t0ixSay8CGlxMRtRDyZPib6SvQ\\n6OH/lpfpbMdW2ErkksgtoIKBVrDilfrcAvrNZu7NxRNbhCSvN8q0s4ICecjbbVQh\\nnueSdlA6vGXbW58BHMq68uRbHkP+k+mM9U0mDJ1HMch67wlg5GbayVRt63H7R2+r\\nVxcna7B80J/lCEjIYZznawgiTvp3MSanTglqAYi+m1EcSsP14bJIB9vgaxS79kTu\\noiSo93leJbBvuGo8QEiUqTwMw4tDksmkLsoqNKQ1q9P7LZ9DGcujtPy4EZsamSJT\\ny8OJt0ECgYEA2lxOxJsQk2kI325JgKFjo92mQeUObIvPfSNWUIZQDTjniOI6Gv63\\nGLWVFrZcvQBWjMEQraJA9xjPbblV8PtfO87MiJGLWCHFxmPz2dzoedN+2Coxom8m\\nV95CLz8QUShuao6u/RYcvUaZEoYs5bHcTmy5sBK80JyEmafJPtCQVxMCgYEAy3ar\\nZr3yv4xRPEPMat4rseswmuMooSaK3SKub19WFI5IAtB/e7qR1Rj9JhOGcZz+OQrl\\nT78O2OFYlgOIkJPvRMrPpK5V9lslc7tz1FSh3BZMRGq5jSyD7ETSOQ0c8T2O/s7v\\nbeEPbVbDe4mwvM24XByH0GnWveVxaDl51ABD65sCgYB3ZAspUkOA5egVCh8kNpnd\\nSd6SnuQBE3ySRlT2WEnCwP9Ph6oPgn+oAfiPX4xbRqkL8q/k0BdHQ4h+zNwhk7+h\\nWtPYRAP1Xxnc/F+jGjb+DVaIaKGU18MWPg7f+FI6nampl3Q0KvfxwX0GdNhtio8T\\nTj1E+SnFwh56SRQuxSh2gwKBgHKjlIO5NtNSflsUYFM+hyQiPiqnHzddfhSG+/3o\\nm5nNaSmczJesUYreH5San7/YEy2UxAugvP7aSY2MxB+iGsiJ9WD2kZzTUlDZJ7RV\\nUzWsoqBR+eZfVJ2FUWWvy8TpSG6trh4dFxImNtKejCR1TREpSiTV3Zb1dmahK9GV\\nrK9NAoGAbBxRLoC01xfxCTgt5BDiBcFVh4fp5yYKwavJPLzHSpuDOrrI9jDn1oKN\\nonq5sDU1i391zfQvdrbX4Ova48BN+B7p63FocP/MK5tyyBoT8zQEk2+vWDOw7H/Z\\nu5dTCPxTIsoIwUw1I+7yIxqJzLPFgR2gVBwY1ra/8iAqCj+zeBw=\\n-----END RSA PRIVATE KEY-----\\n\""
              ]
            }
          },
          "required": [
            "id",
            "node_id",
            "owner",
            "name",
            "description",
            "external_url",
            "html_url",
            "created_at",
            "updated_at",
            "permissions",
            "events"
          ]
        }
      ]
    },
    "reactions": {
      "title": "Reaction Rollup",
      "type": "object",
      "properties": {
        "url": {
          "type": "string",
          "format": "uri"
        },
        "total_count": {
          "type": "integer"
        },
        "+1": {
          "type": "integer"
        },
        "-1": {
          "type": "integer"
        },
        "laugh": {
          "type": "integer"
        },
        "confused": {
          "type": "integer"
        },
        "heart": {
          "type": "integer"
        },
        "hooray": {
          "type": "integer"
        },
        "eyes": {
          "type": "integer"
        },
        "rocket": {
          "type": "integer"
        }
      },
      "required": [
        "url",
        "total_count",
        "+1",
        "-1",
        "laugh",
        "confused",
        "heart",
        "hooray",
        "eyes",
        "rocket"
      ]
    }
  },
  "required": [
    "id",
    "node_id",
    "html_url",
    "issue_url",
    "author_association",
    "user",
    "url",
    "created_at",
    "updated_at"
  ]
}
'''


# Schema for issue comment reactions:
'''
{
  "type": "array",
  "items": {
    "title": "Reaction",
    "description": "Reactions to conversations provide a way to help people express their feelings more simply and effectively.",
    "type": "object",
    "properties": {
      "id": {
        "type": "integer",
        "examples": [
          1
        ]
      },
      "node_id": {
        "type": "string",
        "examples": [
          "MDg6UmVhY3Rpb24x"
        ]
      },
      "user": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          }
        ]
      },
      "content": {
        "description": "The reaction to use",
        "type": "string",
        "enum": [
          "+1",
          "-1",
          "laugh",
          "confused",
          "heart",
          "hooray",
          "rocket",
          "eyes"
        ],
        "examples": [
          "heart"
        ]
      },
      "created_at": {
        "type": "string",
        "format": "date-time",
        "examples": [
          "2016-05-20T20:09:31Z"
        ]
      }
    },
    "required": [
      "id",
      "node_id",
      "user",
      "content",
      "created_at"
    ]
  }
}
'''


# issue event schema:

'''
{
  "title": "Issue Event",
  "description": "Issue Event",
  "type": "object",
  "properties": {
    "id": {
      "type": "integer",
      "examples": [
        1
      ]
    },
    "node_id": {
      "type": "string",
      "examples": [
        "MDEwOklzc3VlRXZlbnQx"
      ]
    },
    "url": {
      "type": "string",
      "format": "uri",
      "examples": [
        "https://api.github.com/repos/octocat/Hello-World/issues/events/1"
      ]
    },
    "actor": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "event": {
      "type": "string",
      "examples": [
        "closed"
      ]
    },
    "commit_id": {
      "type": [
        "string",
        "null"
      ],
      "examples": [
        "6dcb09b5b57875f334f61aebed695e2e4193db5e"
      ]
    },
    "commit_url": {
      "type": [
        "string",
        "null"
      ],
      "examples": [
        "https://api.github.com/repos/octocat/Hello-World/commits/6dcb09b5b57875f334f61aebed695e2e4193db5e"
      ]
    },
    "created_at": {
      "type": "string",
      "format": "date-time",
      "examples": [
        "2011-04-14T16:00:49Z"
      ]
    },
    "issue": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Issue",
          "description": "Issues are a great way to keep track of tasks, enhancements, and bugs for your projects.",
          "type": "object",
          "properties": {
            "id": {
              "type": "integer"
            },
            "node_id": {
              "type": "string"
            },
            "url": {
              "description": "URL for the issue",
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/repositories/42/issues/1"
              ]
            },
            "repository_url": {
              "type": "string",
              "format": "uri"
            },
            "labels_url": {
              "type": "string"
            },
            "comments_url": {
              "type": "string",
              "format": "uri"
            },
            "events_url": {
              "type": "string",
              "format": "uri"
            },
            "html_url": {
              "type": "string",
              "format": "uri"
            },
            "number": {
              "description": "Number uniquely identifying the issue within its repository",
              "type": "integer",
              "examples": [
                42
              ]
            },
            "state": {
              "description": "State of the issue; either 'open' or 'closed'",
              "type": "string",
              "examples": [
                "open"
              ]
            },
            "state_reason": {
              "description": "The reason for the current state",
              "type": [
                "string",
                "null"
              ],
              "enum": [
                "completed",
                "reopened",
                "not_planned",
                null
              ],
              "examples": [
                "not_planned"
              ]
            },
            "title": {
              "description": "Title of the issue",
              "type": "string",
              "examples": [
                "Widget creation fails in Safari on OS X 10.8"
              ]
            },
            "body": {
              "description": "Contents of the issue",
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "It looks like the new widget form is broken on Safari. When I try and create the widget, Safari crashes. This is reproducible on 10.8, but not 10.9. Maybe a browser bug?"
              ]
            },
            "user": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "Simple User",
                  "description": "A GitHub user.",
                  "type": "object",
                  "properties": {
                    "name": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "email": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "login": {
                      "type": "string",
                      "examples": [
                        "octocat"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDQ6VXNlcjE="
                      ]
                    },
                    "avatar_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/images/error/octocat_happy.gif"
                      ]
                    },
                    "gravatar_id": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "41d064eb2195891e12d0413f63227ea7"
                      ]
                    },
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat"
                      ]
                    },
                    "followers_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/followers"
                      ]
                    },
                    "following_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/following{/other_user}"
                      ]
                    },
                    "gists_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/gists{/gist_id}"
                      ]
                    },
                    "starred_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                      ]
                    },
                    "subscriptions_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/subscriptions"
                      ]
                    },
                    "organizations_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/orgs"
                      ]
                    },
                    "repos_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/repos"
                      ]
                    },
                    "events_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/events{/privacy}"
                      ]
                    },
                    "received_events_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/received_events"
                      ]
                    },
                    "type": {
                      "type": "string",
                      "examples": [
                        "User"
                      ]
                    },
                    "site_admin": {
                      "type": "boolean"
                    },
                    "starred_at": {
                      "type": "string",
                      "examples": [
                        "\"2020-07-09T00:17:55Z\""
                      ]
                    }
                  },
                  "required": [
                    "avatar_url",
                    "events_url",
                    "followers_url",
                    "following_url",
                    "gists_url",
                    "gravatar_id",
                    "html_url",
                    "id",
                    "node_id",
                    "login",
                    "organizations_url",
                    "received_events_url",
                    "repos_url",
                    "site_admin",
                    "starred_url",
                    "subscriptions_url",
                    "type",
                    "url"
                  ]
                }
              ]
            },
            "labels": {
              "description": "Labels to associate with this issue; pass one or more label names to replace the set of labels on this issue; send an empty array to clear all labels from the issue; note that the labels are silently dropped for users without push access to the repository",
              "type": "array",
              "items": {
                "oneOf": [
                  {
                    "type": "string"
                  },
                  {
                    "type": "object",
                    "properties": {
                      "id": {
                        "type": "integer",
                        "format": "int64"
                      },
                      "node_id": {
                        "type": "string"
                      },
                      "url": {
                        "type": "string",
                        "format": "uri"
                      },
                      "name": {
                        "type": "string"
                      },
                      "description": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "color": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "default": {
                        "type": "boolean"
                      }
                    }
                  }
                ]
              },
              "examples": [
                "bug",
                "registration"
              ]
            },
            "assignee": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "Simple User",
                  "description": "A GitHub user.",
                  "type": "object",
                  "properties": {
                    "name": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "email": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "login": {
                      "type": "string",
                      "examples": [
                        "octocat"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDQ6VXNlcjE="
                      ]
                    },
                    "avatar_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/images/error/octocat_happy.gif"
                      ]
                    },
                    "gravatar_id": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "41d064eb2195891e12d0413f63227ea7"
                      ]
                    },
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat"
                      ]
                    },
                    "followers_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/followers"
                      ]
                    },
                    "following_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/following{/other_user}"
                      ]
                    },
                    "gists_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/gists{/gist_id}"
                      ]
                    },
                    "starred_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                      ]
                    },
                    "subscriptions_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/subscriptions"
                      ]
                    },
                    "organizations_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/orgs"
                      ]
                    },
                    "repos_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/repos"
                      ]
                    },
                    "events_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/events{/privacy}"
                      ]
                    },
                    "received_events_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/received_events"
                      ]
                    },
                    "type": {
                      "type": "string",
                      "examples": [
                        "User"
                      ]
                    },
                    "site_admin": {
                      "type": "boolean"
                    },
                    "starred_at": {
                      "type": "string",
                      "examples": [
                        "\"2020-07-09T00:17:55Z\""
                      ]
                    }
                  },
                  "required": [
                    "avatar_url",
                    "events_url",
                    "followers_url",
                    "following_url",
                    "gists_url",
                    "gravatar_id",
                    "html_url",
                    "id",
                    "node_id",
                    "login",
                    "organizations_url",
                    "received_events_url",
                    "repos_url",
                    "site_admin",
                    "starred_url",
                    "subscriptions_url",
                    "type",
                    "url"
                  ]
                }
              ]
            },
            "assignees": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "title": "Simple User",
                "description": "A GitHub user.",
                "type": "object",
                "properties": {
                  "name": {
                    "type": [
                      "string",
                      "null"
                    ]
                  },
                  "email": {
                    "type": [
                      "string",
                      "null"
                    ]
                  },
                  "login": {
                    "type": "string",
                    "examples": [
                      "octocat"
                    ]
                  },
                  "id": {
                    "type": "integer",
                    "examples": [
                      1
                    ]
                  },
                  "node_id": {
                    "type": "string",
                    "examples": [
                      "MDQ6VXNlcjE="
                    ]
                  },
                  "avatar_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://github.com/images/error/octocat_happy.gif"
                    ]
                  },
                  "gravatar_id": {
                    "type": [
                      "string",
                      "null"
                    ],
                    "examples": [
                      "41d064eb2195891e12d0413f63227ea7"
                    ]
                  },
                  "url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat"
                    ]
                  },
                  "html_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://github.com/octocat"
                    ]
                  },
                  "followers_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/followers"
                    ]
                  },
                  "following_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/following{/other_user}"
                    ]
                  },
                  "gists_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/gists{/gist_id}"
                    ]
                  },
                  "starred_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                    ]
                  },
                  "subscriptions_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/subscriptions"
                    ]
                  },
                  "organizations_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/orgs"
                    ]
                  },
                  "repos_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/repos"
                    ]
                  },
                  "events_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/events{/privacy}"
                    ]
                  },
                  "received_events_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/received_events"
                    ]
                  },
                  "type": {
                    "type": "string",
                    "examples": [
                      "User"
                    ]
                  },
                  "site_admin": {
                    "type": "boolean"
                  },
                  "starred_at": {
                    "type": "string",
                    "examples": [
                      "\"2020-07-09T00:17:55Z\""
                    ]
                  }
                },
                "required": [
                  "avatar_url",
                  "events_url",
                  "followers_url",
                  "following_url",
                  "gists_url",
                  "gravatar_id",
                  "html_url",
                  "id",
                  "node_id",
                  "login",
                  "organizations_url",
                  "received_events_url",
                  "repos_url",
                  "site_admin",
                  "starred_url",
                  "subscriptions_url",
                  "type",
                  "url"
                ]
              }
            },
            "milestone": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "Milestone",
                  "description": "A collection of related issues and pull requests.",
                  "type": "object",
                  "properties": {
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/repos/octocat/Hello-World/milestones/1"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat/Hello-World/milestones/v1.0"
                      ]
                    },
                    "labels_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/repos/octocat/Hello-World/milestones/1/labels"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1002604
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDk6TWlsZXN0b25lMTAwMjYwNA=="
                      ]
                    },
                    "number": {
                      "description": "The number of the milestone.",
                      "type": "integer",
                      "examples": [
                        42
                      ]
                    },
                    "state": {
                      "description": "The state of the milestone.",
                      "type": "string",
                      "enum": [
                        "open",
                        "closed"
                      ],
                      "default": "open",
                      "examples": [
                        "open"
                      ]
                    },
                    "title": {
                      "description": "The title of the milestone.",
                      "type": "string",
                      "examples": [
                        "v1.0"
                      ]
                    },
                    "description": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "Tracking milestone for version 1.0"
                      ]
                    },
                    "creator": {
                      "anyOf": [
                        {
                          "type": "null"
                        },
                        {
                          "title": "Simple User",
                          "description": "A GitHub user.",
                          "type": "object",
                          "properties": {
                            "name": {
                              "type": [
                                "string",
                                "null"
                              ]
                            },
                            "email": {
                              "type": [
                                "string",
                                "null"
                              ]
                            },
                            "login": {
                              "type": "string",
                              "examples": [
                                "octocat"
                              ]
                            },
                            "id": {
                              "type": "integer",
                              "examples": [
                                1
                              ]
                            },
                            "node_id": {
                              "type": "string",
                              "examples": [
                                "MDQ6VXNlcjE="
                              ]
                            },
                            "avatar_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://github.com/images/error/octocat_happy.gif"
                              ]
                            },
                            "gravatar_id": {
                              "type": [
                                "string",
                                "null"
                              ],
                              "examples": [
                                "41d064eb2195891e12d0413f63227ea7"
                              ]
                            },
                            "url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat"
                              ]
                            },
                            "html_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://github.com/octocat"
                              ]
                            },
                            "followers_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/followers"
                              ]
                            },
                            "following_url": {
                              "type": "string",
                              "examples": [
                                "https://api.github.com/users/octocat/following{/other_user}"
                              ]
                            },
                            "gists_url": {
                              "type": "string",
                              "examples": [
                                "https://api.github.com/users/octocat/gists{/gist_id}"
                              ]
                            },
                            "starred_url": {
                              "type": "string",
                              "examples": [
                                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                              ]
                            },
                            "subscriptions_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/subscriptions"
                              ]
                            },
                            "organizations_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/orgs"
                              ]
                            },
                            "repos_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/repos"
                              ]
                            },
                            "events_url": {
                              "type": "string",
                              "examples": [
                                "https://api.github.com/users/octocat/events{/privacy}"
                              ]
                            },
                            "received_events_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/received_events"
                              ]
                            },
                            "type": {
                              "type": "string",
                              "examples": [
                                "User"
                              ]
                            },
                            "site_admin": {
                              "type": "boolean"
                            },
                            "starred_at": {
                              "type": "string",
                              "examples": [
                                "\"2020-07-09T00:17:55Z\""
                              ]
                            }
                          },
                          "required": [
                            "avatar_url",
                            "events_url",
                            "followers_url",
                            "following_url",
                            "gists_url",
                            "gravatar_id",
                            "html_url",
                            "id",
                            "node_id",
                            "login",
                            "organizations_url",
                            "received_events_url",
                            "repos_url",
                            "site_admin",
                            "starred_url",
                            "subscriptions_url",
                            "type",
                            "url"
                          ]
                        }
                      ]
                    },
                    "open_issues": {
                      "type": "integer",
                      "examples": [
                        4
                      ]
                    },
                    "closed_issues": {
                      "type": "integer",
                      "examples": [
                        8
                      ]
                    },
                    "created_at": {
                      "type": "string",
                      "format": "date-time",
                      "examples": [
                        "2011-04-10T20:09:31Z"
                      ]
                    },
                    "updated_at": {
                      "type": "string",
                      "format": "date-time",
                      "examples": [
                        "2014-03-03T18:58:10Z"
                      ]
                    },
                    "closed_at": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "format": "date-time",
                      "examples": [
                        "2013-02-12T13:22:01Z"
                      ]
                    },
                    "due_on": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "format": "date-time",
                      "examples": [
                        "2012-10-09T23:39:01Z"
                      ]
                    }
                  },
                  "required": [
                    "closed_issues",
                    "creator",
                    "description",
                    "due_on",
                    "closed_at",
                    "id",
                    "node_id",
                    "labels_url",
                    "html_url",
                    "number",
                    "open_issues",
                    "state",
                    "title",
                    "url",
                    "created_at",
                    "updated_at"
                  ]
                }
              ]
            },
            "locked": {
              "type": "boolean"
            },
            "active_lock_reason": {
              "type": [
                "string",
                "null"
              ]
            },
            "comments": {
              "type": "integer"
            },
            "pull_request": {
              "type": "object",
              "properties": {
                "merged_at": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "date-time"
                },
                "diff_url": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "uri"
                },
                "html_url": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "uri"
                },
                "patch_url": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "uri"
                },
                "url": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "uri"
                }
              },
              "required": [
                "diff_url",
                "html_url",
                "patch_url",
                "url"
              ]
            },
            "closed_at": {
              "type": [
                "string",
                "null"
              ],
              "format": "date-time"
            },
            "created_at": {
              "type": "string",
              "format": "date-time"
            },
            "updated_at": {
              "type": "string",
              "format": "date-time"
            },
            "draft": {
              "type": "boolean"
            },
            "closed_by": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "Simple User",
                  "description": "A GitHub user.",
                  "type": "object",
                  "properties": {
                    "name": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "email": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "login": {
                      "type": "string",
                      "examples": [
                        "octocat"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDQ6VXNlcjE="
                      ]
                    },
                    "avatar_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/images/error/octocat_happy.gif"
                      ]
                    },
                    "gravatar_id": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "41d064eb2195891e12d0413f63227ea7"
                      ]
                    },
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat"
                      ]
                    },
                    "followers_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/followers"
                      ]
                    },
                    "following_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/following{/other_user}"
                      ]
                    },
                    "gists_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/gists{/gist_id}"
                      ]
                    },
                    "starred_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                      ]
                    },
                    "subscriptions_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/subscriptions"
                      ]
                    },
                    "organizations_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/orgs"
                      ]
                    },
                    "repos_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/repos"
                      ]
                    },
                    "events_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/events{/privacy}"
                      ]
                    },
                    "received_events_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/received_events"
                      ]
                    },
                    "type": {
                      "type": "string",
                      "examples": [
                        "User"
                      ]
                    },
                    "site_admin": {
                      "type": "boolean"
                    },
                    "starred_at": {
                      "type": "string",
                      "examples": [
                        "\"2020-07-09T00:17:55Z\""
                      ]
                    }
                  },
                  "required": [
                    "avatar_url",
                    "events_url",
                    "followers_url",
                    "following_url",
                    "gists_url",
                    "gravatar_id",
                    "html_url",
                    "id",
                    "node_id",
                    "login",
                    "organizations_url",
                    "received_events_url",
                    "repos_url",
                    "site_admin",
                    "starred_url",
                    "subscriptions_url",
                    "type",
                    "url"
                  ]
                }
              ]
            },
            "body_html": {
              "type": "string"
            },
            "body_text": {
              "type": "string"
            },
            "timeline_url": {
              "type": "string",
              "format": "uri"
            },
            "repository": {
              "title": "Repository",
              "description": "A repository on GitHub.",
              "type": "object",
              "properties": {
                "id": {
                  "description": "Unique identifier of the repository",
                  "type": "integer",
                  "examples": [
                    42
                  ]
                },
                "node_id": {
                  "type": "string",
                  "examples": [
                    "MDEwOlJlcG9zaXRvcnkxMjk2MjY5"
                  ]
                },
                "name": {
                  "description": "The name of the repository.",
                  "type": "string",
                  "examples": [
                    "Team Environment"
                  ]
                },
                "full_name": {
                  "type": "string",
                  "examples": [
                    "octocat/Hello-World"
                  ]
                },
                "license": {
                  "anyOf": [
                    {
                      "type": "null"
                    },
                    {
                      "title": "License Simple",
                      "description": "License Simple",
                      "type": "object",
                      "properties": {
                        "key": {
                          "type": "string",
                          "examples": [
                            "mit"
                          ]
                        },
                        "name": {
                          "type": "string",
                          "examples": [
                            "MIT License"
                          ]
                        },
                        "url": {
                          "type": [
                            "string",
                            "null"
                          ],
                          "format": "uri",
                          "examples": [
                            "https://api.github.com/licenses/mit"
                          ]
                        },
                        "spdx_id": {
                          "type": [
                            "string",
                            "null"
                          ],
                          "examples": [
                            "MIT"
                          ]
                        },
                        "node_id": {
                          "type": "string",
                          "examples": [
                            "MDc6TGljZW5zZW1pdA=="
                          ]
                        },
                        "html_url": {
                          "type": "string",
                          "format": "uri"
                        }
                      },
                      "required": [
                        "key",
                        "name",
                        "url",
                        "spdx_id",
                        "node_id"
                      ]
                    }
                  ]
                },
                "organization": {
                  "anyOf": [
                    {
                      "type": "null"
                    },
                    {
                      "title": "Simple User",
                      "description": "A GitHub user.",
                      "type": "object",
                      "properties": {
                        "name": {
                          "type": [
                            "string",
                            "null"
                          ]
                        },
                        "email": {
                          "type": [
                            "string",
                            "null"
                          ]
                        },
                        "login": {
                          "type": "string",
                          "examples": [
                            "octocat"
                          ]
                        },
                        "id": {
                          "type": "integer",
                          "examples": [
                            1
                          ]
                        },
                        "node_id": {
                          "type": "string",
                          "examples": [
                            "MDQ6VXNlcjE="
                          ]
                        },
                        "avatar_url": {
                          "type": "string",
                          "format": "uri",
                          "examples": [
                            "https://github.com/images/error/octocat_happy.gif"
                          ]
                        },
                        "gravatar_id": {
                          "type": [
                            "string",
                            "null"
                          ],
                          "examples": [
                            "41d064eb2195891e12d0413f63227ea7"
                          ]
                        },
                        "url": {
                          "type": "string",
                          "format": "uri",
                          "examples": [
                            "https://api.github.com/users/octocat"
                          ]
                        },
                        "html_url": {
                          "type": "string",
                          "format": "uri",
                          "examples": [
                            "https://github.com/octocat"
                          ]
                        },
                        "followers_url": {
                          "type": "string",
                          "format": "uri",
                          "examples": [
                            "https://api.github.com/users/octocat/followers"
                          ]
                        },
                        "following_url": {
                          "type": "string",
                          "examples": [
                            "https://api.github.com/users/octocat/following{/other_user}"
                          ]
                        },
                        "gists_url": {
                          "type": "string",
                          "examples": [
                            "https://api.github.com/users/octocat/gists{/gist_id}"
                          ]
                        },
                        "starred_url": {
                          "type": "string",
                          "examples": [
                            "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                          ]
                        },
                        "subscriptions_url": {
                          "type": "string",
                          "format": "uri",
                          "examples": [
                            "https://api.github.com/users/octocat/subscriptions"
                          ]
                        },
                        "organizations_url": {
                          "type": "string",
                          "format": "uri",
                          "examples": [
                            "https://api.github.com/users/octocat/orgs"
                          ]
                        },
                        "repos_url": {
                          "type": "string",
                          "format": "uri",
                          "examples": [
                            "https://api.github.com/users/octocat/repos"
                          ]
                        },
                        "events_url": {
                          "type": "string",
                          "examples": [
                            "https://api.github.com/users/octocat/events{/privacy}"
                          ]
                        },
                        "received_events_url": {
                          "type": "string",
                          "format": "uri",
                          "examples": [
                            "https://api.github.com/users/octocat/received_events"
                          ]
                        },
                        "type": {
                          "type": "string",
                          "examples": [
                            "User"
                          ]
                        },
                        "site_admin": {
                          "type": "boolean"
                        },
                        "starred_at": {
                          "type": "string",
                          "examples": [
                            "\"2020-07-09T00:17:55Z\""
                          ]
                        }
                      },
                      "required": [
                        "avatar_url",
                        "events_url",
                        "followers_url",
                        "following_url",
                        "gists_url",
                        "gravatar_id",
                        "html_url",
                        "id",
                        "node_id",
                        "login",
                        "organizations_url",
                        "received_events_url",
                        "repos_url",
                        "site_admin",
                        "starred_url",
                        "subscriptions_url",
                        "type",
                        "url"
                      ]
                    }
                  ]
                },
                "forks": {
                  "type": "integer"
                },
                "permissions": {
                  "type": "object",
                  "properties": {
                    "admin": {
                      "type": "boolean"
                    },
                    "pull": {
                      "type": "boolean"
                    },
                    "triage": {
                      "type": "boolean"
                    },
                    "push": {
                      "type": "boolean"
                    },
                    "maintain": {
                      "type": "boolean"
                    }
                  },
                  "required": [
                    "admin",
                    "pull",
                    "push"
                  ]
                },
                "owner": {
                  "title": "Simple User",
                  "description": "A GitHub user.",
                  "type": "object",
                  "properties": {
                    "name": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "email": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "login": {
                      "type": "string",
                      "examples": [
                        "octocat"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDQ6VXNlcjE="
                      ]
                    },
                    "avatar_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/images/error/octocat_happy.gif"
                      ]
                    },
                    "gravatar_id": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "41d064eb2195891e12d0413f63227ea7"
                      ]
                    },
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat"
                      ]
                    },
                    "followers_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/followers"
                      ]
                    },
                    "following_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/following{/other_user}"
                      ]
                    },
                    "gists_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/gists{/gist_id}"
                      ]
                    },
                    "starred_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                      ]
                    },
                    "subscriptions_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/subscriptions"
                      ]
                    },
                    "organizations_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/orgs"
                      ]
                    },
                    "repos_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/repos"
                      ]
                    },
                    "events_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/events{/privacy}"
                      ]
                    },
                    "received_events_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/received_events"
                      ]
                    },
                    "type": {
                      "type": "string",
                      "examples": [
                        "User"
                      ]
                    },
                    "site_admin": {
                      "type": "boolean"
                    },
                    "starred_at": {
                      "type": "string",
                      "examples": [
                        "\"2020-07-09T00:17:55Z\""
                      ]
                    }
                  },
                  "required": [
                    "avatar_url",
                    "events_url",
                    "followers_url",
                    "following_url",
                    "gists_url",
                    "gravatar_id",
                    "html_url",
                    "id",
                    "node_id",
                    "login",
                    "organizations_url",
                    "received_events_url",
                    "repos_url",
                    "site_admin",
                    "starred_url",
                    "subscriptions_url",
                    "type",
                    "url"
                  ]
                },
                "private": {
                  "description": "Whether the repository is private or public.",
                  "default": false,
                  "type": "boolean"
                },
                "html_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://github.com/octocat/Hello-World"
                  ]
                },
                "description": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "examples": [
                    "This your first repo!"
                  ]
                },
                "fork": {
                  "type": "boolean"
                },
                "url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/repos/octocat/Hello-World"
                  ]
                },
                "archive_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/{archive_format}{/ref}"
                  ]
                },
                "assignees_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/assignees{/user}"
                  ]
                },
                "blobs_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/git/blobs{/sha}"
                  ]
                },
                "branches_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/branches{/branch}"
                  ]
                },
                "collaborators_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/collaborators{/collaborator}"
                  ]
                },
                "comments_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/comments{/number}"
                  ]
                },
                "commits_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/commits{/sha}"
                  ]
                },
                "compare_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/compare/{base}...{head}"
                  ]
                },
                "contents_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/contents/{+path}"
                  ]
                },
                "contributors_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/contributors"
                  ]
                },
                "deployments_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/deployments"
                  ]
                },
                "downloads_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/downloads"
                  ]
                },
                "events_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/events"
                  ]
                },
                "forks_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/forks"
                  ]
                },
                "git_commits_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/git/commits{/sha}"
                  ]
                },
                "git_refs_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/git/refs{/sha}"
                  ]
                },
                "git_tags_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/git/tags{/sha}"
                  ]
                },
                "git_url": {
                  "type": "string",
                  "examples": [
                    "git:github.com/octocat/Hello-World.git"
                  ]
                },
                "issue_comment_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/issues/comments{/number}"
                  ]
                },
                "issue_events_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/issues/events{/number}"
                  ]
                },
                "issues_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/issues{/number}"
                  ]
                },
                "keys_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/keys{/key_id}"
                  ]
                },
                "labels_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/labels{/name}"
                  ]
                },
                "languages_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/languages"
                  ]
                },
                "merges_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/merges"
                  ]
                },
                "milestones_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/milestones{/number}"
                  ]
                },
                "notifications_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/notifications{?since,all,participating}"
                  ]
                },
                "pulls_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/pulls{/number}"
                  ]
                },
                "releases_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/releases{/id}"
                  ]
                },
                "ssh_url": {
                  "type": "string",
                  "examples": [
                    "git@github.com:octocat/Hello-World.git"
                  ]
                },
                "stargazers_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/stargazers"
                  ]
                },
                "statuses_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/statuses/{sha}"
                  ]
                },
                "subscribers_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/subscribers"
                  ]
                },
                "subscription_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/subscription"
                  ]
                },
                "tags_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/tags"
                  ]
                },
                "teams_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/teams"
                  ]
                },
                "trees_url": {
                  "type": "string",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/git/trees{/sha}"
                  ]
                },
                "clone_url": {
                  "type": "string",
                  "examples": [
                    "https://github.com/octocat/Hello-World.git"
                  ]
                },
                "mirror_url": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "uri",
                  "examples": [
                    "git:git.example.com/octocat/Hello-World"
                  ]
                },
                "hooks_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "http://api.github.com/repos/octocat/Hello-World/hooks"
                  ]
                },
                "svn_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://svn.github.com/octocat/Hello-World"
                  ]
                },
                "homepage": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "uri",
                  "examples": [
                    "https://github.com"
                  ]
                },
                "language": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "forks_count": {
                  "type": "integer",
                  "examples": [
                    9
                  ]
                },
                "stargazers_count": {
                  "type": "integer",
                  "examples": [
                    80
                  ]
                },
                "watchers_count": {
                  "type": "integer",
                  "examples": [
                    80
                  ]
                },
                "size": {
                  "description": "The size of the repository. Size is calculated hourly. When a repository is initially created, the size is 0.",
                  "type": "integer",
                  "examples": [
                    108
                  ]
                },
                "default_branch": {
                  "description": "The default branch of the repository.",
                  "type": "string",
                  "examples": [
                    "master"
                  ]
                },
                "open_issues_count": {
                  "type": "integer",
                  "examples": [
                    0
                  ]
                },
                "is_template": {
                  "description": "Whether this repository acts as a template that can be used to generate new repositories.",
                  "default": false,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "topics": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "has_issues": {
                  "description": "Whether issues are enabled.",
                  "default": true,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "has_projects": {
                  "description": "Whether projects are enabled.",
                  "default": true,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "has_wiki": {
                  "description": "Whether the wiki is enabled.",
                  "default": true,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "has_pages": {
                  "type": "boolean"
                },
                "has_downloads": {
                  "description": "Whether downloads are enabled.",
                  "default": true,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "has_discussions": {
                  "description": "Whether discussions are enabled.",
                  "default": false,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "archived": {
                  "description": "Whether the repository is archived.",
                  "default": false,
                  "type": "boolean"
                },
                "disabled": {
                  "type": "boolean",
                  "description": "Returns whether or not this repository disabled."
                },
                "visibility": {
                  "description": "The repository visibility: public, private, or internal.",
                  "default": "public",
                  "type": "string"
                },
                "pushed_at": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "date-time",
                  "examples": [
                    "2011-01-26T19:06:43Z"
                  ]
                },
                "created_at": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "date-time",
                  "examples": [
                    "2011-01-26T19:01:12Z"
                  ]
                },
                "updated_at": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "date-time",
                  "examples": [
                    "2011-01-26T19:14:43Z"
                  ]
                },
                "allow_rebase_merge": {
                  "description": "Whether to allow rebase merges for pull requests.",
                  "default": true,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "template_repository": {
                  "type": [
                    "object",
                    "null"
                  ],
                  "properties": {
                    "id": {
                      "type": "integer"
                    },
                    "node_id": {
                      "type": "string"
                    },
                    "name": {
                      "type": "string"
                    },
                    "full_name": {
                      "type": "string"
                    },
                    "owner": {
                      "type": "object",
                      "properties": {
                        "login": {
                          "type": "string"
                        },
                        "id": {
                          "type": "integer"
                        },
                        "node_id": {
                          "type": "string"
                        },
                        "avatar_url": {
                          "type": "string"
                        },
                        "gravatar_id": {
                          "type": "string"
                        },
                        "url": {
                          "type": "string"
                        },
                        "html_url": {
                          "type": "string"
                        },
                        "followers_url": {
                          "type": "string"
                        },
                        "following_url": {
                          "type": "string"
                        },
                        "gists_url": {
                          "type": "string"
                        },
                        "starred_url": {
                          "type": "string"
                        },
                        "subscriptions_url": {
                          "type": "string"
                        },
                        "organizations_url": {
                          "type": "string"
                        },
                        "repos_url": {
                          "type": "string"
                        },
                        "events_url": {
                          "type": "string"
                        },
                        "received_events_url": {
                          "type": "string"
                        },
                        "type": {
                          "type": "string"
                        },
                        "site_admin": {
                          "type": "boolean"
                        }
                      }
                    },
                    "private": {
                      "type": "boolean"
                    },
                    "html_url": {
                      "type": "string"
                    },
                    "description": {
                      "type": "string"
                    },
                    "fork": {
                      "type": "boolean"
                    },
                    "url": {
                      "type": "string"
                    },
                    "archive_url": {
                      "type": "string"
                    },
                    "assignees_url": {
                      "type": "string"
                    },
                    "blobs_url": {
                      "type": "string"
                    },
                    "branches_url": {
                      "type": "string"
                    },
                    "collaborators_url": {
                      "type": "string"
                    },
                    "comments_url": {
                      "type": "string"
                    },
                    "commits_url": {
                      "type": "string"
                    },
                    "compare_url": {
                      "type": "string"
                    },
                    "contents_url": {
                      "type": "string"
                    },
                    "contributors_url": {
                      "type": "string"
                    },
                    "deployments_url": {
                      "type": "string"
                    },
                    "downloads_url": {
                      "type": "string"
                    },
                    "events_url": {
                      "type": "string"
                    },
                    "forks_url": {
                      "type": "string"
                    },
                    "git_commits_url": {
                      "type": "string"
                    },
                    "git_refs_url": {
                      "type": "string"
                    },
                    "git_tags_url": {
                      "type": "string"
                    },
                    "git_url": {
                      "type": "string"
                    },
                    "issue_comment_url": {
                      "type": "string"
                    },
                    "issue_events_url": {
                      "type": "string"
                    },
                    "issues_url": {
                      "type": "string"
                    },
                    "keys_url": {
                      "type": "string"
                    },
                    "labels_url": {
                      "type": "string"
                    },
                    "languages_url": {
                      "type": "string"
                    },
                    "merges_url": {
                      "type": "string"
                    },
                    "milestones_url": {
                      "type": "string"
                    },
                    "notifications_url": {
                      "type": "string"
                    },
                    "pulls_url": {
                      "type": "string"
                    },
                    "releases_url": {
                      "type": "string"
                    },
                    "ssh_url": {
                      "type": "string"
                    },
                    "stargazers_url": {
                      "type": "string"
                    },
                    "statuses_url": {
                      "type": "string"
                    },
                    "subscribers_url": {
                      "type": "string"
                    },
                    "subscription_url": {
                      "type": "string"
                    },
                    "tags_url": {
                      "type": "string"
                    },
                    "teams_url": {
                      "type": "string"
                    },
                    "trees_url": {
                      "type": "string"
                    },
                    "clone_url": {
                      "type": "string"
                    },
                    "mirror_url": {
                      "type": "string"
                    },
                    "hooks_url": {
                      "type": "string"
                    },
                    "svn_url": {
                      "type": "string"
                    },
                    "homepage": {
                      "type": "string"
                    },
                    "language": {
                      "type": "string"
                    },
                    "forks_count": {
                      "type": "integer"
                    },
                    "stargazers_count": {
                      "type": "integer"
                    },
                    "watchers_count": {
                      "type": "integer"
                    },
                    "size": {
                      "type": "integer"
                    },
                    "default_branch": {
                      "type": "string"
                    },
                    "open_issues_count": {
                      "type": "integer"
                    },
                    "is_template": {
                      "type": "boolean"
                    },
                    "topics": {
                      "type": "array",
                      "items": {
                        "type": "string"
                      }
                    },
                    "has_issues": {
                      "type": "boolean"
                    },
                    "has_projects": {
                      "type": "boolean"
                    },
                    "has_wiki": {
                      "type": "boolean"
                    },
                    "has_pages": {
                      "type": "boolean"
                    },
                    "has_downloads": {
                      "type": "boolean"
                    },
                    "archived": {
                      "type": "boolean"
                    },
                    "disabled": {
                      "type": "boolean"
                    },
                    "visibility": {
                      "type": "string"
                    },
                    "pushed_at": {
                      "type": "string"
                    },
                    "created_at": {
                      "type": "string"
                    },
                    "updated_at": {
                      "type": "string"
                    },
                    "permissions": {
                      "type": "object",
                      "properties": {
                        "admin": {
                          "type": "boolean"
                        },
                        "maintain": {
                          "type": "boolean"
                        },
                        "push": {
                          "type": "boolean"
                        },
                        "triage": {
                          "type": "boolean"
                        },
                        "pull": {
                          "type": "boolean"
                        }
                      }
                    },
                    "allow_rebase_merge": {
                      "type": "boolean"
                    },
                    "temp_clone_token": {
                      "type": "string"
                    },
                    "allow_squash_merge": {
                      "type": "boolean"
                    },
                    "allow_auto_merge": {
                      "type": "boolean"
                    },
                    "delete_branch_on_merge": {
                      "type": "boolean"
                    },
                    "allow_update_branch": {
                      "type": "boolean"
                    },
                    "use_squash_pr_title_as_default": {
                      "type": "boolean"
                    },
                    "squash_merge_commit_title": {
                      "type": "string",
                      "enum": [
                        "PR_TITLE",
                        "COMMIT_OR_PR_TITLE"
                      ],
                      "description": "The default value for a squash merge commit title:\n\n- `PR_TITLE` - default to the pull request's title.\n- `COMMIT_OR_PR_TITLE` - default to the commit's title (if only one commit) or the pull request's title (when more than one commit)."
                    },
                    "squash_merge_commit_message": {
                      "type": "string",
                      "enum": [
                        "PR_BODY",
                        "COMMIT_MESSAGES",
                        "BLANK"
                      ],
                      "description": "The default value for a squash merge commit message:\n\n- `PR_BODY` - default to the pull request's body.\n- `COMMIT_MESSAGES` - default to the branch's commit messages.\n- `BLANK` - default to a blank commit message."
                    },
                    "merge_commit_title": {
                      "type": "string",
                      "enum": [
                        "PR_TITLE",
                        "MERGE_MESSAGE"
                      ],
                      "description": "The default value for a merge commit title.\n\n- `PR_TITLE` - default to the pull request's title.\n- `MERGE_MESSAGE` - default to the classic title for a merge message (e.g., Merge pull request #123 from branch-name)."
                    },
                    "merge_commit_message": {
                      "type": "string",
                      "enum": [
                        "PR_BODY",
                        "PR_TITLE",
                        "BLANK"
                      ],
                      "description": "The default value for a merge commit message.\n\n- `PR_TITLE` - default to the pull request's title.\n- `PR_BODY` - default to the pull request's body.\n- `BLANK` - default to a blank commit message."
                    },
                    "allow_merge_commit": {
                      "type": "boolean"
                    },
                    "subscribers_count": {
                      "type": "integer"
                    },
                    "network_count": {
                      "type": "integer"
                    }
                  }
                },
                "temp_clone_token": {
                  "type": "string"
                },
                "allow_squash_merge": {
                  "description": "Whether to allow squash merges for pull requests.",
                  "default": true,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "allow_auto_merge": {
                  "description": "Whether to allow Auto-merge to be used on pull requests.",
                  "default": false,
                  "type": "boolean",
                  "examples": [
                    false
                  ]
                },
                "delete_branch_on_merge": {
                  "description": "Whether to delete head branches when pull requests are merged",
                  "default": false,
                  "type": "boolean",
                  "examples": [
                    false
                  ]
                },
                "allow_update_branch": {
                  "description": "Whether or not a pull request head branch that is behind its base branch can always be updated even if it is not required to be up to date before merging.",
                  "default": false,
                  "type": "boolean",
                  "examples": [
                    false
                  ]
                },
                "use_squash_pr_title_as_default": {
                  "type": "boolean",
                  "description": "Whether a squash merge commit can use the pull request title as default. **This property has been deprecated. Please use `squash_merge_commit_title` instead.",
                  "default": false,
                  "deprecated": true
                },
                "squash_merge_commit_title": {
                  "type": "string",
                  "enum": [
                    "PR_TITLE",
                    "COMMIT_OR_PR_TITLE"
                  ],
                  "description": "The default value for a squash merge commit title:\n\n- `PR_TITLE` - default to the pull request's title.\n- `COMMIT_OR_PR_TITLE` - default to the commit's title (if only one commit) or the pull request's title (when more than one commit)."
                },
                "squash_merge_commit_message": {
                  "type": "string",
                  "enum": [
                    "PR_BODY",
                    "COMMIT_MESSAGES",
                    "BLANK"
                  ],
                  "description": "The default value for a squash merge commit message:\n\n- `PR_BODY` - default to the pull request's body.\n- `COMMIT_MESSAGES` - default to the branch's commit messages.\n- `BLANK` - default to a blank commit message."
                },
                "merge_commit_title": {
                  "type": "string",
                  "enum": [
                    "PR_TITLE",
                    "MERGE_MESSAGE"
                  ],
                  "description": "The default value for a merge commit title.\n\n- `PR_TITLE` - default to the pull request's title.\n- `MERGE_MESSAGE` - default to the classic title for a merge message (e.g., Merge pull request #123 from branch-name)."
                },
                "merge_commit_message": {
                  "type": "string",
                  "enum": [
                    "PR_BODY",
                    "PR_TITLE",
                    "BLANK"
                  ],
                  "description": "The default value for a merge commit message.\n\n- `PR_TITLE` - default to the pull request's title.\n- `PR_BODY` - default to the pull request's body.\n- `BLANK` - default to a blank commit message."
                },
                "allow_merge_commit": {
                  "description": "Whether to allow merge commits for pull requests.",
                  "default": true,
                  "type": "boolean",
                  "examples": [
                    true
                  ]
                },
                "allow_forking": {
                  "description": "Whether to allow forking this repo",
                  "type": "boolean"
                },
                "web_commit_signoff_required": {
                  "description": "Whether to require contributors to sign off on web-based commits",
                  "default": false,
                  "type": "boolean"
                },
                "subscribers_count": {
                  "type": "integer"
                },
                "network_count": {
                  "type": "integer"
                },
                "open_issues": {
                  "type": "integer"
                },
                "watchers": {
                  "type": "integer"
                },
                "master_branch": {
                  "type": "string"
                },
                "starred_at": {
                  "type": "string",
                  "examples": [
                    "\"2020-07-09T00:17:42Z\""
                  ]
                },
                "anonymous_access_enabled": {
                  "type": "boolean",
                  "description": "Whether anonymous git access is enabled for this repository"
                }
              },
              "required": [
                "archive_url",
                "assignees_url",
                "blobs_url",
                "branches_url",
                "collaborators_url",
                "comments_url",
                "commits_url",
                "compare_url",
                "contents_url",
                "contributors_url",
                "deployments_url",
                "description",
                "downloads_url",
                "events_url",
                "fork",
                "forks_url",
                "full_name",
                "git_commits_url",
                "git_refs_url",
                "git_tags_url",
                "hooks_url",
                "html_url",
                "id",
                "node_id",
                "issue_comment_url",
                "issue_events_url",
                "issues_url",
                "keys_url",
                "labels_url",
                "languages_url",
                "merges_url",
                "milestones_url",
                "name",
                "notifications_url",
                "owner",
                "private",
                "pulls_url",
                "releases_url",
                "stargazers_url",
                "statuses_url",
                "subscribers_url",
                "subscription_url",
                "tags_url",
                "teams_url",
                "trees_url",
                "url",
                "clone_url",
                "default_branch",
                "forks",
                "forks_count",
                "git_url",
                "has_downloads",
                "has_issues",
                "has_projects",
                "has_wiki",
                "has_pages",
                "homepage",
                "language",
                "archived",
                "disabled",
                "mirror_url",
                "open_issues",
                "open_issues_count",
                "license",
                "pushed_at",
                "size",
                "ssh_url",
                "stargazers_count",
                "svn_url",
                "watchers",
                "watchers_count",
                "created_at",
                "updated_at"
              ]
            },
            "performed_via_github_app": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "GitHub app",
                  "description": "GitHub apps are a new way to extend GitHub. They can be installed directly on organizations and user accounts and granted access to specific repositories. They come with granular permissions and built-in webhooks. GitHub apps are first class actors within GitHub.",
                  "type": "object",
                  "properties": {
                    "id": {
                      "description": "Unique identifier of the GitHub app",
                      "type": "integer",
                      "examples": [
                        37
                      ]
                    },
                    "slug": {
                      "description": "The slug name of the GitHub app",
                      "type": "string",
                      "examples": [
                        "probot-owners"
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDExOkludGVncmF0aW9uMQ=="
                      ]
                    },
                    "owner": {
                      "anyOf": [
                        {
                          "type": "null"
                        },
                        {
                          "title": "Simple User",
                          "description": "A GitHub user.",
                          "type": "object",
                          "properties": {
                            "name": {
                              "type": [
                                "string",
                                "null"
                              ]
                            },
                            "email": {
                              "type": [
                                "string",
                                "null"
                              ]
                            },
                            "login": {
                              "type": "string",
                              "examples": [
                                "octocat"
                              ]
                            },
                            "id": {
                              "type": "integer",
                              "examples": [
                                1
                              ]
                            },
                            "node_id": {
                              "type": "string",
                              "examples": [
                                "MDQ6VXNlcjE="
                              ]
                            },
                            "avatar_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://github.com/images/error/octocat_happy.gif"
                              ]
                            },
                            "gravatar_id": {
                              "type": [
                                "string",
                                "null"
                              ],
                              "examples": [
                                "41d064eb2195891e12d0413f63227ea7"
                              ]
                            },
                            "url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat"
                              ]
                            },
                            "html_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://github.com/octocat"
                              ]
                            },
                            "followers_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/followers"
                              ]
                            },
                            "following_url": {
                              "type": "string",
                              "examples": [
                                "https://api.github.com/users/octocat/following{/other_user}"
                              ]
                            },
                            "gists_url": {
                              "type": "string",
                              "examples": [
                                "https://api.github.com/users/octocat/gists{/gist_id}"
                              ]
                            },
                            "starred_url": {
                              "type": "string",
                              "examples": [
                                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                              ]
                            },
                            "subscriptions_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/subscriptions"
                              ]
                            },
                            "organizations_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/orgs"
                              ]
                            },
                            "repos_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/repos"
                              ]
                            },
                            "events_url": {
                              "type": "string",
                              "examples": [
                                "https://api.github.com/users/octocat/events{/privacy}"
                              ]
                            },
                            "received_events_url": {
                              "type": "string",
                              "format": "uri",
                              "examples": [
                                "https://api.github.com/users/octocat/received_events"
                              ]
                            },
                            "type": {
                              "type": "string",
                              "examples": [
                                "User"
                              ]
                            },
                            "site_admin": {
                              "type": "boolean"
                            },
                            "starred_at": {
                              "type": "string",
                              "examples": [
                                "\"2020-07-09T00:17:55Z\""
                              ]
                            }
                          },
                          "required": [
                            "avatar_url",
                            "events_url",
                            "followers_url",
                            "following_url",
                            "gists_url",
                            "gravatar_id",
                            "html_url",
                            "id",
                            "node_id",
                            "login",
                            "organizations_url",
                            "received_events_url",
                            "repos_url",
                            "site_admin",
                            "starred_url",
                            "subscriptions_url",
                            "type",
                            "url"
                          ]
                        }
                      ]
                    },
                    "name": {
                      "description": "The name of the GitHub app",
                      "type": "string",
                      "examples": [
                        "Probot Owners"
                      ]
                    },
                    "description": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "The description of the app."
                      ]
                    },
                    "external_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://example.com"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/apps/super-ci"
                      ]
                    },
                    "created_at": {
                      "type": "string",
                      "format": "date-time",
                      "examples": [
                        "2017-07-08T16:18:44-04:00"
                      ]
                    },
                    "updated_at": {
                      "type": "string",
                      "format": "date-time",
                      "examples": [
                        "2017-07-08T16:18:44-04:00"
                      ]
                    },
                    "permissions": {
                      "description": "The set of permissions for the GitHub app",
                      "type": "object",
                      "properties": {
                        "issues": {
                          "type": "string"
                        },
                        "checks": {
                          "type": "string"
                        },
                        "metadata": {
                          "type": "string"
                        },
                        "contents": {
                          "type": "string"
                        },
                        "deployments": {
                          "type": "string"
                        }
                      },
                      "additionalProperties": {
                        "type": "string"
                      },
                      "example": {
                        "issues": "read",
                        "deployments": "write"
                      }
                    },
                    "events": {
                      "description": "The list of events for the GitHub app",
                      "type": "array",
                      "items": {
                        "type": "string"
                      },
                      "examples": [
                        "label",
                        "deployment"
                      ]
                    },
                    "installations_count": {
                      "description": "The number of installations associated with the GitHub app",
                      "type": "integer",
                      "examples": [
                        5
                      ]
                    },
                    "client_id": {
                      "type": "string",
                      "examples": [
                        "\"Iv1.25b5d1e65ffc4022\""
                      ]
                    },
                    "client_secret": {
                      "type": "string",
                      "examples": [
                        "\"1d4b2097ac622ba702d19de498f005747a8b21d3\""
                      ]
                    },
                    "webhook_secret": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "\"6fba8f2fc8a7e8f2cca5577eddd82ca7586b3b6b\""
                      ]
                    },
                    "pem": {
                      "type": "string",
                      "examples": [
                        "\"-----BEGIN RSA PRIVATE KEY-----\\nMIIEogIBAAKCAQEArYxrNYD/iT5CZVpRJu4rBKmmze3PVmT/gCo2ATUvDvZTPTey\\nxcGJ3vvrJXazKk06pN05TN29o98jrYz4cengG3YGsXPNEpKsIrEl8NhbnxapEnM9\\nJCMRe0P5JcPsfZlX6hmiT7136GRWiGOUba2X9+HKh8QJVLG5rM007TBER9/z9mWm\\nrJuNh+m5l320oBQY/Qq3A7wzdEfZw8qm/mIN0FCeoXH1L6B8xXWaAYBwhTEh6SSn\\nZHlO1Xu1JWDmAvBCi0RO5aRSKM8q9QEkvvHP4yweAtK3N8+aAbZ7ovaDhyGz8r6r\\nzhU1b8Uo0Z2ysf503WqzQgIajr7Fry7/kUwpgQIDAQABAoIBADwJp80Ko1xHPZDy\\nfcCKBDfIuPvkmSW6KumbsLMaQv1aGdHDwwTGv3t0ixSay8CGlxMRtRDyZPib6SvQ\\n6OH/lpfpbMdW2ErkksgtoIKBVrDilfrcAvrNZu7NxRNbhCSvN8q0s4ICecjbbVQh\\nnueSdlA6vGXbW58BHMq68uRbHkP+k+mM9U0mDJ1HMch67wlg5GbayVRt63H7R2+r\\nVxcna7B80J/lCEjIYZznawgiTvp3MSanTglqAYi+m1EcSsP14bJIB9vgaxS79kTu\\noiSo93leJbBvuGo8QEiUqTwMw4tDksmkLsoqNKQ1q9P7LZ9DGcujtPy4EZsamSJT\\ny8OJt0ECgYEA2lxOxJsQk2kI325JgKFjo92mQeUObIvPfSNWUIZQDTjniOI6Gv63\\nGLWVFrZcvQBWjMEQraJA9xjPbblV8PtfO87MiJGLWCHFxmPz2dzoedN+2Coxom8m\\nV95CLz8QUShuao6u/RYcvUaZEoYs5bHcTmy5sBK80JyEmafJPtCQVxMCgYEAy3ar\\nZr3yv4xRPEPMat4rseswmuMooSaK3SKub19WFI5IAtB/e7qR1Rj9JhOGcZz+OQrl\\nT78O2OFYlgOIkJPvRMrPpK5V9lslc7tz1FSh3BZMRGq5jSyD7ETSOQ0c8T2O/s7v\\nbeEPbVbDe4mwvM24XByH0GnWveVxaDl51ABD65sCgYB3ZAspUkOA5egVCh8kNpnd\\nSd6SnuQBE3ySRlT2WEnCwP9Ph6oPgn+oAfiPX4xbRqkL8q/k0BdHQ4h+zNwhk7+h\\nWtPYRAP1Xxnc/F+jGjb+DVaIaKGU18MWPg7f+FI6nampl3Q0KvfxwX0GdNhtio8T\\nTj1E+SnFwh56SRQuxSh2gwKBgHKjlIO5NtNSflsUYFM+hyQiPiqnHzddfhSG+/3o\\nm5nNaSmczJesUYreH5San7/YEy2UxAugvP7aSY2MxB+iGsiJ9WD2kZzTUlDZJ7RV\\nUzWsoqBR+eZfVJ2FUWWvy8TpSG6trh4dFxImNtKejCR1TREpSiTV3Zb1dmahK9GV\\nrK9NAoGAbBxRLoC01xfxCTgt5BDiBcFVh4fp5yYKwavJPLzHSpuDOrrI9jDn1oKN\\nonq5sDU1i391zfQvdrbX4Ova48BN+B7p63FocP/MK5tyyBoT8zQEk2+vWDOw7H/Z\\nu5dTCPxTIsoIwUw1I+7yIxqJzLPFgR2gVBwY1ra/8iAqCj+zeBw=\\n-----END RSA PRIVATE KEY-----\\n\""
                      ]
                    }
                  },
                  "required": [
                    "id",
                    "node_id",
                    "owner",
                    "name",
                    "description",
                    "external_url",
                    "html_url",
                    "created_at",
                    "updated_at",
                    "permissions",
                    "events"
                  ]
                }
              ]
            },
            "author_association": {
              "title": "author_association",
              "type": "string",
              "description": "How the author is associated with the repository.",
              "enum": [
                "COLLABORATOR",
                "CONTRIBUTOR",
                "FIRST_TIMER",
                "FIRST_TIME_CONTRIBUTOR",
                "MANNEQUIN",
                "MEMBER",
                "NONE",
                "OWNER"
              ],
              "examples": [
                "OWNER"
              ]
            },
            "reactions": {
              "title": "Reaction Rollup",
              "type": "object",
              "properties": {
                "url": {
                  "type": "string",
                  "format": "uri"
                },
                "total_count": {
                  "type": "integer"
                },
                "+1": {
                  "type": "integer"
                },
                "-1": {
                  "type": "integer"
                },
                "laugh": {
                  "type": "integer"
                },
                "confused": {
                  "type": "integer"
                },
                "heart": {
                  "type": "integer"
                },
                "hooray": {
                  "type": "integer"
                },
                "eyes": {
                  "type": "integer"
                },
                "rocket": {
                  "type": "integer"
                }
              },
              "required": [
                "url",
                "total_count",
                "+1",
                "-1",
                "laugh",
                "confused",
                "heart",
                "hooray",
                "eyes",
                "rocket"
              ]
            }
          },
          "required": [
            "assignee",
            "closed_at",
            "comments",
            "comments_url",
            "events_url",
            "html_url",
            "id",
            "node_id",
            "labels",
            "labels_url",
            "milestone",
            "number",
            "repository_url",
            "state",
            "locked",
            "title",
            "url",
            "user",
            "author_association",
            "created_at",
            "updated_at"
          ]
        }
      ]
    },
    "label": {
      "title": "Issue Event Label",
      "description": "Issue Event Label",
      "type": "object",
      "properties": {
        "name": {
          "type": [
            "string",
            "null"
          ]
        },
        "color": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "name",
        "color"
      ]
    },
    "assignee": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "assigner": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "review_requester": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "requested_reviewer": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "requested_team": {
      "title": "Team",
      "description": "Groups of organization members that gives permissions on specified repositories.",
      "type": "object",
      "properties": {
        "id": {
          "type": "integer"
        },
        "node_id": {
          "type": "string"
        },
        "name": {
          "type": "string"
        },
        "slug": {
          "type": "string"
        },
        "description": {
          "type": [
            "string",
            "null"
          ]
        },
        "privacy": {
          "type": "string"
        },
        "permission": {
          "type": "string"
        },
        "permissions": {
          "type": "object",
          "properties": {
            "pull": {
              "type": "boolean"
            },
            "triage": {
              "type": "boolean"
            },
            "push": {
              "type": "boolean"
            },
            "maintain": {
              "type": "boolean"
            },
            "admin": {
              "type": "boolean"
            }
          },
          "required": [
            "pull",
            "triage",
            "push",
            "maintain",
            "admin"
          ]
        },
        "url": {
          "type": "string",
          "format": "uri"
        },
        "html_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "https://github.com/orgs/rails/teams/core"
          ]
        },
        "members_url": {
          "type": "string"
        },
        "repositories_url": {
          "type": "string",
          "format": "uri"
        },
        "parent": {
          "anyOf": [
            {
              "type": "null"
            },
            {
              "title": "Team Simple",
              "description": "Groups of organization members that gives permissions on specified repositories.",
              "type": "object",
              "properties": {
                "id": {
                  "description": "Unique identifier of the team",
                  "type": "integer",
                  "examples": [
                    1
                  ]
                },
                "node_id": {
                  "type": "string",
                  "examples": [
                    "MDQ6VGVhbTE="
                  ]
                },
                "url": {
                  "description": "URL for the team",
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/organizations/1/team/1"
                  ]
                },
                "members_url": {
                  "type": "string",
                  "examples": [
                    "https://api.github.com/organizations/1/team/1/members{/member}"
                  ]
                },
                "name": {
                  "description": "Name of the team",
                  "type": "string",
                  "examples": [
                    "Justice League"
                  ]
                },
                "description": {
                  "description": "Description of the team",
                  "type": [
                    "string",
                    "null"
                  ],
                  "examples": [
                    "A great team."
                  ]
                },
                "permission": {
                  "description": "Permission that the team will have for its repositories",
                  "type": "string",
                  "examples": [
                    "admin"
                  ]
                },
                "privacy": {
                  "description": "The level of privacy this team should have",
                  "type": "string",
                  "examples": [
                    "closed"
                  ]
                },
                "html_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://github.com/orgs/rails/teams/core"
                  ]
                },
                "repositories_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/organizations/1/team/1/repos"
                  ]
                },
                "slug": {
                  "type": "string",
                  "examples": [
                    "justice-league"
                  ]
                },
                "ldap_dn": {
                  "description": "Distinguished Name (DN) that team maps to within LDAP environment",
                  "type": "string",
                  "examples": [
                    "uid=example,ou=users,dc=github,dc=com"
                  ]
                }
              },
              "required": [
                "id",
                "node_id",
                "url",
                "members_url",
                "name",
                "description",
                "permission",
                "html_url",
                "repositories_url",
                "slug"
              ]
            }
          ]
        }
      },
      "required": [
        "id",
        "node_id",
        "url",
        "members_url",
        "name",
        "description",
        "permission",
        "html_url",
        "repositories_url",
        "slug",
        "parent"
      ]
    },
    "dismissed_review": {
      "title": "Issue Event Dismissed Review",
      "type": "object",
      "properties": {
        "state": {
          "type": "string"
        },
        "review_id": {
          "type": "integer"
        },
        "dismissal_message": {
          "type": [
            "string",
            "null"
          ]
        },
        "dismissal_commit_id": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "state",
        "review_id",
        "dismissal_message"
      ]
    },
    "milestone": {
      "title": "Issue Event Milestone",
      "description": "Issue Event Milestone",
      "type": "object",
      "properties": {
        "title": {
          "type": "string"
        }
      },
      "required": [
        "title"
      ]
    },
    "project_card": {
      "title": "Issue Event Project Card",
      "description": "Issue Event Project Card",
      "type": "object",
      "properties": {
        "url": {
          "type": "string",
          "format": "uri"
        },
        "id": {
          "type": "integer"
        },
        "project_url": {
          "type": "string",
          "format": "uri"
        },
        "project_id": {
          "type": "integer"
        },
        "column_name": {
          "type": "string"
        },
        "previous_column_name": {
          "type": "string"
        }
      },
      "required": [
        "url",
        "id",
        "project_url",
        "project_id",
        "column_name"
      ]
    },
    "rename": {
      "title": "Issue Event Rename",
      "description": "Issue Event Rename",
      "type": "object",
      "properties": {
        "from": {
          "type": "string"
        },
        "to": {
          "type": "string"
        }
      },
      "required": [
        "from",
        "to"
      ]
    },
    "author_association": {
      "title": "author_association",
      "type": "string",
      "description": "How the author is associated with the repository.",
      "enum": [
        "COLLABORATOR",
        "CONTRIBUTOR",
        "FIRST_TIMER",
        "FIRST_TIME_CONTRIBUTOR",
        "MANNEQUIN",
        "MEMBER",
        "NONE",
        "OWNER"
      ],
      "examples": [
        "OWNER"
      ]
    },
    "lock_reason": {
      "type": [
        "string",
        "null"
      ]
    },
    "performed_via_github_app": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "GitHub app",
          "description": "GitHub apps are a new way to extend GitHub. They can be installed directly on organizations and user accounts and granted access to specific repositories. They come with granular permissions and built-in webhooks. GitHub apps are first class actors within GitHub.",
          "type": "object",
          "properties": {
            "id": {
              "description": "Unique identifier of the GitHub app",
              "type": "integer",
              "examples": [
                37
              ]
            },
            "slug": {
              "description": "The slug name of the GitHub app",
              "type": "string",
              "examples": [
                "probot-owners"
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDExOkludGVncmF0aW9uMQ=="
              ]
            },
            "owner": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "Simple User",
                  "description": "A GitHub user.",
                  "type": "object",
                  "properties": {
                    "name": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "email": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "login": {
                      "type": "string",
                      "examples": [
                        "octocat"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDQ6VXNlcjE="
                      ]
                    },
                    "avatar_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/images/error/octocat_happy.gif"
                      ]
                    },
                    "gravatar_id": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "41d064eb2195891e12d0413f63227ea7"
                      ]
                    },
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat"
                      ]
                    },
                    "followers_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/followers"
                      ]
                    },
                    "following_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/following{/other_user}"
                      ]
                    },
                    "gists_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/gists{/gist_id}"
                      ]
                    },
                    "starred_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                      ]
                    },
                    "subscriptions_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/subscriptions"
                      ]
                    },
                    "organizations_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/orgs"
                      ]
                    },
                    "repos_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/repos"
                      ]
                    },
                    "events_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/events{/privacy}"
                      ]
                    },
                    "received_events_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/received_events"
                      ]
                    },
                    "type": {
                      "type": "string",
                      "examples": [
                        "User"
                      ]
                    },
                    "site_admin": {
                      "type": "boolean"
                    },
                    "starred_at": {
                      "type": "string",
                      "examples": [
                        "\"2020-07-09T00:17:55Z\""
                      ]
                    }
                  },
                  "required": [
                    "avatar_url",
                    "events_url",
                    "followers_url",
                    "following_url",
                    "gists_url",
                    "gravatar_id",
                    "html_url",
                    "id",
                    "node_id",
                    "login",
                    "organizations_url",
                    "received_events_url",
                    "repos_url",
                    "site_admin",
                    "starred_url",
                    "subscriptions_url",
                    "type",
                    "url"
                  ]
                }
              ]
            },
            "name": {
              "description": "The name of the GitHub app",
              "type": "string",
              "examples": [
                "Probot Owners"
              ]
            },
            "description": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "The description of the app."
              ]
            },
            "external_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://example.com"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/apps/super-ci"
              ]
            },
            "created_at": {
              "type": "string",
              "format": "date-time",
              "examples": [
                "2017-07-08T16:18:44-04:00"
              ]
            },
            "updated_at": {
              "type": "string",
              "format": "date-time",
              "examples": [
                "2017-07-08T16:18:44-04:00"
              ]
            },
            "permissions": {
              "description": "The set of permissions for the GitHub app",
              "type": "object",
              "properties": {
                "issues": {
                  "type": "string"
                },
                "checks": {
                  "type": "string"
                },
                "metadata": {
                  "type": "string"
                },
                "contents": {
                  "type": "string"
                },
                "deployments": {
                  "type": "string"
                }
              },
              "additionalProperties": {
                "type": "string"
              },
              "example": {
                "issues": "read",
                "deployments": "write"
              }
            },
            "events": {
              "description": "The list of events for the GitHub app",
              "type": "array",
              "items": {
                "type": "string"
              },
              "examples": [
                "label",
                "deployment"
              ]
            },
            "installations_count": {
              "description": "The number of installations associated with the GitHub app",
              "type": "integer",
              "examples": [
                5
              ]
            },
            "client_id": {
              "type": "string",
              "examples": [
                "\"Iv1.25b5d1e65ffc4022\""
              ]
            },
            "client_secret": {
              "type": "string",
              "examples": [
                "\"1d4b2097ac622ba702d19de498f005747a8b21d3\""
              ]
            },
            "webhook_secret": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "\"6fba8f2fc8a7e8f2cca5577eddd82ca7586b3b6b\""
              ]
            },
            "pem": {
              "type": "string",
              "examples": [
                "\"-----BEGIN RSA PRIVATE KEY-----\\nMIIEogIBAAKCAQEArYxrNYD/iT5CZVpRJu4rBKmmze3PVmT/gCo2ATUvDvZTPTey\\nxcGJ3vvrJXazKk06pN05TN29o98jrYz4cengG3YGsXPNEpKsIrEl8NhbnxapEnM9\\nJCMRe0P5JcPsfZlX6hmiT7136GRWiGOUba2X9+HKh8QJVLG5rM007TBER9/z9mWm\\nrJuNh+m5l320oBQY/Qq3A7wzdEfZw8qm/mIN0FCeoXH1L6B8xXWaAYBwhTEh6SSn\\nZHlO1Xu1JWDmAvBCi0RO5aRSKM8q9QEkvvHP4yweAtK3N8+aAbZ7ovaDhyGz8r6r\\nzhU1b8Uo0Z2ysf503WqzQgIajr7Fry7/kUwpgQIDAQABAoIBADwJp80Ko1xHPZDy\\nfcCKBDfIuPvkmSW6KumbsLMaQv1aGdHDwwTGv3t0ixSay8CGlxMRtRDyZPib6SvQ\\n6OH/lpfpbMdW2ErkksgtoIKBVrDilfrcAvrNZu7NxRNbhCSvN8q0s4ICecjbbVQh\\nnueSdlA6vGXbW58BHMq68uRbHkP+k+mM9U0mDJ1HMch67wlg5GbayVRt63H7R2+r\\nVxcna7B80J/lCEjIYZznawgiTvp3MSanTglqAYi+m1EcSsP14bJIB9vgaxS79kTu\\noiSo93leJbBvuGo8QEiUqTwMw4tDksmkLsoqNKQ1q9P7LZ9DGcujtPy4EZsamSJT\\ny8OJt0ECgYEA2lxOxJsQk2kI325JgKFjo92mQeUObIvPfSNWUIZQDTjniOI6Gv63\\nGLWVFrZcvQBWjMEQraJA9xjPbblV8PtfO87MiJGLWCHFxmPz2dzoedN+2Coxom8m\\nV95CLz8QUShuao6u/RYcvUaZEoYs5bHcTmy5sBK80JyEmafJPtCQVxMCgYEAy3ar\\nZr3yv4xRPEPMat4rseswmuMooSaK3SKub19WFI5IAtB/e7qR1Rj9JhOGcZz+OQrl\\nT78O2OFYlgOIkJPvRMrPpK5V9lslc7tz1FSh3BZMRGq5jSyD7ETSOQ0c8T2O/s7v\\nbeEPbVbDe4mwvM24XByH0GnWveVxaDl51ABD65sCgYB3ZAspUkOA5egVCh8kNpnd\\nSd6SnuQBE3ySRlT2WEnCwP9Ph6oPgn+oAfiPX4xbRqkL8q/k0BdHQ4h+zNwhk7+h\\nWtPYRAP1Xxnc/F+jGjb+DVaIaKGU18MWPg7f+FI6nampl3Q0KvfxwX0GdNhtio8T\\nTj1E+SnFwh56SRQuxSh2gwKBgHKjlIO5NtNSflsUYFM+hyQiPiqnHzddfhSG+/3o\\nm5nNaSmczJesUYreH5San7/YEy2UxAugvP7aSY2MxB+iGsiJ9WD2kZzTUlDZJ7RV\\nUzWsoqBR+eZfVJ2FUWWvy8TpSG6trh4dFxImNtKejCR1TREpSiTV3Zb1dmahK9GV\\nrK9NAoGAbBxRLoC01xfxCTgt5BDiBcFVh4fp5yYKwavJPLzHSpuDOrrI9jDn1oKN\\nonq5sDU1i391zfQvdrbX4Ova48BN+B7p63FocP/MK5tyyBoT8zQEk2+vWDOw7H/Z\\nu5dTCPxTIsoIwUw1I+7yIxqJzLPFgR2gVBwY1ra/8iAqCj+zeBw=\\n-----END RSA PRIVATE KEY-----\\n\""
              ]
            }
          },
          "required": [
            "id",
            "node_id",
            "owner",
            "name",
            "description",
            "external_url",
            "html_url",
            "created_at",
            "updated_at",
            "permissions",
            "events"
          ]
        }
      ]
    }
  },
  "required": [
    "id",
    "node_id",
    "url",
    "actor",
    "event",
    "commit_id",
    "commit_url",
    "created_at"
  ]
}
'''
