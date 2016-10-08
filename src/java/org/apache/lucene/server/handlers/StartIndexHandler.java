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
import org.apache.lucene.index.IndexReader;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.params.EnumType;
import org.apache.lucene.server.params.IntType;
import org.apache.lucene.server.params.LongType;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;

import net.minidev.json.JSONObject;

/** Handles {@code startIndex}. */
public class StartIndexHandler extends Handler {
  private static StructType TYPE = new StructType(
                                       new Param("indexName", "Index name", new StringType()),
                                       new Param("mode", "Standalone or NRT primary/replica",
                                                 new EnumType("standalone", "Standalone index",
                                                              "primary", "Primary index, replicating changes to zero or more replicas",
                                                              "replica", "Replica index"),
                                                 "standalone"),
                                       new Param("primaryGen", "For mode=primary, the generation of this primary (should increment each time a new primary starts for this index)", new LongType()),
                                       new Param("primaryAddress", "For mode=replica, the IP address or host name of the remote primary", new StringType()),
                                       new Param("primaryPort", "For mode=replica, the TCP port of the remote primary", new IntType())
                                                 );
  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public String getTopDoc() {
    return "Starts an index";
  }

  /** Sole constructor. */
  public StartIndexHandler(GlobalState state) {
    super(state);
  }

  @Override
  public FinishRequest handle(final IndexState indexState, final Request r, Map<String,List<String>> params) throws Exception {
    final ShardState shardState = indexState.getShard(0);
    
    final String mode = r.getEnum("mode");
    final long primaryGen;
    final String primaryAddress;
    final int primaryPort;
    if (mode.equals("primary")) {
      primaryGen = r.getLong("primaryGen");
      primaryAddress = null;
      primaryPort = -1;
    } else if (mode.equals("replica")) {
      primaryGen = r.getLong("primaryGen");
      primaryAddress = r.getString("primaryAddress");
      primaryPort = r.getInt("primaryPort");
    } else {
      primaryGen = -1;
      primaryAddress = null;
      primaryPort = -1;
    }

    return new FinishRequest() {
      @Override
      public String finish() throws Exception {
        long t0 = System.nanoTime();
        if (mode.equals("primary")) {
          shardState.startPrimary(primaryGen);
        } else if (mode.equals("replica")) {
          // nocommit can we use "caller ID" instead somehow?  rob says this is much better!
          shardState.startReplica(new InetSocketAddress(primaryAddress, primaryPort), primaryGen);
        } else {
          indexState.start();
        }
        JSONObject result = new JSONObject();
        SearcherAndTaxonomy s = shardState.acquire();
        try {
          IndexReader r = s.searcher.getIndexReader();
          result.put("maxDoc", r.maxDoc());
          result.put("numDocs", r.numDocs());
          result.put("segments", r.toString());
        } finally {
          shardState.release(s);
        }
        long t1 = System.nanoTime();
        result.put("startTimeMS", ((t1-t0)/1000000.0));

        return result.toString();
      }
    };
  }
}
