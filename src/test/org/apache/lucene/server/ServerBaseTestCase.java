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

import java.io.BufferedOutputStream;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Enumeration;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

import org.apache.lucene.util.LuceneTestCase;
import org.junit.AfterClass;
import org.junit.BeforeClass;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;
import net.minidev.json.JSONStyleIdent;
import net.minidev.json.JSONValue;
import net.minidev.json.parser.ContainerFactory;
import net.minidev.json.parser.JSONParser;
import net.minidev.json.parser.ParseException;

public abstract class ServerBaseTestCase extends LuceneTestCase {

  /** The one currently running server */
  protected static RunServer server;

  /** Current index name; we auto-insert this to outgoing
   *  commands that need it. */

  protected static boolean useDefaultIndex = true;
  
  protected static Path STATE_DIR;

  /** We record the last indexGen we saw return from the
   *  server, and then insert that for search command if no
   *  searcher is already specified.  This avoids a common
   *  test bug of forgetting to specify which indexGen to
   *  search. */
  // nocommit make private again
  static long lastIndexGen = -1;

  @BeforeClass
  public static void beforeClassServerBase() throws Exception {
    Path dir = createTempDir("ServerBase");
    STATE_DIR = dir.resolve("state");
  }
  
  @AfterClass
  public static void afterClassServerBase() throws Exception {
    // who sets this? netty? what a piece of crap
    //System.clearProperty("sun.nio.ch.bugLevel");
    STATE_DIR = null;
  }

  @Override
  public void setUp() throws Exception {
    super.setUp();
    if (server != null) {
      server.lastIndexGen = -1;
      if (useDefaultIndex) {
        server.curIndexName = "index";

        // Some tests bounce the server, so we need to restart
        // the default "index" index for those tests that expect
        // it to be running, if it isn't already:
        if (getString(send("indexStatus"), "status").equals("stopped")) {
          send("startIndex");
        }
      }
    }
  }

  protected long addDocument(String json) throws Exception {
    JSONObject o = send("addDocument", json);
    return ((Number) o.get("indexGen")).longValue();
  }

  protected JSONObject parseJSONObject(String s) throws Exception {
    Object o = new JSONParser(JSONParser.MODE_STRICTEST).parse(s, ContainerFactory.FACTORY_SIMPLE);
    if (o instanceof JSONObject == false) {
      throw new IllegalArgumentException("string is not a JSON struct { .. }");
    }
    return (JSONObject) o;
  }

  protected static void installPlugin(Path sourceFile) throws IOException {
    ZipFile zipFile = new ZipFile(sourceFile.toFile());
    
    Enumeration<? extends ZipEntry> entries = zipFile.entries();

    Path pluginsDir = STATE_DIR.resolve("plugins");
    if (Files.exists(pluginsDir) == false) {
      Files.createDirectories(pluginsDir);
    }

    while (entries.hasMoreElements()) {
      ZipEntry entry = entries.nextElement();
      
      InputStream in = zipFile.getInputStream(entry);
      Path targetFile = pluginsDir.resolve(entry.getName());
      if (entry.isDirectory()) {
        // allow unzipping with directory structure
        Files.createDirectories(targetFile);
      } else {
        Files.createDirectories(targetFile.getParent());
        // nocommit switch to nio2
        OutputStream out = new BufferedOutputStream(new FileOutputStream(targetFile.toFile()));
        
        byte[] buffer = new byte[8192];
        int len;
        while((len = in.read(buffer)) >= 0) {
          out.write(buffer, 0, len);
        }
        
        in.close();
        out.close();
      }
    }
    
    zipFile.close();
  }

  protected static void put(JSONObject o, String key, String value) throws ParseException {
    o.put(key, JSONValue.parseWithException(value));
  }
    
  protected static void startServer() throws Exception {
    server = new RunServer(new Random(random().nextLong()), "test", STATE_DIR);
  }

  protected static void createAndStartIndex(String indexName) throws Exception {
    createIndex(indexName);
    if (VERBOSE) {
      send("settings", "{indexName: " + indexName + ", index.verbose: true}");
    }
    send("startIndex", "{indexName: " + indexName + "}");
  }

  protected static void stopIndex(String indexName) throws Exception {
    send("stopIndex", "{indexName: " + indexName + "}");
  }

  protected static void stopIndex() throws Exception {
    stopIndex(server.curIndexName);
  }

  protected static void deleteIndex(String indexName) throws Exception {
    send("deleteIndex", "{indexName: " + indexName + "}");
  }

  private static AtomicInteger indexUpto = new AtomicInteger();

