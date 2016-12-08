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
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Semaphore;

import org.apache.lucene.document.Document;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.Server;
import org.apache.lucene.server.ShardState.IndexingContext;
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.params.Request;
import org.apache.lucene.server.params.StructType;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;

import net.minidev.json.JSONObject;

/** Bulk addDocument from CSV encoding */

public class BulkCSVAddDocumentHandler extends Handler {

  private static StructType TYPE = new StructType();

  /** We break the incoming CSV bytes into chunks of this size and send each chunk off to separate threads for indexing */
  private static final int CHUNK_SIZE_KB = 512;

  /** Sole constructor. */
  public BulkCSVAddDocumentHandler(GlobalState state) {
    super(state);
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public boolean binaryRequest() {
    return true;
  }

  /** Parses and indexes documents from one chunk of CSV */
  private static class ParseAndIndexOneChunk implements Runnable {
    /** Shared context across all docs being indexed in this one stream */
    private final ShardState.IndexingContext ctx;
    
    private final ShardState shardState;
    private final FieldDef[] fields;
    private final byte[] bytes;

    /** Byte starting offset of our chunk in the total incoming byte stream; we use this to locate errors */
    private final long globalOffset;

    /** The job handling the chunk just before us */
    private ParseAndIndexOneChunk prev;

    private int endFragmentStartOffset = -1;

    private byte[] nextStartFragment;
    private int nextStartFragmentOffset;
    private int nextStartFragmentLength;
    private final byte delimChar;
    
    public ParseAndIndexOneChunk(byte delimChar, long globalOffset, ShardState.IndexingContext ctx, ParseAndIndexOneChunk prev, ShardState shardState,
                                 FieldDef[] fields, byte[] bytes) throws InterruptedException {
      this.delimChar = delimChar;
      this.ctx = ctx;
      ctx.inFlightChunks.register();
      this.prev = prev;
      this.shardState = shardState;
      this.fields = fields;
      this.bytes = bytes;
      this.globalOffset = globalOffset;
    }

    /** Indexes the one document that spans across the end of our chunk.  This is invoked when the chunk after us first starts, or when we
     *  finish processing all whole docs in our chunk, whichever comes last. */
    private void indexSplitDoc() throws InterruptedException {
      try {
        _indexSplitDoc();
      } finally {
        shardState.finishIndexingChunk();
        shardState.indexState.globalState.indexingJobsRunning.release();
        ctx.inFlightChunks.arrive();
      }
    }
        
    private void _indexSplitDoc() throws InterruptedException {
      if (endFragmentStartOffset == -2) {
        assert prev != null;
        // nocommit for very large docs this glueing together is O(N^2) ... fix this to be a List<char[]> instead:
        // Our entire chunk was inside a single document; instead of indexing a split doc, we combine our whole fragment and
        // the next start fragment and pass back to the previous chunk:
        byte[] allBytes = new byte[bytes.length + nextStartFragmentLength];
        System.arraycopy(bytes, 0, allBytes, 0, bytes.length);
        System.arraycopy(nextStartFragment, 0, allBytes, bytes.length, nextStartFragmentLength);
        prev.setNextStartFragment(allBytes, 0, allBytes.length);
        prev = null;
        return;
      }

      int endFragmentLength = bytes.length - endFragmentStartOffset;
      if (endFragmentLength + nextStartFragmentLength > 0) {
        byte[] allBytes = new byte[endFragmentLength + nextStartFragmentLength];
        System.arraycopy(bytes, endFragmentStartOffset, allBytes, 0, endFragmentLength);
        System.arraycopy(nextStartFragment, 0, allBytes, endFragmentLength, nextStartFragmentLength);
        //System.out.println("LAST: " + new String(allBytes, StandardCharsets.UTF_8));
        CSVParser parser = new CSVParser(delimChar, globalOffset + endFragmentStartOffset, fields, allBytes, 0);
        Document doc;
        try {
          doc = parser.nextDoc();
        } catch (Throwable t) {
          ctx.setError(new IllegalArgumentException("last document starting at offset " + (globalOffset + endFragmentStartOffset) + " failed to parse", t));
          return;
        }

        if (doc == null) {
          ctx.setError(new IllegalArgumentException("last document starting at offset " + (globalOffset + endFragmentStartOffset) + " is missing the trailing newline"));
          return;
        }

        if (shardState.indexState.hasFacets()) {
          try {
            doc = shardState.indexState.facetsConfig.build(shardState.taxoWriter, doc);
          } catch (IOException ioe) {
            ctx.setError(new RuntimeException("document at offset " + (globalOffset + parser.getLastDocStart()) + " hit exception building facets", ioe));
            return;
          }
        }
        
        ctx.addCount.incrementAndGet();
        try {
          shardState.indexDocument(doc);
        } catch (Throwable t) {
          ctx.setError(new RuntimeException("failed to index document at offset " + (globalOffset + endFragmentStartOffset), t));
          return;
        }
        assert parser.getBufferUpto() == allBytes.length;
      }
    }

    /** The chunk after us calls this with its prefix fragment */
    public synchronized void setNextStartFragment(byte[] bytes, int offset, int length) throws InterruptedException {
      if (nextStartFragment != null) {
        throw new IllegalStateException("setNextStartFragment was already called");
      }
      nextStartFragment = bytes;
      nextStartFragmentOffset = offset;
      nextStartFragmentLength = length;
      if (endFragmentStartOffset != -1) {
        // OK we already know our end fragment; together, these are one document; parse and index it now:
        indexSplitDoc();
      }
    }

    private synchronized void setEndFragment(int offset) throws InterruptedException {
      endFragmentStartOffset = offset;
      if (nextStartFragment != null) {
        indexSplitDoc();
      }
    }

    @Override
    public void run() {
      try {
        _run();
      } catch (Throwable t) {
        System.out.println("FAILED:");
        t.printStackTrace(System.out);
        throw new RuntimeException(t);
      }
    }

    private void _run() throws InterruptedException {

      // find the start of our first document:
      int upto;
      if (prev != null) {
        upto = 0;
        while (upto < bytes.length) {
          if (bytes[upto] == CSVParser.NEWLINE) {
            break;
          }
          upto++;
        }
        //System.out.println("CHUNK @ " + globalOffset + " startFragment=" + upto + " vs len=" + bytes.length);
      } else {
        upto = -1;
      }

      if (upto < bytes.length) {

        // skip the NEWLINE:
        upto++;
        
        if (prev != null) {
          prev.setNextStartFragment(bytes, 0, upto);
          //System.out.println("CHUNK @ " + globalOffset + " done setNextStartFragment");

          // break the link so GC can promptly drop finished chunks:
          prev = null;
        }

        final int startUpto = upto;

        // add all documents in this chunk as a block:
        final int[] endOffset = new int[1];
        try {
          shardState.writer.addDocuments(new Iterable<Document>() {
              @Override
              public Iterator<Document> iterator() {

                // now parse & index whole documents:

                final CSVParser parser = new CSVParser(delimChar, globalOffset, fields, bytes, startUpto);
                final boolean hasFacets = shardState.indexState.hasFacets();

                return new Iterator<Document>() {
                  private Document nextDoc;
                  private boolean nextSet;
                
                  @Override
                  public boolean hasNext() {
                    if (nextSet == false) {
                      try {
                        nextDoc = parser.nextDoc();
                      } catch (Throwable t) {
                        System.out.println("GOT ERROR: " + t);
                        ctx.setError(t);
                        nextDoc = null;
                      }
                      if (nextDoc != null) {
                        ctx.addCount.incrementAndGet();
                        if (hasFacets) {
                          try {
                            nextDoc = shardState.indexState.facetsConfig.build(shardState.taxoWriter, nextDoc);
                          } catch (IOException ioe) {
                            ctx.setError(new RuntimeException("document at offset " + (globalOffset + parser.getLastDocStart()) + " hit exception building facets", ioe));
                            nextDoc = null;
                          }
                        }
                        // nocommit: live field values
                      } else {
                        endOffset[0] = parser.getLastDocStart();
                      }
                      nextSet = true;
                    }
                    return nextDoc != null;
                  }

                  @Override
                  public Document next() {
                    assert nextSet;
                    try {
                      return nextDoc;
                    } finally {
                      nextSet = false;
                      nextDoc = null;
                    }
                  }
                };
              }
            });
        } catch (Throwable t) {
          ctx.setError(t);
        }

        //System.out.println("CHUNK @ " + globalOffset + ": done parsing; end fragment length=" + (bytes.length-offset));
        setEndFragment(endOffset[0]);
        
      } else {
        // exotic case: the entire chunk is inside one document
        setEndFragment(-2);
        // nocommit also handle the exotic case where the chunk split right at a doc boundary
      }
    }
  }

  @Override
  public void handleBinary(InputStream in, DataInput dataIn, DataOutput out, OutputStream streamOut) throws Exception {

    int v = in.read();
    if (v == -1) {
      throw new IllegalArgumentException("first byte should be delimiter character");
    }
    byte delimChar = (byte) v;
    if (delimChar != (byte) ',' && delimChar != (byte) '\t') {
      throw new IllegalArgumentException("delimiter character should be comma or tab; got: " + v);
    }

    // parse index name and fields header and lookup fields:
    List<FieldDef> fieldsList = new ArrayList<>();
    StringBuilder curField = new StringBuilder();
    long globalOffset = 0;

    byte[] buffer = new byte[1024];
    int bufferUpto = 0;
    int bufferLimit = 0;
    IndexState indexState = null;
    while (true) {
      if (bufferUpto == bufferLimit) {
        globalOffset += bufferLimit;
        bufferLimit = in.read(buffer, 0, buffer.length);
        if (bufferLimit == -1) {
          throw new IllegalArgumentException("hit end while parsing header");
        }
        bufferUpto = 0;
      }
      byte b = buffer[bufferUpto++];
      if (b == delimChar) {
        if (indexState == null) {
          throw new IllegalArgumentException("first line must be the index name");
        }
        fieldsList.add(indexState.getField(curField.toString()));
        curField.setLength(0);
      } else if (b == CSVParser.NEWLINE) {
        if (indexState == null) {
          String indexName = curField.toString();
          indexState = globalState.getIndex(indexName);
          if (indexState.isStarted() == false) {
            throw new IllegalArgumentException("index \"" + indexName + "\" isn't started: cannot index documents");
          }
          curField.setLength(0);
        } else {
          fieldsList.add(indexState.getField(curField.toString()));
          break;
        }
      } else {
        // index and field names are simple ascii:
        curField.append((char) b);
      }
    }

    FieldDef[] fields = fieldsList.toArray(new FieldDef[fieldsList.size()]);

    IndexingContext ctx = new IndexingContext();
    byte[] bufferOld = buffer;

    // nocommit tune this .. core count?

    // Use this to limit how many in-flight 256 KB chunks we allow into the JVM at once:

    boolean done = false;

    // create first chunk buffer, and carry over any leftovers from the header processing:
    buffer = new byte[CHUNK_SIZE_KB*1024];
    System.arraycopy(bufferOld, bufferUpto, buffer, 0, bufferLimit-bufferUpto);
    bufferUpto = bufferLimit - bufferUpto;

    globalOffset += bufferUpto;
    
    ParseAndIndexOneChunk prev = null;
    int phase = ctx.inFlightChunks.getPhase();

    ShardState lastShardState = null;

    while (done == false && ctx.getError() == null) {
      int count = in.read(buffer, bufferUpto, buffer.length-bufferUpto);
      if (count == -1 || bufferUpto + count == buffer.length) {
        if (count != -1) {
          bufferUpto += count;
        }
        if (bufferUpto < buffer.length) {
          byte[] realloc = new byte[bufferUpto];
          System.arraycopy(buffer, 0, realloc, 0, bufferUpto);
          buffer = realloc;
        }
        lastShardState = indexState.getWritableShard();
        prev = new ParseAndIndexOneChunk(delimChar, globalOffset, ctx, prev, lastShardState, fields, buffer);

        // NOTE: This will stall when it tries to acquire the global state semaphore if we already have too many in-flight indexing chunks:
        globalState.submitIndexingTask(prev);
        if (count == -1) {
          // the end
          prev.setNextStartFragment(new byte[0], 0, 0);
          done = true;
          break;
        } else {
          globalOffset += buffer.length;
          // not done yet, make the next buffer:
          buffer = new byte[CHUNK_SIZE_KB*1024];
          bufferUpto = 0;
        }
      } else {
        bufferUpto += count;
      }
    }

    if (done == false) {
      // we exited loop due to error; force last indexing chunk to finish up:
      prev.setNextStartFragment(new byte[0], 0, 0);
    }

    ctx.inFlightChunks.awaitAdvance(phase);

    Throwable t = ctx.getError();
    if (t != null) {
      String message = Server.throwableTraceToString(t);
      byte[] bytes = message.getBytes("UTF-8");
      out.writeByte((byte) 1);
      out.writeInt(bytes.length);
      out.writeBytes(bytes, 0, bytes.length);
    } else {
      JSONObject o = new JSONObject();
      // nocommit how to do sequence number across shards?
      o.put("indexGen", lastShardState.writer.getMaxCompletedSequenceNumber());
      o.put("indexedDocumentCount", ctx.addCount.get());

      byte[] bytes = o.toString().getBytes(StandardCharsets.UTF_8);
      out.writeByte((byte) 0);
      out.writeInt(bytes.length);
      out.writeBytes(bytes, 0, bytes.length);
    }
    streamOut.flush();
  }

  @Override
  public String getTopDoc() {
    return "Add more than one document in a single request, encoded as CSV.";
  }

  @Override
  public FinishRequest handle(IndexState state, Request r, Map<String,List<String>> params) {
    throw new UnsupportedOperationException();
  }
}
