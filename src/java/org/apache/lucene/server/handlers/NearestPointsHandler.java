package org.apache.lucene.server.handlers;

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
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.apache.lucene.document.Document;
import org.apache.lucene.document.LatLonPoint;
import org.apache.lucene.facet.taxonomy.SearcherTaxonomyManager.SearcherAndTaxonomy;
import org.apache.lucene.index.IndexableField;
import org.apache.lucene.search.FieldDoc;
import org.apache.lucene.search.ScoreDoc;
import org.apache.lucene.search.TopFieldDocs;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.params.FloatType;
import org.apache.lucene.server.params.IntType;
import org.apache.lucene.server.params.ListType;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

/** Handles {@code search}. */
public class NearestPointsHandler extends Handler {

  private final static StructType TYPE =
    new StructType(
        new Param("indexName", "Which index to search", new StringType()),
        new Param("fieldName", "Which latlon field to search", new StringType()),
        new Param("latitude", "Latitude of origin point", new FloatType()),
        new Param("longitude", "Longitude of origin point", new FloatType()),
        new Param("count", "Number of nearest hits to return", new IntType(), 10),
        new Param("retrieveFields", "Which stored fields to retrieve.",
                  new ListType(new StringType())),
        new Param("searcher", "Specific searcher version to use for searching.  There are three different ways to specify a searcher version.",
                  SearchHandler.SEARCHER_VERSION_TYPE)
                   );

  @Override
  public String getTopDoc() {
    return "Return the nearest points to an origin point.";
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  /** Sole constructor. */
  public NearestPointsHandler(GlobalState state) {
    super(state);
  }

  @Override
  public FinishRequest handle(final IndexState indexState, final Request r, Map<String,List<String>> params) throws Exception {
    final ShardState shardState = indexState.getShard(0);
    indexState.verifyStarted(r);

    List<String> retrieveFields;
    if (r.hasParam("retrieveFields")) {
      retrieveFields = new ArrayList<String>();
      for(Object o : r.getList("retrieveFields")) {
        retrieveFields.add((String) o);
      }
    } else {
      retrieveFields = null;
    }

    JSONObject diagnostics = new JSONObject();
    String fieldName = r.getString("fieldName");
    double lat = r.getDouble("latitude");
    double lon = r.getDouble("longitude");
    int count = r.getInt("count");

    final String resultString;      

    // Pull the searcher we will use
    final SearcherAndTaxonomy s = SearchHandler.getSearcherAndTaxonomy(r, shardState, diagnostics);
    try {
      TopFieldDocs hits = LatLonPoint.nearest(s.searcher, fieldName, lat, lon, count);

      JSONObject result = new JSONObject();
      result.put("diagnostics", diagnostics);

      JSONArray array = new JSONArray();
      result.put("hits", array);
      for(ScoreDoc hit : hits.scoreDocs) {
        FieldDoc fd = (FieldDoc) hit;
        assert fd.fields.length == 1;
        JSONObject oneHit = new JSONObject();
        oneHit.put("doc", hit.doc);
        oneHit.put("distanceMeters", fd.fields[0]);
        array.add(oneHit);
        if (retrieveFields != null) {
          Document doc = s.searcher.doc(hit.doc);
          JSONObject fieldValues = new JSONObject();
          oneHit.put("fields", fieldValues);
          for(String retrieveFieldName : retrieveFields) {
            IndexableField field = doc.getField(retrieveFieldName);
            // nocommit break out by type here!
            fieldValues.put(retrieveFieldName, field.toString());
          }
        }
      }

      resultString = result.toString();
    } finally {
      // NOTE: this is a little iffy, because we may not
      // have obtained this searcher from the NRTManager
      // (i.e. sometimes we pulled from
      // SearcherLifetimeManager, other times (if
      // snapshot was specified) we opened ourselves,
      // but under-the-hood all these methods just call
      // s.getIndexReader().decRef(), which is what release
      // does:
      shardState.release(s);
    }

    return new FinishRequest() {
      @Override
      public String finish() throws IOException {
        return resultString;
      }
    };
  }

  /** Parses the {@link Request} into a {@link Locale}. */
  public static Locale getLocale(Request r) {
    // nocommit cutover to bcp47
    Locale locale;
    if (!r.hasParam("variant")) {
      if (!r.hasParam("country")) {
        locale = new Locale(r.getString("language"));
      } else {
        locale = new Locale(r.getString("language"),
                            r.getString("country"));
      }
    } else {
      locale = new Locale(r.getString("language"),
                          r.getString("country"),
                          r.getString("variant"));
    }

    return locale;
  }
}
