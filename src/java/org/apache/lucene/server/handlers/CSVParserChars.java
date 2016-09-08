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
import java.text.ParseException;
import java.text.ParsePosition;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Calendar;
import java.util.Date;
import java.util.GregorianCalendar;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;

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
import org.apache.lucene.util.UnicodeUtil;

// TODO:
//   - multi-valued fields?
//   - escaping " , \n

class CSVParserChars {

  final static char NEWLINE = '\n';
  
  final char[] chars;
  final long globalOffset;
  int bufferUpto;
  int bufferLimit;
  final FieldDef[] fields;
  public final IndexState indexState;
  private int lastDocStart;
  private final byte[][] reuseByteArrays;
  private final Field[] reuseFields;
  private final Field[] reuseDVs;
  private final Field[] reusePoints;
  private final Document reuseDoc;
  private final char delimChar;
  // nocommit use CTL to reuse these?
  private SimpleDateFormat dateTimeParser;
  private ParsePosition dateTimeParsePosition;
  
  public CSVParserChars(char delimChar, long globalOffset, FieldDef[] fields, IndexState indexState, char[] chars, int startOffset) {
    this.delimChar = delimChar;
    this.chars = chars;
    this.fields = fields;
    bufferUpto = startOffset;
    this.globalOffset = globalOffset;
    this.indexState = indexState;
    // set up fields for reuse:
    reuseFields = new Field[fields.length];
    reuseByteArrays = new byte[fields.length][];
    reusePoints = new Field[fields.length];
    reuseDVs = new Field[fields.length];
    reuseDoc = new Document();
    initReuseFields();
    //System.out.println("CSV: " + fields.length + " fields");
  }

  private void initReuseFields() {
    for(int i=0;i<fields.length;i++) {
      FieldDef fd = fields[i];
      boolean stored = fd.fieldType.stored();
      DocValuesType dvType = fd.fieldType.docValuesType();
      switch(fd.valueType) {
      case ATOM:
        {
          reuseByteArrays[i] = new byte[16];
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
      case TEXT:
        {
          reuseFields[i] = new AddDocumentHandler.MyField(fd.name, fd.fieldType, "");
          break;
        }
      case INT:
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
      case LONG:
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
      case FLOAT:
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
      case DOUBLE:
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
      case DATE_TIME:
        {
          assert fd.dateTimeFormat != null;
          Calendar calendar = new GregorianCalendar(TimeZone.getTimeZone("UTC"), Locale.ROOT);
          calendar.setLenient(false);
          dateTimeParser = new SimpleDateFormat(fd.dateTimeFormat, Locale.ROOT);
          dateTimeParser.setCalendar(calendar);          
          dateTimeParsePosition = new ParsePosition(0);
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
      // nocommit LAT_LON?
      default:
        throw new AssertionError();
      }
    }
  }

  public int getLastDocStart() {
    return lastDocStart;
  }

  public int getBufferUpto() {
    return bufferUpto;
  }

  private void addOneField(int i, int lastFieldStart) throws ParseException {
    int len = bufferUpto - lastFieldStart - 1;
    assert len > 0;

    // nocommit need to handle escaping!
    
    switch(fields[i].valueType) {
    case ATOM:
      {
        Field field = reuseFields[i];
        BytesRef br = field.binaryValue();
        assert br != null;
        byte[] bytes = reuseByteArrays[i];
        assert bytes != null;
        if (bytes.length < UnicodeUtil.MAX_UTF8_BYTES_PER_CHAR * len) {
          bytes = ArrayUtil.grow(bytes, UnicodeUtil.MAX_UTF8_BYTES_PER_CHAR * len);
          reuseByteArrays[i] = bytes;
        }
        br.bytes = bytes;
        br.offset = 0;
        br.length = UnicodeUtil.UTF16toUTF8(chars, lastFieldStart, len, bytes);
        reuseDoc.add(field);
        Field point = reusePoints[i];
        if (point != null) {
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[i];
        if (dv != null) {
          // nocommit not needed?
          // dv.setBytesValue(br);
          reuseDoc.add(dv);
        }
        break;
      }
    case TEXT:
      {
        String s = new String(chars, lastFieldStart, len);
        Field field = reuseFields[i];
        field.setStringValue(s);
        reuseDoc.add(field);
        break;
      }
    case INT:
      {
        int value;
        Field field = reuseFields[i];
        try {
          value = MathUtil.parseInt(chars, lastFieldStart, len);
          //value = Integer.parseInt(new String(chars, lastFieldStart, len));
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
    case LONG:
      {
        Field field = reuseFields[i];
        long value;
        try {
          value = MathUtil.parseLong(chars, lastFieldStart, len);
          //value = Long.parseLong(new String(chars, lastFieldStart, len));
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
    case FLOAT:
      {
        Field field = reuseFields[i];
        float value;
        try {
          value = MathUtil.parseFloat(chars, lastFieldStart, len);
          //value = Float.parseFloat(new String(chars, lastFieldStart, len));
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
    case DOUBLE:
      {
        Field field = reuseFields[i];
        double value;
        try {
          value = MathUtil.parseDouble(chars, lastFieldStart, len);
          //value = Double.parseDouble(new String(chars, lastFieldStart, len));
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
    case DATE_TIME:
      {
        Field field = reuseFields[i];
        String s = new String(chars, lastFieldStart, len);
        dateTimeParsePosition.setIndex(0);
        Date date = dateTimeParser.parse(s, dateTimeParsePosition);
        if (dateTimeParsePosition.getErrorIndex() != -1) {
          // nocommit more details about why?
          throw new IllegalArgumentException("doc at offset " + (globalOffset + lastFieldStart) + ": could not parse field \"" + fields[i].name + "\", value \"" + s + "\" as date with format \"" + fields[i].dateTimeFormat + "\"");
        }
        if (dateTimeParsePosition.getIndex() != s.length()) {
          // nocommit more details about why?          
          throw new IllegalArgumentException("doc at offset " + (globalOffset + lastFieldStart) + ": could not parse field \"" + fields[i].name + "\", value \"" + s + "\" as date with format \"" + fields[i].dateTimeFormat + "\"");
        }
        long value = date.getTime();
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
    // nocommit LAT_LON
    default:
      throw new AssertionError();
    }
  }

  public Document nextDoc() throws ParseException {
    // clear all prior fields
    reuseDoc.clear();

    int fieldUpto = 0;
    int lastFieldStart = bufferUpto;
    lastDocStart = bufferUpto;
    
    while (bufferUpto < chars.length) {
      char c = chars[bufferUpto++];
      if (c == delimChar) {

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

      } else if (c == NEWLINE) {

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
