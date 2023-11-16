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
import java.io.Reader;
import java.text.Collator;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.analysis.CharArraySet;
import org.apache.lucene.analysis.CharFilterFactory;
import org.apache.lucene.analysis.TokenFilter;
import org.apache.lucene.analysis.TokenFilterFactory;
import org.apache.lucene.analysis.TokenStream;
import org.apache.lucene.analysis.Tokenizer;
import org.apache.lucene.analysis.TokenizerFactory;
import org.apache.lucene.analysis.ar.ArabicAnalyzer;
import org.apache.lucene.analysis.bg.BulgarianAnalyzer;
import org.apache.lucene.analysis.br.BrazilianAnalyzer;
import org.apache.lucene.analysis.ca.CatalanAnalyzer;
import org.apache.lucene.analysis.cjk.CJKAnalyzer;
import org.apache.lucene.analysis.core.WhitespaceAnalyzer;
import org.apache.lucene.analysis.de.GermanAnalyzer;
import org.apache.lucene.analysis.en.EnglishAnalyzer;
import org.apache.lucene.analysis.eu.BasqueAnalyzer;
import org.apache.lucene.analysis.hy.ArmenianAnalyzer;
import org.apache.lucene.analysis.icu.segmentation.DefaultICUTokenizerConfig;
import org.apache.lucene.analysis.icu.segmentation.ICUTokenizer;
import org.apache.lucene.analysis.icu.segmentation.ICUTokenizerConfig;
import org.apache.lucene.analysis.standard.StandardAnalyzer;
import org.apache.lucene.analysis.synonym.SynonymFilter;
import org.apache.lucene.analysis.synonym.SynonymMap;
import org.apache.lucene.codecs.DocValuesFormat;
import org.apache.lucene.codecs.PostingsFormat;
import org.apache.lucene.collation.CollationKeyAnalyzer;
import org.apache.lucene.document.FieldType;
import org.apache.lucene.expressions.Expression;
import org.apache.lucene.expressions.js.JavascriptCompiler;
import org.apache.lucene.facet.FacetsConfig;
import org.apache.lucene.index.DocValuesType;
import org.apache.lucene.index.IndexOptions;
import org.apache.lucene.search.DoubleValuesSource;
import org.apache.lucene.search.similarities.BM25Similarity;
import org.apache.lucene.search.similarities.ClassicSimilarity;
import org.apache.lucene.search.similarities.Similarity;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.FieldDefBindings;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.params.BooleanType;
import org.apache.lucene.server.params.EnumType;
import org.apache.lucene.server.params.FloatType;
import org.apache.lucene.server.params.IntType;
import org.apache.lucene.server.params.ListType;
import org.apache.lucene.server.params.OrType;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.PolyType.PolyEntry;
import org.apache.lucene.server.params.PolyType;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.server.params.Type;
import org.apache.lucene.server.params.WrapType;
import org.apache.lucene.util.AttributeFactory;
import org.apache.lucene.util.CharsRef;
import org.apache.lucene.util.CharsRefBuilder;
import org.apache.lucene.util.ResourceLoader;
import org.apache.lucene.util.ResourceLoaderAware;
import org.apache.lucene.util.Version;

import com.ibm.icu.lang.UCharacter;
import com.ibm.icu.lang.UProperty;
import com.ibm.icu.lang.UScript;
import com.ibm.icu.text.BreakIterator;
import com.ibm.icu.text.RuleBasedBreakIterator;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;
import net.minidev.json.JSONValue;

/** Handles {@code registerFields}. */
public class RegisterFieldsHandler extends Handler {

