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

import java.nio.charset.StandardCharsets;
import java.text.ParseException;
import java.text.ParsePosition;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.GregorianCalendar;
import java.util.Locale;
import java.util.TimeZone;

import org.apache.lucene.document.BinaryDocValuesField;
import org.apache.lucene.document.BinaryPoint;
import org.apache.lucene.document.Document;
import org.apache.lucene.document.DoublePoint;
import org.apache.lucene.document.Field;
import org.apache.lucene.document.FloatPoint;
import org.apache.lucene.document.IntPoint;
import org.apache.lucene.document.LatLonPoint;
import org.apache.lucene.document.LongPoint;
import org.apache.lucene.document.NumericDocValuesField;
import org.apache.lucene.document.SortedDocValuesField;
import org.apache.lucene.document.SortedNumericDocValuesField;
import org.apache.lucene.document.SortedSetDocValuesField;
import org.apache.lucene.document.StoredField;
import org.apache.lucene.document.StringField;
import org.apache.lucene.index.DocValuesType;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.util.MathUtil;
import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.NumericUtils;

// TODO:
//   - multi-valued fields?
//   - escaping " , \n

class CSVParser {

  final static byte NEWLINE = (byte) '\n';
  final static byte DOUBLE_QUOTE = (byte) '"';
  final static byte SEMICOLON = (byte) ';';
  
  final byte[] bytes;
  final long globalOffset;
  int bufferUpto;
  int bufferLimit;
  final FieldDef[] fields;
  private int lastDocStart;
  private final Field[] reuseFields;
  private final Field[] reuseDVs;
  private final Field[] reusePoints;
  private final Document reuseDoc;
  private final byte delimChar;
  
