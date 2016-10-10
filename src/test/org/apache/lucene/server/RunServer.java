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

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStreamWriter;
import java.io.Reader;
import java.io.Writer;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.Socket;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.CharsetEncoder;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;
import org.apache.lucene.store.InputStreamDataInput;
import org.apache.lucene.store.OutputStreamDataOutput;
import org.apache.lucene.util.TestUtil;

import net.minidev.json.JSONObject;
import net.minidev.json.JSONStyle;
import net.minidev.json.JSONStyleIdent;
import net.minidev.json.JSONValue;
import net.minidev.json.parser.JSONParser;
import net.minidev.json.parser.ParseException;

/** Runs a server instance in a new thread in the current JVM */

public class RunServer {

  public boolean VERBOSE;
  
  /** Which socket port this server is listening on */
  public final int port;

  /** Which socket port this server is listening on for binary communications */
  public final int binaryPort;

  /** The main server thread */
  private Thread serverThread;

  public String curIndexName;

  public Path curIndexPath;

  public long lastIndexGen = -1;

  /** Last result from the server; tests can access this to
   *  check results. */
  public JSONObject lastResult;

  public final Server server;

  private final Random random;

  public RunServer(Random random, String name, Path globalStateDir) throws Exception {
    this(random, name, globalStateDir, Arrays.asList(new String[] {"127.0.0.1:0"}));
  }

  public RunServer(Random random, final String name, final Path globalStateDir, List<String> ipPorts) throws Exception {
    this.random = random;
    final CountDownLatch ready = new CountDownLatch(1);
    final Exception[] exc = new Exception[1];
    final AtomicReference<Server> theServer = new AtomicReference<>();
    serverThread = new Thread() {
        @Override
        public void run() {
          try {
            Server s = new Server(name, globalStateDir, 10, 1, ipPorts);
            theServer.set(s);
            s.run(ready);
          } catch (Exception e) {
            exc[0] = e;
            ready.countDown();
          }
        }
      };
    serverThread.setName("test-main-server-" + name);
    serverThread.start();
    if (!ready.await(2, TimeUnit.SECONDS)) {
      throw new IllegalStateException("server took more than 2 seconds to start");
    }
    if (exc[0] != null) {
      throw exc[0];
    }
    this.server = theServer.get();
    port = server.actualPorts.get(0);
    binaryPort = server.actualBinaryPorts.get(0);
  }

  public void shutdown() throws Exception {
    send("shutdown");
    if (serverThread != null) {
      serverThread.join();
      serverThread = null;
    }
  }

  protected void refresh() throws Exception {
    send("refresh", "{indexName: " + curIndexName + "}");
  }

  private boolean requiresIndexName(String command) {
    if (command.equals("shutdown")) {
      return false;
    }
    return true;
  }

  public JSONObject send(String command) throws Exception {
    if (command.equals("startIndex")) {
      // We do this so tests that index a doc and then need
      // to search it, don't wait very long for the new
      // searcher:
      send("liveSettings", "{minRefreshSec: 0.001}");
    }
    return _send(command, "{}");
  }

  public JSONObject send(String command, String args) throws Exception {
    if (args.equals("{}")) {
      throw new IllegalArgumentException("don't pass empty args");
    }
    return _send(command, args);
  }

  JSONObject _send(String command, String args) throws Exception {
    JSONObject o;
    // we do permissive parsing here so tests can do e.g. {indexName: foo} without the double quotes around all strings:
    try {
      o = (JSONObject) new JSONParser(JSONParser.MODE_PERMISSIVE & ~(JSONParser.ACCEPT_TAILLING_DATA)).parse(args);
    } catch (ParseException pe) {
      // NOTE: don't send pe as the cause; it adds lots of
      // unhelpful noise because the message usually states
      // what's wrong very well:
      throw new IllegalArgumentException("test bug: failed to parse json args \"" + args + "\": " + pe.getMessage());
    }
    return send(command, o);
  }

