import datetime
import json
import pickle
import re
import sqlite3
import time

import local_db

# TODO
#   - what is sort order of listed commits?
#   - how to ensure pages don't shift -- point in time?  until/since?

dbconn = None

DB_PATH = 'commits.db'

def get_dbconn():
  global dbconn
  if dbconn is None:
    dbconn = sqlite3.connect(DB_PATH)
  return dbconn

def create_db(dbconn):
  print('Now create DB!')

  print('Create commits table')
  c = dbconn.cursor()
  c.execute('CREATE TABLE commits (sha TEXT UNIQUE PRIMARY KEY, timestamp datetime, pickle BLOB)')
  c.execute('CREATE INDEX commits_timestamp on commits (timestamp)')

  print('Create branches table')
  c = dbconn.cursor()
  c.execute('CREATE TABLE branches (name TEXT UNIQUE PRIMARY KEY, sha TEXT non null, pickle BLOB)')
  dbconn.commit()
  dbconn.commit()

def sync_branches(dbconn):

  c = dbconn.cursor()
  for branch in local_db.http_load_as_json('https://api.github.com/repos/apache/lucene/branches'):
    name = branch['name']
    sha = branch['commit']['sha']
    c.execute(f'INSERT OR REPLACE INTO branches (name, sha, pickle) VALUES (?, ?, ?)',
              (name, sha, pickle.dumps(branch)))
    print(f'branch {name} -> {sha}')
  dbconn.commit()
  return load_branch_by_name(dbconn)

def load_branch_by_name(dbconn):

  branch_by_name = {}
  c = dbconn.cursor()
  for name, sha, blob in c.execute('SELECT name, sha, pickle FROM branches'):
    branch = pickle.loads(blob)
    branch_by_name[name] = pickle.loads(blob)

  return branch_by_name

def sync_commits(dbconn, branch_name):
  now_utc = datetime.datetime.now(datetime.timezone.utc)

  branch_by_name = sync_branches(dbconn)

  if False:
    now_utc_string = now_utc.isoformat('T')

    # WTF why does Python's ISO8601 output silently get truncated by GH
    # to lose the time part, unless I munge like this!?  How many
    # ISO 8601s are there!?
    i = now_utc_string.index('.')
    now_utc_string = now_utc_string[:i] + 'Z'
  else:
    now_utc_string = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

  print(f'now={now_utc_string}')

  # now_utc_string = '2023-11-29T15:00:00Z'

  c = dbconn.cursor()

  rows = c.execute('SELECT pickle FROM commits where sha="last_until"').fetchone()
  if len(rows) == 1:
    last_until = pickle.loads(rows[0])
    if type(last_until) is str:
      if branch_name == 'main':
        since_param = f'&since={last_until}'
        print('loading commits since {last_until}')
        last_until = {'main': last_until}
      else:
        raise RuntimeError(f'must be branch "main" for initial conversion; got {branch_name}')
    elif branch_name in last_until:
      since_param = f'&since={last_until[branch_name]}'
      print('loading commits since {last_until}')
    else:
      since_param = ''
      print('first time loading commits for branch {branch_name}')
  else:
    # first time
    print('first time loading commits for branch {branch_name}')
    since_param = ''
    last_until = {}

  # print(f'here: {json.dumps(branch_by_name, indent=2)}')
  start_sha = branch_by_name[branch_name]['commit']['sha']
    
  next_page_url = f'https://api.github.com/repos/apache/lucene/commits?per_page=100&until={now_utc_string}{since_param}&sha={start_sha}'

  count = 0
  page_count = 0
  last_commit = None
  total_commit_count = c.execute('select count(*) from commits').fetchone()[0]
  while next_page_url is not None:
    page_count += 1
    rows = c.execute('select count(*) from commits').fetchall()
    print(f'\nnow load {next_page_url}\n  {rows[0][0]-1} commits')
    commits, next_page_url = local_db.http_load_as_json(next_page_url, handle_pages=False)
    for x in commits:
      if last_commit is None:
        last_commit = x
      # print(f'\nCOMMIT:\n{json.dumps(c, indent=2)}')
      # TODO: why are date under committer and author always identical?
      print(f'  {x["commit"]["committer"]["date"]}: {x["sha"]}')
      c.execute(f'INSERT OR REPLACE INTO commits (sha, timestamp, pickle) VALUES (?, ?, ?)',
                (x['sha'], x['commit']['committer']['date'], pickle.dumps(x)))
      count += 1
    new_total_commit_count = c.execute('select count(*) from commits').fetchone()[0]
    if branch_name != 'main' and new_total_commit_count == total_commit_count:
      # at some point going backwards the histories converge
      break
    total_commit_count = new_total_commit_count
    dbconn.commit()
    time.sleep(1)

  last_until[branch_name] = now_utc_string  

  c.execute('INSERT OR REPLACE INTO commits (sha, timestamp, pickle) VALUES (?, ?, ?)',
            ('last_until', datetime.datetime.now(), pickle.dumps(last_until)))

  rows = c.execute('select count(*) from commits').fetchall()
  print(f'\nloaded {page_count} pages and {count} commits')
  print(f'\n{rows[0][0] - 1} total commits in DB')

  dbconn.commit()

re_issue_number = re.compile(r'#(\d+)\b')

def parse_commits(dbconn):
  c = dbconn.cursor()
  commit_by_sha = {}
  for sha, blob in c.execute('SELECT sha, pickle FROM commits WHERE sha not in ("last_until")'):
    commit = pickle.loads(blob)
    #print(f'\n{json.dumps(commit, indent=2)}')
    commit_by_sha[sha] = (tuple([x['sha'] for x in commit['parents']]), commit)
    message = commit['commit']['message']
    issues = re_issue_number.findall(message)
    #print(f'  -> issues: {issues}')
    #if len(issues) == 0:
    #  print(f'\nno issue: {message}')

  branch_by_name = {}
  commits_by_branch = {}
  
  for name, sha, blob in c.execute('SELECT name, sha, pickle FROM branches'):
    if name not in ('main', 'branch_9x', 'branch_9_9'):
      continue
    branch = pickle.loads(blob)
    print(f'\nbranch {name}:\n{json.dumps(branch, indent=2)}')
    branch_by_name[name] = pickle.loads(blob)

    all_commits = set()
    queue = [sha]
    # no cycles -- simple search explore -- hmm, though merge commits do diverge & converge
    while len(queue) > 0:
      sha = queue.pop()
      if sha in all_commits:
        # already explored, e.g. one path of a merge commit, and now 2nd path is linking back
        # to divergence point
        continue
      all_commits.add(sha)
      #print(f'\npop: {sha}, all_commits {len(all_commits)}: {all_commits}, queue {queue}')
      commit = commit_by_sha[sha]
      # print(f'\npop: {sha}')
      # print(f'  --> parents {commit[0]}')
      # add all parent shas:
      for parent_sha in commit[0]:
        queue.append(parent_sha)
    print(f'branch {name} has {len(all_commits)} commits')
    commits_by_branch[name] = all_commits

  print(f'{len(commit_by_sha)} commits; {len(branch_by_name)} branches')


if __name__ == '__main__':
  dbconn = get_dbconn()
  #create_db(dbconn)
  #sync_branches(dbconn)
  sync_commits(dbconn, 'branch_9_9')
  parse_commits(dbconn)
  dbconn.close()
