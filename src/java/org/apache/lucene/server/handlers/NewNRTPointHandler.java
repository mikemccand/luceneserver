package org.apache.lucene.server.handlers;

import java.io.InputStream;
import java.io.OutputStream;
import java.util.List;
import java.util.Map;

import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.params.Param;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StringType;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;

/** Invoked externally to replica, to notify it that a new NRT point was just created on the primary */
public class NewNRTPointHandler extends Handler {
  private static StructType TYPE = new StructType(
                                                  new Param("indexName", "Index name", new StringType()));

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public String getTopDoc() {
    return "Notifies replica that primary has just finished creating a new NRT point";
  }

  /** Sole constructor. */
  public NewNRTPointHandler(GlobalState state) {
    super(state);
  }

  /** True if this handler should be given a {@link DataInput} to read. */
  public boolean binaryRequest() {
    return true;
  }

  @Override
  public FinishRequest handle(final IndexState state, final Request r, Map<String,List<String>> params) throws Exception {
    throw new UnsupportedOperationException();
  }

  @Override
  public void handleBinary(InputStream streamIn, DataInput in, DataOutput out, OutputStream streamOut) throws Exception {

    String indexName = in.readString();
    IndexState state = globalState.get(indexName);
    if (state.isReplica() == false) {
      throw new IllegalArgumentException("index \"" + indexName + "\" is not a replica or was not started yet");
    }

    long version = in.readVLong();
    long newPrimaryGen = in.readVLong();
    state.nrtReplicaNode.newNRTPoint(newPrimaryGen, version);
  }
}
