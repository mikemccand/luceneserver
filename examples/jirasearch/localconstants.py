DB_PATH = 'github_issues.db'
LOG_DIR = 'logs'
IS_DEV = True
LUCENE_SERVER_VERSION = '6.2'
GIT_HISTORY_FILE = 'git-history.txt'

ROOT_STATE_PATH = '/home/mike/github-search-state'

LUCENE_SERVER_VERSION = '0.1.1'

SERVER_PORT = 8888

ROOT_INDICES_PATH = '/home/mike/lucene-root-indices'

HEAP = '4g'

JAVA_EXE = '/usr/bin/java'

IS_DEV = True

GITHUB_API_TOKEN = '9b6e21b251034e635fc2d5ad8d6cae19a7beef94'

# why github?
#   - buggy search: /pull search will silently not search issues
#   - does not convey jira tags well
#   - want more intelligence extracted, e.g. are we falling behind on PRs?
#   - missing faceting

