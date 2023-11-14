import sys
import pickle
import json
import datetime
import time
import local_db

from localconstants import DB_PATH, GITHUB_API_TOKEN
from direct_load_all_github_issues import load_full_issue
from local_db import http_load_as_json

def main():
  # not read only, because we write new issue/pr updates into it:
  db = local_db.get()

  # nocommit
  login_to_name = local_db.get_login_to_name()
  print(f'{len(login_to_name)} unique users')
  
  c = db.cursor()

  total_issue_count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]
  print(f'{total_issue_count} issues in DB')

  if False:
      # nocommit one time user table update:
      for k, v in c.execute('SELECT key, pickle FROM issues WHERE key not in ("last_update", "page_upto")'):
        issue, comments, events, reactions, timeline = pickle.loads(v)
        local_db.maybe_load_user(c, issue['user']['login'])
        for comment in comments:
            local_db.maybe_load_user(c, comment['user']['login'])
        for change in events:
            local_db.maybe_load_user(c, change['actor']['login'])
        for change in timeline:
            # change['event'] can be reviewed, committed
            if 'actor' in change:
                local_db.maybe_load_user(c, change['actor']['login'])
            elif 'user' in change:
                local_db.maybe_load_user(c, change['user']['login'])
            else:
                raise RuntimeError(f'unhandled timeline change:\n{json.dumps(change, indent=2)}')

  if False:
      # nocommit
      c = db.cursor()
      c.execute('CREATE TABLE users (login TEXT UNIQUE PRIMARY KEY, pickle BLOB)')
      db.commit()

  if False:
      # nocommit
      c = db.cursor()
      c.execute('CREATE TABLE full_issue (key TEXT UNIQUE PRIMARY KEY, pickle BLOB)')
      db.commit()

  if False:
      # nocommit
      if False:
        c = db.cursor()
        c.execute('CREATE TABLE pr_comments (key TEXT UNIQUE PRIMARY KEY, pickle BLOB)')
        db.commit()
      # nocommit -- one time to catch up on all past loaded PRs; newly refreshed PRs will now do this going forwards
      load_all_pr_comments(db)

  if True:
      # nocommit
      if False:
        c = db.cursor()
        c.execute('CREATE TABLE pr_reviews (key TEXT UNIQUE PRIMARY KEY, pickle BLOB)')
        db.commit()
      # nocommit -- one time to catch up on all past loaded PRs; newly refreshed PRs will now do this going forwards
      load_all_pr_reviews(db)

  if False:
    # nocommit -- one time to catch up on all past loaded PRs; newly refreshed PRs will now do this going forwards
    load_all_full_prs(db)

  c = db.cursor()
  total_issue_count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]
  print(f'{total_issue_count} issues in DB')
  while True:
    refresh_latest_issues(db)
    time.sleep(5.0)

def load_all_full_prs(db):
    # the search API only returns a subset of the fields in a PR, so we must separately individually
    # load the full pr (issues seem to be complete coming from search!?):
    c = db.cursor()
    c.execute('SELECT key, pickle FROM issues WHERE key not in ("last_update", "page_upto")')
    for number, v in c.fetchall():
        issue, comments, events, reactions, timeline = pickle.loads(v)
        print(f'{number}')
        if False and str(number) == '12691':
            print('\n12691: issue')
            print(json.dumps(issue, indent=2))
            print('\n12691: timeline')
            print(json.dumps(timeline, indent=2))
            print('\n12691: events')
            print(json.dumps(events, indent=2))
            row = c.execute('SELECT pickle FROM full_issue WHERE key=?', (str(number),)).fetchone()
            print('\n12691: full PR')
            #full_pr = load_one_full_pr(db, c, number)
            full_pr = pickle.loads(row[0])
            print(json.dumps(full_pr, indent=2))
        #if 'pull_request' in issue and issue.get('state') == 'open':
        if 'pull_request' in issue:
            print('  is pull request!')
            rows = list(c.execute('SELECT pickle FROM full_issue WHERE key=?', (str(number),)).fetchall())
            if len(rows) == 0:
                print(f'  pr not yet fully loaded!  load now...')
                load_one_full_pr(db, c, number)

def load_one_full_pr(db, c, number):
    print(f'  load full pr {number}')
    full_pr = local_db.http_load_as_json(f'https://api.github.com/repos/apache/lucene/pulls/{number}')
    #print(json.dumps(full_pr))
    s = pickle.dumps(full_pr)
    #print(s)
    #print(pickle.loads(s))
    c.execute('REPLACE INTO full_issue (key, pickle) VALUES (?, ?)',
              (str(number), s))
    db.commit()
    return full_pr

def load_all_pr_comments(db):
    # the search API only returns a subset of the fields in a PR, so we must separately individually
    # load the full pr comments (issues seem to be complete coming from search!?):
    c = db.cursor()
    c.execute('SELECT key, pickle FROM issues WHERE key not in ("last_update", "page_upto")')
    for number, v in c.fetchall():
        issue, comments, events, reactions, timeline = pickle.loads(v)
        print(f'{number}')
        if 'pull_request' in issue:
            print('  is pull request!')
            rows = list(c.execute('SELECT pickle FROM pr_comments WHERE key=?', (str(number),)).fetchall())
            if len(rows) == 0:
                print(f'  pr comments not yet fully loaded!  load now...')
                load_pr_comments(db, c, number)

