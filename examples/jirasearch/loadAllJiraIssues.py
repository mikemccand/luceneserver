# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import traceback
import sqlite3
import http.client
import os
import time
import json
import urllib.request, urllib.parse, urllib.error
import pickle
import localconstants
import datetime
import pickle

"""
Does a one-time initial load of the (massive, ~639 MB as of
10/17/2016) full set of Jira issues.  This takes a long time, maybe ~8
hours, because it pauses for 60 seconds between each scrolled load so
we don't overly stress the Apache Jira instance.
"""

if os.getcwd().find('.dev') != -1:
  isDev = True
else:
  isDev = False

#DB_PATH = '/lucenedata/jiracache/db'
DB_PATH = localconstants.DB_PATH

def prettyPrintJSON(obj):
  print(json.dumps(obj,
                   sort_keys=True,
                   indent=4, separators=(',', ': ')))

def loadAllIssues(db, project):

  f = open('allIssues.txt', 'ab')

  args = {
    'jql': 'project="%s" ORDER BY key ASC' % project,
    'maxResults': '200',
    'expand': 'changelog',
    'fields': '*all',
    }

  startAt = 0

  #dir = '%s/%s' % (localconstants.JSON_PATH, project)

  #if not os.path.exists(dir):
  #  os.makedirs(dir)
  
  while True:
    args['startAt'] = str(startAt)
    url = 'https://issues.apache.org/jira/rest/api/2/search?%s' % urllib.parse.urlencode(args)
    while True:
      try:
        s = urllib.request.urlopen(url).read().decode('utf-8')
      except:
        traceback.print_exc()
        print('FAILED: wait then retry...\n')
        time.sleep(30.0)
      else:
        break
    #prettyPrintJSON(json.loads(s))
    #open('%s/%d.pk' % (dir, startAt), 'wb').write(s)
    o = json.loads(s)
    numIssues = len(o['issues'])
    total = o['total']
    print('%s %s: %d results of %d; %.1f KB' % (project, startAt, numIssues, total, len(s)/1024.))
    for x in o['issues']:
      f.write(('%s: %s\n' % (x['key'], json.dumps(x))).encode('utf-8'))
      print('  %s' % x['key'])
      #c.execute('INSERT INTO issues values (?, ?)', (x['key'], pickle.dumps(x)))
    startAt += numIssues
    if startAt >= total:
      break
    time.sleep(60.0)

  f.close()

db = sqlite3.connect('test.db')
if False:
  c = db.cursor()
  c.execute('DROP TABLE issues')
  c.execute('CREATE TABLE issues (key text, body text)')
  c.execute('INSERT INTO issues values (?, ?)', ('lastUpdate', pickle.dumps(datetime.datetime.now())))
