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
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

import org.junit.AfterClass;
import org.junit.BeforeClass;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

public class TestSnapshots extends ServerBaseTestCase {
  
  @BeforeClass
  public static void initClass() throws Exception {
    useDefaultIndex = true;
    startServer();
    createAndStartIndex("index");
    registerFields();
    commit();
  }

  @AfterClass
  public static void fini() throws Exception {
    shutdownServer();
  }

  private static void registerFields() throws Exception {
    send("registerFields", "{fields: {body: {type: text, analyzer: {class: EnglishAnalyzer}}, id: {type: atom, store: true}, facet: {type: atom, search: false, facet: flat}}}");
  }

  public void testBasic() throws Exception {
    deleteAllDocs();

    // Add one doc:
    JSONObject o = send("addDocument", "{fields: {body: 'here is the body', id: '0', facet: 'facet'}}");
    long indexGen = ((Number) o.get("indexGen")).longValue();
    commit();

    o = send("search", "{queryText: 'body:body', searcher: {indexGen:" + indexGen + "}}");
    assertEquals(1, o.get("totalHits"));

    // Take snapshot before making some changes:
    JSONObject result = send("createSnapshot");
    String snapshotID = getString(result, "id");

    // Delete first doc, register new field, add two more docs:
    send("deleteDocuments", "{field: id, values: ['0']}");
    send("registerFields", "{fields: {field: {type: 'atom'}}}");
    send("addDocument", "{fields: {body: 'here is the body', id: '1', facet: 'facet2', field: 'abc'}}");
    send("addDocument", "{fields: {body: 'here is the body', id: '2', facet: 'facet2', field: 'abc'}}");
    long indexGen2 = getLong("indexGen");
    commit();

    Path backupDir = createTempDir("backup");

    // Make sure all files in the snapshot still exist, even
    // though we deleted that segment, and make a backup:
    try {
      for(Map.Entry<String,Object> ent : result.entrySet()) {
        if (ent.getKey().equals("id")) {
          continue;
        }

        // nocommit messy:
        Path dirPath;
        if (ent.getKey().equals("state")) {
          dirPath = server.curIndexPath.resolve(ent.getKey());
        } else {
          dirPath = server.curIndexPath.resolve("shard0").resolve(ent.getKey());
        }
        
        Path destDir = backupDir.resolve(ent.getKey());
        Files.createDirectories(destDir);
        for (Object sub : ((JSONArray) ent.getValue())) {
          String fileName = (String) sub;
          Path sourceFile = dirPath.resolve(fileName);
          assertTrue("file " + sourceFile + " does not exist", Files.exists(sourceFile));
          copyFile(sourceFile, destDir.resolve(fileName));
          //System.out.println("copied to " + new File(destDir, fileName));
        }
      }

      // Make sure we can search the snapshot and only get 1 hit:
      send("search", "{retrieveFields: [id], searcher: {snapshot: \"" + snapshotID + "\"}, query: MatchAllDocsQuery}");
      assertEquals(1, getInt("totalHits"));
      assertEquals("0", getString("hits[0].fields.id"));

      // Make sure we can search the current searcher and we
      // get 2 hits:
      send("search", "{retrieveFields: [id], searcher: {indexGen: " + indexGen2 + "}, query: MatchAllDocsQuery}");
      assertEquals(2, getInt("totalHits"));

      // Bounce the server:
      bounceServer();
      send("startIndex");

      // Make sure we can search the snapshot and still only get 1 hit:
      send("search", "{retrieveFields: [id], searcher: {snapshot: \"" + snapshotID + "\"}, query: MatchAllDocsQuery}");
      assertEquals(1, getInt("totalHits"));
      assertEquals("0", getString("hits[0].fields.id"));

      // Make sure we can search the current searcher and we
      // get 2 hits:
      send("search", "{retrieveFields: [id], query: MatchAllDocsQuery}");
      assertEquals(2, getInt("totalHits"));

      // Make sure files still exist (snapshot persisted):
      for(Map.Entry<String,Object> ent : result.entrySet()) {
        if (ent.getKey().equals("id")) {
          continue;
        }

        // nocommit messy:
        Path dirPath;
        if (ent.getKey().equals("state")) {
          dirPath = server.curIndexPath.resolve(ent.getKey());
        } else {
          dirPath = server.curIndexPath.resolve("shard0").resolve(ent.getKey());
        }
        
        for (Object sub : ((JSONArray) ent.getValue())) {
          String fileName = (String) sub;
          Path sourceFile = dirPath.resolve(fileName);
          assertTrue(Files.exists(sourceFile));
        }
      }

      // Make sure we can still search the snapshot:
      send("search", "{retrieveFields: [id], searcher: {snapshot: \"" + snapshotID + "\"}, query: MatchAllDocsQuery}");
      assertEquals(1, getInt("totalHits"));
      assertEquals("0", getString("hits[0].fields.id"));

      // Now, release the snapshot:
      send("releaseSnapshot", "{id: \"" + snapshotID + "\"}");

      // Make sure some files in the snapshot are now gone:
      boolean someGone = false;
      for(Map.Entry<String,Object> ent : result.entrySet()) {
        if (ent.getKey().equals("id")) {
          continue;
        }
        String dirPath = ent.getKey();
        for (Object sub : ((JSONArray) ent.getValue())) {
          String fileName = (String) sub;
          if (!(new File(dirPath, fileName)).exists()) {
            someGone = true;
          }
        }
      }
      assertTrue(someGone);

      // Restart server against the backup image:
      bounceServer();
      send("startIndex");

      // Make sure search is working, and both docs are visible:
      o = send("search", "{queryText: 'body:body'}");
      assertEquals(2, o.get("totalHits"));

    } finally {
      rmDir(backupDir);
    }
  }

  // TODO: threaded test, taking snapshot while threads are
  // adding/deleting/committing
}