  private final static List<Object> DEFAULT_ENGLISH_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : EnglishAnalyzer.getDefaultStopSet()) {
      DEFAULT_ENGLISH_STOP_WORDS.add(new String((char[]) o));
    }
  }

  private final static List<Object> DEFAULT_ARABIC_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : ArabicAnalyzer.getDefaultStopSet()) {
      DEFAULT_ARABIC_STOP_WORDS.add(new String((char[]) o));
    }
  }

  private final static List<Object> DEFAULT_ARMENIAN_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : ArmenianAnalyzer.getDefaultStopSet()) {
      DEFAULT_ARMENIAN_STOP_WORDS.add(new String((char[]) o));
    }
  }

  private final static List<Object> DEFAULT_BASQUE_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : BasqueAnalyzer.getDefaultStopSet()) {
      DEFAULT_BASQUE_STOP_WORDS.add(new String((char[]) o));
    }
  }

  private final static List<Object> DEFAULT_BRAZILIAN_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : BrazilianAnalyzer.getDefaultStopSet()) {
      DEFAULT_BRAZILIAN_STOP_WORDS.add(new String((char[]) o));
    }
  }

  private final static List<Object> DEFAULT_BULGARIAN_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : BulgarianAnalyzer.getDefaultStopSet()) {
      DEFAULT_BULGARIAN_STOP_WORDS.add(new String((char[]) o));
    }
  }

  private final static List<Object> DEFAULT_CJK_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : CJKAnalyzer.getDefaultStopSet()) {
      DEFAULT_CJK_STOP_WORDS.add(new String((char[]) o));
    }
  }

  private final static List<Object> DEFAULT_CATALAN_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : CatalanAnalyzer.getDefaultStopSet()) {
      DEFAULT_CATALAN_STOP_WORDS.add(new String((char[]) o));
    }
  }

  private final static List<Object> DEFAULT_GERMAN_STOP_WORDS = new ArrayList<Object>();
  static {
    for(Object o : GermanAnalyzer.getDefaultStopSet()) {
      DEFAULT_GERMAN_STOP_WORDS.add(new String((char[]) o));
    }
  }

  // Breaks the recursion:
  private final static WrapType ANALYZER_TYPE_WRAP = new WrapType();

  /** Analyzer type. */
  final static Type ANALYZER_TYPE =
    new StructType(
                   new Param("class",
                             "An existing Analyzer class.  Use either this, or define your own analysis chain by setting tokenizer and tokenFilter.",
                             new PolyType(Analyzer.class,
                                          new PolyEntry("ArabicAnalyzer", "Analyzer for Arabic (see @lucene:analyzers-common:org.apache.lucene.analysis.ar.ArabicAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis",
                                                                  new ListType(new StringType()), DEFAULT_ARABIC_STOP_WORDS),
                                                        new Param("stemExclusionSet", "A set of terms not to be stemmed",
                                                                  new ListType(new StringType()))),
                                          new PolyEntry("ArmenianAnalyzer", "Analyzer for Armenian. (see @lucene:analyzers-common:org.apache.lucene.analysis.hy.ArmenianAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis",
                                                                  new ListType(new StringType()), DEFAULT_ARMENIAN_STOP_WORDS),
                                                        new Param("stemExclusionSet", "A set of terms not to be stemmed",
                                                                  new ListType(new StringType()))),
                                          new PolyEntry("BasqueAnalyzer", "Analyzer for Basque. (see @lucene:analyzers-common:org.apache.lucene.analysis.eu.BasqueAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis",
                                                                  new ListType(new StringType()), DEFAULT_BASQUE_STOP_WORDS),
                                                        new Param("stemExclusionSet", "A set of terms not to be stemmed",
                                                                  new ListType(new StringType()))),
                                          new PolyEntry("BrazilianAnalyzer", "Analyzer for Brazilian Portuguese language (see @lucene:analyzers-common:org.apache.lucene.analysis.br.BrazilianAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis",
                                                                  new ListType(new StringType()), DEFAULT_BRAZILIAN_STOP_WORDS),
                                                        new Param("stemExclusionSet", "A set of terms not to be stemmed",
                                                                  new ListType(new StringType()))),
                                          new PolyEntry("BulgarianAnalyzer", "Analyzer for Bulgarian (see @lucene:analyzers-common:org.apache.lucene.analysis.bg.BulgarianAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis",
                                                                  new ListType(new StringType()), DEFAULT_BULGARIAN_STOP_WORDS),
                                                        new Param("stemExclusionSet", "A set of terms not to be stemmed",
                                                                  new ListType(new StringType()))),
                                          new PolyEntry("CatalanAnalyzer", "Analyzer for Catalan (see @lucene:analyzers-common:org.apache.lucene.analysis.ca.CatalanAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis",
                                                                  new ListType(new StringType()), DEFAULT_BULGARIAN_STOP_WORDS),
                                                        new Param("stemExclusionSet", "A set of terms not to be stemmed",
                                                                  new ListType(new StringType()))),
                                          new PolyEntry("CJKAnalyzer", "An Analyzer that tokenizes text with StandardTokenizer, normalizes content with CJKWidthFilter, folds case with LowerCaseFilter, forms bigrams of CJK with CJKBigramFilter, and filters stopwords with StopFilter (see @lucene:analyzers-common:org.apache.lucene.analysis.cjk.CJKAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis",
                                                                  new ListType(new StringType()), DEFAULT_CJK_STOP_WORDS)),
                                          new PolyEntry("CollationKeyAnalyzer", "<p> Configures KeywordTokenizer with CollationAttributeFactory (see @lucene:analyzers-common:org.apache.lucene.collation.CollationKeyAnalyzer)",
                                                        new Param("locale", "Locale", SearchHandler.LOCALE_TYPE)),
                                          new PolyEntry("EnglishAnalyzer", "Analyzer for English. (see @lucene:analyzers-common:org.apache.lucene.analysis.en.EnglishAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis.",
                                                                  new ListType(new StringType()), DEFAULT_ENGLISH_STOP_WORDS),
                                                        new Param("stemExclusionSet", "A set of terms not to be stemmed",
                                                                  new ListType(new StringType()))),
                                          new PolyEntry("GermanAnalyzer", "Analyzer for German language (see @lucene:analyzers-common:org.apache.lucene.analysis.de.GermanAnalyzer)",
                                                        new Param("stopWords", "Stop words to remove during analysis.",
                                                                  new ListType(new StringType()), DEFAULT_GERMAN_STOP_WORDS),
                                                        new Param("stemExclusionSet", "A set of terms not to be stemmed",
                                                                  new ListType(new StringType()))),
                                          new PolyEntry("StandardAnalyzer", "Filters StandardTokenizer with StandardFilter, LowerCaseFilter and StopFilter, using a list of English stop words (see @lucene:analyzers-common:org.apache.lucene.analysis.standard.StandardAnalyzer)",
                                                        new Param("maxTokenLength", "Max token length.", new IntType(), StandardAnalyzer.DEFAULT_MAX_TOKEN_LENGTH),
                                                        new Param("stopWords", "Stop words to remove during analysis.",
                                                                  new ListType(new StringType()), DEFAULT_ENGLISH_STOP_WORDS)),
                                          new PolyEntry("WhitespaceAnalyzer", "An Analyzer that uses WhitespaceTokenizer (see @lucene:analyzers-common:org.apache.lucene.analysis.core.WhitespaceAnalyzer)")),
                             "StandardAnalyzer"),
                   new Param("positionIncrementGap", "How many positions to insert between separate values in a multi-valued field", new IntType(), 0),
                   new Param("offsetGap", "How many offsets to insert between separate values in a multi-valued field", new IntType(), 1),
                   new Param("tokenizer", "Tokenizer class (for a custom analysis chain).",
                             new OrType(new StringType(), new StructType(new Param("class", "Tokenizer short name (e.g, 'Whitespace')", new StringType())))),
                             // nocommit somehow tap into TokenizerFactory.availableTokenizers
                   new Param("tokenFilters", "Optional chain of TokenFilters to apply after the Tokenizer",
                             new ListType(
                                 new OrType(new StringType(), new StructType(new Param("class", "TokenFilter short name (e.g. 'Stop')", new StringType()))))),
                   new Param("charFilters", "Optional chain of CharFilters to apply beforethe Tokenizer",
                             new ListType(
                                 new OrType(new StringType(), new StructType(new Param("class", "CharFilter short name", new StringType()))))));

  static StructType SYNONYM_FILTER_TYPE = new StructType(
                                              new Param("ignoreCase", "True if matching should be case insensitive", new BooleanType(), true),
                                              new Param("analyzer", "Analyzer to use to tokenize synonym inputs", ANALYZER_TYPE_WRAP),
                                              new Param("synonyms", "Synonyms",
                                                  /** nocommit syn filter: maybe the simpler groups / aliases format? */
                                                  new ListType(
                                                      new StructType(
                                                          new Param("input", "String or list of strings with input token(s) to match", new OrType(new ListType(new StringType()), new StringType())),
                                                          // TODO: allow more than one token on the output?
                                                          new Param("output", "Single token to replace the matched tokens with", new StringType()),
                                                          new Param("replace", "True if the input tokens should be replaced with the output token; false if the input tokens should be preserved and the output token overlaid", new BooleanType(), true)))));

  static StructType ICU_TOKENIZER_TYPE = new StructType(
                                             new Param("cjkAsWords", "??", new BooleanType(), true),
                                             new Param("rules", "Customize the tokenization per-script",
                                                 new ListType(
                                                     new StructType(
                                                         new Param("script", "Script", new StringType()),
                                                         new Param("rules", "Rules", new StringType())))));

  static {
    ANALYZER_TYPE_WRAP.set(ANALYZER_TYPE);
  }

  @SuppressWarnings("deprecation")
  private final static StructType FIELD_TYPE =
    new StructType(
        new Param("type", "Type of the value.",
                  new EnumType("text", "Text that's tokenized and indexed, with the index-time analyzer.",
                               "atom", "Text that's indexed as a single token, with DOCS_ONLY and omitting norms.",
                               "boolean", "Boolean value.",
                               "float", "Float value.",
                               "double", "Double value.",
                               "int", "Int value.",
                               "long", "Long value.",
                               "latlon", "A latitude/longitude point",
                               "datetime", "Date and optional time",
                               // nocommit name this "dynamic" instead of "virtual"?
                               "virtual", "Virtual field defined with a JavaScript expression.",
                               // nocommit need tests for internal:
                               "internal", "Internal field, currently only for holding indexed facets data.")),
        new Param("dateTimeFormat", "Format string used to parse datetime fields", new StringType()),
        new Param("search", "True if the value should be available for searching (or numeric range searching, for a numeric field).", new BooleanType(), false),
        new Param("tokenize", "True if the value should be tokenized.", new BooleanType(), true),
        new Param("store", "True if the value should be stored.", new BooleanType(), false),
        new Param("multiValued", "True if this field may sometimes have more than one value.", new BooleanType(), false),
        new Param("highlight", "True if the value should be indexed for highlighting.", new BooleanType(), false),
        new Param("postingsFormat", "Which PostingsFormat should be used to index this field.",
                  new StringType(), "Lucene90"),
        new Param("docValuesFormat", "Which DocValuesFormat should be used to index this field.",
                  new StringType(), "Lucene90"),
        new Param("sort", "True if the value should be indexed into doc values for sorting.", new BooleanType(), false),
        new Param("group", "True if the value should be indexed into doc values for grouping.", new BooleanType(), false),
        new Param("facet", "Whether this field should index facets, and how.",
                  new EnumType("no", "No facets are indexed.",
                               "flat", "Facets are indexed with no hierarchy.",
                               "hierarchy", "Facets are indexed and are hierarchical.",
                               "numericRange", "Compute facet counts for custom numeric ranges",
                               "sortedSetDocValues", "Use SortedSetDocValuesFacetCounts, which must be flat but don't require a taxonomy index"),
                  "no"),
        new Param("facetIndexFieldName",
                  "Which underlying Lucene index field is used to hold any indexed taxonomy or sorted set doc values facets",
                  new StringType(), FacetsConfig.DEFAULT_INDEX_FIELD_NAME),
        new Param("storeDocValues", "Whether to index the value into doc values.", new BooleanType(), false),
        new Param("omitNorms", "True if norms are omitted.", new BooleanType(), false),
        new Param("analyzer", "Analyzer to use for this field during indexing and searching.", ANALYZER_TYPE),
        new Param("indexAnalyzer", "Analyzer to use for this field during indexing.", ANALYZER_TYPE),
        new Param("searchAnalyzer", "Analyzer to use for this field during searching.", ANALYZER_TYPE),
        new Param("indexOptions", "How the tokens should be indexed.",
                  new EnumType("docs", "Index only doc ids (for binary search).",
                               "docsFreqs", "Index doc ids and term frequencies.",
                               "docsFreqsPositions", "Index doc ids, term frequences and positions.",
                               "docsFreqsPositionsOffsets", "Index doc ids, term frequencies, positions and offsets."),
                  "docsFreqsPositions"),
        new Param("expression", "The JavaScript expression defining a virtual field's value (only used with type=virtual).", new StringType()),
        new Param("termVectors", "Whether/how term vectors should be indexed.",
                  new EnumType("terms", "Index terms and freqs only.",
                               "termsPositions", "Index terms, freqs and positions.",
                               "termsPpositionsOffsets", "Index terms, freqs, positions and offsets.",
                               "termsPositionsdOoffsetsPayloads", "Index terms, freqs, positions, offsets and payloads."
                               )),
        new Param("similarity", "Which Similarity implementation to use for this field.",
                  new StructType(
                                 new Param("class",
                                           "Which Similarity class to use.",
                                           new PolyType(Similarity.class,
                                               new PolyEntry("DefaultSimilarity", "Expert: Default scoring implementation. (see @lucene:core:org.apache.lucene.search.similarities.DefaultSimilarity)", new StructType()),
                                               new PolyEntry("BM25Similarity", "BM25 Similarity (see @lucene:core:org.apache.lucene.search.similarities.BM25Similarity)",
                                                   new StructType(new Param("k1", "Controls non-linear term frequency normalization (saturation).", new FloatType(), 1.2f),
                                                                  new Param("b", "Controls to what degree document length normalizes tf values.", new FloatType(), 0.75f)))),
                                           "DefaultSimilarity")))
                   );

  /** Method type. */
  public final static StructType TYPE =
    new StructType(
        new Param("indexName", "Index name", new StringType()),
        new Param("fields", "New fields to register",
            new StructType(new Param("*", "Register this field name with the provided type.  Note that the field name must be of the form [a-zA-Z_][a-zA-Z_0-9]*.  You can register multiple fields in one request.", FIELD_TYPE))));

  /** Sole constructor. */
  public RegisterFieldsHandler(GlobalState state) {
    super(state);
  }

  @Override
  public String getTopDoc() {
    return "Registers one or more fields.  Fields must be registered before they can be added in a document (via @addDocument).  Pass a struct whose keys are the fields names to register and whose values define the type for that field.  Any number of fields may be registered in a single request, and once a field is registered it cannot be changed (write-once).  <p>This returns the full set of fields currently registered.";
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  private FieldDef parseOneVirtualFieldType(Request r, IndexState state, Map<String,FieldDef> pendingFieldDefs, String name, JSONObject o) {
    String exprString = r.getString("expression");
    Expression expr;

    System.out.println("PARSE: " + exprString + " name=" + name);

    try {
      expr = JavascriptCompiler.compile(exprString);
    } catch (ParseException pe) {
      // Static error (e.g. bad JavaScript syntax):
      r.fail("expression", "could not parse expression: " + pe, pe);

      // Dead code but compiler disagrees:
      expr = null;
    } catch (IllegalArgumentException iae) {
      // Static error (e.g. bad JavaScript syntax):
      r.fail("expression", "could not parse expression: " + iae, iae);

      // Dead code but compiler disagrees:
      expr = null;
    }

    Map<String,FieldDef> allFields = new HashMap<String,FieldDef>(state.getAllFields());
    allFields.putAll(pendingFieldDefs);

    DoubleValuesSource values;
    try {
      values = expr.getDoubleValuesSource(new FieldDefBindings(allFields));
    } catch (RuntimeException re) {
      // Dynamic error (e.g. referred to a field that
      // doesn't exist):
      System.out.println("NOW FAIL");
      r.fail("expression", "could not evaluate expression: " + re, re);

      // Dead code but compiler disagrees:
      values = null;
    }

    return new FieldDef(name, null, FieldDef.FieldValueType.VIRTUAL, null, null, null, true, false, null, null, null, false, values, null);
  }

  private FieldDef parseOneFieldType(Request r, IndexState state, Map<String,FieldDef> pendingFieldDefs, String name, JSONObject o) throws IOException {

    // This way f.fail reports which field name was problematic:
    Request f = new Request(r, name, o, FIELD_TYPE);

    String typeString = f.getEnum("type");
    if (typeString.equals("virtual")) {
      return parseOneVirtualFieldType(f, state, pendingFieldDefs, name, o);
    }
    FieldDef.FieldValueType type;
    switch(typeString) {
    case "atom":
      type = FieldDef.FieldValueType.ATOM;
      break;
    case "text":
      type = FieldDef.FieldValueType.TEXT;
      break;
    case "boolean":
      type = FieldDef.FieldValueType.BOOLEAN;
      break;
    case "long":
      type = FieldDef.FieldValueType.LONG;
      break;
    case "int":
      type = FieldDef.FieldValueType.INT;
      break;
    case "double":
      type = FieldDef.FieldValueType.DOUBLE;
      break;
    case "float":
      type = FieldDef.FieldValueType.FLOAT;
      break;
    case "latlon":
      type = FieldDef.FieldValueType.LAT_LON;
      break;
    case "datetime":
      type = FieldDef.FieldValueType.DATE_TIME;
      break;
    default:
      // bug!  we declare the allowed types
      throw new AssertionError();
    }

    FieldType ft = new FieldType();

    // nocommit why do we have storeDocValues?  it's too low level?
    boolean dv = f.getBoolean("storeDocValues");
    boolean sorted = f.getBoolean("sort");
    boolean grouped = f.getBoolean("group");

    Boolean stored = null;
    if (f.hasParam("store")) {
      stored = f.getBoolean("store");
    }

    // TODO: current we only highlight using
    // PostingsHighlighter; if we enable others (that use
    // term vectors), we need to fix this so app specifies
    // up front which highlighter(s) it wants to use at
    // search time:
    boolean highlighted = f.getBoolean("highlight");

    if (highlighted) {
      if (type != FieldDef.FieldValueType.TEXT && type != FieldDef.FieldValueType.ATOM) {
        f.fail("highlight", "only type=text or type=atom fields can have highlight=true");
      }
    }

    boolean multiValued = f.getBoolean("multiValued");
    if (multiValued) {
      // nocommit not true!  but do we need something at search time so you can pick the picker?
      //if (sorted) {
      //f.fail("multiValued", "cannot sort on multiValued fields");
      //}
      if (grouped) {
        f.fail("multiValued", "cannot group on multiValued fields");
      }
    }

    // if stored was unspecified and we are highlighting, turn it on:
    if (highlighted) {
      if (stored == null) {
        stored = true;
      }
    }
    
    String dateTimeFormat = null;

    // System.out.println("NAME: " + name + " type: " + type + " hightlight: " + highlighted);

    switch(type) {

    case TEXT:
      if (sorted) {
        f.fail("sort", "cannot sort text fields; use atom instead");
      }
      ft.setTokenized(true);
      if (grouped) {
        ft.setDocValuesType(DocValuesType.SORTED);
      } else if (dv) {
        ft.setDocValuesType(DocValuesType.BINARY);
      }
      if (highlighted) {
        if (stored == false) {
          f.fail("store", "store=false is not allowed when highlight=true");
        }
        ft.setStored(true);
        ft.setIndexOptions(IndexOptions.DOCS_AND_FREQS_AND_POSITIONS_AND_OFFSETS);
      } else {
        ft.setIndexOptions(IndexOptions.DOCS_AND_FREQS_AND_POSITIONS);
      }
      break;

    case ATOM:
      if (f.hasParam("analyzer")) {
        f.fail("analyzer", "no analyzer allowed with atom (it's hardwired to KeywordAnalyzer internally)");
      }
      if (highlighted) {
        if (stored == false) {
          f.fail("store", "store=false is not allowed when highlight=true");
        }
        // nocommit need test highlighting atom fields
        ft.setStored(true);
        ft.setIndexOptions(IndexOptions.DOCS_AND_FREQS_AND_POSITIONS_AND_OFFSETS);
      } else {
        ft.setIndexOptions(IndexOptions.DOCS);
      }
      ft.setOmitNorms(true);
      ft.setTokenized(false);
      if (sorted || grouped) {
        if (multiValued) {
          ft.setDocValuesType(DocValuesType.SORTED_SET);
        } else {
          ft.setDocValuesType(DocValuesType.SORTED);
        }
      } else if (grouped || dv) {
        ft.setDocValuesType(DocValuesType.BINARY);
      }
      break;
      
    case BOOLEAN:
      if (dv || sorted || grouped) {
        if (multiValued) {
          ft.setDocValuesType(DocValuesType.SORTED_NUMERIC);
        } else {
          ft.setDocValuesType(DocValuesType.NUMERIC);
        }
      }
      break;

    case LONG:
      if (dv || sorted || grouped) {
        if (multiValued) {
          ft.setDocValuesType(DocValuesType.SORTED_NUMERIC);
        } else {
          ft.setDocValuesType(DocValuesType.NUMERIC);
        }
      }
      break;

    case INT:
      if (dv || sorted || grouped) {
        if (multiValued) {
          ft.setDocValuesType(DocValuesType.SORTED_NUMERIC);
        } else {
          ft.setDocValuesType(DocValuesType.NUMERIC);
        }
      }
      break;
      
    case DOUBLE:
      if (dv || sorted || grouped) {
        if (multiValued) {
          ft.setDocValuesType(DocValuesType.SORTED_NUMERIC);
        } else {
          ft.setDocValuesType(DocValuesType.NUMERIC);
        }
      }
      break;
      
    case FLOAT:
      if (dv || sorted || grouped) {
        if (multiValued) {
          ft.setDocValuesType(DocValuesType.SORTED_NUMERIC);
        } else {
          ft.setDocValuesType(DocValuesType.NUMERIC);
        }
      }
      break;
      
    case LAT_LON:
      if (stored == Boolean.TRUE) {
        f.fail("stored", "latlon fields cannot be stored");
      }
      ft.setDimensions(2, Integer.BYTES);
      if (sorted) {
        ft.setDocValuesType(DocValuesType.SORTED_NUMERIC);
      }
      break;

    case DATE_TIME:

      // nocommit maybe we only accept https://www.ietf.org/rfc/rfc3339.txt

      dateTimeFormat = f.getString("dateTimeFormat");

      // make sure the format is valid:
      try {
        new SimpleDateFormat(dateTimeFormat);
      } catch (IllegalArgumentException iae) {
        f.fail("dateTimeFormat", "could not parse pattern", iae);
      }
      if (grouped) {
        f.fail("group", "cannot group on datetime fields");
      }
      if (dv || sorted) {
        if (multiValued) {
          ft.setDocValuesType(DocValuesType.SORTED_NUMERIC);
        } else {
          ft.setDocValuesType(DocValuesType.NUMERIC);
        }
      }
      
      break;
      
    default:
      throw new AssertionError("unhandled type \"" + type + "\"");
    }

    // nocommit InetAddressPoint, BiggishInteger

    if (stored == Boolean.TRUE) {
      ft.setStored(true);
    }

    boolean usePoints = false;

    if (f.hasParam("search")) {
      if (f.getBoolean("search")) {
        if (type == FieldDef.FieldValueType.INT ||
            type == FieldDef.FieldValueType.LONG ||
            type == FieldDef.FieldValueType.FLOAT ||
            type == FieldDef.FieldValueType.DOUBLE ||
            type == FieldDef.FieldValueType.LAT_LON ||
            type == FieldDef.FieldValueType.DATE_TIME) {
          usePoints = true;
        } else if (ft.indexOptions() == IndexOptions.NONE) {
          ft.setIndexOptions(IndexOptions.DOCS_AND_FREQS_AND_POSITIONS);
        }
      } else if (highlighted) {
        throw f.bad("search", "search must be true when highlight is true");
      } else {
        ft.setIndexOptions(IndexOptions.NONE);
      }
    }

    if (f.hasParam("analyzer") && ft.indexOptions() == IndexOptions.NONE) {
      f.fail("analyzer", "no analyzer allowed when search=false");
    }

    if (type == FieldDef.FieldValueType.TEXT || type == FieldDef.FieldValueType.ATOM) {

      if (ft.indexOptions() != IndexOptions.NONE) {
        if (f.hasParam("tokenize")) {
          ft.setTokenized(f.getBoolean("tokenize"));
        }
        if (f.hasParam("omitNorms")) {
          ft.setOmitNorms(f.getBoolean("omitNorms"));
        }

        if (f.hasParam("termVectors")) {
          String tv = f.getString("termVectors");
          if (tv.equals("terms")) {
            ft.setStoreTermVectors(true);
          } else if (tv.equals("termsPositions")) {
            ft.setStoreTermVectors(true);
            ft.setStoreTermVectorPositions(true);
          } else if (tv.equals("termsPositionsOffsets")) {
            ft.setStoreTermVectors(true);
            ft.setStoreTermVectorPositions(true);
            ft.setStoreTermVectorOffsets(true);
          } else if (tv.equals("termsPositionsOffsetsPayloads")) {
            ft.setStoreTermVectors(true);
            ft.setStoreTermVectorPositions(true);
            ft.setStoreTermVectorOffsets(true);
            ft.setStoreTermVectorPayloads(true);
          } else {
            assert false;
          }
        }

        if (f.hasParam("indexOptions")) {
          String io = f.getString("indexOptions");
          if (io.equals("docs")) {
            ft.setIndexOptions(IndexOptions.DOCS);
          } else if (io.equals("docsFreqs")) {
            ft.setIndexOptions(IndexOptions.DOCS_AND_FREQS);
          } else if (io.equals("docsFreqsPositions")) {
            ft.setIndexOptions(IndexOptions.DOCS_AND_FREQS_AND_POSITIONS);
          } else if (io.equals("docsFreqsPositionsAndOffsets")) {
            ft.setIndexOptions(IndexOptions.DOCS_AND_FREQS_AND_POSITIONS_AND_OFFSETS);
          } else {
            assert false;
          }
        }
      }
    } else if (type == FieldDef.FieldValueType.BOOLEAN) {
      ft.setOmitNorms(true);
      ft.setTokenized(false);
      ft.setIndexOptions(IndexOptions.DOCS);
    }

    // nocommit open up binary points too
    // nocommit open up multi-dimensional points

    String pf = f.getString("postingsFormat");
    if (PostingsFormat.forName(pf) == null) {
      f.fail("postingsFormat", "unrecognized postingsFormat \"" + pf + "\"");
    }
    String dvf = f.getString("docValuesFormat");
    if (DocValuesFormat.forName(dvf) == null) {
      f.fail("docValuesFormat", "unrecognized docValuesFormat \"" + dvf + "\"");
    }

    Similarity sim;
    if (f.hasParam("similarity")) {
      Request s = f.getStruct("similarity");
      Request.PolyResult pr = s.getPoly("class");
      if (pr.name.equals("DefaultSimilarity")) {
        sim = new ClassicSimilarity();
      } else if (pr.name.equals("BM25Similarity")) {
        sim = new BM25Similarity(pr.r.getFloat("k1"), pr.r.getFloat("b"));
      } else {
        assert false;
        sim = null;
      }
    } else {
      sim = new BM25Similarity();
    }

    Analyzer indexAnalyzer;
    Analyzer searchAnalyzer;
    Analyzer analyzer = getAnalyzer(state, f, "analyzer");
    if (analyzer != null) {
      indexAnalyzer = searchAnalyzer = analyzer;
    } else {
      indexAnalyzer = getAnalyzer(state, f, "indexAnalyzer");
      searchAnalyzer = getAnalyzer(state, f, "searchAnalyzer");
    }

    if (type == FieldDef.FieldValueType.TEXT && ft.indexOptions() != IndexOptions.NONE) {
      if (indexAnalyzer == null) {
        indexAnalyzer = new StandardAnalyzer();
        if (searchAnalyzer == null) {
          searchAnalyzer = new StandardAnalyzer();
        }
      } else if (searchAnalyzer == null) {
        searchAnalyzer = new StandardAnalyzer();
      }
    }

    if (indexAnalyzer == null) {
      indexAnalyzer = dummyAnalyzer;
    }

    if (searchAnalyzer == null) {
      searchAnalyzer = indexAnalyzer;
    }

    // TODO: facets w/ dates

    String facet = f.getEnum("facet");
    if (facet.equals("hierarchy")) {
      if (highlighted) {
        f.fail("facet", "facet=hierarchy fields cannot have highlight=true");
      }
      if (ft.indexOptions() != IndexOptions.NONE) {
        f.fail("facet", "facet=hierarchy fields cannot have search=true");
      }
      if (ft.stored()) {
        f.fail("facet", "facet=hierarchy fields cannot have store=true");
      }
    } else if (facet.equals("numericRange")) {
      if (type != FieldDef.FieldValueType.LONG && type != FieldDef.FieldValueType.INT && type != FieldDef.FieldValueType.FLOAT && type != FieldDef.FieldValueType.DOUBLE) {
        f.fail("facet", "numericRange facets only applies to numeric types");
      }
      if (ft.indexOptions() == IndexOptions.NONE && usePoints == false) {
        f.fail("search", "facet=numericRange fields must have search=true");
      }
      // We index the field as points, for drill-down, and store doc values, for dynamic facet counting
      ft.setDocValuesType(DocValuesType.NUMERIC);
    } else if (facet.equals("no")) {
      if (ft.indexOptions() == IndexOptions.NONE && ft.stored() == false && ft.docValuesType() == DocValuesType.NONE && usePoints == false) {
        f.fail("field does nothing: it's neither searched, stored, sorted, grouped, highlighted nor faceted");
      }
    }

    ft.freeze();

    if (facet.equals("no") == false && facet.equals("numericRange") == false) {
      // hierarchy, float or sortedSetDocValues
      if (facet.equals("hierarchy")) {
        state.facetsConfig.setHierarchical(name, true);
      }
      if (multiValued) {
        state.facetsConfig.setMultiValued(name, true);
      }
      state.facetsConfig.setIndexFieldName(name, f.getString("facetIndexFieldName"));
    }

    // nocommit facetsConfig.setRequireDimCount

    // System.out.println("REGISTER: " + name + " -> " + ft);

    return new FieldDef(name, ft, type, facet, pf, dvf, multiValued, usePoints, sim, indexAnalyzer, searchAnalyzer, highlighted, null, dateTimeFormat);
  }

  /** Messy: we need this for indexed-but-not-tokenized
   *  fields, solely for .getOffsetGap I think. */
  public final static Analyzer dummyAnalyzer = new Analyzer() {
      @Override
      protected TokenStreamComponents createComponents(String fieldName) {
        throw new UnsupportedOperationException();
      }
    };

  private static List<String> toStringList(List<Object> l) {
    List<String> words = new ArrayList<String>();
    for(Object o : l) {
      words.add((String) o);
    }
    return words;
  }

  final static Pattern COMMENTS_PATTERN = Pattern.compile("#.*$", Pattern.MULTILINE);

  static TokenizerFactory buildICUTokenizerFactory(Request sub) {
      
    boolean cjkAsWords;

    final BreakIterator breakers[];

    if (sub != null) {
      Request icuRequest = new Request(sub, ICU_TOKENIZER_TYPE);
            
      cjkAsWords = icuRequest.getBoolean("cjkAsWords");

      if (icuRequest.hasParam("rules")) {
        breakers = new BreakIterator[UScript.CODE_LIMIT];
        for(Object o : icuRequest.getList("rules")) {
          Request r2 = (Request) o;
          String script = r2.getString("script");
          String rules = r2.getString("rules");
          rules = COMMENTS_PATTERN.matcher(rules).replaceAll("");
          //System.out.println("ICU RULES:\n" + rules);
          int code;
          try {
            code = UCharacter.getPropertyValueEnum(UProperty.SCRIPT, script);
          } catch (IllegalArgumentException iae) {
            r2.fail("script", "failed to parse as script code: " + iae.getMessage());
            // Dead code but compiler disagrees:
            code = -1;
          }
          try {
            breakers[code] = new RuleBasedBreakIterator(rules);
          } catch (IllegalArgumentException iae) {
            r2.fail("rules", "failed to parse rules: " + iae.getMessage());
          }
        }
      } else {
        breakers = null;
      }
    } else {
      cjkAsWords = true;
      breakers = null;
    }

    // nocommit make these two booleans controllable!!
    final ICUTokenizerConfig config = new DefaultICUTokenizerConfig(true, true) {
        
        @Override
        public RuleBasedBreakIterator getBreakIterator(int script) {
          if (breakers[script] != null) {
            return (RuleBasedBreakIterator) breakers[script].clone();
          } else {
            return super.getBreakIterator(script);
          }
        }

        // TODO: we could also allow codes->types mapping
      };

    return new TokenizerFactory(Collections.<String,String>emptyMap()) {
      
      @Override
      public Tokenizer create(AttributeFactory factory) {
        return new ICUTokenizer(factory, config);
      };
    };
  }

  // nocommit can we use SynonmyFilterFactory???  we could
  // make a custom Reader subclass that sneaks the
  // JSONObject "through", and then a custom
  // SynFilter.Parser that grabs that JSONObject?

  static TokenFilterFactory buildSynonymFilterFactory(IndexState state, Request r) throws IOException {

    Analyzer a = getAnalyzer(state, r, "analyzer");
    if (a == null) {
      r.fail("analyzer", "analyzer is required");
    }

    final SynonymMap synonymMap = parseSynonyms(r.getList("synonyms"), a);

    final boolean ignoreCase = r.getBoolean("ignoreCase");

    // nocommit expand?  dedup?

    return new TokenFilterFactory(Collections.<String,String>emptyMap()) {
      @Override
      public TokenFilter create(TokenStream input) {
        return new SynonymFilter(input, synonymMap, ignoreCase);
      }
    };
  }

  private static List<CharFilterFactory> parseCharFilters(IndexState state, Request chain) throws IOException {
    List<CharFilterFactory> charFilters;
    if (chain.hasParam("charFilters")) {
      charFilters = new ArrayList<CharFilterFactory>();
      for(Object o : chain.getList("charFilters")) {
        String paramName = "charFilters[" + charFilters.size() + "]";
        Request sub;
        String className;
        if (o instanceof String) {
          className = (String) o;
          sub = null;
        } else {
          // The type already validated this:
          assert o instanceof Request;
          sub = (Request) o;
          className = sub.getString("class");
        }

        TwoThings<Map<String,String>,ResourceLoader> things = parseArgsAndResources(state,
                                                                                    className,
                                                                                    sub);

        CharFilterFactory factory;
        try {
          factory = CharFilterFactory.forName(className, things.a);
        } catch (IllegalArgumentException iae) {
          chain.fail(paramName, "failed to create CharFilterFactory for class \"" + className + "\": " + iae, iae);

          // Dead code but compiler disagrees:
          factory = null;
        }

        if (factory instanceof ResourceLoaderAware) {
          ((ResourceLoaderAware) factory).inform(things.b);
        }

        charFilters.add(factory);
      }
    } else {
      charFilters = null;
    }

    return charFilters;
  }

  private static final class TwoThings<A,B> {
    public final A a;
    public final B b;

    public TwoThings(A a, B b) {
      this.a = a;
      this.b = b;
    }
  };

  /** Parses the arguments for an analysis factory
   *  component, but also detects any argument name of the
   *  form xxxFileContents and puts its value into a "fake"
   *  (RAM) file, leaving xxx referring to that file.  This
   *  way any existing component expecting to load a
   *  resource from a "file" will (hacky) work. */
  private static TwoThings<Map<String,String>,ResourceLoader> parseArgsAndResources(IndexState state,
                                                                                    String className,
                                                                                    Request sub) {
    
    Map<String,String> factoryArgs = new HashMap<String,String>();

    // nocommit how to allow the SPI name and separately
    // also a fully qualified class name ...
    factoryArgs.put("class", className);

    ResourceLoader resources = state.resourceLoader;
    RAMResourceLoaderWrapper ramResources = null;

    if (sub != null) {
      for(Map.Entry<String,Object> ent : sub.getRawParams().entrySet()) {
        String argName = ent.getKey();
        Object argValue = ent.getValue();

        // Messy / impedance mismatch: allow
        // components that expect files for things
        // like stopword lists, keywords, to come in
        // as inlined string values.  We "hijack" any
        // argument name ending in FileContents and
        // make a RAM file out of it:
        String argString;

        if (argName.endsWith("FileContents")) {
          if (ramResources == null) {
            ramResources = new RAMResourceLoaderWrapper(resources);
            resources = ramResources;
          }

          String value;
          if (argValue instanceof String) {
            value = (String) argValue;
          } else if (argValue instanceof JSONArray) {
            // Each element in the array is mapped to
            // one line in the file
            StringBuilder b = new StringBuilder();
            for(Object v : (JSONArray) argValue) {
              if ((v instanceof String) == false) {
                sub.failWrongClass(argName, "array must contain strings", v);
              }
              b.append((String) v);
              b.append('\n');
            }
            value = b.toString();
          } else {
            sub.failWrongClass(argName, "must be a String or Array", argValue);

            // Dead code but compiler disagrees:
            value = null;
          }

          argName = argName.substring(0, argName.length()-12);
          ramResources.add(argName, value);
          argString = argName;
        } else {
          argString = argValue.toString();
        }

        factoryArgs.put(argName, argString);
      }

      // Clear all bindings from the incoming request,
      // so that they are not seen as unused by the
      // server.  If any params are really unused, the
      // analysis factory should throw its own
      // IllegalArgumentException:
      sub.clearParams();
    }

    return new TwoThings<Map<String,String>,ResourceLoader>(factoryArgs, resources);
  }

  static TokenizerFactory parseTokenizer(IndexState state, Request chain) throws IOException {
    // Build TokenizerFactory:
    String className;
    Request sub;
    if (chain.isString("tokenizer")) {
      sub = null;
      className = chain.getString("tokenizer");
    } else {
      sub = chain.getStruct("tokenizer");
      className = sub.getString("class");
    }

    TokenizerFactory tokenizerFactory;
    if (className.toLowerCase(Locale.ROOT).equals("icu")) {
      tokenizerFactory = buildICUTokenizerFactory(sub);
    } else {

      TwoThings<Map<String,String>,ResourceLoader> things = parseArgsAndResources(state, className, sub);
      try {
        tokenizerFactory = TokenizerFactory.forName(className, things.a);
      } catch (IllegalArgumentException iae) {
        chain.fail("tokenizer", "failed to create TokenizerFactory for class \"" + className + "\": " + iae, iae);

        // Dead code but compiler disagrees:
        tokenizerFactory = null;
      }

      if (tokenizerFactory instanceof ResourceLoaderAware) {
        // nocommit need test case that requires a
        // xxxFileContents to a Tokenizer
        ((ResourceLoaderAware) tokenizerFactory).inform(things.b);
      }
    }

    return tokenizerFactory;
  }

  static List<TokenFilterFactory> parseTokenFilters(IndexState state, Request chain) throws IOException {

    // Build TokenFilters
    List<TokenFilterFactory> tokenFilterFactories;
    if (chain.hasParam("tokenFilters")) {
      tokenFilterFactories = new ArrayList<TokenFilterFactory>();
      for(Object o : chain.getList("tokenFilters")) {
        String paramName = "tokenFilters[" + tokenFilterFactories.size() + "]";
        String className;
        Request sub;
        if (o instanceof String) {
          className = (String) o;
          sub = null;
        } else {
          // The type already validated this:
          assert o instanceof Request;
          sub = (Request) o;

          className = sub.getString("class");
        }

        TokenFilterFactory tokenFilterFactory;

        if (className.toLowerCase(Locale.ROOT).equals("synonym")) {
          if (sub == null) {
            chain.fail(paramName, "no synonyms were specified");
          }
          tokenFilterFactory = buildSynonymFilterFactory(state, new Request(chain, paramName, sub.getRawParams(), SYNONYM_FILTER_TYPE));
        } else {
          TwoThings<Map<String,String>,ResourceLoader> things = parseArgsAndResources(state, className, sub);
          
          try {
            tokenFilterFactory = TokenFilterFactory.forName(className, things.a);
          } catch (IllegalArgumentException iae) {
            chain.fail("tokenizer", "failed to create TokenFilterFactory for class \"" + className + "\": " + iae, iae);

            // Dead code but compiler disagrees:
            tokenFilterFactory = null;
          }

          if (tokenFilterFactory instanceof ResourceLoaderAware) {
            ((ResourceLoaderAware) tokenFilterFactory).inform(things.b);
          }
        }

        tokenFilterFactories.add(tokenFilterFactory);
      }
    } else {
      tokenFilterFactories = null;
    }

    return tokenFilterFactories;
  }

  static Analyzer buildCustomAnalyzer(IndexState state, Request chain) throws IOException {

    // nocommit what is MultiTermAwareComponent?

    return new CustomAnalyzer(parseCharFilters(state, chain),
                              parseTokenizer(state, chain),
                              parseTokenFilters(state, chain),
                              chain.getInt("positionIncrementGap"),
                              chain.getInt("offsetGap"));
  }

  private static SynonymMap parseSynonyms(List<Object> syns, Analyzer a) {
    try {
      // nocommit this is awkward!  I just want to use Parser's
      // analyze utility method... if the Parser could just take the JSONObject...
      SynonymMap.Parser parser = new SynonymMap.Parser(true, a) {
          @Override
          public void parse(Reader in) throws IOException {
            // nocommit move parsing in here!
          };
        };

      CharsRefBuilder scratch = new CharsRefBuilder();
      CharsRef scratchOutput = new CharsRef();
      for(Object o2 : syns) {
        Request syn = (Request) o2;
        boolean replace = syn.getBoolean("replace");
        CharsRef output = new CharsRef(syn.getString("output"));
        if (syn.isString("input") == false) {
          for(Object o3 : syn.getList("input")) {
            parser.add(parser.analyze((String) o3, scratch),
                       output,
                       !replace);
          }
        } else {
          parser.add(parser.analyze(syn.getString("input"), scratch),
                     output,
                     !replace);
        }
      }
      return parser.build();
    } catch (IOException ioe) {
      throw new RuntimeException(ioe);
    }
  }

  /** An analyzer based on the custom charFilter, tokenizer,
   *  tokenFilters factory chains specified when the field
   *  was registered. */
  private static class CustomAnalyzer extends Analyzer {
    private final int posIncGap;
    private final int offsetGap;
    private final TokenizerFactory tokenizerFactory;
    private final List<TokenFilterFactory> tokenFilterFactories;
    private final List<CharFilterFactory> charFilterFactories;

    public CustomAnalyzer(List<CharFilterFactory> charFilterFactories,
                          TokenizerFactory tokenizerFactory,
                          List<TokenFilterFactory> tokenFilterFactories,
                          int posIncGap, int offsetGap) {
      this.charFilterFactories = charFilterFactories;
      this.tokenizerFactory = tokenizerFactory;
      this.tokenFilterFactories = tokenFilterFactories;
      this.posIncGap = posIncGap;
      this.offsetGap = offsetGap;
    }

    @Override
    protected TokenStreamComponents createComponents(String fieldName) {
      Tokenizer tokenizer = tokenizerFactory.create();
      TokenStream last = tokenizer;
      if (tokenFilterFactories != null) {
        for(TokenFilterFactory factory : tokenFilterFactories) {
          last = factory.create(last);
        }
      }
      return new TokenStreamComponents(tokenizer, last);
    }

    @Override
    protected Reader initReader(String fieldName, Reader reader) {
      Reader result = reader;
      if (charFilterFactories != null) {
        for(CharFilterFactory factory : charFilterFactories) {
          result = factory.create(result);
        }
      }
      return result;
    }

    @Override
    public int getPositionIncrementGap(String fieldName) {
      return posIncGap;
    }

    @Override
    public int getOffsetGap(String fieldName) {
      return offsetGap;
    }
  }

  static Analyzer getAnalyzer(IndexState state, Request f, String name) throws IOException {
    Analyzer analyzer;
    if (f.hasParam(name)) {
      Request a = f.getStruct(name);
      String jsonOrig = a.toString();

      if (a.hasParam("class")) {
        // nocommit just lookup via CP:
        // Predefined analyzer class:
        Request.PolyResult pr = a.getPoly("class");
        // TODO: try to "share" a single instance of
        // each?  Analyzer can be costly!
        if (pr.name.equals("StandardAnalyzer")) {
          CharArraySet set = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          StandardAnalyzer sa = new StandardAnalyzer(set);
          analyzer = sa;
          sa.setMaxTokenLength(pr.r.getInt("maxTokenLength"));
        } else if (pr.name.equals("EnglishAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          if (pr.r.hasParam("stemExclusionSet")) {
            CharArraySet stemExclusions = new CharArraySet(toStringList(pr.r.getList("stemExclusionSet")), false);
            analyzer = new EnglishAnalyzer(stopWords, stemExclusions);
          } else {
            analyzer = new EnglishAnalyzer(stopWords);
          }
        } else if (pr.name.equals("GermanAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          if (pr.r.hasParam("stemExclusionSet")) {
            CharArraySet stemExclusions = new CharArraySet(toStringList(pr.r.getList("stemExclusionSet")), false);
            analyzer = new GermanAnalyzer(stopWords, stemExclusions);
          } else {
            analyzer = new GermanAnalyzer(stopWords);
          }
        } else if (pr.name.equals("ArabicAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          if (pr.r.hasParam("stemExclusionSet")) {
            CharArraySet stemExclusions = new CharArraySet(toStringList(pr.r.getList("stemExclusionSet")), false);
            analyzer = new ArabicAnalyzer(stopWords, stemExclusions);
          } else {
            analyzer = new ArabicAnalyzer(stopWords);
          }
        } else if (pr.name.equals("ArmenianAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          if (pr.r.hasParam("stemExclusionSet")) {
            CharArraySet stemExclusions = new CharArraySet(toStringList(pr.r.getList("stemExclusionSet")), false);
            analyzer = new ArmenianAnalyzer(stopWords, stemExclusions);
          } else {
            analyzer = new ArmenianAnalyzer(stopWords);
          }
        } else if (pr.name.equals("BasqueAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          if (pr.r.hasParam("stemExclusionSet")) {
            CharArraySet stemExclusions = new CharArraySet(toStringList(pr.r.getList("stemExclusionSet")), false);
            analyzer = new BasqueAnalyzer(stopWords, stemExclusions);
          } else {
            analyzer = new BasqueAnalyzer(stopWords);
          }
        } else if (pr.name.equals("BrazilianAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          if (pr.r.hasParam("stemExclusionSet")) {
            CharArraySet stemExclusions = new CharArraySet(toStringList(pr.r.getList("stemExclusionSet")), false);
            analyzer = new BrazilianAnalyzer(stopWords, stemExclusions);
          } else {
            analyzer = new BrazilianAnalyzer(stopWords);
          }
        } else if (pr.name.equals("BulgarianAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          if (pr.r.hasParam("stemExclusionSet")) {
            CharArraySet stemExclusions = new CharArraySet(toStringList(pr.r.getList("stemExclusionSet")), false);
            analyzer = new BulgarianAnalyzer(stopWords, stemExclusions);
          } else {
            analyzer = new BulgarianAnalyzer(stopWords);
          }
        } else if (pr.name.equals("CatalanAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          if (pr.r.hasParam("stemExclusionSet")) {
            CharArraySet stemExclusions = new CharArraySet(toStringList(pr.r.getList("stemExclusionSet")), false);
            analyzer = new CatalanAnalyzer(stopWords, stemExclusions);
          } else {
            analyzer = new CatalanAnalyzer(stopWords);
          }
        } else if (pr.name.equals("CJKAnalyzer")) {
          CharArraySet stopWords = new CharArraySet(toStringList(pr.r.getList("stopWords")), false);
          analyzer = new CJKAnalyzer(stopWords);
        } else if (pr.name.equals("CollationKeyAnalyzer")) {
          Locale locale = SearchHandler.getLocale(pr.r.getStruct("locale"));
          analyzer = new CollationKeyAnalyzer(Collator.getInstance(locale));
        } else if (pr.name.equals("WhitespaceAnalyzer")) {
          analyzer = new WhitespaceAnalyzer();
        } else {
          f.fail("class", "unrecognized analyzer class \"" + pr.name + "\"");
          // Dead code but compiler disagrees:
          analyzer = null;
        }
      } else if (a.hasParam("tokenizer")) {
        analyzer = buildCustomAnalyzer(state, a);
      } else {
        f.fail(name, "either class or tokenizer/tokenFilters are required");
        analyzer = null;
      }
    } else {
      analyzer = null;
    }

    return analyzer;
  }

  /** Parses a Lucene version constant. */
  @SuppressWarnings("deprecation")
  public static Version getVersion(String v) {
    if (v.equals("LUCENE_980")) {
      return Version.LUCENE_9_8_0;
    } else if (v.equals("LUCENE_970")) {
      return Version.LUCENE_9_7_0;
    } else {
      throw new IllegalArgumentException("unhandled version " + v);
    }
  }

  @Override
  public FinishRequest handle(final IndexState state, Request r, Map<String,List<String>> params) throws Exception {

    assert state != null;

    final Map<String,FieldDef> pendingFieldDefs = new HashMap<String,FieldDef>();
    final Map<String,String> saveStates = new HashMap<String,String>();

    if (r.hasParam("fields")) {
      r = r.getStruct("fields");

      Set<String> seen = new HashSet<String>();

      // We make two passes.  In the first pass, we do the
      // "real" fields, and second pass does the virtual
      // fields, so that any fields the virtual field
      // references are guaranteed to exist, in a single
      // request (or, from the saved json):
      for(int pass=0;pass<2;pass++) {
        Iterator<Map.Entry<String,Object>> it = r.getParams();
        while(it.hasNext()) {
          Map.Entry<String,Object> ent = it.next();
          String fieldName = ent.getKey();

          if (pass == 1 && seen.contains(fieldName)) {
            continue;
          }

          if (!(ent.getValue() instanceof JSONObject)) {
            r.fail("field \"" + fieldName + "\": expected object containing the field type but got: " + ent.getValue());
          }

          if (pass == 0 && "virtual".equals(((JSONObject) ent.getValue()).get("type"))) {
            // Do this on 2nd pass so the field it refers to will be registered even if it's a single request
            continue;
          }

          if (!IndexState.isSimpleName(fieldName)) {
            r.fail("invalid field name \"" + fieldName + "\": must be [a-zA-Z_][a-zA-Z0-9]*");
          }

          if (fieldName.endsWith("_boost")) {
            r.fail("invalid field name \"" + fieldName + "\": field names cannot end with _boost");
          }

          if (seen.contains(fieldName)) {
            throw new IllegalArgumentException("field \"" + fieldName + "\" appears at least twice in this request");
          }
      
          seen.add(fieldName);

          JSONObject fd = (JSONObject) ent.getValue();

          saveStates.put(fieldName, fd.toString());

          pendingFieldDefs.put(fieldName, parseOneFieldType(r, state, pendingFieldDefs, fieldName, fd));
        }
      }
    }

    return new FinishRequest() {
      @Override
      public String finish() throws IOException {
        for(Map.Entry<String,FieldDef> ent : pendingFieldDefs.entrySet()) {
          // Silly: we need JSONObject.clone...
          JSONObject o;
          try {
            o = (JSONObject) JSONValue.parseStrict(saveStates.get(ent.getKey()));
          } catch (net.minidev.json.parser.ParseException pe) {
            // BUG
            assert false;
            throw new RuntimeException(pe);
          }

          state.addField(ent.getValue(), o);
        }

        return state.getAllFieldsJSON();
      }
    };
  }
}
