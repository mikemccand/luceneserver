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

import org.apache.lucene.document.Document;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.params.*;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.store.DataOutput;
import org.codehaus.jackson.JsonFactory;
import org.codehaus.jackson.JsonParser;
import org.codehaus.jackson.JsonToken;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;

import static org.apache.lucene.server.IndexState.AddDocumentContext;

/** Bulk addDocument from CSV encoding */

public class BulkCSVAddDocumentHandler extends Handler {

  private static StructType TYPE = new StructType();

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

  /** Parses and indexes documents from one 256 KB chunk of CSV */
  private static class ParseAndIndexOneChunk implements Runnable {
    /** Shared context across all docs being indexed in this one stream */
    private final IndexState.AddDocumentContext ctx;
    
    private final IndexState indexState;
    private final FieldDef[] fields;
    private final byte[] bytes;
    private final Semaphore semaphore;

    /** Byte starting offset of our chunk in the total incoming byte stream; we use this to locate errors */
    private final long globalOffset;

    /** The job handling the chunk just before us */
    private ParseAndIndexOneChunk prev;

    private int endFragmentStartOffset = -1;

    private byte[] nextStartFragment;
    private int nextStartFragmentOffset;
    private int nextStartFragmentLength;
    
    public ParseAndIndexOneChunk(long globalOffset, IndexState.AddDocumentContext ctx, ParseAndIndexOneChunk prev, IndexState indexState,
                                 FieldDef[] fields, byte[] bytes, Semaphore semaphore) throws InterruptedException {
      this.ctx = ctx;
      ctx.inFlightChunkCount.incrementAndGet();
      this.prev = prev;
      this.indexState = indexState;
      this.fields = fields;
      this.bytes = bytes;
      this.semaphore = semaphore;
      this.globalOffset = globalOffset;
      semaphore.acquire();
      //System.out.println("CHUNK @ " + globalOffset + ": init " + bytes.length + " bytes");
    }

    /** Indexes the one document that spans across the end of our chunk */
    private void indexSplitDoc() {
      int endFragmentLength = bytes.length - endFragmentStartOffset;
      //System.out.println("CHUNK @ " + globalOffset + " indexSplitDoc: endFragmentLength=" + endFragmentLength + " nextStartFragmentLength=" + nextStartFragmentLength);
      if (endFragmentLength + nextStartFragmentLength > 0) {
        byte[] allBytes = new byte[endFragmentLength + nextStartFragmentLength];
        System.arraycopy(bytes, endFragmentStartOffset, allBytes, 0, endFragmentLength);
        System.arraycopy(nextStartFragment, 0, allBytes, endFragmentLength, nextStartFragmentLength);
        /*
          try {
          System.out.println("CHUNK @ " + globalOffset + " doc: " + new String(allBytes, "UTF-8"));
          } catch (Exception e) {
          System.out.println("IGNORE: " +e);
          }
        */
        CSVParser parser = new CSVParser(globalOffset + endFragmentStartOffset, fields, indexState, allBytes, 0);
        //parser.verbose = "CHUNK @ " + globalOffset;
        Document doc = parser.nextDoc();
        assert doc != null;
        indexDocument(globalOffset + endFragmentStartOffset, doc);
        assert parser.getBufferUpto() == allBytes.length;
      }
      semaphore.release();
      ctx.inFlightChunkCount.decrementAndGet();
    }

