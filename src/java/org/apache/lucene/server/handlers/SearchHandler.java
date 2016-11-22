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
import org.apache.lucene.search.join.ToParentBlockJoinIndexSearcher;
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
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.WholeMVJSONPassageFormatter;
import org.apache.lucene.server.params.AnyType;
import org.apache.lucene.server.params.BooleanType;
import org.apache.lucene.server.params.EnumType;
import org.apache.lucene.server.params.FloatType;
import org.apache.lucene.server.params.IntType;
import org.apache.lucene.server.params.ListType;
import org.apache.lucene.server.params.LongType;
import org.apache.lucene.server.params.OrType;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.PolyType.PolyEntry;
import org.apache.lucene.server.params.PolyType;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.server.params.Type;
import org.apache.lucene.server.params.WrapType;
import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.QueryBuilder;
import org.apache.lucene.util.automaton.LevenshteinAutomata;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

// nocommit why no double range faceting?

/** Handles {@code search}. */
public class SearchHandler extends Handler {

  /** If a browse-only facet request asks for more than this
   *  count then we don't cache it. */
  private final static int TOP_FACET_CACHE_MAX_FACET_COUNT = 100;

  final static Type SORT_TYPE = new ListType(
                                    new StructType(new Param("field", "The field to sort on.  Pass <code>docid</code> for index order and <code>score</code> for relevance sort.", new StringType()),
                                                   new Param("selector", "For multi valued fields, how to select which value is used for sorting",
                                                             new EnumType("min", "Minimum value",
                                                                          "max", "Maximum value",
                                                                          "middle_min", "Middle value of the set; if there are an even number of values, the lower of the middle two is chosen",
                                                                          "middle_max", "Middle value of the set; if there are an even number of values, the upper of the middle two is chosen"),
                                                             "min"),
                                                   new Param("origin", "For distance sort, the point that we measure distance from",
                                                             new StructType(
                                                                            new Param("latitude", "Latitude of the origin", new FloatType()),
                                                                            new Param("longitude", "Longitude of the origin", new FloatType()))),
                                                   new Param("missingLast", "Whether missing values should sort last instead of first.  Note that this runs \"before\" reverse, so if you sort missing first and reverse=true then missing values will be at the end.", new BooleanType(), false),
                                                   new Param("reverse", "Sort in reverse of the field's natural order", new BooleanType(), false)));

  private final static Type BOOLEAN_OCCUR_TYPE = new EnumType("must", "Clause is required.",
                                                              "should", "Clause is optional.",
                                                              "must_not", "Clause must not match.",
                                                              "filter", "Clause is required but does not score");

  private final static WrapType FILTER_TYPE_WRAP = new WrapType();
  private final static WrapType QUERY_TYPE_WRAP = new WrapType();

  private final static StructType QUERY_TYPE = new StructType(
                                 new Param("boost", "Query boost", new FloatType(), 1.0f),
                                 new Param("field", "Which field to use for this query and any sub-queries ", new StringType()),
                                 new Param("class", "Query class",
                                     new PolyType(Query.class,
                                         new PolyEntry("DisjunctionMaxQuery", "A query that generates the union of documents produced by its subqueries, and that scores each document with the maximum score for that document as produced by any subquery, plus a tie breaking increment for any additional matching subqueries (see @lucene:core:org.apache.lucene.search.DisjunctionMaxQuery)",
                                                       new Param("subQueries", "Queries to OR/max together.", new ListType(QUERY_TYPE_WRAP)),
                                                       new Param("tieBreakMultiplier", "Tie break score.", new FloatType(), 0.0f)),
                                         new PolyEntry("BooleanQuery", "A Query that matches documents matching boolean combinations of other queries, e.g (see @lucene:core:org.apache.lucene.search.BooleanQuery)",
                                                       new Param("subQueries", "Queries to OR/max together.",
                                                           new ListType(
                                                               new StructType(
                                                                   new Param("occur", "Occur.", BOOLEAN_OCCUR_TYPE),
                                                                   new Param("query", "Query for this clause", QUERY_TYPE_WRAP)))),
                                                       new Param("disableCoord", "If true, coord factors will not be used", new BooleanType(), false),
                                                       new Param("minimumNumberShouldMatch", "Minimum number of should clauses for a match.", new IntType(), 0)),
                                         new PolyEntry("CommonTermsQuery", "A query that executes high-frequency terms in a optional sub-query to prevent slow queries due to common terms like stopwords (see @lucene:queries:org.apache.lucene.queries.CommonTermsQuery)",
                                                       new Param("terms", "List of terms", new ListType(new StringType())),
                                                       new Param("lowFreqOccur", "BooleanClause.Occur used for low frequency terms", BOOLEAN_OCCUR_TYPE),
                                                       new Param("highFreqOccur", "BooleanClause.Occur used for high frequency terms", BOOLEAN_OCCUR_TYPE),
                                                       new Param("maxTermFrequency", "a value from [0.0, 1.0) or an absolutely number >= 1 representing the maximum threshold of a terms document frequency to be considered a low frequency term", new FloatType())),
                                         new PolyEntry("ConstantScoreQuery", "A query that wraps another query or a filter and simply returns a constant score equal to the query boost for every document that matches the filter or query (see @lucene:core:org.apache.lucene.search.ConstantScoreQuery)",
                                                       new Param("query", "Wrapped query", QUERY_TYPE_WRAP)),
                                         new PolyEntry("FuzzyQuery", "Implements the fuzzy search query (see @lucene:core:org.apache.lucene.search.FuzzyQuery)",
                                                       new Param("term", "Term text", new StringType()),
                                                       new Param("maxEdits", "Maximum number of edits; must be 1 or 2", new IntType(), FuzzyQuery.defaultMaxEdits),
                                                       new Param("prefixLength", "Length of the common (non-fuzzy) prefix", new IntType(), FuzzyQuery.defaultPrefixLength),
                                                       new Param("maxExpansions", "Maximum number of terms to match", new IntType(), FuzzyQuery.defaultMaxExpansions),
                                                       new Param("transpositions", "Whether transposition counts as a single edit", new BooleanType(), FuzzyQuery.defaultTranspositions)),
                                         new PolyEntry("BooleanFieldQuery", "Matches true values from a boolean type field",
                                                       new Param("field", "Which boolean field to query", new StringType())),
                                         new PolyEntry("MatchAllDocsQuery", "A query that matches all documents. (see @lucene:core:org.apache.lucene.search.MatchAllDocsQuery)"),
                                         new PolyEntry("MultiPhraseQuery", "MultiPhraseQuery is a generalized version of PhraseQuery, with an added method #add(Term[]) (see @lucene:core:org.apache.lucene.search.MultiPhraseQuery)",
                                                       new Param("terms", "List of terms/positions in the phrase",
                                                                 new ListType(new OrType(new StringType(),
                                                                                         new StructType(
                                                                                                        new Param("term", "Term(s) text", new OrType(new ListType(new StringType()),
                                                                                                                                                  new StringType())),
                                                                                                        new Param("position", "Which position this term should appear at", new IntType())),
                                                                                         new ListType(new StringType())))),
                                                       new Param("slop", "The number of other words permitted between words in the phrase.  If this is 0 (the default) then the phrase must be an exact match.", new IntType(), 0)),
                                         new PolyEntry("NumericRangeQuery", "Matches documents with a numeric field in the specified range",
                                                       new Param("min", "Minimum value", new AnyType()),
                                                       new Param("max", "Maximum value", new AnyType())),
                                         new PolyEntry("PhraseQuery", "A Query that matches documents containing a particular sequence of terms (see @lucene:core:org.apache.lucene.search.PhraseQuery)",
                                                       new Param("terms", "List of terms in the phrase", new ListType(new StringType())),
                                                       new Param("slop", "The number of other words permitted between words in the phrase.  If this is 0 (the default) then the phrase must be an exact match.", new IntType(), 0)),
                                         new PolyEntry("PrefixQuery", "A Query that matches documents containing terms with a specified prefix (see @lucene:core:org.apache.lucene.search.PrefixQuery)",
                                                       new Param("term", "Prefix text", new StringType())),
                                         new PolyEntry("RegexpQuery", "A fast regular expression query based on the org.apache.lucene.util.automaton package (see @lucene:core:org.apache.lucene.search.RegexpQuery)",
                                                       new Param("regexp", "Regular expression text", new StringType())),
                                         new PolyEntry("TermRangeQuery", "A Query that matches documents within an range of terms (see @lucene:core:org.apache.lucene.search.TermRangeQuery)",
                                                       new Param("lowerTerm", "Lower term", new StringType()),
                                                       new Param("includeLower", "True if lower term is included", new BooleanType()),
                                                       new Param("upperTerm", "Upper term", new StringType()),
                                                       new Param("includeUpper", "True if upper term is included", new BooleanType())),
                                         new PolyEntry("TermQuery", "A Query that matches documents containing a term (see @lucene:core:org.apache.lucene.search.TermQuery)",
                                                       new Param("term", "Term text", new StringType())),
                                         new PolyEntry("ToParentBlockJoinQuery", "A parent query that wraps another (child) query and joins matches from the child to the parent documents (see @lucene:join:org.apache.lucene.search.ToParentBlockJoinQuery)",
                                                       new Param("childQuery", "Child query", QUERY_TYPE_WRAP),
                                                       new Param("parentsFilter", "Filter identifying parent documents", QUERY_TYPE_WRAP),
                                                       new Param("scoreMode", "How scores are propogated from children to parent hit",
                                                                 new EnumType(
                                                                              "Avg", "Average all child scores",
                                                                              "Max", "Max of all child scores",
                                                                              "Total", "Sum of all child scores",
                                                                              "None", "Child scores are ignored"), "Max"),
                                                       new Param("childHits", "Whether and how to return child hits for each parent hit",
                                                                 new StructType(
                                                                     new Param("sort", "How to sort child hits", SORT_TYPE),
                                                                     new Param("maxChildren", "Maximum number of children to retrieve per parent", new IntType(), Integer.MAX_VALUE),
                                                                     new Param("trackScores", "Whether to compute scores", new BooleanType(), true),
                                                                     new Param("trackMaxScore", "Whether to compute max score", new BooleanType(), true)))),
                                         new PolyEntry("text", "Parse text into query using default QueryParser.",
                                                       new Param("text", "Query text to parse", new StringType()),
                                                       new Param("defaultField", "Default field for QueryParser", new StringType())),
                                         new PolyEntry("LatLonBoxQuery", "A Query that matches documents containing a LatLonPoint inside a box (see @lucene:sandbox:org.apache.lucene.document.LatLonPoint#newBoxQuery)",
                                                       new Param("minLatitude", "Minimum latitude, inclusive", new FloatType()),
                                                       new Param("maxLatitude", "Maximum latitude, inclusive", new FloatType()),
                                                       new Param("minLongitude", "Minimum longitude, inclusive", new FloatType()),
                                                       new Param("maxLongitude", "Maximum longitude, inclusive", new FloatType())),
                                         new PolyEntry("LatLonDistanceQuery", "A Query that matches documents containing a LatLonPoint within a specified distance of an origin point (see @lucene:sandbox:org.apache.lucene.document.LatLonPoint#newDistanceQuery)",
                                                       new Param("latitude", "Latitude of the origin", new FloatType()),
                                                       new Param("longitude", "Longitude of the origin", new FloatType()),
                                                       new Param("radiusMeters", "Radius in meters", new FloatType())),
                                         new PolyEntry("LatLonPolygonQuery", "A Query that matches documents containing a LatLonPoint within a specified polygon (see @lucene:sandbox:org.apache.lucene.document.LatLonPoint#newPolygonQuery)",
                                                       new Param("geojson", "GEOJson string describing the polygon (an alternative to vertices+holes)",
                                                                 new StringType()),
                                                       new Param("polygons", "List of polygons to search",
                                                           new ListType(
                                                               new StructType(
                                                                   new Param("vertices", "Array of latitude/longitude points",
                                                                             new ListType(new ListType(new FloatType()))),
                                                                   new Param("holes", "Array of array of latitude/longitude points for the holes to exclude hits within the polygon",
                                                                             new ListType(new ListType(new ListType(new FloatType())))))))),
                                         new PolyEntry("WildcardQuery", "Implements the wildcard search query (see @lucene:core:org.apache.lucene.search.WildcardQuery)",
                                                       new Param("term", "Wildcard text", new StringType())))));

  static {
    QUERY_TYPE_WRAP.set(QUERY_TYPE);
  }

  public static final StructType SEARCHER_VERSION_TYPE = new StructType(
                new Param("indexGen", "Search a generation previously returned by an indexing operation such as #addDocument.  Use this to search a non-committed (near-real-time) view of the index.", new LongType()),
                new Param("snapshot", "Search a snapshot previously created with #createSnapshot", new StringType()),
                new Param("version", "Search a specific searcher version.  This is typically used by follow-on searches (e.g., user clicks next page, drills down, or changes sort, etc.) to get the same searcher used by the original search.", new LongType()));

  final static Type LOCALE_TYPE = new StructType(new Param("language", "Locale language", new StringType()),
                                                 new Param("country", "Locale country", new StringType()),
                                                 new Param("variant", "Locale variant", new StringType()));

