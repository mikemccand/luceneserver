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
import java.nio.charset.StandardCharsets;

import org.junit.AfterClass;
import org.junit.BeforeClass;

import net.minidev.json.JSONObject;

public class TestDateTime extends ServerBaseTestCase {
  @BeforeClass
  public static void initClass() throws Exception {
    useDefaultIndex = true;
    startServer();
    createAndStartIndex("index");
  }

  @AfterClass
  public static void fini() throws Exception {
    shutdownServer();
  }

  public void testIndexCSVDateTime() throws Exception {
    createIndex();
    send("registerFields", "{fields: {modified: {type: datetime, store: true, sort: true, dateTimeFormat: 'yyyy-MM-dd'}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     ("," + server.curIndexName + "\nmodified\n2016-10-14\n").getBytes(StandardCharsets.UTF_8));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testMissingDateTimeFormat() throws Exception {
    createIndex();
    expectThrows(IOException.class, () -> {
        send("registerFields", "{fields: {modified: {type: datetime, store: true, sort: true}}}");
      });
    send("deleteIndex");
  }

  public void testBogusDateTimeFormat() throws Exception {
    createIndex();
    expectThrows(IOException.class, () -> {
        send("registerFields", "{fields: {modified: {type: datetime, store: true, sort: true, dateTimeFormat: 'g'}}}");
      });
    send("deleteIndex");
  }

  public void testBogusDateTimeValue() throws Exception {
    createIndex();
    send("registerFields", "{fields: {modified: {type: datetime, store: true, sort: true, dateTimeFormat: 'yyyy-MM-dd'}}}");
    send("startIndex");
    IOException e = expectThrows(IOException.class, () -> {
        server.sendBinary("bulkCSVAddDocument",
                          ("," + server.curIndexName + "\nmodified\n2016-10-14x\n").getBytes(StandardCharsets.UTF_8));
      });
    assertContains(e.getMessage(), "could not parse field \"modified\", value \"2016-10-14x\" as date with format \"yyyy-MM-dd\"");
    send("stopIndex");
    send("deleteIndex");
  }

  // nocommit test time too

  public void testStored() throws Exception {
    createIndex();
    send("registerFields", "{fields: {modified: {type: datetime, store: true, sort: true, dateTimeFormat: 'yyyy-MM-dd'}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     ("," + server.curIndexName + "\nmodified\n2016-10-14\n").getBytes(StandardCharsets.UTF_8));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));

    refresh();
    result = send("search", "{query: MatchAllDocsQuery, retrieveFields: [modified]}");
    assertEquals(1, get(result, "hits.length"));
    assertEquals("2016-10-14", get(result, "hits[0].fields.modified"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testRangeQuery() throws Exception {
    createIndex();
    send("registerFields", "{fields: {modified: {type: datetime, search: true, store: true, sort: true, dateTimeFormat: 'yyyy-MM-dd'}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     ("," + server.curIndexName + "\nmodified\n2016-10-14\n").getBytes(StandardCharsets.UTF_8));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(1, getInt(result, "indexedDocumentCount"));

    refresh();
    result = send("search", "{query: {class: NumericRangeQuery, field: modified, min: '2016-10-01', max: '2016-11-1'}, retrieveFields: [modified]}");
    assertEquals(1, get(result, "hits.length"));
    assertEquals("2016-10-14", get(result, "hits[0].fields.modified"));
    send("stopIndex");
    send("deleteIndex");
  }

  public void testSort() throws Exception {
    createIndex();
    send("registerFields", "{fields: {modified: {type: datetime, search: true, store: true, sort: true, dateTimeFormat: 'yyyy-MM-dd'}}}");
    send("startIndex");
    byte[] bytes = server.sendBinary("bulkCSVAddDocument",
                                     ("," + server.curIndexName + "\nmodified\n2016-10-17\n2015-06-02\n").getBytes(StandardCharsets.UTF_8));
    JSONObject result = parseJSONObject(new String(bytes, StandardCharsets.UTF_8));
    assertEquals(2, getInt(result, "indexedDocumentCount"));

    refresh();
    result = send("search", "{query: MatchAllDocsQuery, sort: {fields: [{field: modified}]}, retrieveFields: [modified]}");
    assertEquals(2, get(result, "hits.length"));
    assertEquals("2015-06-02", get(result, "hits[0].fields.modified"));
    assertEquals("2016-10-17", get(result, "hits[1].fields.modified"));
    send("stopIndex");
    send("deleteIndex");
  }
}
