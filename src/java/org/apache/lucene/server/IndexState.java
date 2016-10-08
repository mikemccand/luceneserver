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

import java.io.Closeable;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.CharsetDecoder;
import java.nio.charset.CharsetEncoder;
import java.nio.charset.CodingErrorAction;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Phaser;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Pattern;

import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.analysis.AnalyzerWrapper;
import org.apache.lucene.analysis.core.KeywordAnalyzer;
import org.apache.lucene.analysis.util.FilesystemResourceLoader;
import org.apache.lucene.analysis.util.ResourceLoader;
import org.apache.lucene.document.Document;
import org.apache.lucene.expressions.Bindings;
import org.apache.lucene.facet.FacetsConfig;
import org.apache.lucene.facet.taxonomy.CachedOrdinalsReader;
import org.apache.lucene.facet.taxonomy.DocValuesOrdinalsReader;
import org.apache.lucene.facet.taxonomy.OrdinalsReader;
import org.apache.lucene.facet.taxonomy.SearcherTaxonomyManager.SearcherAndTaxonomy;
import org.apache.lucene.facet.taxonomy.SearcherTaxonomyManager;
import org.apache.lucene.facet.taxonomy.directory.DirectoryTaxonomyWriter;
import org.apache.lucene.index.ConcurrentMergeScheduler;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.index.IndexCommit;
import org.apache.lucene.index.IndexFileNames;
import org.apache.lucene.index.IndexOptions;
import org.apache.lucene.index.IndexReader;
import org.apache.lucene.index.IndexWriter;
import org.apache.lucene.index.IndexWriterConfig.OpenMode;
import org.apache.lucene.index.IndexWriterConfig;
import org.apache.lucene.index.IndexableField;
import org.apache.lucene.index.KeepOnlyLastCommitDeletionPolicy;
import org.apache.lucene.index.PersistentSnapshotDeletionPolicy;
import org.apache.lucene.index.SegmentInfos;
import org.apache.lucene.index.SimpleMergedSegmentWarmer;
import org.apache.lucene.index.Term;
import org.apache.lucene.search.ControlledRealTimeReopenThread;
import org.apache.lucene.search.IndexSearcher;
import org.apache.lucene.search.ReferenceManager.RefreshListener;
import org.apache.lucene.search.ReferenceManager;
import org.apache.lucene.search.SearcherFactory;
import org.apache.lucene.search.SearcherLifetimeManager;
import org.apache.lucene.search.Sort;
import org.apache.lucene.search.similarities.BM25Similarity;
import org.apache.lucene.search.similarities.PerFieldSimilarityWrapper;
import org.apache.lucene.search.similarities.Similarity;
import org.apache.lucene.search.suggest.Lookup;
import org.apache.lucene.search.suggest.analyzing.AnalyzingInfixSuggester;
import org.apache.lucene.server.handlers.BuildSuggestHandler;
import org.apache.lucene.server.handlers.LiveSettingsHandler;
import org.apache.lucene.server.handlers.RegisterFieldHandler;
import org.apache.lucene.server.handlers.SettingsHandler;
import org.apache.lucene.server.params.BooleanType;
import org.apache.lucene.server.params.FloatType;
import org.apache.lucene.server.params.IntType;
import org.apache.lucene.server.params.LongType;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.server.params.Type;
import org.apache.lucene.store.Directory;
import org.apache.lucene.store.IndexInput;
import org.apache.lucene.store.IndexOutput;
import org.apache.lucene.store.NRTCachingDirectory;
import org.apache.lucene.store.RAMDirectory;
import org.apache.lucene.util.IOUtils;
import org.apache.lucene.util.PrintStreamInfoStream;
import org.apache.lucene.util.Version;
import org.apache.lucene.util.packed.PackedInts;

import net.minidev.json.JSONObject;
import net.minidev.json.JSONStyleIdent;
import net.minidev.json.JSONValue;
import net.minidev.json.parser.ParseException;

/** Holds all state associated with one index.  On startup
 *  and on creating a new index, the index loads its state
 *  but does not start itself.  At this point, settings can
 *  be changed, and then the index must be {@link #start}ed
 *  before it can be used for indexing and searching, at
 *  which point only live settings may be changed.
 *
 *  Filesystem state: each index has its own rootDir,
 *  specified when the index is created.  Under each
 *  rootDir:
 *  <ul>
 *    <li> {@code index} has the Lucene index
 *    <li> {@code taxonomy} has the taxonomy index (empty if
 *     no facets are indexed)
 *   <li> {@code state} has all current settings
 *   <li> {@code state/state.N} gen files holds all settings
 *   <li> {@code state/saveLoadRefCounts.N} gen files holds
 *     all reference counts from live snapshots
 *  </ul>
 */

