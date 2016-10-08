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
import java.io.PrintStream;
import java.net.InetSocketAddress;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

import org.apache.lucene.replicator.nrt.CopyJob;
import org.apache.lucene.replicator.nrt.CopyState;
import org.apache.lucene.replicator.nrt.FileMetaData;
import org.apache.lucene.replicator.nrt.NodeCommunicationException;
import org.apache.lucene.replicator.nrt.ReplicaNode;
import org.apache.lucene.search.SearcherFactory;
import org.apache.lucene.server.handlers.CopyFilesHandler;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.Directory;

public class NRTReplicaNode extends ReplicaNode {

  InetSocketAddress primaryAddress;

  InetSocketAddress localAddress;
  final String indexName;
  final Jobs jobs;

  public NRTReplicaNode(String indexName, InetSocketAddress primaryAddress, InetSocketAddress localAddress, int id, Directory dir,
                        SearcherFactory searcherFactory, PrintStream printStream, long primaryGen) throws IOException {
    super(id, dir, searcherFactory, printStream);
    this.indexName = indexName;
    assert IndexState.isSimpleName(indexName);
    this.localAddress = localAddress;
    this.primaryAddress = primaryAddress;

    // Handles fetching files from primary:
    jobs = new Jobs(this);
    jobs.setName("R" + id + ".copyJobs");
    jobs.setDaemon(true);
    jobs.start();

    start(primaryGen);
  }
  
  public CopyJob launchPreCopyFiles(AtomicBoolean finished, long curPrimaryGen, Map<String,FileMetaData> files) throws IOException {
    return launchPreCopyMerge(finished, curPrimaryGen, files);
  }

  @Override
  public void close() throws IOException {
    jobs.close();
    System.out.println("CLOSE NRT REPLICA");
    message("top: jobs closed");
    synchronized(mergeCopyJobs) {
      for (CopyJob job : mergeCopyJobs) {
        message("top: cancel merge copy job " + job);
        job.cancel("jobs closing", null);
      }
    }
    super.close();
  }

  /** Pulls CopyState off the wire */
  private static CopyState readCopyState(DataInput in) throws IOException {

    // Decode a new CopyState
    byte[] infosBytes = new byte[in.readVInt()];
    in.readBytes(infosBytes, 0, infosBytes.length);

    long gen = in.readVLong();
    long version = in.readVLong();
    Map<String,FileMetaData> files = CopyFilesHandler.readFilesMetaData(in);

    int count = in.readVInt();
    Set<String> completedMergeFiles = new HashSet<>();
    for(int i=0;i<count;i++) {
      completedMergeFiles.add(in.readString());
    }
    long primaryGen = in.readVLong();

    return new CopyState(files, version, gen, infosBytes, completedMergeFiles, primaryGen, null);
  }

  @Override
  protected CopyJob newCopyJob(String reason, Map<String,FileMetaData> files, Map<String,FileMetaData> prevFiles,
                               boolean highPriority, CopyJob.OnceDone onceDone) throws IOException {

    // TODO: we should instead keep a persistent connection between nodes instead of opening new socket every time for each copy job:

    CopyState copyState;
    Connection c;

    // Exceptions in here mean something went wrong talking over the socket, which are fine (e.g. primary node crashed):
    try {
      c = new Connection(primaryAddress);
      c.out.writeInt(Server.BINARY_MAGIC);
      c.out.writeString("sendMeFiles");
      c.out.writeString(indexName);
      c.out.writeVInt(id);
      c.flush();

      if (files == null) {
        // No incoming CopyState: ask primary for latest one now
        c.out.writeByte((byte) 1);
        c.flush();
        copyState = readCopyState(c.in);
        files = copyState.files;
      } else {
        c.out.writeByte((byte) 0);
        copyState = null;
      }
    } catch (Throwable t) {
      throw new NodeCommunicationException("exc while reading files to copy", t);
    }

    return new SimpleCopyJob(reason, c, copyState, this, files, highPriority, onceDone);
  }

  @Override
  protected void sendNewReplica() throws IOException {
    message("send new_replica to primary tcpPort=" + primaryAddress.getPort() + " localAddress=" + localAddress);
    try (Connection c = new Connection(primaryAddress)) {
      c.out.writeInt(Server.BINARY_MAGIC);
      c.out.writeString("addReplica");
      c.out.writeString(indexName);
      c.out.writeVInt(id);
      
      c.out.writeVInt(localAddress.getPort());
      byte[] bytes = localAddress.getAddress().getAddress();
      c.out.writeVInt(bytes.length);
      c.out.writeBytes(bytes, 0, bytes.length);
      System.out.println("done send new_replica");
      c.flush();
      
    } catch (Throwable t) {
      System.out.println("GOT:");
      t.printStackTrace(System.out);
      message("ignoring exc " + t + " sending new_replica to primary address=" + primaryAddress);
    }
  }

  @Override
  protected void launch(CopyJob job) {
    jobs.launch(job);
  }
}
