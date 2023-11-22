import os
import json
import datetime
import requests
import sys
import pickle
import time
import local_db
from localconstants import DB_PATH, GITHUB_API_TOKEN, ROOT_STATE_PATH

# TODO
#   - should we bother loading all reactions to each comment!?
#   - make histogram of PR age / complexity / engagement

def load_full_issue(issue):
    comments = local_db.http_load_as_json(issue['comments_url'] + '?per_page=100')
    # TODO: responses to each comment?
    events = local_db.http_load_as_json(issue['events_url'] + '?per_page=100')
    # print(f'load events for {issue["number"]}:\n  {json.dumps(events, indent=2)}')
    reactions = local_db.http_load_as_json(issue['reactions']['url'] + '?per_page=100')
    timeline = local_db.http_load_as_json(issue['timeline_url'] + '?per_page=100')
    return comments, events, reactions, timeline

def main():
    c = db.cursor()
    start_time_sec = time.time()
    row = c.execute('SELECT pickle FROM issues WHERE key="page_upto"').fetchone()
    page = pickle.loads(row[0])
    print(f'Starting from page {page}')

    while True:
        count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]
        print(f'\n\n{time.time() - start_time_sec:.1f}s: {count-2} issues in DB; page={page}')
        batch = local_db.http_load_as_json(f'https://api.github.com/repos/apache/lucene/issues?state=all&per_page=20&direction=asc&page={page}')
        for issue in batch:
            print(f'  load issue {issue["number"]}')
            # GitHub response is denormalized -- we must load a few more URLs to get all content:
            comments, events, reactions, timeline = load_full_issue(issue)

            local_db.maybe_load_user(c, issue['user']['login'])
            for comment in comments:
                local_db.maybe_load_user(c, comment['user']['login'])
            for change in events:
                local_db.maybe_load_user(c, change['actor']['login'])
            for change in timeline:
                if 'actor' in change:
                    local_db.maybe_load_user(c, change['actor']['login'])
                elif 'user' in change:
                    local_db.maybe_load_user(c, change['user']['login'])
                elif change['event'] != 'committed':
                    # curiously, there is no user login when a commit timeline event happens:
                    raise RuntimeError(f'unhandled timeline change:\n{json.dumps(change, indent=2)}')

            c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)',
                      (str(issue['number']), pickle.dumps((issue, comments, events, reactions, timeline))))
            
        page += 1
        c.execute('INSERT OR REPLACE INTO issues (key, pickle) VALUES (?, ?)', ('page_upto', pickle.dumps(page)))
        db.commit()

        # done!
        if not batch['incomplete_results']:
          break

    print(json.dumps(comments, indent=2))

def create_db():
    print('Now create DB!')
    c = db.cursor()
    c.execute('CREATE TABLE issues (key TEXT UNIQUE PRIMARY KEY, pickle BLOB)')
    c.execute('INSERT INTO issues VALUES (?, ?)', ('last_update', pickle.dumps(datetime.datetime.utcnow())))
    c.execute('INSERT INTO issues VALUES (?, ?)', ('page_upto', pickle.dumps(1)))

    c.execute('CREATE TABLE users (login TEXT UNIQUE PRIMARY KEY, pickle BLOB)')
    db.commit()

if __name__ == '__main__':
    global db

    do_create = '-create' in sys.argv
    if do_create:
        sys.argv.remove('-create')
        if os.path.exists(DB_PATH):
            raise RuntimeError(f'please first remove DB {DB_PATH} with -create')

    db = local_db.get()

    if do_create:
       create_db()
    main()


# example:
'''
[{
    "id": 1,
    "node_id": "MDU6SXNzdWUx",
    "url": "https://api.github.com/repos/octocat/Hello-World/issues/1347",
    "repository_url": "https://api.github.com/repos/octocat/Hello-World",
    "labels_url": "https://api.github.com/repos/octocat/Hello-World/issues/1347/labels{/name}",
    "comments_url": "https://api.github.com/repos/octocat/Hello-World/issues/1347/comments",
    "events_url": "https://api.github.com/repos/octocat/Hello-World/issues/1347/events",
    "html_url": "https://github.com/octocat/Hello-World/issues/1347",
    "number": 1347,
    "state": "open",
    "title": "Found a bug",
    "body": "I'm having a problem with this.",
    "user": {
      "login": "octocat",
      "id": 1,
      "node_id": "MDQ6VXNlcjE=",
      "avatar_url": "https://github.com/images/error/octocat_happy.gif",
      "gravatar_id": "",
      "url": "https://api.github.com/users/octocat",
      "html_url": "https://github.com/octocat",
      "followers_url": "https://api.github.com/users/octocat/followers",
      "following_url": "https://api.github.com/users/octocat/following{/other_user}",
      "gists_url": "https://api.github.com/users/octocat/gists{/gist_id}",
      "starred_url": "https://api.github.com/users/octocat/starred{/owner}{/repo}",
      "subscriptions_url": "https://api.github.com/users/octocat/subscriptions",
      "organizations_url": "https://api.github.com/users/octocat/orgs",
      "repos_url": "https://api.github.com/users/octocat/repos",
      "events_url": "https://api.github.com/users/octocat/events{/privacy}",
      "received_events_url": "https://api.github.com/users/octocat/received_events",
      "type": "User",
      "site_admin": false
    },
    "labels": [
      {
        "id": 208045946,
        "node_id": "MDU6TGFiZWwyMDgwNDU5NDY=",
        "url": "https://api.github.com/repos/octocat/Hello-World/labels/bug",
        "name": "bug",
        "description": "Something isn't working",
        "color": "f29513",
        "default": true
      }
    ],
    "assignee": {
      "login": "octocat",
      "id": 1,
      "node_id": "MDQ6VXNlcjE=",
      "avatar_url": "https://github.com/images/error/octocat_happy.gif",
      "gravatar_id": "",
      "url": "https://api.github.com/users/octocat",
      "html_url": "https://github.com/octocat",
      "followers_url": "https://api.github.com/users/octocat/followers",
      "following_url": "https://api.github.com/users/octocat/following{/other_user}",
      "gists_url": "https://api.github.com/users/octocat/gists{/gist_id}",
      "starred_url": "https://api.github.com/users/octocat/starred{/owner}{/repo}",
      "subscriptions_url": "https://api.github.com/users/octocat/subscriptions",
      "organizations_url": "https://api.github.com/users/octocat/orgs",
      "repos_url": "https://api.github.com/users/octocat/repos",
      "events_url": "https://api.github.com/users/octocat/events{/privacy}",
      "received_events_url": "https://api.github.com/users/octocat/received_events",
      "type": "User",
      "site_admin": false
    },
    "assignees": [
      {
        "login": "octocat",
        "id": 1,
        "node_id": "MDQ6VXNlcjE=",
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "",
        "url": "https://api.github.com/users/octocat",
        "html_url": "https://github.com/octocat",
        "followers_url": "https://api.github.com/users/octocat/followers",
        "following_url": "https://api.github.com/users/octocat/following{/other_user}",
        "gists_url": "https://api.github.com/users/octocat/gists{/gist_id}",
        "starred_url": "https://api.github.com/users/octocat/starred{/owner}{/repo}",
        "subscriptions_url": "https://api.github.com/users/octocat/subscriptions",
        "organizations_url": "https://api.github.com/users/octocat/orgs",
        "repos_url": "https://api.github.com/users/octocat/repos",
        "events_url": "https://api.github.com/users/octocat/events{/privacy}",
        "received_events_url": "https://api.github.com/users/octocat/received_events",
        "type": "User",
        "site_admin": false
      }
    ],
    "milestone": {
      "url": "https://api.github.com/repos/octocat/Hello-World/milestones/1",
      "html_url": "https://github.com/octocat/Hello-World/milestones/v1.0",
      "labels_url": "https://api.github.com/repos/octocat/Hello-World/milestones/1/labels",
      "id": 1002604,
      "node_id": "MDk6TWlsZXN0b25lMTAwMjYwNA==",
      "number": 1,
      "state": "open",
      "title": "v1.0",
      "description": "Tracking milestone for version 1.0",
      "creator": {
        "login": "octocat",
        "id": 1,
        "node_id": "MDQ6VXNlcjE=",
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "",
        "url": "https://api.github.com/users/octocat",
        "html_url": "https://github.com/octocat",
        "followers_url": "https://api.github.com/users/octocat/followers",
        "following_url": "https://api.github.com/users/octocat/following{/other_user}",
        "gists_url": "https://api.github.com/users/octocat/gists{/gist_id}",
        "starred_url": "https://api.github.com/users/octocat/starred{/owner}{/repo}",
        "subscriptions_url": "https://api.github.com/users/octocat/subscriptions",
        "organizations_url": "https://api.github.com/users/octocat/orgs",
        "repos_url": "https://api.github.com/users/octocat/repos",
        "events_url": "https://api.github.com/users/octocat/events{/privacy}",
        "received_events_url": "https://api.github.com/users/octocat/received_events",
        "type": "User",
        "site_admin": false
      },
      "open_issues": 4,
      "closed_issues": 8,
      "created_at": "2011-04-10T20:09:31Z",
      "updated_at": "2014-03-03T18:58:10Z",
      "closed_at": "2013-02-12T13:22:01Z",
      "due_on": "2012-10-09T23:39:01Z"
    },
    "locked": true,
    "active_lock_reason": "too heated",
    "comments": 0,
    "pull_request": {
      "url": "https://api.github.com/repos/octocat/Hello-World/pulls/1347",
      "html_url": "https://github.com/octocat/Hello-World/pull/1347",
      "diff_url": "https://github.com/octocat/Hello-World/pull/1347.diff",
      "patch_url": "https://github.com/octocat/Hello-World/pull/1347.patch"
    },
    "closed_at": null,
    "created_at": "2011-04-22T13:33:48Z",
    "updated_at": "2011-04-22T13:33:48Z",
    "repository": {
      "id": 1296269,
      "node_id": "MDEwOlJlcG9zaXRvcnkxMjk2MjY5",
      "name": "Hello-World",
      "full_name": "octocat/Hello-World",
      "owner": {
        "login": "octocat",
        "id": 1,
        "node_id": "MDQ6VXNlcjE=",
        "avatar_url": "https://github.com/images/error/octocat_happy.gif",
        "gravatar_id": "",
        "url": "https://api.github.com/users/octocat",
        "html_url": "https://github.com/octocat",
        "followers_url": "https://api.github.com/users/octocat/followers",
        "following_url": "https://api.github.com/users/octocat/following{/other_user}",
        "gists_url": "https://api.github.com/users/octocat/gists{/gist_id}",
        "starred_url": "https://api.github.com/users/octocat/starred{/owner}{/repo}",
        "subscriptions_url": "https://api.github.com/users/octocat/subscriptions",
        "organizations_url": "https://api.github.com/users/octocat/orgs",
        "repos_url": "https://api.github.com/users/octocat/repos",
        "events_url": "https://api.github.com/users/octocat/events{/privacy}",
        "received_events_url": "https://api.github.com/users/octocat/received_events",
        "type": "User",
        "site_admin": false
      },
      "private": false,
      "html_url": "https://github.com/octocat/Hello-World",
      "description": "This your first repo!",
      "fork": false,
      "url": "https://api.github.com/repos/octocat/Hello-World",
      "archive_url": "https://api.github.com/repos/octocat/Hello-World/{archive_format}{/ref}",
      "assignees_url": "https://api.github.com/repos/octocat/Hello-World/assignees{/user}",
      "blobs_url": "https://api.github.com/repos/octocat/Hello-World/git/blobs{/sha}",
      "branches_url": "https://api.github.com/repos/octocat/Hello-World/branches{/branch}",
      "collaborators_url": "https://api.github.com/repos/octocat/Hello-World/collaborators{/collaborator}",
      "comments_url": "https://api.github.com/repos/octocat/Hello-World/comments{/number}",
      "commits_url": "https://api.github.com/repos/octocat/Hello-World/commits{/sha}",
      "compare_url": "https://api.github.com/repos/octocat/Hello-World/compare/{base}...{head}",
      "contents_url": "https://api.github.com/repos/octocat/Hello-World/contents/{+path}",
      "contributors_url": "https://api.github.com/repos/octocat/Hello-World/contributors",
      "deployments_url": "https://api.github.com/repos/octocat/Hello-World/deployments",
      "downloads_url": "https://api.github.com/repos/octocat/Hello-World/downloads",
      "events_url": "https://api.github.com/repos/octocat/Hello-World/events",
      "forks_url": "https://api.github.com/repos/octocat/Hello-World/forks",
      "git_commits_url": "https://api.github.com/repos/octocat/Hello-World/git/commits{/sha}",
      "git_refs_url": "https://api.github.com/repos/octocat/Hello-World/git/refs{/sha}",
      "git_tags_url": "https://api.github.com/repos/octocat/Hello-World/git/tags{/sha}",
      "git_url": "git:github.com/octocat/Hello-World.git",
      "issue_comment_url": "https://api.github.com/repos/octocat/Hello-World/issues/comments{/number}",
      "issue_events_url": "https://api.github.com/repos/octocat/Hello-World/issues/events{/number}",
      "issues_url": "https://api.github.com/repos/octocat/Hello-World/issues{/number}",
      "keys_url": "https://api.github.com/repos/octocat/Hello-World/keys{/key_id}",
      "labels_url": "https://api.github.com/repos/octocat/Hello-World/labels{/name}",
      "languages_url": "https://api.github.com/repos/octocat/Hello-World/languages",
      "merges_url": "https://api.github.com/repos/octocat/Hello-World/merges",
      "milestones_url": "https://api.github.com/repos/octocat/Hello-World/milestones{/number}",
      "notifications_url": "https://api.github.com/repos/octocat/Hello-World/notifications{?since,all,participating}",
      "pulls_url": "https://api.github.com/repos/octocat/Hello-World/pulls{/number}",
      "releases_url": "https://api.github.com/repos/octocat/Hello-World/releases{/id}",
      "ssh_url": "git@github.com:octocat/Hello-World.git",
      "stargazers_url": "https://api.github.com/repos/octocat/Hello-World/stargazers",
      "statuses_url": "https://api.github.com/repos/octocat/Hello-World/statuses/{sha}",
      "subscribers_url": "https://api.github.com/repos/octocat/Hello-World/subscribers",
      "subscription_url": "https://api.github.com/repos/octocat/Hello-World/subscription",
      "tags_url": "https://api.github.com/repos/octocat/Hello-World/tags",
      "teams_url": "https://api.github.com/repos/octocat/Hello-World/teams",
      "trees_url": "https://api.github.com/repos/octocat/Hello-World/git/trees{/sha}",
      "clone_url": "https://github.com/octocat/Hello-World.git",
      "mirror_url": "git:git.example.com/octocat/Hello-World",
      "hooks_url": "https://api.github.com/repos/octocat/Hello-World/hooks",
      "svn_url": "https://svn.github.com/octocat/Hello-World",
      "homepage": "https://github.com",
      "language": null,
      "forks_count": 9,
      "stargazers_count": 80,
      "watchers_count": 80,
      "size": 108,
      "default_branch": "master",
      "open_issues_count": 0,
      "is_template": true,
      "topics": [
        "octocat",
        "atom",
        "electron",
        "api"
      ],
      "has_issues": true,
      "has_projects": true,
      "has_wiki": true,
      "has_pages": false,
      "has_downloads": true,
      "archived": false,
      "disabled": false,
      "visibility": "public",
      "pushed_at": "2011-01-26T19:06:43Z",
      "created_at": "2011-01-26T19:01:12Z",
      "updated_at": "2011-01-26T19:14:43Z",
      "permissions": {
        "admin": false,
        "push": false,
        "pull": true
      },
      "allow_rebase_merge": true,
      "template_repository": null,
      "temp_clone_token": "ABTLWHOULUVAXGTRYU7OC2876QJ2O",
      "allow_squash_merge": true,
      "allow_auto_merge": false,
      "delete_branch_on_merge": true,
      "allow_merge_commit": true,
      "subscribers_count": 42,
      "network_count": 0,
      "license": {
        "key": "mit",
        "name": "MIT License",
        "url": "https://api.github.com/licenses/mit",
        "spdx_id": "MIT",
        "node_id": "MDc6TGljZW5zZW1pdA==",
        "html_url": "https://github.com/licenses/mit"
      },
      "forks": 1,
      "open_issues": 1,
      "watchers": 1
    },
    "author_association": "COLLABORATOR"
  }
]
'''


