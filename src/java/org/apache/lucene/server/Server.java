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
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.io.UnsupportedEncodingException;
import java.io.Writer;
import java.net.FileNameMap;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URI;
import java.net.URL;
import java.net.URLConnection;
import java.net.URLDecoder;
import java.nio.ByteBuffer;
import java.nio.charset.Charset;
import java.nio.charset.CharsetDecoder;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;

import org.apache.lucene.server.handlers.*;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.PolyType.PolyEntry;
import org.apache.lucene.server.params.PolyType;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.RequestFailedException;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.InputStreamDataInput;
import org.apache.lucene.store.OutputStreamDataOutput;

import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;

import net.minidev.json.JSONObject;
import net.minidev.json.JSONStyleIdent;
import net.minidev.json.parser.ContainerFactory;
import net.minidev.json.parser.JSONParser;
import net.minidev.json.parser.ParseException;

public class Server {

  public static final int BINARY_MAGIC = 0x3414f5c;

  private static final boolean VERBOSE = false;

  final GlobalState globalState;
  final HttpServer httpServer;
  final ExecutorService httpThreadPool;
  final BinaryServer binaryServer;

  public final int actualPort;
  public final int actualBinaryPort;

  private static Map<String, List<String>> splitQuery(URI uri) throws UnsupportedEncodingException {
    final Map<String, List<String>> params = new LinkedHashMap<String, List<String>>();
    String query = uri.getQuery();
    if (query != null) {
      final String[] pairs = query.split("&");
      for (String pair : pairs) {
        final int idx = pair.indexOf("=");
        final String key = idx > 0 ? URLDecoder.decode(pair.substring(0, idx), "UTF-8") : pair;
        if (params.containsKey(key) == false) {
          params.put(key, new LinkedList<String>());
        }
        final String value = idx > 0 && pair.length() > idx + 1 ? URLDecoder.decode(pair.substring(idx + 1), "UTF-8") : null;
        params.get(key).add(value);
      }
    }

    return params;
  }  

  class DocHandler implements HttpHandler {
    public void handle(HttpExchange x) throws IOException {
      try {
        _handle(x);
      } catch (Exception e) {
        if (VERBOSE) {
          System.out.println("\nSERVER: handle for " + x.getRequestURI() + " hit exception:");
          e.printStackTrace(System.out);
        }
        throw new RuntimeException(e);
      }
    }

    private void _handle(HttpExchange x) throws Exception {
      Map<String,List<String>> params = splitQuery(x.getRequestURI());
      String html = globalState.docHandler.handle(params, globalState.getHandlers());
      byte[] responseBytes = html.getBytes("UTF-8");

      Headers headers = x.getResponseHeaders();
      headers.set("Content-Type", "text-html;charset=utf-8");
      x.sendResponseHeaders(200, responseBytes.length);
      x.getResponseBody().write(responseBytes, 0, responseBytes.length);
      x.getRequestBody().close();
      x.getResponseBody().close();
    }
  }

  static void sendError(HttpExchange x, int httpCode, String httpMessage) throws IOException {
    byte[] bytes;
    try {
      bytes = httpMessage.getBytes("UTF-8");
    } catch (UnsupportedEncodingException uoe) {
      // should not happen!
      throw new RuntimeException(uoe);
    }
    x.sendResponseHeaders(httpCode, bytes.length);
    x.getResponseBody().write(bytes);
    x.getRequestBody().close();
    x.getResponseBody().close();
  }

  class PluginsStaticFileHandler implements HttpHandler {
    private final FileNameMap fileNameMap = URLConnection.getFileNameMap();
      
    public void handle(HttpExchange x) throws IOException {
      try {
        _handle(x);
      } catch (Exception e) {
        if (VERBOSE) {
          System.out.println("\nSERVER: handle for " + x.getRequestURI() + " hit exception:");
          e.printStackTrace(System.out);
        }
        throw new RuntimeException(e);
      }
    }

