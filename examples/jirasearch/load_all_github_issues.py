import github
import datetime
import pprint
import requests
import time
import os
import sys
import urllib.parse
import pickle
import sqlite3
from contextlib import closing
from util import get_or_none

# TODO
#   - how to resume full crawl after process exits?  need to be able to pass 'page' param down?
#   - how also to get closed issues
#   - how to safely fully scroll for full crawl
#   - test since arg for incremental crawl
#   - extract old Jira metadata in the first comment
#   - if it's named user, use name?

# docs:
#  https://pygithub.readthedocs.io/en/latest/introduction.html
#  https://docs.github.com/en/rest/issues?apiVersion=2022-11-28
#  PyGithub installed here: /Users/mike/Library/Python/3.9/lib/python/site-packages/github

username = 'mikemccand'

DB_PATH = 'github_issues.db'

url = f'https://github.com/apache/lucene/issues'

def create_db(db):
    print('Now create DB!')
    c = db.cursor()
    #c.execute('DROP TABLE issues')
    c.execute('CREATE TABLE issues (key TEXT UNIQUE PRIMARY KEY, pickle BLOB)')
    c.execute('INSERT INTO issues VALUES (?, ?)', ('last_update', pickle.dumps(None)))
    c.execute('INSERT INTO issues VALUES (?, ?)', ('next_url', pickle.dumps(None)))
    db.commit()
    return db

def load_full_issue(issue):
    title = issue.title
    body = issue.body
    state = issue.state
    number = issue.number
    labels = list(issue.get_labels())
    events = list(issue.get_events())
    comments = list(issue.get_comments())
    reactions = list(issue.get_reactions())
    timeline = list(issue.get_timeline())
    assignee = get_or_none(issue.assignee, 'login')

    # TODO: what about assignees?!

    milestone_id = get_or_none(issue.milestone, 'id')

    # TODO: is this really reporter?
    user = issue.user.login

    creator = get_or_none(get_or_none(issue, 'creator'), 'login')

    locked = issue.locked
    active_lock_reason = issue.active_lock_reason

    is_pr = issue.pull_request is not None
    created_at = issue.created_at
    updated_at = issue.updated_at
    closed_at = issue.closed_at

    # WTF is this?
    author_association = get_or_none(issue, 'author_association')

    print(f'\nissue: number={number} {issue} created={created_at} updated={updated_at} closed_at={closed_at}')
    print(f'  creator: {creator}')
    print(f'  assignee: {assignee}')    
    print(f'  user: {user}')
    print(f'  is_pr?: {is_pr}')
    print(f'  body: {issue.body}')

    for label in labels:
        print(f'  {label}')

    comment_reactions = []
    for comment in comments:
        print(f'  comment: {comment.user} {comment.created_at} {comment.updated_at} {comment.url}\n    {comment.body}')
        #if hasattr(comment, 'reactions') and comment.reactions.total_count > 0:
        if True:
            comment_reactions.append(list(comment.get_reactions()))
            for comment_reaction in comment_reactions[-1]:
                print(f'    got comment reaction: {comment_reaction.user.login} {comment_reaction.content} {comment_reaction.created_at}')
        else:
            comment_reactions.append([])

    for event in events:
      #print(f'event: {event.actor.login} {event.event} {event.created_at} {event.label} {event.assignee} {event.assigner} {event.review_requester} {event.requested_reviewer} {event.dismissed_review} {event.team} {event.milestone} {event.rename} {event.lock_reason}')
      print(f'event: {event.actor.login} {event.event} {event.created_at} {event.label} {event.assignee} {event.assigner} {event.review_requester} {event.requested_reviewer} {event.dismissed_review} {event.milestone} {event.rename} {event.lock_reason}')

    for reaction in reactions:
      print(f'  reaction: {reaction.user} {reaction.content} {reaction.created_at}')

    return labels, comments, comment_reactions, events, reactions, timeline

def main(g, db):

    c = db.cursor()
    with closing(db):
        count = c.execute('SELECT COUNT(*) FROM issues').fetchone()[0]
        print(f'\n\n{count-2} issues in DB')

        repo = g.get_repo('apache/lucene')

        # force rate limit check at startup
        last_rate_limit_sec = 0

        row = c.execute('SELECT pickle FROM issues WHERE key="next_url"').fetchone()
        last_next_url = pickle.loads(row[0])
        print(f'resume from last_next_url {last_next_url}')

        issues = repo.get_issues(state='all', sort='created', direction='asc', first_url_string=last_next_url)

        print(f'total count: {issues.totalCount}')

        for count, issue in enumerate(issues):

            now = time.time()
            if now - last_rate_limit_sec > 20:
                rate_limit = g.get_rate_limit()
                print(f'\n\nRate limit: {rate_limit.core}')
                last_rate_limit_sec = now

            labels, comments, comment_reactions, events, reactions, timeline = load_full_issue(issue)

            c.execute('REPLACE INTO issues (key, pickle) VALUES (?, ?)',
                      (str(issue['number']), pickle.dumps((issue, labels, comments, comment_reactions, events, reactions, timeline))))

            next_url = issues._PaginatedList__nextUrl
            if next_url != last_next_url:
                # only write the LAST next_url when we see a new next_url so that if we interrupt we will re-load the possibly
                # partially saved page
                if last_next_url is not None:
                    print(f'Now save next_url: {last_next_url}')
                    c.execute('INSERT OR REPLACE INTO issues (key, pickle) VALUES (?, ?)', ('next_url', pickle.dumps(last_next_url)))
                last_next_url = next_url
                db.commit()


if __name__ == '__main__':

    do_create = '-create' in sys.argv
    if do_create:
        sys.argv.remove('-create')
        if os.path.exists(DB_PATH):
            raise RuntimeError(f'please first remove DB {DB_PATH} with -create')
    db = sqlite3.connect(DB_PATH)

    if do_create:
       create_db(db)
        
    github_token = sys.argv[1]
    print(f'use github token {github_token}')
    g = github.Github(github_token)
    while True:
        try:
            main(g, db)
        except github.RateLimitExceededException:

            print('\nNow rate limit...')
            rate_limit = g.get_rate_limit()

            t0 = time.time()
            while True:
                time.sleep(60)
                now = time.time()
                rate_limit = g.get_rate_limit()
                print(f'{(now - t0):.2f}s: {rate_limit.core}')
                last_rate_limit_sec = now
                if rate_limit.core.remaining > 4000:
                    break
            t1 = time.time()
            print(f'\nNow resume after {(now - t0):.2f} second wait')
            db = sqlite3.connect(DB_PATH)
        else:
            # main already closes db:
            #db.commit()
            #db.close()
            print('All done!')
            break


