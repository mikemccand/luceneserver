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
import java.text.BreakIterator;
import java.text.ParseException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantLock;

import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.document.Document;
import org.apache.lucene.document.DoublePoint;
import org.apache.lucene.document.FloatPoint;
import org.apache.lucene.document.IntPoint;
import org.apache.lucene.document.LatLonDocValuesField;
import org.apache.lucene.document.LatLonPoint;
import org.apache.lucene.document.LongPoint;
import org.apache.lucene.expressions.Bindings;
import org.apache.lucene.expressions.Expression;
import org.apache.lucene.expressions.js.JavascriptCompiler;
import org.apache.lucene.facet.DrillDownQuery;
import org.apache.lucene.facet.DrillSideways;
import org.apache.lucene.facet.FacetResult;
import org.apache.lucene.facet.Facets;
import org.apache.lucene.facet.FacetsCollector;
import org.apache.lucene.facet.FacetsConfig;
import org.apache.lucene.facet.LabelAndValue;
import org.apache.lucene.facet.range.DoubleRange;
import org.apache.lucene.facet.range.DoubleRangeFacetCounts;
import org.apache.lucene.facet.range.LongRange;
import org.apache.lucene.facet.range.LongRangeFacetCounts;
import org.apache.lucene.facet.range.Range;
import org.apache.lucene.facet.sortedset.SortedSetDocValuesFacetCounts;
import org.apache.lucene.facet.sortedset.SortedSetDocValuesReaderState;
import org.apache.lucene.facet.taxonomy.FastTaxonomyFacetCounts;
import org.apache.lucene.facet.taxonomy.SearcherTaxonomyManager.SearcherAndTaxonomy;
import org.apache.lucene.facet.taxonomy.TaxonomyFacetCounts;
import org.apache.lucene.geo.Polygon;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.index.DocValuesType;
import org.apache.lucene.index.IndexOptions;
import org.apache.lucene.index.IndexReader;
import org.apache.lucene.index.IndexableField;
import org.apache.lucene.index.LeafReader;
import org.apache.lucene.index.LeafReaderContext;
import org.apache.lucene.index.ReaderUtil;
import org.apache.lucene.index.Term;
import org.apache.lucene.queries.CommonTermsQuery;
import org.apache.lucene.queries.function.FunctionValues;
import org.apache.lucene.queries.function.ValueSource;
import org.apache.lucene.queries.function.valuesource.DoubleFieldSource;
import org.apache.lucene.queries.function.valuesource.FloatFieldSource;
import org.apache.lucene.queries.function.valuesource.IntFieldSource;
import org.apache.lucene.queries.function.valuesource.LongFieldSource;
import org.apache.lucene.queryparser.classic.MultiFieldQueryParser;
import org.apache.lucene.queryparser.classic.QueryParser;
import org.apache.lucene.queryparser.classic.QueryParserBase;
import org.apache.lucene.queryparser.simple.SimpleQueryParser;
import org.apache.lucene.search.BooleanClause;
import org.apache.lucene.search.BooleanQuery;
import org.apache.lucene.search.BoostQuery;
import org.apache.lucene.search.Collector;
import org.apache.lucene.search.ConstantScoreQuery;
import org.apache.lucene.search.DisjunctionMaxQuery;
import org.apache.lucene.search.DocIdSet;
import org.apache.lucene.search.DocIdSetIterator;
import org.apache.lucene.search.FieldDoc;
import org.apache.lucene.search.FuzzyQuery;
import org.apache.lucene.search.IndexSearcher;
import org.apache.lucene.search.MatchAllDocsQuery;
import org.apache.lucene.search.MultiCollector;
import org.apache.lucene.search.MultiPhraseQuery;
import org.apache.lucene.search.PhraseQuery;
import org.apache.lucene.search.PrefixQuery;
import org.apache.lucene.search.Query;
import org.apache.lucene.search.ReferenceManager.RefreshListener;
import org.apache.lucene.search.RegexpQuery;
import org.apache.lucene.search.ScoreDoc;
import org.apache.lucene.search.Sort;
import org.apache.lucene.search.SortField;
import org.apache.lucene.search.SortedNumericSelector;
import org.apache.lucene.search.SortedNumericSortField;
import org.apache.lucene.search.SortedSetSelector;
import org.apache.lucene.search.SortedSetSortField;
import org.apache.lucene.search.TermQuery;
import org.apache.lucene.search.TermRangeQuery;
import org.apache.lucene.search.TimeLimitingCollector;
import org.apache.lucene.search.TopDocs;
import org.apache.lucene.search.TopDocsCollector;
import org.apache.lucene.search.TopFieldCollector;
import org.apache.lucene.search.TopFieldDocs;
import org.apache.lucene.search.TopScoreDocCollector;
import org.apache.lucene.search.WildcardQuery;
import org.apache.lucene.search.grouping.GroupDocs;
import org.apache.lucene.search.grouping.SearchGroup;
import org.apache.lucene.search.grouping.TopGroups;
import org.apache.lucene.search.grouping.term.TermAllGroupsCollector;
import org.apache.lucene.search.grouping.term.TermFirstPassGroupingCollector;
import org.apache.lucene.search.grouping.term.TermSecondPassGroupingCollector;
import org.apache.lucene.search.join.BitSetProducer;
import org.apache.lucene.search.join.QueryBitSetProducer;
import org.apache.lucene.search.join.ScoreMode;
import org.apache.lucene.search.join.ToParentBlockJoinCollector;
import org.apache.lucene.search.join.ToParentBlockJoinQuery;
import org.apache.lucene.search.postingshighlight.PassageFormatter;
import org.apache.lucene.search.postingshighlight.PassageScorer;
import org.apache.lucene.search.postingshighlight.PostingsHighlighter;
import org.apache.lucene.search.postingshighlight.WholeBreakIterator;
import org.apache.lucene.server.Constants;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.FieldDefBindings;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.MyIndexSearcher;
import org.apache.lucene.server.SVJSONPassageFormatter;
import org.apache.lucene.server.WholeMVJSONPassageFormatter;
import org.apache.lucene.server.params.*;
import org.apache.lucene.server.params.PolyType.PolyEntry;
import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.FixedBitSet;
import org.apache.lucene.util.QueryBuilder;
import org.apache.lucene.util.automaton.LevenshteinAutomata;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;
import net.minidev.json.JSONValue;

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
  public FinishRequest handle(final IndexState state, final Request r, Map<String,List<String>> params) throws Exception {

    state.verifyStarted(r);

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
    final SearcherAndTaxonomy s = SearchHandler.getSearcherAndTaxonomy(r, state, diagnostics);
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
      state.release(s);
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
