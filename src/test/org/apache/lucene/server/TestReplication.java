package org.apache.lucene.server;

/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Locale;

import org.apache.lucene.document.Document;
import org.apache.lucene.util.LineFileDocs;
import org.apache.lucene.util.TestUtil;
import org.junit.AfterClass;
import org.junit.BeforeClass;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

public class TestReplication extends ServerBaseTestCase {

  public void testBasic() throws Exception {
    Path dir1 = createTempDir("server1");
    rmDir(dir1);
    RunServer server1 = new RunServer("server1", dir1);

    Path dir2 = createTempDir("server1");
    rmDir(dir2);
    RunServer server2 = new RunServer("server2", dir2);

    Path primaryPath = createTempDir("indexPrimary");
    rmDir(primaryPath);

    Path replicaPath = createTempDir("indexReplica");
    rmDir(replicaPath);

    try {

      server1.send("createIndex", "{indexName: index, rootDir: " + primaryPath.toAbsolutePath() + "}");
      server2.send("createIndex", "{indexName: index, rootDir: " + replicaPath.toAbsolutePath() + "}");

      server1.send("liveSettings", "{indexName: index, minRefreshSec: 0.001}");
      server2.send("liveSettings", "{indexName: index, minRefreshSec: 0.001}");

      JSONObject o = new JSONObject();
      put(o, "body", "{type: text, highlight: true, store: true, analyzer: {class: StandardAnalyzer}, similarity: {class: BM25Similarity, b: 0.15}}");
      JSONObject o2 = new JSONObject();
      o2.put("indexName", "index");
      o2.put("fields", o);
      server1.send("registerFields", o2);
      server2.send("registerFields", o2);
      
      server1.send("startIndex", "{indexName: index, mode: primary, primaryGen: 0}");

      // add one doc primary
      server1.send("addDocument", "{indexName: index, fields: {body: 'here is a test'}}");
      server1.send("refresh", "{indexName: index}");
      JSONObject result = server1.send("search", "{indexName: index, queryText: test, retrieveFields: [body]}");

      server2.send("startIndex", "{indexName: index, mode: replica, primaryAddress: \"127.0.0.1\", primaryGen: 0, primaryPort: " + server1.binaryPort + "}");

      // nocommit do we need a replica command to pull latest nrt point w/o having primary write a new one?  or maybe replica on start
      // should do this before opening for business?

      // add 2nd doc to primary
      server1.send("addDocument", "{indexName: index, fields: {body: 'here is a test'}}");

      // publish new NRT point
      result = server1.send("writeNRTPoint", "{indexName: index}");

      int version = getInt(result, "version");

      // primary should show 2 hits now
      result = server1.send("search", "{indexName: index, queryText: test, retrieveFields: [body], searcher: {version: " + version + "}}");
      assertEquals(2, getInt(result, "totalHits"));
      
      // replica should too!
      result = server2.send("search", "{indexName: index, queryText: test, retrieveFields: [body], searcher: {version: " + version + "}}");
      assertEquals(2, getInt(result, "totalHits"));

      // nocommit need to get SLM to always register every searcher version?

    } finally {
      System.out.println("TEST: now shutdown");
      server1.shutdown();
      server2.shutdown();
      System.out.println("TEST: done shutdown");
    }
  }

  public void testIndexing() throws Exception {

    Path dir1 = createTempDir("server1");
    rmDir(dir1);
    RunServer server1 = new RunServer("server1", dir1);

    Path dir2 = createTempDir("server1");
    rmDir(dir2);
    RunServer server2 = new RunServer("server2", dir2);

    Path primaryPath = createTempDir("indexPrimary");
    rmDir(primaryPath);

    Path replicaPath = createTempDir("indexReplica");
    rmDir(replicaPath);

    LineFileDocs docs = new LineFileDocs(random());
    
    try {

      server1.send("createIndex", "{indexName: index, rootDir: " + primaryPath.toAbsolutePath() + "}");
      server2.send("createIndex", "{indexName: index, rootDir: " + replicaPath.toAbsolutePath() + "}");

      //server1.send("settings", "{indexName: index, index.verbose: true}");
      //server2.send("settings", "{indexName: index, index.verbose: true}");
      
      server1.send("liveSettings", "{indexName: index, minRefreshSec: 0.001}");
      server2.send("liveSettings", "{indexName: index, minRefreshSec: 0.001}");

      JSONObject o = new JSONObject();
      put(o, "body", "{type: text, highlight: true, store: true, analyzer: {class: StandardAnalyzer}, similarity: {class: BM25Similarity, b: 0.15}}");
      put(o, "title", "{type: text, highlight: true, store: true, analyzer: {class: WhitespaceAnalyzer}, similarity: {class: BM25Similarity, b: 0.15}}");
      put(o, "id", "{type: int, store: true, sort: true}");

      JSONObject o2 = new JSONObject();
      o2.put("indexName", "index");
      o2.put("fields", o);
      server1.send("registerFields", o2);
      server2.send("registerFields", o2);

      server1.send("startIndex", "{indexName: index, mode: primary, primaryGen: 0}");
      server2.send("startIndex", "{indexName: index, mode: replica, primaryAddress: \"127.0.0.1\", primaryGen: 0, primaryPort: " + server1.binaryPort + "}");

      int id = 0;
      int lastSearchCount = 0;
      
      for(int i=0;i<100;i++) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"indexName\": \"index\", \"documents\": [");
        for(int j=0;j<100;j++) {
          Document doc = docs.nextDoc();
          JSONObject fields = new JSONObject();
          fields.put("title", doc.get("titleTokenized"));
          fields.put("body", doc.get("body"));
          fields.put("id", id++);
          o = new JSONObject();
          o.put("fields", fields);
          if (j > 0) {
            sb.append(',');
          }
          sb.append(o.toString());
        }
        sb.append("]}");
        String s = sb.toString();
        JSONObject result = server1.sendChunked(s, "bulkAddDocument");
        assertEquals(100, result.get("indexedDocumentCount"));

        result = server2.send("search", "{indexName: index, queryText: '*:*', retrieveFields: [body]}");
        //System.out.println("GOT: " + result);
        int searchCount = getInt(result, "totalHits");
        if (searchCount != lastSearchCount) {
          System.out.println("TEST: search count " + searchCount + ", version " + getLong(result, "searchState.searcher"));
          lastSearchCount = searchCount;
        }
      }

      // make sure replica reflects all indexed docs:
      JSONObject result = server1.send("writeNRTPoint", "{indexName: index}");
      long version = getLong(result, "version");
      result = server2.send("search", "{indexName: index, queryText: '*:*', retrieveFields: [body], searcher: {version: " + version + "}}");
      assertEquals(100*100, getInt(result, "totalHits"));
      System.out.println("TEST: done");

    } finally {
      // shutdown replica before primary:
      server2.shutdown();
      server1.shutdown();
    }
  }
}
