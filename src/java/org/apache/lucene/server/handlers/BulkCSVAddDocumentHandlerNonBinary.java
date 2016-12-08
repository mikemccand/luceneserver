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
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Semaphore;

import org.apache.lucene.document.BinaryDocValuesField;
import org.apache.lucene.document.BinaryPoint;
import org.apache.lucene.document.Document;
import org.apache.lucene.document.SortedDocValuesField;
import org.apache.lucene.document.SortedSetDocValuesField;
import org.apache.lucene.document.StringField;
import org.apache.lucene.document.TextField;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.Server;
import org.apache.lucene.server.ShardState;
import org.apache.lucene.server.params.*;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;
import org.apache.lucene.util.IOUtils;
import org.apache.lucene.util.IOUtils;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

/** Bulk addDocument from CSV encoding */

public class BulkCSVAddDocumentHandlerNonBinary extends Handler {

  private static StructType TYPE = new StructType();

  /** We break the incoming CSV chars into chunks of this size and send each chunk off to separate threads for parsing and indexing */
  private static final int CHUNK_SIZE_KB = 512;

  /** Sole constructor. */
  public BulkCSVAddDocumentHandlerNonBinary(GlobalState state) {
    super(state);
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public boolean doStream() {
    return true;
  }

  /** Parses and indexes documents from one chunk of CSV */
  private static class ParseAndIndexOneChunk implements Runnable {
    /** Shared context across all docs being indexed in this one stream */
    private final ShardState.IndexingContext ctx;
    
    private final ShardState shardState;
    private final FieldDef[] fields;
    private final char[] chars;
    private final Semaphore semaphore;

    /** Byte starting offset of our chunk in the total incoming byte stream; we use this to locate errors */
    private final long globalOffset;

    /** The job handling the chunk just before us */
    private ParseAndIndexOneChunk prev;

    private int endFragmentStartOffset = -1;

    private char[] nextStartFragment;
    private int nextStartFragmentOffset;
    private int nextStartFragmentLength;
    private final char delimChar;
    
    public ParseAndIndexOneChunk(char delimChar, long globalOffset, ShardState.IndexingContext ctx, ParseAndIndexOneChunk prev, ShardState shardState,
                                 FieldDef[] fields, char[] chars, Semaphore semaphore) throws InterruptedException {
      this.delimChar = delimChar;
      this.ctx = ctx;
      ctx.inFlightChunks.register();
      this.prev = prev;
      this.shardState = shardState;
      this.fields = fields;
      this.chars = chars;
      this.semaphore = semaphore;
      this.globalOffset = globalOffset;
      semaphore.acquire();
    }

    /** Indexes the one document that spans across the end of our chunk.  This is invoked when the chunk after us first starts, or when we
     *  finish processing all whole docs in our chunk, whichever comes last. */
    private void indexSplitDoc() {
      try {
        _indexSplitDoc();
      } finally {
        shardState.indexState.globalState.indexingJobsRunning.release();
        semaphore.release();
        ctx.inFlightChunks.arriveAndDeregister();
      }
    }
        
    private void _indexSplitDoc() {
      if (endFragmentStartOffset == -2) {
        assert prev != null;
        // nocommit for very large docs this glueing together is O(N^2) ... fix this to be a List<char[]> instead:
        // Our entire chunk was inside a single document; instead of indexing a split doc, we combine our whole fragment and
        // the next start fragment and pass back to the previous chunk:
        char[] allChars = new char[chars.length + nextStartFragmentLength];
        System.arraycopy(chars, 0, allChars, 0, chars.length);
        System.arraycopy(nextStartFragment, 0, allChars, chars.length, nextStartFragmentLength);
        prev.setNextStartFragment(allChars, 0, allChars.length);
        prev = null;
        return;
      }
      IndexState indexState = shardState.indexState;
      int endFragmentLength = chars.length - endFragmentStartOffset;
      if (endFragmentLength + nextStartFragmentLength > 0) {
        char[] allChars = new char[endFragmentLength + nextStartFragmentLength];
        System.arraycopy(chars, endFragmentStartOffset, allChars, 0, endFragmentLength);
        System.arraycopy(nextStartFragment, 0, allChars, endFragmentLength, nextStartFragmentLength);
        CSVParserChars parser = new CSVParserChars(delimChar, globalOffset + endFragmentStartOffset, fields, allChars, 0);
        Document doc;
        try {
          doc = parser.nextDoc();
        } catch (Throwable t) {
          ctx.setError(new IllegalArgumentException("last document starting at offset " + (globalOffset + endFragmentStartOffset) + " is missing the trailing newline"));
          return;
        }
        if (indexState.hasFacets()) {
          try {
            doc = indexState.facetsConfig.build(shardState.taxoWriter, doc);
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
        // At most one document spans across two chunks:
        assert parser.getBufferUpto() == allChars.length;
      }
    }

    /** The chunk after us calls this with its prefix fragment */
    public synchronized void setNextStartFragment(char[] chars, int offset, int length) {
      if (nextStartFragment != null) {
        throw new IllegalStateException("setNextStartFragment was already called");
      }
      nextStartFragment = chars;
      nextStartFragmentOffset = offset;
      nextStartFragmentLength = length;
      if (endFragmentStartOffset != -1) {
        // OK we already know our end fragment; together, these are one document; parse and index it now:
        indexSplitDoc();
      }
    }

    private synchronized void setEndFragment(int offset) {
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

    private void _run() {

      IndexState indexState = shardState.indexState;

      // find the start of our first document:
      int upto;
      if (prev != null) {
        upto = 0;
        while (upto < chars.length) {
          if (chars[upto] == CSVParser.NEWLINE) {
            break;
          }
          upto++;
        }
        //System.out.println("CHUNK @ " + globalOffset + " startFragment=" + upto + " vs len=" + bytes.length);
      } else {
        upto = -1;
      }

      if (upto < chars.length) {

        // skip the NEWLINE:
        upto++;
        
        if (prev != null) {
          prev.setNextStartFragment(chars, 0, upto);
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

                final CSVParserChars parser = new CSVParserChars(delimChar, globalOffset, fields, chars, startUpto);
                final boolean hasFacets = indexState.hasFacets();

                return new Iterator<Document>() {
                  private Document nextDoc;
                  private boolean nextSet;
                
                  @Override
                  public boolean hasNext() {
                    if (nextSet == false) {
                      try {
                        nextDoc = parser.nextDoc();
                      } catch (Throwable t) {
                        ctx.setError(t);
                        nextDoc = null;
                      }
                      if (nextDoc != null) {
                        ctx.addCount.incrementAndGet();
                        if (hasFacets) {
                          try {
                            nextDoc = indexState.facetsConfig.build(shardState.taxoWriter, nextDoc);
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
  public String handleStreamed(Reader reader, Map<String,List<String>> params) throws Exception {
    char delimChar;
    List<String> delims = params.get("delimChar");
    if (delims != null) {
      if (delims.size() != 1) {
        throw new IllegalArgumentException("delim parameter should only be specified once; got: " + delims);
      }
      if (delims.get(0).length() != 1) {
        throw new IllegalArgumentException("delim must be comma or tab character; got: " + delims.get(0));
      }
      delimChar = delims.get(0).charAt(0);
      if (delimChar != ',' && delimChar != '\t') {
        throw new IllegalArgumentException("delim must be comma or tab character; got: " + delims.get(0));
      }
    } else {
      delimChar = ',';
    }

    if (params.get("indexName") == null) {
      throw new IllegalArgumentException("required parameter \"indexName\" is missing");
    }

    if (params.get("indexName").size() != 1) {
      throw new IllegalArgumentException("only one \"indexName\" value is allowed");
    }

    String indexName = params.get("indexName").get(0);

    // Make sure the index does in fact exist
    IndexState indexState = globalState.getIndex(indexName);

    // Make sure the index is started:
    if (indexState.isStarted() == false) {
      throw new IllegalArgumentException("index \"" + indexName + "\" isn't started: cannot index documents");
    }

    ShardState shardState = indexState.getShard(0);
    
    // parse fields header and lookup fields:
    List<FieldDef> fieldsList = new ArrayList<>();
    StringBuilder curField = new StringBuilder();
    long globalOffset = 0;

    char[] buffer = new char[1024];
    int bufferUpto = 0;
    int bufferLimit = 0;
    while (true) {
      if (bufferUpto == bufferLimit) {
        globalOffset += bufferLimit;
        bufferLimit = reader.read(buffer, 0, buffer.length);
        if (bufferLimit == -1) {
          throw new IllegalArgumentException("hit end while parsing header");
        }
        bufferUpto = 0;
      }
      char c = buffer[bufferUpto++];
      if (c == delimChar) {
        fieldsList.add(indexState.getField(curField.toString()));
        curField.setLength(0);
      } else if (c == CSVParserChars.NEWLINE) {
        fieldsList.add(indexState.getField(curField.toString()));
        break;
      } else {
        curField.append(c);
      }
    }

    FieldDef[] fields = fieldsList.toArray(new FieldDef[fieldsList.size()]);

    ShardState.IndexingContext ctx = new ShardState.IndexingContext();
    char[] bufferOld = buffer;

    // nocommit tune this .. core count?

    // Use this to limit how many in-flight 256 KB chunks we allow into the JVM at once:

    // nocommit this should be in GlobalState so it's across all incoming indexing:
    Semaphore semaphore = new Semaphore(64);

    boolean done = false;

    // create first chunk buffer, and carry over any leftovers from the header processing:
    buffer = new char[CHUNK_SIZE_KB*1024/2];
    System.arraycopy(bufferOld, bufferUpto, buffer, 0, bufferLimit-bufferUpto);
    bufferUpto = bufferLimit - bufferUpto;

    globalOffset += bufferUpto;
    
    ParseAndIndexOneChunk prev = null;
    int phase = ctx.inFlightChunks.getPhase();

    while (done == false && ctx.getError() == null) {
      int count = reader.read(buffer, bufferUpto, buffer.length-bufferUpto);
      if (count == -1 || bufferUpto + count == buffer.length) {
        if (count != -1) {
          bufferUpto += count;
        }
        if (bufferUpto < buffer.length) {
          char[] realloc = new char[bufferUpto];
          System.arraycopy(buffer, 0, realloc, 0, bufferUpto);
          buffer = realloc;
        }
        // NOTE: This ctor will stall when it tries to acquire the semaphore if we already have too many in-flight indexing chunks:
        prev = new ParseAndIndexOneChunk(delimChar, globalOffset, ctx, prev, shardState, fields, buffer, semaphore);
        globalState.submitIndexingTask(prev);
        if (count == -1) {
          // the end
          prev.setNextStartFragment(new char[0], 0, 0);
          done = true;
          break;
        } else {
          globalOffset += buffer.length;
          // not done yet, make the next buffer:
          buffer = new char[CHUNK_SIZE_KB*1024/2];
          bufferUpto = 0;
        }
      } else {
        bufferUpto += count;
      }
    }

    if (done == false) {
      // we exited loop due to error; force last indexing chunk to finish up:
      prev.setNextStartFragment(new char[0], 0, 0);
    }

    // Wait for all chunks to finish indexing:
    ctx.inFlightChunks.awaitAdvance(phase);

    Throwable t = ctx.getError();
    if (t != null) {
      IOUtils.reThrow(t);
      return null;
    } else {
      JSONObject o = new JSONObject();
      o.put("indexGen", shardState.writer.getMaxCompletedSequenceNumber());
      o.put("indexedDocumentCount", ctx.addCount.get());
      return o.toString();
    }
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
