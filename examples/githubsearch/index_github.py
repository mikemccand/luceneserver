import shutil
import traceback
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
import local_db
import datetime
from datetime import timezone
import localconstants
import util
import gitHistory
from direct_load_all_github_issues import load_full_issue
from update_from_github import refresh_latest_issues, refresh_specific_issues

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
#   - how come certbot does not auto-renew?
#   - build new lightsail box: fixes scp stupidity?
#   - GRR what firewall is sometimes blocking ssh/scp?
#   - GRR how to get status.py to run in one interpreter only?
#   - get push.py working; use git to move the UI sources
#   - make github indexing a true service like jirasearch
#   - get nrt.log monitoring working again!
#   - get monitor notifications working again
#   - don't allow multi-select on some facet fields e.g. Update / ago
#   - hmm NRT indexing broken?  #12508 failed to close nor update comments
#   - mike S: so I would like one (saved filter/s) where every issue assigned to me, I opened, I'm mentioned, etc.
#   - default to Open status
#   - commit metadata to check
#     - find changes entries that appear illegaly under more than one release
#     - missing : in issues
#     - issues/pr are closed after change is merged
#     - if backported to 9.x, milestone says so
#     - entry is in right section of changes
#     - changes.txt are consistent main and 9.9
#     - how to keep track of branch head commit?  derive 9.x and main branch commits?
#     - confirm there is a changes entry when a commit references a PR
#     - confirm PRs were backported
#   - cutover git_history.txt -> REST commits API
#   - grr PhraseQuery doesn't work (double quotes)?
#   - other_text is hidden from user -- not great!  maybe commit_messages / timeline should be true child docs?
#   - add a comment_other_text and put username/login of person who commented?
#   - hmm suggeter shoudl weight exact match highest!  suggest for 1245 (no space in the end) is missing that one in top N!
#     - grr also: space after a term should change the suggestions!  this used to work?
#   - fixup load all users logic
#   - prod
#     - get prod tools working again
#   - upgrade AL -- just build a new lightsail instance
#   - fix username situation
#      - allow search by login name and display name
#      - render hits with display name if available
#   - we could maybe preserve MD through highlighting and then conver to equivalent HTML for simple markup?
#   - hrmm do i need to get the commits and cross join myself?  commit does not show updated agains the issues it mentions
#   - does the "get an issue" API return everything the search results does?
#   - launch as beta publicly, get feedback
#   - hmm is periodic "git pull" not working in nrt mode?  only seemed to work on restart?
#   - move this to examples/githubsearch; restore jirasearch to work w/ Jira
#   - somehow tie/present display name for users login
#   - should we link/associate PRs that related to issues?
#   - re-run full gibhub -> localdb, removing these separate joined tables!
#   - split on . and # so things like RandomBytes.foobar or RandomBytes#foobar match sub-parts
#   - how to support Jira and Github?  separate servers?
#   - add property "awaiting approval to run steps" boolean field?
#   - GRRR the load_issue and load_pr APIs give more info than the list issue/pr!?
#     - and mergeability is delayed computed in the BG eventgual consistency -- must periodcially resweep the open PRs?
#   - index some cool PR attrs
#     - merged by?
#     - author_association: first time contributor, contributor, member
#     - mergeable
#     - changed_files
#     - mergeable_state
#     - comments
#     - draft
#     - merged x closed?
#     - etc.
#   - how to map Jira username to GH login?
#   - add attrs
#     - watched_by (user) / has_watchers?
#   - should i track uers's email too, and use that to resolve the commit event in timelines?
#   - can/should I also search individual commits?
#     - which committers commit other people's PRs often?
#   - how to get attachments info!?
#   - ooh can we use blame API?  https://docs.gitlab.com/ee/api/repository_files.html
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
reSVNCommitURL = re.compile(r'(http://svn\.apache\.org/viewvc.*?)$', re.MULTILINE)
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

MY_EPOCH = datetime.datetime(year=2014, month=1, day=1, tzinfo=timezone.utc)

