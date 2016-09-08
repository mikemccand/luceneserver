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

/** Handles {@code indexStatus}. */
public class IndexStatusHandler extends Handler {
  private static StructType TYPE = new StructType(
                                       new Param("indexName", "Index name", new StringType()));
  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public String getTopDoc() {
    return "Returns index status (started or stopped)";
  }

  /** Sole constructor. */
  public IndexStatusHandler(GlobalState state) {
    super(state);
  }

  @Override
  public FinishRequest handle(final IndexState state, final Request r, Map<String,List<String>> params) throws Exception {

    return new FinishRequest() {
      @Override
      public String finish() throws Exception {
        JSONObject result = new JSONObject();
        result.put("status", state.isStarted() ? "started" : "stopped");
        return result.toString();
      }
    };
  }
}