def load_pr_comments(db, c, number):
  print(f'  load full pr comments {number}')
  all_pr_comments = local_db.http_load_as_json(f'https://api.github.com/repos/apache/lucene/pulls/{number}/comments')
  s = pickle.dumps(all_pr_comments)
  #print(s)
  #print(pickle.loads(s))
  c.execute('REPLACE INTO pr_comments (key, pickle) VALUES (?, ?)',
            (str(number), s))
  db.commit()
  print(f'    got: {all_pr_comments}')
  return all_pr_comments
        
def load_all_pr_reviews(db):
    # the search API only returns a subset of the fields in a PR, so we must separately individually
    # load the full pr comments (issues seem to be complete coming from search!?):
    c = db.cursor()
    c.execute('SELECT key, pickle FROM issues WHERE key not in ("last_update", "page_upto")')
    for number, v in c.fetchall():
        issue, comments, events, reactions, timeline = pickle.loads(v)
        if 'pull_request' in issue:
          print(f'{number} is PR')
          rows = list(c.execute('SELECT pickle FROM pr_reviews WHERE key=?', (str(number),)).fetchall())
          if len(rows) == 0:
              print(f'  pr reviews not yet fully loaded!  load now...')
              load_pr_reviews(db, c, number)

def load_pr_reviews(db, c, number):
  print(f'  load full pr reviews {number}')
  all_pr_reviews = local_db.http_load_as_json(f'https://api.github.com/repos/apache/lucene/pulls/{number}/reviews')
  s = pickle.dumps(all_pr_reviews)
  c.execute('REPLACE INTO pr_reviews (key, pickle) VALUES (?, ?)',
            (str(number), s))
  db.commit()
  print(f'    got: {all_pr_reviews}')
  return all_pr_reviews

def load_and_store_full_issue(issue, db, c):

  number = issue['number']

  now = datetime.datetime.now()
  comments, events, reactions, timeline = load_full_issue(issue)

  local_db.maybe_load_user(c, issue['user']['login'])
  for comment in comments:
      local_db.maybe_load_user(c, comment['user']['login'])
  # nocommit what about events/timeline users?

  c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)',
            (str(number), pickle.dumps((issue, comments, events, reactions, timeline))))

  #print(f'ISSUE={json.dumps(issue, indent=2)}')
  #print(f'COMMENTS={json.dumps(comments, indent=2)}')

  if 'pull_request' in issue:
    # nocommit move the other table inserts here too, instead of "down low"
    load_one_full_pr(db, c, number)
    load_pr_comments(db, c, number)
    load_pr_reviews(db, c, number)
        
def refresh_latest_issues(db):
  now = datetime.datetime.utcnow()

  c = db.cursor()

  # when did we last pull updates from GitHub?
  rows = c.execute('SELECT pickle FROM issues WHERE key="last_update"').fetchall()
  if len(rows) == 1:
    last_update_utc = pickle.loads(rows[0][0])
  else:
    raise RuntimeError(f'should be one row with "last_update" key but found or too many rows matched {len(rows)}')
  if last_update_utc is None:
    print('WARNING: no last_update -- crawling all updates from two weeks ago until now')
    last_update_utc = now - datetime.timedelta(days=14)

  first = False

  nrt_started_utc = datetime.datetime.utcnow()

  since_utc = last_update_utc - datetime.timedelta(seconds=10)

  print(f'\n{datetime.datetime.now()}: now refresh latest updates (GitHub ratelimit_remaining={local_db.ratelimit_remaining})')
  print(f'  use since={since_utc} ({(nrt_started_utc-since_utc).total_seconds()} seconds ago)')

  page = 1

  issue_numbers_refreshed = []

  # in case we need to load multiple pages to get the updated issues:
  while True:

    # TODO: make it tz aware?
    since_string = since_utc.isoformat()
    # Not certain but GH may not like these fractional seconds -- strip them:
    if '.' in since_string:
      since_string = since_string[:since_string.index('.')]

    # Add zulu (UTC) timezone:
    since_string += 'Z'

    # hopefully we never wind up throttling here due to too many issue updates versus GitHub API rate limit!
    batch = local_db.http_load_as_json(f'https://api.github.com/repos/apache/lucene/issues?state=all&per_page=100&direction=asc&since={since_string}&page={page}')

    if len(batch) == 0:
      print('  no more results... finishing')
      break

    for issue in batch:
      number = issue['number']
      print(f'  load {number}')
      load_and_store_full_issue(issue, db, c)
      issue_numbers_refreshed.append(number)
        
    page += 1

  if False and len(issue_numbers_refreshed) != total_count:
    # TODO: github API seems not to give us total count?
    print(f'WARNING: iterated through {len(issue_numbers_refreshed)} issues but GitHub issues API claimed we would see {total_count}')

  c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)', ('last_update', pickle.dumps(nrt_started_utc),))
  db.commit()

  return issue_numbers_refreshed

def refresh_specific_issues(issue_numbers):
  db = local_db.get()
  c = db.cursor()
  for number in issue_numbers:
    print(f'  refresh {number}')
    issue = http_load_as_json(f'https://api.github.com/repos/apache/lucene/issues/{number}')
    load_and_store_full_issue(issue, db, c)

if __name__ == '__main__':
  main()
