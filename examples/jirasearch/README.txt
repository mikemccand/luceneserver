Simple Python scripts that pull Jira issues via the JSON search API,
index them into luceneserver and offer a simple WSGI search UI to
search/facet.

loadAllJiraIssues.py -- run this once for a full export of all Jira issues

createDB.py -- makes a local sqlite3 DB from the above issues loaded

indexJira.py -- indexes all issues (-reindex -delete), and also does nrt build (-nrt)