  private final static Type QUERY_PARSER_TYPE = new StructType(
                      new Param("defaultOperator", "Whether terms are OR'd or AND'd by default.",
                                new EnumType("or", "or", "and", "and"), "or"),
                      new Param("fuzzyMinSim", "Minimum similarity for fuzzy queries", new IntType(), LevenshteinAutomata.MAXIMUM_SUPPORTED_DISTANCE),
                      new Param("fuzzyPrefixLength", "Prefix length for fuzzy queries", new IntType(), FuzzyQuery.defaultPrefixLength),
                      new Param("phraseSlop", "Default slop for phrase queries", new IntType(), 0),
                      new Param("enablePositionIncrements", "When set, phrase and multi-phrase queries will be aware of position increments", new BooleanType(), true),
                      new Param("locale", "Locale to be used by date range parsing, lowercasing and other locale-sensitive operations", LOCALE_TYPE),
                      new Param("class", "Which QueryParser to use.",
                                new PolyType(QueryParser.class,
                                             new PolyEntry("SimpleQueryParser", "@lucene:queryparser:org.apache.lucene.queryparser.simple.SimpleQueryParser is used to parse human readable query syntax.",
                                                 new Param("operators", "Which operators to allow",
                                                     new ListType(
                                                         new EnumType("AND", "Enable the AND operator with +",
                                                                      "OR", "Enable the OR operator with |",
                                                                      "NOT", "Enable the NOT operator with -",
                                                                      "PREFIX", "Enable the PREFIX operator with *",
                                                                      "PHRASE", "Enable the PHRASE operator with \"",
                                                                      "PRECEDENCE", "Enable the PRECEDENCE operator with ( and )",
                                                                      "ESCAPE", "Enable the ESCAPE operator with \\",
                                                                      "WHITESPACE", "Enable the WHITESPACE operator with ' ', '\\n', '\\r, or '\\t'")),
                                                     new ArrayList<Object>()),
                                                 new Param("fields", "Which fields/boosts to query against",
                                                     new ListType(new OrType(new StringType(),
                                                          new StructType(
                                                              new Param("field", "Field name", new StringType()),
                                                              new Param("boost", "Field boost", new FloatType())))))),
                                             new PolyEntry("MultiFieldQueryParser", "",
                                                           new Param("fields", "Which fields/boosts to query against",
                                                                     new ListType(new OrType(new StringType(),
                                                                                             new StructType(
                                                                                                            new Param("field", "Field name", new StringType()),
                                                                                                            new Param("boost", "Field boost", new FloatType())))))),
                                             new PolyEntry("classic", "Classic QueryParser.",
                                                           new Param("defaultField", "Default field to query against.", new StringType()))),
                                "classic")
                      );

  private static final StructType NUMERIC_RANGE_TYPE = new StructType(new Param("label", "Label for this range", new StringType()),
                                                           new Param("min", "Min value for the range", new OrType(new LongType(), new FloatType())),
                                                           new Param("minInclusive", "True if the min value is inclusive", new BooleanType()),
                                                           new Param("max", "Max value for the range", new OrType(new LongType(), new FloatType())),
                                                           new Param("maxInclusive", "True if the max value is inclusive", new BooleanType()));