  protected static void createIndex() throws Exception {
    createIndex("index" + indexUpto.getAndIncrement());
  }

  protected static void createAndStartIndex() throws Exception {
    createIndex();
    send("startIndex", "{indexName: " + server.curIndexName + "}");
  }

  protected static void createIndex(String indexName) throws Exception {
    server.curIndexPath = createTempDir(indexName);
    rmDir(server.curIndexPath);
    send("createIndex", "{indexName: " + indexName + ", rootDir: " + server.curIndexPath.toAbsolutePath() + "}");
    // Wait at most 1 msec for a searcher to reopen; this
    // value is too low for a production site but for
    // testing we want to minimize sleep time:
    send("liveSettings", "{indexName: " + indexName + ", minRefreshSec: 0.001}");
    server.curIndexName = indexName;
  }

  protected static byte[] toUTF8(String s) {
    return s.getBytes(StandardCharsets.UTF_8);
  }

  protected static void shutdownServer() throws Exception {
    if (server == null) {
      throw new IllegalStateException("server was not started");
    }
    server.shutdown();
    server = null;
  }

  protected static void bounceServer() throws Exception {
    String curIndexName = server.curIndexName;
    Path curIndexPath = server.curIndexPath;
    shutdownServer();
    startServer();
    server.curIndexPath = curIndexPath;
    server.curIndexName = curIndexName;
  }

  protected static void deleteAllDocs() throws Exception {
    if (VERBOSE) {
      System.out.println("TEST: deleteAllDocs");
    }
    send("deleteAllDocuments", "{indexName: " + server.curIndexName + "}");
  }

  protected static void commit() throws Exception {
    send("commit", "{indexName: " + server.curIndexName + "}");
  }

  protected static void refresh() throws Exception {
    send("refresh", "{indexName: " + server.curIndexName + "}");
  }

  /** Send a no-args command, or a command taking just
   *  indexName which is automatically added (e.g., commit,
   *  closeIndex, startIndex). */
  protected static JSONObject send(String command) throws Exception {
    return server.send(command);
  }

  protected static JSONObject send(String command, String args) throws Exception {
    return server.send(command, args);
  }
  
  private static JSONObject _send(String command, String args) throws Exception {
    return server._send(command, args);
  }

  protected static JSONObject send(String command, JSONObject args) throws Exception {
    return server.send(command, args);
  }

  protected static JSONObject sendRaw(String command, String body) throws Exception {
    return server.sendRaw(command, body);
  }

  protected static void assertContains(String message, String fragment) throws Exception {
    if (message.contains(fragment) == false) {
      throw new AssertionError("fragment=\"" + fragment + "\" is not contained in message:\n" + message);
    }
  }

  protected static void copyFile(Path source, Path dest) throws IOException {
    InputStream is = null;
    OutputStream os = null;
    try {
      is = new FileInputStream(source.toFile());
      os = new FileOutputStream(dest.toFile());
      byte[] buffer = new byte[1024];
      int length;
      while ((length = is.read(buffer)) > 0) {
        os.write(buffer, 0, length);
      }
    } finally {
      is.close();
      os.close();
    }
  }

  protected String prettyPrint(JSONObject o) throws Exception {
    return o.toJSONString(new JSONStyleIdent());
  }

  protected static String httpLoad(String path) throws Exception {
    return server.httpLoad(path);
  }

  protected static JSONObject send(String command, Map<String,Object> params, Reader body) throws Exception {
    return server.send(command, params, body);
  }
  
  /** Simple xpath-like utility method to jump down and grab
   *  something out of the JSON response. */
  protected static Object get(Object o, String path) {
    int upto = 0;
    int tokStart = 0;
    boolean inArrayIndex = false;
    while(upto < path.length()) {       
      char ch = path.charAt(upto++);
      if (inArrayIndex) {
        if (ch == ']') {
          int index = Integer.parseInt(path.substring(tokStart, upto-1));
          o = ((JSONArray) o).get(index);
          inArrayIndex = false;
          tokStart = upto;
        }
      } else if (ch == '.' || ch == '[') {
        String name = path.substring(tokStart, upto-1);
        if (name.length() != 0) {
          o = ((JSONObject) o).get(name);
          if (o == null) {
            // Likely a test bug: try to help out:
            if (tokStart == 0) {
              throw new IllegalArgumentException("JSONObject does not have member " + name);
            } else {
              throw new IllegalArgumentException("path " + path.substring(0, tokStart-1) + " does not have member ." + name);
            }
          }
        }
        tokStart = upto;
        if (ch == '[') {
          inArrayIndex = true;
        }
      }
    }

    String name = path.substring(tokStart, upto);
    if (name.length() > 0) {
      if (o instanceof JSONArray && name.equals("length")) {
        o = new Integer(((JSONArray) o).size());
      } else {
        o = ((JSONObject) o).get(name);
        if (o == null) {
          // Likely a test bug: try to help out:
          throw new IllegalArgumentException("path " + path.substring(0, tokStart) + " does not have member ." + name);
        }
      }
    }
    return o;
  }