# schema:
'''
{
  "type": "array",
  "items": {
    "title": "Issue",
    "description": "Issues are a great way to keep track of tasks, enhancements, and bugs for your projects.",
    "type": "object",
    "properties": {
      "id": {
        "type": "integer",
        "format": "int64"
      },
      "node_id": {
        "type": "string"
      },
      "url": {
        "description": "URL for the issue",
        "type": "string",
        "format": "uri",
        "examples": [
          "https://api.github.com/repositories/42/issues/1"
        ]
      },
      "repository_url": {
        "type": "string",
        "format": "uri"
      },
      "labels_url": {
        "type": "string"
      },
      "comments_url": {
        "type": "string",
        "format": "uri"
      },
      "events_url": {
        "type": "string",
        "format": "uri"
      },
      "html_url": {
        "type": "string",
        "format": "uri"
      },
      "number": {
        "description": "Number uniquely identifying the issue within its repository",
        "type": "integer",
        "examples": [
          42
        ]
      },
      "state": {
        "description": "State of the issue; either 'open' or 'closed'",
        "type": "string",
        "examples": [
          "open"
        ]
      },
      "state_reason": {
        "description": "The reason for the current state",
        "type": [
          "string",
          "null"
        ],
        "enum": [
          "completed",
          "reopened",
          "not_planned",
          null
        ],
        "examples": [
          "not_planned"
        ]
      },
      "title": {
        "description": "Title of the issue",
        "type": "string",
        "examples": [
          "Widget creation fails in Safari on OS X 10.8"
        ]
      },
      "body": {
        "description": "Contents of the issue",
        "type": [
          "string",
          "null"
        ],
        "examples": [
          "It looks like the new widget form is broken on Safari. When I try and create the widget, Safari crashes. This is reproducible on 10.8, but not 10.9. Maybe a browser bug?"
        ]
      },
      "user": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          }
        ]
      },
      "labels": {
        "description": "Labels to associate with this issue; pass one or more label names to replace the set of labels on this issue; send an empty array to clear all labels from the issue; note that the labels are silently dropped for users without push access to the repository",
        "type": "array",
        "items": {
          "oneOf": [
            {
              "type": "string"
            },
            {
              "type": "object",
              "properties": {
                "id": {
                  "type": "integer",
                  "format": "int64"
                },
                "node_id": {
                  "type": "string"
                },
                "url": {
                  "type": "string",
                  "format": "uri"
                },
                "name": {
                  "type": "string"
                },
                "description": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "color": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "default": {
                  "type": "boolean"
                }
              }
            }
          ]
        },
        "examples": [
          "bug",
          "registration"
        ]
      },
      "assignee": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          }
        ]
      },
      "assignees": {
        "type": [
          "array",
          "null"
        ],
        "items": {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      },
      "milestone": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Milestone",
            "description": "A collection of related issues and pull requests.",
            "type": "object",
            "properties": {
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/repos/octocat/Hello-World/milestones/1"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat/Hello-World/milestones/v1.0"
                ]
              },
              "labels_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/repos/octocat/Hello-World/milestones/1/labels"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1002604
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDk6TWlsZXN0b25lMTAwMjYwNA=="
                ]
              },
              "number": {
                "description": "The number of the milestone.",
                "type": "integer",
                "examples": [
                  42
                ]
              },
              "state": {
                "description": "The state of the milestone.",
                "type": "string",
                "enum": [
                  "open",
                  "closed"
                ],
                "default": "open",
                "examples": [
                  "open"
                ]
              },
              "title": {
                "description": "The title of the milestone.",
                "type": "string",
                "examples": [
                  "v1.0"
                ]
              },
              "description": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "Tracking milestone for version 1.0"
                ]
              },
              "creator": {
                "anyOf": [
                  {
                    "type": "null"
                  },
                  {
                    "title": "Simple User",
                    "description": "A GitHub user.",
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "email": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "login": {
                        "type": "string",
                        "examples": [
                          "octocat"
                        ]
                      },
                      "id": {
                        "type": "integer",
                        "examples": [
                          1
                        ]
                      },
                      "node_id": {
                        "type": "string",
                        "examples": [
                          "MDQ6VXNlcjE="
                        ]
                      },
                      "avatar_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://github.com/images/error/octocat_happy.gif"
                        ]
                      },
                      "gravatar_id": {
                        "type": [
                          "string",
                          "null"
                        ],
                        "examples": [
                          "41d064eb2195891e12d0413f63227ea7"
                        ]
                      },
                      "url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat"
                        ]
                      },
                      "html_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://github.com/octocat"
                        ]
                      },
                      "followers_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/followers"
                        ]
                      },
                      "following_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/following{/other_user}"
                        ]
                      },
                      "gists_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/gists{/gist_id}"
                        ]
                      },
                      "starred_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                        ]
                      },
                      "subscriptions_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/subscriptions"
                        ]
                      },
                      "organizations_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/orgs"
                        ]
                      },
                      "repos_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/repos"
                        ]
                      },
                      "events_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/events{/privacy}"
                        ]
                      },
                      "received_events_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/received_events"
                        ]
                      },
                      "type": {
                        "type": "string",
                        "examples": [
                          "User"
                        ]
                      },
                      "site_admin": {
                        "type": "boolean"
                      },
                      "starred_at": {
                        "type": "string",
                        "examples": [
                          "\"2020-07-09T00:17:55Z\""
                        ]
                      }
                    },
                    "required": [
                      "avatar_url",
                      "events_url",
                      "followers_url",
                      "following_url",
                      "gists_url",
                      "gravatar_id",
                      "html_url",
                      "id",
                      "node_id",
                      "login",
                      "organizations_url",
                      "received_events_url",
                      "repos_url",
                      "site_admin",
                      "starred_url",
                      "subscriptions_url",
                      "type",
                      "url"
                    ]
                  }
                ]
              },
              "open_issues": {
                "type": "integer",
                "examples": [
                  4
                ]
              },
              "closed_issues": {
                "type": "integer",
                "examples": [
                  8
                ]
              },
              "created_at": {
                "type": "string",
                "format": "date-time",
                "examples": [
                  "2011-04-10T20:09:31Z"
                ]
              },
              "updated_at": {
                "type": "string",
                "format": "date-time",
                "examples": [
                  "2014-03-03T18:58:10Z"
                ]
              },
              "closed_at": {
                "type": [
                  "string",
                  "null"
                ],
                "format": "date-time",
                "examples": [
                  "2013-02-12T13:22:01Z"
                ]
              },
              "due_on": {
                "type": [
                  "string",
                  "null"
                ],
                "format": "date-time",
                "examples": [
                  "2012-10-09T23:39:01Z"
                ]
              }
            },
            "required": [
              "closed_issues",
              "creator",
              "description",
              "due_on",
              "closed_at",
              "id",
              "node_id",
              "labels_url",
              "html_url",
              "number",
              "open_issues",
              "state",
              "title",
              "url",
              "created_at",
              "updated_at"
            ]
          }
        ]
      },
      "locked": {
        "type": "boolean"
      },
      "active_lock_reason": {
        "type": [
          "string",
          "null"
        ]
      },
      "comments": {
        "type": "integer"
      },
      "pull_request": {
        "type": "object",
        "properties": {
          "merged_at": {
            "type": [
              "string",
              "null"
            ],
            "format": "date-time"
          },
          "diff_url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri"
          },
          "html_url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri"
          },
          "patch_url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri"
          },
          "url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri"
          }
        },
        "required": [
          "diff_url",
          "html_url",
          "patch_url",
          "url"
        ]
      },
      "closed_at": {
        "type": [
          "string",
          "null"
        ],
        "format": "date-time"
      },
      "created_at": {
        "type": "string",
        "format": "date-time"
      },
      "updated_at": {
        "type": "string",
        "format": "date-time"
      },
      "draft": {
        "type": "boolean"
      },
      "closed_by": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          }
        ]
      },
      "body_html": {
        "type": "string"
      },
      "body_text": {
        "type": "string"
      },
      "timeline_url": {
        "type": "string",
        "format": "uri"
      },
      "repository": {
        "title": "Repository",
        "description": "A repository on GitHub.",
        "type": "object",
        "properties": {
          "id": {
            "description": "Unique identifier of the repository",
            "type": "integer",
            "examples": [
              42
            ]
          },
          "node_id": {
            "type": "string",
            "examples": [
              "MDEwOlJlcG9zaXRvcnkxMjk2MjY5"
            ]
          },
          "name": {
            "description": "The name of the repository.",
            "type": "string",
            "examples": [
              "Team Environment"
            ]
          },
          "full_name": {
            "type": "string",
            "examples": [
              "octocat/Hello-World"
            ]
          },
          "license": {
            "anyOf": [
              {
                "type": "null"
              },
              {
                "title": "License Simple",
                "description": "License Simple",
                "type": "object",
                "properties": {
                  "key": {
                    "type": "string",
                    "examples": [
                      "mit"
                    ]
                  },
                  "name": {
                    "type": "string",
                    "examples": [
                      "MIT License"
                    ]
                  },
                  "url": {
                    "type": [
                      "string",
                      "null"
                    ],
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/licenses/mit"
                    ]
                  },
                  "spdx_id": {
                    "type": [
                      "string",
                      "null"
                    ],
                    "examples": [
                      "MIT"
                    ]
                  },
                  "node_id": {
                    "type": "string",
                    "examples": [
                      "MDc6TGljZW5zZW1pdA=="
                    ]
                  },
                  "html_url": {
                    "type": "string",
                    "format": "uri"
                  }
                },
                "required": [
                  "key",
                  "name",
                  "url",
                  "spdx_id",
                  "node_id"
                ]
              }
            ]
          },
          "organization": {
            "anyOf": [
              {
                "type": "null"
              },
              {
                "title": "Simple User",
                "description": "A GitHub user.",
                "type": "object",
                "properties": {
                  "name": {
                    "type": [
                      "string",
                      "null"
                    ]
                  },
                  "email": {
                    "type": [
                      "string",
                      "null"
                    ]
                  },
                  "login": {
                    "type": "string",
                    "examples": [
                      "octocat"
                    ]
                  },
                  "id": {
                    "type": "integer",
                    "examples": [
                      1
                    ]
                  },
                  "node_id": {
                    "type": "string",
                    "examples": [
                      "MDQ6VXNlcjE="
                    ]
                  },
                  "avatar_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://github.com/images/error/octocat_happy.gif"
                    ]
                  },
                  "gravatar_id": {
                    "type": [
                      "string",
                      "null"
                    ],
                    "examples": [
                      "41d064eb2195891e12d0413f63227ea7"
                    ]
                  },
                  "url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat"
                    ]
                  },
                  "html_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://github.com/octocat"
                    ]
                  },
                  "followers_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/followers"
                    ]
                  },
                  "following_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/following{/other_user}"
                    ]
                  },
                  "gists_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/gists{/gist_id}"
                    ]
                  },
                  "starred_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                    ]
                  },
                  "subscriptions_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/subscriptions"
                    ]
                  },
                  "organizations_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/orgs"
                    ]
                  },
                  "repos_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/repos"
                    ]
                  },
                  "events_url": {
                    "type": "string",
                    "examples": [
                      "https://api.github.com/users/octocat/events{/privacy}"
                    ]
                  },
                  "received_events_url": {
                    "type": "string",
                    "format": "uri",
                    "examples": [
                      "https://api.github.com/users/octocat/received_events"
                    ]
                  },
                  "type": {
                    "type": "string",
                    "examples": [
                      "User"
                    ]
                  },
                  "site_admin": {
                    "type": "boolean"
                  },
                  "starred_at": {
                    "type": "string",
                    "examples": [
                      "\"2020-07-09T00:17:55Z\""
                    ]
                  }
                },
                "required": [
                  "avatar_url",
                  "events_url",
                  "followers_url",
                  "following_url",
                  "gists_url",
                  "gravatar_id",
                  "html_url",
                  "id",
                  "node_id",
                  "login",
                  "organizations_url",
                  "received_events_url",
                  "repos_url",
                  "site_admin",
                  "starred_url",
                  "subscriptions_url",
                  "type",
                  "url"
                ]
              }
            ]
          },
          "forks": {
            "type": "integer"
          },
          "permissions": {
            "type": "object",
            "properties": {
              "admin": {
                "type": "boolean"
              },
              "pull": {
                "type": "boolean"
              },
              "triage": {
                "type": "boolean"
              },
              "push": {
                "type": "boolean"
              },
              "maintain": {
                "type": "boolean"
              }
            },
            "required": [
              "admin",
              "pull",
              "push"
            ]
          },
          "owner": {
            "title": "Simple User",
            "description": "A GitHub user.",
            "type": "object",
            "properties": {
              "name": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "email": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "login": {
                "type": "string",
                "examples": [
                  "octocat"
                ]
              },
              "id": {
                "type": "integer",
                "examples": [
                  1
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDQ6VXNlcjE="
                ]
              },
              "avatar_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/images/error/octocat_happy.gif"
                ]
              },
              "gravatar_id": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "41d064eb2195891e12d0413f63227ea7"
                ]
              },
              "url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/octocat"
                ]
              },
              "followers_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/followers"
                ]
              },
              "following_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/following{/other_user}"
                ]
              },
              "gists_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/gists{/gist_id}"
                ]
              },
              "starred_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                ]
              },
              "subscriptions_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/subscriptions"
                ]
              },
              "organizations_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/orgs"
                ]
              },
              "repos_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/repos"
                ]
              },
              "events_url": {
                "type": "string",
                "examples": [
                  "https://api.github.com/users/octocat/events{/privacy}"
                ]
              },
              "received_events_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://api.github.com/users/octocat/received_events"
                ]
              },
              "type": {
                "type": "string",
                "examples": [
                  "User"
                ]
              },
              "site_admin": {
                "type": "boolean"
              },
              "starred_at": {
                "type": "string",
                "examples": [
                  "\"2020-07-09T00:17:55Z\""
                ]
              }
            },
            "required": [
              "avatar_url",
              "events_url",
              "followers_url",
              "following_url",
              "gists_url",
              "gravatar_id",
              "html_url",
              "id",
              "node_id",
              "login",
              "organizations_url",
              "received_events_url",
              "repos_url",
              "site_admin",
              "starred_url",
              "subscriptions_url",
              "type",
              "url"
            ]
          },
          "private": {
            "description": "Whether the repository is private or public.",
            "default": false,
            "type": "boolean"
          },
          "html_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://github.com/octocat/Hello-World"
            ]
          },
          "description": {
            "type": [
              "string",
              "null"
            ],
            "examples": [
              "This your first repo!"
            ]
          },
          "fork": {
            "type": "boolean"
          },
          "url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://api.github.com/repos/octocat/Hello-World"
            ]
          },
          "archive_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/{archive_format}{/ref}"
            ]
          },
          "assignees_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/assignees{/user}"
            ]
          },
          "blobs_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/blobs{/sha}"
            ]
          },
          "branches_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/branches{/branch}"
            ]
          },
          "collaborators_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/collaborators{/collaborator}"
            ]
          },
          "comments_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/comments{/number}"
            ]
          },
          "commits_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/commits{/sha}"
            ]
          },
          "compare_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/compare/{base}...{head}"
            ]
          },
          "contents_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/contents/{+path}"
            ]
          },
          "contributors_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/contributors"
            ]
          },
          "deployments_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/deployments"
            ]
          },
          "downloads_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/downloads"
            ]
          },
          "events_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/events"
            ]
          },
          "forks_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/forks"
            ]
          },
          "git_commits_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/commits{/sha}"
            ]
          },
          "git_refs_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/refs{/sha}"
            ]
          },
          "git_tags_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/tags{/sha}"
            ]
          },
          "git_url": {
            "type": "string",
            "examples": [
              "git:github.com/octocat/Hello-World.git"
            ]
          },
          "issue_comment_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/issues/comments{/number}"
            ]
          },
          "issue_events_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/issues/events{/number}"
            ]
          },
          "issues_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/issues{/number}"
            ]
          },
          "keys_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/keys{/key_id}"
            ]
          },
          "labels_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/labels{/name}"
            ]
          },
          "languages_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/languages"
            ]
          },
          "merges_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/merges"
            ]
          },
          "milestones_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/milestones{/number}"
            ]
          },
          "notifications_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/notifications{?since,all,participating}"
            ]
          },
          "pulls_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/pulls{/number}"
            ]
          },
          "releases_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/releases{/id}"
            ]
          },
          "ssh_url": {
            "type": "string",
            "examples": [
              "git@github.com:octocat/Hello-World.git"
            ]
          },
          "stargazers_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/stargazers"
            ]
          },
          "statuses_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/statuses/{sha}"
            ]
          },
          "subscribers_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/subscribers"
            ]
          },
          "subscription_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/subscription"
            ]
          },
          "tags_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/tags"
            ]
          },
          "teams_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/teams"
            ]
          },
          "trees_url": {
            "type": "string",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/git/trees{/sha}"
            ]
          },
          "clone_url": {
            "type": "string",
            "examples": [
              "https://github.com/octocat/Hello-World.git"
            ]
          },
          "mirror_url": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri",
            "examples": [
              "git:git.example.com/octocat/Hello-World"
            ]
          },
          "hooks_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "http://api.github.com/repos/octocat/Hello-World/hooks"
            ]
          },
          "svn_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://svn.github.com/octocat/Hello-World"
            ]
          },
          "homepage": {
            "type": [
              "string",
              "null"
            ],
            "format": "uri",
            "examples": [
              "https://github.com"
            ]
          },
          "language": {
            "type": [
              "string",
              "null"
            ]
          },
          "forks_count": {
            "type": "integer",
            "examples": [
              9
            ]
          },
          "stargazers_count": {
            "type": "integer",
            "examples": [
              80
            ]
          },
          "watchers_count": {
            "type": "integer",
            "examples": [
              80
            ]
          },
          "size": {
            "description": "The size of the repository. Size is calculated hourly. When a repository is initially created, the size is 0.",
            "type": "integer",
            "examples": [
              108
            ]
          },
          "default_branch": {
            "description": "The default branch of the repository.",
            "type": "string",
            "examples": [
              "master"
            ]
          },
          "open_issues_count": {
            "type": "integer",
            "examples": [
              0
            ]
          },
          "is_template": {
            "description": "Whether this repository acts as a template that can be used to generate new repositories.",
            "default": false,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "topics": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "has_issues": {
            "description": "Whether issues are enabled.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "has_projects": {
            "description": "Whether projects are enabled.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "has_wiki": {
            "description": "Whether the wiki is enabled.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "has_pages": {
            "type": "boolean"
          },
          "has_downloads": {
            "description": "Whether downloads are enabled.",
            "default": true,
            "type": "boolean",
            "deprecated": true,
            "examples": [
              true
            ]
          },
          "has_discussions": {
            "description": "Whether discussions are enabled.",
            "default": false,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "archived": {
            "description": "Whether the repository is archived.",
            "default": false,
            "type": "boolean"
          },
          "disabled": {
            "type": "boolean",
            "description": "Returns whether or not this repository disabled."
          },
          "visibility": {
            "description": "The repository visibility: public, private, or internal.",
            "default": "public",
            "type": "string"
          },
          "pushed_at": {
            "type": [
              "string",
              "null"
            ],
            "format": "date-time",
            "examples": [
              "2011-01-26T19:06:43Z"
            ]
          },
          "created_at": {
            "type": [
              "string",
              "null"
            ],
            "format": "date-time",
            "examples": [
              "2011-01-26T19:01:12Z"
            ]
          },
          "updated_at": {
            "type": [
              "string",
              "null"
            ],
            "format": "date-time",
            "examples": [
              "2011-01-26T19:14:43Z"
            ]
          },
          "allow_rebase_merge": {
            "description": "Whether to allow rebase merges for pull requests.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "template_repository": {
            "type": [
              "object",
              "null"
            ],
            "properties": {
              "id": {
                "type": "integer"
              },
              "node_id": {
                "type": "string"
              },
              "name": {
                "type": "string"
              },
              "full_name": {
                "type": "string"
              },
              "owner": {
                "type": "object",
                "properties": {
                  "login": {
                    "type": "string"
                  },
                  "id": {
                    "type": "integer"
                  },
                  "node_id": {
                    "type": "string"
                  },
                  "avatar_url": {
                    "type": "string"
                  },
                  "gravatar_id": {
                    "type": "string"
                  },
                  "url": {
                    "type": "string"
                  },
                  "html_url": {
                    "type": "string"
                  },
                  "followers_url": {
                    "type": "string"
                  },
                  "following_url": {
                    "type": "string"
                  },
                  "gists_url": {
                    "type": "string"
                  },
                  "starred_url": {
                    "type": "string"
                  },
                  "subscriptions_url": {
                    "type": "string"
                  },
                  "organizations_url": {
                    "type": "string"
                  },
                  "repos_url": {
                    "type": "string"
                  },
                  "events_url": {
                    "type": "string"
                  },
                  "received_events_url": {
                    "type": "string"
                  },
                  "type": {
                    "type": "string"
                  },
                  "site_admin": {
                    "type": "boolean"
                  }
                }
              },
              "private": {
                "type": "boolean"
              },
              "html_url": {
                "type": "string"
              },
              "description": {
                "type": "string"
              },
              "fork": {
                "type": "boolean"
              },
              "url": {
                "type": "string"
              },
              "archive_url": {
                "type": "string"
              },
              "assignees_url": {
                "type": "string"
              },
              "blobs_url": {
                "type": "string"
              },
              "branches_url": {
                "type": "string"
              },
              "collaborators_url": {
                "type": "string"
              },
              "comments_url": {
                "type": "string"
              },
              "commits_url": {
                "type": "string"
              },
              "compare_url": {
                "type": "string"
              },
              "contents_url": {
                "type": "string"
              },
              "contributors_url": {
                "type": "string"
              },
              "deployments_url": {
                "type": "string"
              },
              "downloads_url": {
                "type": "string"
              },
              "events_url": {
                "type": "string"
              },
              "forks_url": {
                "type": "string"
              },
              "git_commits_url": {
                "type": "string"
              },
              "git_refs_url": {
                "type": "string"
              },
              "git_tags_url": {
                "type": "string"
              },
              "git_url": {
                "type": "string"
              },
              "issue_comment_url": {
                "type": "string"
              },
              "issue_events_url": {
                "type": "string"
              },
              "issues_url": {
                "type": "string"
              },
              "keys_url": {
                "type": "string"
              },
              "labels_url": {
                "type": "string"
              },
              "languages_url": {
                "type": "string"
              },
              "merges_url": {
                "type": "string"
              },
              "milestones_url": {
                "type": "string"
              },
              "notifications_url": {
                "type": "string"
              },
              "pulls_url": {
                "type": "string"
              },
              "releases_url": {
                "type": "string"
              },
              "ssh_url": {
                "type": "string"
              },
              "stargazers_url": {
                "type": "string"
              },
              "statuses_url": {
                "type": "string"
              },
              "subscribers_url": {
                "type": "string"
              },
              "subscription_url": {
                "type": "string"
              },
              "tags_url": {
                "type": "string"
              },
              "teams_url": {
                "type": "string"
              },
              "trees_url": {
                "type": "string"
              },
              "clone_url": {
                "type": "string"
              },
              "mirror_url": {
                "type": "string"
              },
              "hooks_url": {
                "type": "string"
              },
              "svn_url": {
                "type": "string"
              },
              "homepage": {
                "type": "string"
              },
              "language": {
                "type": "string"
              },
              "forks_count": {
                "type": "integer"
              },
              "stargazers_count": {
                "type": "integer"
              },
              "watchers_count": {
                "type": "integer"
              },
              "size": {
                "type": "integer"
              },
              "default_branch": {
                "type": "string"
              },
              "open_issues_count": {
                "type": "integer"
              },
              "is_template": {
                "type": "boolean"
              },
              "topics": {
                "type": "array",
                "items": {
                  "type": "string"
                }
              },
              "has_issues": {
                "type": "boolean"
              },
              "has_projects": {
                "type": "boolean"
              },
              "has_wiki": {
                "type": "boolean"
              },
              "has_pages": {
                "type": "boolean"
              },
              "has_downloads": {
                "type": "boolean"
              },
              "archived": {
                "type": "boolean"
              },
              "disabled": {
                "type": "boolean"
              },
              "visibility": {
                "type": "string"
              },
              "pushed_at": {
                "type": "string"
              },
              "created_at": {
                "type": "string"
              },
              "updated_at": {
                "type": "string"
              },
              "permissions": {
                "type": "object",
                "properties": {
                  "admin": {
                    "type": "boolean"
                  },
                  "maintain": {
                    "type": "boolean"
                  },
                  "push": {
                    "type": "boolean"
                  },
                  "triage": {
                    "type": "boolean"
                  },
                  "pull": {
                    "type": "boolean"
                  }
                }
              },
              "allow_rebase_merge": {
                "type": "boolean"
              },
              "temp_clone_token": {
                "type": "string"
              },
              "allow_squash_merge": {
                "type": "boolean"
              },
              "allow_auto_merge": {
                "type": "boolean"
              },
              "delete_branch_on_merge": {
                "type": "boolean"
              },
              "allow_update_branch": {
                "type": "boolean"
              },
              "use_squash_pr_title_as_default": {
                "type": "boolean"
              },
              "squash_merge_commit_title": {
                "type": "string",
                "enum": [
                  "PR_TITLE",
                  "COMMIT_OR_PR_TITLE"
                ],
                "description": "The default value for a squash merge commit title:\n\n- `PR_TITLE` - default to the pull request's title.\n- `COMMIT_OR_PR_TITLE` - default to the commit's title (if only one commit) or the pull request's title (when more than one commit)."
              },
              "squash_merge_commit_message": {
                "type": "string",
                "enum": [
                  "PR_BODY",
                  "COMMIT_MESSAGES",
                  "BLANK"
                ],
                "description": "The default value for a squash merge commit message:\n\n- `PR_BODY` - default to the pull request's body.\n- `COMMIT_MESSAGES` - default to the branch's commit messages.\n- `BLANK` - default to a blank commit message."
              },
              "merge_commit_title": {
                "type": "string",
                "enum": [
                  "PR_TITLE",
                  "MERGE_MESSAGE"
                ],
                "description": "The default value for a merge commit title.\n\n- `PR_TITLE` - default to the pull request's title.\n- `MERGE_MESSAGE` - default to the classic title for a merge message (e.g., Merge pull request #123 from branch-name)."
              },
              "merge_commit_message": {
                "type": "string",
                "enum": [
                  "PR_BODY",
                  "PR_TITLE",
                  "BLANK"
                ],
                "description": "The default value for a merge commit message.\n\n- `PR_TITLE` - default to the pull request's title.\n- `PR_BODY` - default to the pull request's body.\n- `BLANK` - default to a blank commit message."
              },
              "allow_merge_commit": {
                "type": "boolean"
              },
              "subscribers_count": {
                "type": "integer"
              },
              "network_count": {
                "type": "integer"
              }
            }
          },
          "temp_clone_token": {
            "type": "string"
          },
          "allow_squash_merge": {
            "description": "Whether to allow squash merges for pull requests.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "allow_auto_merge": {
            "description": "Whether to allow Auto-merge to be used on pull requests.",
            "default": false,
            "type": "boolean",
            "examples": [
              false
            ]
          },
          "delete_branch_on_merge": {
            "description": "Whether to delete head branches when pull requests are merged",
            "default": false,
            "type": "boolean",
            "examples": [
              false
            ]
          },
          "allow_update_branch": {
            "description": "Whether or not a pull request head branch that is behind its base branch can always be updated even if it is not required to be up to date before merging.",
            "default": false,
            "type": "boolean",
            "examples": [
              false
            ]
          },
          "use_squash_pr_title_as_default": {
            "type": "boolean",
            "description": "Whether a squash merge commit can use the pull request title as default. **This property has been deprecated. Please use `squash_merge_commit_title` instead.",
            "default": false,
            "deprecated": true
          },
          "squash_merge_commit_title": {
            "type": "string",
            "enum": [
              "PR_TITLE",
              "COMMIT_OR_PR_TITLE"
            ],
            "description": "The default value for a squash merge commit title:\n\n- `PR_TITLE` - default to the pull request's title.\n- `COMMIT_OR_PR_TITLE` - default to the commit's title (if only one commit) or the pull request's title (when more than one commit)."
          },
          "squash_merge_commit_message": {
            "type": "string",
            "enum": [
              "PR_BODY",
              "COMMIT_MESSAGES",
              "BLANK"
            ],
            "description": "The default value for a squash merge commit message:\n\n- `PR_BODY` - default to the pull request's body.\n- `COMMIT_MESSAGES` - default to the branch's commit messages.\n- `BLANK` - default to a blank commit message."
          },
          "merge_commit_title": {
            "type": "string",
            "enum": [
              "PR_TITLE",
              "MERGE_MESSAGE"
            ],
            "description": "The default value for a merge commit title.\n\n- `PR_TITLE` - default to the pull request's title.\n- `MERGE_MESSAGE` - default to the classic title for a merge message (e.g., Merge pull request #123 from branch-name)."
          },
          "merge_commit_message": {
            "type": "string",
            "enum": [
              "PR_BODY",
              "PR_TITLE",
              "BLANK"
            ],
            "description": "The default value for a merge commit message.\n\n- `PR_TITLE` - default to the pull request's title.\n- `PR_BODY` - default to the pull request's body.\n- `BLANK` - default to a blank commit message."
          },
          "allow_merge_commit": {
            "description": "Whether to allow merge commits for pull requests.",
            "default": true,
            "type": "boolean",
            "examples": [
              true
            ]
          },
          "allow_forking": {
            "description": "Whether to allow forking this repo",
            "type": "boolean"
          },
          "web_commit_signoff_required": {
            "description": "Whether to require contributors to sign off on web-based commits",
            "default": false,
            "type": "boolean"
          },
          "subscribers_count": {
            "type": "integer"
          },
          "network_count": {
            "type": "integer"
          },
          "open_issues": {
            "type": "integer"
          },
          "watchers": {
            "type": "integer"
          },
          "master_branch": {
            "type": "string"
          },
          "starred_at": {
            "type": "string",
            "examples": [
              "\"2020-07-09T00:17:42Z\""
            ]
          },
          "anonymous_access_enabled": {
            "type": "boolean",
            "description": "Whether anonymous git access is enabled for this repository"
          }
        },
        "required": [
          "archive_url",
          "assignees_url",
          "blobs_url",
          "branches_url",
          "collaborators_url",
          "comments_url",
          "commits_url",
          "compare_url",
          "contents_url",
          "contributors_url",
          "deployments_url",
          "description",
          "downloads_url",
          "events_url",
          "fork",
          "forks_url",
          "full_name",
          "git_commits_url",
          "git_refs_url",
          "git_tags_url",
          "hooks_url",
          "html_url",
          "id",
          "node_id",
          "issue_comment_url",
          "issue_events_url",
          "issues_url",
          "keys_url",
          "labels_url",
          "languages_url",
          "merges_url",
          "milestones_url",
          "name",
          "notifications_url",
          "owner",
          "private",
          "pulls_url",
          "releases_url",
          "stargazers_url",
          "statuses_url",
          "subscribers_url",
          "subscription_url",
          "tags_url",
          "teams_url",
          "trees_url",
          "url",
          "clone_url",
          "default_branch",
          "forks",
          "forks_count",
          "git_url",
          "has_downloads",
          "has_issues",
          "has_projects",
          "has_wiki",
          "has_pages",
          "homepage",
          "language",
          "archived",
          "disabled",
          "mirror_url",
          "open_issues",
          "open_issues_count",
          "license",
          "pushed_at",
          "size",
          "ssh_url",
          "stargazers_count",
          "svn_url",
          "watchers",
          "watchers_count",
          "created_at",
          "updated_at"
        ]
      },
      "performed_via_github_app": {
        "anyOf": [
          {
            "type": "null"
          },
          {
            "title": "GitHub app",
            "description": "GitHub apps are a new way to extend GitHub. They can be installed directly on organizations and user accounts and granted access to specific repositories. They come with granular permissions and built-in webhooks. GitHub apps are first class actors within GitHub.",
            "type": "object",
            "properties": {
              "id": {
                "description": "Unique identifier of the GitHub app",
                "type": "integer",
                "examples": [
                  37
                ]
              },
              "slug": {
                "description": "The slug name of the GitHub app",
                "type": "string",
                "examples": [
                  "probot-owners"
                ]
              },
              "node_id": {
                "type": "string",
                "examples": [
                  "MDExOkludGVncmF0aW9uMQ=="
                ]
              },
              "owner": {
                "anyOf": [
                  {
                    "type": "null"
                  },
                  {
                    "title": "Simple User",
                    "description": "A GitHub user.",
                    "type": "object",
                    "properties": {
                      "name": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "email": {
                        "type": [
                          "string",
                          "null"
                        ]
                      },
                      "login": {
                        "type": "string",
                        "examples": [
                          "octocat"
                        ]
                      },
                      "id": {
                        "type": "integer",
                        "examples": [
                          1
                        ]
                      },
                      "node_id": {
                        "type": "string",
                        "examples": [
                          "MDQ6VXNlcjE="
                        ]
                      },
                      "avatar_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://github.com/images/error/octocat_happy.gif"
                        ]
                      },
                      "gravatar_id": {
                        "type": [
                          "string",
                          "null"
                        ],
                        "examples": [
                          "41d064eb2195891e12d0413f63227ea7"
                        ]
                      },
                      "url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat"
                        ]
                      },
                      "html_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://github.com/octocat"
                        ]
                      },
                      "followers_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/followers"
                        ]
                      },
                      "following_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/following{/other_user}"
                        ]
                      },
                      "gists_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/gists{/gist_id}"
                        ]
                      },
                      "starred_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                        ]
                      },
                      "subscriptions_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/subscriptions"
                        ]
                      },
                      "organizations_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/orgs"
                        ]
                      },
                      "repos_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/repos"
                        ]
                      },
                      "events_url": {
                        "type": "string",
                        "examples": [
                          "https://api.github.com/users/octocat/events{/privacy}"
                        ]
                      },
                      "received_events_url": {
                        "type": "string",
                        "format": "uri",
                        "examples": [
                          "https://api.github.com/users/octocat/received_events"
                        ]
                      },
                      "type": {
                        "type": "string",
                        "examples": [
                          "User"
                        ]
                      },
                      "site_admin": {
                        "type": "boolean"
                      },
                      "starred_at": {
                        "type": "string",
                        "examples": [
                          "\"2020-07-09T00:17:55Z\""
                        ]
                      }
                    },
                    "required": [
                      "avatar_url",
                      "events_url",
                      "followers_url",
                      "following_url",
                      "gists_url",
                      "gravatar_id",
                      "html_url",
                      "id",
                      "node_id",
                      "login",
                      "organizations_url",
                      "received_events_url",
                      "repos_url",
                      "site_admin",
                      "starred_url",
                      "subscriptions_url",
                      "type",
                      "url"
                    ]
                  }
                ]
              },
              "name": {
                "description": "The name of the GitHub app",
                "type": "string",
                "examples": [
                  "Probot Owners"
                ]
              },
              "description": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "The description of the app."
                ]
              },
              "external_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://example.com"
                ]
              },
              "html_url": {
                "type": "string",
                "format": "uri",
                "examples": [
                  "https://github.com/apps/super-ci"
                ]
              },
              "created_at": {
                "type": "string",
                "format": "date-time",
                "examples": [
                  "2017-07-08T16:18:44-04:00"
                ]
              },
              "updated_at": {
                "type": "string",
                "format": "date-time",
                "examples": [
                  "2017-07-08T16:18:44-04:00"
                ]
              },
              "permissions": {
                "description": "The set of permissions for the GitHub app",
                "type": "object",
                "properties": {
                  "issues": {
                    "type": "string"
                  },
                  "checks": {
                    "type": "string"
                  },
                  "metadata": {
                    "type": "string"
                  },
                  "contents": {
                    "type": "string"
                  },
                  "deployments": {
                    "type": "string"
                  }
                },
                "additionalProperties": {
                  "type": "string"
                },
                "example": {
                  "issues": "read",
                  "deployments": "write"
                }
              },
              "events": {
                "description": "The list of events for the GitHub app",
                "type": "array",
                "items": {
                  "type": "string"
                },
                "examples": [
                  "label",
                  "deployment"
                ]
              },
              "installations_count": {
                "description": "The number of installations associated with the GitHub app",
                "type": "integer",
                "examples": [
                  5
                ]
              },
              "client_id": {
                "type": "string",
                "examples": [
                  "\"Iv1.25b5d1e65ffc4022\""
                ]
              },
              "client_secret": {
                "type": "string",
                "examples": [
                  "\"1d4b2097ac622ba702d19de498f005747a8b21d3\""
                ]
              },
              "webhook_secret": {
                "type": [
                  "string",
                  "null"
                ],
                "examples": [
                  "\"6fba8f2fc8a7e8f2cca5577eddd82ca7586b3b6b\""
                ]
              },
              "pem": {
                "type": "string",
                "examples": [
                  "\"-----BEGIN RSA PRIVATE KEY-----\\nMIIEogIBAAKCAQEArYxrNYD/iT5CZVpRJu4rBKmmze3PVmT/gCo2ATUvDvZTPTey\\nxcGJ3vvrJXazKk06pN05TN29o98jrYz4cengG3YGsXPNEpKsIrEl8NhbnxapEnM9\\nJCMRe0P5JcPsfZlX6hmiT7136GRWiGOUba2X9+HKh8QJVLG5rM007TBER9/z9mWm\\nrJuNh+m5l320oBQY/Qq3A7wzdEfZw8qm/mIN0FCeoXH1L6B8xXWaAYBwhTEh6SSn\\nZHlO1Xu1JWDmAvBCi0RO5aRSKM8q9QEkvvHP4yweAtK3N8+aAbZ7ovaDhyGz8r6r\\nzhU1b8Uo0Z2ysf503WqzQgIajr7Fry7/kUwpgQIDAQABAoIBADwJp80Ko1xHPZDy\\nfcCKBDfIuPvkmSW6KumbsLMaQv1aGdHDwwTGv3t0ixSay8CGlxMRtRDyZPib6SvQ\\n6OH/lpfpbMdW2ErkksgtoIKBVrDilfrcAvrNZu7NxRNbhCSvN8q0s4ICecjbbVQh\\nnueSdlA6vGXbW58BHMq68uRbHkP+k+mM9U0mDJ1HMch67wlg5GbayVRt63H7R2+r\\nVxcna7B80J/lCEjIYZznawgiTvp3MSanTglqAYi+m1EcSsP14bJIB9vgaxS79kTu\\noiSo93leJbBvuGo8QEiUqTwMw4tDksmkLsoqNKQ1q9P7LZ9DGcujtPy4EZsamSJT\\ny8OJt0ECgYEA2lxOxJsQk2kI325JgKFjo92mQeUObIvPfSNWUIZQDTjniOI6Gv63\\nGLWVFrZcvQBWjMEQraJA9xjPbblV8PtfO87MiJGLWCHFxmPz2dzoedN+2Coxom8m\\nV95CLz8QUShuao6u/RYcvUaZEoYs5bHcTmy5sBK80JyEmafJPtCQVxMCgYEAy3ar\\nZr3yv4xRPEPMat4rseswmuMooSaK3SKub19WFI5IAtB/e7qR1Rj9JhOGcZz+OQrl\\nT78O2OFYlgOIkJPvRMrPpK5V9lslc7tz1FSh3BZMRGq5jSyD7ETSOQ0c8T2O/s7v\\nbeEPbVbDe4mwvM24XByH0GnWveVxaDl51ABD65sCgYB3ZAspUkOA5egVCh8kNpnd\\nSd6SnuQBE3ySRlT2WEnCwP9Ph6oPgn+oAfiPX4xbRqkL8q/k0BdHQ4h+zNwhk7+h\\nWtPYRAP1Xxnc/F+jGjb+DVaIaKGU18MWPg7f+FI6nampl3Q0KvfxwX0GdNhtio8T\\nTj1E+SnFwh56SRQuxSh2gwKBgHKjlIO5NtNSflsUYFM+hyQiPiqnHzddfhSG+/3o\\nm5nNaSmczJesUYreH5San7/YEy2UxAugvP7aSY2MxB+iGsiJ9WD2kZzTUlDZJ7RV\\nUzWsoqBR+eZfVJ2FUWWvy8TpSG6trh4dFxImNtKejCR1TREpSiTV3Zb1dmahK9GV\\nrK9NAoGAbBxRLoC01xfxCTgt5BDiBcFVh4fp5yYKwavJPLzHSpuDOrrI9jDn1oKN\\nonq5sDU1i391zfQvdrbX4Ova48BN+B7p63FocP/MK5tyyBoT8zQEk2+vWDOw7H/Z\\nu5dTCPxTIsoIwUw1I+7yIxqJzLPFgR2gVBwY1ra/8iAqCj+zeBw=\\n-----END RSA PRIVATE KEY-----\\n\""
                ]
              }
            },
            "required": [
              "id",
              "node_id",
              "owner",
              "name",
              "description",
              "external_url",
              "html_url",
              "created_at",
              "updated_at",
              "permissions",
              "events"
            ]
          }
        ]
      },
      "author_association": {
        "title": "author_association",
        "type": "string",
        "description": "How the author is associated with the repository.",
        "enum": [
          "COLLABORATOR",
          "CONTRIBUTOR",
          "FIRST_TIMER",
          "FIRST_TIME_CONTRIBUTOR",
          "MANNEQUIN",
          "MEMBER",
          "NONE",
          "OWNER"
        ],
        "examples": [
          "OWNER"
        ]
      },
      "reactions": {
        "title": "Reaction Rollup",
        "type": "object",
        "properties": {
          "url": {
            "type": "string",
            "format": "uri"
          },
          "total_count": {
            "type": "integer"
          },
          "+1": {
            "type": "integer"
          },
          "-1": {
            "type": "integer"
          },
          "laugh": {
            "type": "integer"
          },
          "confused": {
            "type": "integer"
          },
          "heart": {
            "type": "integer"
          },
          "hooray": {
            "type": "integer"
          },
          "eyes": {
            "type": "integer"
          },
          "rocket": {
            "type": "integer"
          }
        },
        "required": [
          "url",
          "total_count",
          "+1",
          "-1",
          "laugh",
          "confused",
          "heart",
          "hooray",
          "eyes",
          "rocket"
        ]
      }
    },
    "required": [
      "assignee",
      "closed_at",
      "comments",
      "comments_url",
      "events_url",
      "html_url",
      "id",
      "node_id",
      "labels",
      "labels_url",
      "milestone",
      "number",
      "repository_url",
      "state",
      "locked",
      "title",
      "url",
      "user",
      "author_association",
      "created_at",
      "updated_at"
    ]
  }
}
'''





