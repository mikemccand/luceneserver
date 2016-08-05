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
import org.apache.lucene.document.Field;
import org.apache.lucene.document.FloatDocValuesField;
import org.apache.lucene.document.FloatPoint;
import org.apache.lucene.document.IntPoint;
import org.apache.lucene.document.LongPoint;
import org.apache.lucene.document.NumericDocValuesField;
import org.apache.lucene.document.SortedDocValuesField;
import org.apache.lucene.document.SortedNumericDocValuesField;
import org.apache.lucene.document.SortedSetDocValuesField;
import org.apache.lucene.document.StoredField;
import org.apache.lucene.document.StringField;
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
  private final Field[] reuseFields;
  private final Field[] reuseDVs;
  private final Field[] reusePoints;
  private final Document reuseDoc;
  
  public CSVParser(long globalOffset, FieldDef[] fields, IndexState indexState, byte[] bytes, int startOffset) {
    this.bytes = bytes;
    this.fields = fields;
    bufferUpto = startOffset;
    this.globalOffset = globalOffset;
    this.indexState = indexState;
    // set up fields for reuse:
    reuseFields = new Field[fields.length];
    reusePoints = new Field[fields.length];
    reuseDVs = new Field[fields.length];
    reuseDoc = new Document();
    initReuseFields();
  }

  private void initReuseFields() {
    for(int i=0;i<fields.length;i++) {
      FieldDef fd = fields[i];
      boolean stored = fd.fieldType.stored();
      DocValuesType dvType = fd.fieldType.docValuesType();
      switch(fd.valueType) {
      case "atom":
        {
          BytesRef br;
          if (fd.usePoints) {
            reusePoints[i] = new BinaryPoint(fd.name, new byte[0]);
            // little bit sneaky sharing of a single BytesRef across all Lucene
            // fields we add for this user's field:
            br = reusePoints[i].binaryValue();
            assert br != null;
          } else {
            br = new BytesRef();
          }
          reuseFields[i] = new StringField(fd.name, br, stored ? Field.Store.YES : Field.Store.NO);
          if (dvType == DocValuesType.SORTED) {
            reuseDVs[i] = new SortedDocValuesField(fd.name, br);
          } else if (dvType == DocValuesType.SORTED_SET) {
            reuseDVs[i] = new SortedSetDocValuesField(fd.name, br);
          } else if (dvType == DocValuesType.BINARY) {
            reuseDVs[i] = new BinaryDocValuesField(fd.name, br);
          }
          break;
        }
      case "text":
        {
          reuseFields[i] = new AddDocumentHandler.MyField(fd.name, fd.fieldType, "");
          break;
        }
      case "int":
        {
          if (stored) {
            reuseFields[i] = new StoredField(fd.name, 0);
          }
          if (fd.usePoints) {
            reusePoints[i] = new IntPoint(fd.name, 0);
          }
          if (dvType == DocValuesType.NUMERIC) {
            reuseDVs[i] = new NumericDocValuesField(fd.name, 0);
          } else if (dvType == DocValuesType.SORTED_NUMERIC) {
            reuseDVs[i] = new SortedNumericDocValuesField(fd.name, 0);
          }
          break;
        }
      case "long":
        {
          if (stored) {
            reuseFields[i] = new StoredField(fd.name, 0L);
          }
          if (fd.usePoints) {
            reusePoints[i] = new LongPoint(fd.name, 0);
          }
          if (dvType == DocValuesType.NUMERIC) {
            reuseDVs[i] = new NumericDocValuesField(fd.name, 0);
          } else if (dvType == DocValuesType.SORTED_NUMERIC) {
            reuseDVs[i] = new SortedNumericDocValuesField(fd.name, 0);
          }
          break;
        }
      case "float":
        {
          if (stored) {
            reuseFields[i] = new StoredField(fd.name, 0.0f);
          }
          if (fd.usePoints) {
            reusePoints[i] = new FloatPoint(fd.name, 0.0f);
          }
          if (dvType == DocValuesType.NUMERIC) {
            reuseDVs[i] = new NumericDocValuesField(fd.name, 0);
          } else if (dvType == DocValuesType.SORTED_NUMERIC) {
            reuseDVs[i] = new SortedNumericDocValuesField(fd.name, 0);
          }
          break;
        }
      case "double":
        {
          if (stored) {
            reuseFields[i] = new StoredField(fd.name, 0.0);
          }
          if (fd.usePoints) {
            reusePoints[i] = new DoublePoint(fd.name, 0.0);
          }
          if (dvType == DocValuesType.NUMERIC) {
            reuseDVs[i] = new NumericDocValuesField(fd.name, 0);
          } else if (dvType == DocValuesType.SORTED_NUMERIC) {
            reuseDVs[i] = new SortedNumericDocValuesField(fd.name, 0);
          }
          break;
        }
      }
    }
  }

  public int getLastDocStart() {
    return lastDocStart;
  }

  public int getBufferUpto() {
    return bufferUpto;
  }

  private void addOneField(int i, int lastFieldStart) {
    int len = bufferUpto - lastFieldStart - 1;
    assert len > 0;

    // nocommit need to handle escaping!
    
    switch(fields[i].valueType) {
    case "atom":
      {
        Field field = reuseFields[i];
        BytesRef br = field.binaryValue();
        assert br != null;
        br.bytes = bytes;
        br.offset = lastFieldStart;
        br.length = len;
        reuseDoc.add(field);
        Field point = reusePoints[i];
        if (point != null) {
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[i];
        if (dv != null) {
          dv.setBytesValue(br);
          reuseDoc.add(dv);
        }
        break;
      }
    case "text":
      {
        String s = new String(bytes, lastFieldStart, len, StandardCharsets.UTF_8);
        Field field = reuseFields[i];
        field.setStringValue(s);
        reuseDoc.add(field);
        break;
      }
    case "int":
      {
        int value;
        Field field = reuseFields[i];
        try {
          value = MathUtil.parseInt(bytes, lastFieldStart, len);
        } catch (NumberFormatException nfe) {
          throw new NumberFormatException("doc at offset " + (globalOffset + lastFieldStart) + ": could not parse field \"" + fields[i].name + "\" as int: " + nfe.getMessage());
        }
        if (field != null) {
          field.setIntValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[i];
        if (point != null) {
          BytesRef br = point.binaryValue();
          IntPoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[i];
        if (dv != null) {
          dv.setLongValue(value);
          reuseDoc.add(dv);
        }
        break;
      }
    case "long":
      {
        Field field = reuseFields[i];
        long value;
        try {
          value = MathUtil.parseLong(bytes, lastFieldStart, len);
        } catch (NumberFormatException nfe) {
          throw new NumberFormatException("doc at offset " + (globalOffset + lastFieldStart) + ": could not parse field \"" + fields[i].name + "\" as long: " + nfe.getMessage());
        }
        if (field != null) {
          field.setLongValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[i];
        if (point != null) {
          BytesRef br = point.binaryValue();
          LongPoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[i];
        if (dv != null) {
          dv.setLongValue(value);
          reuseDoc.add(dv);
        }
        break;
      }
    case "float":
      {
        Field field = reuseFields[i];
        float value;
        try {
          value = MathUtil.parseFloat(bytes, lastFieldStart, len);
        } catch (NumberFormatException nfe) {
          throw new NumberFormatException("doc at offset " + (globalOffset + lastFieldStart) + ": could not parse field \"" + fields[i].name + "\" as float: " + nfe.getMessage());
        }
        if (field != null) {
          field.setFloatValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[i];
        if (point != null) {
          BytesRef br = point.binaryValue();
          FloatPoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[i];
        if (dv != null) {
          dv.setLongValue(NumericUtils.floatToSortableInt(value));
          reuseDoc.add(dv);
        }
        break;
      }
    case "double":
      {
        Field field = reuseFields[i];
        double value;
        try {
          value = MathUtil.parseDouble(bytes, lastFieldStart, len);
        } catch (NumberFormatException nfe) {
          throw new NumberFormatException("doc at offset " + (globalOffset + lastFieldStart) + ": could not parse field \"" + fields[i].name + "\" as double: " + nfe.getMessage());
        }
        if (field != null) {
          field.setDoubleValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[i];
        if (point != null) {
          BytesRef br = point.binaryValue();
          DoublePoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[i];
        if (dv != null) {
          dv.setLongValue(NumericUtils.doubleToSortableLong(value));
          reuseDoc.add(dv);
        }
        break;
      }
    }
  }

  public Document nextDoc() {
    // clear all prior fields
    reuseDoc.clear();

    int fieldUpto = 0;
    int lastFieldStart = bufferUpto;
    lastDocStart = bufferUpto;
    
    while (bufferUpto < bytes.length) {
      byte b = bytes[bufferUpto++];
      if (b == COMMA) {

        if (fieldUpto == fields.length) {
          throw new IllegalArgumentException("doc at offset " + lastDocStart + ": line has too many fields");
        }
        
        if (bufferUpto > lastFieldStart+1) {
          addOneField(fieldUpto, lastFieldStart);
        } else {
          // OK: empty field
        }
        lastFieldStart = bufferUpto;
        fieldUpto++;

      } else if (b == NEWLINE) {

        if (fieldUpto != fields.length-1) {
          throw new IllegalArgumentException("doc at offset " + lastDocStart + ": line has wrong number of fields: expected " + fields.length + " but saw " + (fieldUpto+1));
        }
        
        // add last field
        addOneField(fieldUpto, lastFieldStart);
        return reuseDoc;
      }
    }

    return null;
  }
}