public class IndexState implements Closeable {

  /** Name of this index. */
  public final String name;

  /** Creates directories */
  public DirectoryFactory df = DirectoryFactory.get("FSDirectory");

  /** Loads all resources for analysis components */
  public final ResourceLoader resourceLoader;

  /** Where all index state and shards (subdirs) are saved */
  public final Path rootDir;

  /** Optional index time sorting (write once!) or null if no index time sorting */
  private Sort indexSort;

  final GlobalState globalState;

  /** Which norms format to use for all indexed fields. */
  public String normsFormat = "Lucene53";

  /** If normsFormat is Lucene53, what acceptableOverheadRatio to pass. */
  public float normsAcceptableOverheadRatio = PackedInts.FASTEST;

  /** Holds pending save state, written to state.N file on commit. */
  // nocommit move these to their own obj, make it sync'd,
  // instead of syncing on IndexState instance:
  final JSONObject settingsSaveState = new JSONObject();
  final JSONObject liveSettingsSaveState = new JSONObject();
  final JSONObject fieldsSaveState = new JSONObject();
  final JSONObject suggestSaveState = new JSONObject();

  /** The field definitions (registerField) */
  private final Map<String,FieldDef> fields = new ConcurrentHashMap<String,FieldDef>();

  /** Contains fields set as facetIndexFieldName. */
  public final Set<String> internalFacetFieldNames = Collections.newSetFromMap(new ConcurrentHashMap<String,Boolean>());

  public final FacetsConfig facetsConfig = new FacetsConfig();

  /** {@link Bindings} to pass when evaluating expressions. */
  public final Bindings exprBindings = new FieldDefBindings(fields);

  private final Map<Integer,ShardState> shards = new ConcurrentHashMap<>();

  /** Built suggest implementations */
  public final Map<String,Lookup> suggesters = new ConcurrentHashMap<String,Lookup>();

  /** Holds suggest settings loaded but not yet started */
  private JSONObject suggesterSettings;

  /** Tracks snapshot references to generations. */
  private static class SaveLoadRefCounts extends GenFileUtil<Map<Long,Integer>> {

    public SaveLoadRefCounts(Directory dir) {
      super(dir, "stateRefCounts");
    }
    
    @Override
    protected void saveOne(IndexOutput out, Map<Long,Integer> refCounts) throws IOException {
      JSONObject o = new JSONObject();
      for(Map.Entry<Long,Integer> ent : refCounts.entrySet()) {
        o.put(ent.getKey().toString(), ent.getValue());
      }
      byte[] bytes = IndexState.toUTF8(o.toString());
      out.writeBytes(bytes, 0, bytes.length);
    }

    @Override
    protected Map<Long,Integer> loadOne(IndexInput in) throws IOException {
      int numBytes = (int) in.length();
      byte[] bytes = new byte[numBytes];
      in.readBytes(bytes, 0, bytes.length);
      String s = IndexState.fromUTF8(bytes);
      JSONObject o = null;
      try {
        o = (JSONObject) JSONValue.parseStrict(s);
      } catch (ParseException pe) {
        // Change to IOExc so gen logic will fallback:
        throw new IOException("invalid JSON when parsing refCounts", pe);
      }
      Map<Long,Integer> refCounts = new HashMap<Long,Integer>();      
      for(Map.Entry<String,Object> ent : o.entrySet()) {
        refCounts.put(Long.parseLong(ent.getKey()), ((Integer) ent.getValue()).intValue());
      }
      return refCounts;
    }
  }

  private class SaveLoadState extends GenFileUtil<JSONObject> {

    public SaveLoadState(Directory dir) {
      super(dir, "state");
    }
    
    @Override
    protected void saveOne(IndexOutput out, JSONObject state) throws IOException {
      // Pretty print:
      String pretty = state.toJSONString(new JSONStyleIdent());
      byte[] bytes = IndexState.toUTF8(pretty.toString());
      out.writeBytes(bytes, 0, bytes.length);
    }

