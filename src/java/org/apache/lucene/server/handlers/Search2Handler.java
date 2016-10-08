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
import java.text.ParsePosition;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Calendar;
import java.util.Collection;
import java.util.Collections;
import java.util.Date;
import java.util.GregorianCalendar;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TimeZone;
import java.util.TreeMap;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.Lock;
import java.util.concurrent.locks.ReentrantLock;

import org.apache.lucene.analysis.Analyzer;
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
import org.apache.lucene.server.QueryID;
import org.apache.lucene.server.RemoteNodeConnection;
import org.apache.lucene.server.SVJSONPassageFormatter;
import org.apache.lucene.server.WholeMVJSONPassageFormatter;
import org.apache.lucene.server.params.*;
import org.apache.lucene.server.params.PolyType.PolyEntry;
import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.FixedBitSet;
import org.apache.lucene.util.QueryBuilder;
import org.apache.lucene.util.StringHelper;
import org.apache.lucene.util.automaton.LevenshteinAutomata;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;
import net.minidev.json.JSONValue;

// nocommit why no double range faceting?

// nocommit remove SearchHandler and replace w/ this impl

/** Handles {@code search} using distributed queue. */
public class Search2Handler extends Handler {

  private final static StructType TYPE =
    new StructType(
        new Param("queryText", "Query text to parse using the specified QueryParser.", new StringType()),
        new Param("indexNames", "Which indices to query.", new ListType(new StringType()))
                   );
  @Override
  public String getTopDoc() {
    return "Execute a search.";
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  /** Sole constructor. */
  public Search2Handler(GlobalState state) {
    super(state);
    requiresIndexName = false;
  }

  /** Holds returned results from one index */
  private static class QueryHits {
    public final QueryID queryID;
    public final TopDocs hits;

    public QueryHits(QueryID queryID, TopDocs hits) {
      this.queryID = queryID;
      this.hits = hits;
    }
  }

  /** Returned hits are added here */
  private final Map<QueryID,QueryHits> pendingHits = new HashMap<>();

  public synchronized void deliverHits(QueryID queryID, TopDocs hits) {
    pendingHits.put(queryID, new QueryHits(queryID, hits));
    notifyAll();
  }

  @Override
  public FinishRequest handle(final IndexState state, final Request r, Map<String,List<String>> params) throws Exception {

    String queryText = r.getString("queryText");

    final Set<QueryID> queryIDs = new HashSet<>();

    long t0 = System.nanoTime();

    for(Object _indexName : r.getList("indexNames")) {

      String indexName = (String) _indexName;

      // Assign a unique ID for this query + indexName
      QueryID queryID = new QueryID();

      queryIDs.add(queryID);

      // Enroll the query in the distributed queue:
      globalState.searchQueue.addNewQuery(queryID, indexName, 0, queryText, globalState.nodeID);

      // nocommit move this into addNewQuery
      for(RemoteNodeConnection node : globalState.remoteNodes) {
        synchronized(node.c) {
          node.c.out.writeByte(NodeToNodeHandler.CMD_NEW_QUERY);
          node.c.out.writeBytes(queryID.id, 0, queryID.id.length);
          node.c.out.writeString(indexName);
          node.c.out.writeString(queryText);
          node.c.flush();
        }
      }
    }

    // TODO: we could let "wait for results" be optional here:

    // Wait for hits to come back:
    final List<QueryHits> allHits = new ArrayList<>();
    synchronized(this) {
      while (true) {
        Iterator<QueryID> it = queryIDs.iterator();
        while (it.hasNext()) {
          QueryID queryID = it.next();
          QueryHits hits = pendingHits.remove(queryID);
          if (hits != null) {
            allHits.add(hits);
            it.remove();
          }
        }
        if (queryIDs.size() == 0) {
          break;
        }
        wait();
      }
    }

    final double msec = (System.nanoTime()-t0)/1000000.0;

    TopDocs[] allTopDocs = new TopDocs[allHits.size()];
    for(int i=0;i<allTopDocs.length;i++) {
      allTopDocs[i] = allHits.get(i).hits;
    }
    final TopDocs mergedHits = TopDocs.merge(10, allTopDocs);

    return new FinishRequest() {
      @Override
      public String finish() throws IOException {
        JSONObject result = new JSONObject();
        //result.put("queryID", queryID);
        result.put("queryTimeMS", msec);
        result.put("totalHits", mergedHits.totalHits);
        JSONArray hitsArray = new JSONArray();
        for(ScoreDoc hit : mergedHits.scoreDocs) {
          JSONObject hitObj = new JSONObject();
          hitObj.put("docID", hit.doc);
          hitObj.put("score", hit.score);
          hitsArray.add(hitObj);
        }
        result.put("hits", hitsArray);
        return result.toString();
      }
    };
  }
}
