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

public class TestSearch2 extends ServerBaseTestCase {

  public void testBasic() throws Exception {
    Path dir1 = createTempDir("server1");
    rmDir(dir1);
    RunServer server1 = new RunServer(random(), "server1", dir1);

    Path dir2 = createTempDir("server1");
    rmDir(dir2);
    RunServer server2 = new RunServer(random(), "server2", dir2);

    // Tell the nodes about each other
    server1.send("linkNode", "{remoteBinaryAddress: \"127.0.0.1\", remoteBinaryPort: " + server2.binaryPort + "}");
    server2.send("linkNode", "{remoteBinaryAddress: \"127.0.0.1\", remoteBinaryPort: " + server1.binaryPort + "}");

    Path index1Path = createTempDir("index1");
    rmDir(index1Path);

    Path index2Path = createTempDir("index2");
    rmDir(index2Path);

    try {

      server1.send("createIndex", "{indexName: index1, rootDir: " + index1Path.toAbsolutePath() + "}");
      server2.send("createIndex", "{indexName: index2, rootDir: " + index2Path.toAbsolutePath() + "}");

      server1.send("startIndex", "{indexName: index1}");
      server2.send("startIndex", "{indexName: index2}");

      JSONObject o = new JSONObject();
      put(o, "title", "{type: text, highlight: true, store: true}");
      put(o, "id", "{type: atom, store: true}");
      JSONObject o2 = new JSONObject();
      o2.put("fields", o);
      o2.put("indexName", "index1");
      server1.send("registerFields", o2);

      o = new JSONObject();
      put(o, "title", "{type: text, highlight: true, store: true}");
      put(o, "id", "{type: atom, store: true}");
      o2 = new JSONObject();
      o2.put("fields", o);
      o2.put("indexName", "index2");
      server2.send("registerFields", o2);

      server1.send("addDocument", "{indexName: index1, fields: {title: 'here is a test', id: '0'}}");
      server1.send("addDocument", "{indexName: index1, fields: {title: 'here is a nontest', id: '0'}}");
      server1.send("refresh", "{indexName: index1}");

      server2.send("addDocument", "{indexName: index2, fields: {title: 'here is a test', id: '0'}}");
      server2.send("addDocument", "{indexName: index2, fields: {title: 'here is a nontest', id: '0'}}");      
      server2.send("refresh", "{indexName: index2}");

      for(int i=0;i<10;i++) {
        RunServer server;
        if (i % 2 == 0) {
          server = server1;
        } else {
          server = server2;
        }
        JSONObject result = server.send("search2", "{queryText: test, indexNames: [index1, index2]}");
      }

    } finally {
      System.out.println("TEST: now shutdown");
      server1.shutdown();
      server2.shutdown();
      System.out.println("TEST: done shutdown");
    }
  }
}