  public JSONObject send(String command, JSONObject args) throws Exception {
    // Auto-insert indexName:
    if (curIndexName != null && requiresIndexName(command) && args.get("indexName") == null) {
      if (VERBOSE) {
        System.out.println("NOTE: ServerBaseTestCase: now add current indexName: " + curIndexName);
      }
      args.put("indexName", curIndexName);
    }

    if (command.equals("search") && args.containsKey("searcher") == false && lastIndexGen != -1) {
      if (VERBOSE) {
        System.out.println("\nNOTE: ServerBaseTestCase: inserting 'searcher: {indexGen: " + lastIndexGen + "}' into search request");
      }
      JSONObject o = new JSONObject();
      o.put("indexGen", lastIndexGen);
      args.put("searcher", o);
    }

    if (VERBOSE) {
      System.out.println("\nNOTE: ServerBaseTestCase: sendRaw command=" + command + " args:\n" + args.toJSONString(new JSONStyleIdent()));
    }

    lastResult = sendRaw(command, args.toJSONString(JSONStyle.NO_COMPRESS));

    if (VERBOSE) {
      System.out.println("NOTE: ServerBaseTestCase: server response:\n" + lastResult.toJSONString(new JSONStyleIdent()));
    }

    if (lastResult.containsKey("indexGen")) {
      lastIndexGen = ServerBaseTestCase.getLong(lastResult, "indexGen");
      if (VERBOSE) {
        System.out.println("NOTE: ServerBaseTestCase: record lastIndexGen=" + lastIndexGen);
      }
    }

    return lastResult;
  }

  public JSONObject sendRaw(String command, String body) throws Exception {
    return sendRaw(command, body.getBytes("UTF-8"));
  }

  public JSONObject sendRaw(String command, byte[] body) throws Exception {
    return sendRaw(command, body, port);
  }

  public JSONObject sendRaw(String command, byte[] body, int port) throws Exception {
    HttpURLConnection c = (HttpURLConnection) new URL("http://localhost:" + port + "/" + command).openConnection();
    c.setUseCaches(false);
    c.setDoOutput(true);
    c.setRequestMethod("POST");
    c.setRequestProperty("Content-Length", ""+body.length);
    c.setRequestProperty("Charset", "UTF-8");
    try {
      c.getOutputStream().write(body);
    } catch (ConnectException ce) {
      System.out.println("FAILED port=" + port + ":");
      ce.printStackTrace(System.out);
      throw ce;
    }
    // c.connect()
    int code = c.getResponseCode();
    int size = c.getContentLength();
    byte[] bytes = new byte[size];
    if (code == 200) {
      InputStream is = c.getInputStream();
      readFully(is, bytes);
      c.disconnect();
      //System.out.println("PARSE: " + new String(bytes, "UTF-8"));
      String jsonString = new String(bytes, "UTF-8");
      try {
        return (JSONObject) JSONValue.parseStrict(jsonString);
      } catch (ParseException pe) {
        System.out.println("FAILED TO PARSE server response as valid json:\n" + jsonString + "\n");
        throw pe;
      }
    } else {
      InputStream is = c.getErrorStream();
      readFully(is, bytes);
      c.disconnect();
      throw new IOException("Server error:\n" + new String(bytes, "UTF-8"));
    }
  }

  private static void readFully(InputStream stream, byte[] bytes) throws IOException {
    int upto = 0;
    while (upto < bytes.length) {
      int count = stream.read(bytes, upto, bytes.length-upto);
      if (count == -1) {
        throw new IOException("hit end-of-stream after reading " + upto + " bytes of " + bytes.length);
      }
      upto += count;
    }
  }

  public byte[] sendBinary(String command, byte[] body) throws Exception {
    Socket s = new Socket("localhost", binaryPort);
    BufferedInputStream in = new BufferedInputStream(s.getInputStream());
    BufferedOutputStream out = new BufferedOutputStream(s.getOutputStream());
    DataInput dataIn = new InputStreamDataInput(in);
    DataOutput dataOut = new OutputStreamDataOutput(out);
    dataOut.writeInt(Server.BINARY_MAGIC);
    byte[] commandBytes = command.getBytes(StandardCharsets.UTF_8);
    dataOut.writeVInt(commandBytes.length);
    dataOut.writeBytes(commandBytes, 0, commandBytes.length);
    dataOut.writeBytes(body, 0, body.length);
    out.flush();
    s.shutdownOutput();

    byte status = dataIn.readByte();
    int len = dataIn.readInt();
    byte[] responseBytes = new byte[len];
    dataIn.readBytes(responseBytes, 0, len);
    s.close();
    if (status == 0) {
      // good
      return responseBytes;
    } else if (status == 1) {
      // bad!
      throw new IOException("server error:\n" + new String(responseBytes, StandardCharsets.UTF_8));
    } else {
      // horrible!
      throw new IOException("server prototol error: expected 0 or 1 leading response byte, but got: " + status);
    }
  }
  