issueToCommitPaths = gitHistory.parseLog()[1]

def prettyPrintJSON(obj):
  print(json.dumps(obj,
                   sort_keys=True,
                   indent=4, separators=(',', ': ')))

def parse_date_time(s):
  # GitHub uses ISO8601:
  return datetime.datetime.fromisoformat(s)

ICU_RULES = open('Latin-dont-break-issues.rbbi').read()

# Latn customized to keep AAAA-NNNN tokens:
ICU_TOKENIZER_KEEP_ISSUES = {
  'class': 'icu',
  'rules': [{'script': 'Latn', 'rules': ICU_RULES}]}

def create_schema(svr):

  path = '%s/index' % localconstants.ROOT_STATE_PATH

  if os.path.exists(path):
    shutil.rmtree(path)

  svr.send('createIndex', {'indexName': 'github', 'rootDir': path})
  #svr.send('settings', {'indexName': 'github', 'index.verbose': True})
  svr.send('settings', {'indexName': 'github', 'directory': 'MMapDirectory', 'nrtCachingDirectory.maxMergeSizeMB': 0.0})
  #svr.send('settings', {'indexName': 'github', 'directory': 'NIOFSDirectory', 'nrtCachingDirectory.maxMergeSizeMB': 0.0})
  svr.send('startIndex', {'indexName': 'github'})

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
  #prettyPrintJSON(svr.send('analyze', {'analyzer': analyzer, 'indexName': 'github', 'text': 'foo LUCENE-444 lucene-1123 AnalyzingInfixSuggester'}))

  fields = {'key': {'type': 'atom',
                    'sort': True,
                    'store': True},
            'old_jira_id': {'type': 'atom',
                            'store': True},
            'child_key': {'type': 'atom'},
            'issue_or_pr': {'type': 'atom',
                            'store': True,
                            'facet': 'flat'},
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
            'mentioned_users': {'type': 'text',
                         'store': True,
                         'facet': 'flat',
                         'analyzer': analyzer,
                         'multiValued': True},
            'commented_users': {'type': 'text',
                                'store': True,
                                'facet': 'flat',
                                'analyzer': analyzer,
                                'multiValued': True},
            'reviewed_users': {'type': 'text',
                               'store': True,
                               'facet': 'flat',
                               'analyzer': analyzer,
                               'multiValued': True},
            'requested_reviewers': {'type': 'text',
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
                              'store': True,
                              'facet': 'numericRange',
                              'search': True},
            'reaction_count': {'type': 'int',
                               'sort': True,
                               'store': True,
                               'facet': 'numericRange',
                               'search': True},
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
            'events': {'type': 'atom',
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
            'author_association': {'type': 'atom',
                                   'multiValued': True,
                                   'store': True,
                                   'facet': 'flat'},
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
            # TODO: hmm can i facet on child doc field?  i block join up to parent (whole issue/pr)...
            'pr_review_state': {'type': 'atom',
                                'facet': 'flat'},
            'comment_type': {'type': 'atom',
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
                     'store': True,
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
                             'search': True,
                             'highlight': True,
                             'similarity': {'class': 'BM25Similarity'},
                             'store': True,
                             'analyzer': analyzer},
            }

  result = svr.send('registerFields', {'indexName': 'github', 'fields': fields})
  print('Done register')

def removeAllGhosts():
  # Remove ghost of renamed issues:

  # we need read/write access here:
  db = local_db.get()
  
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

def all_issues():
  db = local_db.get(read_only=True)
  c = db.cursor()
  c2 = db.cursor()
  for k, v in c.execute('SELECT key, pickle FROM issues WHERE key not in ("last_update", "page_upto")'):
    try:
      yield pickle.loads(v)
    except:
      traceback.print_exc()
      print(k)
      raise

def specific_issues(issues):
  print(f'specific_issues: issues={issues}')
  db = local_db.get(read_only=True)
  c = db.cursor()
  in_list = ",".join(["\'" + str(x) + "\'" for x in issues])
  sql = f'SELECT key, pickle FROM issues where key in ({in_list})'
  print(f'sql: {sql}')
  for k, v in c.execute(sql).fetchall():
    print(f'  specific yield issues={k}')
    yield pickle.loads(v)

def issues_updated_after(min_time_stamp):
  db = local_db.get(read_only=True)
  c = db.cursor()
  c2 = db.cursor()
  for k, v in c.execute('SELECT key, pickle FROM issues where key not in ("last_update", "page_upto")'):
    issue, comments, events, reactions, timeline, full_pr, pr_comments, pr_reviews = pickle.loads(v)

    updated = parse_date_time(issue['updated_at'])

    # nocommit illegal clock comparison here!  minTimeStamp is local
    # time, updated is jira server time!
    if updated >= min_time_stamp:
      print('%s updated after %s' % (k, min_time_stamp))
      yield pickle.loads(v)

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
  elif svr.send('indexStatus', {'indexName': 'github'})['status'] != 'started':
    svr.send('startIndex', {'indexName': 'github'})

  if getFlag('-build_full_suggest'):
    build_full_suggest(svr)

  single_issue = getArg('-index_single_issue')
  if single_issue is not None:
    index_docs(svr, specific_issues([int(single_issue)]), printIssue=True, updateSuggest=True)
    sys.exit(0)
    
  if getFlag('-nrt'):
    nrt_index_forever(svr)


def nrt_index_forever(svr):
  now = datetime.datetime.now(timezone.utc)

  # First, catch up since last commit:
  print('\nNRT index: catch up since last commit')
  commitUserData = svr.send('getCommitUserData', {'indexName': 'github'})
  last_commit_time = datetime.datetime.fromisoformat(commitUserData['last_commit_time'])
  print('Last commit time %s (%s ago); now catch up' %
        (last_commit_time, now - last_commit_time))
  index_docs(svr, issues_updated_after(last_commit_time), updateSuggest=True)
  print(f'  done catching up after last commit')

  # not read only, because we write new issue/pr updates into it:
  db = local_db.get()
  c = db.cursor()

  first = False
  lastSuggestBuild = time.time()
  lastGITBuild = 0

  # Force a git refresh on startup:
  any_updates_since_git = True

  while True:

    print(f'\n{datetime.datetime.now()}: nrt index')
    issue_numbers_refreshed = refresh_latest_issues(db)
    print(f'  {len(issue_numbers_refreshed)} issues to reindex: {issue_numbers_refreshed}')

    index_start_time_sec = time.time()
    index_docs(svr, specific_issues(issue_numbers_refreshed), printIssue=True, updateSuggest=True)
    print(f'  {(time.time() - index_start_time_sec):.1f} sec to index')

    total_issue_count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]

    print(f'  loaded and indexed {len(issue_numbers_refreshed)} issues; {total_issue_count} issues in DB')

    # Check for git commits every  minute:
    if time.time() - lastGITBuild > 60 and any_updates_since_git:
      lastGITBuild = time.time()
      all_mentioned_issues, newIssueToCommitPaths, committedIssues = gitHistory.refresh()
      if len(all_mentioned_issues) > 0:
        print(f'  now force reload of mentioned issues {all_mentioned_issues}')
        refresh_specific_issues(all_mentioned_issues)

      # nocommit wtf is difference between committedIssues & all_mentioned_issues
      issues_to_index = set()
      issues_to_index.update(all_mentioned_issues)
      issues_to_index.update(committedIssues)
        
      # merge new git history into our in-memory version:
      mergeIssueCommits(issueToCommitPaths, newIssueToCommitPaths)
      print('  update from git commits...')
      index_docs(svr, specific_issues(issues_to_index), printIssue=True)
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
      # merge paths
      old.extend(ent[1:])

