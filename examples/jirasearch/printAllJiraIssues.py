import pprint
import dbm
import localconstants
import traceback
import pickle

DB_PATH = localconstants.DB_PATH

def allIssues():
  db = dbm.open(DB_PATH, 'r')
  try:
    for k in db.keys():
      if k != b'lastUpdate':
        try:
          yield pickle.loads(db[k])
        except:
          traceback.print_exc()
          print(k)
  finally:
    db.close()

for issue in allIssues():
  pprint.pprint(issue)