  protected boolean hasParam(Object o, String path) {
    try {
      get(o, path);
      return true;
    } catch (IllegalArgumentException iae) {
      return false;
    }
  }

  protected boolean hasParam(String path) {
    return hasParam(server.lastResult, path);
  }

  protected static String getString(Object o, String path) {
    return (String) get(o, path);
  }

  protected static String getString(String path) {
    return getString(server.lastResult, path);
  }

  protected static int getInt(Object o, String path) {
    return ((Number) get(o, path)).intValue();
  }

  protected static int getInt(String path) {
    return getInt(server.lastResult, path);
  }

  protected static boolean getBoolean(Object o, String path) {
    return ((Boolean) get(o, path)).booleanValue();
  }

  protected static boolean getBoolean(String path) {
    return getBoolean(server.lastResult, path);
  }

  protected static long getLong(Object o, String path) {
    return ((Number) get(o, path)).longValue();
  }

  protected static long getLong(String path) {
    return getLong(server.lastResult, path);
  }

  protected static float getFloat(Object o, String path) {
    return ((Number) get(o, path)).floatValue();
  }

  protected static float getFloat(String path) {
    return getFloat(server.lastResult, path);
  }

  protected static JSONObject getObject(Object o, String path) {
    return (JSONObject) get(o, path);
  }

  protected static JSONObject getObject(String path) {
    return getObject(server.lastResult, path);
  }

  protected static JSONArray getArray(Object o, String path) {
    return (JSONArray) get(o, path);
  }

  protected static JSONArray getArray(String path) {
    return getArray(server.lastResult, path);
  }

  protected static JSONArray getArray(JSONArray o, int index) {
    return (JSONArray) o.get(index);
  }

  /** Renders one hilited field (multiple passages) value
   * with <b>...</b> tags, and ... separating the passages. */ 
  protected String renderHighlight(JSONArray hit) {
    StringBuilder sb = new StringBuilder();
    for(Object o : hit) {
      if (sb.length() != 0) {
        sb.append("...");
      }
      sb.append(renderSingleHighlight(getArray(o, "parts")));
    }

    return sb.toString();
  }

  /** Renders a single passage with <b>...</b> tags. */
  protected String renderSingleHighlight(JSONArray passage) {
    StringBuilder sb = new StringBuilder();
    for(Object o2 : passage) {
      if (o2 instanceof String) {
        sb.append((String) o2);
      } else {
        JSONObject obj = (JSONObject) o2;
        sb.append("<b>");
        sb.append(obj.get("text"));
        sb.append("</b>");
      }
    }

    return sb.toString();
  }

  /** Sends the command + args, expecting a failure such
   *  that all fragments occur in the failure message
   *  string.  Use this to verify a failure case is hitting
   *  the right error messages back to the user. */
  protected void assertFailsWith(String command, JSONObject args, String... fragments) throws Exception {
    assertFailsWith(command, args.toString(), fragments);
  }

  /** Sends the command + args, expecting a failure such
   *  that all fragments occur in the failure message
   *  string.  Use this to verify a failure case is hitting
   *  the right error messages back to the user. */
  protected void assertFailsWith(String command, String args, String... fragments) throws Exception {
    try {
      send(command, args);
      fail("did not hit expected exception");
    } catch (IOException ioe) {
      for(String fragment : fragments) {
        if (ioe.getMessage().contains(fragment) == false) {
          fail("expected: " + fragment + "\nactual: \"" + ioe.getMessage());
        }
      }
    }
  }

  // nocommit fix server to not need to use specific named directories?
  public static void rmDir(Path dir) throws IOException {
    if (Files.exists(dir)) {
      if (Files.isRegularFile(dir)) {
        Files.delete(dir);
      } else {
        try (DirectoryStream<Path> stream = Files.newDirectoryStream(dir)) {
          for (Path path : stream) {
            if (Files.isDirectory(path)) {
              rmDir(path);
            } else {
              Files.delete(path);
            }
          }
        }
        Files.delete(dir);
      }
    }
  }
}