  public CSVParser(byte delimChar, long globalOffset, FieldDef[] fields, byte[] bytes, int startOffset) {
    this.delimChar = delimChar;
    this.bytes = bytes;
    this.fields = fields;
    bufferUpto = startOffset;
    this.globalOffset = globalOffset;
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
      case ATOM:
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
      case LAT_LON:
        {
          reusePoints[i] = new LatLonPoint(fd.name, 0.0, 0.0);
          break;
        }
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

  private void addOneField(int fieldUpto, int start, int length) throws ParseException {
    assert length > 0;

    // nocommit need to handle multi-valued!

    switch(fields[fieldUpto].valueType) {
    case ATOM:
      {
        Field field = reuseFields[fieldUpto];
        BytesRef br = field.binaryValue();
        assert br != null;
        br.bytes = bytes;
        br.offset = start;
        br.length = length;
        reuseDoc.add(field);
        Field point = reusePoints[fieldUpto];
        if (point != null) {
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[fieldUpto];
        if (dv != null) {
          // nocommit not needed?
          //dv.setBytesValue(br);
          reuseDoc.add(dv);
        }
        break;
      }
    case TEXT:
      {
        String s = new String(bytes, start, length, StandardCharsets.UTF_8);
        Field field = reuseFields[fieldUpto];
        field.setStringValue(s);
        reuseDoc.add(field);
        break;
      }
    case INT:
      {
        int value;
        Field field = reuseFields[fieldUpto];
        try {
          value = MathUtil.parseInt(bytes, start, length);
          //value = Integer.parseInt(new String(bytes, start, length, StandardCharsets.UTF_8));
        } catch (NumberFormatException nfe) {
          throw new NumberFormatException("doc at offset " + (globalOffset + start) + ": could not parse field \"" + fields[fieldUpto].name + "\" as int: " + nfe.getMessage());
        }
        if (field != null) {
          field.setIntValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[fieldUpto];
        if (point != null) {
          BytesRef br = point.binaryValue();
          IntPoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[fieldUpto];
        if (dv != null) {
          dv.setLongValue(value);
          reuseDoc.add(dv);
        }
        break;
      }
    case LONG:
      {
        Field field = reuseFields[fieldUpto];
        long value;
        try {
          value = MathUtil.parseLong(bytes, start, length);
          //value = Long.parseLong(new String(bytes, start, length, StandardCharsets.UTF_8));
        } catch (NumberFormatException nfe) {
          throw new NumberFormatException("doc at offset " + (globalOffset + start) + ": could not parse field \"" + fields[fieldUpto].name + "\" as long: " + nfe.getMessage());
        }
        if (field != null) {
          field.setLongValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[fieldUpto];
        if (point != null) {
          BytesRef br = point.binaryValue();
          LongPoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[fieldUpto];
        if (dv != null) {
          dv.setLongValue(value);
          reuseDoc.add(dv);
        }
        break;
      }
    case FLOAT:
      {
        Field field = reuseFields[fieldUpto];
        float value;
        try {
          value = MathUtil.parseFloat(bytes, start, length);
          //value = Float.parseFloat(new String(bytes, start, length, StandardCharsets.UTF_8));
        } catch (NumberFormatException nfe) {
          throw new NumberFormatException("doc at offset " + (globalOffset + start) + ": could not parse field \"" + fields[fieldUpto].name + "\" as float: " + nfe.getMessage());
        }
        if (field != null) {
          field.setFloatValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[fieldUpto];
        if (point != null) {
          BytesRef br = point.binaryValue();
          FloatPoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[fieldUpto];
        if (dv != null) {
          dv.setLongValue(NumericUtils.floatToSortableInt(value));
          reuseDoc.add(dv);
        }
        break;
      }
    case DOUBLE:
      {
        Field field = reuseFields[fieldUpto];
        double value;
        try {
          value = MathUtil.parseDouble(bytes, start, length);
          //value = Double.parseDouble(new String(bytes, start, length, StandardCharsets.UTF_8));
        } catch (NumberFormatException nfe) {
          throw new NumberFormatException("doc at offset " + (globalOffset + start) + ": could not parse field \"" + fields[fieldUpto].name + "\" as double: " + nfe.getMessage());
        }
        if (field != null) {
          field.setDoubleValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[fieldUpto];
        if (point != null) {
          BytesRef br = point.binaryValue();
          DoublePoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[fieldUpto];
        if (dv != null) {
          dv.setLongValue(NumericUtils.doubleToSortableLong(value));
          reuseDoc.add(dv);
        }
        break;
      }
    case DATE_TIME:
      {
        Field field = reuseFields[fieldUpto];
        String s = new String(bytes, start, length, StandardCharsets.UTF_8);
        FieldDef.DateTimeParser parser = fields[fieldUpto].getDateTimeParser();
        parser.position.setIndex(0);
        Date date = parser.parser.parse(s, parser.position);
        if (parser.position.getErrorIndex() != -1) {
          // nocommit more details about why?
          throw new IllegalArgumentException("doc at offset " + (globalOffset + start) + ": could not parse field \"" + fields[fieldUpto].name + "\", value \"" + s + "\" as date with format \"" + fields[fieldUpto].dateTimeFormat + "\"");
        }
        if (parser.position.getIndex() != s.length()) {
          // nocommit more details about why?          
          throw new IllegalArgumentException("doc at offset " + (globalOffset + start) + ": could not parse field \"" + fields[fieldUpto].name + "\", value \"" + s + "\" as date with format \"" + fields[fieldUpto].dateTimeFormat + "\"");
        }
        long value = date.getTime();
        if (field != null) {
          field.setLongValue(value);
          reuseDoc.add(field);
        }
        Field point = reusePoints[fieldUpto];
        if (point != null) {
          BytesRef br = point.binaryValue();
          LongPoint.encodeDimension(value, br.bytes, 0);
          reuseDoc.add(point);
        }
        Field dv = reuseDVs[fieldUpto];
        if (dv != null) {
          dv.setLongValue(value);
          reuseDoc.add(dv);
        }
        break;
      }
    case LAT_LON:
      {
        LatLonPoint point = (LatLonPoint) reusePoints[fieldUpto];
        int i=0;
        for(;i<length;i++) {
          if (bytes[start+i] == SEMICOLON) {
            double lat = MathUtil.parseDouble(bytes, start, i);
            double lon = MathUtil.parseDouble(bytes, start+i+1, length-i-1);
            point.setLocationValue(lat, lon);
            reuseDoc.add(point);
            break;
          }
        }

        if (i == length) {
          throw new IllegalArgumentException("doc at offset " + (globalOffset + start) + ": could not parse field \"" + fields[fieldUpto].name + "\", value \"" + new String(bytes, start, length, StandardCharsets.UTF_8) + "\" as lat;lon format");
        }
        
        break;
      }
    default:
      throw new AssertionError();
    }
  }

  // TODO: this could be a bit faster w/ an DFA + actions (FST):
  
  public Document nextDoc() throws ParseException {
    // clear all prior fields
    reuseDoc.clear();

    int fieldUpto = 0;
    lastDocStart = bufferUpto;

    // this loop must gracefully handle the byte[] ending in the middle of a line, by returning null (doc) and leaving lastDocStart pointing
    // to the beginning of the last line fragment:
    while (bufferUpto < bytes.length) {
      byte b = bytes[bufferUpto];
      if (b == delimChar) {        
        // empty field
        if (fieldUpto == fields.length) {
          throw new IllegalArgumentException("doc at offset " + lastDocStart + ": line has too many fields");
        }
        bufferUpto++;
        fieldUpto++;
      } else if (b == NEWLINE) {
        if (fieldUpto != fields.length) {
          throw new IllegalArgumentException("doc at offset " + lastDocStart + ": line has wrong number of fields: expected " + fields.length + " but saw " + fieldUpto);
        }
        bufferUpto++;
        return reuseDoc;
      } else if (b == DOUBLE_QUOTE) {
        if (fieldUpto == fields.length) {
          throw new IllegalArgumentException("doc at offset " + lastDocStart + ": line has too many fields");
        }
        if (parseEscapedField(fieldUpto) == false) {
          break;
        }
        fieldUpto++;
      } else {
        if (fieldUpto == fields.length) {
          throw new IllegalArgumentException("doc at offset " + lastDocStart + ": line has too many fields");
        }
        if (parseUnescapedField(fieldUpto) == false) {
          break;
        }
        fieldUpto++;
      }
    }

    return null;
  }

  /** Returns true if a field was parsed, else false if the end of the bytes was hit first */
  private boolean parseUnescapedField(int fieldUpto) throws ParseException {
    int fieldStart = bufferUpto;
    while (bufferUpto < bytes.length) {
      byte b = bytes[bufferUpto++];
      if (b == delimChar) {
        addOneField(fieldUpto, fieldStart, bufferUpto - fieldStart - 1);
        return true;
      } else if (b == NEWLINE) {
        addOneField(fieldUpto, fieldStart, bufferUpto - fieldStart - 1);
        // put the newline back so the loop above sees it next:
        bufferUpto--;
        return true;
      }
    }
    return false;
  }

  /** Parses a field escaped with surrounding double quotes.  Embedded double quotes are escaped with double-double quotes.  Else, the field
   *  only ends with a trailing double quote.  Returns true if a field was parsed, else false if the end of the bytes was hit first. */
  private boolean parseEscapedField(int fieldUpto) throws ParseException {
    // We unescape in place as we parse:

    int fieldStart = bufferUpto;

    // bufferUpto is on the first double quote:
    int writeTo = bufferUpto;
    bufferUpto++;
    while (bufferUpto < bytes.length) {
      byte b = bytes[bufferUpto++];
      if (b == DOUBLE_QUOTE) {
        if (bufferUpto == bytes.length) {
          return false;
        }
        if (bytes[bufferUpto] == DOUBLE_QUOTE) {
          // an escaped double quote
          bytes[writeTo++] = DOUBLE_QUOTE;
          bufferUpto++;
        } else {
          if (bufferUpto == bytes.length) {
            return false;
          }
          if (bytes[bufferUpto] == delimChar) {
            bufferUpto++;
          } else if (bytes[bufferUpto] != NEWLINE) {
            throw new IllegalArgumentException("doc at offset " + lastDocStart + ": closing quote must appear only at the end of the cell");
          }
          addOneField(fieldUpto, fieldStart, writeTo - fieldStart);
          return true;
        }
      } else {
        bytes[writeTo++] = b;
      }
    }
    return false;
  }
}