    private void _handle(HttpExchange x) throws Exception {
      String uri = x.getRequestURI().toString();
      int idx = uri.indexOf('/', 9);
      if (idx == -1) {
        sendError(x, 400, "URL should be /plugin/name/...");
        return;
      }
          
      String pluginName = uri.substring(9, idx);
      Path pluginsDir = globalState.stateDir.resolve("plugins");
      Path pluginDir = pluginsDir.resolve(pluginName);
      if (Files.exists(pluginDir) == false) {
        sendError(x, 400, "plugin \"" + pluginName + "\" does not exist");
      }

      Path localFile = pluginsDir.resolve(pluginName).resolve("site").resolve(uri.substring(idx+1));
      if (Files.exists(localFile) == false) {
        sendError(x, 400, "file " + uri + " does not exist");
      }

      String mimeType = fileNameMap.getContentTypeFor(uri);
      
      Headers headers = x.getResponseHeaders();
      headers.set("Content-Type", mimeType);
      
      // nocommit don't do this:
      byte[] bytes = Files.readAllBytes(localFile);
      
      x.sendResponseHeaders(200, bytes.length);
      x.getResponseBody().write(bytes, 0, bytes.length);
      x.getRequestBody().close();
      x.getResponseBody().close();
    }
  }
  
  class ServerHandler implements HttpHandler {
    private final Handler handler;
    
    public ServerHandler(Handler handler) {
      this.handler = handler;
      // nocommit should we set http keep-alive here?  e.g. bulk indexing request could stall for a while?
    }

    private void sendException(HttpExchange x, Throwable e) throws IOException {
      x.getRequestBody().close();
      // Just send full stack trace back to client:
      Writer sw = new StringWriter();
      PrintWriter pw = new PrintWriter(sw);

      RequestFailedException rfe;
      if (e instanceof RequestFailedException) {
        rfe = (RequestFailedException) e;
      } else if (e.getCause() != null && e.getCause() instanceof RequestFailedException) {
        rfe = (RequestFailedException) e.getCause();
      } else {
        rfe = null;
      }

      if (rfe != null) {
        pw.println(rfe.path + ": " + rfe.reason);
        if (rfe.getCause() != null) {
          pw.println();
          rfe.getCause().printStackTrace(pw);
        }
        
        // TODO?
        //Throwable cause = rfe.getCause();
        //if (cause != null) {
        //pw.write("\n\nCaused by:\n\n" + cause);
        //}
      } else {
        e.printStackTrace(pw);
      }

      String message = sw.toString();
      String[] lines = message.split("\n");
      StringBuilder b = new StringBuilder();
      boolean inHttp = false;
      for(String line : lines) {
        if (line.startsWith("\tat com.sun.net.httpserver") || line.startsWith("\tat sun.net.httpserver") || line.startsWith("\tat java.lang.Thread.run") || line.startsWith("\tat java.util.concurrent.ThreadPoolExecutor")) {
          if (inHttp == false) {
            inHttp = true;
            line = "\tat <httpserver>";
          } else {
            continue;
          }
        } else {
          inHttp = false;
        }
        if (b.length() > 0) {
          b.append('\n');
        }
        b.append(line);
      }
      message = b.toString();

      Headers headers = x.getResponseHeaders();
      headers.set("Content-Type", "text-plain; charset=utf-8");
      byte[] bytes = message.getBytes("UTF-8");
      headers.set("Content-Length", "" + bytes.length);
      x.sendResponseHeaders(500, bytes.length);
      x.getResponseBody().write(bytes, 0, bytes.length);
      x.getResponseBody().close();
    }

    public void handle(HttpExchange x) throws IOException {
      try {
        _handle(x);
      } catch (Exception e) {
        if (VERBOSE) {
          System.out.println("\nSERVER: handle for " + x.getRequestURI() + " hit exception:");
          e.printStackTrace(System.out);
        }
        throw new RuntimeException(e);
      }
    }

