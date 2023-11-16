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

import java.io.IOException;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Locale;

import org.junit.AfterClass;
import org.junit.BeforeClass;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

public class TestServer extends ServerBaseTestCase {

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
    JSONObject o = new JSONObject();
    put(o, "body", "{type: text, highlight: true, store: true, analyzer: {class: StandardAnalyzer}, similarity: {class: BM25Similarity, b: 0.15}}");
    put(o, "id", "{type: int, store: true}");
    put(o, "price", "{type: float, sort: true, search: true, store: true}");
    put(o, "date", "{type: atom, search: false, store: true}");
    put(o, "dateFacet", "{type: atom, search: false, store: false, facet: hierarchy}");
    put(o, "author", "{type: text, search: false, facet: flat, group: true}");
    JSONObject o2 = new JSONObject();
    o2.put("indexName", "index");
    o2.put("fields", o);
    send("registerFields", o2);
  }

  // nocommit multi-valued field

  // Returns gen for the added document
  private long addDocument(int id, String author, String body, float price, String date) throws Exception {
    JSONObject o = new JSONObject();
    o.put("body", body);
    o.put("author", author);
    o.put("price", price);
    o.put("id", id);
    o.put("date", date);
    JSONArray path = new JSONArray();
    o.put("dateFacet", path);
    for(String part : date.split("/")) {
      path.add(part);
    }

    JSONObject o2 = new JSONObject();
    o2.put("fields", o);
    o2.put("indexName", "index");

    JSONObject result = send("addDocument", o2);
    return ((Number) result.get("indexGen")).longValue();
  }

  private JSONObject search(String body) throws Exception {
    return search(body, -1, null, false, true, null, null);
  }

  private JSONObject search(String query, long indexGen, String sortField, boolean reversed, boolean snippets, String groupField, String groupSortField) throws Exception {
    JSONObject o = new JSONObject();
    o.put("indexName", "index");
    o.put("queryText", query);
    if (indexGen != -1) {
      JSONObject o2 = new JSONObject();
      o.put("searcher", o2);
      o2.put("indexGen", indexGen);
    }

    if (sortField != null) {
      JSONObject sort = new JSONObject();
      o.put("sort", sort);
      // sort.put("doDocScores", true);

      JSONArray sortFields = new JSONArray();
      sort.put("fields", sortFields);

      JSONObject o2 = new JSONObject();
      sortFields.add(o2);

      o2.put("field", sortField);
      o2.put("reverse", reversed);
    }

    if (groupField != null) {
      String s = "{field: '" + groupField + "'";
      if (groupSortField != null) {
        s += ", sort: [{field: '" + groupSortField + "'}]";
      }
      s += "}";
      put(o, "grouping", s);
    }

    put(o, "facets", "[{dim: dateFacet, topN: 10}]");
    put(o, "retrieveFields", "[id, date, price, {field: body, highlight: " + (snippets ? "snippets" : "whole") + "}]");

    return send("search", o);
  }

  public void testBasic() throws Exception {
    deleteAllDocs();
    long gen = addDocument(0, "Bob", "this is a test", 10f, "2012/10/17");
    JSONObject o = search("test", gen, null, false, true, null, null);
    assertEquals(1, getInt(o, "totalHits.value"));
  }

  public void testUnusedParamsAreCaught() throws Exception {
    deleteAllDocs();
    long gen = addDocument(0, "Bob", "this is a test", 10f, "2012/10/17");
    JSONObject o = new JSONObject();
    o.put("indexName", "index");
    o.put("queryText", "*:*");
    o.put("extra", 17);
    Exception e = expectThrows(IOException.class, () -> {send("search", o);});
    //e.printStackTrace(System.out);
    assertTrue(e.toString().contains("param extra is unrecognized"));
  }

  public void testNumericSort() throws Exception {
    deleteAllDocs();
    addDocument(0, "Lisa", "this is a test", 10.99f, "2012/10/1");
    long gen = addDocument(1, "Tom", "this is also a test", 14.99f, "2012/11/3");
    JSONObject o = search("test", gen, "price", false, true, null, null);
    assertEquals(2, getInt(o, "totalHits.value"));
    JSONArray hits = (JSONArray) o.get("hits");
    assertEquals(2, hits.size());

    JSONObject hit = (JSONObject) hits.get(0);
    assertEquals(0, ((JSONObject) hit.get("fields")).get("id"));

    hit = (JSONObject) hits.get(1);
    assertEquals(1, ((JSONObject) hit.get("fields")).get("id"));
  }

  public void testReverseNumericSort() throws Exception {
    deleteAllDocs();
    addDocument(0, "Frank", "this is a test", 10.99f, "2012/10/1");
    long gen = addDocument(1, "Lisa", "this is also a test", 14.99f, "2012/11/3");
    JSONObject o = search("test", gen, "price", true, true, null, null);
    assertEquals(2, getInt(o, "totalHits.value"));

    JSONArray hits = (JSONArray) o.get("hits");
    assertEquals(2, hits.size());

    JSONObject hit = (JSONObject) hits.get(0);
    assertEquals(1, ((JSONObject) hit.get("fields")).get("id"));

    hit = (JSONObject) hits.get(1);
    assertEquals(0, ((JSONObject) hit.get("fields")).get("id"));
  }

  public void testPrevSearchState() throws Exception {
    deleteAllDocs();
    long gen = addDocument(0, "Tom", "this is a test.  here is a random sentence.  here is another sentence with test in it.", 10.99f, "2012/10/17");

    JSONObject o = search("test", gen, null, false, false, null, null);
    assertEquals(1, getInt(o, "totalHits.value"));

    // Add another document
    gen = addDocument(0, "Melanie", "this is a test.  here is a random sentence.  here is another sentence with test in it.", 10.99f, "2012/10/17");

    JSONObject o2 = search("test", gen, null, false, false, null, null);
    assertEquals(2, getInt(o2, "totalHits.value"));

    // Now the first search does a follow-on search, so we
    // should only see 1 document since it should be using
    // the old searcher:
    JSONObject o3 = new JSONObject();
    o3.put("indexName", "index");
    o3.put("queryText", "test");
    put(o3, "searcher", "{version: " + get(o, "searchState.searcher") + "}");
    //System.out.println("send: " + o3);
    JSONObject o4 = send("search", o3);

    assertEquals(1, getInt(o4, "totalHits.value"));
  }

  public void testInvalidFields() throws Exception {
    deleteAllDocs();
    addDocument(0, "Lisa", "this is a test.  here is a random sentence.  here is another sentence with test in it.", 10.99f, "2012/10/17");

    JSONObject o3 = new JSONObject();
    o3.put("queryText", "test");
    JSONArray fields = new JSONArray();
    o3.put("retrieveFields", fields);
    fields.add("bogus");
    try {
      send("search", o3);
      fail("did not hit exception");
    } catch (IOException e) {
      // expected
    }

    o3 = new JSONObject();
    o3.put("queryText", "test");
    JSONObject sort = new JSONObject();
    o3.put("sort", sort);
    JSONArray sortFields = new JSONArray();
    sort.put("fields", sortFields);
    
    JSONObject sortField = new JSONObject();
    sortFields.add(sortField);
    sortField.put("field", "bogus2");
    try {
      send("search", o3);
      fail("did not hit exception");
    } catch (IOException e) {
      // expected
    }
  }

  public void testInvalidSearcherVersion() throws Exception {
    deleteAllDocs();

    JSONObject o3 = new JSONObject();
    o3.put("queryText", "test");
    JSONObject searchState = new JSONObject();
    put(o3, "searcher", "{version: 0}");
    String message = expectThrows(IOException.class, () -> {send("search", o3);}).getMessage();
    assertTrue(message.contains("search > searcher: This searcher has expired"));
  }

  public void testMultiValuedString() throws Exception {
    deleteAllDocs();

    send("registerFields", "{fields: {authors: {type: text, search: true, store: true, facet: flat, multiValued: true, analyzer: {class: StandardAnalyzer}}}}");

    JSONObject result = send("addDocument", "{fields: {authors: [Bob, Lisa]}}");

    long indexGen = getInt(result, "indexGen");

    result = send("search", "{searcher: {indexGen: " + indexGen + "}, queryText: 'authors:bob', retrieveFields: [authors]}");

    assertEquals(1, getInt(result, "totalHits.value"));
    assertEquals("[\"Bob\",\"Lisa\"]", getArray(result, "hits[0].fields.authors").toString());
  }

  public void testMultiValuedNumeric() throws Exception {
    deleteAllDocs();

    send("registerFields", "{fields: {ratings: {type: int, search: true, store: true, multiValued: true}}}");

    JSONObject result = send("addDocument", "{fields: {body: 'here is a test', ratings: [17, 22]}}");

    long indexGen = getInt(result, "indexGen");

    result = send("search", "{searcher: {indexGen: " + indexGen + "}, queryText: 'body:test', retrieveFields: [ratings]}");

    assertEquals(1, getInt(result, "totalHits.value"));
    assertEquals("[17,22]", getArray(result, "hits[0].fields.ratings").toString());
  }

  public void testStandardAnalyzer() throws Exception {
    deleteAllDocs();

    send("registerFields", "{fields: {aTextField: {type: text, analyzer: {class: StandardAnalyzer}, store: true}}}");

    JSONObject result = send("addDocument", "{fields: {aTextField: 'here is a test'}}");
    long indexGen = getInt(result, "indexGen");

    // nocommit: grrr need QP to understand schema
    //o.put("queryText", "ratings:[16 TO 18]");

    // search on a stop word should yield no results:
    result = send("search", String.format(Locale.ROOT, "{searcher: {indexGen: %d}, queryText: 'aTextField:a'}", indexGen));
    assertEquals(0, getInt(result, "totalHits.value"));
  }

  public void testStandardAnalyzerNoStopWords() throws Exception {
    deleteAllDocs();

    send("registerFields", "{fields: {aTextField2: {type: text, search: true, store: true, analyzer: {class: StandardAnalyzer, stopWords: []}}}}");

    JSONObject result = send("addDocument", "{fields: {aTextField2: 'here is a test'}}");
    long indexGen = getLong(result, "indexGen");

    // nocommit: grrr need QP to understand schema
    //o.put("queryText", "ratings:[16 TO 18]");

    // search on a stop word should now yield one hit:
    result = send("search", "{queryText: 'aTextField2:a', searcher: {indexGen: " + indexGen + "}}");
    assertEquals(1, getInt(result, "totalHits.value"));
  }

  public void testEnglishAnalyzerNoStopWords() throws Exception {
    deleteAllDocs();

    send("registerFields", "{fields: {aTextField3: {type: text, search: true, store: true, analyzer: {class: EnglishAnalyzer, stopWords: []}}}}");
    JSONObject result = send("addDocument", "{fields: {aTextField3: 'the cats in the hat'}}");
    long indexGen = getLong(result, "indexGen");

    // nocommit: grrr need QP to understand schema
    //o.put("queryText", "ratings:[16 TO 18]");

    // cats should stem to cat and get a match:
    result = send("search", "{queryText: 'aTextField3:cat', searcher: {indexGen: " + indexGen + "}}");
    assertEquals(1, getInt(result, "totalHits.value"));
  }

  public void testInvalidFieldName() throws Exception {
    JSONObject o = new JSONObject();
    JSONObject o2 = new JSONObject();
    o.put("9", o2);
    o2.put("type", "text");
    try {
      send("registerFields", o);
      fail();
    } catch (IOException ioe) {
      // expected
    }
  }

  public void testMoreThanOneValueOnSingleValuedField() throws Exception {
    deleteAllDocs();
    JSONObject o = new JSONObject();
    JSONArray arr = new JSONArray();
    o.put("author", arr);
    arr.add("Author 1");
    arr.add("Author 2");

    try {
      send("addDocument", o);
      fail("expected exception");
    } catch (IOException ioe) {
      // expected
    }
  }

  public void testServerRestart() throws Exception {
    deleteAllDocs();
    addDocument(0, "Bob", "this is a test", 10f, "2012/10/17");
    send("commit");
    bounceServer();
    send("startIndex");
    JSONObject o = search("test", 0, null, false, true, null, null);
    assertEquals(1, getInt(o, "totalHits.value"));
  }

  public void testStatsHandler() throws Exception {
    JSONObject result = send("stats");
    //System.out.println("GOT: " + result);
  }

  public void testStuffAfterJSON() throws Exception {
    // Extra whitespace should be OK:
    sendRaw("stats", "{\"indexName\": \"index\"}  ");
    
    // ... but this should not:
    try {
      sendRaw("stats", "{\"indexName\": \"index\"}  bogus");
      fail("did not hit exception");
    } catch (IOException ioe) {
      // expected
      assertTrue(ioe.toString().indexOf("could not parse HTTP request data as JSON") != -1);
    }
  }

  public void testTenIndices() throws Exception {
    stopIndex("index");
    deleteIndex("index");
    for(int i=0;i<10;i++) {
      createAndStartIndex("index");
      stopIndex("index");
      deleteIndex("index");
    }
    createAndStartIndex("index");
    registerFields();
    commit();
  }

  public void testBindToTwoIPs() throws Exception {
    Path dir = createTempDir();
    rmDir(dir);

    // specify port 0 twice, which tells the OS to pick two free ports:
    RunServer server = new RunServer(random(), "test", dir, Arrays.asList(new String[] {"127.0.0.1:0", "127.0.0.1:0"}));
    assertEquals(2, server.server.bindIPs.size());
    assertEquals(2, server.server.actualPorts.size());
    assertEquals(2, server.server.actualBinaryPorts.size());

    // make sure the two interfaces are talking to the same node:
    Path indexDir = createTempDir();
    rmDir(indexDir);
    
    server.send("createIndex", "{indexName: index, rootDir: " + indexDir.toAbsolutePath() + "}");
    server.send("liveSettings", "{indexName: index, minRefreshSec: 0.001}");
    server.send("startIndex", "{indexName: index}");
    JSONObject result = server.sendRaw("indexStatus", "{\"indexName\": \"index\"}".getBytes("UTF-8"), server.server.actualPorts.get(1));
    assertEquals("started", getString(result, "status"));
    server.shutdown();
  }

  public void testInvalidNullJSONFields() throws Exception {
    deleteAllDocs();

    // null key
    expectThrows(IOException.class, () -> {
        sendRaw("addDocument", "{\"indexName\": \"index\", \"fields\": {\"body\": \"body\", null: \"foobar\"}}");
      });

    // null value
    expectThrows(IOException.class, () -> {
        sendRaw("addDocument", "{\"indexName\": \"index\", \"fields\": {\"body\": \"body\", \"id\": null}}");
      });
  }

  // nocommit assert that exact field name w/ error is in
  // error message

  // nocommit drillDowns test, single and multi valued

  // nocommit testDocs

  // nocommit need test case that screws up adding bulk docs
  // (eg category path with empty string component) and
  // verifies the error "comes through"

  // nocommit need stress test that makes some index
  // thousands of times to make sure nothing leaks...
}