    @Override
    protected JSONObject loadOne(IndexInput in) throws IOException {
      int numBytes = (int) in.length();
      byte[] bytes = new byte[numBytes];
      in.readBytes(bytes, 0, numBytes);
      String s = IndexState.fromUTF8(bytes);
      JSONObject ret = null;
      try {
        ret = (JSONObject) JSONValue.parseStrict(s);
      } catch (ParseException pe) {
        // Change to IOExc so gen logic will fallback:
        throw new IOException("invalid JSON when parsing refCounts", pe);
      }
      return ret;
    }

    @Override
    protected boolean canDelete(long gen) {
      return !hasRef(gen);
    }
  }

  /** Which snapshots (List&lt;Long&gt;) are referencing which
   *  save state generations. */
  Map<Long,Integer> genRefCounts;
  SaveLoadRefCounts saveLoadGenRefCounts;

  /** Holds all settings, field definitions */
  SaveLoadState saveLoadState;

  /** Per-field wrapper that provides the analyzer
   *  configured in the FieldDef */
  private static final Analyzer keywordAnalyzer = new KeywordAnalyzer();

  /** Index-time analyzer. */
  public final Analyzer indexAnalyzer = new AnalyzerWrapper(Analyzer.PER_FIELD_REUSE_STRATEGY) {
        @Override
        public Analyzer getWrappedAnalyzer(String name) {
          FieldDef fd = getField(name); 
          if (fd.valueType == FieldDef.FieldValueType.ATOM) {
            return keywordAnalyzer;
          }
          if (fd.indexAnalyzer == null) {
            throw new IllegalArgumentException("field \"" + name + "\" did not specify analyzer or indexAnalyzer");
          }
          return fd.indexAnalyzer;
        }

        @Override
        protected TokenStreamComponents wrapComponents(String fieldName, TokenStreamComponents components) {
          return components;
        }
      };

  /** Search-time analyzer. */
  public final Analyzer searchAnalyzer = new AnalyzerWrapper(Analyzer.PER_FIELD_REUSE_STRATEGY) {
        @Override
        public Analyzer getWrappedAnalyzer(String name) {
          FieldDef fd = getField(name);
          if (fd.valueType == FieldDef.FieldValueType.ATOM) {
            return keywordAnalyzer;
          }
          if (fd.searchAnalyzer == null) {
            throw new IllegalArgumentException("field \"" + name + "\" did not specify analyzer or searchAnalyzer");
          }
          return fd.searchAnalyzer;
        }

        @Override
        protected TokenStreamComponents wrapComponents(String fieldName, TokenStreamComponents components) {
          return components;
        }
      };

  /** Per-field wrapper that provides the similarity
   *  configured in the FieldDef */
  final Similarity sim = new PerFieldSimilarityWrapper(new BM25Similarity()) {
      final Similarity defaultSim = new BM25Similarity();

      @Override
      public Similarity get(String name) {
        if (internalFacetFieldNames.contains(name)) {
          return defaultSim;
        }
        return getField(name).sim;
      }
    };

  /** When a search is waiting on a specific generation, we
   *  will wait at most this many seconds before reopening
   *  (default 50 msec). */
  volatile double minRefreshSec = .05f;

  /** When no searcher is waiting on a specific generation, we
   *  will wait at most this many seconds before proactively
   *  reopening (default 1 sec). */
  volatile double maxRefreshSec = 1.0f;

  /** Once a searcher becomes stale (i.e., a new searcher is
   *  opened), we will close it after this much time
   *  (default: 60 seconds).  If this is too small, it means
   *  that old searches returning for a follow-on query may
   *  find their searcher pruned (lease expired). */
  volatile double maxSearcherAgeSec = 60;

  /** RAM buffer size passed to {@link
   *  IndexWriterConfig#setRAMBufferSizeMB}. */
  volatile double indexRAMBufferSizeMB = 16;

  /** True if this is a new index. */
  private final boolean doCreate;

  /** Sole constructor; creates a new index or loads an
   *  existing one if it exists, but does not start the
   *  index. */
  public IndexState(GlobalState globalState, String name, Path rootDir, boolean doCreate) throws IOException {
    this.globalState = globalState;
    this.name = name;
    this.rootDir = rootDir;
    if (rootDir != null) {
      if (Files.exists(rootDir) == false) {
        Files.createDirectories(rootDir);
      }
      this.resourceLoader = new FilesystemResourceLoader(rootDir);
    } else {
      // nocommit can/should we make a DirectoryResourceLoader?
      this.resourceLoader = null;
    }

    this.doCreate = doCreate;

    if (doCreate == false) {
      initSaveLoadState();
    }
  }