# get an issue schema -- is it different from search results?
'''
{
  "title": "Issue",
  "description": "Issues are a great way to keep track of tasks, enhancements, and bugs for your projects.",
  "type": "object",
  "properties": {
    "id": {
      "type": "integer",
      "format": "int64"
    },
    "node_id": {
      "type": "string"
    },
    "url": {
      "description": "URL for the issue",
      "type": "string",
      "format": "uri",
      "examples": [
        "https://api.github.com/repositories/42/issues/1"
      ]
    },
    "repository_url": {
      "type": "string",
      "format": "uri"
    },
    "labels_url": {
      "type": "string"
    },
    "comments_url": {
      "type": "string",
      "format": "uri"
    },
    "events_url": {
      "type": "string",
      "format": "uri"
    },
    "html_url": {
      "type": "string",
      "format": "uri"
    },
    "number": {
      "description": "Number uniquely identifying the issue within its repository",
      "type": "integer",
      "examples": [
        42
      ]
    },
    "state": {
      "description": "State of the issue; either 'open' or 'closed'",
      "type": "string",
      "examples": [
        "open"
      ]
    },
    "state_reason": {
      "description": "The reason for the current state",
      "type": [
        "string",
        "null"
      ],
      "enum": [
        "completed",
        "reopened",
        "not_planned",
        null
      ],
      "examples": [
        "not_planned"
      ]
    },
    "title": {
      "description": "Title of the issue",
      "type": "string",
      "examples": [
        "Widget creation fails in Safari on OS X 10.8"
      ]
    },
    "body": {
      "description": "Contents of the issue",
      "type": [
        "string",
        "null"
      ],
      "examples": [
        "It looks like the new widget form is broken on Safari. When I try and create the widget, Safari crashes. This is reproducible on 10.8, but not 10.9. Maybe a browser bug?"
      ]
    },
    "user": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "labels": {
      "description": "Labels to associate with this issue; pass one or more label names to replace the set of labels on this issue; send an empty array to clear all labels from the issue; note that the labels are silently dropped for users without push access to the repository",
      "type": "array",
      "items": {
        "oneOf": [
          {
            "type": "string"
          },
          {
            "type": "object",
            "properties": {
              "id": {
                "type": "integer",
                "format": "int64"
              },
              "node_id": {
                "type": "string"
              },
              "url": {
                "type": "string",
                "format": "uri"
              },
              "name": {
                "type": "string"
              },
              "description": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "color": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "default": {
                "type": "boolean"
              }
            }
          }
        ]
      },
      "examples": [
        "bug",
        "registration"
      ]
    },
    "assignee": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "assignees": {
      "type": [
        "array",
        "null"
      ],
      "items": {
        "title": "Simple User",
        "description": "A GitHub user.",
        "type": "object",
        "properties": {
          "name": {
            "type": [
              "string",
              "null"
            ]
          },
          "email": {
            "type": [
              "string",
              "null"
            ]
          },
          "login": {
            "type": "string",
            "examples": [
              "octocat"
            ]
          },
          "id": {
            "type": "integer",
            "examples": [
              1
            ]
          },
          "node_id": {
            "type": "string",
            "examples": [
              "MDQ6VXNlcjE="
            ]
          },
          "avatar_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://github.com/images/error/octocat_happy.gif"
            ]
          },
          "gravatar_id": {
            "type": [
              "string",
              "null"
            ],
            "examples": [
              "41d064eb2195891e12d0413f63227ea7"
            ]
          },
          "url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://api.github.com/users/octocat"
            ]
          },
          "html_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://github.com/octocat"
            ]
          },
          "followers_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://api.github.com/users/octocat/followers"
            ]
          },
          "following_url": {
            "type": "string",
            "examples": [
              "https://api.github.com/users/octocat/following{/other_user}"
            ]
          },
          "gists_url": {
            "type": "string",
            "examples": [
              "https://api.github.com/users/octocat/gists{/gist_id}"
            ]
          },
          "starred_url": {
            "type": "string",
            "examples": [
              "https://api.github.com/users/octocat/starred{/owner}{/repo}"
            ]
          },
          "subscriptions_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://api.github.com/users/octocat/subscriptions"
            ]
          },
          "organizations_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://api.github.com/users/octocat/orgs"
            ]
          },
          "repos_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://api.github.com/users/octocat/repos"
            ]
          },
          "events_url": {
            "type": "string",
            "examples": [
              "https://api.github.com/users/octocat/events{/privacy}"
            ]
          },
          "received_events_url": {
            "type": "string",
            "format": "uri",
            "examples": [
              "https://api.github.com/users/octocat/received_events"
            ]
          },
          "type": {
            "type": "string",
            "examples": [
              "User"
            ]
          },
          "site_admin": {
            "type": "boolean"
          },
          "starred_at": {
            "type": "string",
            "examples": [
              "\"2020-07-09T00:17:55Z\""
            ]
          }
        },
        "required": [
          "avatar_url",
          "events_url",
          "followers_url",
          "following_url",
          "gists_url",
          "gravatar_id",
          "html_url",
          "id",
          "node_id",
          "login",
          "organizations_url",
          "received_events_url",
          "repos_url",
          "site_admin",
          "starred_url",
          "subscriptions_url",
          "type",
          "url"
        ]
      }
    },
    "milestone": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Milestone",
          "description": "A collection of related issues and pull requests.",
          "type": "object",
          "properties": {
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/repos/octocat/Hello-World/milestones/1"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat/Hello-World/milestones/v1.0"
              ]
            },
            "labels_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/repos/octocat/Hello-World/milestones/1/labels"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1002604
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDk6TWlsZXN0b25lMTAwMjYwNA=="
              ]
            },
            "number": {
              "description": "The number of the milestone.",
              "type": "integer",
              "examples": [
                42
              ]
            },
            "state": {
              "description": "The state of the milestone.",
              "type": "string",
              "enum": [
                "open",
                "closed"
              ],
              "default": "open",
              "examples": [
                "open"
              ]
            },
            "title": {
              "description": "The title of the milestone.",
              "type": "string",
              "examples": [
                "v1.0"
              ]
            },
            "description": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "Tracking milestone for version 1.0"
              ]
            },
            "creator": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "Simple User",
                  "description": "A GitHub user.",
                  "type": "object",
                  "properties": {
                    "name": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "email": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "login": {
                      "type": "string",
                      "examples": [
                        "octocat"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDQ6VXNlcjE="
                      ]
                    },
                    "avatar_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/images/error/octocat_happy.gif"
                      ]
                    },
                    "gravatar_id": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "41d064eb2195891e12d0413f63227ea7"
                      ]
                    },
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat"
                      ]
                    },
                    "followers_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/followers"
                      ]
                    },
                    "following_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/following{/other_user}"
                      ]
                    },
                    "gists_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/gists{/gist_id}"
                      ]
                    },
                    "starred_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                      ]
                    },
                    "subscriptions_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/subscriptions"
                      ]
                    },
                    "organizations_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/orgs"
                      ]
                    },
                    "repos_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/repos"
                      ]
                    },
                    "events_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/events{/privacy}"
                      ]
                    },
                    "received_events_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/received_events"
                      ]
                    },
                    "type": {
                      "type": "string",
                      "examples": [
                        "User"
                      ]
                    },
                    "site_admin": {
                      "type": "boolean"
                    },
                    "starred_at": {
                      "type": "string",
                      "examples": [
                        "\"2020-07-09T00:17:55Z\""
                      ]
                    }
                  },
                  "required": [
                    "avatar_url",
                    "events_url",
                    "followers_url",
                    "following_url",
                    "gists_url",
                    "gravatar_id",
                    "html_url",
                    "id",
                    "node_id",
                    "login",
                    "organizations_url",
                    "received_events_url",
                    "repos_url",
                    "site_admin",
                    "starred_url",
                    "subscriptions_url",
                    "type",
                    "url"
                  ]
                }
              ]
            },
            "open_issues": {
              "type": "integer",
              "examples": [
                4
              ]
            },
            "closed_issues": {
              "type": "integer",
              "examples": [
                8
              ]
            },
            "created_at": {
              "type": "string",
              "format": "date-time",
              "examples": [
                "2011-04-10T20:09:31Z"
              ]
            },
            "updated_at": {
              "type": "string",
              "format": "date-time",
              "examples": [
                "2014-03-03T18:58:10Z"
              ]
            },
            "closed_at": {
              "type": [
                "string",
                "null"
              ],
              "format": "date-time",
              "examples": [
                "2013-02-12T13:22:01Z"
              ]
            },
            "due_on": {
              "type": [
                "string",
                "null"
              ],
              "format": "date-time",
              "examples": [
                "2012-10-09T23:39:01Z"
              ]
            }
          },
          "required": [
            "closed_issues",
            "creator",
            "description",
            "due_on",
            "closed_at",
            "id",
            "node_id",
            "labels_url",
            "html_url",
            "number",
            "open_issues",
            "state",
            "title",
            "url",
            "created_at",
            "updated_at"
          ]
        }
      ]
    },
    "locked": {
      "type": "boolean"
    },
    "active_lock_reason": {
      "type": [
        "string",
        "null"
      ]
    },
    "comments": {
      "type": "integer"
    },
    "pull_request": {
      "type": "object",
      "properties": {
        "merged_at": {
          "type": [
            "string",
            "null"
          ],
          "format": "date-time"
        },
        "diff_url": {
          "type": [
            "string",
            "null"
          ],
          "format": "uri"
        },
        "html_url": {
          "type": [
            "string",
            "null"
          ],
          "format": "uri"
        },
        "patch_url": {
          "type": [
            "string",
            "null"
          ],
          "format": "uri"
        },
        "url": {
          "type": [
            "string",
            "null"
          ],
          "format": "uri"
        }
      },
      "required": [
        "diff_url",
        "html_url",
        "patch_url",
        "url"
      ]
    },
    "closed_at": {
      "type": [
        "string",
        "null"
      ],
      "format": "date-time"
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    },
    "draft": {
      "type": "boolean"
    },
    "closed_by": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        }
      ]
    },
    "body_html": {
      "type": "string"
    },
    "body_text": {
      "type": "string"
    },
    "timeline_url": {
      "type": "string",
      "format": "uri"
    },
    "repository": {
      "title": "Repository",
      "description": "A repository on GitHub.",
      "type": "object",
      "properties": {
        "id": {
          "description": "Unique identifier of the repository",
          "type": "integer",
          "examples": [
            42
          ]
        },
        "node_id": {
          "type": "string",
          "examples": [
            "MDEwOlJlcG9zaXRvcnkxMjk2MjY5"
          ]
        },
        "name": {
          "description": "The name of the repository.",
          "type": "string",
          "examples": [
            "Team Environment"
          ]
        },
        "full_name": {
          "type": "string",
          "examples": [
            "octocat/Hello-World"
          ]
        },
        "license": {
          "anyOf": [
            {
              "type": "null"
            },
            {
              "title": "License Simple",
              "description": "License Simple",
              "type": "object",
              "properties": {
                "key": {
                  "type": "string",
                  "examples": [
                    "mit"
                  ]
                },
                "name": {
                  "type": "string",
                  "examples": [
                    "MIT License"
                  ]
                },
                "url": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/licenses/mit"
                  ]
                },
                "spdx_id": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "examples": [
                    "MIT"
                  ]
                },
                "node_id": {
                  "type": "string",
                  "examples": [
                    "MDc6TGljZW5zZW1pdA=="
                  ]
                },
                "html_url": {
                  "type": "string",
                  "format": "uri"
                }
              },
              "required": [
                "key",
                "name",
                "url",
                "spdx_id",
                "node_id"
              ]
            }
          ]
        },
        "organization": {
          "anyOf": [
            {
              "type": "null"
            },
            {
              "title": "Simple User",
              "description": "A GitHub user.",
              "type": "object",
              "properties": {
                "name": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "email": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "login": {
                  "type": "string",
                  "examples": [
                    "octocat"
                  ]
                },
                "id": {
                  "type": "integer",
                  "examples": [
                    1
                  ]
                },
                "node_id": {
                  "type": "string",
                  "examples": [
                    "MDQ6VXNlcjE="
                  ]
                },
                "avatar_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://github.com/images/error/octocat_happy.gif"
                  ]
                },
                "gravatar_id": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "examples": [
                    "41d064eb2195891e12d0413f63227ea7"
                  ]
                },
                "url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/users/octocat"
                  ]
                },
                "html_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://github.com/octocat"
                  ]
                },
                "followers_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/users/octocat/followers"
                  ]
                },
                "following_url": {
                  "type": "string",
                  "examples": [
                    "https://api.github.com/users/octocat/following{/other_user}"
                  ]
                },
                "gists_url": {
                  "type": "string",
                  "examples": [
                    "https://api.github.com/users/octocat/gists{/gist_id}"
                  ]
                },
                "starred_url": {
                  "type": "string",
                  "examples": [
                    "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                  ]
                },
                "subscriptions_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/users/octocat/subscriptions"
                  ]
                },
                "organizations_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/users/octocat/orgs"
                  ]
                },
                "repos_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/users/octocat/repos"
                  ]
                },
                "events_url": {
                  "type": "string",
                  "examples": [
                    "https://api.github.com/users/octocat/events{/privacy}"
                  ]
                },
                "received_events_url": {
                  "type": "string",
                  "format": "uri",
                  "examples": [
                    "https://api.github.com/users/octocat/received_events"
                  ]
                },
                "type": {
                  "type": "string",
                  "examples": [
                    "User"
                  ]
                },
                "site_admin": {
                  "type": "boolean"
                },
                "starred_at": {
                  "type": "string",
                  "examples": [
                    "\"2020-07-09T00:17:55Z\""
                  ]
                }
              },
              "required": [
                "avatar_url",
                "events_url",
                "followers_url",
                "following_url",
                "gists_url",
                "gravatar_id",
                "html_url",
                "id",
                "node_id",
                "login",
                "organizations_url",
                "received_events_url",
                "repos_url",
                "site_admin",
                "starred_url",
                "subscriptions_url",
                "type",
                "url"
              ]
            }
          ]
        },
        "forks": {
          "type": "integer"
        },
        "permissions": {
          "type": "object",
          "properties": {
            "admin": {
              "type": "boolean"
            },
            "pull": {
              "type": "boolean"
            },
            "triage": {
              "type": "boolean"
            },
            "push": {
              "type": "boolean"
            },
            "maintain": {
              "type": "boolean"
            }
          },
          "required": [
            "admin",
            "pull",
            "push"
          ]
        },
        "owner": {
          "title": "Simple User",
          "description": "A GitHub user.",
          "type": "object",
          "properties": {
            "name": {
              "type": [
                "string",
                "null"
              ]
            },
            "email": {
              "type": [
                "string",
                "null"
              ]
            },
            "login": {
              "type": "string",
              "examples": [
                "octocat"
              ]
            },
            "id": {
              "type": "integer",
              "examples": [
                1
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDQ6VXNlcjE="
              ]
            },
            "avatar_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/images/error/octocat_happy.gif"
              ]
            },
            "gravatar_id": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "41d064eb2195891e12d0413f63227ea7"
              ]
            },
            "url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/octocat"
              ]
            },
            "followers_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/followers"
              ]
            },
            "following_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/following{/other_user}"
              ]
            },
            "gists_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/gists{/gist_id}"
              ]
            },
            "starred_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/starred{/owner}{/repo}"
              ]
            },
            "subscriptions_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/subscriptions"
              ]
            },
            "organizations_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/orgs"
              ]
            },
            "repos_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/repos"
              ]
            },
            "events_url": {
              "type": "string",
              "examples": [
                "https://api.github.com/users/octocat/events{/privacy}"
              ]
            },
            "received_events_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://api.github.com/users/octocat/received_events"
              ]
            },
            "type": {
              "type": "string",
              "examples": [
                "User"
              ]
            },
            "site_admin": {
              "type": "boolean"
            },
            "starred_at": {
              "type": "string",
              "examples": [
                "\"2020-07-09T00:17:55Z\""
              ]
            }
          },
          "required": [
            "avatar_url",
            "events_url",
            "followers_url",
            "following_url",
            "gists_url",
            "gravatar_id",
            "html_url",
            "id",
            "node_id",
            "login",
            "organizations_url",
            "received_events_url",
            "repos_url",
            "site_admin",
            "starred_url",
            "subscriptions_url",
            "type",
            "url"
          ]
        },
        "private": {
          "description": "Whether the repository is private or public.",
          "default": false,
          "type": "boolean"
        },
        "html_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "https://github.com/octocat/Hello-World"
          ]
        },
        "description": {
          "type": [
            "string",
            "null"
          ],
          "examples": [
            "This your first repo!"
          ]
        },
        "fork": {
          "type": "boolean"
        },
        "url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "https://api.github.com/repos/octocat/Hello-World"
          ]
        },
        "archive_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/{archive_format}{/ref}"
          ]
        },
        "assignees_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/assignees{/user}"
          ]
        },
        "blobs_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/git/blobs{/sha}"
          ]
        },
        "branches_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/branches{/branch}"
          ]
        },
        "collaborators_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/collaborators{/collaborator}"
          ]
        },
        "comments_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/comments{/number}"
          ]
        },
        "commits_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/commits{/sha}"
          ]
        },
        "compare_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/compare/{base}...{head}"
          ]
        },
        "contents_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/contents/{+path}"
          ]
        },
        "contributors_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/contributors"
          ]
        },
        "deployments_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/deployments"
          ]
        },
        "downloads_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/downloads"
          ]
        },
        "events_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/events"
          ]
        },
        "forks_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/forks"
          ]
        },
        "git_commits_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/git/commits{/sha}"
          ]
        },
        "git_refs_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/git/refs{/sha}"
          ]
        },
        "git_tags_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/git/tags{/sha}"
          ]
        },
        "git_url": {
          "type": "string",
          "examples": [
            "git:github.com/octocat/Hello-World.git"
          ]
        },
        "issue_comment_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/issues/comments{/number}"
          ]
        },
        "issue_events_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/issues/events{/number}"
          ]
        },
        "issues_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/issues{/number}"
          ]
        },
        "keys_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/keys{/key_id}"
          ]
        },
        "labels_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/labels{/name}"
          ]
        },
        "languages_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/languages"
          ]
        },
        "merges_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/merges"
          ]
        },
        "milestones_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/milestones{/number}"
          ]
        },
        "notifications_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/notifications{?since,all,participating}"
          ]
        },
        "pulls_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/pulls{/number}"
          ]
        },
        "releases_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/releases{/id}"
          ]
        },
        "ssh_url": {
          "type": "string",
          "examples": [
            "git@github.com:octocat/Hello-World.git"
          ]
        },
        "stargazers_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/stargazers"
          ]
        },
        "statuses_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/statuses/{sha}"
          ]
        },
        "subscribers_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/subscribers"
          ]
        },
        "subscription_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/subscription"
          ]
        },
        "tags_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/tags"
          ]
        },
        "teams_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/teams"
          ]
        },
        "trees_url": {
          "type": "string",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/git/trees{/sha}"
          ]
        },
        "clone_url": {
          "type": "string",
          "examples": [
            "https://github.com/octocat/Hello-World.git"
          ]
        },
        "mirror_url": {
          "type": [
            "string",
            "null"
          ],
          "format": "uri",
          "examples": [
            "git:git.example.com/octocat/Hello-World"
          ]
        },
        "hooks_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "http://api.github.com/repos/octocat/Hello-World/hooks"
          ]
        },
        "svn_url": {
          "type": "string",
          "format": "uri",
          "examples": [
            "https://svn.github.com/octocat/Hello-World"
          ]
        },
        "homepage": {
          "type": [
            "string",
            "null"
          ],
          "format": "uri",
          "examples": [
            "https://github.com"
          ]
        },
        "language": {
          "type": [
            "string",
            "null"
          ]
        },
        "forks_count": {
          "type": "integer",
          "examples": [
            9
          ]
        },
        "stargazers_count": {
          "type": "integer",
          "examples": [
            80
          ]
        },
        "watchers_count": {
          "type": "integer",
          "examples": [
            80
          ]
        },
        "size": {
          "description": "The size of the repository. Size is calculated hourly. When a repository is initially created, the size is 0.",
          "type": "integer",
          "examples": [
            108
          ]
        },
        "default_branch": {
          "description": "The default branch of the repository.",
          "type": "string",
          "examples": [
            "master"
          ]
        },
        "open_issues_count": {
          "type": "integer",
          "examples": [
            0
          ]
        },
        "is_template": {
          "description": "Whether this repository acts as a template that can be used to generate new repositories.",
          "default": false,
          "type": "boolean",
          "examples": [
            true
          ]
        },
        "topics": {
          "type": "array",
          "items": {
            "type": "string"
          }
        },
        "has_issues": {
          "description": "Whether issues are enabled.",
          "default": true,
          "type": "boolean",
          "examples": [
            true
          ]
        },
        "has_projects": {
          "description": "Whether projects are enabled.",
          "default": true,
          "type": "boolean",
          "examples": [
            true
          ]
        },
        "has_wiki": {
          "description": "Whether the wiki is enabled.",
          "default": true,
          "type": "boolean",
          "examples": [
            true
          ]
        },
        "has_pages": {
          "type": "boolean"
        },
        "has_downloads": {
          "description": "Whether downloads are enabled.",
          "default": true,
          "type": "boolean",
          "deprecated": true,
          "examples": [
            true
          ]
        },
        "has_discussions": {
          "description": "Whether discussions are enabled.",
          "default": false,
          "type": "boolean",
          "examples": [
            true
          ]
        },
        "archived": {
          "description": "Whether the repository is archived.",
          "default": false,
          "type": "boolean"
        },
        "disabled": {
          "type": "boolean",
          "description": "Returns whether or not this repository disabled."
        },
        "visibility": {
          "description": "The repository visibility: public, private, or internal.",
          "default": "public",
          "type": "string"
        },
        "pushed_at": {
          "type": [
            "string",
            "null"
          ],
          "format": "date-time",
          "examples": [
            "2011-01-26T19:06:43Z"
          ]
        },
        "created_at": {
          "type": [
            "string",
            "null"
          ],
          "format": "date-time",
          "examples": [
            "2011-01-26T19:01:12Z"
          ]
        },
        "updated_at": {
          "type": [
            "string",
            "null"
          ],
          "format": "date-time",
          "examples": [
            "2011-01-26T19:14:43Z"
          ]
        },
        "allow_rebase_merge": {
          "description": "Whether to allow rebase merges for pull requests.",
          "default": true,
          "type": "boolean",
          "examples": [
            true
          ]
        },
        "template_repository": {
          "type": [
            "object",
            "null"
          ],
          "properties": {
            "id": {
              "type": "integer"
            },
            "node_id": {
              "type": "string"
            },
            "name": {
              "type": "string"
            },
            "full_name": {
              "type": "string"
            },
            "owner": {
              "type": "object",
              "properties": {
                "login": {
                  "type": "string"
                },
                "id": {
                  "type": "integer"
                },
                "node_id": {
                  "type": "string"
                },
                "avatar_url": {
                  "type": "string"
                },
                "gravatar_id": {
                  "type": "string"
                },
                "url": {
                  "type": "string"
                },
                "html_url": {
                  "type": "string"
                },
                "followers_url": {
                  "type": "string"
                },
                "following_url": {
                  "type": "string"
                },
                "gists_url": {
                  "type": "string"
                },
                "starred_url": {
                  "type": "string"
                },
                "subscriptions_url": {
                  "type": "string"
                },
                "organizations_url": {
                  "type": "string"
                },
                "repos_url": {
                  "type": "string"
                },
                "events_url": {
                  "type": "string"
                },
                "received_events_url": {
                  "type": "string"
                },
                "type": {
                  "type": "string"
                },
                "site_admin": {
                  "type": "boolean"
                }
              }
            },
            "private": {
              "type": "boolean"
            },
            "html_url": {
              "type": "string"
            },
            "description": {
              "type": "string"
            },
            "fork": {
              "type": "boolean"
            },
            "url": {
              "type": "string"
            },
            "archive_url": {
              "type": "string"
            },
            "assignees_url": {
              "type": "string"
            },
            "blobs_url": {
              "type": "string"
            },
            "branches_url": {
              "type": "string"
            },
            "collaborators_url": {
              "type": "string"
            },
            "comments_url": {
              "type": "string"
            },
            "commits_url": {
              "type": "string"
            },
            "compare_url": {
              "type": "string"
            },
            "contents_url": {
              "type": "string"
            },
            "contributors_url": {
              "type": "string"
            },
            "deployments_url": {
              "type": "string"
            },
            "downloads_url": {
              "type": "string"
            },
            "events_url": {
              "type": "string"
            },
            "forks_url": {
              "type": "string"
            },
            "git_commits_url": {
              "type": "string"
            },
            "git_refs_url": {
              "type": "string"
            },
            "git_tags_url": {
              "type": "string"
            },
            "git_url": {
              "type": "string"
            },
            "issue_comment_url": {
              "type": "string"
            },
            "issue_events_url": {
              "type": "string"
            },
            "issues_url": {
              "type": "string"
            },
            "keys_url": {
              "type": "string"
            },
            "labels_url": {
              "type": "string"
            },
            "languages_url": {
              "type": "string"
            },
            "merges_url": {
              "type": "string"
            },
            "milestones_url": {
              "type": "string"
            },
            "notifications_url": {
              "type": "string"
            },
            "pulls_url": {
              "type": "string"
            },
            "releases_url": {
              "type": "string"
            },
            "ssh_url": {
              "type": "string"
            },
            "stargazers_url": {
              "type": "string"
            },
            "statuses_url": {
              "type": "string"
            },
            "subscribers_url": {
              "type": "string"
            },
            "subscription_url": {
              "type": "string"
            },
            "tags_url": {
              "type": "string"
            },
            "teams_url": {
              "type": "string"
            },
            "trees_url": {
              "type": "string"
            },
            "clone_url": {
              "type": "string"
            },
            "mirror_url": {
              "type": "string"
            },
            "hooks_url": {
              "type": "string"
            },
            "svn_url": {
              "type": "string"
            },
            "homepage": {
              "type": "string"
            },
            "language": {
              "type": "string"
            },
            "forks_count": {
              "type": "integer"
            },
            "stargazers_count": {
              "type": "integer"
            },
            "watchers_count": {
              "type": "integer"
            },
            "size": {
              "type": "integer"
            },
            "default_branch": {
              "type": "string"
            },
            "open_issues_count": {
              "type": "integer"
            },
            "is_template": {
              "type": "boolean"
            },
            "topics": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "has_issues": {
              "type": "boolean"
            },
            "has_projects": {
              "type": "boolean"
            },
            "has_wiki": {
              "type": "boolean"
            },
            "has_pages": {
              "type": "boolean"
            },
            "has_downloads": {
              "type": "boolean"
            },
            "archived": {
              "type": "boolean"
            },
            "disabled": {
              "type": "boolean"
            },
            "visibility": {
              "type": "string"
            },
            "pushed_at": {
              "type": "string"
            },
            "created_at": {
              "type": "string"
            },
            "updated_at": {
              "type": "string"
            },
            "permissions": {
              "type": "object",
              "properties": {
                "admin": {
                  "type": "boolean"
                },
                "maintain": {
                  "type": "boolean"
                },
                "push": {
                  "type": "boolean"
                },
                "triage": {
                  "type": "boolean"
                },
                "pull": {
                  "type": "boolean"
                }
              }
            },
            "allow_rebase_merge": {
              "type": "boolean"
            },
            "temp_clone_token": {
              "type": "string"
            },
            "allow_squash_merge": {
              "type": "boolean"
            },
            "allow_auto_merge": {
              "type": "boolean"
            },
            "delete_branch_on_merge": {
              "type": "boolean"
            },
            "allow_update_branch": {
              "type": "boolean"
            },
            "use_squash_pr_title_as_default": {
              "type": "boolean"
            },
            "squash_merge_commit_title": {
              "type": "string",
              "enum": [
                "PR_TITLE",
                "COMMIT_OR_PR_TITLE"
              ],
              "description": "The default value for a squash merge commit title:\n\n- `PR_TITLE` - default to the pull request's title.\n- `COMMIT_OR_PR_TITLE` - default to the commit's title (if only one commit) or the pull request's title (when more than one commit)."
            },
            "squash_merge_commit_message": {
              "type": "string",
              "enum": [
                "PR_BODY",
                "COMMIT_MESSAGES",
                "BLANK"
              ],
              "description": "The default value for a squash merge commit message:\n\n- `PR_BODY` - default to the pull request's body.\n- `COMMIT_MESSAGES` - default to the branch's commit messages.\n- `BLANK` - default to a blank commit message."
            },
            "merge_commit_title": {
              "type": "string",
              "enum": [
                "PR_TITLE",
                "MERGE_MESSAGE"
              ],
              "description": "The default value for a merge commit title.\n\n- `PR_TITLE` - default to the pull request's title.\n- `MERGE_MESSAGE` - default to the classic title for a merge message (e.g., Merge pull request #123 from branch-name)."
            },
            "merge_commit_message": {
              "type": "string",
              "enum": [
                "PR_BODY",
                "PR_TITLE",
                "BLANK"
              ],
              "description": "The default value for a merge commit message.\n\n- `PR_TITLE` - default to the pull request's title.\n- `PR_BODY` - default to the pull request's body.\n- `BLANK` - default to a blank commit message."
            },
            "allow_merge_commit": {
              "type": "boolean"
            },
            "subscribers_count": {
              "type": "integer"
            },
            "network_count": {
              "type": "integer"
            }
          }
        },
        "temp_clone_token": {
          "type": "string"
        },
        "allow_squash_merge": {
          "description": "Whether to allow squash merges for pull requests.",
          "default": true,
          "type": "boolean",
          "examples": [
            true
          ]
        },
        "allow_auto_merge": {
          "description": "Whether to allow Auto-merge to be used on pull requests.",
          "default": false,
          "type": "boolean",
          "examples": [
            false
          ]
        },
        "delete_branch_on_merge": {
          "description": "Whether to delete head branches when pull requests are merged",
          "default": false,
          "type": "boolean",
          "examples": [
            false
          ]
        },
        "allow_update_branch": {
          "description": "Whether or not a pull request head branch that is behind its base branch can always be updated even if it is not required to be up to date before merging.",
          "default": false,
          "type": "boolean",
          "examples": [
            false
          ]
        },
        "use_squash_pr_title_as_default": {
          "type": "boolean",
          "description": "Whether a squash merge commit can use the pull request title as default. **This property has been deprecated. Please use `squash_merge_commit_title` instead.",
          "default": false,
          "deprecated": true
        },
        "squash_merge_commit_title": {
          "type": "string",
          "enum": [
            "PR_TITLE",
            "COMMIT_OR_PR_TITLE"
          ],
          "description": "The default value for a squash merge commit title:\n\n- `PR_TITLE` - default to the pull request's title.\n- `COMMIT_OR_PR_TITLE` - default to the commit's title (if only one commit) or the pull request's title (when more than one commit)."
        },
        "squash_merge_commit_message": {
          "type": "string",
          "enum": [
            "PR_BODY",
            "COMMIT_MESSAGES",
            "BLANK"
          ],
          "description": "The default value for a squash merge commit message:\n\n- `PR_BODY` - default to the pull request's body.\n- `COMMIT_MESSAGES` - default to the branch's commit messages.\n- `BLANK` - default to a blank commit message."
        },
        "merge_commit_title": {
          "type": "string",
          "enum": [
            "PR_TITLE",
            "MERGE_MESSAGE"
          ],
          "description": "The default value for a merge commit title.\n\n- `PR_TITLE` - default to the pull request's title.\n- `MERGE_MESSAGE` - default to the classic title for a merge message (e.g., Merge pull request #123 from branch-name)."
        },
        "merge_commit_message": {
          "type": "string",
          "enum": [
            "PR_BODY",
            "PR_TITLE",
            "BLANK"
          ],
          "description": "The default value for a merge commit message.\n\n- `PR_TITLE` - default to the pull request's title.\n- `PR_BODY` - default to the pull request's body.\n- `BLANK` - default to a blank commit message."
        },
        "allow_merge_commit": {
          "description": "Whether to allow merge commits for pull requests.",
          "default": true,
          "type": "boolean",
          "examples": [
            true
          ]
        },
        "allow_forking": {
          "description": "Whether to allow forking this repo",
          "type": "boolean"
        },
        "web_commit_signoff_required": {
          "description": "Whether to require contributors to sign off on web-based commits",
          "default": false,
          "type": "boolean"
        },
        "subscribers_count": {
          "type": "integer"
        },
        "network_count": {
          "type": "integer"
        },
        "open_issues": {
          "type": "integer"
        },
        "watchers": {
          "type": "integer"
        },
        "master_branch": {
          "type": "string"
        },
        "starred_at": {
          "type": "string",
          "examples": [
            "\"2020-07-09T00:17:42Z\""
          ]
        },
        "anonymous_access_enabled": {
          "type": "boolean",
          "description": "Whether anonymous git access is enabled for this repository"
        }
      },
      "required": [
        "archive_url",
        "assignees_url",
        "blobs_url",
        "branches_url",
        "collaborators_url",
        "comments_url",
        "commits_url",
        "compare_url",
        "contents_url",
        "contributors_url",
        "deployments_url",
        "description",
        "downloads_url",
        "events_url",
        "fork",
        "forks_url",
        "full_name",
        "git_commits_url",
        "git_refs_url",
        "git_tags_url",
        "hooks_url",
        "html_url",
        "id",
        "node_id",
        "issue_comment_url",
        "issue_events_url",
        "issues_url",
        "keys_url",
        "labels_url",
        "languages_url",
        "merges_url",
        "milestones_url",
        "name",
        "notifications_url",
        "owner",
        "private",
        "pulls_url",
        "releases_url",
        "stargazers_url",
        "statuses_url",
        "subscribers_url",
        "subscription_url",
        "tags_url",
        "teams_url",
        "trees_url",
        "url",
        "clone_url",
        "default_branch",
        "forks",
        "forks_count",
        "git_url",
        "has_downloads",
        "has_issues",
        "has_projects",
        "has_wiki",
        "has_pages",
        "homepage",
        "language",
        "archived",
        "disabled",
        "mirror_url",
        "open_issues",
        "open_issues_count",
        "license",
        "pushed_at",
        "size",
        "ssh_url",
        "stargazers_count",
        "svn_url",
        "watchers",
        "watchers_count",
        "created_at",
        "updated_at"
      ]
    },
    "performed_via_github_app": {
      "anyOf": [
        {
          "type": "null"
        },
        {
          "title": "GitHub app",
          "description": "GitHub apps are a new way to extend GitHub. They can be installed directly on organizations and user accounts and granted access to specific repositories. They come with granular permissions and built-in webhooks. GitHub apps are first class actors within GitHub.",
          "type": "object",
          "properties": {
            "id": {
              "description": "Unique identifier of the GitHub app",
              "type": "integer",
              "examples": [
                37
              ]
            },
            "slug": {
              "description": "The slug name of the GitHub app",
              "type": "string",
              "examples": [
                "probot-owners"
              ]
            },
            "node_id": {
              "type": "string",
              "examples": [
                "MDExOkludGVncmF0aW9uMQ=="
              ]
            },
            "owner": {
              "anyOf": [
                {
                  "type": "null"
                },
                {
                  "title": "Simple User",
                  "description": "A GitHub user.",
                  "type": "object",
                  "properties": {
                    "name": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "email": {
                      "type": [
                        "string",
                        "null"
                      ]
                    },
                    "login": {
                      "type": "string",
                      "examples": [
                        "octocat"
                      ]
                    },
                    "id": {
                      "type": "integer",
                      "examples": [
                        1
                      ]
                    },
                    "node_id": {
                      "type": "string",
                      "examples": [
                        "MDQ6VXNlcjE="
                      ]
                    },
                    "avatar_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/images/error/octocat_happy.gif"
                      ]
                    },
                    "gravatar_id": {
                      "type": [
                        "string",
                        "null"
                      ],
                      "examples": [
                        "41d064eb2195891e12d0413f63227ea7"
                      ]
                    },
                    "url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat"
                      ]
                    },
                    "html_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://github.com/octocat"
                      ]
                    },
                    "followers_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/followers"
                      ]
                    },
                    "following_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/following{/other_user}"
                      ]
                    },
                    "gists_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/gists{/gist_id}"
                      ]
                    },
                    "starred_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/starred{/owner}{/repo}"
                      ]
                    },
                    "subscriptions_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/subscriptions"
                      ]
                    },
                    "organizations_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/orgs"
                      ]
                    },
                    "repos_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/repos"
                      ]
                    },
                    "events_url": {
                      "type": "string",
                      "examples": [
                        "https://api.github.com/users/octocat/events{/privacy}"
                      ]
                    },
                    "received_events_url": {
                      "type": "string",
                      "format": "uri",
                      "examples": [
                        "https://api.github.com/users/octocat/received_events"
                      ]
                    },
                    "type": {
                      "type": "string",
                      "examples": [
                        "User"
                      ]
                    },
                    "site_admin": {
                      "type": "boolean"
                    },
                    "starred_at": {
                      "type": "string",
                      "examples": [
                        "\"2020-07-09T00:17:55Z\""
                      ]
                    }
                  },
                  "required": [
                    "avatar_url",
                    "events_url",
                    "followers_url",
                    "following_url",
                    "gists_url",
                    "gravatar_id",
                    "html_url",
                    "id",
                    "node_id",
                    "login",
                    "organizations_url",
                    "received_events_url",
                    "repos_url",
                    "site_admin",
                    "starred_url",
                    "subscriptions_url",
                    "type",
                    "url"
                  ]
                }
              ]
            },
            "name": {
              "description": "The name of the GitHub app",
              "type": "string",
              "examples": [
                "Probot Owners"
              ]
            },
            "description": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "The description of the app."
              ]
            },
            "external_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://example.com"
              ]
            },
            "html_url": {
              "type": "string",
              "format": "uri",
              "examples": [
                "https://github.com/apps/super-ci"
              ]
            },
            "created_at": {
              "type": "string",
              "format": "date-time",
              "examples": [
                "2017-07-08T16:18:44-04:00"
              ]
            },
            "updated_at": {
              "type": "string",
              "format": "date-time",
              "examples": [
                "2017-07-08T16:18:44-04:00"
              ]
            },
            "permissions": {
              "description": "The set of permissions for the GitHub app",
              "type": "object",
              "properties": {
                "issues": {
                  "type": "string"
                },
                "checks": {
                  "type": "string"
                },
                "metadata": {
                  "type": "string"
                },
                "contents": {
                  "type": "string"
                },
                "deployments": {
                  "type": "string"
                }
              },
              "additionalProperties": {
                "type": "string"
              },
              "example": {
                "issues": "read",
                "deployments": "write"
              }
            },
            "events": {
              "description": "The list of events for the GitHub app",
              "type": "array",
              "items": {
                "type": "string"
              },
              "examples": [
                "label",
                "deployment"
              ]
            },
            "installations_count": {
              "description": "The number of installations associated with the GitHub app",
              "type": "integer",
              "examples": [
                5
              ]
            },
            "client_id": {
              "type": "string",
              "examples": [
                "\"Iv1.25b5d1e65ffc4022\""
              ]
            },
            "client_secret": {
              "type": "string",
              "examples": [
                "\"1d4b2097ac622ba702d19de498f005747a8b21d3\""
              ]
            },
            "webhook_secret": {
              "type": [
                "string",
                "null"
              ],
              "examples": [
                "\"6fba8f2fc8a7e8f2cca5577eddd82ca7586b3b6b\""
              ]
            },
            "pem": {
              "type": "string",
              "examples": [
                "\"-----BEGIN RSA PRIVATE KEY-----\\nMIIEogIBAAKCAQEArYxrNYD/iT5CZVpRJu4rBKmmze3PVmT/gCo2ATUvDvZTPTey\\nxcGJ3vvrJXazKk06pN05TN29o98jrYz4cengG3YGsXPNEpKsIrEl8NhbnxapEnM9\\nJCMRe0P5JcPsfZlX6hmiT7136GRWiGOUba2X9+HKh8QJVLG5rM007TBER9/z9mWm\\nrJuNh+m5l320oBQY/Qq3A7wzdEfZw8qm/mIN0FCeoXH1L6B8xXWaAYBwhTEh6SSn\\nZHlO1Xu1JWDmAvBCi0RO5aRSKM8q9QEkvvHP4yweAtK3N8+aAbZ7ovaDhyGz8r6r\\nzhU1b8Uo0Z2ysf503WqzQgIajr7Fry7/kUwpgQIDAQABAoIBADwJp80Ko1xHPZDy\\nfcCKBDfIuPvkmSW6KumbsLMaQv1aGdHDwwTGv3t0ixSay8CGlxMRtRDyZPib6SvQ\\n6OH/lpfpbMdW2ErkksgtoIKBVrDilfrcAvrNZu7NxRNbhCSvN8q0s4ICecjbbVQh\\nnueSdlA6vGXbW58BHMq68uRbHkP+k+mM9U0mDJ1HMch67wlg5GbayVRt63H7R2+r\\nVxcna7B80J/lCEjIYZznawgiTvp3MSanTglqAYi+m1EcSsP14bJIB9vgaxS79kTu\\noiSo93leJbBvuGo8QEiUqTwMw4tDksmkLsoqNKQ1q9P7LZ9DGcujtPy4EZsamSJT\\ny8OJt0ECgYEA2lxOxJsQk2kI325JgKFjo92mQeUObIvPfSNWUIZQDTjniOI6Gv63\\nGLWVFrZcvQBWjMEQraJA9xjPbblV8PtfO87MiJGLWCHFxmPz2dzoedN+2Coxom8m\\nV95CLz8QUShuao6u/RYcvUaZEoYs5bHcTmy5sBK80JyEmafJPtCQVxMCgYEAy3ar\\nZr3yv4xRPEPMat4rseswmuMooSaK3SKub19WFI5IAtB/e7qR1Rj9JhOGcZz+OQrl\\nT78O2OFYlgOIkJPvRMrPpK5V9lslc7tz1FSh3BZMRGq5jSyD7ETSOQ0c8T2O/s7v\\nbeEPbVbDe4mwvM24XByH0GnWveVxaDl51ABD65sCgYB3ZAspUkOA5egVCh8kNpnd\\nSd6SnuQBE3ySRlT2WEnCwP9Ph6oPgn+oAfiPX4xbRqkL8q/k0BdHQ4h+zNwhk7+h\\nWtPYRAP1Xxnc/F+jGjb+DVaIaKGU18MWPg7f+FI6nampl3Q0KvfxwX0GdNhtio8T\\nTj1E+SnFwh56SRQuxSh2gwKBgHKjlIO5NtNSflsUYFM+hyQiPiqnHzddfhSG+/3o\\nm5nNaSmczJesUYreH5San7/YEy2UxAugvP7aSY2MxB+iGsiJ9WD2kZzTUlDZJ7RV\\nUzWsoqBR+eZfVJ2FUWWvy8TpSG6trh4dFxImNtKejCR1TREpSiTV3Zb1dmahK9GV\\nrK9NAoGAbBxRLoC01xfxCTgt5BDiBcFVh4fp5yYKwavJPLzHSpuDOrrI9jDn1oKN\\nonq5sDU1i391zfQvdrbX4Ova48BN+B7p63FocP/MK5tyyBoT8zQEk2+vWDOw7H/Z\\nu5dTCPxTIsoIwUw1I+7yIxqJzLPFgR2gVBwY1ra/8iAqCj+zeBw=\\n-----END RSA PRIVATE KEY-----\\n\""
              ]
            }
          },
          "required": [
            "id",
            "node_id",
            "owner",
            "name",
            "description",
            "external_url",
            "html_url",
            "created_at",
            "updated_at",
            "permissions",
            "events"
          ]
        }
      ]
    },
    "author_association": {
      "title": "author_association",
      "type": "string",
      "description": "How the author is associated with the repository.",
      "enum": [
        "COLLABORATOR",
        "CONTRIBUTOR",
        "FIRST_TIMER",
        "FIRST_TIME_CONTRIBUTOR",
        "MANNEQUIN",
        "MEMBER",
        "NONE",
        "OWNER"
      ],
      "examples": [
        "OWNER"
      ]
    },
    "reactions": {
      "title": "Reaction Rollup",
      "type": "object",
      "properties": {
        "url": {
          "type": "string",
          "format": "uri"
        },
        "total_count": {
          "type": "integer"
        },
        "+1": {
          "type": "integer"
        },
        "-1": {
          "type": "integer"
        },
        "laugh": {
          "type": "integer"
        },
        "confused": {
          "type": "integer"
        },
        "heart": {
          "type": "integer"
        },
        "hooray": {
          "type": "integer"
        },
        "eyes": {
          "type": "integer"
        },
        "rocket": {
          "type": "integer"
        }
      },
      "required": [
        "url",
        "total_count",
        "+1",
        "-1",
        "laugh",
        "confused",
        "heart",
        "hooray",
        "eyes",
        "rocket"
      ]
    }
  },
  "required": [
    "assignee",
    "closed_at",
    "comments",
    "comments_url",
    "events_url",
    "html_url",
    "id",
    "node_id",
    "labels",
    "labels_url",
    "milestone",
    "number",
    "repository_url",
    "state",
    "locked",
    "title",
    "url",
    "user",
    "author_association",
    "created_at",
    "updated_at"
  ]
}
'''
