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
import java.io.InputStream;
import java.lang.reflect.Constructor;
import java.net.InetSocketAddress;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.SeekableByteChannel;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.Callable;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.Semaphore;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

import org.apache.lucene.facet.taxonomy.SearcherTaxonomyManager.SearcherAndTaxonomy;
import org.apache.lucene.index.Term;
import org.apache.lucene.search.MatchAllDocsQuery;
import org.apache.lucene.search.ScoreDoc;
import org.apache.lucene.search.TermQuery;
import org.apache.lucene.search.TimeLimitingCollector;
import org.apache.lucene.search.TopDocs;
import org.apache.lucene.server.handlers.DocHandler;
import org.apache.lucene.server.handlers.Handler;
import org.apache.lucene.server.handlers.NodeToNodeHandler;
import org.apache.lucene.server.handlers.Search2Handler;
import org.apache.lucene.server.plugins.Plugin;
import org.apache.lucene.util.IOUtils;
import org.apache.lucene.util.NamedThreadFactory;
import org.apache.lucene.util.StringHelper;

import net.minidev.json.JSONObject;
import net.minidev.json.JSONValue;
import net.minidev.json.parser.ParseException;

/** Holds all global state for the server.  Per-index state
 *  is held in {@link IndexState}.
 *
 * <p> Filesystem state ($stateDir is the "global state
 * dir", passed to GlobalState on init):
 *
 * <ul>
 *   <li> $stateDir/indices.gen: holds map of indexName to
 *     root filesystem path for that index
 *   <li> $stateDir/plugins: a directory with one
 *     sub-directory per plugin
 * </ul>
 *
 * Each plugin sub-directory ($stateDir/plugins/foo/)
 * defines one plugin, and contains:
 * <ul>
 *   <li> lucene-server-plugin.properties:
 *     file with the properties for plugin {@code foo};
 *     alternatively, the properties file can be inside a
 *     *.zip or *.jar in the plugin directory.  This must
 *     define the property "class" with the fully qualified
 *     path to the Plugin class to instantiate
 *   <li> $stateDir/plugins/foo/lib/*: optional, contains
 *     *.jar to add to the classpath while loading the
 *     plugin
 *   <li> $stateDir/plugins/*.zip or *.jar contains the
 *     plugins class files and optionally the properties
 *     file
 * </ul>

 * Each index has its own indexDir, specified when the index
 * is created; see {@link IndexState} for details. */
public class GlobalState implements Closeable {

  private static final String PLUGIN_PROPERTIES_FILE = "lucene-server-plugin.properties";

  // TODO: make these controllable
  // nocommit allow controlling per CSV/json bulk import max concurrency sent into IW?
  private final static int MAX_INDEXING_THREADS = Runtime.getRuntime().availableProcessors();

  final DocHandler docHandler = new DocHandler();

  private final Map<String,Handler> handlers = new HashMap<String,Handler>();

  private final Map<String,Plugin> plugins = new HashMap<String,Plugin>();

  private final static int MAX_BUFFERED_ITEMS = Math.max(100, 2*MAX_INDEXING_THREADS);

  public final SearchQueue searchQueue;

  public final Semaphore indexingJobsRunning = new Semaphore(MAX_BUFFERED_ITEMS);

  // Seems to be substantially faster than ArrayBlockingQueue at high throughput:  
  final BlockingQueue<Runnable> docsToIndex = new LinkedBlockingQueue<Runnable>(MAX_BUFFERED_ITEMS);

  /** Common thread pool to index document chunks. */
  private final ExecutorService indexService = new ThreadPoolExecutor(MAX_INDEXING_THREADS,
                                                                      MAX_INDEXING_THREADS,
                                                                      60, TimeUnit.SECONDS,
                                                                      docsToIndex,
                                                                      new NamedThreadFactory("LuceneIndexing"));
  /** Server shuts down once this latch is decremented. */
  public final CountDownLatch shutdownNow = new CountDownLatch(1);

  /** Current indices. */
  final Map<String,IndexState> indices = new ConcurrentHashMap<String,IndexState>();

  final Path stateDir;

