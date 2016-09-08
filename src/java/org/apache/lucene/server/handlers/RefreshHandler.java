package org.apache.lucene.server.handlers;

import java.util.List;
import java.util.Map;

import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;

import net.minidev.json.JSONObject;

/** Handles {@code refresh}. */
public class RefreshHandler extends Handler {
  private static StructType TYPE = new StructType(
                                       new Param("indexName", "Index name", new StringType()));

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public String getTopDoc() {
    return "Refresh the latest searcher for an index";
  }

  /** Sole constructor. */
  public RefreshHandler(GlobalState state) {
    super(state);
  }

  @Override
  public FinishRequest handle(final IndexState state, final Request r, Map<String,List<String>> params) throws Exception {
    return new FinishRequest() {
      @Override
      public String finish() throws Exception {
        long t0 = System.nanoTime();
        JSONObject result = new JSONObject();
        state.maybeRefreshBlocking();
        long t1 = System.nanoTime();
        result.put("refreshTimeMS", ((t1-t0)/1000000.0));
        return result.toString();
      }
    };
  }
}
