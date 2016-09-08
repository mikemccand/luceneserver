package org.apache.lucene.server.handlers;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.util.List;
import java.util.Map;

import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;

/** This is invoked on the primary for an index to record that a new replica is starting */
public class AddReplicaHandler extends Handler {
  private static StructType TYPE = new StructType();

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public boolean binaryRequest() {
    return true;
  }

  @Override
  public void handleBinary(InputStream streamIn, DataInput in, DataOutput out, OutputStream streamOut) throws Exception {
    String indexName = in.readString();
    IndexState state = globalState.get(indexName);
    if (state.isPrimary() == false) {
      throw new IllegalArgumentException("index \"" + indexName + "\" was not started or is not a primary");
    }

    int replicaID = in.readVInt();

    System.out.println("AddReplicaHandler: add indexName=" + indexName);

    // nocommit factor this out into readInetSocketAddress:
    int port = in.readVInt();
    int length = in.readVInt();
    byte[] bytes = new byte[length];
    in.readBytes(bytes, 0, length);

    InetSocketAddress replicaAddress = new InetSocketAddress(InetAddress.getByAddress(bytes), port);
    System.out.println("AddReplicaHandler: now add ID=" + replicaID + " address=" + replicaAddress);
    state.nrtPrimaryNode.addReplica(replicaID, replicaAddress);
  }

  @Override
  public FinishRequest handle(IndexState state, Request request, Map<String,List<String>> params) {
    throw new UnsupportedOperationException();
  }

  @Override
  public String getTopDoc() {
    return "Notifies primary that a new replica is starting";
  }

  /** Sole constructor. */
  public AddReplicaHandler(GlobalState state) {
    super(state);
  }
}