  private final static StructType TYPE =
    new StructType(
        new Param("indexName", "Which index to search", new StringType()),
        new Param("timeStamp", "The 'current' timestamp to use, e.g. for blended sorting; typically this should be fixed and reused from the returned value from the first query in a session so that as the user does follow-on paging, drill-downs, etc., the results don't unexpectedly changing.", new LongType()),
        new Param("queryText", "Query text to parse using the specified QueryParser.", new StringType()),
        new Param("queryParser", "Which QueryParser to use; by default MultiFieldQUeryParser searching all indexed fields will be used", QUERY_PARSER_TYPE),
        new Param("highlighter", "Highlighter configuration to use when highlighting matches.",
                  new StructType(
                      new Param("maxPassages", "Maximum number of passages to extract.", new IntType(), 2),
                      new Param("class", "Which implementation to use",
                                new PolyType(Object.class,
                                             new PolyEntry("PostingsHighlighter", "PostingsHighlighter",
                                                           new Param("maxLength", "Only highlight the first N bytes of each item.", new IntType(), PostingsHighlighter.DEFAULT_MAX_LENGTH),
                                                           new Param("maxSnippetLength", "Maximum length (in chars) for each text snippet chunk.", new IntType(), 100),
                                                           new Param("passageScorer.b", "Scoring factor b in PassageScorer", new FloatType(), 0.75f),
                                                           new Param("passageScorer.k1", "Scoring factor k1 in PassageScorer", new FloatType(), 0.8f),
                                                           new Param("passageScorer.pivot", "Scoring factor pivot in PassageScorer", new FloatType(), 87f),
                                                           //new Param("passageScorer.proxScoring", "True if proximity passage scoring should be used", new BooleanType(), true),
                                                           new Param("breakIterator", "Which BreakIterator to use to create fragments",
                                                               new StructType(
                                                                   new Param("locale", "Locale", SearchHandler.LOCALE_TYPE),
                                                                   new Param("mode", "Which BreakIterator to create",
                                                                             new EnumType("character", "Character instance",
                                                                                          "word", "Word instance",
                                                                                          "line", "Line instance",
                                                                                          "sentence", "Sentence instance"),
                                                                             "sentence")))
                                                           )),
                                "PostingsHighlighter"))),
        new Param("query", "Full query to execute (not using QueryParser).", QUERY_TYPE),
        new Param("grouping", "Whether/how to group search results.",
                  new StructType(
                                 new Param("field", "Field to group by.", new StringType()),
                                 new Param("groupStart", "Which group to start from (for pagination).", new IntType(), 0),
                                 new Param("groupsPerPage", "How many groups to include on each page.", new IntType(), 3),
                                 new Param("hitsPerGroup", "How many top hits to include in each group.", new IntType(), 4),
                                 new Param("doMaxScore", "Whether to compute maxScore for each group.", new BooleanType(), false),
                                 new Param("doDocScores", "Whether to compute scores for each hit in each group.", new BooleanType(), true),
                                 new Param("sort", "How to sort groups (default is by relevance).", SORT_TYPE),
                                 new Param("doTotalGroupCount", "If true, return the total number of groups (at possibly highish added CPU cost)",
                                           new BooleanType(), false))),
        new Param("searcher", "Specific searcher version to use for searching.  There are three different ways to specify a searcher version.",
                  SEARCHER_VERSION_TYPE),
        new Param("startHit", "Which hit to start from (for pagination).", new IntType(), 0),
        new Param("topHits", "How many top hits to retrieve.", new IntType(), 10),
        new Param("virtualFields", "Defines virtual fields (name'd dynamic expressions) for this query.",
                  new ListType(
                      new StructType(
                          new Param("name", "Virtual field's name.  Must be different from registered fields and any other virtual fields.", new StringType()),
                          new Param("expression", "JavaScript expression defining this field's values.", new StringType())))),
        new Param("searchAfter", "Only return hits after the specified hit; this is useful for deep paging",
                  new StructType(
                                 new Param("lastDoc", "Last docID of the previous page.", new IntType()),
                                 new Param("lastFieldValues", "Last sort field values of the previous page.", new ListType(new AnyType())),
                                 new Param("lastScore", "Last score of the previous page.", new FloatType()))),
        new Param("retrieveFields", "Which fields to highlight or retrieve.",
                  new ListType(
                      new OrType(
                             new StringType(),
                             new StructType(
                                   new Param("field", "Name of the field in the index.", new StringType()),
                                   //new Param("label", "Label to be used for this value in the returned result, in case you want to retrieve the same field more than once, e.g. one time with highlighting and another time without, or with different highlighting params.", new StringType()),
                                   new Param("highlight", "Whether and how to highlight this field",
                                             new EnumType("no", "No highlighting",
                                                          "whole", "The entire field value(s) is/are highlighted and returned",
                                                          "snippets", "Snippets are extracted from the field value(s); multi-valued fields are concatenated and treated as a single text"),
                                             "no"),
                                   // TODO: make other highlighter config per-field too (maxLength, scoring, proxScoring)
                                   // TODO: factor out & share w/ top-level type
                                   new Param("maxPassages", "Maximum number of passages to extract for this field", new IntType(), 2),
                                   new Param("breakIterator", "Which BreakIterator to use to create fragments",
                                             new StructType(
                                                            new Param("locale", "Locale", SearchHandler.LOCALE_TYPE),
                                                            new Param("mode", "Which BreakIterator to create",
                                                                      new EnumType("character", "Character instance",
                                                                                   "word", "Word instance",
                                                                                   "line", "Line instance",
                                                                                   "sentence", "Sentence instance"),
                                                                      "sentence")))

                                            )))),
        new Param("facets", "Which facets to retrieve.",
                  new ListType(
                               new StructType(
                                   // nocommit rename to field:
                                   new Param("dim", "Dimension (field).", new StringType()),
                                   new Param("path", "Prefix path to facet 'under'.",
                                             new OrType(new StringType(), new ListType(new StringType()))),
                                   new Param("numericRanges", "Custom numeric ranges.  Field must be indexed with facet=numericRange.",
                                       new ListType(NUMERIC_RANGE_TYPE)),
                                   // new Param("autoDrillDown", "True if single-child facet should be auto-expanded (not yet implemented!).", new BooleanType()),
                                   new Param("useOrdsCache", "True if the ordinals cache should be used.", new BooleanType(), false),
                                   new Param("labels", "Specific facet labels to retrieve.", new ListType(new StringType())),
                                   new Param("topN", "How many top facets to return.", new IntType(), 7)))),
        new Param("drillDowns", "Facet drill down filters to apply.",
                  new ListType(new StructType(
                                   new Param("field", "Field name to drill down on.", new StringType()),
                                   new Param("query", "Sub-query for drill down (e.g., use NumericRangeQuery to drill down on dynamic ranges).", QUERY_TYPE),
                                   new Param("numericRange", "A numeric range to drill down on", NUMERIC_RANGE_TYPE),
                                   new Param("value", "Which values to allow, either String or array of String.  Drill down on the same field more than once to OR multiple drill-down values for that field.",
                                             new OrType(new StringType(), new ListType(new StringType())))))),
        new Param("sort", "Sort hits by field (default is by relevance).",
                  new StructType(
                      new Param("doMaxScore", "Compute the max score across all hits (costs added CPU).", new BooleanType(), false),
                      new Param("doDocScores", "Compute the doc score for each collected (costs added CPU).", new BooleanType(), false),
                      new Param("fields", "Fields to sort on.", SORT_TYPE))),
        new Param("timeoutSec", "Maximum number of seconds spent on each collection phase; note that for multi-pass searches (e.g. query-time grouping), this timeout applies to each phase.", new FloatType())
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
  public SearchHandler(GlobalState state) {
    super(state);
  }

  /** Holds the state for a single {@link
   *  PostingsHighlighter} instance. */
  public final class HighlighterConfig {
    CachedDocsJSONPostingsHighlighter highlighter;
    int maxPassages;
    String config;

    /** Sole constructor. */
    public HighlighterConfig() {
    }

    /** Holds field values for all documents we loaded for
     * this request. */
    Map<Integer,Map<String,Object>> docsCache = new HashMap<Integer,Map<String,Object>>();

    /** Load the fiels for a single document, using the
     *  cache so we only ever load a document once from
     *  Lucene. */
    @SuppressWarnings("unchecked")
    public Map<String,Object> getDocument(IndexState state, IndexSearcher searcher, int docID) throws IOException {
      Map<String,Object> doc = docsCache.get(docID);
      if (doc == null) {
        // Load & cache all stored fields:
        doc = new HashMap<String,Object>();
        docsCache.put(docID, doc);
        for(IndexableField field : searcher.doc(docID)) {
          String name = field.name();
          FieldDef fd = state.getField(name);
          Object value = field.numericValue();
          if (value == null) {
            value = field.stringValue();
          }
          Object o = doc.get(name);
          if (o == null) {
            if (fd.multiValued) {
              List<Object> l = new ArrayList<Object>();
              l.add(value);
              value = l;
            }
            doc.put(name, value);
          } else {
            assert o instanceof List;
            ((List<Object>) o).add(value);
          }
        }
      }
      return doc;
    }
  }

  /** Loads docs/fields from a shared cache so we only call
   *  IndexReader.document once per hit */
  private static class CachedDocsJSONPostingsHighlighter extends PostingsHighlighter {
    private final HighlighterConfig config;
    private final IndexState state;
    private final Map<String,FieldHighlightConfig> perFieldConfig;
    private final PassageScorer scorer;
    private final BreakIterator defaultBI;
    private final int maxSnippetLength;

    public CachedDocsJSONPostingsHighlighter(IndexState state, HighlighterConfig config,
                                             Map<String,FieldHighlightConfig> perFieldConfig,
                                             int maxLength, int maxSnippetLength, PassageScorer scorer, BreakIterator defaultBI) {
      super(maxLength);
      this.maxSnippetLength = maxSnippetLength;
      this.perFieldConfig = perFieldConfig;
      this.config = config;
      this.scorer = scorer;
      this.state = state;
      this.defaultBI = defaultBI;
    }

    @Override
    protected PassageScorer getScorer(String fieldName) {
      return scorer;
    }

    @Override
    protected Analyzer getIndexAnalyzer(String fieldName) {
      return state.getField(fieldName).indexAnalyzer;
    }

    @Override
    protected BreakIterator getBreakIterator(String fieldName) {
      FieldHighlightConfig perField = perFieldConfig.get(fieldName);
      if (perField.mode.equals("whole")) {
        return new WholeBreakIterator();
      } else if (perField.breakIterator != null) {
        return perField.breakIterator;
      } else {
        return defaultBI;
      }
    }

    @Override
    protected PassageFormatter getFormatter(String fieldName) {
      FieldHighlightConfig perField = perFieldConfig.get(fieldName);
      if (perField.multiValued && perField.mode.equals("whole")) {
        FieldDef fd = state.getField(fieldName);
        assert fd.indexAnalyzer != null;
        return new WholeMVJSONPassageFormatter(fd.indexAnalyzer.getOffsetGap(fieldName));
      } else {
        return new SVJSONPassageFormatter(maxSnippetLength);
      }
    }

    /** Highlights directly to JSONArray[]. */
    public Map<String,Object[]> highlightToObjects(String fieldsIn[], Query query, IndexSearcher searcher, int docidsIn[], int maxPassagesIn[]) throws IOException {
      return super.highlightFieldsAsObjects(fieldsIn, query, searcher, docidsIn, maxPassagesIn);
    }

    // TODO: allow pulling from DV too:

    @SuppressWarnings("unchecked")
    @Override
    protected String[][] loadFieldValues(IndexSearcher searcher, String[] fields, int[] docIDs, int maxLength) throws IOException {
      String[][] contents = new String[fields.length][docIDs.length];
      for (int i = 0; i < docIDs.length; i++) {
        Map<String,Object> doc = config.getDocument(state, searcher, docIDs[i]);

        for (int j = 0; j < fields.length; j++) {
          Object o = doc.get(fields[j]);
          FieldHighlightConfig perField = perFieldConfig.get(fields[j]);
          boolean isWhole = perField.mode.equals("whole");
          if (o != null) {
            String value;
            if (o instanceof List) {
              StringBuilder sb = new StringBuilder();
              for(Object _s : (List<Object>) o) {
                // Schema enforces only text/atom fields can
                // be highlighted:
                assert _s instanceof String;
                String s = (String) _s;

                if (sb.length() > 0) {
                  if (isWhole) {
                    // NOTE: we ensured this character does
                    // not occur in the content, at indexing
                    // time.  We could remove this restriction
                    // by looking at the actual String[]
                    // values for the field while formatting
                    // the passages:
                    sb.append(Constants.INFORMATION_SEP);
                  } else {
                    sb.append(' ');
                  }
                }
                
                if (sb.length() + s.length() > maxLength) {
                  sb.append(s, 0, maxLength - sb.length());
                  break;
                } else {
                  sb.append(s);
                }
              }
              value = sb.toString();
            } else {
              String s = (String) o;
              if (s.length() > maxLength) {
                value = s.substring(0, maxLength);
              } else {
                value = s;
              }
            }
            contents[j][i] = value;
          } else {
            contents[j][i] = "";
          }
        }
      }

      return contents;
    }
  }

  private static BreakIterator parseBreakIterator(Request r) {
    BreakIterator bi;
    if (r.hasParam("breakIterator")) {
      Request r2 = r.getStruct("breakIterator");
      Locale locale = getLocale(r2.getStruct("locale"));
      String mode = r.getString("mode");
      if (mode.equals("character")) {
        bi = BreakIterator.getCharacterInstance(locale);
      } else if (mode.equals("word")) {
        bi = BreakIterator.getWordInstance(locale);
      } else if (mode.equals("line")) {
        bi = BreakIterator.getLineInstance(locale);
      } else if (mode.equals("sentence")) {
        bi = BreakIterator.getSentenceInstance(locale);
      } else {
        assert false;
        bi = null;
      }
    } else {
      bi = BreakIterator.getSentenceInstance(Locale.ROOT);
    }
    return bi;
  }

  private HighlighterConfig getHighlighter(IndexState state, Request r, Map<String,FieldHighlightConfig> highlightFields) {
    HighlighterConfig config = new HighlighterConfig();

    if (r.hasParam("highlighter")) {
      r = r.getStruct("highlighter");
      config.maxPassages = r.getInt("maxPassages");

      final Request.PolyResult pr = r.getPoly("class");
      if (!pr.name.equals("PostingsHighlighter")) {
        r.fail("class", "Only PostingsHighlighter is currently supported.");
      } 

      r = pr.r;

      //final boolean doProx = r.getBoolean("passageScorer.proxScoring");

      // TODO: BreakIterator Locale?
      PassageScorer scorer = new PassageScorer(r.getFloat("passageScorer.k1"), r.getFloat("passageScorer.b"), r.getFloat("passageScorer.pivot"));

      final BreakIterator bi = parseBreakIterator(r);
      config.highlighter = new CachedDocsJSONPostingsHighlighter(state,
                                                                 config,
                                                                 highlightFields,
                                                                 r.getInt("maxLength"),
                                                                 r.getInt("maxSnippetLength"),
                                                                 scorer,
                                                                 bi);
    } else {
      // Default:
      config.maxPassages = 2;
      config.highlighter = new CachedDocsJSONPostingsHighlighter(state,
                                                                 config,
                                                                 highlightFields,
                                                                 PostingsHighlighter.DEFAULT_MAX_LENGTH,
                                                                 100,
                                                                 new PassageScorer(),
                                                                 BreakIterator.getSentenceInstance(Locale.ROOT));
    }

    return config;
  }

  /** Decodes a list of Request into the corresponding Sort. */
  static Sort parseSort(long timestampSec, IndexState state, List<Object> fields, List<String> sortFieldNames, Map<String,FieldDef> dynamicFields) {
    List<SortField> sortFields = new ArrayList<SortField>();
    for(Object _sub : fields) {
      Request sub = (Request) _sub;

      String fieldName = sub.getString("field");
      SortField sf;
      if (sortFieldNames != null) {
        sortFieldNames.add(fieldName);
      }
      if (fieldName.equals("docid")) {
        sf = SortField.FIELD_DOC;
      } else if (fieldName.equals("score")) {
        sf = SortField.FIELD_SCORE;
      } else {
        FieldDef fd;
        if (dynamicFields != null) {
          fd = dynamicFields.get(fieldName);
        } else {
          fd = null;
        }
        if (fd == null) {
          fd = state.getField(fieldName);
        }
        if (fd == null) {
          sub.fail("field", "field \"" + fieldName + "\" was not registered and was not specified as a dynamicField");
          // Dead code but compiler disagrees:
          fd = null;
        }

        if (fd.valueSource != null) {
          sf = fd.valueSource.getSortField(sub.getBoolean("reverse"));
        } else if (fd.valueType == FieldDef.FieldValueType.LAT_LON) {
          if (fd.fieldType.docValuesType() == DocValuesType.NONE) {
            sub.fail("field", "field \"" + fieldName + "\" was not registered with sort=true");
          }
          Request sub2 = sub.getStruct("origin");
          sf = LatLonDocValuesField.newDistanceSort(fieldName, sub2.getDouble("latitude"), sub2.getDouble("longitude"));
        } else {
          if ((fd.fieldType != null && fd.fieldType.docValuesType() == DocValuesType.NONE) ||
              (fd.fieldType == null && fd.valueSource == null)) {
            sub.fail("field", "field \"" + fieldName + "\" was not registered with sort=true");
          }

          if (fd.multiValued) {
            String selectorString = sub.getEnum("selector");
            if (fd.valueType == FieldDef.FieldValueType.ATOM) {
              SortedSetSelector.Type selector;
              if (selectorString.equals("min")) {
                selector = SortedSetSelector.Type.MIN;
              } else if (selectorString.equals("max")) {
                selector = SortedSetSelector.Type.MAX;
              } else if (selectorString.equals("middle_min")) {
                selector = SortedSetSelector.Type.MIDDLE_MIN;
              } else if (selectorString.equals("middle_max")) {
                selector = SortedSetSelector.Type.MIDDLE_MAX;
              } else {
                assert false;
                // dead code but javac disagrees
                selector = null;
              }
              sf = new SortedSetSortField(fieldName, sub.getBoolean("reverse"), selector);
            } else if (fd.valueType == FieldDef.FieldValueType.INT) {
              sf = new SortedNumericSortField(fieldName, SortField.Type.INT, sub.getBoolean("reverse"), parseNumericSelector(sub, selectorString));
            } else if (fd.valueType == FieldDef.FieldValueType.LONG) {
              sf = new SortedNumericSortField(fieldName, SortField.Type.LONG, sub.getBoolean("reverse"), parseNumericSelector(sub, selectorString));
            } else if (fd.valueType == FieldDef.FieldValueType.FLOAT) {
              sf = new SortedNumericSortField(fieldName, SortField.Type.FLOAT, sub.getBoolean("reverse"), parseNumericSelector(sub, selectorString));
            } else if (fd.valueType == FieldDef.FieldValueType.DOUBLE) {
              sf = new SortedNumericSortField(fieldName, SortField.Type.DOUBLE, sub.getBoolean("reverse"), parseNumericSelector(sub, selectorString));
            } else {
              sub.fail("field", "cannot sort by multiValued field \"" + fieldName + "\": type is " + fd.valueType);
              assert false;
              sf = null;
            }
          } else {
            SortField.Type sortType;
            if (fd.valueType == FieldDef.FieldValueType.ATOM) {
              sortType = SortField.Type.STRING;
            } else if (fd.valueType == FieldDef.FieldValueType.LONG || fd.valueType == FieldDef.FieldValueType.DATE_TIME) {
              sortType = SortField.Type.LONG;
            } else if (fd.valueType == FieldDef.FieldValueType.INT) {
              sortType = SortField.Type.INT;
            } else if (fd.valueType == FieldDef.FieldValueType.DOUBLE) {
              sortType = SortField.Type.DOUBLE;
            } else if (fd.valueType == FieldDef.FieldValueType.FLOAT) {
              sortType = SortField.Type.FLOAT;
            } else {
              sub.fail("field", "cannot sort by field \"" + fieldName + "\": type is " + fd.valueType);
              assert false;
              sortType = null;
            }

            sf = new SortField(fieldName,
                               sortType,
                               sub.getBoolean("reverse"));
          }
        }
        
        boolean hasMissingLast = sub.hasParam("missingLast");

        boolean missingLast = sub.getBoolean("missingLast");

        if (fd.valueType == FieldDef.FieldValueType.ATOM) {
          if (missingLast) {
            sf.setMissingValue(SortField.STRING_LAST);
          } else {
            sf.setMissingValue(SortField.STRING_FIRST);
          }
        } else if (fd.valueType == FieldDef.FieldValueType.INT) {
          sf.setMissingValue(missingLast ? Integer.MAX_VALUE : Integer.MIN_VALUE);
        } else if (fd.valueType == FieldDef.FieldValueType.LONG) {
          sf.setMissingValue(missingLast ? Long.MAX_VALUE : Long.MIN_VALUE);
        } else if (fd.valueType == FieldDef.FieldValueType.FLOAT) {
          sf.setMissingValue(missingLast ? Float.POSITIVE_INFINITY : Float.NEGATIVE_INFINITY);
        } else if (fd.valueType == FieldDef.FieldValueType.DOUBLE) {
          sf.setMissingValue(missingLast ? Double.POSITIVE_INFINITY : Double.NEGATIVE_INFINITY);
        } else if (hasMissingLast) {
          sub.fail("missingLast", "field=" + fieldName + ": can only specify missingLast for string and numeric field types: got SortField type " + sf.getType());
        }
      }
      sortFields.add(sf);
    }

    return new Sort(sortFields.toArray(new SortField[sortFields.size()]));
  }

  private static SortedNumericSelector.Type parseNumericSelector(Request r, String selectorString) {
    if (selectorString.equals("min")) {
      return SortedNumericSelector.Type.MIN;
    } else if (selectorString.equals("max")) {
      return SortedNumericSelector.Type.MAX;
    } else {
      r.fail("selector", "must be min or max for multi-valued numeric sort fields");
      // dead code but javac disagrees
      return null;
    }
  }

  /** NOTE: this is a slow method, since it makes many objects just to format one date/time value */
  private static String msecToDateString(FieldDef fd, long value) {
    assert fd.valueType == FieldDef.FieldValueType.DATE_TIME;
    // nocommit use CTL to reuse these?
    Calendar calendar = new GregorianCalendar(TimeZone.getTimeZone("UTC"), Locale.ROOT);
    calendar.setLenient(false);
    SimpleDateFormat dateTimeFormat = new SimpleDateFormat(fd.dateTimeFormat, Locale.ROOT);
    dateTimeFormat.setCalendar(calendar);
    Date date = new Date(value);
    String result = dateTimeFormat.format(date);
    System.out.println("MSEC TO DATE: value=" + value + " s=" + result);
    return result;
  }

  /** NOTE: this is a slow method, since it makes many objects just to parse one date/time value */
  private static long dateStringToMSec(FieldDef fd, String s) throws ParseException {
    assert fd.valueType == FieldDef.FieldValueType.DATE_TIME;
    // nocommit use CTL to reuse these?
    Calendar calendar = new GregorianCalendar(TimeZone.getTimeZone("UTC"), Locale.ROOT);
    calendar.setLenient(false);
    SimpleDateFormat dateTimeFormat = new SimpleDateFormat(fd.dateTimeFormat, Locale.ROOT);
    dateTimeFormat.setCalendar(calendar);
    ParsePosition pos = new ParsePosition(0);    
    Date date = dateTimeFormat.parse(s, pos);
    if (pos.getErrorIndex() != -1) {
      // nocommit more details about why?
      throw new ParseException("could not parse field \"" + fd.name + "\", value \"" + s + "\" as date with format \"" + fd.dateTimeFormat + "\"", pos.getErrorIndex());
    }
    if (pos.getIndex() != s.length()) {
      // nocommit more details about why?          
      throw new ParseException("could not parse field \"" + fd.name + "\", value \"" + s + "\" as date with format \"" + fd.dateTimeFormat + "\"", pos.getIndex());
    }
    return date.getTime();
  }

  private static Object convertType(FieldDef fd, Object o) {
    if (fd.valueType == FieldDef.FieldValueType.BOOLEAN) {
      if (((Integer) o).intValue() == 1) {
        return Boolean.TRUE;
      } else {
        assert ((Integer) o).intValue() == 0;
        return Boolean.FALSE;
      }
    } else if (fd.valueType == FieldDef.FieldValueType.DATE_TIME) {
      return msecToDateString(fd, ((Number) o).longValue());
    //} else if (fd.valueType == FieldDef.FieldValueType.FLOAT && fd.fieldType.docValueType() == DocValuesType.NUMERIC) {
      // nocommit not right...
      //return Float.intBitsToFloat(((Number) o).intValue());
    } else {
      return o;
    }
  }

  @SuppressWarnings("unchecked")
  /** Fills in the returned fields (some hilited) for one hit: */
  private void fillFields(IndexState state, HighlighterConfig highlighter, IndexSearcher s,
                          JSONObject result, ScoreDoc hit, Set<String> fields,
                          Map<String,Object[]> highlights,
                          int hiliteHitIndex, Sort sort,
                          List<String> sortFieldNames,
                          Map<String,FieldDef> dynamicFields) throws IOException {
    //System.out.println("fillFields fields=" + fields);
    if (fields != null) {

      // Add requested stored fields (no highlighting):

      // TODO: make this also retrieve DV fields
      // even if they were not stored ...
      Map<String,Object> doc = highlighter.getDocument(state, s, hit.doc);

      for (String name : fields) {
        FieldDef fd = dynamicFields.get(name);

        // We detect invalid field above:
        assert fd != null;

        // nocommit also allow pulling from doc values?
        if (fd.valueSource != null) {
          List<LeafReaderContext> leaves = s.getIndexReader().leaves();
          LeafReaderContext leaf = leaves.get(ReaderUtil.subIndex(hit.doc, leaves));
          Map<String,Object> context = new HashMap<String,Object>();

          int docID = hit.doc - leaf.docBase;

          assert Float.isNaN(hit.score) == false || fd.valueSource.getSortField(false).needsScores() == false;
          context.put("scorer", new CannedScorer(docID, hit.score));
          FunctionValues segValues = fd.valueSource.getValues(context, leaf);
          result.put(name, segValues.doubleVal(docID));
        } else {
          Object v = doc.get(name);
          if (v != null) {
            // We caught same field name above:
            assert !result.containsKey(name);

            if (fd.multiValued == false) {
              result.put(name, convertType(fd, v));
            } else {
              JSONArray arr = new JSONArray();
              result.put(name, arr);
              if (!(v instanceof List)) {
                arr.add(convertType(fd, v));
              } else {
                for(Object o : (List<Object>) v) {
                  arr.add(convertType(fd, o));
                }
              }
            }
          }
        }
      }
    }

    if (highlights != null) {
      for (Map.Entry<String,Object[]> ent : highlights.entrySet()) {
        Object v = ent.getValue()[hiliteHitIndex];
        if (v != null) {
          result.put(ent.getKey(), v);
        }
      }
    }

    if (hit instanceof FieldDoc) {
      FieldDoc fd = (FieldDoc) hit;
      if (fd.fields != null) {
        JSONObject o4 = new JSONObject();
        result.put("sortFields", o4);
        SortField[] sortFields = sort.getSort();
        for(int i=0;i<sortFields.length;i++) {
          // We must use a separate list because an expr's
          // SortField doesn't know the virtual field name
          // (it returns the expression string from
          // .getField):
          String fieldName = sortFieldNames.get(i);
          if (fd.fields[i] instanceof BytesRef) {
            o4.put(fieldName, ((BytesRef) fd.fields[i]).utf8ToString());
          } else {
            o4.put(fieldName, fd.fields[i]);
          }
        }
      }
    }
  }

  private static BooleanClause.Occur parseBooleanOccur(String occurString) {
    if (occurString.equals("should")) {
      return BooleanClause.Occur.SHOULD;
    } else if (occurString.equals("must")) {
      return BooleanClause.Occur.MUST;
    } else if (occurString.equals("must_not")) {
      return BooleanClause.Occur.MUST_NOT;
    } else if (occurString.equals("filter")) {
      return BooleanClause.Occur.FILTER;
    } else {
      // BUG
      assert false;
      return null;
    }
  }

  static String toJSONKey(Request r) {
    return sort(r.getRawParams()).toString();
  }

  static Object sort(JSONObject o) {
    Map<String,Object> sorted = new TreeMap<String,Object>();
    sorted.putAll(o);
    return sorted;
  }

  /** Records configuration for a block join query. */
  static class BlockJoinQueryChild {
    public Sort sort;
    public List<String> sortFieldNames;
    public int maxChildren;
    public boolean trackScores;
    public boolean trackMaxScore;
  }

  @SuppressWarnings("unchecked")
  private static Query parseQuery(long timestampSec, Request topRequest, IndexState state, Request r, String field,
                                  Map<ToParentBlockJoinQuery,BlockJoinQueryChild> useBlockJoinCollector,
                                  Map<String,FieldDef> dynamicFields) {
    Query q;
    Request.PolyResult pr = r.getPoly("class");
    if (r.hasParam("field")) {
      FieldDef fd = state.getField(r, "field");
      field = fd.name;
      if (fd.fieldType.indexOptions() == IndexOptions.NONE && fd.usePoints == false) {
        r.fail("field", "field \"" + field + "\" was not registered with search=true; cannot search");
      }
    }

    if (pr.name.equals("BooleanQuery")) {
      Request r2 = pr.r;
      BooleanQuery.Builder bq = new BooleanQuery.Builder();
      bq.setMinimumNumberShouldMatch(r2.getInt("minimumNumberShouldMatch"));
      bq.setDisableCoord(r2.getBoolean("disableCoord"));
      for(Object o : r2.getList("subQueries")) {
        Request r3 = (Request) o;
        BooleanClause.Occur occur = parseBooleanOccur(r3.getEnum("occur"));
        Query subQuery = parseQuery(timestampSec, topRequest, state, r3.getStruct("query"), field, useBlockJoinCollector, dynamicFields);
        assert subQuery != null: "got null subQuery from " + r3.getStruct("query");
        bq.add(subQuery, occur);
      }
      q = bq.build();
    } else if (pr.name.equals("CommonTermsQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      CommonTermsQuery ctq = new CommonTermsQuery(parseBooleanOccur(pr.r.getEnum("highFreqOccur")),
                                                  parseBooleanOccur(pr.r.getEnum("lowFreqOccur")),
                                                  pr.r.getFloat("maxTermFrequency"));
      for(Object o : pr.r.getList("terms")) {
        ctq.add(new Term(field, (String) o));
      }
      q = ctq;
    } else if (pr.name.equals("ConstantScoreQuery")) {
      if (pr.r.hasParam("query")) {
        q = new ConstantScoreQuery(parseQuery(timestampSec, topRequest, state, pr.r.getStruct("query"), field, useBlockJoinCollector, dynamicFields));
      } else {
        throw pr.r.bad("query", "ConstantScoreQuery must have a query");
      }
    } else if (pr.name.equals("FuzzyQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      q = new FuzzyQuery(new Term(field, pr.r.getString("term")),
                         pr.r.getInt("maxEdits"),
                         pr.r.getInt("prefixLength"),
                         pr.r.getInt("maxExpansions"),
                         pr.r.getBoolean("transpositions"));
    } else if (pr.name.equals("BooleanFieldQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      FieldDef fd = state.getField(field);
      if (fd.valueType != FieldDef.FieldValueType.BOOLEAN) {
        r.fail("field", "field \"" + field + "\" must be valueType=boolean but got: " + fd.valueType);
      }
      q = new ConstantScoreQuery(new TermQuery(new Term(field, "1")));
    } else if (pr.name.equals("MatchAllDocsQuery")) {
      q = new MatchAllDocsQuery();
    } else if (pr.name.equals("MultiPhraseQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      MultiPhraseQuery.Builder mpq = new MultiPhraseQuery.Builder();
      for(Object o : pr.r.getList("terms")) {
        if (o instanceof String) {
          mpq.add(new Term(field, (String) o));
        } else if (o instanceof List) {
          List<Object> terms = (List<Object>) o;
          Term[] termsArray = new Term[terms.size()];
          for(int i=0;i<termsArray.length;i++) {
            termsArray[i] = new Term(field, (String) terms.get(i));
          }
          mpq.add(termsArray);
        } else {
          Request sr = (Request) o;
          int pos = sr.getInt("position");
          if (sr.isString("term")) {
            mpq.add(new Term[] {new Term(field, sr.getString("term"))}, pos);
          } else  {
            List<Object> terms = (List<Object>) o;
            Term[] termsArray = new Term[terms.size()];
            for(int i=0;i<termsArray.length;i++) {
              termsArray[i] = new Term(field, (String) terms.get(i));
            }
            mpq.add(new Term[] {new Term(field, sr.getString("term"))}, pos);
          }
        }
      }
      mpq.setSlop(pr.r.getInt("slop"));
      q = mpq.build();
    } else if (pr.name.equals("PhraseQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      PhraseQuery.Builder pq = new PhraseQuery.Builder();
      for(Object o : pr.r.getList("terms")) {
        pq.add(new Term(field, (String) o));
      }
      pq.setSlop(pr.r.getInt("slop"));
      q = pq.build();
    } else if (pr.name.equals("PrefixQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      // TODO: change rewrite method?
      q = new PrefixQuery(new Term(field, pr.r.getString("term")));
    } else if (pr.name.equals("RegexpQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      // TODO: flags
      q = new RegexpQuery(new Term(field, pr.r.getString("regexp")));
    } else if (pr.name.equals("TermRangeQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      q = new TermRangeQuery(field,
                             new BytesRef(pr.r.getString("lowerTerm")),
                             new BytesRef(pr.r.getString("upperTerm")),
                             pr.r.getBoolean("includeLower"),
                             pr.r.getBoolean("includeUpper"));
    } else if (pr.name.equals("NumericRangeQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      FieldDef fd = state.getField(field);
      if (fd.usePoints == false) {
        pr.r.fail("field \"" + field + "\" was not registered with numeric type; cannot run NumericRangeQuery");
      }
      Number min;
      if (pr.r.hasParam("min")) {
        Object o = pr.r.getAny("min");
        if (fd.valueType == FieldDef.FieldValueType.DATE_TIME) {
          if (o instanceof String == false) {
            pr.r.fail("min", "expected string date");
          }
          try {
            min = dateStringToMSec(fd, (String) o);
          } catch (ParseException pe) {
            throw pr.r.bad("min", "could not parse string \"" + o + "\" as date with format \"" + fd.dateTimeFormat + "\"", pe);
          }
        } else {
          if (!(o instanceof Number)) {
            pr.r.fail("min", "expected number but got " + o);
          }
          min = (Number) o;
        }
      } else {
        min = null;
      }

      Number max;
      if (pr.r.hasParam("max")) {
        Object o = pr.r.getAny("max");
        if (fd.valueType == FieldDef.FieldValueType.DATE_TIME) {
          if (o instanceof String == false) {
            pr.r.fail("max", "expected string date");
          }
          try {
            max = dateStringToMSec(fd, (String) o);
          } catch (ParseException pe) {
            throw pr.r.bad("max", "could not parse string \"" + o + "\" as date with format \"" + fd.dateTimeFormat + "\"", pe);
          }
        } else {
          if (!(o instanceof Number)) {
            pr.r.fail("max", "expected number but got " + o);
          }
          max = (Number) o;
        }
      } else {
        max = null;
      }

      // nocommit also set queries
      
      if (fd.valueType == FieldDef.FieldValueType.INT) {
        q = IntPoint.newRangeQuery(field, toMinInt(min), toMaxInt(max));
      } else if (fd.valueType == FieldDef.FieldValueType.LONG) {
        q = LongPoint.newRangeQuery(field, toMinLong(min), toMaxLong(max));
      } else if (fd.valueType == FieldDef.FieldValueType.FLOAT) {
        q = FloatPoint.newRangeQuery(field, toMinFloat(min), toMaxFloat(max));
      } else if (fd.valueType == FieldDef.FieldValueType.DOUBLE) {
        q = DoublePoint.newRangeQuery(field, toMinDouble(min), toMaxDouble(max));
      } else if (fd.valueType == FieldDef.FieldValueType.DATE_TIME) {
        q = LongPoint.newRangeQuery(field, toMinLong(min), toMaxLong(max));
      } else {
        // BUG
        throw r.bad("NumericRangeQuery", "unhandled valueType " + fd.valueType);
      }
    } else if (pr.name.equals("TermQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      q = new TermQuery(new Term(field, pr.r.getString("term")));
    } else if (pr.name.equals("LatLonBoxQuery")) {
      q = LatLonPoint.newBoxQuery(field, 
                                  pr.r.getDouble("minLatitude"),
                                  pr.r.getDouble("maxLatitude"),
                                  pr.r.getDouble("minLongitude"),
                                  pr.r.getDouble("maxLongitude"));
    } else if (pr.name.equals("LatLonDistanceQuery")) {
      q = LatLonPoint.newDistanceQuery(field, 
                                       pr.r.getDouble("latitude"),
                                       pr.r.getDouble("longitude"),
                                       pr.r.getDouble("radiusMeters"));
    } else if (pr.name.equals("LatLonPolygonQuery")) {
      Polygon[] polygons;
      if (pr.r.hasParam("geojson")) {
        try {
          polygons = Polygon.fromGeoJSON(pr.r.getString("geojson"));
        } catch (ParseException pe) {
          pr.r.fail("geojson", "failed to parse geojson string: " + pe.getMessage(), pe);
          polygons = null;
        }
      } else {
        List<Polygon> polygonsList = new ArrayList<>();
        for(Object p : pr.r.getList("polygons")) {
          Request r2 = (Request) p;
          List<Object> vertices = r2.getList("vertices");
          double[] polyLats = new double[vertices.size()];
          double[] polyLons = new double[vertices.size()];
          for(int i=0;i<vertices.size();i++) {
            Object o = vertices.get(i);
            if ((o instanceof JSONArray) == false) {
              r2.fail("vertices", "polygon vertices must be array of [latitude, longitude]; got: " + o);
            }
            JSONArray latLon = (JSONArray) o;
            if (latLon.size() != 2) {
              r2.fail("vertices", "polygon vertices must be array of [latitude, longitude]; got: " + o);
            }
            polyLats[i] = ((Number) latLon.get(0)).doubleValue();
            polyLons[i] = ((Number) latLon.get(1)).doubleValue();
          }

          Polygon[] holes;
          if (r2.hasParam("holes")) {
            List<Object> o = r2.getList("holes");
            holes = new Polygon[o.size()];
            for(int i=0;i<o.size();i++) {
              JSONArray o2 = (JSONArray) o.get(i);
              double[] holeLats = new double[o2.size()];
              double[] holeLons = new double[o2.size()];
              for(int j=0;j<o2.size();j++) {
                JSONArray o3 = (JSONArray) o2.get(j);
                holeLats[j] = ((Number) o3.get(0)).doubleValue();
                holeLons[j] = ((Number) o3.get(1)).doubleValue();
              }
              holes[i] = new Polygon(holeLats, holeLons);
            }
          } else {
            holes = new Polygon[0];
          }
          polygonsList.add(new Polygon(polyLats, polyLons, holes));
        }
        polygons = polygonsList.toArray(new Polygon[polygonsList.size()]);
      }
      q = LatLonPoint.newPolygonQuery(field, polygons);

    } else if (pr.name.equals("ToParentBlockJoinQuery")) {
      Query childQuery = parseQuery(timestampSec, topRequest, state, pr.r.getStruct("childQuery"), field, useBlockJoinCollector, dynamicFields);
      BitSetProducer parentsFilter = new QueryBitSetProducer(parseQuery(timestampSec, topRequest, state, pr.r.getStruct("parentsFilter"), field, useBlockJoinCollector, dynamicFields));
      String scoreModeString = pr.r.getEnum("scoreMode");
      ScoreMode scoreMode;
      if (scoreModeString.equals("None")) {
        scoreMode = ScoreMode.None;
      } else if (scoreModeString.equals("Avg")) {
        scoreMode = ScoreMode.Avg;
      } else if (scoreModeString.equals("Max")) {
        scoreMode = ScoreMode.Max;
      } else if (scoreModeString.equals("Total")) {
        scoreMode = ScoreMode.Total;
      } else {
        throw pr.r.bad("scoreMode", "unknown scoreMode " + scoreModeString);
      }
      q = new ToParentBlockJoinQuery(childQuery, parentsFilter, scoreMode);
      if (pr.r.hasParam("childHits")) {
        if (useBlockJoinCollector == null) {
          pr.r.fail("returnChildHits", "cannot return child hits when inside a filter");
        }
        if (!useBlockJoinCollector.isEmpty()) {
          pr.r.fail("returnChildHits", "can only support a single ToParentBlockJoinQuery for now");
        }
        Request childHits = pr.r.getStruct("childHits");
        BlockJoinQueryChild child = new BlockJoinQueryChild();
        if (childHits.hasParam("sort")) {
          child.sortFieldNames = new ArrayList<String>();
          child.sort = parseSort(timestampSec, state, childHits.getList("sort"), child.sortFieldNames, dynamicFields);
        }
        child.maxChildren = childHits.getInt("maxChildren");
        child.trackScores = childHits.getBoolean("trackScores");
        child.trackMaxScore = childHits.getBoolean("trackMaxScore");
        useBlockJoinCollector.put((ToParentBlockJoinQuery) q, child);
      }
    } else if (pr.name.equals("DisjunctionMaxQuery")) {
      Request r2 = pr.r;
      List<Query> subQueries = new ArrayList<>();
      for(Object o : r2.getList("subQueries")) {
        subQueries.add(parseQuery(timestampSec, topRequest, state, (Request) o, field, useBlockJoinCollector, dynamicFields));
      }
      q = new DisjunctionMaxQuery(subQueries, r2.getFloat("tieBreakMultiplier"));
    } else if (pr.name.equals("text")) {
      Request r2 = pr.r;
      String queryText = r2.getString("text");
      if (field == null) {
        r.fail("no field specified");
      }
      QueryBuilder queryParser = createQueryParser(state, topRequest, field);
      try {
        q = parseQuery(queryParser, queryText);
      } catch (Exception e) {
        throw r2.bad("text", "could not parse", e);
      }
      //System.out.println("  got: " +q);
    } else if (pr.name.equals("WildcardQuery")) {
      if (field == null) {
        r.fail("no field specified");
      }
      q = new WildcardQuery(new Term(field, pr.r.getString("term")));
    } else {
      throw r.bad("class", "unhandled query class " + pr.name);
    }
    float boost = r.getFloat("boost");
    if (boost != 1.0f) {
      q = new BoostQuery(q, boost);
    }
    return q;
  }

  private static Query parseQuery(QueryBuilder qp, String text) throws ParseException, org.apache.lucene.queryparser.classic.ParseException {
    if (qp instanceof QueryParserBase) {
      return ((QueryParserBase) qp).parse(text);
    } else {
      return ((SimpleQueryParser) qp).parse(text);
    }
  }

  private static Integer toMinInt(Number x) {
    if (x == null) {
      return Integer.MIN_VALUE;
    } else {
      return x.intValue();
    }
  }

  private static Integer toMaxInt(Number x) {
    if (x == null) {
      return Integer.MAX_VALUE;
    } else {
      return x.intValue();
    }
  }

  private static Long toMinLong(Number x) {
    if (x == null) {
      return Long.MIN_VALUE;
    } else {
      return x.longValue();
    }
  }

  private static Long toMaxLong(Number x) {
    if (x == null) {
      return Long.MAX_VALUE;
    } else {
      return x.longValue();
    }
  }

  private static Float toMinFloat(Number x) {
    if (x == null) {
      return Float.NEGATIVE_INFINITY;
    } else {
      return x.floatValue();
    }
  }

  private static Float toMaxFloat(Number x) {
    if (x == null) {
      return Float.POSITIVE_INFINITY;
    } else {
      return x.floatValue();
    }
  }

  private static Double toMinDouble(Number x) {
    if (x == null) {
      return Double.NEGATIVE_INFINITY;
    } else {
      return x.doubleValue();
    }
  }

  private static Double toMaxDouble(Number x) {
    if (x == null) {
      return Double.POSITIVE_INFINITY;
    } else {
      return x.doubleValue();
    }
  }

  /** If field is non-null it overrides any specified
   *  defaultField. */
  private static QueryBuilder createQueryParser(IndexState state, Request r, String field) {

    if (r.hasParam("queryParser")) {
      r = r.getStruct("queryParser");
      Request.PolyResult pr = r.getPoly("class");
      QueryBuilder qp;

      if (pr.name.equals("classic")) {
        FieldDef fd = state.getField(pr.r, "defaultField");
        qp = new QueryParser(field == null ? fd.name : field, state.searchAnalyzer);
      } else if (pr.name.equals("SimpleQueryParser")) {
        int flags = 0;
        for(Object o : pr.r.getList("operators")) {
          if (o.equals("AND")) {
            flags = flags | SimpleQueryParser.AND_OPERATOR;
          } else if (o.equals("NOT")) {
            flags = flags | SimpleQueryParser.NOT_OPERATOR;
          } else if (o.equals("OR")) {
            flags = flags | SimpleQueryParser.OR_OPERATOR;
          } else if (o.equals("PREFIX")) {
            flags = flags | SimpleQueryParser.PREFIX_OPERATOR;
          } else if (o.equals("PHRASE")) {
            flags = flags | SimpleQueryParser.PHRASE_OPERATOR;
          } else if (o.equals("PRECEDENCE")) {
            flags = flags | SimpleQueryParser.PRECEDENCE_OPERATORS;
          } else if (o.equals("ESCAPE")) {
            flags = flags | SimpleQueryParser.ESCAPE_OPERATOR;
          } else if (o.equals("WHITESPACE")) {
            flags = flags | SimpleQueryParser.WHITESPACE_OPERATOR;
          } else {
            // BUG
            throw new AssertionError();
          }
        }

        Map<String,Float> fieldAndWeights;

        if (field != null) {
          fieldAndWeights = new HashMap<String,Float>();
          fieldAndWeights.put(field, 1.0f);
        } else {
          fieldAndWeights = parseFieldsAndWeights(state, pr.r, "fields");
        }

        qp = new SimpleQueryParser(state.searchAnalyzer,
                                   fieldAndWeights,
                                   flags);
        
      } else if (pr.name.equals("MultiFieldQueryParser")) {
        Map<String,Float> fieldsAndWeights = parseFieldsAndWeights(state, pr.r, "fields");
        //System.out.println("boosts: "+ fieldsAndWeights);
        String[] fields = new String[fieldsAndWeights.size()];
        int upto=0;
        for(String field2 : fieldsAndWeights.keySet()) {
          fields[upto++] = field2;
        }
        qp = new MultiFieldQueryParser(fields, state.searchAnalyzer, fieldsAndWeights);
      } else {
        // BUG
        assert false;
        qp = null;
      }

      String opString = r.getEnum("defaultOperator");
      if (opString.equals("or")) {
        if (qp instanceof SimpleQueryParser) {
          ((SimpleQueryParser) qp).setDefaultOperator(BooleanClause.Occur.SHOULD);
        } else {
          ((QueryParserBase) qp).setDefaultOperator(QueryParser.OR_OPERATOR);
        }
      } else {
        if (qp instanceof SimpleQueryParser) {
          ((SimpleQueryParser) qp).setDefaultOperator(BooleanClause.Occur.MUST);
        } else {
          ((QueryParserBase) qp).setDefaultOperator(QueryParser.AND_OPERATOR);
        }
      }
      qp.setEnablePositionIncrements(r.getBoolean("enablePositionIncrements"));
      if (qp instanceof QueryParserBase) {
        QueryParserBase qpb = (QueryParserBase) qp;
        qpb.setFuzzyMinSim(r.getInt("fuzzyMinSim"));
        qpb.setFuzzyPrefixLength(r.getInt("fuzzyPrefixLength"));
        qpb.setPhraseSlop(r.getInt("phraseSlop"));
        if (r.hasParam("locale")) {
          qpb.setLocale(getLocale(r.getStruct("locale")));
        }
      }
      return qp;
    } else {
      List<String> fields;
      if (field != null) {
        fields = Collections.singletonList(field);
      } else {
        // Default to MultiFieldQueryParser over all indexed fields:
        fields = state.getIndexedAnalyzedFields();
      }
      return new MultiFieldQueryParser(fields.toArray(new String[fields.size()]), state.searchAnalyzer);
    }
  }

  private static Map<String,Float> parseFieldsAndWeights(IndexState state, Request r, String param) {
    Map<String,Float> boosts = new HashMap<String,Float>();
    for(Object o : r.getList(param)) {
      String field2;
      float boost;

      if (o instanceof String) {
        field2 = (String) o;
        boost = 1.0f;
      } else {
        Request r2 = (Request) o;
        field2 = r2.getString("field");
        boost = r2.getFloat("boost");
      }

      FieldDef fd;
      try {
        fd = state.getField(field2);
      } catch (IllegalArgumentException iae) {
        r.fail(param, iae.toString());
        // Dead code but compiler disagrees:
        fd = null;
      }
      if (fd.fieldType.indexOptions() == IndexOptions.NONE) {
        r.fail(param, "field \"" + field2 + "\" was not registered with search=true");
      }
      boosts.put(field2, boost);
    }

    return boosts;
  }


  /** Highlight configuration. */
  static class FieldHighlightConfig {
    /** Number of passages. */
    public int maxPassages = -1;

    // nocommit use enum:
    /** Snippet or whole. */
    public String mode;

    /** True if field is single valued. */
    public boolean multiValued;

    /** {@link BreakIterator} to use. */
    public BreakIterator breakIterator;
  }

  /** Returns a ref. */
  private static SearcherAndTaxonomy openSnapshotReader(ShardState state, IndexState.Gens snapshot, JSONObject diagnostics) throws IOException {
    // TODO: this "reverse-NRT" is ridiculous: we acquire
    // the latest reader, and from that do a reopen to an
    // older snapshot ... this is inefficient if multiple
    // snaphots share older segments that the latest reader
    // does not share ... Lucene needs a reader pool
    // somehow:
    SearcherAndTaxonomy s = state.acquire();
    try {
      // This returns a new reference to us, which
      // is decRef'd in the finally clause after
      // search is done:
      long t0 = System.nanoTime();

      // Returns a ref, which we return to caller:
      IndexReader r = DirectoryReader.openIfChanged((DirectoryReader) s.searcher.getIndexReader(),
                                                    state.snapshots.getIndexCommit(snapshot.indexGen));

      // Ref that we return to caller
      s.taxonomyReader.incRef();

      SearcherAndTaxonomy result = new SearcherAndTaxonomy(new MyIndexSearcher(r), s.taxonomyReader);
      state.slm.record(result.searcher);
      long t1 = System.nanoTime();
      if (diagnostics != null) {
        diagnostics.put("newSnapshotSearcherOpenMS", ((t1-t0)/1000000.0));
      }
      return result;
    } finally {
      state.release(s);
    }
  }

  /** Returns the requested searcher + taxoReader, either
   *  by indexGen, snapshot, version or just the current
   *  (latest) one. */
  public static SearcherAndTaxonomy getSearcherAndTaxonomy(Request request, ShardState state, JSONObject diagnostics) throws InterruptedException, IOException {
    // Figure out which searcher to use:
    //final long searcherVersion;
    //final IndexState.Gens searcherSnapshot;

    SearcherAndTaxonomy s;

    if (request.hasParam("searcher")) {

      // Request wants a specific searcher:
      Request searcher = request.getStruct("searcher");
      if (searcher.hasParam("indexGen")) {

        // Searcher is identified by an indexGen, returned
        // from a previous indexing operation,
        // e.g. addDocument.  Apps use this then they want
        // to ensure a specific indexing change is visible:
        long t0 = System.nanoTime();
        long gen = searcher.getLong("indexGen");
        if (gen > state.writer.getMaxCompletedSequenceNumber()) {
          searcher.fail("indexGen", "requested indexGen (" + gen + ") is beyond the current maximum generation (" + state.writer.getMaxCompletedSequenceNumber() + ")");
        }
        state.waitForGeneration(gen);
        if (diagnostics != null) {
          diagnostics.put("nrtWaitMS", (System.nanoTime() - t0)/1000000);
        }
        s = state.acquire();
        state.slm.record(s.searcher);
      } else {

        long version;
        IndexState.Gens snapshot;

        if (searcher.hasParam("version")) {
          // Searcher is identified by a version, returned by
          // a prior search or by a refresh.  Apps use this when
          // the user does a follow-on search (next page, drill
          // down, etc.), or to ensure changes from a refresh
          // or NRT replication point are reflected:
          version = searcher.getLong("version");
          snapshot = null;
        } else {

          if (searcher.hasParam("snapshot") == false) {
            request.fail("searcher", "must specify exactly one of indexGen, version or snapshot");
          }

          // Searcher is identified by a specific snapshot,
          // previously created by the app using
          // createSnapshot.  This saves a point-in-time
          // view of the index indefinitely, until the app
          // calls deleteSnapshot.  Here, we resolve it to
          // the corresponding version:
          snapshot = new IndexState.Gens(searcher, "snapshot");
          Long v = state.snapshotGenToVersion.get(snapshot.indexGen);
          if (v == null) {
            searcher.fail("snapshot", "unrecognized snapshot \"" + snapshot.id + "\"; please call createSnapshot first");
          }
          version = v.longValue();
        }

        // nocommit need to generify this so we can pull
        // TaxoReader too:
        IndexSearcher priorSearcher = state.slm.acquire(version);
        if (priorSearcher == null) {
          if (snapshot != null) {
            // First time this snapshot is being searched
            // against since this server started, or the call
            // to createSnapshot didn't specify
            // openSearcher=true; now open the reader:
            s = openSnapshotReader(state, snapshot, diagnostics);
          } else {

            SearcherAndTaxonomy current = state.acquire();
            long currentVersion = ((DirectoryReader) current.searcher.getIndexReader()).getVersion();
            if (currentVersion == version) {
              s = current;
            } else if (version > currentVersion) {
              System.out.println("SearchHandler: now await version=" + version + " vs currentVersion=" + currentVersion);

              // TODO: should we have some timeout here?  if user passes bogus future version, we hang forever:
              
              // user is asking for search version beyond what we are currently searching ... wait for us to refresh to it:

              state.release(current);

              // TODO: Use FutureTask<SearcherAndTaxonomy> here?
              
              // nocommit: do this in an async way instead!  this task should be parked somewhere and resumed once refresh runs and exposes
              // the requested version, instead of blocking the current search thread
              Lock lock = new ReentrantLock();
              Condition cond = lock.newCondition();
              RefreshListener listener = new RefreshListener() {
                  @Override
                  public void beforeRefresh() {
                  }

                  @Override
                  public void afterRefresh(boolean didRefresh) throws IOException {
                    SearcherAndTaxonomy current = state.acquire();
                    System.out.println("SearchHandler: refresh completed newVersion=" + ((DirectoryReader) current.searcher.getIndexReader()).getVersion());
                    try {
                      if (((DirectoryReader) current.searcher.getIndexReader()).getVersion() >= version) {
                        lock.lock();
                        try {
                          System.out.println("SearchHandler: now signal new version");
                          cond.signal();
                        } finally {
                          lock.unlock();
                        }
                      }
                    } finally {
                      state.release(current);
                    }
                  };
                };
              state.addRefreshListener(listener);
              lock.lock();
              try {
                current = state.acquire();
                if (((DirectoryReader) current.searcher.getIndexReader()).getVersion() < version) {
                  // still not there yet
                  state.release(current);
                  cond.await();
                  current = state.acquire();
                  assert ((DirectoryReader) current.searcher.getIndexReader()).getVersion() >= version;
                }
                s = current;
              } finally {
                lock.unlock();
                state.removeRefreshListener(listener);
              }
            } else {
              // Specific searcher version was requested,
              // but this searcher has timed out.  App
              // should present a "your session expired" to
              // user:
              request.fail("searcher", "This searcher has expired version=" + version + " vs currentVersion=" + currentVersion);
              // Dead code but compiler disagrees:
              s = null;
            }
          }
        } else {
          // nocommit messy ... we pull an old searcher
          // but the latest taxoReader ... necessary
          // because SLM can't take taxo reader yet:
          SearcherAndTaxonomy s2 = state.acquire();
          s = new SearcherAndTaxonomy(priorSearcher, s2.taxonomyReader);
          s2.searcher.getIndexReader().decRef();
        }
      }
    } else {
      // Request didn't specify any specific searcher;
      // just use the current (latest) searcher:
      s = state.acquire();
      state.slm.record(s.searcher);
    }

    return s;
  }

  /** Fold in any drillDowns requests into the query. */
  private static DrillDownQuery addDrillDowns(long timestampSec, IndexState state, Request r, Query q, Map<String,FieldDef> dynamicFields) {
    // Always create a DrillDownQuery; if there
    // are no drill-downs it will just rewrite to the
    // original query:
    DrillDownQuery ddq = new DrillDownQuery(state.facetsConfig, q);

    if (r.hasParam("drillDowns")) {
      List<Object> drillDownList = r.getList("drillDowns");
      if (!drillDownList.isEmpty()) {
        for(Object o : drillDownList) {
          Request fr = (Request) o;
          String f = fr.getString("field");
          FieldDef fd = dynamicFields.get(f);
          if (fd == null) {
            fr.fail("field", "field \"" + f + "\" was not registered and was not specified as a dynamicField");
            // Dead code but compiler disagrees:
            fd = null;
          }

          if (fr.hasParam("query")) {
            // Drill down by query:
            ddq.add(fd.name, parseQuery(timestampSec, null, state, r.getStruct("query"), fd.name, null, dynamicFields));
          } else if (fr.hasParam("numericRange")) {
            Request rr = fr.getStruct("numericRange");
            Range range;
            if (fd.valueType == FieldDef.FieldValueType.INT || fd.valueType == FieldDef.FieldValueType.LONG) {
              range = new LongRange(rr.getString("label"),
                                    rr.getLong("min"),
                                    rr.getBoolean("minInclusive"),
                                    rr.getLong("max"),
                                    rr.getBoolean("maxInclusive"));

            } else if (fd.valueType == FieldDef.FieldValueType.FLOAT || fd.valueType == FieldDef.FieldValueType.DOUBLE || fd.valueType == FieldDef.FieldValueType.VIRTUAL) {
              range = new DoubleRange(rr.getString("label"),
                                      rr.getDouble("min"),
                                      rr.getBoolean("minInclusive"),
                                      rr.getDouble("max"),
                                      rr.getBoolean("maxInclusive"));
            } else {
              fr.fail("numericRange", "field \"" + fd.name + "\" is not numeric");

              // Dead code but compiler disagrees:
              range = null;
            }

            ValueSource valueSource;
            if (fd.valueSource == null) {
              if (fd.valueType == FieldDef.FieldValueType.INT) {
                valueSource = new IntFieldSource(fd.name);
              } else if (fd.valueType == FieldDef.FieldValueType.LONG) {
                valueSource = new LongFieldSource(fd.name);
              } else if (fd.valueType == FieldDef.FieldValueType.DOUBLE) {
                valueSource = new DoubleFieldSource(fd.name);
              } else if (fd.valueType == FieldDef.FieldValueType.FLOAT) {
                valueSource = new FloatFieldSource(fd.name);
              } else {
                fr.fail("numericRange", "currently only supported for virtual and numeric fields");

                // Dead code but compiler disagrees:
                valueSource = null;
              }
            } else {
              valueSource = fd.valueSource;
            }
            ddq.add(fd.name, range.getQuery(null, valueSource));
          } else {
            String[] path;
            if (fr.isString("value")) {
              path = new String[] {fr.getString("value")};
            } else {
              List<Object> values = fr.getList("value");
              path = new String[values.size()];
              for(int i=0;i<path.length;i++) {
                path[i] = (String) values.get(i);
              }
            }

            ddq.add(fd.name, path);
          }
        }
      }
    }

    return ddq;
  }

  private static Query extractQuery(IndexState state, Request r, long timestampSec,
                                    Map<ToParentBlockJoinQuery,BlockJoinQueryChild> useBlockJoinCollector,
                                    Map<String,FieldDef> dynamicFields) throws Exception {
    Query q;
    if (r.hasParam("queryText")) {
      QueryBuilder queryParser = createQueryParser(state, r, null);

      String queryText = r.getString("queryText");

      if (queryText != null) {
        try {
          q = parseQuery(queryParser, queryText);
        } catch (Exception e) {
          r.fail("queryText", "could not parse", e);
          // dead code but compiler disagrees:
          return null;
        }
      } else {
        q = null;
      }
    } else if (r.hasParam("query")) {
      q = parseQuery(timestampSec, r, state, r.getStruct("query"), null, useBlockJoinCollector, dynamicFields);
    } else {
      q = new MatchAllDocsQuery();
    }

    return q;
  }

  private static JSONObject buildFacetResultJSON(FacetResult result) {
    JSONObject o = new JSONObject();
    JSONArray counts = new JSONArray();
    o.put("counts", counts);
    o.put("childCount", result.childCount);
    JSONArray pair = new JSONArray();
    counts.add(pair);
    pair.add("top");
    pair.add(result.value);
    for(LabelAndValue labelValue : result.labelValues) {
      pair = new JSONArray();
      counts.add(pair);
      pair.add(labelValue.label);
      pair.add(labelValue.value);
    }

    return o;
  }

  static void fillFacetResults(Request r, SearcherAndTaxonomy s, FacetsCollector drillDowns,
                               FacetsCollector[] drillSideways, String[] drillSidewaysDims,
                               ShardState shardState, JSONArray facetResults,
                               Map<String,FieldDef> dynamicFields) throws IOException {

    IndexState indexState = shardState.indexState;
    
    Map<String,FacetsCollector> dsDimMap = new HashMap<String,FacetsCollector>();
    if (drillSidewaysDims != null) {
      for(int i=0;i<drillSidewaysDims.length;i++) {
        dsDimMap.put(drillSidewaysDims[i], drillSideways[i]);
      }
    }

    // Holds already computed Facets, since more
    // than one dimension can share a single
    // index field name.  We need one map for "normal" and
    // another for SSDV facets because an app can index both
    // into the same Lucene field (this is the default):
    Map<String,Facets> indexFieldNameToFacets = new HashMap<String,Facets>();
    Map<String,Facets> indexFieldNameToSSDVFacets = new HashMap<String,Facets>();

    for(Object o2 : r.getList("facets")) {
      Request r2 = (Request) o2;
      String fieldName = r2.getString("dim");
      FieldDef fd = dynamicFields.get(fieldName);
      if (fd == null) {
        r2.fail("dim", "field \"" + fieldName + "\" was not registered and was not specified as a dynamicField");
        // Dead code but compiler disagrees:
        fd = null;
      }

      FacetResult facetResult;

      if (r2.hasParam("numericRanges")) {
        if (fd.faceted != null && !fd.faceted.equals("numericRange")) {
          r2.fail("numericRanges", "field \"" + fd.name + "\" was not registered with facet=numericRange");
        }
        if (fd.valueType == FieldDef.FieldValueType.INT || fd.valueType == FieldDef.FieldValueType.LONG) {
          List<Object> rangeList = r2.getList("numericRanges");
          LongRange[] ranges = new LongRange[rangeList.size()];
          for(int i=0;i<ranges.length;i++) {
            Request r3 = (Request) rangeList.get(i);
            ranges[i] = new LongRange(r3.getString("label"),
                                      r3.getLong("min"),
                                      r3.getBoolean("minInclusive"),
                                      r3.getLong("max"),
                                      r3.getBoolean("maxInclusive"));
          }

          FacetsCollector c = dsDimMap.get(fd.name);
          if (c == null) {
            c = drillDowns;
          }

          Facets facets = new LongRangeFacetCounts(fd.name,
                                                   c,
                                                   ranges);
          facetResult = facets.getTopChildren(0, fd.name);
        } else if (fd.valueType == FieldDef.FieldValueType.FLOAT || fd.valueType == FieldDef.FieldValueType.DOUBLE || fd.valueType == FieldDef.FieldValueType.VIRTUAL) {
          List<Object> rangeList = r2.getList("numericRanges");
          DoubleRange[] ranges = new DoubleRange[rangeList.size()];
          for(int i=0;i<ranges.length;i++) {
            Request r3 = (Request) rangeList.get(i);
            ranges[i] = new DoubleRange(r3.getString("label"),
                                        r3.getDouble("min"),
                                        r3.getBoolean("minInclusive"),
                                        r3.getDouble("max"),
                                        r3.getBoolean("maxInclusive"));
          }

          FacetsCollector c = dsDimMap.get(fd.name);
          if (c == null) {
            c = drillDowns;
          }

          Facets facets;
          if (fd.valueType == FieldDef.FieldValueType.VIRTUAL) {
            facets = new DoubleRangeFacetCounts(fd.name,
                                                fd.valueSource,
                                                c,
                                                ranges);
          } else {
            facets = new DoubleRangeFacetCounts(fd.name,
                                                c,
                                                ranges);
          }
          facetResult = facets.getTopChildren(0, fd.name);
        } else {
          // nocommit float/double too
          throw r2.bad("numericRanges", "field type must be numeric; got: " + fd.valueType);
        }
      } else if (fd.faceted.equals("sortedSetDocValues")) {
        FacetsCollector c = dsDimMap.get(fd.name);
        if (c == null) {
          c = drillDowns;
        }
        SortedSetDocValuesFacetCounts facets = new SortedSetDocValuesFacetCounts(shardState.getSSDVState(s, r, fd), c);
        facetResult = facets.getTopChildren(r2.getInt("topN"), fd.name, new String[0]);
      } else {

        // Taxonomy or SSDV facets
        if (fd.faceted.equals("no")) {
          r2.fail("path", "field \"" + fd.name + "\" was not registered with facet enabled");
        } else if (fd.faceted.equals("numericRange")) {
          r2.fail("path", "field \"" + fd.name + "\" was registered with facet=numericRange; must pass numericRanges in the request");
        }

        String[] path;
        if (r2.hasParam("path")) {
          if (r2.isString("path")) {
            path = new String[] {r2.getString("path")};
          } else {
            List<Object> l = r2.getList("path");
            if (l.isEmpty()) {
              r2.fail("path", "path must contain at least one part");
            }
            path = new String[l.size()];
            for(int idx=0;idx<path.length;idx++) {
              path[idx] = l.get(idx).toString();
            }
          }
        } else {
          path = new String[0];
        }

        Facets facets;

        FacetsCollector c = dsDimMap.get(fd.name);

        boolean useCachedOrds;

        if (r2.hasParam("useOrdsCache")) {
          if (fd.faceted.equals("sortedSetDocValues")) {
            r2.fail("useOrdsCache", "field: \"" + fd.name + "\": cannot useOrdsCache with facet=sortedSetDocValues");
          }
          useCachedOrds = r2.getBoolean("useOrdsCache");
        } else {
          useCachedOrds = false;
        }

        if (c != null) {
          // This dimension was used in
          // drill-down; compute its facet counts from the
          // drill-sideways collector:
          String indexFieldName = indexState.facetsConfig.getDimConfig(fd.name).indexFieldName;
          if (useCachedOrds) {
            facets = new TaxonomyFacetCounts(shardState.getOrdsCache(indexFieldName),
                                             s.taxonomyReader,
                                             indexState.facetsConfig, 
                                             c);
          } else if (fd.faceted.equals("sortedSetDocValues")) {
            facets = new SortedSetDocValuesFacetCounts(shardState.getSSDVState(s, r, fd), c);
          } else {
            facets = new FastTaxonomyFacetCounts(indexFieldName,
                                                 s.taxonomyReader,
                                                 indexState.facetsConfig, 
                                                 c);
          }
        } else {

          // nocommit test both normal & ssdv facets in same index

          // See if we already computed facet
          // counts for this indexFieldName:
          String indexFieldName = indexState.facetsConfig.getDimConfig(fd.name).indexFieldName;
          Map<String,Facets> facetsMap;
          if (fd.faceted.equals("sortedSetDocValues")) {
            facetsMap = indexFieldNameToSSDVFacets;
          } else {
            facetsMap = indexFieldNameToFacets;
          }
          facets = facetsMap.get(indexFieldName);
          if (facets == null) {
            if (useCachedOrds) {
              facets = new TaxonomyFacetCounts(shardState.getOrdsCache(indexFieldName),
                                               s.taxonomyReader,
                                               indexState.facetsConfig, 
                                               c);
            } else if (fd.faceted.equals("sortedSetDocValues")) {
              facets = new SortedSetDocValuesFacetCounts(shardState.getSSDVState(s, r, fd),
                                                         c);
            } else {
              facets = new FastTaxonomyFacetCounts(indexFieldName,
                                                   s.taxonomyReader,
                                                   indexState.facetsConfig,
                                                   drillDowns);
            }
            facetsMap.put(indexFieldName, facets);
          }
        }
        if (r2.hasParam("topN")) {
          facetResult = facets.getTopChildren(r2.getInt("topN"), fd.name, path);
        } else if (r2.hasParam("labels")) {
          List<LabelAndValue> results = new ArrayList<LabelAndValue>();
          for(Object o : r2.getList("labels")) {
            String label = (String) o;
            results.add(new LabelAndValue(label, 
                                          facets.getSpecificValue(fd.name, label)));
          }
          facetResult = new FacetResult(fd.name, path, -1, results.toArray(new LabelAndValue[results.size()]), -1);
        } else {
          r2.fail("each facet request must have either topN or labels");

          // Dead code but compiler disagrees:
          facetResult = null;
        }
      }

      if (facetResult == null) {
        facetResults.add(null);
      } else {
        facetResults.add(buildFacetResultJSON(facetResult));
      }
    }
  }

  /** Parses any virtualFields, which define dynamic
   *  (expression) fields for this one request. */
  private static Map<String,FieldDef> getDynamicFields(ShardState shardState, Request r) {
    IndexState indexState = shardState.indexState;
    Map<String,FieldDef> dynamicFields;
    if (r.hasParam("virtualFields")) {
      dynamicFields = new HashMap<String,FieldDef>();
      dynamicFields.putAll(indexState.getAllFields());
      Bindings bindings = new FieldDefBindings(dynamicFields);
      for(Object o : r.getList("virtualFields")) {
        Request oneField = (Request) o;
        String name = oneField.getString("name");
        String exprString = oneField.getString("expression");

        Expression expr;
        try {
          expr = JavascriptCompiler.compile(exprString);
        } catch (ParseException pe) {
          // Static error (e.g. bad JavaScript syntax):
          oneField.fail("expressoin", "could not parse expression: " + pe, pe);

          // Dead code but compiler disagrees:
          expr = null;
        } catch (IllegalArgumentException iae) {
          // Static error (e.g. bad JavaScript syntax):
          oneField.fail("expression", "could not parse expression: " + iae, iae);

          // Dead code but compiler disagrees:
          expr = null;
        }

        ValueSource values;
        try {
          values = expr.getValueSource(bindings);
        } catch (RuntimeException re) {
          // Dynamic error (e.g. referred to a field that
          // doesn't exist):
          oneField.fail("expression", "could not evaluate expression: " + re, re);

          // Dead code but compiler disagrees:
          values = null;
        }

        FieldDef fd = new FieldDef(name, null, FieldDef.FieldValueType.VIRTUAL, null, null, null, true, false, null, null, null, false, values, null);

        if (dynamicFields.put(name, fd) != null) {
          oneField.fail("name", "registered field or dynamic field \"" + name + "\" already exists");
        }
      }
    } else {
      dynamicFields = indexState.getAllFields();
    }

    return dynamicFields;
  }

  @SuppressWarnings("unchecked")
  @Override
  public FinishRequest handle(final IndexState indexState, final Request r, Map<String,List<String>> params) throws Exception {

    ShardState shardState = indexState.getShard(0);

    indexState.verifyStarted(r);

    final Map<ToParentBlockJoinQuery,BlockJoinQueryChild> useBlockJoinCollector = new HashMap<ToParentBlockJoinQuery,BlockJoinQueryChild>();

    // App should re-use a previous timestampSec if user does a
    // follow-on action, so that things relying on timestampSec
    // (e.g. dynamic range facet counts, recency blended
    // sorting) don't change as the user drills down / next
    // pages / etc.
    final long timestampSec;
    if (r.hasParam("timeStamp")) {
      timestampSec = r.getLong("timeStamp");
    } else {
      timestampSec = System.currentTimeMillis()/1000;
    }

    JSONObject diagnostics = new JSONObject();

    final Map<String,FieldDef> dynamicFields = getDynamicFields(shardState, r);

    Query q = extractQuery(indexState, r, timestampSec, useBlockJoinCollector, dynamicFields);

    final Set<String> fields;
    final Map<String,FieldHighlightConfig> highlightFields;

    boolean forceDocScores = false;

    if (r.hasParam("retrieveFields")) {
      fields = new HashSet<String>();
      highlightFields = new HashMap<String,FieldHighlightConfig>();
      Set<String> fieldSeen = new HashSet<String>();
      for(Object o : r.getList("retrieveFields")) {
        String field;
        String highlight = "no";
        FieldHighlightConfig perField = null;
        if (o instanceof String) {
          field = (String) o;
          fields.add(field);
        } else if (o instanceof Request) {
          Request f = (Request) o;
          field = f.getString("field");
          if (f.hasParam("highlight")) {
            highlight = f.getEnum("highlight");
            if (!highlight.equals("no")) {
              perField = new FieldHighlightConfig();
              highlightFields.put(field, perField);
              perField.mode = highlight;
              if (f.hasParam("maxPassages")) {
                perField.maxPassages = f.getInt("maxPassages");
              }
              if (f.hasParam("breakIterator")) {
                perField.breakIterator = parseBreakIterator(f.getStruct("breakIterator"));
              }
            } else {
              fields.add(field);
            }
          } else {
            fields.add(field);
          }
        } else {
          r.fail("retrieveFields", "unrecognized object " + o);
          field = null;
        }
        if (fieldSeen.contains(field)) {
          r.fail("retrieveFields", "field \"" + field + "\" cannot be retrieved more than once");
        }       
        fieldSeen.add(field);

        FieldDef fd = dynamicFields.get(field);
        if (fd == null) {
          r.fail("retrieveFields", "field \"" + field + "\" was not registered and was not specified as a dynamicField");
          // Dead code but compiler disagrees:
          fd = null;
        }

        // If any of the fields being retrieved require
        // score, than force returned FieldDoc.score to be
        // computed:
        if (fd.valueSource != null && fd.valueSource.getSortField(false).needsScores()) {
          forceDocScores = true;
        }

        if (perField != null) {
          perField.multiValued = fd.multiValued;
          if (fd.multiValued == false && perField.mode.equals("joinedSnippets")) {
            ((Request) o).fail("highlight", "joinedSnippets can only be used with multi-valued fields");
          }
        }
        if (!highlight.equals("no") && !fd.highlighted) {
          r.fail("retrieveFields", "field \"" + field + "\" was not indexed with highlight=true");
        }

        // nocommit allow pulling from DV?  need separate
        // dvFields?

        if (fd.fieldType == null) {
          if (fd.valueSource == null) {
            r.fail("retrieveFields", "field \"" + field + "\" was not registered with store=true");
          }
        } else if (!fd.fieldType.stored()) {
          r.fail("retrieveFields", "field \"" + field + "\" was not registered with store=true");
        }
      }

    } else {
      fields = null;
      highlightFields = null;
    }

    HighlighterConfig highlighter = getHighlighter(indexState, r, highlightFields);

    diagnostics.put("parsedQuery", q.toString());

    TopDocs hits;
    TopGroups<BytesRef> groups;
    TopGroups<Integer> joinGroups;
    int totalGroupCount = -1;

    final String resultString;

    // Pull the searcher we will use
    final SearcherAndTaxonomy s = getSearcherAndTaxonomy(r, shardState, diagnostics);

    final Query queryOrig = q;

    // matching finally clause releases this searcher:
    try {

      // nocommit can we ... not do this?  it's awkward that
      // we have to ... but, the 2-pass (query time
      // join/grouping) is slower for MTQs if we don't
      // ... and the whole out-of-order collector or not
      // ...

      q = s.searcher.rewrite(q);
      //System.out.println("after rewrite: " + q);
      diagnostics.put("rewrittenQuery", q.toString());

      // nocommit add test with drill down on OR of fields:

      // TODO: re-enable this?  else we never get
      // in-order collectors
      //Weight w = s.createNormalizedWeight(q2);

      DrillDownQuery ddq = addDrillDowns(timestampSec, indexState, r, q, dynamicFields);

      diagnostics.put("drillDownQuery", q.toString());

      Collector c;
      TermFirstPassGroupingCollector groupCollector = null;
      TermAllGroupsCollector allGroupsCollector = null;

      FieldDef groupField = null;
      Request grouping = null;
      Sort groupSort = null;
      Sort sort;
      Request sortRequest;
      List<String> sortFieldNames;
      if (r.hasParam("sort")) {
        sortRequest = r.getStruct("sort");
        sortFieldNames = new ArrayList<String>();
        sort = parseSort(timestampSec, indexState, sortRequest.getList("fields"), sortFieldNames, dynamicFields);
      } else {
        sortRequest = null;
        sort = null;
        sortFieldNames = null;
      }

      int topHits = r.getInt("topHits");

      if (r.hasParam("grouping")) {
        if (r.hasParam("searchAfter")) {
          r.fail("searchAfter", "cannot use searchAfter with grouping");
        }
        if (!useBlockJoinCollector.isEmpty()) {
          r.fail("grouping", "cannot do both grouping and ToParentBlockJoinQuery with returnChildHits=true");
        }
        grouping = r.getStruct("grouping");
        groupField = indexState.getField(grouping, "field");

        // Make sure the group-by field was indexed with group=true:
        if (groupField.fieldType.docValuesType() == null) {
          grouping.fail("field", "field \"" + groupField.name + "\" was not registered with group=true");
        }

        if (grouping.hasParam("sort")) {
          groupSort = parseSort(timestampSec, indexState, grouping.getList("sort"), null, dynamicFields);
        } else {
          groupSort = Sort.RELEVANCE;
        }

        groupCollector = new TermFirstPassGroupingCollector(groupField.name, groupSort, grouping.getInt("groupsPerPage"));
        if (grouping.getBoolean("doTotalGroupCount")) {
          allGroupsCollector = new TermAllGroupsCollector(groupField.name);
          c = MultiCollector.wrap(groupCollector, allGroupsCollector);
        } else {
          c = groupCollector;
        }
      } else if (useBlockJoinCollector.isEmpty() == false) {
        if (r.hasParam("searchAfter")) {
          r.fail("searchAfter", "cannot use searchAfter with ToParentBlockJoinQuery with returnChildHits=true");
        }
        Iterator<Map.Entry<ToParentBlockJoinQuery,BlockJoinQueryChild>> it = useBlockJoinCollector.entrySet().iterator();
        Map.Entry<ToParentBlockJoinQuery,BlockJoinQueryChild> ent = it.next();
        BlockJoinQueryChild child = ent.getValue();
        c = new ToParentBlockJoinCollector(sort == null ? Sort.RELEVANCE : sort,
                                           topHits, child.trackScores, child.trackMaxScore);
      } else if (sort == null) {
        ScoreDoc searchAfter;
        if (r.hasParam("searchAfter")) {
          Request sa = r.getStruct("searchAfter");
          searchAfter = new ScoreDoc(sa.getInt("lastDoc"),
                                     sa.getFloat("lastScore"));
        } else {
          searchAfter = null;
        }
        c = TopScoreDocCollector.create(topHits, searchAfter);
      } else {

        // If any of the sort fields require score, than
        // ask for FieldDoc.score in the returned hits:
        for(SortField sortField : sort.getSort()) {
          forceDocScores |= sortField.needsScores();
        }

        // Sort by fields:
        FieldDoc searchAfter;
        if (r.hasParam("searchAfter")) {
          Request sa = r.getStruct("searchAfter");
          List<Object> lastFieldValues = sa.getList("lastFieldValues");
          searchAfter = new FieldDoc(sa.getInt("lastDoc"),
                                     0.0f,
                                     lastFieldValues.toArray(new Object[lastFieldValues.size()]));
        } else {
          searchAfter = null;
        }

        c = TopFieldCollector.create(sort, topHits, searchAfter, true,
                                     sortRequest.getBoolean("doDocScores") || forceDocScores,
                                     sortRequest.getBoolean("doMaxScore"));
      }

      long timeoutMS;
      Collector c2;
      if (r.hasParam("timeoutSec")) {
        timeoutMS = (long) (r.getFloat("timeoutSec") * 1000);
        if (timeoutMS <= 0) {
          r.fail("timeoutSec", "must be > 0 msec");
        }
        c2 = new TimeLimitingCollector(c, TimeLimitingCollector.getGlobalCounter(), timeoutMS);
      } else {
        c2 = c;
        timeoutMS = -1;
      }

      // nocommit can we do better?  sometimes downgrade
      // to DDQ not DS?

      long searchStartTime = System.nanoTime();

      // Holds the search result JSON object:
      JSONObject result = new JSONObject();
      result.put("diagnostics", diagnostics);

      if (r.hasParam("facets")) {

        final JSONArray facetResults = new JSONArray();
        result.put("facets", facetResults);

        // Always use drill sideways; it downgrades to a
        // "normal" query if there were no drilldowns:
        //System.out.println("SEARCHER: " + s.searcher.getClass());
        DrillSideways ds = new DrillSideways(s.searcher, indexState.facetsConfig, s.taxonomyReader) {

            private FacetsCollector getCollector(String dim, Map<String,FacetsCollector> dsMap, FacetsCollector drillDowns) {
              FacetsCollector c = dsMap.get(dim);
              if (c == null) {
                c = drillDowns;
              }

              return c;
            }

            @Override
            protected Facets buildFacetsResult(FacetsCollector drillDowns, FacetsCollector[] drillSideways, String[] drillSidewaysDims) throws IOException {
              fillFacetResults(r, s, drillDowns, drillSideways, drillSidewaysDims, shardState, facetResults, dynamicFields);
              return null;
            }

            @Override
            protected boolean scoreSubDocsAtOnce() {
              // If we are using
              // ToParentBlockJoinCollector then all
              // sub-docs must be scored at once:
              return !useBlockJoinCollector.isEmpty();
            }
          };

        // Fills in facetResults as a side-effect:
        //System.out.println("DDQ: " + ddq);
        try {
          ds.search(ddq, c2);
        } catch (TimeLimitingCollector.TimeExceededException tee) {
          result.put("hitTimeout", true);
        }

      } else {
        try {
          s.searcher.search(ddq, c2);
        } catch (TimeLimitingCollector.TimeExceededException tee) {
          result.put("hitTimeout", true);
        }
      }

      diagnostics.put("firstPassSearchMS", ((System.nanoTime()-searchStartTime)/1000000.0));

      int startHit = r.getInt("startHit");

      if (grouping != null) {
        if (sort == null) {
          sort = Sort.RELEVANCE;
        }
        Collection<SearchGroup<BytesRef>> topGroups = groupCollector.getTopGroups(grouping.getInt("groupStart"), true);
        if (topGroups != null) {
          TermSecondPassGroupingCollector c3 = new TermSecondPassGroupingCollector(groupField.name,
                                                                                   topGroups,
                                                                                   groupSort,
                                                                                   sort,
                                                                                   grouping.getInt("hitsPerGroup"),
                                                                                   grouping.getBoolean("doDocScores"),
                                                                                   grouping.getBoolean("doMaxScore"),
                                                                                   true);
          long t0 = System.nanoTime();

          c = c3;
          if (timeoutMS > 0) {
            c = new TimeLimitingCollector(c, TimeLimitingCollector.getGlobalCounter(), timeoutMS);
          }

          try {
            s.searcher.search(ddq, c);
          } catch (TimeLimitingCollector.TimeExceededException tee) {
            result.put("hitTimeout", true);
          }
          diagnostics.put("secondPassSearchMS", ((System.nanoTime()-t0)/1000000));

          groups = c3.getTopGroups(0);
          hits = null;
          joinGroups = null;
          if (allGroupsCollector != null) {
            totalGroupCount = allGroupsCollector.getGroups().size();
          }
        } else {
          hits = null;
          groups = null;
          joinGroups = null;
          totalGroupCount = 0;
        }
      } else if (!useBlockJoinCollector.isEmpty()) {
        assert useBlockJoinCollector.size() == 1;
        Iterator<Map.Entry<ToParentBlockJoinQuery,BlockJoinQueryChild>> it = useBlockJoinCollector.entrySet().iterator();
        Map.Entry<ToParentBlockJoinQuery,BlockJoinQueryChild> ent = it.next();
        BlockJoinQueryChild child = ent.getValue();

        joinGroups = ((ToParentBlockJoinCollector) c).getTopGroups(ent.getKey(),
                                                                   child.sort, startHit,
                                                                   child.maxChildren, 0, true);
        groups = null;
        hits = null;
      } else {
        groups = null;
        joinGroups = null;
        hits = ((TopDocsCollector) c).topDocs();

        if (startHit != 0) {
          // Slice:
          int count = Math.max(0, hits.scoreDocs.length - startHit);
          ScoreDoc[] newScoreDocs = new ScoreDoc[count];
          if (count > 0) {
            System.arraycopy(hits.scoreDocs, startHit, newScoreDocs, 0, count);
          }
          hits = new TopDocs(hits.totalHits,
                             newScoreDocs,
                             hits.getMaxScore());
        }
      }

      int[] highlightDocIDs = null;
      if (groupField != null) {
        if (groups != null) {

          // These groups are already sliced according
          // to groupStart:
          int count = 0;
          for(GroupDocs<BytesRef> group : groups.groups) {
            count += group.scoreDocs.length;
          }
          if (count > 0) {
            highlightDocIDs = new int[count];

            int upto = 0;
            for(GroupDocs<BytesRef> group : groups.groups) {
              for(ScoreDoc scoreDoc : group.scoreDocs) {
                highlightDocIDs[upto++] = scoreDoc.doc;
              }
            }
          }
        }
      } else if (!useBlockJoinCollector.isEmpty()) {
        if (joinGroups != null) {

          int count = 0;
          for(GroupDocs<Integer> group : joinGroups.groups) {
            // for the parent docID:
            count++;
            // for all child docs:
            count += group.scoreDocs.length;
          }

          if (count > 0) {
            highlightDocIDs = new int[count];

            int upto = 0;
            for(GroupDocs<Integer> group : joinGroups.groups) {
              highlightDocIDs[upto++] = group.groupValue.intValue();
              for(ScoreDoc scoreDoc : group.scoreDocs) {
                highlightDocIDs[upto++] = scoreDoc.doc;
              }
            }
          }
        }
      } else {
        highlightDocIDs = new int[hits.scoreDocs.length];
        for(int i=0;i<hits.scoreDocs.length;i++) {
          highlightDocIDs[i] = hits.scoreDocs[i].doc;
        }
      }

      Map<String,Object[]> highlights = null;

      long t0 = System.nanoTime();
      if (highlightDocIDs != null && highlightFields != null && !highlightFields.isEmpty()) {
        int[] maxPassages = new int[highlightFields.size()];
        Arrays.fill(maxPassages, highlighter.maxPassages);
        String[] fieldsArray = new String[highlightFields.size()];
        int upto = 0;
        for(Map.Entry<String,FieldHighlightConfig> ent : highlightFields.entrySet()) {
          fieldsArray[upto] = ent.getKey();
          FieldHighlightConfig perField = ent.getValue();
          if (perField.maxPassages != -1) {
            maxPassages[upto] = perField.maxPassages;
          }
          upto++;
        }

        highlights = highlighter.highlighter.highlightToObjects(fieldsArray,
                                                                queryOrig,
                                                                s.searcher,
                                                                highlightDocIDs,
                                                                maxPassages);
      }
      diagnostics.put("highlightTimeMS", (System.nanoTime() - t0)/1000000.);

      t0 = System.nanoTime();
        
      if (groupField != null) {
        if (groups == null) {
          result.put("totalHits", 0);
          result.put("totalGroupCount", 0);
        } else {
          result.put("totalHits", groups.totalHitCount);
          result.put("totalGroupedHits", groups.totalGroupedHitCount);
          if (groups.totalGroupCount != null) {
            result.put("totalGroupCount", groups.totalGroupCount);
          } else if (totalGroupCount != -1) {
            result.put("totalGroupCount", totalGroupCount);
          }

          // nocommit why am I getting a maxScore back when
          // I didn't ask for it ... oh because I'm sorting
          // by relevance ... hmm ... must test field sort
          // case

          if (!Float.isNaN(groups.maxScore)) {
            result.put("maxScore", groups.maxScore);
          }

          JSONArray o2 = new JSONArray();
          result.put("groups", o2);
          int hitIndex = 0;
          for(GroupDocs<BytesRef> group : groups.groups) {
            JSONObject o3 = new JSONObject();
            o2.add(o3);
            Object v = group.groupValue;
            if (v instanceof BytesRef) {
              o3.put("groupValue", ((BytesRef) v).utf8ToString());
            } else {
              o3.put("groupValue", v);
            }
            o3.put("totalHits", group.totalHits);

            if (!Float.isNaN(group.maxScore)) {
              o3.put("maxScore", group.maxScore);
            }

            if (!Float.isNaN(group.score)) {
              o3.put("score", group.score);
            }

            JSONObject o4 = new JSONObject();
            o3.put("groupSortFields", o4);
            SortField[] groupSortFields = groupSort.getSort();
            for(int i=0;i<groupSortFields.length;i++) {
              String field = groupSortFields[i].getField();
              if (field == null) {
                field = "<score>";
              }
              o4.put(field, group.groupSortValues[i]);
            }

            JSONArray o5 = new JSONArray();
            o3.put("hits", o5);

            for(ScoreDoc hit : group.scoreDocs) {
              JSONObject o6 = new JSONObject();
              o5.add(o6);
              o6.put("doc", hit.doc);
              if (!Float.isNaN(hit.score)) {
                o6.put("score", hit.score);
              }

              if (fields != null || highlightFields != null) {
                JSONObject o7 = new JSONObject();
                o6.put("fields", o7);
                fillFields(indexState, highlighter, s.searcher, o7, hit, fields, highlights, hitIndex, sort, sortFieldNames, dynamicFields);
              }

              hitIndex++;
            }
          }
        }
      } else if (!useBlockJoinCollector.isEmpty()) {
        // ToParentBlockJoin
        if (joinGroups == null) {
          result.put("totalHits", 0);
          result.put("totalGroupCount", 0);
        } else {

          assert useBlockJoinCollector.size() == 1;
          Iterator<Map.Entry<ToParentBlockJoinQuery,BlockJoinQueryChild>> it = useBlockJoinCollector.entrySet().iterator();
          Map.Entry<ToParentBlockJoinQuery,BlockJoinQueryChild> ent = it.next();
          BlockJoinQueryChild child = ent.getValue();

          result.put("totalHits", joinGroups.totalHitCount);
          result.put("totalGroupedHits", joinGroups.totalGroupedHitCount);
          if (joinGroups.totalGroupCount != null) {
            result.put("totalGroupCount", joinGroups.totalGroupCount);
          }

          // nocommit why am I getting a maxScore back when
          // I didn't ask for it ... oh because I'm sorting
          // by relevance ... hmm ... must test field sort
          // case

          if (!Float.isNaN(joinGroups.maxScore)) {
            result.put("maxScore", joinGroups.maxScore);
          }

          JSONArray o2 = new JSONArray();
          result.put("groups", o2);
          int hitIndex = 0;
          for(GroupDocs<Integer> group : joinGroups.groups) {
            JSONObject o3 = new JSONObject();
            o2.add(o3);
            if (fields != null || highlightFields != null) {
              JSONObject o4 = new JSONObject();
              o3.put("fields", o4);
              ScoreDoc sd = new ScoreDoc(group.groupValue.intValue(), group.score);
              fillFields(indexState, highlighter, s.searcher, o4, sd, fields, highlights, hitIndex, sort, sortFieldNames, dynamicFields);
            }
            hitIndex++;

            o3.put("totalHits", group.totalHits);

            if (!Float.isNaN(group.maxScore)) {
              o3.put("maxScore", group.maxScore);
            }

            JSONObject o4 = new JSONObject();
            o3.put("groupSortFields", o4);
            SortField[] groupSortFields = (child.sort == null ? Sort.RELEVANCE : child.sort).getSort();
            for(int i=0;i<groupSortFields.length;i++) {
              String field = groupSortFields[i].getField();
              if (field == null) {
                field = "<score>";
              }
              o4.put(field, group.groupSortValues[i]);
            }

            JSONArray o5 = new JSONArray();
            o3.put("hits", o5);

            for(ScoreDoc hit : group.scoreDocs) {
              JSONObject o6 = new JSONObject();
              o5.add(o6);
              o6.put("doc", hit.doc);
              if (!Float.isNaN(hit.score)) {
                o6.put("score", hit.score);
              }

              if (fields != null || highlightFields != null) {
                JSONObject o7 = new JSONObject();
                o6.put("fields", o7);
                fillFields(indexState, highlighter, s.searcher, o7, hit, fields, highlights, hitIndex, child.sort, child.sortFieldNames, dynamicFields);
              }

              hitIndex++;
            }
          }
        }

      } else {
        result.put("totalHits", hits.totalHits);
        JSONArray o2 = new JSONArray();
        result.put("hits", o2);
        if (!Float.isNaN(hits.getMaxScore())) {
          result.put("maxScore", hits.getMaxScore());
        }

        for(int hitIndex=0;hitIndex<hits.scoreDocs.length;hitIndex++) {
          ScoreDoc hit = hits.scoreDocs[hitIndex];

          JSONObject o3 = new JSONObject();
          o2.add(o3);
          o3.put("doc", hit.doc);
          if (!Float.isNaN(hit.score)) {
            o3.put("score", hit.score);
          }

          if (fields != null || highlightFields != null) {
            JSONObject o4 = new JSONObject();
            o3.put("fields", o4);
            fillFields(indexState, highlighter, s.searcher, o4, hit, fields, highlights, hitIndex, sort, sortFieldNames, dynamicFields);
          }
        }
      }

      JSONObject o3 = new JSONObject();
      result.put("searchState", o3);
      o3.put("timeStamp", timestampSec);

      // Record searcher version that handled this request:
      o3.put("searcher", ((DirectoryReader) s.searcher.getIndexReader()).getVersion());

      // Fill in lastDoc for searchAfter:
      if (hits != null && hits.scoreDocs.length != 0) {
        ScoreDoc lastHit = hits.scoreDocs[hits.scoreDocs.length-1];
        o3.put("lastDoc", lastHit.doc);
        if (sort != null) {
          JSONArray fieldValues = new JSONArray();
          o3.put("lastFieldValues", fieldValues);
          FieldDoc fd = (FieldDoc) lastHit;
          for(Object fv : fd.fields) {
            fieldValues.add(fv);
          }
        } else {
          o3.put("lastScore", lastHit.score);
        }
      }

      diagnostics.put("getFieldsMS", ((System.nanoTime()-t0)/1000000));

      t0 = System.nanoTime();
      resultString = result.toString();
      //System.out.println("MS: " + ((System.nanoTime()-t0)/1000000.0));
        
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
