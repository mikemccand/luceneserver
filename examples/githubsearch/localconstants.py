LOG_DIR = 'logs'
IS_DEV = True
LUCENE_SERVER_VERSION = '6.2'
LUCENE_TRUNK_GIT_CLONE = '/l/trunk'

ROOT_STATE_PATH = '/home/mike/github-search-state'
DB_PATH = f'{ROOT_STATE_PATH}/github_issues.db'

GIT_HISTORY_FILE = f'{ROOT_STATE_PATH}/git-history.txt'

LUCENE_SERVER_VERSION = '0.1.1'

SERVER_PORT = 8888

ROOT_INDICES_PATH = '/home/mike/lucene-root-indices'

HEAP = '4g'

JAVA_EXE = '/usr/bin/java'

IS_DEV = True

# hmm suddenly as of Oct 14 2023 this is not accepted?
# GITHUB_API_TOKEN = '9b6e21b251034e635fc2d5ad8d6cae19a7beef94'

# NOTE: expires Oct 14, 2024 (called Jirasearch indexing GitHub)
GITHUB_API_TOKEN = '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'

# NOTE: expires Oct 21, 2024 (called jirasearch-lucene at GitHub)
GITHUB_API_TOKEN2 = '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'

# why github?
#   - buggy search: /pull search will silently not search issues
#   - does not convey jira tags well
#   - want more intelligence extracted, e.g. are we falling behind on PRs?
#   - missing faceting