  public boolean containsShard(int shardOrd) {
    return shards.containsKey(shardOrd);
  }

  /** Retrieve the field's type.
   *
   *  @throws IllegalArgumentException if the field was not
   *     registered. */
  public FieldDef getField(String fieldName) {
    FieldDef fd = fields.get(fieldName);
    if (fd == null) {
      String message = "field \"" + fieldName + "\" is unknown: it was not registered with registerField";
      throw new IllegalArgumentException(message);
    }
    return fd;
  }

  /** Lookup the value of {@code paramName} in the {@link
   *  Request} and then passes that field name to {@link
   *  #getField(String)}.
   *
   *  @throws IllegalArgumentException if the field was not
   *     registered. */
  public FieldDef getField(Request r, String paramName) {
    String fieldName = r.getString(paramName);
    FieldDef fd = fields.get(fieldName);
    if (fd == null) {
      String message = "field \"" + fieldName + "\" is unknown: it was not registered with registerField";
      r.fail(paramName, message);
    }

    return fd;
  }

  /** Returns all field names that are indexed and analyzed. */
  public List<String> getIndexedAnalyzedFields() {
    List<String> result = new ArrayList<String>();
    for(FieldDef fd : fields.values()) {
      // TODO: should we default to include numeric fields too...?
      if (fd.fieldType != null && fd.fieldType.indexOptions() != IndexOptions.NONE && fd.searchAnalyzer != null) {
        result.add(fd.name);
      }
    }

    return result;
  }

  public Map<String,FieldDef> getAllFields() {
    return Collections.unmodifiableMap(fields);
  }

  /** True if this index has at least one commit. */
  public boolean hasCommit() throws IOException {
    return saveLoadState.getNextWriteGen() != 0;
  }

  IndexWriterConfig getIndexWriterConfig(OpenMode openMode, Directory origIndexDir) throws IOException {
    IndexWriterConfig iwc = new IndexWriterConfig(indexAnalyzer);
    iwc.setOpenMode(openMode);
    if (getBooleanSetting("index.verbose")) {
      iwc.setInfoStream(new PrintStreamInfoStream(System.out));
    }

    if (indexSort != null) {
      iwc.setIndexSort(indexSort);
    }

    iwc.setSimilarity(sim);
    iwc.setRAMBufferSizeMB(indexRAMBufferSizeMB);

    // nocommit in primary case we can't do this?
    iwc.setMergedSegmentWarmer(new SimpleMergedSegmentWarmer(iwc.getInfoStream()));
    
    ConcurrentMergeScheduler cms = (ConcurrentMergeScheduler) iwc.getMergeScheduler();

    if (getBooleanSetting("index.merge.scheduler.auto_throttle")) {
      cms.enableAutoIOThrottle();
    } else {
      cms.disableAutoIOThrottle();
    }

    if (hasSetting("concurrentMergeScheduler.maxMergeCount")) {
      // SettingsHandler verifies this:
      assert hasSetting("concurrentMergeScheduler.maxThreadCount");
      cms.setMaxMergesAndThreads(getIntSetting("concurrentMergeScheduler.maxMergeCount"),
                                 getIntSetting("concurrentMergeScheduler.maxThreadCount"));
    }

    iwc.setIndexDeletionPolicy(new PersistentSnapshotDeletionPolicy(new KeepOnlyLastCommitDeletionPolicy(),
                                                                    origIndexDir,
                                                                    OpenMode.CREATE_OR_APPEND));

    iwc.setCodec(new ServerCodec(this));
    return iwc;
  }

  @Override
  public void close() throws IOException {
    commit();
    List<Closeable> closeables = new ArrayList<>();
    closeables.addAll(shards.values());
    closeables.addAll(fields.values());
    for(Lookup suggester : suggesters.values()) {
      if (suggester instanceof Closeable) {
        closeables.add((Closeable) suggester);
      }
    }
    IOUtils.close(closeables);

    // nocommit should we remove this instance?  if app
    // starts again ... should we re-use the current
    // instance?  seems ... risky?
    // nocommit this is dangerous .. eg Server iterates
    // all IS.indices and closes ...:
    // nocommit need sync:

    globalState.indices.remove(name);
  }

  // nocommit fix snapshot to NOT save settings?

