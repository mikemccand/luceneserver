# Lucene Server

This project provides a simple, example HTTP server on top of [Apache
Lucene](http://lucene.apache.org) sources, exposing most of Lucene's
core and modules functionality efficiently over a REST API.

The design differs from the popular Lucene search servers
[Elasticsearch](https://www.elastic.co/products/elasticsearch) and
[Apache Solr](http://lucene.apache.org/solr) in that it is more of a
thin wrapper around Lucene's functions.

For example, there is limited distributed support, except for
[near-real-time index
replication](https://issues.apache.org/jira/browse/LUCENE-5438).
There is no transaction log, so you must call commit yourself
periodically to make changes durable on disk.

This server is running "in production" at [Jira
search](http://jirasearch.mikemccandless.com), a simple search
instance to find Lucene jira issues updated in near-real-time.

To run the server:

  * clone this project

  * cd <clone directory>

  * python3 -u build.py package

This creates a packaged zip file
`build/luceneserver-0.1.0-SNAPSHOT.zip`.  Unzip that somewhere, `cd
luceneserver-0.1.0-SNAPSHOT` and run `java -cp "lib/*"
org.apache.lucene.server.Server`.  Make sure you put double quotes
around that "lib/*" so java sees that asterisk and not your shell!
