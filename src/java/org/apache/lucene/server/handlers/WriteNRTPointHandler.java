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
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.util.List;
import java.util.Map;

import org.apache.lucene.facet.taxonomy.SearcherTaxonomyManager.SearcherAndTaxonomy;
import org.apache.lucene.index.IndexReader;
import org.apache.lucene.server.Connection;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.Server;
import org.apache.lucene.server.params.IntType;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;

import net.minidev.json.JSONObject;

/** Invoked externally to primary, to make all recent index operations searchable on the primary and, once copying is done, on the replicas */
public class WriteNRTPointHandler extends Handler {
  private static StructType TYPE = new StructType(
                                                  new Param("indexName", "Index name", new StringType()));

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public String getTopDoc() {
    return "Make all recent index operations searchable";
  }

  /** Sole constructor. */
  public WriteNRTPointHandler(GlobalState state) {
    super(state);
  }

  @Override
  public FinishRequest handle(final IndexState state, final Request r, Map<String,List<String>> params) throws Exception {

    if (state.isPrimary() == false) {
      throw new IllegalArgumentException("index \"" + state.name + "\" is either not started or is not a primary index");
    }
    
    return new FinishRequest() {
      @Override
      public String finish() throws Exception {
        System.out.println("WriteNRTPoint: run");
        if (state.nrtPrimaryNode.flushAndRefresh()) {
          System.out.println("WriteNRTPoint: did write");
          // Something did get flushed (there were indexing ops since the last flush):

          // nocommit: we used to notify caller of the version, before trying to push to replicas, in case we crash after flushing but
          // before notifying all replicas, at which point we have a newer version index than client knew about?
          long version = state.nrtPrimaryNode.getCopyStateVersion();

          int[] replicaIDs;
          InetSocketAddress[] replicaAddresses;
          synchronized (state.nrtPrimaryNode) {
            replicaIDs = state.nrtPrimaryNode.replicaIDs;
            replicaAddresses = state.nrtPrimaryNode.replicaAddresses;
          }

          state.nrtPrimaryNode.message("send flushed version=" + version + " replica count " + replicaIDs.length);

          // Notify current replicas:
          for(int i=0;i<replicaIDs.length;i++) {
            int replicaID = replicaIDs[i];
            try (Connection c = new Connection(replicaAddresses[i])) {
              state.nrtPrimaryNode.message("send NEW_NRT_POINT to R" + replicaID + " at address=" + replicaAddresses[i]);
              c.out.writeInt(Server.BINARY_MAGIC);
              c.out.writeString("newNRTPoint");
              c.out.writeString(state.name);
              c.out.writeVLong(version);
              c.out.writeVLong(state.nrtPrimaryNode.getPrimaryGen());
              c.flush();
              // TODO: we should use multicast to broadcast files out to replicas
              // TODO: ... replicas could copy from one another instead of just primary
              // TODO: we could also prioritize one replica at a time?
            } catch (Throwable t) {
              state.nrtPrimaryNode.message("top: failed to connect R" + replicaID + " for newNRTPoint; skipping: " + t.getMessage());
            }
          }
          
          return "{\"version\": " + version + "}";
        } else {
          return "{\"version\": -1}";
        }
      }
    };
  }
}