    /** The chunk after us calls this with its prefix fragment */
    public synchronized void setNextStartFragment(byte[] bytes, int offset, int length) {
      nextStartFragment = bytes;
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

    private void indexDocument(long docOffset, Document doc) {
      ctx.addCount.incrementAndGet();
      try {
        indexState.indexDocument(doc);
      } catch (Exception e) {
        ctx.addException(docOffset, e);
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
          indexState.writer.addDocuments(new Iterable<Document>() {
              @Override
              public Iterator<Document> iterator() {

                // now parse & index whole documents:

                final CSVParser parser = new CSVParser(globalOffset, fields, indexState, bytes, startUpto);

                return new Iterator<Document>() {
                  private Document nextDoc;
                  private boolean nextSet;
                
                  @Override
                  public boolean hasNext() {
                    if (nextSet == false) {
                      nextDoc = parser.nextDoc();
                      if (nextDoc != null) {
                        ctx.addCount.incrementAndGet();
                        try {
                          nextDoc = indexState.facetsConfig.build(indexState.taxoWriter, nextDoc);
                        } catch (IOException ioe) {
                          throw new RuntimeException(ioe);
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
        } catch (Exception e) {
          ctx.addException(globalOffset, e);
        }

        //System.out.println("CHUNK @ " + globalOffset + ": done parsing; end fragment length=" + (bytes.length-offset));
        setEndFragment(endOffset[0]);
        
      } else {
        // exotic case: the entire 256 KB chunk is inside one document
        // nocommit handle this corner case too!
        throw new IllegalArgumentException("entire chunk is a subset of one document");

        // nocommit also handle the exotic case where the chunk split right at a doc boundary
      }
    }
  }

  @Override
  public void handleBinary(InputStream in, DataInput dataIn, DataOutput out, OutputStream streamOut) throws Exception {

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
      if (b == CSVParser.COMMA) {
        if (indexState == null) {
          throw new IllegalArgumentException("first line must be the index name");
        }
        fieldsList.add(indexState.getField(curField.toString()));
        curField.setLength(0);
      } else if (b == CSVParser.NEWLINE) {
        if (indexState == null) {
          String indexName = curField.toString();
          indexState = globalState.get(indexName);
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

    IndexState.AddDocumentContext ctx = new IndexState.AddDocumentContext();
    byte[] bufferOld = buffer;

    // nocommit tune this .. core count?

    // Use this to limit how many in-flight 256 KB chunks we allow into the JVM at once:
    Semaphore semaphore = new Semaphore(64);

    ParseAndIndexOneChunk prev = null;

    boolean done = false;

    buffer = new byte[256*1024];
    System.arraycopy(bufferOld, bufferUpto, buffer, 0, bufferLimit-bufferUpto);
    bufferUpto = bufferLimit - bufferUpto;

    globalOffset += bufferUpto;
    
    while (bufferUpto < buffer.length) {
      int count = in.read(buffer, bufferUpto, buffer.length-bufferUpto);
      if (count == -1) {
        if (bufferUpto < buffer.length) {
          byte[] realloc = new byte[bufferUpto];
          System.arraycopy(buffer, 0, realloc, 0, bufferUpto);
          buffer = realloc;
        }
        prev = new ParseAndIndexOneChunk(globalOffset, ctx, prev, indexState, fields, buffer, semaphore);
        prev.setNextStartFragment(new byte[0], 0, 0);
        globalState.indexService.submit(prev);
        done = true;
        break;
      } else {
        bufferUpto += count;
      }
    }

    if (done == false) {
      prev = new ParseAndIndexOneChunk(globalOffset, ctx, prev, indexState, fields, buffer, semaphore);
      globalOffset += buffer.length;
      globalState.indexService.submit(prev);

      while (done == false) {
        buffer = new byte[256*1024];
        bufferUpto = 0;
        while (bufferUpto < buffer.length) {
          int count = in.read(buffer, bufferUpto, buffer.length-bufferUpto);
          if (count == -1) {
            if (bufferUpto < buffer.length) {
              byte[] realloc = new byte[bufferUpto];
              System.arraycopy(buffer, 0, realloc, 0, bufferUpto);
              buffer = realloc;
            }
            prev = new ParseAndIndexOneChunk(globalOffset, ctx, prev, indexState, fields, buffer, semaphore);
            prev.setNextStartFragment(new byte[0], 0, 0);
            globalState.indexService.submit(prev);
            done = true;
            break;
          } else {
            bufferUpto += count;
          }
        }

        if (done == false) {
          prev = new ParseAndIndexOneChunk(globalOffset, ctx, prev, indexState, fields, buffer, semaphore);
          globalOffset += buffer.length;
          globalState.indexService.submit(prev);
        }
      }
    }
    
    // nocommit this is ... lameish ... can we just join on these futures?:
    while (true) {
      if (ctx.inFlightChunkCount.get() == 0) {
        break;
      }
      Thread.sleep(1);
    }

    JSONObject o = new JSONObject();
    o.put("indexGen", indexState.writer.getMaxCompletedSequenceNumber());
    o.put("indexedDocumentCount", ctx.addCount.get());
    if (!ctx.errors.isEmpty()) {
      JSONArray errors = new JSONArray();
      o.put("errors", errors);
      for(int i=0;i<ctx.errors.size();i++) {
        JSONObject err = new JSONObject();
        errors.add(err);
        err.put("index", ctx.errorIndex.get(i));
        err.put("exception", ctx.errors.get(i));
      }
    }

    byte[] bytes = o.toString().getBytes(StandardCharsets.UTF_8);
    out.writeInt(bytes.length);
    out.writeBytes(bytes, 0, bytes.length);
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