  /** Record that this snapshot id refers to the current generation, returning it. */
  public synchronized long incRefLastCommitGen() throws IOException {
    long nextGen = saveLoadState.getNextWriteGen();
    if (nextGen == 0) {
      throw new IllegalStateException("no commit exists");
    }
    long result = nextGen-1;
    incRef(result);
    return result;
  }

  private synchronized void incRef(long stateGen) throws IOException {
    Integer rc = genRefCounts.get(stateGen);
    if (rc == null) {
      genRefCounts.put(stateGen, 1);
    } else {
      genRefCounts.put(stateGen, 1+rc.intValue());
    }
    saveLoadGenRefCounts.save(genRefCounts);
  }

  /** Drop this snapshot from the references. */
  public synchronized void decRef(long stateGen) throws IOException {
    Integer rc = genRefCounts.get(stateGen);
    if (rc == null) {
      throw new IllegalArgumentException("stateGen=" + stateGen + " is not held by a snapshot");
    }
    assert rc.intValue() > 0;
    if (rc.intValue() == 1) {
      genRefCounts.remove(stateGen);
    } else {
      genRefCounts.put(stateGen, rc.intValue()-1);
    }
    saveLoadGenRefCounts.save(genRefCounts);
  }

  /** True if this generation is still referenced by at
   *  least one snapshot. */
  public synchronized boolean hasRef(long gen) {
    Integer rc = genRefCounts.get(gen);
    if (rc == null) {
      return false;
    } else {
      assert rc.intValue() > 0;
      return true;
    }
  }

  /** Records a new field in the internal {@code fields} state. */
  public synchronized void addField(FieldDef fd, JSONObject json) {
    if (fields.containsKey(fd.name)) {
      throw new IllegalArgumentException("field \"" + fd.name + "\" was already registered");
    }
    fields.put(fd.name, fd);
    assert !fieldsSaveState.containsKey(fd.name);
    fieldsSaveState.put(fd.name, json);
    // nocommit support sorted set dv facets
    if (fd.faceted != null && fd.faceted.equals("no") == false && fd.faceted.equals("numericRange") == false) {
      internalFacetFieldNames.add(facetsConfig.getDimConfig(fd.name).indexFieldName);
    }
  }

  public synchronized boolean hasFacets() {
    return internalFacetFieldNames.isEmpty() == false;
  }

  /** Returns JSON representation of all registered fields. */
  public synchronized String getAllFieldsJSON() {
    return fieldsSaveState.toString();
  }

  /** Returns JSON representation of all settings. */
  public synchronized String getSettingsJSON() {
    return settingsSaveState.toString();
  }

  /** Returns JSON representation of all live settings. */
  public synchronized String getLiveSettingsJSON() {
    return liveSettingsSaveState.toString();
  }

  /** Records a new suggester state. */
  public synchronized void addSuggest(String name, JSONObject o) {
    suggestSaveState.put(name, o);
  }

  public void verifyStarted(Request r) {
    if (isStarted() == false) {
      String message = "index '" + name + "' isn't started; call startIndex first";
      if (r == null) {
        throw new IllegalStateException(message);
      } else {
        r.fail("indexName", message);
      }
    }
  }

  public boolean isStarted() {
    for(ShardState shard : shards.values()) {
      if (shard.isStarted()) {
        return true;
      }
    }
    return false;
  }

  /** Fold in new non-live settings from the incoming request into the stored settings. */
  public synchronized void mergeSimpleSettings(Request r) {
    if (isStarted()) {
      throw new IllegalStateException("index \"" + name + "\" was already started (cannot change non-live settings)");
    }
    StructType topType = r.getType();
    Iterator<Map.Entry<String,Object>> it = r.getParams();
    while (it.hasNext()) {
      Map.Entry<String,Object> ent = it.next();
      String paramName = ent.getKey();
      Param p = topType.params.get(paramName);
      if (p == null) {
        throw new IllegalArgumentException("unrecognized parameter \"" + paramName + "\"");
      }

      Type type = p.type;

      if (type instanceof StringType || type instanceof IntType || type instanceof LongType || type instanceof FloatType || type instanceof BooleanType) {
        Object value = ent.getValue();
        try {
          type.validate(value);
        } catch (IllegalArgumentException iae) {
          r.fail(paramName, iae.toString());
        }
        // TODO: do more stringent validation?  eg
        // nrtCachingDirMaxMergeSizeMB must be >= 0.0
        settingsSaveState.put(paramName, value);
        it.remove();
      } else {
        r.fail(paramName, "unhandled parameter");
      }
    }
  }

