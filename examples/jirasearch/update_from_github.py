import pickle
import json
import datetime
import sqlite3
import time

from localconstants import DB_PATH, GITHUB_API_TOKEN
from direct_load_all_github_issues import http_load_as_json, load_full_issue, maybe_load_user

try:
  with open('%s/user_names_map.pk' % localconstants.ROOT_STATE_PATH, 'rb') as f:
    login_to_name = pickle.load(f)
except FileNotFoundError:
  login_to_name = {}
except:
  print('WARNING: unable to load prior user names map; starting new one')
  login_to_name = {}

def main():
  # not read only, because we write new issue/pr updates into it:
  db = sqlite3.connect(DB_PATH)

  # nocommit one time user table update:
  c = db.cursor()
  for k, v in c.execute('SELECT key, pickle FROM issues WHERE key not in ("last_update", "page_upto")'):
    issue, comments, events, reactions, timeline = pickle.loads(v)
    maybe_load_user(c, issue['user']['login'], login_to_name)
    for comment in comments:
        maybe_load_user(c, comment['user']['login'], login_to_name)
    for change in events:
        maybe_load_user(c, change['actor']['login'], login_to_name)
    for change in timeline:
        maybe_load_user(c, change['actor']['login'], login_to_name)

  if False:
      # nocommit
      c = db.cursor()
      c.execute('CREATE TABLE users (login TEXT UNIQUE PRIMARY KEY, pickle BLOB)')
      db.commit()

  c = db.cursor()
  total_issue_count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]
  print(f'{total_issue_count} issues in DB')
  while True:
    refresh_latest_issues(db)
    time.sleep(5.0)

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

  since_utc = last_update_utc - datetime.timedelta(seconds=60)

  print('\n%s: now refresh latest updates' % datetime.datetime.now())
  print(f'  use since={since_utc} ({(nrt_started_utc-since_utc).total_seconds()} seconds ago)')

  page = 1

  issue_numbers_refreshed = []

  # in case we need to load multiple pages to get the updated issues:
  while True:

    # hopefully we never wind up throttling here due to too many issue updates versus GitHub API rate limit!
    batch = http_load_as_json(f'https://api.github.com/repos/apache/lucene/issues?state=all&per_page=100&direction=asc&since={since_utc.isoformat()}&page={page}')
    # print(f'got: {json.dumps(batch, indent=2)} len={len(batch)}')

    if len(batch) == 0:
        print('  no more results... finishing')
        break

    for issue in batch:

      print(f'  load {issue["number"]}')

      now = datetime.datetime.now()
      comments, events, reactions, timeline = load_full_issue(issue)

      maybe_load_user(c, issue['user']['login'], login_to_name)
      for comment in comments:
          maybe_load_user(c, comment['user']['login'], login_to_name)
      # nocommit what about events/timeline users?

      c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)',
                (str(issue['number']), pickle.dumps((issue, comments, events, reactions, timeline))))
      issue_numbers_refreshed.append(issue['number'])

    if False:
        if not batch['incomplete_results']:
          page += 1
        else:
          # retry same page -- GitHub timed out and gave us subset of results
          pass
    page += 1

  if False and len(issue_numbers_refreshed) != total_count:
    print(f'WARNING: iterated through {len(issue_numbers_refreshed)} issues but GitHub issues API claimed we would see {total_count}')

  c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)', ('last_update', pickle.dumps(nrt_started_utc),))
  db.commit()

  total_issue_count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]

  print(f'  loaded and indexed {len(issue_numbers_refreshed)} issues; {total_issue_count} issues in DB')

if __name__ == '__main__':
    main()