    private void _handle(HttpExchange x) throws Exception {
      String method = x.getRequestMethod();
      if (method.equals("POST") == false) {
        // TODO: am I supposed to set HTTP error code instead!?
        // nocommit make sure we test this
        System.out.println("  FAIL");
        throw new IllegalArgumentException("use HTTP POST, not " + method);
      }

      String command = x.getRequestURI().getPath().substring(1);
      //System.out.println("SVR " + globalState.nodeName + ": start handle " + command);

      Map<String,List<String>> params = splitQuery(x.getRequestURI());

      Headers headers = x.getRequestHeaders();
      //System.out.println("HEADERS: " + headers.entrySet());

      List<String> header = headers.get("Charset");
      String charset;
      if (header != null) {
        charset = header.get(0);
      } else {
        charset = "UTF-8";
      }
      InputStream in = x.getRequestBody();

      //System.out.println("in=" + in);
      List<String> v = headers.get("Transfer-Encoding");

      String responseString;

      CharsetDecoder decoder = Charset.forName(charset).newDecoder()
        .onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT);
      
      if (v != null && v.get(0).equalsIgnoreCase("chunked")) {
        // client is streaming the request to us; length not known in advance
        if (handler.doStream()) {
          try {
            // TODO: BufferedInputStream didn't seem to help?  Maybe HttpServer is already buffereing chunked requests here?
            //responseString = handler.handleStreamed(new InputStreamReader(new BufferedInputStream(in, 128*1024), decoder), params);
            responseString = handler.handleStreamed(new InputStreamReader(in, decoder), params);
          } catch (Throwable t) {
            sendException(x, t);
            return;
          }
        } else {
          throw new IllegalArgumentException("command " + command + " does not support chunked transfer");
        }
      } else {
        int length = Integer.parseInt(headers.get("Content-Length").get(0));
        byte[] bytes = new byte[length];
        int upto = 0;
        while (upto < length) {
          int count = in.read(bytes, upto, length-upto);
          if (count == -1) {
            break;
          } else {
            upto += count;
          }
        }

        if (upto != length) {
          throw new IllegalArgumentException("did not read enough bytes: expected " + length + " but got " + upto);
        }

        String requestString;
        try {
          requestString = decoder.decode(ByteBuffer.wrap(bytes)).toString();
        } catch (Throwable t) {
          sendException(x, t);
          return;
        }

        Object o = null;
        try {
          o = new JSONParser(JSONParser.MODE_STRICTEST).parse(requestString, ContainerFactory.FACTORY_SIMPLE);
        } catch (ParseException pe) {
          IllegalArgumentException iae = new IllegalArgumentException("could not parse HTTP request data as JSON");
          iae.initCause(pe);
          sendException(x, iae);
          return;
        }
        if (!(o instanceof JSONObject)) {
          throw new IllegalArgumentException("HTTP request data must be a JSON struct { .. }");
        }

        JSONObject requestJSON = (JSONObject) o;

        Request request = new Request(null, command, requestJSON, handler.getType());

        FinishRequest finish;
        try {
          IndexState state;
          if (handler.requiresIndexName) {
            String indexName = request.getString("indexName");
            state = globalState.get(indexName);
          } else {
            state = null;
          }
      
          for(PreHandle h : handler.preHandlers) {
            h.invoke(request);
          }
          // TODO: for "compute intensive" (eg search)
          // handlers, we should use a separate executor?  And
          // we should more gracefully handle the "Too Busy"
          // case by accepting the connection, seeing backlog
          // is too much, and sending HTTP 500 back

          // nocommit remove this 3rd argument (cgi params)?
          finish = handler.handle(state, request, params);
        } catch (RequestFailedException rfe) {
          String details = null;
          if (rfe.param != null) {

            // nocommit this seems to not help, ie if a
            // handler threw an exception on a specific
            // parameter, it means something went wrong w/
            // that param, and it's not (rarely?) helpful to
            // then list all the other valid params?

            /*
              if (rfe.request.getType() != null) {
              Param p = rfe.request.getType().params.get(rfe.param);
              if (p != null) {
              if (p.type instanceof StructType) {
              List<String> validParams = new ArrayList<String>(((StructType) p.type).params.keySet());
              Collections.sort(validParams);
              details = "valid params are: " + validParams.toString();
              } else if (p.type instanceof ListType && (((ListType) p.type).subType instanceof StructType)) {
              List<String> validParams = new ArrayList<String>(((StructType) ((ListType) p.type).subType).params.keySet());
              Collections.sort(validParams);
              details = "each element in the array may have these params: " + validParams.toString();
              }
              }
              }
            */
          } else {
            List<String> validParams = new ArrayList<String>(rfe.request.getType().params.keySet());
            Collections.sort(validParams);
            details = "valid params are: " + validParams.toString();
          }

          // nocommit get this working correctly:
          if (false && details != null) {
            rfe = new RequestFailedException(rfe, details);
          }

          sendException(x, rfe);
          return;
        } catch (Throwable t) {
          sendException(x, t);
          return;
        }
        //System.out.println("SVR " + globalState.nodeName + ": done handle");

        // We remove params as they are accessed, so if
        // anything is left it means it wasn't used:
        if (Request.anythingLeft(requestJSON)) {
          assert request != null;
          JSONObject fullRequest;
          try {
            fullRequest = (JSONObject) new JSONParser(JSONParser.MODE_STRICTEST).parse(requestString, ContainerFactory.FACTORY_SIMPLE);
          } catch (ParseException pe) {
            // The request parsed originally...:
            assert false;

            // Dead code but compiler disagrees:
            fullRequest = null;
          }

          // Pretty print the leftover (unhandled) params:
          String pretty = requestJSON.toJSONString(new JSONStyleIdent());
          String s = "unrecognized parameters:\n" + pretty;
          String details = findFirstWrongParam(handler.getType(), fullRequest, requestJSON, new ArrayList<String>());
          if (details != null) {
            s += "\n\n" + details;
          }
          sendException(x, new IllegalArgumentException(s));
        }

        //System.out.println("SVR " + globalState.nodeName + ": start finish");
        try {
          responseString = finish.finish();
        } catch (Throwable t) {
          sendException(x, t);
          return;
        }
        //System.out.println("SVR " + globalState.nodeName + ": done finish");
      }
      
