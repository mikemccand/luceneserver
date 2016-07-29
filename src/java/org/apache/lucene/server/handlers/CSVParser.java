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
import org.apache.lucene.server.util.MathUtil;
import org.apache.lucene.store.DataInput;
import org.apache.lucene.util.ArrayUtil;
import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.NumericUtils;

import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

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
    boolean stored = fd.fieldType.stored();
    DocValuesType dvType = fd.fieldType.docValuesType();
    
    // nocommit need to handle escaping!
    
    switch(fd.valueType) {
    case "atom":
      {
        String s = new String(bytes, lastFieldStart, len, StandardCharsets.UTF_8);
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
        String s = new String(bytes, lastFieldStart, len, StandardCharsets.UTF_8);
        doc.add(new AddDocumentHandler.MyField(fd.name, fd.fieldTypeNoDV, s));
        break;
      }
    case "int":
      {
        int value;
        try {
          value = MathUtil.parseInt(bytes, lastFieldStart, len);
        } catch (NumberFormatException nfe) {
          // nocommit add this to indexing ctx
          System.out.println("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": " + nfe.getMessage());
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
        long value;
        try {
          value = MathUtil.parseLong(bytes, lastFieldStart, len);
        } catch (NumberFormatException nfe) {
          // nocommit add this to indexing ctx
          System.out.println("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": " + nfe.getMessage());
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
        float value;
        try {
          value = MathUtil.parseFloat(bytes, lastFieldStart, len);
        } catch (NumberFormatException nfe) {
          // nocommit add this to indexing ctx
          System.out.println("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": " + nfe.getMessage());
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
        double value;
        try {
          value = MathUtil.parseDouble(bytes, lastFieldStart, len);
        } catch (NumberFormatException nfe) {
          // nocommit add this to indexing ctx
          System.out.println("doc at offset " + (globalOffset + lastFieldStart) + ": field \"" + fd.name + "\": " + nfe.getMessage());
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

  private static final long LONG_MAX_DIV10 = Long.MAX_VALUE / 10;
  
  private static long parseLong(byte[] bytes, int start, int length) {
    int i = start;
    int negMult;
    if (bytes[i] == (byte) '-') {
      i++;
      negMult = -1;
    } else if (bytes[i] == (byte) '+') {
      i++;
      negMult = 1;
    } else {
      negMult = 1;
    }

    int end = start + length;
    
    long value = 0;
    while (i < end) {
      byte b = bytes[i++];
      if (b >= (byte) '0' && b <= (byte) '9') {
        int digit = (int) (b - (byte) '0');
        long newValue = value * 10 + digit;
        if (value > LONG_MAX_DIV10 || newValue < value) {
          // overflow
          throw new NumberFormatException("too many digits to parse \"" + new String(bytes, start, end-start, StandardCharsets.UTF_8) + "\" as long");
        }
        value = newValue;
      } else {
        throw new NumberFormatException("could not parse \"" + new String(bytes, start, end-start, StandardCharsets.UTF_8) + "\" as long");
      }
    }

    return negMult * value;
  }

  // inspired by Javolution's double parser:
  private static double parseDouble(byte[] bytes, int start, int end) {
    int i = start;
    if (start == end) {
      throw new NumberFormatException("empty string");
    }

    int negMult;
    if (bytes[i] == (byte) '-') {
      i++;
      negMult = -1;
    } else if (bytes[i] == (byte) '+') {
      i++;
      negMult = 1;
    } else {
      negMult = 1;
    }
       
    // accumulate all characters into a long, then divide by wherever-decimal-point is
    long value = 0;
    int decimalPos = -1;
    while (i < end) {
      byte b = bytes[i++];
      if (b == (byte) '.') {
        decimalPos = i;
      } else if (b >= (byte) '0' && b <= (byte) '9') {
        int digit = (int) (b - (byte) '0');
        long newValue = value * 10 + digit;
        if (value > LONG_MAX_DIV10 || newValue < value) {
          // overflow
          throw new NumberFormatException("too many digits");
        }
        value = newValue;
      } else {
        // something more exotic (Infinity, NaN, exponents): let java try
        return parseDoubleSlowly(bytes, start, end);
      }
    }

    return 0.0;
  }

  private static double parseDoubleSlowly(byte[] bytes, int start, int end) {
    return Double.parseDouble(new String(bytes, start, end-start, StandardCharsets.UTF_8));
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
