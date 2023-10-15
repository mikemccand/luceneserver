import sqlite3
import requests
import json
import time
import pickle

from localconstants import DB_PATH, ROOT_STATE_PATH, GITHUB_API_TOKEN

db_readonly = None
db = None
ratelimit_remaining = None

_login_to_name = None

def get_login_to_name():
    global _login_to_name
    if _login_to_name is None:
        #t0 = time.time()
        _login_to_name = {}

        db = get(read_only=True)
        c = db.cursor()
        for login, blob in c.execute('SELECT login, pickle FROM users').fetchall():
            user = pickle.loads(blob)
            #print(f'{login}:\n{json.dumps(user, indent=2)}')
            name = user['name']
            if name is None:
                name = login
            _login_to_name[login] = name
        #t1 = time.time()
        #print(f'{1000*(t1-t0):.1f} msec to compute _login_to_name; {len(_login_to_name)} unique users')
    return _login_to_name

def get(read_only=False):
  global db
  global db_readonly

  # nocommit -- hmm what if same process opens both?  index_github does so!
  if not read_only:
    if db is None:
      db = sqlite3.connect(DB_PATH)
    return db
  else:
    if db_readonly is None:
      db_readonly = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    return db_readonly

def maybe_load_user(c, login):
  login_to_name = get_login_to_name()
  if login in login_to_name:
    return
  print(f'now load full user for login {login}')
  user = http_load_as_json(f'https://api.github.com/users/{login}')
  name = user['name']
  print(f'  --> name: {name}')
  c.execute('INSERT INTO users (login, pickle) VALUES (?, ?)', (login, pickle.dumps(user)))
  login_to_name[login] = name

  # yes, O(N^2) but N is smallish, and this cost is paid once on initial GitHub crawl
  open('%s/user_names_map.pk' % ROOT_STATE_PATH, 'wb').write(pickle.dumps(login_to_name))

def http_load_as_json(url):
  global ratelimit_remaining
    
  headers = {'Authorization': f'token {GITHUB_API_TOKEN}',
             'Accept': 'application/vnd.github.full+json',
             'X-GitHub-Api-Version': '2022-11-28'}
  response = requests.get(url, headers=headers)
  if response.status_code != 200:
    raise RuntimeError(f'got {response.status_code} response loading {url}\n\n {response.text}')
  if not response.headers['Content-Type'].startswith('application/json'):
    raise RuntimeError(f'got {response.headers["Content-Type"]} but expected application/json when loading {url}')

  # print(f'\n{url}\n  response headers: {response.headers}')
    
  # wait due to GitHub API throttling:
  ratelimit_remaining = int(response.headers['X-RateLimit-Remaining'])
  if ratelimit_remaining < 10:
    reset_at = int(response.headers['X-RateLimit-Reset'])
    wait_seconds = reset_at - time.time() + 5
    if wait_seconds > 0:
      db.commit()
      print(f'Now wait due to throttling ({ratelimit_remaining} requests remaining (reset at {reset_at}; wait for {wait_seconds} seconds)')
      time.sleep(wait_seconds)
        
  # print(response.headers)
  return json.loads(response.text)
