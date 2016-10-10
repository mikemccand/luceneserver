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
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Collections;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

import org.junit.AfterClass;
import org.junit.BeforeClass;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

public class TestIndexing extends ServerBaseTestCase {

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
    put(o, "id", "{type: atom, store: true, postingsFormat: Memory}");
    put(o, "price", "{type: float, sort: true, search: true, store: true}");
    put(o, "date", "{type: atom, search: false, store: true}");
    put(o, "dateFacet", "{type: atom, search: false, store: false, facet: hierarchy}");
    put(o, "author", "{type: text, search: false, facet: flat, store: true, group: true}");
    put(o, "charCount", "{type: int, store: true}");
    JSONObject o2 = new JSONObject();
    o2.put("fields", o);
    send("registerFields", o2);
  }

  public void testUpdateDocument() throws Exception {
    send("addDocument", "{fields: {body: 'here is a test', id: '0'}}");
    long gen = getLong(send("updateDocument", "{term: {field: id, term: '0'}, fields: {body: 'here is another test', id: '0'}}"), "indexGen");
    JSONObject o = send("search", "{queryText: 'body:test', searcher: {indexGen: " + gen + "}, retrieveFields: [body]}");
    assertEquals(1, getInt(o, "totalHits"));
    assertEquals("here is another test", getString(o, "hits[0].fields.body"));
  }

  public void testBulkUpdateDocuments() throws Exception {
    deleteAllDocs();
    StringBuilder sb = new StringBuilder();
    for(int i=0;i<100;i++) {
      JSONObject o = new JSONObject();
      o.put("body", "here is the body " + i);
      o.put("id", ""+i);
      sb.append(o.toString());
      sb.append('\n');
    }

    String s = sb.toString();

    JSONObject result = send("bulkAddDocument", Collections.singletonMap("indexName", Collections.singletonList("index")), new StringReader(s));
    assertEquals(100, result.get("indexedDocumentCount"));
    long indexGen = ((Number) result.get("indexGen")).longValue();
    assertEquals(1, getInt(send("search", "{queryText: 'body:99', searcher: {indexGen: " + indexGen + "}}"), "totalHits"));

    // Now, update:
    sb = new StringBuilder();
    sb.append("{\"indexName\": \"index\", \"documents\": [");
    for(int i=0;i<100;i++) {
      JSONObject o2 = new JSONObject();
      JSONObject o = new JSONObject();
      o2.put("fields", o);
      o.put("body", "here is the body " + i);
      o.put("id", ""+i);
      if (i > 0) {
        sb.append(',');
      }
      put(o2, "term", "{field: id, term: '" + i + "'}");
      sb.append(o2.toString());
    }
    sb.append("]}");

    s = sb.toString();

    result = send("bulkUpdateDocument", new HashMap<>(), new StringReader(s));
    assertEquals(100, result.get("indexedDocumentCount"));
    indexGen = ((Number) result.get("indexGen")).longValue();
    assertEquals(1, getInt(send("search", "{queryText: 'body:99', searcher: {indexGen: " + indexGen + "}}"), "totalHits"));

    assertEquals(100, getInt(send("search", "{query: MatchAllDocsQuery, searcher: {indexGen: " + indexGen + "}}"), "totalHits"));
  }

  public void testBulkAddException() throws Exception {
    deleteAllDocs();
    StringBuilder sb = new StringBuilder();
    sb.append("{\"indexName\": \"index\", \"documents\": [");
    for(int i=0;i<100;i++) {
      JSONObject o = new JSONObject();
      o.put("body", "here is the body " + i);
      o.put("id", ""+i);
      if (i > 0) {
        sb.append(',');
      }
      if (i == 57) {
        o.put("foobar", 17);
      }
      JSONObject o2 = new JSONObject();
      o2.put("fields", o);
      sb.append(o2.toString());
    }
    sb.append("]}");

    String s = sb.toString();

    try {
      send("bulkAddDocument", Collections.singletonMap("indexName", Collections.singletonList("index")), new StringReader(s));
      fail("did not hit expected exception");
    } catch (IOException ioe) {
      // expected
    }
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
      sort.put("doDocScores", true);

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

  public void testBulkAddDocument() throws Exception {
    deleteAllDocs();
    StringBuilder sb = new StringBuilder();
    for(int i=0;i<100;i++) {
      JSONObject o = new JSONObject();
      o.put("body", "here is the body " + i);
      o.put("author", "Mr. " + i);
      o.put("price", 15.66);
      o.put("id", ""+i);
      o.put("date", "01/01/2013");
      sb.append(o.toString());
      sb.append('\n');
    }
    String s = sb.toString();

    JSONObject result = send("bulkAddDocument", Collections.singletonMap("indexName", Collections.singletonList("index")), new StringReader(s));
    assertEquals(100, result.get("indexedDocumentCount"));
    long indexGen = getLong(result, "indexGen");
    JSONObject r = search("99", indexGen, null, false, true, null, null);
    assertEquals(1, ((Integer) r.get("totalHits")).intValue());
  }

  public void testBulkAddDocument2() throws Exception {
    createAndStartIndex("bulk2");
    registerFields();
    StringBuilder sb = new StringBuilder();
    for(int i=0;i<100;i++) {
      JSONObject o = new JSONObject();
      o.put("body", "here is the body " + i);
      o.put("author", "Mr. " + i);
      o.put("price", 15.66);
      o.put("id", ""+i);
      o.put("date", "01/01/2013");
      if (i > 0) {
        sb.append('\n');
      }
      sb.append(o.toString());
    }
    String s = sb.toString();
    Map<String,Object> params = new HashMap<>();
    params.put("indexName", "bulk2");
    JSONObject result = send("bulkAddDocument2", params, new StringReader(s));
    assertEquals(100, result.get("indexedDocumentCount"));
    long indexGen = getLong(result, "indexGen");
    JSONObject r = send("search", "{indexName: bulk2, searcher: {indexGen: " + indexGen + "}, queryText: \"99\", facets: [{dim: dateFacet, topN: 10}], retrieveFields: [id, date, price, {field: body, highlight: snippets}]}");
    assertEquals(1, ((Integer) r.get("totalHits")).intValue());
    send("deleteIndex");
  }

  /** Make sure you get an error if you try to addDocument
   *  after index is stopped */
  public void testAddAfterStop() throws Exception {
    deleteAllDocs();
    send("stopIndex");
    try {
      send("addDocument", "{fields: {}}");
      fail();
    } catch (IOException ioe) {
      // expected
    }
    send("startIndex");
  }

  public void testBoost() throws Exception {
    createIndex("boost");
    send("settings", "{directory: RAMDirectory}");
    // Just to test merge rate limiting:
    send("settings", "{mergeMaxMBPerSec: 10.0}");
    // Just to test index.ramBufferSizeMB:
    send("liveSettings", "{index.ramBufferSizeMB: 20.0}");
    send("registerFields", "{fields: {id: {type: atom, store: true}, body: {type: text, analyzer: StandardAnalyzer}}}");
    send("startIndex");
    send("addDocument", "{fields: {id: '0', body: 'here is a test'}}");
    long gen = getLong(send("addDocument", "{fields: {id: '1', body: 'here is a test'}}"), "indexGen");
    JSONObject result = send("search", String.format(Locale.ROOT, "{retrieveFields: [id], queryText: test, searcher: {indexGen: %d}}", gen));
    assertEquals(2, getInt(result, "hits.length"));
    // Unboosted, the hits come back in order they were added:
    assertEquals("0", getString(result, "hits[0].fields.id"));
    assertEquals("1", getString(result, "hits[1].fields.id"));

    // Do it again, this time setting higher boost for 2nd doc:
    send("deleteAllDocuments");
    send("addDocument", "{fields: {id: '0', body: 'here is a test'}}");
    gen = getLong(send("addDocument", "{fields: {id: '1', body: {boost: 2.0, value: 'here is a test'}}}"), "indexGen");
    result = send("search", String.format(Locale.ROOT, "{retrieveFields: [id], queryText: test, searcher: {indexGen: %d}}", gen));
    assertEquals(2, getInt(result, "hits.length"));
    // Unboosted, the hits come back in order they were added:
    assertEquals("1", getString(result, "hits[0].fields.id"));
    assertEquals("0", getString(result, "hits[1].fields.id"));

    send("deleteIndex");
  }

  public void testInvalidNormsFormat() throws Exception {
    try {
      send("settings", "{normsFormat: NoSuchNormsFormat}");
      fail("did not hit exception");
    } catch (IOException ioe) {
      assertContains(ioe.getMessage(), "unrecognized value \"NoSuchNormsFormat\"");
    }
  }

  public void testInvalidUTF8() throws Exception {
    String s = "{\"indexName\": \"foo\"}";
    byte[] bytes = s.getBytes("UTF-8");
    // replaces the last 'o' in foo with illegal UTF-8 byte:
    bytes[bytes.length-3] = (byte) 0xff;
    Exception e = expectThrows(IOException.class, () -> server.sendRaw("createIndex", bytes));
    assertContains(e.toString(), "MalformedInputException");
  }

  public void testNormsFormat() throws Exception {
    if (VERBOSE) {
      System.out.println("\nTEST: createIndex");
    }
    createIndex("normsFormat");
    send("settings", "{directory: RAMDirectory, normsFormat: Lucene53}");
    send("registerFields",
         "{fields: {id: {type: atom, store: true}, body: {type: text, analyzer: StandardAnalyzer}}}");
    if (VERBOSE) {
      System.out.println("\nTEST: startIndex");
    }
    send("startIndex");
    send("addDocument", "{fields: {id: '0', body: 'here is a test'}}");
    long gen = getLong(send("addDocument", "{fields: {id: '1', body: 'here is a test again'}}"), "indexGen");
    JSONObject result = send("search", String.format(Locale.ROOT, "{retrieveFields: [id], queryText: test, searcher: {indexGen: %d}}", gen));
    assertEquals(2, getInt(result, "hits.length"));
    assertEquals("0", getString(result, "hits[0].fields.id"));
    assertEquals("1", getString(result, "hits[1].fields.id"));

    if (VERBOSE) {
      System.out.println("\nTEST: deleteIndex");
    }
    send("deleteIndex");
  }

  public void testIndexSort() throws Exception {
    createIndex("sorted");
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}}}");
    send("settings", "{indexSort: [{field: id}]}");
    JSONObject result = send("settings", "{indexName: sorted}");
    assertEquals("[{\"field\":\"id\"}]", result.get("indexSort").toString());
    Exception e = expectThrows(IOException.class, () -> {send("settings", "{indexSort: [{field: id2}]}");});
    assertContains(e.getMessage(), "java.lang.IllegalStateException: index \"sorted\": cannot change index sort");
    send("startIndex");
    for(int i=200;i>=0;i--) {
      send("addDocument", "{fields: {id: \"" + i + "\"}}");
      refresh();
      send("search", "{indexName: sorted, queryText: \"*:*\"}");
      result = send("stats", "{indexName: sorted}");
      if (result.toString().contains("indexSort=<string: \\\"id\\\">")) {
        // success
        break;
      }
    }

    // make sure indexSort survives server bounce:
    bounceServer();
    send("startIndex", "{indexName: sorted}");
    send("deleteAllDocuments");
    System.out.println("TEST: again");
    for(int i=200;i>=0;i--) {
      send("addDocument", "{fields: {id: \"" + i + "\"}}");
      refresh();
      send("search", "{indexName: sorted, queryText: \"*:*\"}");
      result = send("stats", "{indexName: sorted}");
      if (result.toString().contains("indexSort=<string: \\\"id\\\">")) {
        // success
        break;
      }
    }
    
    send("deleteIndex");
  }

  public void testIndexCSVBasic() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1,some text\n1,2,some more text\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(2, getInt(result, "indexedDocumentCount"));
    send("stopIndex");
    send("deleteIndex");
  }

  /** Index a document via CSV that's larger than the 512 KB chunk size */
  public void testIndexCSVBig() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    StringBuilder b = new StringBuilder();
    int size = atLeast(512);
    for(int i=0;i<256 * size;i++) {
      b.append("wordy ");
    }
    b.append(" document");
    String body = b.toString();
    assertTrue(body.length() > 512*1024);
    
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1," + body + "\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    assertEquals(1, getInt(send("search", "{queryText: document}"), "totalHits"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIndexCSVLatLon() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, point: {type: latlon, sort: true, search: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nid,point,body\n0,42.3677;71.0709,some text\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    send("search", "{query: {class: LatLonDistanceQuery, field: point, latitude: 41.0, longitude: 71.0, radiusMeters: 1000000.0}}");
    assertEquals(1, getInt("totalHits"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVBadLatLon() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, point: {type: latlon, sort: true, search: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\nid,point,body\n0,42.3677x71.0709,some text\n"));
      });
    assertContains(t.getMessage(), "doc at offset 30: could not parse field \"point\", value \"42.3677x71.0709\" as lat;lon format");
    
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIndexCSVEscape1() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true, search: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1,\"some text\"\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    result = send("search", "{queryText: \"*:*\", retrieveFields: [body]}");
    assertEquals("some text", getString(result, "hits[0].fields.body"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIndexCSVEscape2() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true, search: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1,\"some, text\"\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    result = send("search", "{queryText: \"*:*\", retrieveFields: [body]}");
    assertEquals("some, text", getString(result, "hits[0].fields.body"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIndexCSVEscape3() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true, search: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1,\"some\"\" text\"\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    result = send("search", "{queryText: \"*:*\", retrieveFields: [body]}");
    assertEquals("some\" text", getString(result, "hits[0].fields.body"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIndexCSVEscape4() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true, search: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1,\"some\"\" text\"\"\"\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    result = send("search", "{queryText: \"*:*\", retrieveFields: [body]}");
    assertEquals("some\" text\"", getString(result, "hits[0].fields.body"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIndexCSVEscape5() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true, search: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1,\"some\n text\"\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    result = send("search", "{queryText: \"*:*\", retrieveFields: [body]}");
    assertEquals("some\n text", getString(result, "hits[0].fields.body"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIndexCSVEscape6() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true, search: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     toUTF8("," + server.curIndexName + "\nbody,id,id2\n\"some\n text\",1,2\n"));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    result = send("search", "{queryText: \"*:*\", retrieveFields: [body]}");
    assertEquals("some\n text", getString(result, "hits[0].fields.body"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVBadEscape() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true, search: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\nbody,id,id2\n\"some \"text,1,2\n"));
      });
    assertContains(t.getMessage(), "doc at offset 0: closing quote must appear only at the end of the cell");
    send("stopIndex");
    send("deleteIndex");
  }

  // nocommit test illegal double quote before delim or newline

  public void testIndexCSVBasicHTTP() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Map<String,Object> params = new HashMap<>();
    params.put("indexName", server.curIndexName);
    JSONObject result = server.send("bulkCSVAddDocument2", params, new StringReader("id,id2,body\n0,1,some text\n1,2,some more text\n"));
    assertEquals(2, getInt(result, "indexedDocumentCount"));
    send("stopIndex");
    send("deleteIndex");
  }

  /** Index a document via CSV that's larger than the 512 KB chunk size */
  public void testIndexCSVBigHTTP() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    StringBuilder b = new StringBuilder();
    int size = atLeast(512);
    for(int i=0;i<256 * size;i++) {
      b.append("wordy ");
    }
    b.append(" document");
    String body = b.toString();
    assertTrue(body.length() > 512*1024);

    Map<String,Object> params = new HashMap<>();
    params.put("indexName", server.curIndexName);
    JSONObject result = server.send("bulkCSVAddDocument2", params, new StringReader("id,id2,body\n0,1," + body + "\n"));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    assertEquals(1, getInt(send("search", "{queryText: document}"), "totalHits"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIndexCSVLatLonHTTP() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, point: {type: latlon, sort: true, search: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Map<String,Object> params = new HashMap<>();
    params.put("indexName", server.curIndexName);
    JSONObject result = send("bulkCSVAddDocument2", params, new StringReader("id,point,body\n0,42.3677;71.0709,some text\n"));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    refresh();
    send("search", "{query: {class: LatLonDistanceQuery, field: point, latitude: 41.0, longitude: 71.0, radiusMeters: 1000000.0}}");
    assertEquals(1, getInt("totalHits"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVBadLatLonHTTP() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, point: {type: latlon, sort: true, search: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Map<String,Object> params = new HashMap<>();
    params.put("indexName", server.curIndexName);
    Throwable t = expectThrows(IOException.class, () -> {
        send("bulkCSVAddDocument2", params, new StringReader("id,point,body\n0,42.3677x71.0709,some text\n"));
      });
    assertContains(t.getMessage(), "doc at offset 30: could not parse field \"point\", value \"42.3677x71.0709\" as lat;lon format");
    
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVTooManyFields() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1,some text,boo\n1,2,some more text\n"));
      });
    assertContains(t.getMessage(), "doc at offset 0: line has too many fields");
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVTooFewFields() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1\n1,2,some more text\n"));
      });
    assertContains(t.getMessage(), "doc at offset 0: line has wrong number of fields: expected 3 but saw 2");
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVMissingTrailingNewline() throws Exception {
    createIndex();
    send("registerFields", "{fields: {id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\nid,id2,body\n0,1,some text\n1,2,some more text"));
      });
    assertContains(t.getMessage(), "last document starting at offset 46 is missing the trailing newline");
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVBadInt() throws Exception {
    createIndex();
    send("registerFields", "{fields: {count: {type: int, search: true}, id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\ncount,id2,body\n0,1,some text\n118371391723487213472,2,some more text"));
      });
    assertContains(t.getMessage(), "doc at offset 66: could not parse field \"count\" as int: overflow: \"118371391723487213472\"");
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVBadLong() throws Exception {
    createIndex();
    send("registerFields", "{fields: {count: {type: long, search: true}, id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\ncount,id2,body\n0,1,some text\n118371391723487213472,2,some more text"));
      });
    assertContains(t.getMessage(), "doc at offset 66: could not parse field \"count\" as long: overflow: \"118371391723487213472\"");
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVBadFloat() throws Exception {
    createIndex();
    send("registerFields", "{fields: {count: {type: float, search: true}, id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\ncount,id2,body\n0,1,some text\n1183x71391723487213472,2,some more text"));
      });
    assertContains(t.getMessage(), "doc at offset 67: could not parse field \"count\" as float: extra characters: \"1183x71391723487213472\"");
    send("stopIndex");
    send("deleteIndex");
  }

  public void testIllegalIndexCSVBadDouble() throws Exception {
    createIndex();
    send("registerFields", "{fields: {count: {type: double, search: true}, id: {type: atom, store: true, sort: true}, id2: {type: atom, store: true, sort: true}, body: {type: text, store: true, highlight: true}}}");
    send("startIndex");
    Throwable t = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          toUTF8("," + server.curIndexName + "\ncount,id2,body\n0,1,some text\n1183x71391723487213472,2,some more text"));
      });
    assertContains(t.getMessage(), "doc at offset 67: could not parse field \"count\" as double: extra characters: \"1183x71391723487213472\"");
    send("stopIndex");
    send("deleteIndex");
  }

  public void testOnlySettings() throws Exception {
    if (VERBOSE) {
      System.out.println("TEST: testOnlySettings start");
    }
    for(int i=0;i<2;i++) {
      server.curIndexName = "settings";
      if (VERBOSE) {
        System.out.println("\nTEST: create");
      }
      if (i == 0) {
        send("createIndex");
      } else {
        Path dir = createTempDir("recency").resolve("root");
        send("createIndex", "{rootDir: " + dir.toAbsolutePath() + "}");
      }
      String dirImpl = i == 0 ? "RAMDirectory" : "FSDirectory";

      if (VERBOSE) {
        System.out.println("\nTEST: settings1");
      }
      send("settings", "{directory: " + dirImpl + "}");
      send("registerFields", "{fields: {id: {type: atom, store: true}}}");
      //send("stopIndex");
      if (VERBOSE) {
        System.out.println("\nTEST: settings2");
      }
      JSONObject result = send("settings");
      assertEquals(dirImpl, getString(result, "directory"));
      if (i == 1) {
        // With FSDir, the index & settings should survive a
        // server bounce, even if the index wasn't ever started:

        if (VERBOSE) {
          System.out.println("\nTEST: bounce");
        }

        bounceServer();

        if (VERBOSE) {
          System.out.println("\nTEST: settings3");
        }
        result = send("settings");
        assertEquals(dirImpl, getString(result, "directory"));
      }
      send("deleteIndex");
    }
  }

  public void testIllegalRegisterFields() throws Exception {
    // Cannot specify an analyzer with an atom field (it
    // always uses KeywordAnalyzer):
    assertFailsWith("registerFields",
                    "{fields: {bad: {type: atom, analyzer: WhitespaceAnalyzer}}}",
                    "registerFields > fields > bad > analyzer: no analyzer allowed with atom (it's hardwired to KeywordAnalyzer internally)");

    // Must not specify an analyzer with a non-searched text field:
    assertFailsWith("registerFields",
                    "{fields: {bad: {type: text, search: false, analyzer: WhitespaceAnalyzer}}}",
                    "registerFields > fields > bad > analyzer: no analyzer allowed when search=false");

    // Must not disable store if highlight is true:
    assertFailsWith("registerFields",
                    "{fields: {bad: {type: text, store: false, highlight: true, analyzer: WhitespaceAnalyzer}}}",
                    "registerFields > fields > bad > store: store=false is not allowed when highlight=true");

    // Cannot search a facet=hierarchy field:
    assertFailsWith("registerFields",
                    "{fields: {bad: {type: atom, facet: hierarchy, search: true}}}",
                    "registerFields > fields > bad > facet: facet=hierarchy fields cannot have search=true");

    // Cannot store a facet=hierarchy field:
    assertFailsWith("registerFields",
                    "{fields: {bad: {type: atom, facet: hierarchy, search: false, store: true}}}",
                    "registerFields > fields > bad > facet: facet=hierarchy fields cannot have store=true");

    // Cannot highlight a facet=hierarchy field:
    assertFailsWith("registerFields",
                    "{fields: {bad: {type: atom, facet: hierarchy, highlight: true, store: true}}}",
                    "registerFields > fields > bad > facet: facet=hierarchy fields cannot have highlight=true");

    // Cannot create a pointless do-nothing field:
    assertFailsWith("registerFields",
                    "{fields: {bad: {type: atom, search: false, store: false}}}",
                    "registerFields > fields > bad: field does nothing: it's neither searched, stored, sorted, grouped, highlighted nor faceted");
  }
}