#loadAllIssues(db, 'Lucene - Core')
loadAllIssues(db, 'Solr')
loadAllIssues(db, 'Tika')
loadAllIssues(db, 'Infrastructure')
db.commit()
db.close()

  
# EG:
"""
python -u jira.py
https://issues.apache.org/jira/rest/api/2/search?fields=%2Aall&jql=project%3D%22Lucene+-+Core%22+ORDER+BY+key+ASC&maxResults=10

{
    "expand": "schema,names",
    "issues": [
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Lucene Developers",
                    "emailAddress": "noreply@example.com",
                    "name": "java-dev@lucene.apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=java-dev%40lucene.apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "I fixed this by disabling lock files in JDK 1.1.\n",
                            "created": "2001-10-10T17:50:07.000+0000",
                            "id": "12320963",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314151/comment/12320963",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-10-10T17:50:07.000+0000"
                        }
                    ],
                    "maxResults": 1,
                    "startAt": 0,
                    "total": 1
                },
                "components": [
                    {
                        "description": "issues with store code (e.g. Directory)",
                        "id": "12310236",
                        "name": "core/store",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310236"
                    }
                ],
                "created": "2001-10-09T16:19:16.000+0000",
                "customfield_10010": 4049.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-10-10 17:50:07.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_146049355000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "0.0",
                "customfield_12310420": "13749",
                "customfield_12310920": "27719",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "The method File.createNewFile() does not exist in JDK 1.1.8.  Since Lucene \nstill supports JDK 1.1, a workaround should be found.",
                "duedate": null,
                "environment": "Operating System: All\nPlatform: All",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/major.png",
                    "id": "3",
                    "name": "Major",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/3"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Doug Cutting",
                    "emailAddress": "cutting@apache.org",
                    "name": "cutting",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting"
                },
                "resolution": {
                    "description": "A fix for this issue is checked into the tree and tested.",
                    "id": "1",
                    "name": "Fixed",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/1"
                },
                "resolutiondate": "2006-06-06T06:24:38.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "lock files don't work in JDK 1.1",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:01:08.000+0000",
                "versions": [
                    {
                        "archived": true,
                        "description": "First Apache release",
                        "id": "12310284",
                        "name": "1.2",
                        "releaseDate": "2002-06-13",
                        "released": true,
                        "self": "https://issues.apache.org/jira/rest/api/2/version/12310284"
                    }
                ],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-1/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-1/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314151",
            "key": "LUCENE-1",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314151"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Lucene Developers",
                    "emailAddress": "noreply@example.com",
                    "name": "java-dev@lucene.apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=java-dev%40lucene.apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "\n\n*** This bug has been marked as a duplicate of 4105 ***",
                            "created": "2001-12-04T18:30:00.000+0000",
                            "id": "12320964",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314152/comment/12320964",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-12-04T18:30:00.000+0000"
                        }
                    ],
                    "maxResults": 1,
                    "startAt": 0,
                    "total": 1
                },
                "components": [
                    {
                        "description": "issues with QueryParser code under core",
                        "id": "12310234",
                        "name": "core/queryparser",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310234"
                    }
                ],
                "created": "2001-10-11T12:55:32.000+0000",
                "customfield_10010": 4102.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-12-04 18:30:00.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_145888780000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "0.0",
                "customfield_12310420": "13748",
                "customfield_12310920": "27718",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "Hi. I am using a cvs version of Lucene (got on 2001.10.11).\n\nI am having the following problem: while I can achieve case insensibility of the\nsearch engine by using the correct tokenizer (a derivative of\nLowerCaseTokenizer, which passes alphanumeric characters instead of letters only\nas token components), I cannot have this feature work with prefix queries.\n\nAs I am currently working on the problem myself, I can submit a solution fixing\nthis bug in some future.",
                "duedate": null,
                "environment": "Operating System: other\nPlatform: Other",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/major.png",
                    "id": "3",
                    "name": "Major",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/3"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Andrzej Jarmoniuk",
                    "emailAddress": "andrzej.jarmoniuk@e-point.pl",
                    "name": "andrzej.jarmoniuk@e-point.pl",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=andrzej.jarmoniuk%40e-point.pl"
                },
                "resolution": {
                    "description": "The problem is a duplicate of an existing issue.",
                    "id": "3",
                    "name": "Duplicate",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/3"
                },
                "resolutiondate": "2006-05-27T01:35:12.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "Prefix Queries cannot be case insensitible",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:03:39.000+0000",
                "versions": [],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-2/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-2/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314152",
            "key": "LUCENE-2",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314152"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Lucene Developers",
                    "emailAddress": "noreply@example.com",
                    "name": "java-dev@lucene.apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=java-dev%40lucene.apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "A simple way to fix this might be to add two methods to QueryParser:\n  void setLowercasePrefixes(boolean);\n  boolean getLowercasePrefixes();\n\nThis would determine whether prefixes are lowercased by the query parser before \nthe PrefixQuery is constructed.  It could be true by default.\n\nWould that suffice?",
                            "created": "2001-10-11T15:26:36.000+0000",
                            "id": "12320965",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314153/comment/12320965",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-10-11T15:26:36.000+0000"
                        },
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "*** Bug 4102 has been marked as a duplicate of this bug. ***",
                            "created": "2001-12-04T18:30:02.000+0000",
                            "id": "12320966",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314153/comment/12320966",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-12-04T18:30:02.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Daniel Rall",
                                "emailAddress": "dlr@finemaltcoding.com",
                                "name": "dlr@finemaltcoding.com",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=dlr%40finemaltcoding.com"
                            },
                            "body": "corrected spelling while searching for another bug",
                            "created": "2002-01-29T05:07:45.000+0000",
                            "id": "12320967",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314153/comment/12320967",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Daniel Rall",
                                "emailAddress": "dlr@finemaltcoding.com",
                                "name": "dlr@finemaltcoding.com",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=dlr%40finemaltcoding.com"
                            },
                            "updated": "2002-01-29T05:07:45.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Erik Hatcher",
                                "emailAddress": "jakarta@ehatchersolutions.com",
                                "name": "jakarta@ehatchersolutions.com",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=jakarta%40ehatchersolutions.com"
                            },
                            "body": "I believe this has been fixed with the setLowercaseWildcardTerms flag in QueryParser.",
                            "created": "2003-10-31T18:33:45.000+0000",
                            "id": "12320968",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314153/comment/12320968",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Erik Hatcher",
                                "emailAddress": "jakarta@ehatchersolutions.com",
                                "name": "jakarta@ehatchersolutions.com",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=jakarta%40ehatchersolutions.com"
                            },
                            "updated": "2003-10-31T18:33:45.000+0000"
                        }
                    ],
                    "maxResults": 4,
                    "startAt": 0,
                    "total": 4
                },
                "components": [
                    {
                        "description": "issues with QueryParser code under core",
                        "id": "12310234",
                        "name": "core/queryparser",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310234"
                    }
                ],
                "created": "2001-10-11T13:36:45.000+0000",
                "customfield_10010": 4105.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-10-11 15:26:36.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_145886307000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "0.0",
                "customfield_12310420": "13747",
                "customfield_12310920": "27717",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "Hi. I am using a cvs version of Lucene (got on 2001.10.11).\n\nI am having the following problem: while I can achieve case insensibility of the\nsearch engine by using the correct tokenizer (a derivative of\nLowerCaseTokenizer, which passes alphanumeric characters instead of letters only\nas token components), I cannot have this feature work with prefix queries.\n\nAs I am currently working on the problem myself, I can submit a solution fixing\nthis bug in some future.",
                "duedate": null,
                "environment": "Operating System: other\nPlatform: Other",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/major.png",
                    "id": "3",
                    "name": "Major",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/3"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Andrzej Jarmoniuk",
                    "emailAddress": "andrzej.jarmoniuk@e-point.pl",
                    "name": "andrzej.jarmoniuk@e-point.pl",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=andrzej.jarmoniuk%40e-point.pl"
                },
                "resolution": {
                    "description": "A fix for this issue is checked into the tree and tested.",
                    "id": "1",
                    "name": "Fixed",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/1"
                },
                "resolutiondate": "2006-05-27T01:35:12.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "Prefix Queries cannot be case insensitive",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:03:39.000+0000",
                "versions": [],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-3/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-3/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314153",
            "key": "LUCENE-3",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314153"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Lucene Developers",
                    "emailAddress": "noreply@example.com",
                    "name": "java-dev@lucene.apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=java-dev%40lucene.apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "The way boosts are currently implemented, I actually don't think that this will \nwork.  The boosts are squared in TermQuery.sumOfSquaredWeights(), which loses \ntheir negativeness, no?\n\nAnd as you've reported separately, zeroed weights don't do what you want either.\n\nCan you try changing that method so that boosts are not multiplied in until \nafter the query is normalized?  Tell me if that makes things work any better \nfor you.\n   \n   final float sumOfSquaredWeights(Searcher searcher) throws IOException {\n-    idf = Similarity.idf(term, searcher);\n-    weight = idf * boost;\n+    weight = idf = Similarity.idf(term, searcher);\n     return weight * weight;\t\t\t  // square term weights\n   }\n \n   final void normalize(float norm) {\n     weight *= norm;\t\t\t\t  // normalize for query\n     weight *= idf;\t\t\t\t  // factor from document\n+    weight *= boost;                              // boost query\n   }\n",
                            "created": "2001-10-24T18:45:11.000+0000",
                            "id": "12320969",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314154/comment/12320969",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-10-24T18:45:11.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "body": "Has anyone tried Doug's suggestion for this or confirmed that Alex's query\nparser modification indeed works properly, despite Doug's doubt?\n\nI'd just like to close this bug, if possible.\nThanks.",
                            "created": "2002-04-04T00:17:30.000+0000",
                            "id": "12320970",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314154/comment/12320970",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "updated": "2002-04-04T00:17:30.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "body": "This bug is over a year old, and we have not heard from the original bug\nreporter, so I'm closing it.\nOne thing that we may want to do is throw IllegalArgumentException in\nsetBoost(Float) if the method param is <=0.\n\nDoes anyone mind this?\n",
                            "created": "2003-05-12T03:20:47.000+0000",
                            "id": "12320971",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314154/comment/12320971",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "updated": "2003-05-12T03:20:47.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "body": "Created an attachment (id=6318)\nDiff against QueryParser.jj revision 1.29\n",
                            "created": "2003-05-12T03:29:31.000+0000",
                            "id": "12320972",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314154/comment/12320972",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "updated": "2003-05-12T03:29:31.000+0000"
                        }
                    ],
                    "maxResults": 4,
                    "startAt": 0,
                    "total": 4
                },
                "components": [
                    {
                        "description": "issues with QueryParser code under core",
                        "id": "12310234",
                        "name": "core/queryparser",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310234"
                    }
                ],
                "created": "2001-10-18T00:00:23.000+0000",
                "customfield_10010": 4254.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-10-24 18:45:11.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_145330490000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "1.0",
                "customfield_12310420": "13746",
                "customfield_12310920": "27716",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "The TermQuery allows .setBost to set a float multiplier.  The boost is entered \nvia a '^'<NUMBER> format in the String query, however, while .setBoost will \ntake a negative number, the parser does not allow negative numbers due to the \nlimited description of the <NUMBER> token (QueryParser.jj):\n\n| <NUMBER:     (<_NUM_CHAR>)+ \".\" (<_NUM_CHAR>)+ >\n\nThe solution is to allow + or - as in:\n\n| <NUMBER:    ([\"+\",\"-\"])? (<_NUM_CHAR>)+ \".\" (<_NUM_CHAR>)+ >\n\nThis works correctly, properly reading negative numbers.  \n\nI have done some simple tests, and negative boost seems to work as expected, by \nmoving the entry to the end of the list.",
                "duedate": null,
                "environment": "Operating System: other\nPlatform: All",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/major.png",
                    "id": "3",
                    "name": "Major",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/3"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Alex Paransky",
                    "emailAddress": "alex.paransky@individualnetwork.com",
                    "name": "alex.paransky@individualnetwork.com",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=alex.paransky%40individualnetwork.com"
                },
                "resolution": {
                    "description": "The problem described is an issue which will never be fixed.",
                    "id": "2",
                    "name": "Won't Fix",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/2"
                },
                "resolutiondate": "2006-05-27T01:35:13.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "QueryParser does not recognized negative numbers...",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:03:22.000+0000",
                "versions": [],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-4/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-4/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314154",
            "key": "LUCENE-4",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314154"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Gerhard Schwarz",
                    "emailAddress": "malco@claranet.de",
                    "name": "malco@claranet.de",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=malco%40claranet.de"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Gerhard Schwarz",
                                "emailAddress": "malco@claranet.de",
                                "name": "malco@claranet.de",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=malco%40claranet.de"
                            },
                            "body": "Created an attachment (id=797)\nPatch for the \"alpha-geek\" bug\n",
                            "created": "2001-11-15T18:49:40.000+0000",
                            "id": "12320973",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314155/comment/12320973",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Gerhard Schwarz",
                                "emailAddress": "malco@claranet.de",
                                "name": "malco@claranet.de",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=malco%40claranet.de"
                            },
                            "updated": "2001-11-15T18:49:40.000+0000"
                        },
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "Gerhard, has this bug been fixed?",
                            "created": "2001-12-04T18:34:31.000+0000",
                            "id": "12320974",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314155/comment/12320974",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-12-04T18:34:31.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Gerhard Schwarz",
                                "emailAddress": "malco@claranet.de",
                                "name": "malco@claranet.de",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=malco%40claranet.de"
                            },
                            "body": "A fix (diff) is already attached to the bug track (Patch for the \"alpha-geek\"\nbug). I will checkin the fix into CVS as soon as possible.",
                            "created": "2001-12-04T20:54:35.000+0000",
                            "id": "12320975",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314155/comment/12320975",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Gerhard Schwarz",
                                "emailAddress": "malco@claranet.de",
                                "name": "malco@claranet.de",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=malco%40claranet.de"
                            },
                            "updated": "2001-12-04T20:54:35.000+0000"
                        }
                    ],
                    "maxResults": 3,
                    "startAt": 0,
                    "total": 3
                },
                "components": [
                    {
                        "description": "issues related to analysis module",
                        "id": "12310230",
                        "name": "modules/analysis",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310230"
                    }
                ],
                "created": "2001-10-31T22:58:20.000+0000",
                "customfield_10010": 4555.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-11-15 18:49:40.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_144124613000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "1.0",
                "customfield_12310420": "13745",
                "customfield_12310920": "27715",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "Version: lucene-1.2-rc1.jar\n\nIndexing of \"alpha-geek2\" works.\nIndexing of \"alpha-geek\" throws exception. (Hope its not my inability.)\n\ndemo code which shows exception: http://www.nalle.de/TestIndex.java\nOutput of code:\n\nindexed 1\njava.lang.StringIndexOutOfBoundsException: String index out of range: -1\n        at java.lang.StringBuffer.charAt(StringBuffer.java:283)\n        at org.apache.lucene.analysis.de.GermanStemmer.resubstitute(Unknown \nSource)\n        at org.apache.lucene.analysis.de.GermanStemmer.stem(Unknown Source)\n        at org.apache.lucene.analysis.de.GermanStemFilter.next(Unknown Source)\n        at org.apache.lucene.analysis.LowerCaseFilter.next(Unknown Source)\n        at org.apache.lucene.index.DocumentWriter.invertDocument(Unknown Source)\n        at org.apache.lucene.index.DocumentWriter.addDocument(Unknown Source)\n        at org.apache.lucene.index.IndexWriter.addDocument(Unknown Source)\n        at TestIndex.<init>(TestIndex.java:25)\n        at TestIndex.main(TestIndex.java:36)",
                "duedate": null,
                "environment": "Operating System: Solaris\nPlatform: Sun",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/major.png",
                    "id": "3",
                    "name": "Major",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/3"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "M. Reinsch",
                    "emailAddress": "nalle@ymail.de",
                    "name": "nalle@ymail.de",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=nalle%40ymail.de"
                },
                "resolution": {
                    "description": "A fix for this issue is checked into the tree and tested.",
                    "id": "1",
                    "name": "Fixed",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/1"
                },
                "resolutiondate": "2006-05-27T01:35:13.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "GermanStemmer crashes while indexing",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:03:36.000+0000",
                "versions": [],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-5/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-5/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314155",
            "key": "LUCENE-5",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314155"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Lucene Developers",
                    "emailAddress": "noreply@example.com",
                    "name": "java-dev@lucene.apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=java-dev%40lucene.apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "This is mostly a documentation problem.  One must first call next() on a \nTermEnum created with IndexReader.terms(), but not one created by \nIndexReader.terms(Term).  In that case, one can check if the enun is already at \nits end by checking if enum.term() == null.\n\nThis is what PrefixQuery does, so PrefixQuery in fact works correctly.\n\nStill, this API should be improved, or at least better documented.\n\n",
                            "created": "2001-11-01T21:25:58.000+0000",
                            "id": "12320976",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314156/comment/12320976",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-11-01T21:25:58.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "body": "I believe this was fixed last week, when one of Christoph Goller's patches was\napplied.\n",
                            "created": "2003-09-19T04:38:06.000+0000",
                            "id": "12320977",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314156/comment/12320977",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "updated": "2003-09-19T04:38:06.000+0000"
                        }
                    ],
                    "maxResults": 2,
                    "startAt": 0,
                    "total": 2
                },
                "components": [
                    {
                        "description": "issues with indexing code",
                        "id": "12310232",
                        "name": "core/index",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310232"
                    }
                ],
                "created": "2001-11-01T16:08:55.000+0000",
                "customfield_10010": 4568.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-11-01 21:25:58.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_144062778000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "0.0",
                "customfield_12310420": "13744",
                "customfield_12310920": "27714",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "if I do\n\nIndexReader r = IndexReader.open(\"index\");\nTerm t = new Term(\"contents\",\"heidegger\");\nTermEnum terms = r.terms(t);\nout.println(\"zero-term: \"+terms.term().text()+\"<br>\");\nint cnt = 0;\nwhile (terms.next()) {\n\tout.println(\"term: \"+terms.term().text()+\"<br>\");\n\tif (cnt++>5) break;\n}\n\nthen the first term I see in the main loop after terms.next() is \nnot \"heidegger\", even though this is in my index. If I query the enumerator \nBEFORE calling next(), the term is there.\nHowever, the comments in TermEnum.term() says that this method is only valid \nafter the first next() and all other enumerators work that way too.\n\nThe terms(Term) should give back the actual term first, just as it says it \ndoes, right?\n\nThe enumerator skips over the first term if I search for a non-existing term \nlike \"heidegge\" as well.\n\nThis means that a PrefixQuery will not work as expected since it uses this \nenumerator, right?",
                "duedate": null,
                "environment": "Operating System: All\nPlatform: PC",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/major.png",
                    "id": "3",
                    "name": "Major",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/3"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Anne Veling",
                    "emailAddress": "anne@veling.nl",
                    "name": "anne@veling.nl",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=anne%40veling.nl"
                },
                "resolution": {
                    "description": "A fix for this issue is checked into the tree and tested.",
                    "id": "1",
                    "name": "Fixed",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/1"
                },
                "resolutiondate": "2006-05-27T01:35:13.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "new IndexReader.terms(myterm) skips over first term",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:01:12.000+0000",
                "versions": [
                    {
                        "archived": true,
                        "description": "First Apache release",
                        "id": "12310284",
                        "name": "1.2",
                        "releaseDate": "2002-06-13",
                        "released": true,
                        "self": "https://issues.apache.org/jira/rest/api/2/version/12310284"
                    }
                ],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-6/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-6/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314156",
            "key": "LUCENE-6",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314156"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Lucene Developers",
                    "emailAddress": "noreply@example.com",
                    "name": "java-dev@lucene.apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=java-dev%40lucene.apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "This has been fixed.",
                            "created": "2001-12-04T18:43:26.000+0000",
                            "id": "12320978",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314157/comment/12320978",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-12-04T18:43:26.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Paul Smith",
                                "emailAddress": "psmith@apache.org",
                                "name": "psmith@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=psmith%40apache.org"
                            },
                            "body": "Created an attachment (id=15140)\nSame HPFOF trace, patch applied, but with deeper stack trace\n",
                            "created": "2005-05-24T16:04:11.000+0000",
                            "id": "12320979",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314157/comment/12320979",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Paul Smith",
                                "emailAddress": "psmith@apache.org",
                                "name": "psmith@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=psmith%40apache.org"
                            },
                            "updated": "2005-05-24T16:04:11.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Paul Smith",
                                "emailAddress": "psmith@apache.org",
                                "name": "psmith@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=psmith%40apache.org"
                            },
                            "body": "(From update of attachment 15140)\nooooops!  Attached to wrong bug sorry.\n",
                            "created": "2005-05-24T16:05:36.000+0000",
                            "id": "12320980",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314157/comment/12320980",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Paul Smith",
                                "emailAddress": "psmith@apache.org",
                                "name": "psmith@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=psmith%40apache.org"
                            },
                            "updated": "2005-05-24T16:05:36.000+0000"
                        }
                    ],
                    "maxResults": 3,
                    "startAt": 0,
                    "total": 3
                },
                "components": [
                    {
                        "description": "issues related to examples module",
                        "id": "12310231",
                        "name": "modules/examples",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310231"
                    }
                ],
                "created": "2001-11-08T22:17:51.000+0000",
                "customfield_10010": 4754.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-12-04 18:43:26.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_143435843000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "1.0",
                "customfield_12310420": "13743",
                "customfield_12310920": "27713",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "In the docs it says to run the following example:\n\njava -cp lucene.jar:demo/classes org.apache.lucene.IndexFilesSearchFiles\n\n\n\nshould be instead \n\njava -cp lucene.jar:demo/classes org.apache.lucene.SearchFiles",
                "duedate": null,
                "environment": "Operating System: other\nPlatform: Other",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/minor.png",
                    "id": "4",
                    "name": "Minor",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/4"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Dror Matalon",
                    "emailAddress": "dror@matal.com",
                    "name": "dror@matal.com",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=dror%40matal.com"
                },
                "resolution": {
                    "description": "A fix for this issue is checked into the tree and tested.",
                    "id": "1",
                    "name": "Fixed",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/1"
                },
                "resolutiondate": "2006-05-27T01:35:14.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "Documentation error example",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:01:10.000+0000",
                "versions": [
                    {
                        "archived": true,
                        "description": "First Apache release",
                        "id": "12310284",
                        "name": "1.2",
                        "releaseDate": "2002-06-13",
                        "released": true,
                        "self": "https://issues.apache.org/jira/rest/api/2/version/12310284"
                    }
                ],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-7/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-7/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314157",
            "key": "LUCENE-7",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314157"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Lucene Developers",
                    "emailAddress": "noreply@example.com",
                    "name": "java-dev@lucene.apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=java-dev%40lucene.apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "body": "These ParseException classes are generated by JavaCC and cannot be renamed.  If \nwe put all JavaCC-generated grammars in a single package then they would share \na single implementation of ParseException, but that does not seem worthwhile.  \nSo long as we use JavaCC in both the lucene.queryParser and \nlucene.analysis.standard packages there will be two exceptions named \nParseException.  Sorry.\n",
                            "created": "2001-12-07T17:16:30.000+0000",
                            "id": "12320981",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314158/comment/12320981",
                            "updateAuthor": {
                                "active": false,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10453",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10453"
                                },
                                "displayName": "cutting@apache.org",
                                "name": "cutting@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=cutting%40apache.org"
                            },
                            "updated": "2001-12-07T17:16:30.000+0000"
                        }
                    ],
                    "maxResults": 1,
                    "startAt": 0,
                    "total": 1
                },
                "components": [
                    {
                        "description": "issues with QueryParser code under core",
                        "id": "12310234",
                        "name": "core/queryparser",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310234"
                    }
                ],
                "created": "2001-12-07T13:01:21.000+0000",
                "customfield_10010": 5313.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-12-07 17:16:30.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_140963633000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "0.0",
                "customfield_12310420": "13742",
                "customfield_12310920": "27712",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "Is it good that two exceptions in different packages has equal names ???\n\n\"SearchRAM.java\": Error #: 304 : reference to ParseException is ambiguous; both \nclass org.apache.lucene.queryParser.ParseException in package \norg.apache.lucene.queryParser and class \norg.apache.lucene.analysis.standard.ParseException in package \norg.apache.lucene.analysis.standard match at line 186, column 13\n\nI don't want to write long name like here:\n}catch( org.apache.lucene.queryParser.ParseException e ){\n\n- it's not a good style.\n\nThank you !",
                "duedate": null,
                "environment": "Operating System: All\nPlatform: PC",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/major.png",
                    "id": "3",
                    "name": "Major",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/3"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Serge A. Redchuk",
                    "emailAddress": "bitl@mail.ru",
                    "name": "bitl@mail.ru",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=bitl%40mail.ru"
                },
                "resolution": {
                    "description": "The problem described is an issue which will never be fixed.",
                    "id": "2",
                    "name": "Won't Fix",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/2"
                },
                "resolutiondate": "2006-05-27T01:35:14.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "reference to ParseException is ambiguous",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:03:16.000+0000",
                "versions": [],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-8/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-8/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314158",
            "key": "LUCENE-8",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314158"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Lucene Developers",
                    "emailAddress": "noreply@example.com",
                    "name": "java-dev@lucene.apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=java-dev%40lucene.apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "body": "Lucene does not support standalone NOT queries and this is a feature, not a bug.\nc.f. http://marc.theaimsgroup.com/?l=lucene-user&w=2&r=1&s=negation&q=b",
                            "created": "2001-12-17T16:38:18.000+0000",
                            "id": "12320982",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314159/comment/12320982",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "updated": "2001-12-17T16:38:18.000+0000"
                        }
                    ],
                    "maxResults": 1,
                    "startAt": 0,
                    "total": 1
                },
                "components": [
                    {
                        "description": "issues with QueryParser code under core",
                        "id": "12310234",
                        "name": "core/queryparser",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310234"
                    }
                ],
                "created": "2001-12-17T13:57:36.000+0000",
                "customfield_10010": 5456.0,
                "customfield_12310120": null,
                "customfield_12310220": "2001-12-17 16:38:18.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_140096259000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "0.0",
                "customfield_12310420": "13741",
                "customfield_12310920": "27711",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "I think there's \"ideo-logic\" error in QueryParser:\n  (and in BooleanQuery!)\n\n  when I search for smth. like \"love OR NOT onion\"\n  I receive the same result as I search for \"love AND NOT onion\".\n  IMHO it's wrong.\n\n  Let we have 4 docs:\n  doc1: \"Love is life\"\n  doc2: \"Java is pretty nice language\"\n  doc3: \"C++ is powerful, but unsafe\"\n  doc4: \"Onion and love sometimes are not compatoble\"\n\n  So, if search for \"love OR NOT onion\"\n  result must be: doc1, doc2, doc3.\n  (_everything_ where the word \"onion\" isn't present, because we say \"OR\")\n\n  but, we have the same result as in case of search for:\n  \"love AND NOT onion\":\n  result: doc1.\n\n  \n  So, I have created own parser, using BooleanQuery, that would help\n  me, but unfortunatelly it wouldn't.\n\n  Please ! Fix it ASAYK !",
                "duedate": null,
                "environment": "Operating System: All\nPlatform: PC",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/critical.png",
                    "id": "2",
                    "name": "Critical",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/2"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Serge A. Redchuk",
                    "emailAddress": "bitl@mail.ru",
                    "name": "bitl@mail.ru",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=bitl%40mail.ru"
                },
                "resolution": {
                    "description": "The problem is not completely described.",
                    "id": "4",
                    "name": "Incomplete",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/4"
                },
                "resolutiondate": "2006-05-27T01:35:15.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "logic error in QueryParser and in BooleanQuery !",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:01:12.000+0000",
                "versions": [
                    {
                        "archived": true,
                        "description": "First Apache release",
                        "id": "12310284",
                        "name": "1.2",
                        "releaseDate": "2002-06-13",
                        "released": true,
                        "self": "https://issues.apache.org/jira/rest/api/2/version/12310284"
                    }
                ],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-9/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-9/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314159",
            "key": "LUCENE-9",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314159"
        },
        {
            "expand": "editmeta,renderedFields,transitions,changelog,operations",
            "fields": {
                "aggregateprogress": {
                    "progress": 0,
                    "total": 0
                },
                "aggregatetimeestimate": null,
                "aggregatetimeoriginalestimate": null,
                "aggregatetimespent": null,
                "assignee": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Brian Goetz",
                    "emailAddress": "briangoetz@apache.org",
                    "name": "briangoetz@apache.org",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=briangoetz%40apache.org"
                },
                "comment": {
                    "comments": [
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Daniel Rall",
                                "emailAddress": "dlr@finemaltcoding.com",
                                "name": "dlr@finemaltcoding.com",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=dlr%40finemaltcoding.com"
                            },
                            "body": "QueryParser should allow a method of escaping the colon character, preferably\nusing the backspace character in the position before it.  I assume this consists\nof modifying the JavaCC grammar to take escaping into account.\n",
                            "created": "2002-01-29T05:17:07.000+0000",
                            "id": "12320983",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314160/comment/12320983",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Daniel Rall",
                                "emailAddress": "dlr@finemaltcoding.com",
                                "name": "dlr@finemaltcoding.com",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=dlr%40finemaltcoding.com"
                            },
                            "updated": "2002-01-29T05:17:07.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Brian Goetz",
                                "emailAddress": "briangoetz@apache.org",
                                "name": "briangoetz@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=briangoetz%40apache.org"
                            },
                            "body": "I'll add a mechanism for escaping all the special characters.  ",
                            "created": "2002-01-29T07:57:26.000+0000",
                            "id": "12320984",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314160/comment/12320984",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Brian Goetz",
                                "emailAddress": "briangoetz@apache.org",
                                "name": "briangoetz@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=briangoetz%40apache.org"
                            },
                            "updated": "2002-01-29T07:57:26.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Daniel Rall",
                                "emailAddress": "dlr@finemaltcoding.com",
                                "name": "dlr@finemaltcoding.com",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=dlr%40finemaltcoding.com"
                            },
                            "body": "Any word on this?  If no one has time to look into it, I'd be willing to take a\nlook if someone will point me in the right direction.  Brian?\n",
                            "created": "2002-05-07T01:25:53.000+0000",
                            "id": "12320985",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314160/comment/12320985",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Daniel Rall",
                                "emailAddress": "dlr@finemaltcoding.com",
                                "name": "dlr@finemaltcoding.com",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=dlr%40finemaltcoding.com"
                            },
                            "updated": "2002-05-07T01:25:53.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Brian Goetz",
                                "emailAddress": "briangoetz@apache.org",
                                "name": "briangoetz@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=briangoetz%40apache.org"
                            },
                            "body": "I think we were hung up on assigning an escape character.  \\ was preferred by \nthe unix-types, but the windows-types felt this would conflict with DOS path \nnames.  \n\nBut I guess \\ is OK.  Will do.",
                            "created": "2002-05-07T04:46:26.000+0000",
                            "id": "12320986",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314160/comment/12320986",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Brian Goetz",
                                "emailAddress": "briangoetz@apache.org",
                                "name": "briangoetz@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=briangoetz%40apache.org"
                            },
                            "updated": "2002-05-07T04:46:26.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "body": "I think this has been fixed, and the escape character added, although it looks\nlike there are either some problems with it, or it is not clear how the escape\ncharacter should be used.\nC.f. bug 12950 and bug 12444.\n",
                            "created": "2002-10-31T01:11:10.000+0000",
                            "id": "12320987",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314160/comment/12320987",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "updated": "2002-10-31T01:11:10.000+0000"
                        },
                        {
                            "author": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "body": "It looks like the escape character works fine, and the key is to use an Analyzer\nthat will not throw it out.  StandardAnalyzer does this, but WhitespaceAnalyzer\ndoes not.  One can write a custom Analyzer if WhitespaceAnalyzer does not meet\nall the application requirements.\n\nWow, 1 year old bug.\n",
                            "created": "2003-01-05T00:49:08.000+0000",
                            "id": "12320988",
                            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314160/comment/12320988",
                            "updateAuthor": {
                                "active": true,
                                "avatarUrls": {
                                    "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                                    "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                                },
                                "displayName": "Otis Gospodnetic",
                                "emailAddress": "otis@apache.org",
                                "name": "otis@apache.org",
                                "self": "https://issues.apache.org/jira/rest/api/2/user?username=otis%40apache.org"
                            },
                            "updated": "2003-01-05T00:49:08.000+0000"
                        }
                    ],
                    "maxResults": 6,
                    "startAt": 0,
                    "total": 6
                },
                "components": [
                    {
                        "description": "issues with QueryParser code under core",
                        "id": "12310234",
                        "name": "core/queryparser",
                        "self": "https://issues.apache.org/jira/rest/api/2/component/12310234"
                    }
                ],
                "created": "2002-01-29T05:13:45.000+0000",
                "customfield_10010": 6078.0,
                "customfield_12310120": null,
                "customfield_12310220": "2002-01-29 07:57:26.0",
                "customfield_12310222": "6_*:*_1_*:*_0_*|*_5_*:*_1_*:*_136412490000",
                "customfield_12310290": null,
                "customfield_12310291": null,
                "customfield_12310300": null,
                "customfield_12310310": "0.0",
                "customfield_12310420": "13740",
                "customfield_12310920": "27710",
                "customfield_12310921": null,
                "customfield_12311120": null,
                "description": "org.apache.lucene.queryParser.QueryParser does not allow the colon character to\nbe included in search text.  When I don't filter colon characters from user\ninput in Eyebrowse's SearchList servlet, I get the following exception when\nseraching for the text \"10:\" (minus the quotes):\n\norg.apache.lucene.queryParser.ParseException: Encountered \"<EOF>\" at line 1,\ncolumn 3.\nWas expecting one of:\n    \"(\" ...\n    <QUOTED> ...\n    <NUMBER> ...\n    <TERM> ...\n    <WILDTERM> ...\n    <RANGEIN> ...\n    <RANGEEX> ...\n\n        at\norg.apache.lucene.queryParser.QueryParser.generateParseException(Unknown Source)\n        at org.apache.lucene.queryParser.QueryParser.jj_consume_token(Unknown\nSource)\n        at org.apache.lucene.queryParser.QueryParser.Clause(Unknown Source)\n        at org.apache.lucene.queryParser.QueryParser.Query(Unknown Source)\n        at org.apache.lucene.queryParser.QueryParser.parse(Unknown Source)\n        at org.apache.lucene.queryParser.QueryParser.parse(Unknown Source)\n        at org.tigris.eyebrowse.LuceneIndexer.search(LuceneIndexer.java:207)\n        at org.tigris.eyebrowse.core.SearchList.core(SearchList.java:138)",
                "duedate": null,
                "environment": "Operating System: All\nPlatform: All",
                "fixVersions": [],
                "issuelinks": [],
                "issuetype": {
                    "description": "A problem which impairs or prevents the functions of the product.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/issuetypes/bug.png",
                    "id": "1",
                    "name": "Bug",
                    "self": "https://issues.apache.org/jira/rest/api/2/issuetype/1",
                    "subtask": false
                },
                "labels": [],
                "lastViewed": null,
                "priority": {
                    "iconUrl": "https://issues.apache.org/jira/images/icons/priorities/major.png",
                    "id": "3",
                    "name": "Major",
                    "self": "https://issues.apache.org/jira/rest/api/2/priority/3"
                },
                "progress": {
                    "progress": 0,
                    "total": 0
                },
                "project": {
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/projectavatar?size=small&pid=12310110&avatarId=10061",
                        "48x48": "https://issues.apache.org/jira/secure/projectavatar?pid=12310110&avatarId=10061"
                    },
                    "id": "12310110",
                    "key": "LUCENE",
                    "name": "Lucene - Core",
                    "self": "https://issues.apache.org/jira/rest/api/2/project/LUCENE"
                },
                "reporter": {
                    "active": true,
                    "avatarUrls": {
                        "16x16": "https://issues.apache.org/jira/secure/useravatar?size=small&avatarId=10452",
                        "48x48": "https://issues.apache.org/jira/secure/useravatar?avatarId=10452"
                    },
                    "displayName": "Daniel Rall",
                    "emailAddress": "dlr@finemaltcoding.com",
                    "name": "dlr@finemaltcoding.com",
                    "self": "https://issues.apache.org/jira/rest/api/2/user?username=dlr%40finemaltcoding.com"
                },
                "resolution": {
                    "description": "A fix for this issue is checked into the tree and tested.",
                    "id": "1",
                    "name": "Fixed",
                    "self": "https://issues.apache.org/jira/rest/api/2/resolution/1"
                },
                "resolutiondate": "2006-05-27T01:35:15.000+0000",
                "status": {
                    "description": "The issue is considered finished, the resolution is correct. Issues which are closed can be reopened.",
                    "iconUrl": "https://issues.apache.org/jira/images/icons/statuses/closed.png",
                    "id": "6",
                    "name": "Closed",
                    "self": "https://issues.apache.org/jira/rest/api/2/status/6"
                },
                "subtasks": [],
                "summary": "Colon character not searchable by QueryParser",
                "timeestimate": null,
                "timeoriginalestimate": null,
                "timespent": null,
                "timetracking": {},
                "updated": "2011-06-02T22:03:35.000+0000",
                "versions": [],
                "votes": {
                    "hasVoted": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-10/votes",
                    "votes": 0
                },
                "watches": {
                    "isWatching": false,
                    "self": "https://issues.apache.org/jira/rest/api/2/issue/LUCENE-10/watchers",
                    "watchCount": 0
                },
                "worklog": {
                    "maxResults": 0,
                    "startAt": 0,
                    "total": 0,
                    "worklogs": []
                },
                "workratio": -1
            },
            "id": "12314160",
            "key": "LUCENE-10",
            "self": "https://issues.apache.org/jira/rest/api/2/issue/12314160"
        }
    ],
    "maxResults": 10,
    "startAt": 0,
    "total": 4918
}
"""