  // nocommit make this a thread pool :)
  final Thread searchThread = new Thread() {
      @Override
      public void run() {
        try {
          _run();
        } catch (Exception e) {
          // nocommit this kills our one and only search thread ;)
          throw new RuntimeException(e);
        }
      }

      private void _run() throws Exception {
        Search2Handler searchHandler = (Search2Handler) getHandler("search2");
        assert searchHandler != null;
        
        while (true) {
          SearchQueue.QueryAndID query;
          try {
            query = searchQueue.takeNextQuery();
          } catch (RuntimeException re) {
            if (re.getCause() instanceof InterruptedException) {
              break;
            } else { 
              throw re;
            }
          }
          //System.out.println("N" + StringHelper.idToString(nodeID) + ": run query Q" + query.id);

          IndexState indexState = getIndex(query.indexName);
          ShardState shardState = indexState.getShard(query.shardOrd);
          SearcherAndTaxonomy searcher = shardState.acquire();
          shardState.slm.record(searcher.searcher);
          System.out.println("searcher for " + shardState);
          TopDocs hits;
          try {
            hits = searcher.searcher.search(new MatchAllDocsQuery(), 10);
          } finally {
            shardState.release(searcher);
          }

          if (Arrays.equals(query.returnNodeID, nodeID)) {
            // We are the coordinating node for this query
            searchHandler.deliverHits(query.id, hits);
          } else {

            RemoteNodeConnection node = getNodeLink(query.returnNodeID);
          
            synchronized(node.c) {
              node.c.out.writeByte(NodeToNodeHandler.CMD_RECEIVE_HITS);
              node.c.out.writeBytes(query.id.id, 0, query.id.id.length);
              node.c.out.writeInt(hits.totalHits);
              node.c.out.writeInt(hits.scoreDocs.length);
              for(ScoreDoc hit : hits.scoreDocs) {
                node.c.out.writeInt(hit.doc);
                node.c.out.writeInt(Float.floatToIntBits(hit.score));
              }
              node.c.flush();
            }
          }
        }
      }
    };

  // nocommit why not just ls the root dir?

  /** This is persisted so on restart we know about all previously created indices. */
  private final JSONObject indexNames = new JSONObject();
  
  private long lastIndicesGen;

  /** The externally accessible host/port we are bound to; set by the server */
  public InetSocketAddress localAddress;

  /** The host/port we are bound to for binary communications; set by the server */
  public InetSocketAddress localBinaryAddress;

  public final String nodeName;

  public final List<RemoteNodeConnection> remoteNodes = new CopyOnWriteArrayList<>();

  public final byte[] nodeID = StringHelper.randomId();

  /** Sole constructor. */
  public GlobalState(String nodeName, Path stateDir) throws IOException {
    System.out.println("MAX INDEXING THREADS " + MAX_INDEXING_THREADS);
    this.nodeName = nodeName;
    this.stateDir = stateDir;
    if (Files.exists(stateDir) == false) {
      Files.createDirectories(stateDir);
    }
    searchQueue = new SearchQueue(this);
  }

  public synchronized void addNodeLink(byte[] nodeID, Connection c) {
    remoteNodes.add(new RemoteNodeConnection(nodeID, c));
  }

  public synchronized RemoteNodeConnection getNodeLink(byte[] nodeID) {
    // nocommit hashmap instead
    for(RemoteNodeConnection node : remoteNodes) {
      if (Arrays.equals(nodeID, node.nodeID)) {
        return node;
      }
    }
    return null;
  }

  public void submitIndexingTask(Runnable job) throws InterruptedException {
    indexingJobsRunning.acquire();
    indexService.submit(job);
  }

  public void submitIndexingTask(Callable job) throws InterruptedException {
    indexingJobsRunning.acquire();
    indexService.submit(job);
  }

  /** Record a new handler, by methode name (search,
   *  addDocument, etc.).  The server registers all builtin
   *  handlers on startup, but plugins can also register
   *  their own handlers when they are instantiated. */
  public void addHandler(String name, Handler handler) {
    if (handlers.containsKey(name)) {
      throw new IllegalArgumentException("handler \"" + name + "\" is already defined");
    }
    handlers.put(name, handler);
  }

  /** Retrieve a handler by method name (search,
   *  addDocument, etc.). */
  public Handler getHandler(String name) {
    Handler h = handlers.get(name);
    if (h == null) {
      throw new IllegalArgumentException("handler \"" + name + "\" is not defined");
    }
    return h;
  }