  /** Live setting: set the mininum refresh time (seconds), which is the
   *  longest amount of time a client may wait for a
   *  searcher to reopen. */
  public synchronized void setMinRefreshSec(double min) {
    minRefreshSec = min;
    liveSettingsSaveState.put("minRefreshSec", min);
    for(ShardState shardState : shards.values()) {
      shardState.restartReopenThread();
    }
  }

  /** Live setting: set the maximum refresh time (seconds), which is the
   *  amount of time before we reopen the searcher
   *  proactively (when no search client is waiting for a specific index generation). */
  public synchronized void setMaxRefreshSec(double max) {
    maxRefreshSec = max;
    liveSettingsSaveState.put("maxRefreshSec", max);
    for(ShardState shardState : shards.values()) {
      shardState.restartReopenThread();
    }
  }

  /** Live setting: once a searcher becomes stale, we will close it after
   *  this many seconds. */
  public synchronized void setMaxSearcherAgeSec(double d) {
    maxSearcherAgeSec = d;
    liveSettingsSaveState.put("maxSearcherAgeSec", d);
  }

  /** Live setting: how much RAM to use for buffered documents during
   *  indexing (passed to {@link IndexWriterConfig#setRAMBufferSizeMB}. */
  public synchronized void setIndexRAMBufferSizeMB(double d) {
    indexRAMBufferSizeMB = d;
    liveSettingsSaveState.put("indexRAMBufferSizeMB", d);

    // nocommit sync: what if closeIndex is happening in
    // another thread:
    for(ShardState shard : shards.values()) {
      if (shard.writer != null) {
        // Propagate the change to the open IndexWriter
        shard.writer.getConfig().setRAMBufferSizeMB(d);
      } else if (shard.nrtPrimaryNode != null) {
        shard.nrtPrimaryNode.setRAMBufferSizeMB(d);
      }
    }
  }

  /** Record the {@link DirectoryFactory} to use for this
   *  index. */
  public synchronized void setDirectoryFactory(DirectoryFactory df, Object saveState) {
    if (isStarted()) {
      throw new IllegalStateException("index \"" + name + "\": cannot change Directory when the index is running");
    }
    settingsSaveState.put("directory", saveState);
    this.df = df;
  }

  public void setIndexSort(Sort sort, Object saveState) {
    if (isStarted()) {
      throw new IllegalStateException("index \"" + name + "\": cannot change index sort when the index is running");
    }
    if (this.indexSort != null && this.indexSort.equals(sort) == false) {
      throw new IllegalStateException("index \"" + name + "\": cannot change index sort");
    }
    settingsSaveState.put("indexSort", saveState);
    this.indexSort = sort;
  }

  public void start() throws Exception {
    // start all local shards
    for(ShardState shard : shards.values()) {
      shard.start();
    }

    if (suggesterSettings != null) {
      // load suggesters:
      ((BuildSuggestHandler) globalState.getHandler("buildSuggest")).load(this, suggesterSettings);
      suggesterSettings = null;
    }
  }

  public synchronized void rollback() throws IOException {
    for(ShardState shardState: shards.values()) {
      shardState.rollback();
    }

    List<Closeable> closeables = new ArrayList<>();
    for(Lookup suggester : suggesters.values()) {
      if (suggester instanceof Closeable) {
        closeables.add((Closeable) suggester);
      }
    }
    IOUtils.close(closeables);

    globalState.indices.remove(name);
  }

  public void setNormsFormat(String format, float acceptableOverheadRatio) {
    this.normsFormat = format;
    // nocommit not used anymore?
    this.normsAcceptableOverheadRatio = acceptableOverheadRatio;
  }

  /** Get the current save state. */
  public synchronized JSONObject getSaveState() throws IOException {
    JSONObject o = new JSONObject();
    o.put("settings", settingsSaveState);
    o.put("fields", fieldsSaveState);
    o.put("suggest", suggestSaveState);
    return o;
  }

  /** Commit all state and shards. */
  public synchronized long commit() throws IOException {

    if (saveLoadState == null) {
      initSaveLoadState();
    }

    // nocommit this does nothing on replica?  make a failing test!
    long gen = -1;
    for(ShardState shard : shards.values()) {
      gen = shard.commit();
    }

    for(Lookup suggester : suggesters.values()) {
      if (suggester instanceof AnalyzingInfixSuggester) {       
        ((AnalyzingInfixSuggester) suggester).commit();
      }
    }

    // nocommit needs test case that creates index, changes
    // some settings, closes it w/o ever starting it:
    // settings changes are lost then?

    JSONObject saveState = new JSONObject();
    saveState.put("state", getSaveState());
    saveLoadState.save(saveState);

    return gen;
  }

