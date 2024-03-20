import sqlite3
import traceback
import requests
import json
import time
import pickle

from localconstants import DB_PATH, ROOT_STATE_PATH, GITHUB_API_TOKEN

db_readonly = None
db = None
ratelimit_remaining = None

_login_to_name = None
_jira_to_github_account_map = None

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
        # For some insane reason, Doug has no display name ;)
        _login_to_name['cutting'] = 'Doug Cutting'
        
    return _login_to_name

def get_jira_to_github_account_map():
  global _jira_to_github_account_map
  if _jira_to_github_account_map is None:
      _jira_to_github_account_map = {}
      with open('account-map.csv.20220722.verified', encoding='utf-8') as f:
          for line in f.readlines():
              if line.startswith('#'):
                  continue
              line = line.strip()
              if len(line) == 0:
                  continue
              if line == 'JiraName,GitHubAccount,JiraDispName':
                  # header line
                  continue
              tup = line.split(',')
              if len(tup) != 3:
                  raise RuntimeError(f'expected three entries on line, but got {len(tup)}: {tup}')
              jira_login, github_login, jira_display_name = tup
              _jira_to_github_account_map[jira_login] = (github_login, jira_display_name)
  return _jira_to_github_account_map

def get(read_only=False):
  global db
  global db_readonly

  print(f'now get DB {read_only=}')
  traceback.print_stack()

  # nocommit maybe nuke the whole concept of read-only?  i don't think i can open DB from two processes even if second one is read-only=true, or if both are?
  if True or not read_only:
    if db_readonly is not None:
      raise RuntimeError('cannot open non-read-only DB after first opening read-only DB')
    if db is None:
      db = sqlite3.connect(DB_PATH)
    return db
  elif db is not None:
    # if read-only requested, and we already have read/write opened, return it.  else we get "db is locked" errors:
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
  c.execute('REPLACE INTO users (login, pickle) VALUES (?, ?)', (login, pickle.dumps(user)))
  login_to_name[login] = name

  # yes, O(N^2) but N is smallish, and this cost is paid once on initial GitHub crawl
  open('%s/user_names_map.pk' % ROOT_STATE_PATH, 'wb').write(pickle.dumps(login_to_name))

def maybe_retry(retry_count, message):
  if retry_count < 5:
    sleep_time_sec = 2 ** retry_count
    print(f'request failed: {message} retry_count={retry_count}; will retry after pausing for {sleep_time_sec} seconds')
    time.sleep(sleep_time_sec)
    return retry_count + 1
  else:
    raise RuntimeError(f'{message}; too many retries, giving up')
  

def http_load_as_json(url, do_post=False, token=GITHUB_API_TOKEN, handle_pages=True):
  global ratelimit_remaining
  print(f'    load to json {url} {handle_pages=}')

  all_results = None

  # for each page
  while True:

    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.full+json',
        'X-GitHub-Api-Version': '2022-11-28'}

    # for each retry
    retry_count = 0
    
    while True:
      try:
        if do_post:
          response = requests.post(url, headers=headers, timeout=30)
        else:
          response = requests.get(url, headers=headers, timeout=30)
      except Exception as e:
        retry_count = maybe_retry(retry_count, f'request failed: url={url} headers={headers} exception={e} retry_count={retry_count}')
        continue

      if response.status_code != 200:
        retry_count = maybe_retry(retry_count, f'got {response.status_code} response loading {url}\n\n {response.text}')
        continue

      if not response.headers['Content-Type'].startswith('application/json'):
        retry_count = maybe_retry(retry_count, f'got {response.headers["Content-Type"]} but expected application/json when loading {url}')
        continue

      # wait due to GitHub API throttling:
      try:
        s = response.headers['X-RateLimit-Remaining']
      except KeyError:
        pass
      else:
        ratelimit_remaining = int(s)
        if ratelimit_remaining < 10:
          reset_at = int(response.headers['X-RateLimit-Reset'])
          wait_seconds = reset_at - time.time() + 5
          if wait_seconds > 0:
            db.commit()
            print(f'Now wait due to throttling ({ratelimit_remaining} requests remaining (reset at {reset_at}; wait for {wait_seconds} seconds)')
            time.sleep(wait_seconds)

      try:
        this_page_results = json.loads(response.text)
      except:
        print(f'failed to parse respone as JSON:\n{response.headers}\n{response.text}; retry')
        retry_count = maybe_retry(retry_count, f'failed to parse json: {response.text}')
        continue
      else:
        break
    
    if all_results is None:
      # maybe only one page, or all results fit into page 1
      all_results = this_page_results
    else:
      if type(all_results) != list:
        raise RuntimeError(f'saw next page, but previous type was not a list: got {type(all_results)}')
      else:
        all_results.extend(this_page_results)

    if 'next' in response.links and handle_pages:
      # this is a paginated response, and we have not reached the end yet:
      url = response.links['next']['url']
      print(f'      next page: {url}, result count is {len(all_results)}')
    else:
      break

  if handle_pages:
    return all_results
  else:
    if 'next' in response.links:
      next_page_url = response.links['next']['url']
    else:
      next_page_url = None
    return all_results, next_page_url
