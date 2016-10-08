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

import java.net.InetSocketAddress;
import java.util.List;
import java.util.Map;

import org.apache.lucene.facet.taxonomy.SearcherTaxonomyManager.SearcherAndTaxonomy;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.server.Connection;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.Server;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;

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
  public FinishRequest handle(final IndexState indexState, final Request r, Map<String,List<String>> params) throws Exception {

    final ShardState shardState = indexState.getShard(0);
    
    if (shardState.isPrimary() == false) {
      throw new IllegalArgumentException("index \"" + shardState.name + "\" is either not started or is not a primary index");
    }
    
    return new FinishRequest() {
      @Override
      public String finish() throws Exception {
        if (shardState.nrtPrimaryNode.flushAndRefresh()) {
          // Something did get flushed (there were indexing ops since the last flush):

          // nocommit: we used to notify caller of the version, before trying to push to replicas, in case we crash after flushing but
          // before notifying all replicas, at which point we have a newer version index than client knew about?
          long version = shardState.nrtPrimaryNode.getCopyStateVersion();

          int[] replicaIDs;
          InetSocketAddress[] replicaAddresses;
          synchronized (shardState.nrtPrimaryNode) {
            replicaIDs = shardState.nrtPrimaryNode.replicaIDs;
            replicaAddresses = shardState.nrtPrimaryNode.replicaAddresses;
          }

          shardState.nrtPrimaryNode.message("send flushed version=" + version + " replica count " + replicaIDs.length);

          // Notify current replicas:
          for(int i=0;i<replicaIDs.length;i++) {
            int replicaID = replicaIDs[i];
            try (Connection c = new Connection(replicaAddresses[i])) {
              shardState.nrtPrimaryNode.message("send NEW_NRT_POINT to R" + replicaID + " at address=" + replicaAddresses[i]);
              c.out.writeInt(Server.BINARY_MAGIC);
              c.out.writeString("newNRTPoint");
              c.out.writeString(indexState.name);
              c.out.writeVLong(version);
              c.out.writeVLong(shardState.nrtPrimaryNode.getPrimaryGen());
              c.flush();
              // TODO: we should use multicast to broadcast files out to replicas
              // TODO: ... replicas could copy from one another instead of just primary
              // TODO: we could also prioritize one replica at a time?
            } catch (Throwable t) {
              shardState.nrtPrimaryNode.message("top: failed to connect R" + replicaID + " for newNRTPoint; skipping: " + t.getMessage());
            }
          }
          
          return "{\"version\": " + version + ", \"didRefresh\": true}";
        } else {
          SearcherAndTaxonomy s = shardState.acquire();
          try {
            return "{\"version\": " + ((DirectoryReader) s.searcher.getIndexReader()).getVersion() + ", \"didRefresh\": false}";
          } finally {
            shardState.release(s);
          }
        }
      }
    };
  }
}
