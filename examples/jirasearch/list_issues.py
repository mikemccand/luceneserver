import sqlite3
import pickle

DB_PATH = 'github_issues.db'

db = sqlite3.connect(DB_PATH)
c = db.cursor()

issues = c.execute('SELECT pickle FROM issues WHERE key NOT IN ("last_update", "page_upto")').fetchall()
count = 0
for issue in issues:
  issue, comments, events, reactions, timeline = pickle.loads(issue[0])
  print(f'issue {issue["number"]}\n  {len(comments)} comments')
  count += 1
print(f'{count} issues')
