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
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.ConnectException;
import java.net.HttpURLConnection;
import java.net.Socket;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;
import org.apache.lucene.store.InputStreamDataInput;
import org.apache.lucene.store.OutputStreamDataOutput;

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

  public RunServer(final String name, final Path globalStateDir) throws Exception {
    final CountDownLatch ready = new CountDownLatch(1);
    final Exception[] exc = new Exception[1];
    final AtomicReference<Server> theServer = new AtomicReference<>();
    serverThread = new Thread() {
        @Override
        public void run() {
          try {
            Server s = new Server(name, globalStateDir, 0, 10, 1, "127.0.0.1");
            theServer.set(s);
            s.run(ready);
          } catch (Exception e) {
            exc[0] = e;
            ready.countDown();
          }
        }
      };
    serverThread.start();
    if (!ready.await(2, TimeUnit.SECONDS)) {
      throw new IllegalStateException("server took more than 2 seconds to start");
    }
    if (exc[0] != null) {
      throw exc[0];
    }

    port = theServer.get().actualPort;
    binaryPort = theServer.get().actualBinaryPort;
  }

  public void shutdown() throws Exception {
    send("shutdown");
    if (serverThread != null) {
      serverThread.join();
      serverThread = null;
    }
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
      is.read(bytes);
      c.disconnect();
      //System.out.println("PARSE: " + new String(bytes, "UTF-8"));
      JSONObject result = (JSONObject) JSONValue.parseStrict(new String(bytes, "UTF-8"));
      //System.out.println("  got: " + result);
      return result;
    } else {
      InputStream is = c.getErrorStream();
      is.read(bytes);
      c.disconnect();
      throw new IOException("Server error:\n" + new String(bytes, "UTF-8"));
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

    int len = dataIn.readInt();
    byte[] responseBytes = new byte[len];
    dataIn.readBytes(responseBytes, 0, len);
    s.close();
    return responseBytes;
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
      is.read(bytes);
      c.disconnect();
      return new String(bytes, "UTF-8");
    } else {
      InputStream is = c.getErrorStream();
      is.read(bytes);
      c.disconnect();
      throw new IOException("Server error:\n" + new String(bytes, "UTF-8"));
    }
  }

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
      is.read(bytes);
      c.disconnect();
      return (JSONObject) JSONValue.parseStrict(new String(bytes, "UTF-8"));
    } else {
      InputStream is = c.getErrorStream();
      is.read(bytes);
      c.disconnect();
      throw new IOException("Server error:\n" + new String(bytes, "UTF-8"));
    }
  }
}
