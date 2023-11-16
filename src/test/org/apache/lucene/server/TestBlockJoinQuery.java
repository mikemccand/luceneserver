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
import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

public class TestBlockJoinQuery extends ServerBaseTestCase {
  
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
    send("registerFields", "{fields: {docType: {type: atom}, name: {type: atom, store: true}, country: {type: atom, store: true, sort: true}, skill: {type: atom, store: true}, year: {type: int, store: true}}}");
  }

  private JSONObject getResume(String name, String country) {
    JSONObject o = new JSONObject();
    o.put("docType", "resume");
    o.put("name", name);
    o.put("country", country);
    JSONObject o2 = new JSONObject();
    o2.put("fields", o);
    return o2;
  }

  private JSONObject getJob(String skill, int year) {
    JSONObject o = new JSONObject();
    o.put("skill", skill);
    o.put("year", year);
    JSONObject o2 = new JSONObject();
    o2.put("fields", o);
    return o2;
  }

  public void testToParentBlockJoin() throws Exception {
    deleteAllDocs();

    JSONObject o = new JSONObject();
    o.put("indexName", "index");
    o.put("parent", getResume("Lisa", "United Kingdom"));
    JSONArray arr = new JSONArray();
    o.put("children", arr);
    arr.add(getJob("java", 2007));
    arr.add(getJob("python", 2010));
    send("addDocuments", o);

    // search on parent:
    send("search", "{query: {class: ToParentBlockJoinQuery, childQuery: {class: text, field: skill, text: python}, parentsFilter: {class: TermQuery, field: docType, term: resume}}}");
    //System.out.println("GOT: " + result);
    assertEquals(1, getInt("totalHits.value"));

    // Returns child docs grouped up to parent doc:
    send("search", "{retrieveFields: [skill, year, name, country], query: {class: ToParentBlockJoinQuery, childHits: {}, childQuery: {class: text, field: skill, text: python}, parentsFilter: {class: TermQuery, field: docType, term: resume}}}");

    assertEquals(1, getInt("totalGroupCount"));
    // Grouping from a BJQ does not set totalHits:
    assertEquals(0, getInt("totalHits.value"));

    System.out.println("GOT RESPONSE:\n" + server.lastResult);

    assertEquals(1, getInt("groups.length"));
    assertEquals(1, getInt("groups[0].hits.length"));
    assertEquals("Lisa", getString("groups[0].fields.name"));
    assertEquals("United Kingdom", getString("groups[0].fields.country"));
    assertEquals("python", getString("groups[0].hits[0].fields.skill"));
    assertEquals(2010, getInt("groups[0].hits[0].fields.year"));

    // Sort by country
    send("search", "{retrieveFields: [skill, year, name, country], query: {class: ToParentBlockJoinQuery, childHits: {sort: [{field: country}]}, childQuery: {class: text, field: skill, text: python}, parentsFilter: {class: TermQuery, field: docType, term: resume}}}");
  }

  public void testToParentBlockJoinWithExpressions() throws Exception {
    deleteAllDocs();

    JSONObject o = new JSONObject();
    o.put("indexName", "index");
    o.put("parent", getResume("Lisa", "United Kingdom"));
    JSONArray arr = new JSONArray();
    o.put("children", arr);
    arr.add(getJob("java", 2007));
    arr.add(getJob("python", 2010));
    send("addDocuments", o);

    // search on parent:
    send("search",
         "{virtualFields: [{name: origScore, expression: '_score'}]," +
          "sort: {fields: [{field: origScore}]}," +
          "retrieveFields: [origScore]," +
          "query: {class: ToParentBlockJoinQuery, childHits: {}," +
                  "scoreMode: Max," +
                  "childQuery: {class: text, field: skill, text: python}," +
                  "parentsFilter: {class: TermQuery, field: docType, term: resume}}}");
    //System.out.println("GOT: " + prettyPrint(lastResult));
    assertEquals(1, getInt("totalGroupedHits"));
    double childScore = getFloat("groups[0].hits[0].fields.origScore");
    assertEquals(childScore, getFloat("groups[0].fields.origScore"), 0.0);
  }
}
