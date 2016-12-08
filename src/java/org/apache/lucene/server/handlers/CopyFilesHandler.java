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
import java.io.InputStream;
import java.io.OutputStream;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import org.apache.lucene.replicator.nrt.CopyJob;
import org.apache.lucene.replicator.nrt.FileMetaData;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;

/*
  Primary/replica communications:

    - at any given moment, primary knows the replicas it should push changes to, and replica knows the current primary

    - every time a new primary is started, the primaryGen (a long) is incremented, so replicas can always know if they are talking to a new
      primary e.g. after crashing and starting up again

    - someone asks primary to make a new NRT point (could be external or just on a self schedule like once per second)

    - primary writes all docs to new segments, makes a new in-memory SegmentInfos

    - primary sends copyFiles command to all known replicas

    - each replica sends sendMeFiles command to primary, asking for the latest copyState, which is an incRef'd set of files referenced by
      the current in-memory SegmentInfos

    - each replica diffs the file set against what it already has in its index and copies the new files

    - when copy is done, replica switches local searcher manager to new NRT point, and primary decRefs the copyState.  replica also decRefs
      old nrt point

    - on primary, when merge finishes, we "warm" by sending copyFiles to all replicas, with the files for the newly merged segment; replica
      then sends sendMeFiles back to primary, copying those merged files

    - if replica crashes, primary just removes it from the list of replicas it notifies of new nrt points or new merges

    - when replica finally comes back up, possibly much later, it does a sendMeFiles as it would for a new nrt point.  if the primary had
      changed while the replica was down, it's possible replica must delete its commit points before copying files to prevent an apparent
      index corruption if the replica crashes again while it is copying.  TODO: if replica then starts again, with no segments file in the
      index, are we then forced to do a full index copy?

    - if primary crashes, whichever replica has the newest NRT point is picked as the new primary

    - TODO: when primary crashes

*/

// nocommit it's silly to separate copyFiles and sendMeFiles?  we should do it in one connection instead ... or more generally just re-use
// binary connections for more than one command

/** Primary invokes this on a replica to ask it to copy files */
public class CopyFilesHandler extends Handler {
  private static StructType TYPE = new StructType();

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public FinishRequest handle(IndexState state, Request request, Map<String,List<String>> params) {
    throw new UnsupportedOperationException();
  }

  @Override
  public boolean binaryRequest() {
    return true;
  }

  @Override
  public String getTopDoc() {
    return "Copy files from this replica's primary to the local index directory";
  }

  /** Sole constructor. */
  public CopyFilesHandler(GlobalState state) {
    super(state);
  }

  public static void writeFilesMetaData(DataOutput out, Map<String,FileMetaData> files) throws IOException {
    out.writeVInt(files.size());
    for(Map.Entry<String,FileMetaData> ent : files.entrySet()) {
      out.writeString(ent.getKey());

      FileMetaData fmd = ent.getValue();
      out.writeVLong(fmd.length);
      out.writeVLong(fmd.checksum);
      out.writeVInt(fmd.header.length);
      out.writeBytes(fmd.header, 0, fmd.header.length);
      out.writeVInt(fmd.footer.length);
      out.writeBytes(fmd.footer, 0, fmd.footer.length);
    }
  }

  public static Map<String,FileMetaData> readFilesMetaData(DataInput in) throws IOException {
    int fileCount = in.readVInt();
    //System.out.println("readFilesMetaData: fileCount=" + fileCount);
    Map<String,FileMetaData> files = new HashMap<>();
    for(int i=0;i<fileCount;i++) {
      String fileName = in.readString();
      //System.out.println("readFilesMetaData: fileName=" + fileName);
      long length = in.readVLong();
      long checksum = in.readVLong();
      byte[] header = new byte[in.readVInt()];
      in.readBytes(header, 0, header.length);
      byte[] footer = new byte[in.readVInt()];
      in.readBytes(footer, 0, footer.length);
      files.put(fileName, new FileMetaData(header, footer, length, checksum));
    }
    return files;
  }

  @Override
  public void handleBinary(InputStream streamIn, DataInput in, DataOutput out, OutputStream streamOut) throws Exception {

    String indexName = in.readString();
    IndexState state = globalState.getIndex(indexName);
    ShardState shardState = state.getShard(0);
    if (shardState.isReplica() == false) {
      throw new IllegalArgumentException("index \"" + indexName + "\" is not a replica or was not started yet");
    }

    long primaryGen = in.readVLong();

    // these are the files that the remote (primary) wants us to copy
    Map<String,FileMetaData> files = readFilesMetaData(in);

    AtomicBoolean finished = new AtomicBoolean();
    CopyJob job = shardState.nrtReplicaNode.launchPreCopyFiles(finished, primaryGen, files);

    // we hold open this request, only finishing/closing once our copy has finished, so primary knows when we finished
    while (true) {
      // nocommit don't poll!  use a condition...
      if (finished.get()) {
        break;
      }
      Thread.sleep(10);
      // TODO: keep alive mechanism so primary can better "guess" when we dropped off
    }

    out.writeByte((byte) 1);
    streamOut.flush();
  }
}
