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

import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.apache.lucene.document.BinaryDocValuesField;
import org.apache.lucene.document.BinaryPoint;
import org.apache.lucene.document.Document;
import org.apache.lucene.document.DoubleDocValuesField;
import org.apache.lucene.document.DoublePoint;
import org.apache.lucene.document.FloatDocValuesField;
import org.apache.lucene.document.FloatPoint;
import org.apache.lucene.document.IntPoint;
import org.apache.lucene.document.LongPoint;
import org.apache.lucene.document.NumericDocValuesField;
import org.apache.lucene.document.SortedDocValuesField;
import org.apache.lucene.document.SortedNumericDocValuesField;
import org.apache.lucene.document.SortedSetDocValuesField;
import org.apache.lucene.document.StoredField;
import org.apache.lucene.index.DocValuesType;
import org.apache.lucene.index.IndexOptions;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.util.ArrayUtil;
import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.NumericUtils;

// TODO:
//   - multi-valued fields?
//   - escaping " , \n

class CSVParser {

  final static byte COMMA = (byte) ',';
  final static byte NEWLINE = (byte) '\n';
  
  final byte[] bytes;
  final long globalOffset;
  int bufferUpto;
  int bufferLimit;
  final FieldDef[] fields;
  public final IndexState indexState;
  private int lastDocStart;
  // nocommit
  public String verbose;

  public CSVParser(long globalOffset, FieldDef[] fields, IndexState indexState, byte[] bytes, int startOffset) {
    this.bytes = bytes;
    this.fields = fields;
    bufferUpto = startOffset;
    this.globalOffset = globalOffset;
    this.indexState = indexState;
  }

  public int getLastDocStart() {
    return lastDocStart;
  }

  public int getBufferUpto() {
    return bufferUpto;
  }