  public String httpLoad(String path) throws Exception {
    HttpURLConnection c = (HttpURLConnection) new URL("http://localhost:" + port + "/" + path).openConnection();
    c.setUseCaches(false);
    c.setDoOutput(true);
    c.setRequestMethod("GET");
    // c.connect()
    int code = c.getResponseCode();
    int size = c.getContentLength();
    byte[] bytes = new byte[size];
    if (code == 200) {
      InputStream is = c.getInputStream();
      readFully(is, bytes);
      c.disconnect();
      return new String(bytes, "UTF-8");
    } else {
      InputStream is = c.getErrorStream();
      readFully(is, bytes);
      c.disconnect();
      throw new IOException("Server error:\n" + new String(bytes, "UTF-8"));
    }
  }

  /** Sends a chunked HTTP request */
  public JSONObject send(String command, Map<String,Object> params, Reader body) throws Exception {
    // TODO: isn't there some java sugar for this already!?
    StringBuilder url = new StringBuilder("http://localhost:");
    url.append(port);
    url.append('/');
    url.append(command);
    url.append('?');
    for(Map.Entry<String,Object> ent : params.entrySet()) {
      if (ent.getValue() instanceof List) {
        List<String> values = (List<String>) ent.getValue();
        for(String value : values) {
          url.append(ent.getKey());
          url.append('=');
          url.append(URLEncoder.encode(value));
        }
      } else {
        url.append(ent.getKey());
        url.append('=');
        url.append(URLEncoder.encode((String) ent.getValue()));
      }
    }
    HttpURLConnection c = (HttpURLConnection) new URL(url.toString()).openConnection();
    c.setUseCaches(false);
    c.setDoOutput(true);
    int chunkKB = TestUtil.nextInt(random, 1, 128);
    c.setChunkedStreamingMode(chunkKB*1024);
    c.setRequestMethod("POST");
    c.setRequestProperty("Charset", "UTF-8");

    CharsetEncoder encoder = StandardCharsets.UTF_8.newEncoder()
      .onMalformedInput(CodingErrorAction.REPORT)
      .onUnmappableCharacter(CodingErrorAction.REPORT);
    Writer w = new OutputStreamWriter(c.getOutputStream(), encoder);
    char[] buffer = new char[2048];
    while (true) {
      int count = body.read(buffer);
      if (count == -1) {
        break;
      }
      assert count > 0;
      w.write(buffer, 0, count);
    }
    w.flush();

    int code = c.getResponseCode();
    int size = c.getContentLength();
    byte[] bytes = new byte[size];
    if (code == 200) {
      InputStream is = c.getInputStream();
      readFully(is, bytes);
      c.disconnect();
      // nocommit we can't assume it's UTF-8 coming back from the server:
      return (JSONObject) JSONValue.parseStrict(new String(bytes, "UTF-8"));
    } else {
      InputStream is = c.getErrorStream();
      readFully(is, bytes);
      c.disconnect();
      throw new IOException("Server error:\n" + new String(bytes, "UTF-8"));
    }
  }

  /*
  public JSONObject sendChunked(String body, String request) throws Exception {
    HttpURLConnection c = (HttpURLConnection) new URL("http://localhost:" + port + "/" + request).openConnection();
    c.setUseCaches(false);
    c.setDoOutput(true);
    c.setChunkedStreamingMode(256);
    c.setRequestMethod("POST");
    c.setRequestProperty("Charset", "UTF-8");
    byte[] bytes = body.getBytes("UTF-8");
    c.getOutputStream().write(bytes);
    // c.connect()
    int code = c.getResponseCode();
    int size = c.getContentLength();
    if (code == 200) {
      InputStream is = c.getInputStream();
      bytes = new byte[size];
      readFully(is, bytes);
      c.disconnect();
      return (JSONObject) JSONValue.parseStrict(new String(bytes, "UTF-8"));
    } else {
      InputStream is = c.getErrorStream();
      readFully(is, bytes);
      c.disconnect();
      throw new IOException("Server error:\n" + new String(bytes, "UTF-8"));
    }
  }
  */
}
