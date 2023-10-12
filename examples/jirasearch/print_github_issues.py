import pickle
import sqlite3
import localconstants
import json
import datetime
from datetime import timezone

DB_PATH = localconstants.DB_PATH

def connect_db_readonly():
  path = f'file:{DB_PATH}?mode=ro'
  return sqlite3.connect(path, uri=True, timeout=120)

def main():
  db = connect_db_readonly()
  c = db.cursor()
  now = datetime.datetime.now(timezone.utc)
  open_pr_count = 0
  closed_pr_count = 0
  histo_by_days = {}
  for k, v in c.execute('SELECT key, pickle FROM issues'):
    if k in ('last_update', 'page_upto'):
      continue
    issue, comments, events, reactions, timeline = pickle.loads(v)

    if 'pull_request' in issue:
        print(f'  {issue["number"]} is pr!')
        print(f'    {len(comments)} comments')
        #print(f'    {issue["state"]}')
        if issue['state'] == 'open':
            open_pr_count += 1
            #print(json.dumps(issue, indent=2))
            created_at = datetime.datetime.fromisoformat(issue['created_at'])
            age = now - created_at
            days_age = int(age.total_seconds()/(24*3600.))
            print(f'    age={age}')
            histo_by_days[days_age] = 1+histo_by_days.get(days_age, 0)
        else:
            closed_pr_count += 1

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