def build_full_suggest(svr):
  print('Build suggest...')
  t0 = time.time()
  with open('%s/suggest.txt' % localconstants.ROOT_STATE_PATH, 'wb') as suggest_file:
    all_users = {}

    for issue, comments, events, reactions, timeline, full_pr, pr_comments, pr_reviews in all_issues():
      key = issue['number']
      project = extract_project(issue)
      reporter = extract_reporter(issue)
      add_user(all_users, reporter, project, key, source='top')

      if issue['assignees'] is not None and len(issue['assignees']) > 0:
        for x in issue['assignees']:
          add_user(all_users, x, project, key, source='assignees')

      for change in timeline:
        print(f'tl: {change["event"]}')

      for change in events:
        print(f'ev: {change["event"]}')

      for change in events:
        didAttach = False
        if False:
          for item in change['items']:
            if 'field' in item and item['field'] == 'Attachment':
              didAttach = True

          if didAttach:
            #prettyPrintJSON(change)
            if 'author' in change:
              add_user(all_users, change['author'], project, key, source='attach')

      for comment in comments:
        # nocommit -- must handle "migrated from Jira" too
        add_user(all_users, comment['user'], project, key, source='comment')
        
      append_one_suggest_issue(suggest_file, issue, comments, events)

    for userDisplayName, (count, projects) in sorted(all_users.items(), key = lambda x: (-x[1][0], x[0])):
      userDisplayName = re.sub(r'\s+', ' ', userDisplayName)
      suggest_file.write(('%d\x1f%s\x1fuser %s\x1f%s\n' % \
                         (count, userDisplayName, userDisplayName, '\x1f'.join(projects))).encode('utf-8'))

    for project in all_projects:
      suggest_file.write(('1000000000\x1f%s\x1fproject %s\x1f%s\n' % (project, project, '\x1f'.join(all_projects))).encode('utf-8'))

  # Use ICU so we split on '.', e.g. Directory.fileExists
  # Don't do WDF preserveOriginal at query time else no suggestions for fileExists

  fullSuggestPath = os.path.abspath(suggest_file.name)

  # Build infix title suggest
  res = svr.send('buildSuggest',
                    {'indexName': 'github',
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

  start_time = datetime.datetime.now(timezone.utc)

  if doDelete:
    try:
      isStarted = svr.send('indexStatus', {'indexName': 'github'})['status'] == 'started'
    except:
      traceback.print_exc()
      isStarted = False
      
    if isStarted:
      print('Rollback index...')
      try:
        svr.send('rollbackIndex', {'indexName': 'github'})
      except:
        traceback.print_exc()
      print('Stop index...')
      try:
        svr.send('stopIndex', {'indexName': 'github'})
      except:
        traceback.print_exc()
    print('Delete index...')
    try:
      svr.send('deleteIndex', {'indexName': 'github'})
    except:
      traceback.print_exc()

    print('Create schema...')
    create_schema(svr)

    #svr.send('deleteAllDocuments', {'indexName': 'github'})

  index_docs(svr, all_issues(), updateSuggest=False)
  build_full_suggest(svr)

  print('Done full index')
  commit(svr, start_time)

def commit(svr, timestamp):
  t0 = time.time()
  svr.send('setCommitUserData', {'indexName': 'github',
                                 'userData': {'last_commit_time': timestamp.isoformat()}})
  svr.send('commit', {'indexName': 'github'})
  print('Commit took %.1f msec' % (1000*(time.time()-t0)))

def is_commit_user(user):
  #print(f'{user=}')
  for s in ('Commit Tag Bot', 'ASF subversion and git services', 'ASF GitHub Bot'):
    if ('name' in user and user['name'] is not None and s in user['name']) or \
       ('login' in user and user['login'] is not None and s in user['login']):
      return True
  return False

def add_user(all_users, user, project, key=None, source=None):
  # print(f'add_user: {json.dumps(user, indent=2)} {source=}')

  if 'login' in user:
    login = user['login']
    if login not in ('GitHub',):
      if login not in all_users:
        all_users[login] = [0, set()]
      l = all_users[login]
      l[0] += 1
      l[1].add(project)
  else:
    # Oh why oh why GH can't you be consistent and always include login?
    name = user['name']
      
def extract_project(issue):
  m = re_github_issue_url.match(issue['url'])
  assert m is not None
  return m.group(1)

def extract_reporter(issue):
  login = issue['user']['login']
  if issue['body'] is not None:
    # if this is a migrated Jira issue, the login will be 'asfimport', so we
    # do a bit more work to extract the original (Jira) username ... hmm, but
    # this may not be the same as the GH login?
    m = re_jira_migrated.search(issue['body'])
    if m is not None:
      m2 = re_jira_creator.match(m.group(2))
      if m2 is not None:
        name = m2.group(1)
        # already mapped to GH login during migration:
        login = m2.group(2)
      else:
        # we matched a "by so-and-so" but there was no @jira-username in there.  pretend name is jira login:
        name = m.group(2)
        login = f'jira:{name}'
        #print(f'WARNING: jira migrated issue but could not map login {name}:\n{json.dumps(issue, indent=2)}')
      return {'name': name, 'login': login}

  return {'name': local_db.get_login_to_name().get(login, None), 'login': login}

def to_utc_epoch_seconds(dt):
  '''
  Return the number of seconds since UNIX epoch (12 AM Jan 1 1970) in UTC/Zulu timezone
  '''

  # good grief this is complex, see https://docs.python.org/3/library/datetime.html#determining-if-an-object-is-aware-or-naive
  if type(dt) is datetime.time:
    is_tz_aware = dt.tzinfo is not None and dt.tzinfo.utcoffset(None) is not None
  else:
    assert type(dt) is datetime.datetime
    is_tz_aware = dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None
    
  if is_tz_aware and dt.tzinfo == timezone.utc:
    # good -- this timestampe is TZ aware and is in UTC/Zulu
    # WTF why doesn't this work?
    # return dt.timestamp()
    return int(dt.strftime('%s'))
  else:
    raise RuntimeError(f'datetime {dt} is not timezone aware or is not in UTC')

AUTHOR_ASSOCIATION_MAP = {'NONE': 'None',
                          'MEMBER': 'Member',
                          'CONTRIBUTOR': 'Contributor',
                          'FIRST_TIME_CONTRIBUTOR': 'New contributor',
                          'FIRST_TIMER': 'New GitHub user'}

def index_docs(svr, issues, printIssue=False, updateSuggest=False):

  bulk = server.ChunkedSend(svr, 'bulkUpdateDocuments', 32768)
  bulk.add('{"indexName": "github", "documents": [')

  if updateSuggest:
    suggest_file = open('%s/suggest.txt' % localconstants.ROOT_STATE_PATH, 'wb')

  now = datetime.datetime.now()

  issue_count = 0
  first = True
  
  for issue, comments, events, reactions, timeline, full_pr, pr_comments, pr_reviews in issues:

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
           'title': clean_github_markdown(number, issue['title'])}

    reaction_count = issue['reactions']['total_count']
    doc['reaction_count'] = reaction_count
    # member vs contributor vs first time

    author_association = issue['author_association']
    is_pr = 'pull_request' in issue
    if is_pr:
      doc['issue_or_pr'] = 'PR'
      #print(f'full pr is {json.dumps(full_pr, indent=2)}')
      #print(f'pr_comments is count {len(pr_comments)}\n{json.dumps(pr_comments, indent=2)}')
      #print(f'comments is {json.dumps(comments, indent=2)}')
      if full_pr is not None:
        # for some reason these sometimes differ, e.g. 'FIRST_TIMER' vs 'FIRST_TIME_CONTRIBUTOR'
        # --> ahh see https://docs.github.com/en/graphql/reference/enums#commentauthorassociation
        author_association = full_pr['author_association']

      doc['requested_reviewers'] = [x['login'] for x in full_pr['requested_reviewers']]
        
    else:
      doc['issue_or_pr'] = 'Issue'

    # multiple values for all users who interact on the issue/PR:
    author_associations = set()
    author_associations.add(author_association)
    
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

    updated = parse_date_time(issue['updated_at'])
    
    # curiously, mentions of an issue/PR will not refresh the updated_at for that issue/PR, so we do it manually here:
    for event in events:
      updated = max(updated, parse_date_time(event['created_at']))

    mentioned_users = set()
    commented_users = set()
    reviewed_users = set()
    for event in events:
      what = event['event']
      if what == 'mentioned':
        # oddly mentioned happens in both events and timelines:
        mentioned_users.add(event['actor']['login'])
    
    for event in timeline:
      what = event['event']
      if what == 'commented':
        commented_users.add(event['actor']['login'])
      elif what == 'reviewed':
        reviewed_users.add(event['user']['login']) 
      elif what == 'mentioned':
        # oddly mentioned happens in both events and timelines:
        mentioned_users.add(event['actor']['login'])
    doc['commented_users'] = list(commented_users)
    doc['reviewed_users'] = list(reviewed_users)
    doc['mentioned_users'] = list(mentioned_users)


    change_events = set()

    for change in events:
      #if event['event'] != 'closed':
        #print(f'event: {json.dumps(event, indent=2)}')
      #print(f'event: {event.actor.login} {event.event} {event.created_at} {event.label} {event.assignee} {event.assigner} {event.review_requester} {event.requested_reviewer} {event.dismissed_review} {getattr(event, "team", None)} {event.milestone} {event.rename} {event.lock_reason}')
      if change['actor'] is not None:
        # TODO: why is this sometimes (rarely: at least #12450) None?
        add_user(all_users, change['actor'], project, source='events')
      change_events.add(change['event'])

    # TODO: what really is the difference between events and timeline?

    commit_messages = []
    for change in timeline:
      if 'actor' in change:
        if change['actor'] is not None:
          # TODO: why does this happen (rarely: 12450)?
          add_user(all_users, change['actor'], project, source='timeline1')
      elif 'user' in change:
        add_user(all_users, change['user'], project, source='timeline2')
      elif 'committer' in change:
        add_user(all_users, change['committer'], project, source='timeline3')
      elif change['event'] == 'committed':
        commit_messages.append(change['message'], source='timeline4')
      else:
        # curiously, there is no user login when a commit timeline event happens:
        raise RuntimeError(f'unhandled timeline change:\n{json.dumps(change, indent=2)}')
      change_events.add(change['event'])

    doc['events'] = list(change_events)

    # who opened the issue/PR
    if issue['user'] is not None:
      #print(f'user: {issue["user"]}')
      doc['reporter'] = issue['user']['login']
      add_user(all_users, issue['user'], project, source='top user')

    # TODO: what is body vs body_text?  markup removed?  sometiems it is here, sometiems not!?

    #if'body' in issue and 'body_text' not in issue:
    #print(f'MISMATCH: {json.dumps(issue, indent=2)}')
    
    if issue['body'] is not None:
      doc['body'] = clean_github_markdown(number, issue['body'])
      #doc['body'] = issue['body_text']

    if issue['locked']:
      doc['locked'] = issue['lock_reason']

    doc['project'] = project

    # TODO this polish should be at search render time, not here?
    state = issue['state']
    print(f'raw state={state}')
    if state == 'open':
      state = 'Open'
    elif state == 'closed':
      state = 'Closed'
      
    if 'state_reason' in issue and issue['state_reason'] is not None:
      state_reason = issue['state_reason']
      if state_reason != 'completed':
        state = state_reason
        print(f'{state_reason=}')
    doc['status'] = state

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
        add_user(all_users, x, project, source='assignees')
        doc['assignee'] = x['login']
    elif issue['assignee'] is not None:
      doc['assignee'] = issue['assignee']['login']
      add_user(all_users, issue['assignee'], project, source='assignee')
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
          # Hmm I'm not sure which TZ we used when migrating from Jira -> Github!  Let's assume UTC:
          closed_dt = datetime.datetime.strptime(m.group(5).strip() + ' +0000', '%b %d %Y %z')
          doc['closed'] = to_utc_epoch_seconds(closed_dt)
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
      print(f'reporter -> {s}')
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
            add_user(all_users, change['author'], project, source='attachment')
      if len(attachments) == 0:
        attachments.add('None')
      doc['attachments'] = list(attachments)
                
    subDocs = []

    has_commits = False
    
    # doc['comment_count'] = issue['comments']

    # TODO: merged_at?

    if issue['created_at'] is not None:
      print(f'{issue["created_at"]}')
      doc['created'] = to_utc_epoch_seconds(parse_date_time(issue['created_at']))
    if issue['closed_at'] is not None:
      doc['closed'] = to_utc_epoch_seconds(parse_date_time(issue['closed_at']))

    # TODO: is there a closed_by user?

    if is_pr:
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
        doc['status'] = f' {jira_resolution}'
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

    if is_pr:
      # TODO: any fun metadata we could extract about pr_comments?
      #    - src path commented on
      #    - src diff commented on
      index_comments = [('Review code comment', pr_comments), ('Review text', pr_reviews), ('Comment', comments)]
    else:
      index_comments = [('Comment', comments)]

    total_comment_count = 0

    # for i, comment in enumerate(comments):
    for comment_cat, comment_list in index_comments:
      total_comment_count += len(comment_list)

      for comment in comment_list:
        body = comment['body']
        if len(body.strip()) == 0:
          # hmm why does this happen?  e.g. #12769
          continue
        
        # print(f'comment: {comment}')
        #if 'JIRA' in comment['body']:
        #  print(f'jira comment: {json.dumps(comment, indent=2)}')
        # nocommit must map / extra jira / github id too?
        add_user(all_users, comment['user'], project, source=f'index_comments: {comment_cat}')

        author_associations.add(comment['author_association'])

        # TODO: we don't bother loading these from GitHub now:
        if False:
          # each comment has an array of reactions:
          for reaction in list(comment_reactions[i]):
            print(f'  comment reaction: {reaction.user} {reaction.content} {reaction.created_at}')
            add_user(all_users, reaction.user, project)

        subDoc = {}
        subDoc['author'] = comment['user']['login']
        subDoc['comment_type'] = comment_cat

        if comment_cat == 'Review text' and 'state' in comment:
          # a pr review
          # approved, changes requested, etc
          subDoc['pr_review_state'] = comment['state']

        # TODO: fixme to detect migrated Jira comment, and new GitHub style commit comment
        isCommit = is_commit_user(comment['user'])
        # print(f'  comment body {body}')
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
        print(f'  comment: {subDoc["comment_body"]}')

        subDoc['comment_id'] = comment['id']
        # Disregard the bulk-update after X.Y release:
        if comment_cat == 'Review text':
          if comment['state'] != 'PENDING':
            created_at = parse_date_time(comment['submitted_at'])
        else:
          created_at = parse_date_time(comment['created_at'])

        if subDoc['comment_body'] != 'Closed after release.':
          # nocommit also rule out asfimport touching issues on migration from Jira?
          updated = max(updated, created_at)

        subDoc['created'] = int(created_at.strftime('%s'))

        # TODO: why store this twice in each child doc!?
        subDoc['key'] = key
        subDoc['child_key'] = key
        subDocs.append({'fields': subDoc})

    # sort by descending creation date (newest first):
    subDocs.sort(key=lambda x: x['fields']['created'])
    subDocs.reverse()

    if number == 12180:
      print(f'XXX\n{number} {is_pr}\n  issue: {issue}\n  events: {events}\n  comments: {comments}\n  index_comments: {index_comments=}\n  {pr_comments=}\n  {pr_reviews=}\n  {comments=}\n  {subDocs=}')

    # count both normal comments and PR code comments:
    doc['comment_count'] = total_comment_count

    doc['author_association'] = list([AUTHOR_ASSOCIATION_MAP.get(x, x) for x in author_associations])

    # we compute our own updated since GitHub's fails to notice (touch updated) when an issue/PR is referenced/mentioned
    doc['updated'] = to_utc_epoch_seconds(updated)

    # TODO: maybe lucene server needs a copy field:
    # nocommit: hmm why is this a separate field?  looks identical to "updated"?
    doc['updated_ago'] = doc['updated']

    if last_contributor is not None:
      doc['last_contributor'] = last_contributor

    if updateSuggest:
      weight = (updated-MY_EPOCH).total_seconds()
      append_one_suggest_issue(suggest_file, issue, comments, events)

    l = [(y[0], x) for x, y in list(all_users.items())]
    l.sort(reverse=True)
    print(f'all_users is {all_users}')
    doc['all_users'] = [x for y, x in l]
    doc['has_commits'] = has_commits

    other_text = []
    other_text.append(doc['key'])
    if len(doc['labels']) > 0:
      other_text.append(' '.join(doc['labels']))

    # for PRs, include the commit messages:
    other_text.extend(commit_messages)

    # NOTE: wasteful ... ideally, we could somehow make queries run "against" the parent doc?
    # TODO: why not just index child doc text field!?  block join would take care...
    other_text.extend(comments_text)
    doc['other_text'] = other_text

    # update = {'term': {'field': 'number', 'term': str(number)}, 'parent': {'fields': doc}, 'children': subDocs}
    update = {'term': {'field': 'key', 'term': str(number)}, 'parent': {'fields': doc}, 'children': subDocs}
            
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

  print(f'  {issue_count} issues indexed')

  bulk.add(']}')

  bulk.finish()

  if updateSuggest:
    suggest_file.close()
    if not first:
      res = svr.send('updateSuggest',
                      {'indexName': 'github',
                       'suggestName': 'titles_infix',
                       'source': {'localFile': os.path.abspath(suggest_file.name)}})
      print('updateSuggest: %s' % res)

def append_one_suggest_issue(suggest_file, issue, comments, events):
  project = extract_project(issue)
  number = issue['number']
  text = f'#{number}'
  if 'pull_request' in issue:
    text += ' PR'
  text += ':'
  text += clean_github_markdown(issue['number'], issue['title'])

  updated = parse_date_time(issue['created_at'])
  for comment in comments:
    if comment['body'] != 'Closed after release.':
      updated = max(updated, parse_date_time(comment['created_at']))

  updated = max(updated, parse_date_time(issue['updated_at']))

  # curiously, mentions of an issue/PR will not refresh the updated_at for that issue/PR, so we do it manually here:
  for event in events:
    updated = max(updated, parse_date_time(event['created_at']))

  # Index project as a context, so we can suggest within project:
  weight = int((updated-MY_EPOCH).total_seconds())
  suggest_file.write(f'{weight}\x1f{text}\x1f{number}\x1f{project}\n'.encode('utf-8'))

  
def map_user_name(user):
  user = user.group(1)
  mapped = local_db.get_login_to_name().get(user[2:-1])
  if mapped is not None:
    #print('map %s to %s' % (user, mapped))
    return '[%s]' % mapped
  else:
    return user

# replace hyperlink with just its link text
re_github_md_link = re.compile(r'\[(.*?)\]\((.*?)\)')

# back-quote escaped code chunk:
re_github_code_link = re.compile(r'\u0060(.*?)\u0060')

re_header1 = re.compile('#([^#]+)\n')
re_header2 = re.compile('##([^#]+)\n')
re_header3 = re.compile('###([^#]+)\n')

def clean_github_markdown(key, s):
  # TODO: fixme!!
  s0 = re_github_md_link.sub(r'\1', s)
  s0 = re_github_code_link.sub(r'\1', s0)
  s0 = re_header1.sub(r'\1', s0)
  s0 = re_header2.sub(r'\1', s0)
  s0 = re_header3.sub(r'\1', s0)

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
    -nrt  Run forever, indexing github issues as they are changed
    -delete  If -reindex is specified, this will first delete the entire index, instead of updating it in place
    -build_full_suggest  Rebuild the infix suggester
    [-help] prints this message
''')
    sys.exit(0)
    
  main()
