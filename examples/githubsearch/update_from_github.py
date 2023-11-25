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

  login_to_name = local_db.get_login_to_name()
  print(f'{len(login_to_name)} unique users')
  
  c = db.cursor()

  # nocommit
  #refresh_specific_issues([12624])
  #sys.exit(0)

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

  c = db.cursor()
  total_issue_count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]
  print(f'{total_issue_count} issues in DB')
  while True:
    refresh_latest_issues(db)
    time.sleep(5.0)

def load_and_store_full_issue(issue, db, c):

  number = issue['number']

  now = datetime.datetime.now()
  comments, events, reactions, timeline, full_pr, pr_comments, pr_reviews = load_full_issue(issue)

  local_db.maybe_load_user(c, issue['user']['login'])
  for comment in comments:
      local_db.maybe_load_user(c, comment['user']['login'])

  c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)',
            (str(number), pickle.dumps((issue, comments, events, reactions, timeline, full_pr, pr_comments, pr_reviews))))

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

  # TODO: make it tz aware?
  since_string = since_utc.isoformat()
  # Not certain but GH may not like these fractional seconds -- strip them:
  if '.' in since_string:
    since_string = since_string[:since_string.index('.')]

  # Add zulu (UTC) timezone:
  since_string += 'Z'

  next_page_url = f'https://api.github.com/repos/apache/lucene/issues?state=all&per_page=100&direction=asc&since={since_string}&page={page}'

  # in case we need to load multiple pages to get the updated issues:
  while True:

    # hopefully we never wind up throttling here due to too many issue updates versus GitHub API rate limit!
    # then we have a problem ... rate of GitHub updates exceeds our throttle limit
    batch, next_page_url = local_db.http_load_as_json(next_page_url, handle_pages=False)

    for issue in batch:
      number = issue['number']
      print(f'  load {number}')
      load_and_store_full_issue(issue, db, c)
      issue_numbers_refreshed.append(number)

    if next_page_url is None:
      print('  no more results... finishing')
      break

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
