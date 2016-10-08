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
import java.io.InputStream;
import java.io.OutputStream;
import java.io.Reader;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Semaphore;

import org.apache.lucene.document.BinaryDocValuesField;
import org.apache.lucene.document.BinaryPoint;
import org.apache.lucene.document.Document;
import org.apache.lucene.document.SortedDocValuesField;
import org.apache.lucene.document.SortedSetDocValuesField;
import org.apache.lucene.document.StringField;
import org.apache.lucene.document.TextField;
import org.apache.lucene.server.Connection;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.Server;
import org.apache.lucene.server.params.*;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;
import org.apache.lucene.util.IOUtils;
import org.apache.lucene.util.StringHelper;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

/** Called externally to notify us of another node */

public class LinkNodeHandler extends Handler {

  private final static StructType TYPE =
    new StructType(
        new Param("remoteBinaryAddress", "TCP interface of remote node", new StringType()),
        new Param("remoteBinaryPort", "TCP port of remote node's binary listener", new IntType()));

  /** Sole constructor. */
  public LinkNodeHandler(GlobalState state) {
    super(state);
    requiresIndexName = false;
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public FinishRequest handle(final IndexState state, final Request r, Map<String,List<String>> params) throws Exception {
    String remoteIP = r.getString("remoteBinaryAddress");
    int remotePort = r.getInt("remoteBinaryPort");

    return new FinishRequest() {
      @Override
      public String finish() throws IOException {
        Connection c = new Connection(new InetSocketAddress(remoteIP, remotePort));
        // We send tiny commands back and forth between the nodes, so we are far more concerned with lower latency than higher throughput:
        c.s.setTcpNoDelay(true);
        c.out.writeInt(Server.BINARY_MAGIC);
        c.out.writeString("nodeToNode");
        c.out.writeBytes(globalState.nodeID, 0, globalState.nodeID.length);
        c.bos.flush();
        byte[] remoteNodeID = new byte[StringHelper.ID_LENGTH];
        c.in.readBytes(remoteNodeID, 0, remoteNodeID.length);
        globalState.addNodeLink(remoteNodeID, c);
        return "{}";
      }
    };
  }  

  @Override
  public String getTopDoc() {
    return "Notify this node that another node has joined the cluster";
  }
}