  /** Get all handlers. */
  public Map<String,Handler> getHandlers() {
    return Collections.unmodifiableMap(handlers);
  }

  /** Get the {@link IndexState} by index name. */
  public IndexState getIndex(String name) throws IOException {
    synchronized(indices) {
      IndexState state = indices.get(name);
      if (state == null) {
        String rootPath = (String) indexNames.get(name);
        if (rootPath != null) {
          if (rootPath.equals("NULL")) {
            state = new IndexState(this, name, null, false);
          } else {
            state = new IndexState(this, name, Paths.get(rootPath), false);
          }
          // nocommit we need to also persist which shards are here?
          state.addShard(0, false);
          indices.put(name, state);
        } else {
          throw new IllegalArgumentException("index \"" + name + "\" was not yet created");
        }
      }
      return state;
    }
  }

  public boolean hasIndex(String name, int shardOrd) {
    // nocommit what if it's deleted right now?
    IndexState indexState = indices.get(name);
    if (indexState != null) {
      return indexState.containsShard(shardOrd);
    } else {
      return false;
    }
  }

  /** Remove the specified index. */
  public void deleteIndex(String name) {
    synchronized(indices) {
      indexNames.remove(name);
    }
  }

  /** Create a new index. */
  public IndexState createIndex(String name, Path rootDir) throws Exception {
    synchronized (indices) {
      if (indexNames.containsKey(name)) {
        throw new IllegalArgumentException("index \"" + name + "\" already exists");
      }
      if (rootDir == null) {
        indexNames.put(name, "NULL");
      } else {
        if (Files.exists(rootDir)) {
          throw new IllegalArgumentException("rootDir \"" + rootDir + "\" already exists");
        }
        indexNames.put(name, rootDir.toAbsolutePath().toString());
      }
      saveIndexNames();
      IndexState state = new IndexState(this, name, rootDir, true);
      indices.put(name, state);
      return state;
    }
  }

  void removeIndex(String name) {
    synchronized(indices) {
      indices.remove(name);
    }
  }

  void loadIndexNames() throws IOException {
    long gen = IndexState.getLastGen(stateDir, "indices");
    lastIndicesGen = gen;
    if (gen != -1) {
      Path path = stateDir.resolve("indices." + gen);
      byte[] bytes;
      try (SeekableByteChannel channel = Files.newByteChannel(path, StandardOpenOption.READ)) {
        bytes = new byte[(int) channel.size()];
        ByteBuffer buffer = ByteBuffer.wrap(bytes);
        int count = channel.read(buffer);
        if (count != bytes.length) {
          throw new AssertionError("fix me!");
        }
      }
      JSONObject o;
      try {
        o = (JSONObject) JSONValue.parseStrict(IndexState.fromUTF8(bytes));
      } catch (ParseException pe) {
        // Something corrupted the save state since we last
        // saved it ...
        throw new RuntimeException("index state file \"" + path + "\" cannot be parsed: " + pe.getMessage());
      }
      indexNames.putAll(o);
    }
  }

  private void saveIndexNames() throws IOException {
    synchronized(indices) {
      lastIndicesGen++;
      byte[] bytes = IndexState.toUTF8(indexNames.toString());
      Path f = stateDir.resolve("indices." + lastIndicesGen);
      try (FileChannel channel = FileChannel.open(f, StandardOpenOption.WRITE, StandardOpenOption.CREATE_NEW)) {
        int count = channel.write(ByteBuffer.wrap(bytes));
        if (count != bytes.length) {
          throw new AssertionError("fix me");
        }
        channel.force(true);
      }

      // remove old gens
      try (DirectoryStream<Path> stream = Files.newDirectoryStream(stateDir)) {
        for (Path sub : stream) {
          if (sub.toString().startsWith("indices.")) {
            long gen = Long.parseLong(sub.toString().substring(8));
            if (gen != lastIndicesGen) {
              Files.delete(sub);
            }
          }
        }
      }
    }
  }

  @Override
  public void close() throws IOException {
    //System.out.println("GlobalState.close: indices=" + indices);
    searchThread.interrupt();
    IOUtils.close(remoteNodes);
    IOUtils.close(indices.values());
    indexService.shutdown();
    TimeLimitingCollector.getGlobalTimerThread().stopTimer();
    try {
      TimeLimitingCollector.getGlobalTimerThread().join();
    } catch (InterruptedException ie) {
      throw new RuntimeException(ie);
    }
  }

