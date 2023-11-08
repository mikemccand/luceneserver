import sys
import pickle
import sqlite3
import localconstants
import json
import datetime
from datetime import timezone
from index_github import decode_and_load_one_issue

DB_PATH = localconstants.DB_PATH

def connect_db_readonly():
  path = f'file:{DB_PATH}?mode=ro'
  return sqlite3.connect(path, uri=True, timeout=120)

def main():
  db = connect_db_readonly()
  c = db.cursor()
  c2 = db.cursor()
  now = datetime.datetime.now(timezone.utc)
  open_pr_count = 0
  closed_pr_count = 0
  histo_by_days = {}

  if '-print_full_pr' in sys.argv:
    i = sys.argv.index('-print_full_pr')
    pr_number = sys.argv[i+1]
    blob = c.execute('SELECT pickle FROM issues WHERE key=?', (pr_number,)).fetchone()[0]
    issue, comments, events, reactions, timeline = pickle.loads(blob)
    print(f'\nISSUE:\n{json.dumps(issue, indent=2)}')
    print(f'\nCOMMENTS:\n{json.dumps(comments, indent=2)}')
    print(f'\nEVENTS:\n{json.dumps(events, indent=2)}')
    print(f'\nREACTIONS:\n{json.dumps(reactions, indent=2)}')
    print(f'\nTIMELINE:\n{json.dumps(timeline, indent=2)}')

    blob = c.execute('SELECT pickle FROM full_issue WHERE key=?', (pr_number,)).fetchone()[0]
    full_issue = pickle.loads(blob)
    print(f'\nFULL PULL_REQUEST:\n{json.dumps(full_issue, indent=2)}')
    
    
    sys.exit(0)
    
  for k, v in c.execute('SELECT key, pickle FROM issues').fetchall():
    if k in ('last_update', 'page_upto'):
      continue

    (issue, comments, events, reactions, timeline), full_pr, full_pr_comments, pr_reviews = decode_and_load_one_issue(c2, v)

    if issue['number'] == 12781:
      print(f'\nISSUE:\n{json.dumps(issue, indent=2)}')
      print(f'\nCOMMENTS:\n{json.dumps(comments, indent=2)}')
      print(f'\nEVENTS:\n{json.dumps(events, indent=2)}')
      print(f'\nREACTIONS:\n{json.dumps(reactions, indent=2)}')
      print(f'\nTIMELINE:\n{json.dumps(timeline, indent=2)}')
      print(f'\nFULL_PR:\n{json.dumps(full_pr, indent=2)}')
      print(f'\nFULL_PR_COMMENTS:\n{json.dumps(full_pr_comments, indent=2)}')
      print(f'\nPR_REVIEWS:\n{json.dumps(full_pr_reviews, indent=2)}')

    if 'pull_request' in issue:
      if 'mergeable_state' in issue and issue['mergeable_state'] == 'unknown':
        print(f'unknown: {issue["html_url"]}')

    #print(f'\n issue {issue["number"]}\n{json.dumps(issue, indent=2)}')
    if False and len(events) > 0:
      print(f'\nissue {issue["number"]}')
      for event in events:
        # event types: https://docs.github.com/en/rest/overview/issue-event-types?apiVersion=2022-11-28
        print(f'  {event["event"]}')
    if False and len(timeline) > 0:
      print(f'\nissue {issue["number"]}')
      for t in timeline:
        #print(f'  {json.dumps(t, indent=2)}')
        print(f'  {t["event"]}')
  print(f'{open_pr_count} open PRs; {closed_pr_count} closed PRs')

  entries = list(histo_by_days.items())
  entries.sort()
  for days_age, count in entries:
      print(f'{days_age} days: {count}')
  
if __name__ == '__main__':
  main()