  /** Load all previously saved state. */
  public synchronized void load(JSONObject o) throws IOException {

    // To load, we invoke each handler from the save state,
    // as if the app had just done so from a fresh index,
    // except for suggesters which uses a dedicated load
    // method:

    try {

      // Do fields first, because indexSort could reference fields:
      
      // Field defs:
      JSONObject fieldsState = (JSONObject) o.get("fields");
      JSONObject top = new JSONObject();
      top.put("fields", fieldsState);
      Request r = new Request(null, null, top, RegisterFieldHandler.TYPE);
      FinishRequest fr = ((RegisterFieldHandler) globalState.getHandler("registerFields")).handle(this, r, null);
      assert !Request.anythingLeft(top): top;
      fr.finish();

      // Global settings:
      JSONObject settingsState = (JSONObject) o.get("settings");
      //System.out.println("load: state=" + o);
      r = new Request(null, null, settingsState, SettingsHandler.TYPE);
      fr = ((SettingsHandler) globalState.getHandler("settings")).handle(this, r, null);
      fr.finish();
      assert !Request.anythingLeft(settingsState): settingsState.toString();

      // nocommit shouldn't this be "liveSettings" or something?
      JSONObject liveSettingsState = (JSONObject) o.get("settings");
      r = new Request(null, null, liveSettingsState, LiveSettingsHandler.TYPE);
      fr = ((LiveSettingsHandler) globalState.getHandler("liveSettings")).handle(this, r, null);
      fr.finish();
      assert !Request.anythingLeft(liveSettingsState): liveSettingsState.toString();

      // do not init suggesters here: they can take non-trivial heap, and they need Directory to be created
      suggesterSettings = (JSONObject) o.get("suggest");
        
    } catch (Exception e) {
      throw new IOException(e);
    }
  }

  synchronized double getDoubleSetting(String name) {
    Object o = settingsSaveState.get(name);
    if (o == null) {
      Param p = SettingsHandler.TYPE.params.get(name);
      assert p != null;
      o = p.defaultValue;
    }
    return ((Number) o).doubleValue();
  }

  synchronized boolean hasSetting(String name) {
    return settingsSaveState.containsKey(name);
  }

  synchronized int getIntSetting(String name) {
    Object o = settingsSaveState.get(name);
    if (o == null) {
      Param p = SettingsHandler.TYPE.params.get(name);
      assert p != null;
      o = p.defaultValue;
    }
    return ((Number) o).intValue();
  }

  synchronized boolean getBooleanSetting(String name) {
    Object o = settingsSaveState.get(name);
    if (o == null) {
      Param p = SettingsHandler.TYPE.params.get(name);
      assert p != null;
      o = p.defaultValue;
    }
    return (Boolean) o;
  }

  void initSaveLoadState() throws IOException {
    Path stateDirFile;
    if (rootDir != null) {
      stateDirFile = rootDir.resolve("state");
      //if (!stateDirFile.exists()) {
      //stateDirFile.mkdirs();
      //}
    } else {
      stateDirFile = null;
    }

    // nocommit who closes this?
    // nocommit can't this be in the rootDir directly?
    Directory stateDir = df.open(stateDirFile);

    saveLoadGenRefCounts = new SaveLoadRefCounts(stateDir);

    // Snapshot ref counts:
    genRefCounts = saveLoadGenRefCounts.load();
    if (genRefCounts == null) {
      genRefCounts = new HashMap<Long,Integer>();
    }

    saveLoadState = new SaveLoadState(stateDir);

    JSONObject priorState = saveLoadState.load();
    if (priorState != null) {
      load((JSONObject) priorState.get("state"));
    }
  }

  /** String -&gt; UTF8 byte[]. */
  public static byte[] toUTF8(String s) {
    CharsetEncoder encoder = Charset.forName("UTF-8").newEncoder();
    // Make sure we catch any invalid UTF16:
    encoder.onMalformedInput(CodingErrorAction.REPORT);
    encoder.onUnmappableCharacter(CodingErrorAction.REPORT);
    try {
      ByteBuffer bb = encoder.encode(CharBuffer.wrap(s));
      byte[] bytes = new byte[bb.limit()];
      bb.position(0);
      bb.get(bytes, 0, bytes.length);
      return bytes;
    } catch (CharacterCodingException cce) {
      throw new IllegalArgumentException(cce);
    }
  }

