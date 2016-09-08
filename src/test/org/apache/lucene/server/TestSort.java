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

import org.junit.AfterClass;
import org.junit.BeforeClass;

import net.minidev.json.JSONObject;

public class TestSort extends ServerBaseTestCase {

  @BeforeClass
  public static void initClass() throws Exception {
    useDefaultIndex = true;
    startServer();
    createAndStartIndex("index");
    registerFields();
    commit();
  }

  private static void registerFields() throws Exception {
    JSONObject o = new JSONObject();
    put(o, "atom", "{type: atom, sort: true}");
    put(o, "atomMV", "{type: atom, sort: true, multiValued: true}");
    put(o, "int", "{type: int, sort: true}");
    put(o, "intMV", "{type: int, sort: true, multiValued: true}");
    put(o, "float", "{type: float, sort: true}");
    put(o, "long", "{type: long, sort: true}");
    put(o, "double", "{type: double, sort: true}");
    put(o, "text", "{type: text, analyzer: WhitespaceAnalyzer}");
    put(o, "id", "{type: int, store: true}");
    JSONObject o2 = new JSONObject();
    o2.put("fields", o);
    send("registerFields", o2);
  }

  @AfterClass
  public static void fini() throws Exception {
    shutdownServer();
  }

  public void testMissingLastAtom() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, atom: a}}");
    send("addDocument", "{fields: {id: 1, atom: b}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("atom");
  }

  public void testMultiValuedAtomDefaultSelector() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, atomMV: a}}");
    send("addDocument", "{fields: {id: 1, atomMV: [b, c]}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("atomMV");
  }

  public void testMultiValuedAtomMaxSelector() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, atomMV: b}}");
    send("addDocument", "{fields: {id: 1, atomMV: [a, c]}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("atomMV", ", selector: max");
  }

  public void testMissingLastInt() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, int: -7}}");
    send("addDocument", "{fields: {id: 1, int: 7}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("int");
  }

  public void testMissingLastLong() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, long: -7}}");
    send("addDocument", "{fields: {id: 1, long: 7}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("long");
  }

  public void testMissingLastFloat() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, float: -7}}");
    send("addDocument", "{fields: {id: 1, float: 7}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("float");
  }

  public void testMissingLastDouble() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, double: -7}}");
    send("addDocument", "{fields: {id: 1, double: 7}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("double");
  }

  public void testNoSortOnText() throws Exception {
    assertFailsWith("registerFields",
                    "{fields: {bad: {type: text, sort: true, analyzer: WhitespaceAnalyzer}}}",
                    "registerFields > fields > bad > sort: cannot sort text fields; use atom instead");
  }

  public void testMultiValuedNumericSortDefaultSelector() throws Exception {
    deleteAllDocs();
    send("addDocument", "{fields: {id: 0, intMV: [12, -9]}}");
    // you can still add a single value if the field is registered as MV:
    send("addDocument", "{fields: {id: 1, intMV: -7}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("intMV");
  }

  public void testMultiValuedNumericSortWithSelector() throws Exception {
    deleteAllDocs();
    // you can still add a single value if the field is registered as MV:
    send("addDocument", "{fields: {id: 0, intMV: -7}}");
    send("addDocument", "{fields: {id: 1, intMV: [12, -9]}}");
    // field is missing:
    send("addDocument", "{fields: {id: 2}}");
    verifySort("intMV", ", selector: max");
  }

  private void verifySort(String field) throws Exception {
    verifySort(field, "");
  }
  
  private void verifySort(String field, String sortSpec) throws Exception {

    // missing is (annoyingly) first by default:
    boolean missingLast = false;
    
    int[] expected;
    if (missingLast) {
      expected = new int[] {0, 1, 2};
    } else {
      expected = new int[] {2, 0, 1};
    }

    long gen = getLong("indexGen");

    // default
    send("search",
         "{query: MatchAllDocsQuery, topHits: 3, retrieveFields: [id], searcher: {indexGen: " + gen + "}, sort: {fields: [{field: " + field + sortSpec + "}]}}");
    assertEquals(3, getInt("totalHits"));
    for(int i=0;i<3;i++) {
      assertEquals(expected[i], getInt("hits[" + i + "].fields.id"));
    }

    // reverse
    if (missingLast) {
      expected = new int[] {2, 1, 0};
    } else {
      expected = new int[] {1, 0, 2};
    }
    
    send("search",
         "{query: MatchAllDocsQuery, topHits: 3, retrieveFields: [id], searcher: {indexGen: " + gen + "}, sort: {fields: [{field: " + field + sortSpec + ", reverse: true}]}}");
    assertEquals(3, getInt("totalHits"));
    for(int i=0;i<3;i++) {
      assertEquals(expected[i], getInt("hits[" + i + "].fields.id"));
    }

    // missing last:
    expected = new int[] {0, 1, 2};
    send("search",
         "{query: MatchAllDocsQuery, topHits: 3, retrieveFields: [id], searcher: {indexGen: " + gen + "}, sort: {fields: [{field: " + field + sortSpec + ", missingLast: true}]}}");
    assertEquals(3, getInt("totalHits"));
    for(int i=0;i<3;i++) {
      assertEquals(expected[i], getInt("hits[" + i + "].fields.id"));
    }

    // reverse, missing last:
    expected = new int[] {2, 1, 0};
    send("search",
         "{query: MatchAllDocsQuery, topHits: 3, retrieveFields: [id], searcher: {indexGen: " + gen + "}, sort: {fields: [{field: " + field + sortSpec + ", reverse: true, missingLast: true}]}}");
    assertEquals(3, getInt("totalHits"));
    for(int i=0;i<3;i++) {
      assertEquals(expected[i], getInt("hits[" + i + "].fields.id"));
    }
  }
}
