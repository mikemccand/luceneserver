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

import java.io.BufferedOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.Reader;
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
import org.apache.lucene.search.ScoreDoc;
import org.apache.lucene.search.TopDocs;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.QueryID;
import org.apache.lucene.server.Server;
import org.apache.lucene.server.params.*;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;
import org.apache.lucene.util.IOUtils;
import org.apache.lucene.util.StringHelper;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

/** Holds a persistent binary connection to another node in the cluster; this is the receiving end of the LinkNodeHandler. */

public class NodeToNodeHandler extends Handler {

  private static StructType TYPE = new StructType();

  public static final byte CMD_NEW_QUERY = (byte) 0;

  public static final byte CMD_TAKE_QUERY = (byte) 1;

  /** Hits are being delivered back to us, the coordinating node */
  public static final byte CMD_RECEIVE_HITS = (byte) 2;

  /** Sole constructor. */
  public NodeToNodeHandler(GlobalState state) {
    super(state);
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public boolean binaryRequest() {
    return true;
  }

  @Override
  public void handleBinary(InputStream in, DataInput dataIn, DataOutput out, OutputStream streamOut) throws Exception {
    byte[] remoteNodeID = new byte[StringHelper.ID_LENGTH];
    dataIn.readBytes(remoteNodeID, 0, remoteNodeID.length);
    out.writeBytes(globalState.nodeID, 0, StringHelper.ID_LENGTH);
    // yucky:
    ((BufferedOutputStream) streamOut).flush();

    Search2Handler searchHandler = (Search2Handler) globalState.getHandler("search2");
    assert searchHandler != null;
    
    while (true) {
      int v = in.read();
      if (v == -1) {
        return;
      }

      switch((byte) v) {

      case CMD_NEW_QUERY:
        {
          byte[] queryID = new byte[StringHelper.ID_LENGTH];
          dataIn.readBytes(queryID, 0, queryID.length);
          String indexName = dataIn.readString();
          String queryText = dataIn.readString();
          // TODO: index names/patterns
          globalState.searchQueue.addNewQuery(new QueryID(queryID), indexName, 0, queryText, remoteNodeID);
        }
        break;

      case CMD_TAKE_QUERY:
        {
          byte[] queryID = new byte[StringHelper.ID_LENGTH];
          dataIn.readBytes(queryID, 0, queryID.length);
          if (globalState.searchQueue.takeQuery(new QueryID(queryID), remoteNodeID)) {
            streamOut.write((byte) 1);
          } else {
            streamOut.write((byte) 0);
          }
          streamOut.flush();
        }
        break;

      case CMD_RECEIVE_HITS:
        {
          byte[] queryID = new byte[StringHelper.ID_LENGTH];
          dataIn.readBytes(queryID, 0, queryID.length);
          int totalHits = dataIn.readInt();
          int topNHits = dataIn.readInt();
          ScoreDoc[] hits = new ScoreDoc[topNHits];
          for(int i=0;i<topNHits;i++) {
            int docID = dataIn.readInt();
            float score = Float.intBitsToFloat(dataIn.readInt());
            hits[i] = new ScoreDoc(docID, score);
          }

          searchHandler.deliverHits(new QueryID(queryID), new TopDocs(totalHits, hits, 0.0f));
        }
        break;
        
      default:
        throw new AssertionError("unknown command " + v);
      }
    }      
  }  

  @Override
  public String getTopDoc() {
    return "Handles persistent node to node communication";
  }

  @Override
  public FinishRequest handle(IndexState state, Request r, Map<String,List<String>> params) {
    throw new UnsupportedOperationException();
  }
}
