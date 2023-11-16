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
import java.util.List;

import org.apache.lucene.index.IndexReader;
import org.apache.lucene.index.LeafReaderContext;
import org.apache.lucene.search.BulkScorer;
import org.apache.lucene.search.CollectionTerminatedException;
import org.apache.lucene.search.Collector;
import org.apache.lucene.search.DocIdSetIterator;
import org.apache.lucene.search.IndexSearcher;
import org.apache.lucene.search.LeafCollector;
import org.apache.lucene.search.Query;
import org.apache.lucene.search.Scorer;
import org.apache.lucene.search.Weight;
import org.apache.lucene.search.join.ToParentBlockJoinQuery;
import org.apache.lucene.util.Bits;

/** This is sadly necessary because for ToParentBlockJoinQuery we must invoke .scorer not .bulkScorer, yet for DrillSideways we must do
 *  exactly the opposite! */

public class MyIndexSearcher extends IndexSearcher {
  public MyIndexSearcher(IndexReader reader) {
    super(reader);
  }

  @Override
  protected void search(List<LeafReaderContext> leaves, Weight weight, Collector collector) throws IOException {

    // nocommit -- removeme?  do we still rely on this Scorer not BulkScorer / getChildren?
    for (LeafReaderContext ctx : leaves) { // search each subreader
      // we force the use of Scorer (not BulkScorer) to make sure
      // that the scorer passed to LeafCollector.setScorer supports
      // Scorer.getChildren -- messy messy!  maybe broken now?
      final LeafCollector leafCollector = collector.getLeafCollector(ctx);
      if (weight.getQuery().toString().contains("DrillSidewaysQuery")) {
        BulkScorer scorer = weight.bulkScorer(ctx);
        if (scorer != null) {
          try {
            scorer.score(leafCollector, ctx.reader().getLiveDocs());
          } catch (CollectionTerminatedException e) {
            // collection was terminated prematurely
            // continue with the following leaf
          }
        }
      } else {
        Scorer scorer = weight.scorer(ctx);
        if (scorer != null) {
          leafCollector.setScorer(scorer);
          final Bits liveDocs = ctx.reader().getLiveDocs();
          final DocIdSetIterator it = scorer.iterator();
          for (int doc = it.nextDoc(); doc != DocIdSetIterator.NO_MORE_DOCS; doc = it.nextDoc()) {
            if (liveDocs == null || liveDocs.get(doc)) {
              leafCollector.collect(doc);
            }
          }
        }
      }

      // Note: this is called if collection ran successfully, including the above special cases of
      // CollectionTerminatedException and TimeExceededException, but no other exception.
      leafCollector.finish();
    }
  }
}
