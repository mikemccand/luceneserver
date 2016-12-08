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
import java.util.List;
import java.util.Map;

import org.apache.lucene.facet.taxonomy.SearcherTaxonomyManager.SearcherAndTaxonomy;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.search.IndexSearcher;
import org.apache.lucene.search.SearcherLifetimeManager;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

/** Handles {@code stats}. */
public class StatsHandler extends Handler {

  StructType TYPE = new StructType(new Param("indexName", "Index name", new StringType()));

  @Override
  public String getTopDoc() {
    return "Retrieve index statistics.";
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  /** Sole constructor. */
  public StatsHandler(GlobalState state) {
    super(state);
  }

  @Override
  public FinishRequest handle(final IndexState indexState, final Request r, Map<String,List<String>> params) throws Exception {
    return new FinishRequest() {
      @Override
      public String finish() throws IOException {
        JSONObject result = new JSONObject();
        JSONArray shards = new JSONArray();
        result.put("shards", shards);
        for(Map.Entry<Integer,ShardState> ent : indexState.shards.entrySet()) {
          ShardState shardState = ent.getValue();
          JSONObject shard = new JSONObject();
          shards.add(shard);
          shard.put("ord", ent.getKey());
          shard.put("maxDoc", shardState.maxDoc());

          final JSONObject searchers = new JSONObject();
          shard.put("searchers", searchers);

          // TODO: snapshots

          // TODO: go per segment and print more details, and
          // only print segment for a given searcher if it's
          // "new"

          // Doesn't actually prune; just gathers stats
          shardState.slm.prune(new SearcherLifetimeManager.Pruner() {
              @Override
              public boolean doPrune(double ageSec, IndexSearcher searcher) {
                JSONObject s = new JSONObject();
                searchers.put(Long.toString(((DirectoryReader) searcher.getIndexReader()).getVersion()), s);
                s.put("staleAgeSeconds", ageSec);
                s.put("segments", searcher.getIndexReader().toString());
                s.put("maxDoc", searcher.getIndexReader().maxDoc());
                return false;
              }
            });

          JSONObject curSearcher = new JSONObject();
          shard.put("currentSearcher", curSearcher);
          shard.put("state", shardState.getState());

          JSONObject taxo = new JSONObject();
          shard.put("taxonomy", taxo);
        
          SearcherAndTaxonomy s = shardState.acquire();
          try {
            taxo.put("segments", s.taxonomyReader.toString());
            taxo.put("numOrds", s.taxonomyReader.getSize());
            curSearcher.put("segments", s.searcher.toString());
          } finally {
            shardState.release(s);
          }
        }

        // nocommit cached filters from index searchers?

        return result.toString();
      }
    };
  }
}
