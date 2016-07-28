# Lucene Server

This project provides a simple, example HTTP server on top of [Apache
Lucene](http://lucene.apache.org) version 6.x snapshot sources,
exposing many of Lucene's core and modules functionality efficiently
over a simple REST/JSON HTTP API.

Note that this code is all very new and likely has exciting bugs!  But
it's also very fast!

This server is running "in production" at [Jira
search](http://jirasearch.mikemccandless.com), a simple search
instance for developers to find Lucene, Solr and Tika jira issues
updated in near-real-time.

# Design

The design differs from the popular Lucene-based search servers
[Elasticsearch](https://www.elastic.co/products/elasticsearch) and
[Apache Solr](http://lucene.apache.org/solr) in that it is more of a
minimal, thin wrapper around Lucene's functions.  The goal is to only
expose functions that the Apache Lucene project already offers.  For
example, there is no "cluster" support, no aggregations (but there are
facets).

A single node can index documents, run near-real-time searches via
DSL or parsed query string, including "scrolled" searches, geo point
searches, highlighting, joins, sorting, index-time sorting, grouping,
faceting, etc.

Fields must first be registered with the `registerFields` command,
where you express whether you will search, sort, highlight, group,
etc., and then documents can be indexed with those fields.

There is no transaction log, so you must call commit yourself
periodically to make recent changes durable on disk.  This means that
if a node crashes, all indexed documents since the last commit are
lost.

# Bulk indexing via JSON or CSV

Lucene server supports a streaming bulk indexing API, which means you
make a single connection, and send the bytes over as either JSON,
using a chunked HTTP request, or as CSV, using a simple binary TCP
connection.

Inside the server, the incoming bytes are broken up and parsed into
documents concurrently based on how many cores are available.  In
performance tests indexing 1.2 billion documents in the [New York City
taxi ride
data](http://www.nyc.gov/html/tlc/html/about/trip_record_data.shtml),
a single python client (see below) sending bulk CSV documents to index
reaches almost the same performance as a raw standalone Lucene tool
indexing from the same source.

# Near-real-time replication

[Near-real-time index
replication](https://issues.apache.org/jira/browse/LUCENE-5438) allows
additional replica nodes on the network to copy newly created index
files from the primary node, in near-real-time.  This has some strong
benefits over document-based replication used by Elasticsearch and
Apache Solr:

  * No indexing cost on the replica nodes, just copying bytes for new
    files, and opening new near-real-time searchers

  * Consistent point-in-time searcher versions across primary and
    replicas, so that a follow-on search will see precisely the same
    point-in-time view even if it is sent to a different replica

But there are downsides as well:

  * Merged segments must also be copied

  * Additional time when opening a new searcher to copy the files across
    the network, since the primary must first write the files, and
    then each replica must copy them.

# Build and install

This has only been tested on Linux:

To run the server, run `./build.py package`, which will build the
installable bits at `build/luceneserver-0.1.0-SNAPSHOT.zip`.

Unzip that somewhere, `cd luceneserver-0.1.0-SNAPSHOT` and run `java
-cp "lib/*" org.apache.lucene.server.Server`.  Make sure you put
double quotes around that `"lib/*"` so java sees that asterisk and not
your shell!

# Live documentation

Once the server is running, load `http://localhost:4000/docs` to see
minimial documentation of all REST commands and their accepted
parameters.

# Example indexing tool

The `scripts/indexTaxis.py` shows an example of using a Python client
to bulk-index documents from the [New York City taxi ride
data](http://www.nyc.gov/html/tlc/html/about/trip_record_data.shtml),
optionally spawning replicas as well.  It will build the release
artifact, install it, launch it, download the taxis document source
(first 1 M documents), and index them.