  /** UTF8 byte[] -&gt; String. */
  public static String fromUTF8(byte[] bytes) {
    CharsetDecoder decoder = Charset.forName("UTF-8").newDecoder();
    // Make sure we catch any invalid UTF8:
    decoder.onMalformedInput(CodingErrorAction.REPORT);
    decoder.onUnmappableCharacter(CodingErrorAction.REPORT);
    try {
      return decoder.decode(ByteBuffer.wrap(bytes)).toString();
    } catch (CharacterCodingException cce) {
      throw new IllegalArgumentException(cce);
    }
  }

  /** UTF8 byte[], offset, length -&gt; char[]. */
  public static char[] utf8ToCharArray(byte[] bytes, int offset, int length) {
    CharsetDecoder decoder = Charset.forName("UTF-8").newDecoder();
    // Make sure we catch any invalid UTF8:
    decoder.onMalformedInput(CodingErrorAction.REPORT);
    decoder.onUnmappableCharacter(CodingErrorAction.REPORT);
    CharBuffer buffer;
    try {
      buffer = decoder.decode(ByteBuffer.wrap(bytes, offset, length));
    } catch (CharacterCodingException cce) {
      throw new IllegalArgumentException(cce);
    }
    char[] arr = new char[buffer.remaining()];
    buffer.get(arr);
    return arr;
  }

  private final static Pattern reSimpleName = Pattern.compile("^[a-zA-Z_][a-zA-Z_0-9]*$");

  /** Verifies this name doesn't use any "exotic"
   *  characters. */
  public static boolean isSimpleName(String name) {
    return reSimpleName.matcher(name).matches();
  }

  /** Find the most recent generation in the directory for this prefix. */
  public static long getLastGen(Path dir, String prefix) throws IOException {
    assert isSimpleName(prefix);
    prefix += '.';
    long lastGen = -1;
    if (Files.exists(dir)) {
      try (DirectoryStream<Path> stream = Files.newDirectoryStream(dir)) {
        for (Path subFile : stream) {
          String name = subFile.getFileName().toString();
          if (name.startsWith(prefix)) {
            lastGen = Math.max(lastGen, Long.parseLong(name.substring(prefix.length())));
          }
        }
      }
    }

    return lastGen;
  }

  /** Holds metadata for one snapshot, including its id, and
   *  the index, taxonomy and state generations. */
  public static class Gens {

    /** Index generation. */
    public final long indexGen;

    /** Taxonomy index generation. */
    public final long taxoGen;

    /** State generation. */
    public final long stateGen;

    /** Snapshot id. */
    public final String id;

    /** Sole constructor. */
    public Gens(Request r, String param) {
      id = r.getString(param);
      final String[] gens = id.split(":");
      if (gens.length != 3) {
        r.fail(param, "invalid snapshot id \"" + id + "\": must be format N:M:O");
      }
      long indexGen1 = -1;
      long taxoGen1 = -1;
      long stateGen1 = -1;
      try {
        indexGen1 = Long.parseLong(gens[0]);
        taxoGen1 = Long.parseLong(gens[1]);
        stateGen1 = Long.parseLong(gens[2]);
      } catch (Exception e) {
        r.fail(param, "invalid snapshot id \"" + id + "\": must be format N:M:O");
      }      
      indexGen = indexGen1;
      taxoGen = taxoGen1;
      stateGen = stateGen1;
    }
  }

  public ShardState addShard(int shardOrd, boolean doCreate) {
    if (shards.containsKey(shardOrd)) {
      throw new IllegalArgumentException("shardOrd=" + shardOrd + " already exists in index + \"" + name + "\"");
    }
    ShardState shard = new ShardState(this, shardOrd, doCreate);
    shards.put(shardOrd, shard);
    return shard;
  }

  public ShardState getShard(int shardOrd) {
    ShardState shardState = shards.get(shardOrd);
    if (shardState == null) {
      throw new IllegalArgumentException("shardOrd=" + shardOrd + " does not exist in index \"" + name + "\"");
    }
    return shardState;
  }

  public void deleteIndex() throws IOException {
    for(ShardState shardState : shards.values()) {
      shardState.deleteShard();
    }
    globalState.deleteIndex(name);
  }
}