  /** Load any plugins. */
  @SuppressWarnings({"unchecked"})
  public void loadPlugins() throws Exception {
    Path pluginsDir = stateDir.resolve("plugins");
    
    if (Files.exists(pluginsDir)) {

      if (Files.isDirectory(pluginsDir) == false) {
        throw new IllegalStateException("\"" + pluginsDir.toAbsolutePath() + "\" is not a directory");
      }

      List<Path> files = new ArrayList<>();
      try (DirectoryStream<Path> stream = Files.newDirectoryStream(pluginsDir)) {
        for (Path sub : stream) {
          files.add(sub);
        }
      }

      // First, add all plugin resources onto classpath:
      for(Path pluginDir : files) {
        if (Files.isDirectory(pluginDir)) {

          // nocommit fixme correctly
          if (pluginDir.getFileName().toString().startsWith("extra")) {
            continue;
          }

          List<Path> pluginFiles = new ArrayList<>();
          try (DirectoryStream<Path> stream = Files.newDirectoryStream(pluginDir)) {
            for (Path sub : stream) {
              pluginFiles.add(sub);
            }
          }
          
          // Verify the plugin contains
          // PLUGIN_PROPERTIES_FILE:
          Path propFile = pluginDir.resolve(PLUGIN_PROPERTIES_FILE);

          if (Files.exists(propFile) == false) {
            throw new IllegalStateException("plugin \"" + pluginDir + "\" is missing the " + PLUGIN_PROPERTIES_FILE + " file");
          }

          System.out.println("Start plugin " + pluginDir.toAbsolutePath());

          // read plugin properties
          Properties pluginProps = new Properties();
          try (InputStream is = Files.newInputStream(propFile)) {
            pluginProps.load(is);
          }
          
          String pluginClassName = pluginProps.getProperty("class");
          if (pluginClassName == null) {
            throw new IllegalStateException("property file \"" + pluginDir + "\" does not have the \"class\" property");
          }
          
          List<URL> urls = new ArrayList<>();

          // Add any .jar/.zip in the plugin's root directory:
          for(Path pluginFile : pluginFiles) {
            if (pluginFile.toString().endsWith(".jar") || 
                pluginFile.toString().endsWith(".zip")) {
              urls.add(pluginFile.toUri().toURL());
            }
          }

          // Add any .jar files in the plugin's lib sub
          // directory, if it exists:
          Path pluginLibDir = pluginDir.resolve("lib");
          if (Files.exists(pluginLibDir)) {
            List<Path> pluginLibFiles = new ArrayList<>();
            try (DirectoryStream<Path> stream = Files.newDirectoryStream(pluginLibDir)) {
              for (Path sub : stream) {
                pluginLibFiles.add(sub);
              }
            }
            
            for(Path pluginFile : pluginLibFiles) {
              if (pluginFile.toString().endsWith(".jar")) {
                urls.add(pluginFile.toUri().toURL());
              }
            }
          }
          
          // make a new classloader with the Urls
          ClassLoader loader = URLClassLoader.newInstance(urls.toArray(new URL[0]));
          Class<? extends Plugin> pluginClass = (Class<? extends Plugin>) loader.loadClass(pluginClassName);
          Constructor<? extends Plugin> ctor;
          try {
            ctor = pluginClass.getConstructor(GlobalState.class);
          } catch (NoSuchMethodException e1) {
            throw new IllegalStateException("class \"" + pluginClassName + "\" for plugin \"" + pluginDir + "\" does not have constructor that takes GlobalState");
          }

          Plugin plugin;
          try {
            plugin = ctor.newInstance(this);
          } catch (Exception e) {
            throw new IllegalStateException("failed to instantiate class \"" + pluginClassName + "\" for plugin \"" + pluginDir, e);
          }
          if (plugins.containsKey(plugin.getName())) {
            throw new IllegalStateException("plugin \"" + plugin.getName() + "\" appears more than once");
          }
          // nocommit verify plugin name matches subdir directory name
          plugins.put(plugin.getName(), plugin);
        }
      }
    }
  }
}
