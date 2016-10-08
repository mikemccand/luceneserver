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

import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.apache.lucene.server.handlers.NodeToNodeHandler;
import org.apache.lucene.util.StringHelper;

public class SearchQueue {

  private final Map<QueryID,QueryAndID> queryQueue = new HashMap<>();

  // nocommit must prune this sometimes!!:
  private final List<QueryAndID> queryDone = new ArrayList<>();

  private final GlobalState globalState;

  public SearchQueue(GlobalState globalState) {
    this.globalState = globalState;
  }

  /** Enroll a new query into the queue */
  public synchronized void addNewQuery(QueryID queryID, String indexName, int shardOrd, String text, byte[] returnNodeID) {
    //System.out.println("ADD NEW QUERY: " + StringHelper.idToString(id) + " text=" + text);
    QueryAndID query = queryQueue.remove(queryID);
    if (query != null) {
      assert query.state == 1;
      assert query.nodeID != null;
      query.returnNodeID = returnNodeID;
      query.text = text;
      queryDone.add(query);
    } else {
      queryQueue.put(queryID, new QueryAndID(queryID, indexName, shardOrd, text, returnNodeID));
      notify();
    }
  }

  public synchronized boolean takeQuery(QueryID queryID, byte[] remoteNodeID) {
    QueryAndID query = queryQueue.get(queryID);
    if (query == null) {
      // this is a new query (we haven't yet heard about it); in this case we enroll the query in the queue as taken; when the addQuery is
      // finally called, we see that it was already taken and move to the done queue
      query = new QueryAndID(queryID, null, 0, null, null);
      query.state = 1;
      query.nodeID = remoteNodeID;
      queryQueue.put(queryID, query);
      return true;
    } else if (query.state <= 1 || StringHelper.compare(StringHelper.ID_LENGTH, remoteNodeID, 0, globalState.nodeID, 0) < 0) {
      // break race conditions by letting lower-ID'd node win
      assert query.nodeID == null;
      query.nodeID = remoteNodeID;
      queryQueue.remove(queryID);
      queryDone.add(query);
      return true;
    } else {
      assert StringHelper.compare(StringHelper.ID_LENGTH, remoteNodeID, 0, globalState.nodeID, 0) != 0: "node IDs are not unique?";
      return false;
    }
  }

  public synchronized void finishedQuery(QueryID queryID) {
    QueryAndID query = queryQueue.remove(queryID);
    query.nodeID = globalState.nodeID;
    queryDone.add(query);
  }

  /** Pops the next query to run from the distributed query queue, waiting if the queue is empty. */
  public QueryAndID takeNextQuery() throws IOException {

    nextQuery:

    while (true) {
      // First find a query and mark it as taken, but do not remove from the queue yet, until we've convinced all other nodes that it's ours:
      QueryAndID theQuery = null;

      synchronized (this) {
        // nocommit make it FIFO (LinkedHashMap?) instead:
        for(QueryAndID query : queryQueue.values()) {
          // nocommit maybe also validate that the indexGen/searcherVersion is present on this node:
          if (query.state == 0 && globalState.hasIndex(query.indexName, query.shardOrd)) {
            theQuery = query;
            query.state = 2;
            break;
          }
        }
        //System.out.println("TAKE QUERY: got " + theQuery);
        if (theQuery == null) {
          try {
            wait();
          } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            throw new RuntimeException(ie);
          }
          continue;
        }
      }

      // TODO: use futures to do all this concurrently:
      // Next, confirm all other nodes are willing to let us take this query:
      for(RemoteNodeConnection node : globalState.remoteNodes) {
        synchronized(node.c) {
          node.c.out.writeByte(NodeToNodeHandler.CMD_TAKE_QUERY);
          node.c.out.writeBytes(theQuery.id.id, 0, theQuery.id.id.length);
          node.c.bos.flush();
          byte result = node.c.in.readByte();
          if (result == 0) {
            // rejected: the other node will run this query
            continue nextQuery;
          }
        }
      }

      // We run the query!
      //System.out.println("NODE " + StringHelper.idToString(nodeID) + " run query " + theQuery.id);

      return theQuery;
    }
  }

  public static class QueryAndID {
    public final QueryID id;
    public final String indexName;
    public final int shardOrd;
    public String text;
    // 0 = unclaimed
    // 1 = remote node claimed
    // 2 = my node claimed
    volatile int state;

    // nodeID that's running this query
    volatile byte[] nodeID;

    public volatile byte[] returnNodeID;

    public QueryAndID(QueryID id, String indexName, int shardOrd, String text, byte[] returnNodeID) {
      this.indexName = indexName;
      this.shardOrd = shardOrd;
      this.id = id;
      this.text = text;
      this.returnNodeID = returnNodeID;
    }
  }
}
