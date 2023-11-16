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

import org.junit.AfterClass;
import org.junit.BeforeClass;

import net.minidev.json.JSONObject;

public class TestBooleanFieldType extends ServerBaseTestCase {

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
    put(o, "id", "{type: int, store: true}");
    put(o, "other", "{type: text, store: true}");
    put(o, "flagStored", "{type: boolean, store: true, search: false}");
    put(o, "flagIndexed", "{type: boolean, store: false, search: true}");
    JSONObject o2 = new JSONObject();
    o2.put("indexName", "index");
    o2.put("fields", o);
    send("registerFields", o2);
  }

  public void testStored() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, flagStored: false}}");
    long gen = getLong(send("addDocument", "{fields: {id: 1, flagStored: true}}"), "indexGen");
    JSONObject o = send("search", "{searcher: {indexGen: " + gen + "}, query: MatchAllDocsQuery, retrieveFields: [id, flagStored]}");
    assertEquals(2, getInt(o, "totalHits.value"));
    assertFalse(getBoolean(o, "hits[0].fields.flagStored"));
    assertTrue(getBoolean(o, "hits[1].fields.flagStored"));
  }

  public void testIndexed() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, flagIndexed: false, flagStored: false}}");
    long gen = getLong(send("addDocument", "{fields: {id: 1, flagIndexed: true, flagStored: true}}"), "indexGen");
    JSONObject o = send("search", "{searcher: {indexGen: " + gen + "}, query: {class: BooleanFieldQuery, field: flagIndexed}, retrieveFields: [id, flagStored]}");
    assertEquals(1, getInt(o, "totalHits.value"));
    assertTrue(getBoolean(o, "hits[0].fields.flagStored"));
  }

  public void testWrongFieldType() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, other: \"foo\", flagIndexed: false, flagStored: false}}");
    long gen = getLong(send("addDocument", "{fields: {id: 1, flagIndexed: true, flagStored: true}}"), "indexGen");
    Exception e = expectThrows(IOException.class, () -> {send("search", "{searcher: {indexGen: " + gen + "}, query: {class: BooleanFieldQuery, field: other}, retrieveFields: [id, flagStored]}");});
    assertEquals("Server error:\nsearch > query > field: field \"other\" must be valueType=boolean but got: TEXT", e.getMessage());
  }
}