      byte[] responseBytes = responseString.getBytes("UTF-8");
      x.sendResponseHeaders(200, responseBytes.length);
      x.getResponseBody().write(responseBytes, 0, responseBytes.length);
      x.getResponseBody().close();
      in.close();

      if (command.equals("shutdown")) {
        globalState.shutdownNow.countDown();
      }
    }
  }

  private static PolyEntry findPolyType(JSONObject fullRequest, StructType type) {
    for(Map.Entry<String,Param> param : type.params.entrySet()) {
      if (param.getValue().type instanceof PolyType) {
        Object v = fullRequest.get(param.getKey());
        if (v != null && v instanceof String) {
          PolyEntry polyEntry = ((PolyType) param.getValue().type).types.get((String) v);
          if (polyEntry != null) {
            return polyEntry;
          }
        }
      }
    }

    return null;
  }

  // TODO: should we find ALL wrong params?
  // nocommit improve this: it needs to recurse into arrays too
  private static String findFirstWrongParam(StructType type, JSONObject fullRequest, JSONObject r, List<String> path) {
    PolyEntry polyEntry = findPolyType(fullRequest, type);
    for(Map.Entry<String,Object> ent : r.entrySet()) {
      String param = ent.getKey();
      if (!type.params.containsKey(param) && !type.params.containsKey("*") && (polyEntry == null || !polyEntry.type.params.containsKey(param))) {

        List<String> validParams = null;
        String extra = "";
        if (polyEntry != null) {
          validParams = new ArrayList<String>(polyEntry.type.params.keySet());
          extra = " for class=" + polyEntry.name;
        } else {
          // No PolyType found:
          validParams = new ArrayList<String>(type.params.keySet());
        }
        Collections.sort(validParams);
        
        StringBuilder sb = new StringBuilder();
        for(int i=0;i<path.size();i++) {
          if (i > 0) {
            sb.append(" > ");
          }
          sb.append(path.get(i));
        }

        if (sb.length() != 0) {
          sb.append(" > ");
        }
        sb.append(param);
        return "param " + sb.toString() + " is unrecognized; valid params" + extra + " are: " + validParams.toString();
      }
    }
      
    // Recurse:
    for(Map.Entry<String,Object> ent : r.entrySet()) {
      Param param = type.params.get(ent.getKey());
      if (param == null && polyEntry != null) {
        param = polyEntry.type.params.get(ent.getKey());
      }
      if (param == null) {
        param = type.params.get("*");
      }
      // nocommit go into array, poly too
      // nocommit handle case where we expected object but
      // didnt' get json object
      if (param.type instanceof StructType && ent.getValue() instanceof JSONObject) {
        path.add(param.name);
        String details = findFirstWrongParam((StructType) param.type, (JSONObject) fullRequest.get(ent.getKey()), (JSONObject) ent.getValue(), path);
        if (details != null) {
          return details;
        }
        path.remove(path.size()-1);
      }
    }

    return null;
  }

  private static void usage() {
    System.out.println("\nUsage: java -cp <stuff> org.apache.lucene.server.Server [-port port] [-maxHTTPThreadCount count] [-stateDir /path/to/dir]\n\n");
  }

  public Server(String nodeName, Path globalStateDir, int port, int backlog, int threadCount, String bindHost) throws Exception {
    globalState = new GlobalState(nodeName, globalStateDir);
    globalState.loadIndexNames();
    
    httpServer = HttpServer.create(new InetSocketAddress(bindHost, port), backlog);

    httpThreadPool = Executors.newFixedThreadPool(threadCount);
    globalState.localAddress = httpServer.getAddress();
    httpServer.setExecutor(httpThreadPool);
    actualPort = httpServer.getAddress().getPort();

    int binaryPort;
    if (port == 0) {
      binaryPort = 0;
    } else {
      binaryPort = port+1;
    }
    binaryServer = new BinaryServer(bindHost, binaryPort);
    actualBinaryPort = binaryServer.actualPort;
    globalState.localBinaryAddress = (InetSocketAddress) binaryServer.serverSocket.getLocalSocketAddress();

    globalState.addHandler("addDocument", new AddDocumentHandler(globalState));
    globalState.addHandler("addDocuments", new AddDocumentsHandler(globalState));
    globalState.addHandler("analyze", new AnalysisHandler(globalState));
    globalState.addHandler("buildSuggest", new BuildSuggestHandler(globalState));
    globalState.addHandler("bulkAddDocument", new BulkAddDocumentHandler(globalState));
    globalState.addHandler("bulkAddDocuments", new BulkAddDocumentsHandler(globalState));
    globalState.addHandler("bulkUpdateDocument", new BulkUpdateDocumentHandler(globalState));
    globalState.addHandler("bulkUpdateDocuments", new BulkUpdateDocumentsHandler(globalState));
    globalState.addHandler("commit", new CommitHandler(globalState));
    globalState.addHandler("createIndex", new CreateIndexHandler(globalState));
    globalState.addHandler("createSnapshot", new CreateSnapshotHandler(globalState));
    globalState.addHandler("deleteAllDocuments", new DeleteAllDocumentsHandler(globalState));
    globalState.addHandler("deleteIndex", new DeleteIndexHandler(globalState));
    globalState.addHandler("deleteDocuments", new DeleteDocumentsHandler(globalState));
    globalState.addHandler("help", new HelpHandler(globalState));
    globalState.addHandler("indexStatus", new IndexStatusHandler(globalState));
    globalState.addHandler("liveSettings", new LiveSettingsHandler(globalState));
    globalState.addHandler("liveValues", new LiveValuesHandler(globalState));
    globalState.addHandler("registerFields", new RegisterFieldHandler(globalState));
    globalState.addHandler("releaseSnapshot", new ReleaseSnapshotHandler(globalState));
    globalState.addHandler("search", new SearchHandler(globalState));
    globalState.addHandler("nearestPoints", new NearestPointsHandler(globalState));
    globalState.addHandler("settings", new SettingsHandler(globalState));
    globalState.addHandler("shutdown", new ShutdownHandler(globalState));
    globalState.addHandler("startIndex", new StartIndexHandler(globalState));
    globalState.addHandler("stats", new StatsHandler(globalState));
    globalState.addHandler("stopIndex", new StopIndexHandler(globalState));
    globalState.addHandler("suggestLookup", new SuggestLookupHandler(globalState));
    globalState.addHandler("refresh", new RefreshHandler(globalState));
    globalState.addHandler("updateSuggest", new UpdateSuggestHandler(globalState));
    globalState.addHandler("updateDocument", new UpdateDocumentHandler(globalState));
    globalState.addHandler("setCommitUserData", new SetCommitUserDataHandler(globalState));
    globalState.addHandler("getCommitUserData", new GetCommitUserDataHandler(globalState));

    // primary only, binary protocol, to record remote address of a replica for an index on this node
    globalState.addHandler("addReplica", new AddReplicaHandler(globalState));

    // primary only, to create a new NRT point and notify previously linked replicas to copy it:
    globalState.addHandler("writeNRTPoint", new WriteNRTPointHandler(globalState));

    // replica only, binary protocol: asks replica to copy specific files from its primary (used for merge warming)
    globalState.addHandler("copyFiles", new CopyFilesHandler(globalState));

    // primary only, binary: send files to me
    globalState.addHandler("sendMeFiles", new SendMeFilesHandler(globalState));

    // replica only, binary: notifies replica that its primary just created a new NRT point
    globalState.addHandler("newNRTPoint", new NewNRTPointHandler(globalState));

    // TODO: allow CSV update document too:
    // binary protocol for bulk adding CSV encoded documents
    globalState.addHandler("bulkCSVAddDocument", new BulkCSVAddDocumentHandler(globalState));

    // docs are their own handler:
    httpServer.createContext("/doc", new DocHandler());

    // static files from plugins are their own handler:
    httpServer.createContext("/plugins", new PluginsStaticFileHandler());
    
    for(Map.Entry<String,Handler> ent : globalState.getHandlers().entrySet()) {
      httpServer.createContext("/" + ent.getKey(), new ServerHandler(ent.getValue()));
    }
  }

  public void run(CountDownLatch ready) throws Exception {

    globalState.loadPlugins();

    System.out.println("SVR " + globalState.nodeName + ": listening on ports " + actualPort + "/" + actualBinaryPort + ".");

    httpServer.start();
    binaryServer.start();

    //System.out.println("SVR: done httpServer.start");

    // Notify caller server is started:
    ready.countDown();

    // Await shutdown:
    globalState.shutdownNow.await();

    httpServer.stop(0);
    httpThreadPool.shutdown();
    binaryServer.close();

    globalState.close();
    System.out.println("SVR: done close");
  }

  /** Command-line entry. */
  public static void main(String[] args) throws Exception {
    int port = 4000;
    int maxHTTPThreadCount = 2*Runtime.getRuntime().availableProcessors();
    String bindHost = "127.0.0.1";
    Path stateDir = Paths.get(System.getProperty("user.home"), "lucene", "server");
    for(int i=0;i<args.length;i++) {
      if (args[i].equals("-port")) {
        if (args.length == i+1) {
          throw new IllegalArgumentException("no value specified after -port");
        }
        port = Integer.parseInt(args[i+1]);
        i++;
      } else if (args[i].equals("-maxHTTPThreadCount")) {
        if (args.length == i+1) {
          throw new IllegalArgumentException("no value specified after -maxHTTPThreadCount");
        }
        maxHTTPThreadCount = Integer.parseInt(args[i+1]);
        i++;
      } else if (args[i].equals("-stateDir")) {
        if (args.length == i+1) {
          throw new IllegalArgumentException("no value specified after -stateDir");
        }
        stateDir = Paths.get(args[i+1]);
        i++;
      } else if (args[i].equals("-interface")) {
        if (args.length == i+1) {
          throw new IllegalArgumentException("no value specified after -stateDir");
        }
        bindHost = args[i+1];
        i++;
      } else {
        usage();
        System.exit(-1);
      }
    }

    // nocommit don't hardwire 50 tcp queue length, 10 threads
    new Server("main", stateDir, port, 50, 10, bindHost).run(new CountDownLatch(1));
  }

  private static class BinaryClientHandler implements Runnable {

    private final Socket socket;

    private final GlobalState globalState;

    public BinaryClientHandler(GlobalState globalState, Socket socket) {
      this.globalState = globalState;
      this.socket = socket;
    }

    @Override
    public void run() {
      try {
        _run();
      } catch (Exception e) {
        System.out.println("SVR " + globalState.nodeName + ": hit exception");
        e.printStackTrace(System.out);
        throw new RuntimeException(e);
      }
    }

    private void _run() throws Exception {
      System.out.println("SVR " + globalState.nodeName + ": handle binary client; receive buffer=" + socket.getReceiveBufferSize());
      // nocommit buffer here:
      try (InputStream in = new BufferedInputStream(socket.getInputStream(), 128 * 1024); OutputStream out = socket.getOutputStream()) {
        DataInput dataIn = new InputStreamDataInput(in);
        int x = dataIn.readInt();
        if (x != BINARY_MAGIC) {
          throw new IllegalArgumentException("wrong magic header: got " + x + " but expected " + BINARY_MAGIC);
        }
        int length = dataIn.readVInt();
        if (length > 128) {
          throw new IllegalArgumentException("command length too long: got " + length);
        }
        System.out.println("LENGTH " + length);
        byte[] bytes = new byte[length];
        dataIn.readBytes(bytes, 0, length);
        String command = new String(bytes, 0, length, StandardCharsets.UTF_8);
        System.out.println("SVR " + globalState.nodeName + ": binary: command=" + command);

        Handler handler = globalState.getHandler(command);
        if (handler.binaryRequest() == false) {
          throw new IllegalArgumentException("command " + command + " cannot handle binary requests");
        }

        // nocommit what buffer size?
        OutputStream bufferedOut = new BufferedOutputStream(out);

        handler.handleBinary(in, dataIn, new OutputStreamDataOutput(bufferedOut), bufferedOut);
        bufferedOut.flush();
      }
    }
  }

  private class BinaryServer extends Thread {
    public final ServerSocket serverSocket;
    public final int actualPort;

    private final ExecutorService threadPool;
    private boolean stop;
    
    public BinaryServer(String host, int port) throws IOException {
      serverSocket = new ServerSocket();
      serverSocket.bind(new InetSocketAddress(host, port));
      actualPort = serverSocket.getLocalPort();
      threadPool = Executors.newCachedThreadPool(
                         new ThreadFactory() {
                           @Override
                           public Thread newThread(Runnable r) {
                             Thread thread = new Thread(r);
                             thread.setName("binary " + globalState.nodeName);
                             return thread;
                           }
                         });
    }

    public void close() throws IOException, InterruptedException {
      stop = true;
      serverSocket.close();
      join();
    }

    public void run() {
      while (stop == false) {
        Socket clientSocket = null;
        //System.out.println("SVR " + globalState.nodeName + ": binary: now accept");
        try {
          clientSocket = serverSocket.accept();
        } catch (IOException e) {
          if (stop) {
            break;
          }
          throw new RuntimeException("Error accepting client connection", e);
        }
        //System.out.println("SVR " + globalState.nodeName + ": binary: done accept: " + clientSocket + " rcv buffer " + clientSocket.getReceiveBufferSize());
        threadPool.execute(new BinaryClientHandler(globalState, clientSocket));
      }

      threadPool.shutdown();
    }
  }
}
