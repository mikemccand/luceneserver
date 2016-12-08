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
import java.util.List;
import java.util.Map;

import org.apache.lucene.replicator.nrt.CopyState;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;
import org.apache.lucene.store.IOContext;
import org.apache.lucene.store.IndexInput;

/** Sends requested files from this node (primary) to a replica node */
public class SendMeFilesHandler extends Handler {
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
    return "Sends requested files on the wire";
  }

  /** Sole constructor. */
  public SendMeFilesHandler(GlobalState state) {
    super(state);
  }

  @Override
  public void handleBinary(InputStream streamIn, DataInput in, DataOutput out, OutputStream streamOut) throws Exception {
    // which index we will send files from
    String indexName = in.readString();
    IndexState indexState = globalState.getIndex(indexName);
    ShardState shardState = indexState.getShard(0);

    // TODO: we could also allow replica to copy files from another replica, or a peer-to-peer multicast, or something?

    // make sure this index was started as a primary:
    if (shardState.isPrimary() == false) {
      throw new IllegalArgumentException("index \"" + indexName + "\" is not a primary or was not started yet");
    }

    // which replica we are sending files to
    int replicaID = in.readVInt();

    byte b = in.readByte();
    CopyState copyState;
    if (b == 0) {
      // Caller already has CopyState (because it is pre-copying merged files)
      copyState = null;
    } else if (b == 1) {
      // Caller does not have CopyState; we pull the latest NRT point:
      copyState = shardState.nrtPrimaryNode.getCopyState();
      Thread.currentThread().setName("send-R" + replicaID + "-" + copyState.version);
    } else {
      // Protocol error:
      throw new IllegalArgumentException("invalid CopyState byte=" + b);
    }

    try {
      if (copyState != null) {
        // Serialize CopyState on the wire to the client:
        writeCopyState(copyState, out);
        streamOut.flush();
      }

      // nocommit: is there some low-risk zero-copy way to do this?  we just want to pull bytes from the file and put on the wire
      byte[] buffer = new byte[16384];
      int fileCount = 0;
      long totBytesSent = 0;
      while (true) {
        byte done = in.readByte();
        if (done == 1) {
          break;
        } else if (done != 0) {
          throw new IllegalArgumentException("expected 0 or 1 byte but got " + done);
        }

        // Name of the file the replica wants us to send:
        String fileName = in.readString();

        // Starting offset in the file we should start sending bytes from:
        long fpStart = in.readVLong();

        //System.out.println("SendMe: now read file " + fileName + " from fpStart=" + fpStart);

        try (IndexInput file = shardState.indexDir.openInput(fileName, IOContext.DEFAULT)) {
          long len = file.length();
          //message("fetch " + fileName + ": send len=" + len);
          out.writeVLong(len);
          file.seek(fpStart);
          long upto = fpStart;
          while (upto < len) {
            int chunk = (int) Math.min(buffer.length, (len-upto));
            file.readBytes(buffer, 0, chunk);
            out.writeBytes(buffer, 0, chunk);
            upto += chunk;
            totBytesSent += chunk;
          }
        }

        // nocommit validate checksum here, at least if it wasn't a resumed copy?

        fileCount++;
      }

      streamOut.flush();
      
      shardState.nrtPrimaryNode.message("top: done fetch files for R" + replicaID + ": sent " + fileCount + " files; sent " + totBytesSent + " bytes");
    } catch (Throwable t) {
      // nocommit narrow the throwable we catch here
      //t.printStackTrace(System.out);
      shardState.nrtPrimaryNode.message("top: exception during fetch: " + t.getMessage() + "; now close socket");
    } finally {
      if (copyState != null) {
        shardState.nrtPrimaryNode.message("top: fetch: now release CopyState");
        shardState.nrtPrimaryNode.releaseCopyState(copyState);
      }
    }
  }

  /** Pushes CopyState on the wire */
  private static void writeCopyState(CopyState state, DataOutput out) throws IOException {
    // TODO (opto): we could encode to byte[] once when we created the copyState, and then just send same byts to all replicas...
    out.writeVInt(state.infosBytes.length);
    out.writeBytes(state.infosBytes, 0, state.infosBytes.length);
    out.writeVLong(state.gen);
    out.writeVLong(state.version);
    CopyFilesHandler.writeFilesMetaData(out, state.files);

    out.writeVInt(state.completedMergeFiles.size());
    for(String fileName : state.completedMergeFiles) {
      out.writeString(fileName);
    }
    out.writeVLong(state.primaryGen);
  }
}