  private void addOneField(FieldDef fd, Document doc, int lastFieldStart) {
    int len = bufferUpto - lastFieldStart - 1;
    String s = new String(bytes, lastFieldStart, len, StandardCharsets.US_ASCII);
    if (verbose != null) {
      System.out.println(verbose +": FIELD " + fd.name + " -> " + s);
    }
    boolean stored = fd.fieldType.stored();
    DocValuesType dvType = fd.fieldType.docValuesType();
    
    // nocommit need to handle escaping!
    
    switch(fd.valueType) {
    case "atom":
      {
        if (fd.usePoints) {
          doc.add(new BinaryPoint(fd.name, Arrays.copyOfRange(bytes, lastFieldStart, len)));
        }
        if (stored || fd.fieldType.indexOptions() != IndexOptions.NONE) {
          doc.add(new AddDocumentHandler.MyField(fd.name, fd.fieldTypeNoDV, s));
        }
        if (dvType == DocValuesType.SORTED) {
          doc.add(new SortedDocValuesField(fd.name, new BytesRef(Arrays.copyOfRange(bytes, lastFieldStart, lastFieldStart+len))));
        } else if (dvType == DocValuesType.SORTED_SET) {
          doc.add(new SortedSetDocValuesField(fd.name, new BytesRef(Arrays.copyOfRange(bytes, lastFieldStart, lastFieldStart+len))));
        } else if (dvType == DocValuesType.BINARY) {
          doc.add(new BinaryDocValuesField(fd.name, new BytesRef(Arrays.copyOfRange(bytes, lastFieldStart, lastFieldStart+len))));
        }
        break;
      }
    case "text":
      {
        doc.add(new AddDocumentHandler.MyField(fd.name, fd.fieldTypeNoDV, s));
        break;
      }
    case "int":
      {
        // TODO: bytes -> int directly
        int value;
        try {
          value = Integer.parseInt(s);
        } catch (NumberFormatException nfe) {
          //throw new IllegalArgumentException("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": could not parse " + s + " as an int");
          System.out.println(("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": could not parse " + s + " as an int"));
          return;
        }
        if (fd.usePoints) {
          doc.add(new IntPoint(fd.name, value));
        }
        if (stored) {
          doc.add(new StoredField(fd.name, value));
        }
        if (dvType == DocValuesType.NUMERIC) {
          doc.add(new NumericDocValuesField(fd.name, value));
        } else if (dvType == DocValuesType.SORTED_NUMERIC) {
          doc.add(new SortedNumericDocValuesField(fd.name, value));
        }
        break;
      }
    case "long":
      {
        // TODO: bytes -> long directly
        long value;
        try {
          value = Long.parseLong(s);
        } catch (NumberFormatException nfe) {
          //throw new IllegalArgumentException("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": could not parse " + s + " as a long");
          System.out.println("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": could not parse " + s + " as a long");
          return;
        }
        if (fd.usePoints) {
          doc.add(new LongPoint(fd.name, value));
        }
        if (stored) {
          doc.add(new StoredField(fd.name, value));
        }
        if (dvType == DocValuesType.NUMERIC) {
          doc.add(new NumericDocValuesField(fd.name, value));
        } else if (dvType == DocValuesType.SORTED_NUMERIC) {
          doc.add(new SortedNumericDocValuesField(fd.name, value));
        }
        break;
      }
    case "float":
      {
        // TODO: bytes -> float directly
        float value;
        try {
          value = Float.parseFloat(s);
        } catch (NumberFormatException nfe) {
          //throw new IllegalArgumentException("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": could not parse " + s + " as a float");
          System.out.println("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": could not parse " + s + " as a float");
          return;
        }
        if (fd.usePoints) {
          doc.add(new FloatPoint(fd.name, value));
        }
        if (stored) {
          doc.add(new StoredField(fd.name, value));
        }
        if (dvType == DocValuesType.NUMERIC) {
          doc.add(new FloatDocValuesField(fd.name, value));
        } else if (dvType == DocValuesType.SORTED_NUMERIC) {
          doc.add(new SortedNumericDocValuesField(fd.name, NumericUtils.floatToSortableInt(value)));
        }
        break;
      }
    case "double":
      {
        // TODO: bytes -> double directly
        double value;
        try {
          value = Double.parseDouble(s);
        } catch (NumberFormatException nfe) {
          //throw new IllegalArgumentException("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": could not parse " + s + " as a double");
          System.out.println("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": could not parse " + s + " as a double");
          return;
        }
        if (fd.usePoints) {
          doc.add(new DoublePoint(fd.name, value));
        }
        if (stored) {
          doc.add(new StoredField(fd.name, value));
        }
        if (dvType == DocValuesType.NUMERIC) {
          doc.add(new DoubleDocValuesField(fd.name, value));
        } else if (dvType == DocValuesType.SORTED_NUMERIC) {
          doc.add(new SortedNumericDocValuesField(fd.name, NumericUtils.doubleToSortableLong(value)));
        }
        break;
      }
    }
  }

  public Document nextDoc() {
    Document doc = new Document();

    int fieldUpto = 0;
    int lastFieldStart = bufferUpto;
    lastDocStart = bufferUpto;
    
    while (bufferUpto < bytes.length) {
      byte b = bytes[bufferUpto++];
      if (b == COMMA) {
        if (bufferUpto > lastFieldStart+1) {
          addOneField(fields[fieldUpto], doc, lastFieldStart);
        } else {
          // OK: empty field
        }
        lastFieldStart = bufferUpto;
        fieldUpto++;
        if (fieldUpto > fields.length) {
          throw new IllegalArgumentException("doc at offset " + (globalOffset + lastFieldStart) + ": line has too many fields");
        }

      } else if (b == NEWLINE) {
        // add last field
        addOneField(fields[fieldUpto], doc, lastFieldStart);
        fieldUpto++;
        if (fieldUpto != fields.length) {
          throw new IllegalArgumentException("doc at offset " + lastDocStart + " has " + fieldUpto + " fields, but expected " + fields.length);
        }
        return doc;
      }
    }

    return null;
  }
}
