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
import java.io.StringReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

import org.apache.lucene.document.BinaryDocValuesField;
import org.apache.lucene.document.Document;
import org.apache.lucene.document.DoubleDocValuesField;
import org.apache.lucene.document.DoublePoint;
import org.apache.lucene.document.Field;
import org.apache.lucene.document.FieldType;
import org.apache.lucene.document.FloatDocValuesField;
import org.apache.lucene.document.FloatPoint;
import org.apache.lucene.document.IntPoint;
import org.apache.lucene.document.LatLonDocValuesField;
import org.apache.lucene.document.LatLonPoint;
import org.apache.lucene.document.LongPoint;
import org.apache.lucene.document.NumericDocValuesField;
import org.apache.lucene.document.SortedDocValuesField;
import org.apache.lucene.document.SortedNumericDocValuesField;
import org.apache.lucene.document.SortedSetDocValuesField;
import org.apache.lucene.facet.FacetField;
import org.apache.lucene.facet.sortedset.SortedSetDocValuesFacetField;
import org.apache.lucene.index.DocValuesType;
import org.apache.lucene.index.IndexOptions;
import org.apache.lucene.server.Constants;
import org.apache.lucene.server.FieldDef;
import org.apache.lucene.server.FinishRequest;
import org.apache.lucene.server.GlobalState;
import org.apache.lucene.server.IndexState;
import org.apache.lucene.server.params.*;
import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.NumericUtils;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;

import net.minidev.json.JSONArray;
import net.minidev.json.JSONObject;
import net.minidev.json.JSONValue;

/** Handles {@code addDocument}, by delegating the single
 *  document to {@link BulkAddDocumentHandler}. */
public class AddDocumentHandler extends Handler {

  /** Type for a document. */
  public final static StructType DOCUMENT_TYPE = new StructType(
                                       new Param("fields", "Fields to index into one document",
                                           new StructType(
                                                          new Param("anyFieldName", "A name/value pair for this document.  Multiple name/values can be specified, but each field name must already have been registered via @registerFields.  The type of the value must match how the field was registered.", new AnyType()))));

  /** Parmeter type. */
  final StructType TYPE = new StructType(
                                     new Param("indexName", "Index name", new StringType()));

  /** Sole constructor. */
  public AddDocumentHandler(GlobalState state) {
    super(state);
    TYPE.params.putAll(DOCUMENT_TYPE.params);
  }

  @Override
  public StructType getType() {
    return TYPE;
  }

  @Override
  public String getTopDoc() {
    return "Adds one document to the index.  Returns the index generation (indexGen) that contains this added document.";
  }

  static class MyField extends Field {
    public MyField(String name, FieldType ft, Object value) {
      super(name, ft);
      fieldsData = value;
    }
  }

  /** Parses value for one field. */
  @SuppressWarnings({"unchecked"})
  private static void parseOneNativeValue(FieldDef fd, Document doc, Object o, float boost) {

    assert o != null;
    assert fd != null;
    
    if (fd.fieldType.stored() || fd.fieldType.indexOptions() != IndexOptions.NONE || fd.fieldType.docValuesType() != DocValuesType.NONE) {
      switch(fd.valueType) {
      case TEXT:
      case ATOM:
        if (!(o instanceof String)) {
          fail(fd.name, "expected String value but got " + o);
        }
        break;
      case BOOLEAN:
        if (!(o instanceof Boolean)) {
          fail(fd.name, "expected Boolean value but got " + o.getClass());
        }
        // Turn boolean -> int now
        if (o == Boolean.TRUE) {
          o = Integer.valueOf(1);
        } else {
          o = Integer.valueOf(0);
        }
        break;
      case FLOAT:
      case DOUBLE:
        if (!(o instanceof Number)) {
          fail(fd.name, "for float or double field, expected Number value but got " + o);
        }
        break;
      case LAT_LON:
        if (o instanceof double[] == false) {
          fail(fd.name, "for latlon field, expected [lat, lon] double array " + o);
        }
        break;
      case INT:
      case LONG:
        // int or long
        if (!(o instanceof Integer) && !(o instanceof Long)) {
          fail(fd.name, "for int or long field, expected Integer or Long value but got " + o + " of class=" + o.getClass());
        }
        break;
      case DATE_TIME:
        // turn date time into msec since epoch:
        if (!(o instanceof String)) {
          fail(fd.name, "for date_time field, expected String but got " + o + " of class=" + o.getClass());
        }
        String s = (String) o;
        FieldDef.DateTimeParser parser = fd.getDateTimeParser();
        parser.position.setIndex(0);
        Date date = parser.parser.parse(s, parser.position);
        if (parser.position.getErrorIndex() != -1) {
          fail(fd.name, "could not parse \"" + o + "\" as date_time with format \"" + fd.dateTimeFormat + "\"");
        }
        if (parser.position.getIndex() != s.length()) {
          fail(fd.name, "could not parse \"" + o + "\" as date_time with format \"" + fd.dateTimeFormat + "\"");
        }
        o = date.getTime();        
        break;
      default:
        throw new AssertionError();
      }
    }

    if (fd.faceted.equals("flat")) {

      if (o instanceof List) { 
        fail(fd.name, "value should be String when facet=flat; got JSONArray");
      }
        
      doc.add(new FacetField(fd.name, o.toString()));
    } else if (fd.faceted.equals("hierarchy")) {
      if (o instanceof List) {
        if (fd.multiValued) {
          List<List<String>> values = (List<List<String>>) o;
          for(List<String> sub : values) {
            doc.add(new FacetField(fd.name, sub.toArray(new String[sub.size()])));
          }
        } else {
          List<String> values = (List<String>) o;
          doc.add(new FacetField(fd.name, values.toArray(new String[values.size()])));
        }
      } else {
        doc.add(new FacetField(fd.name, o.toString()));
      }
    } else if (fd.faceted.equals("sortedSetDocValues")) {
      if (o instanceof List) { 
        fail(fd.name, "value should be String when facet=sortedSetDocValues; got JSONArray");
      }
      doc.add(new SortedSetDocValuesFacetField(fd.name, o.toString()));
    }

    if (fd.highlighted) {
      assert o instanceof String;
      if (fd.multiValued && (((String) o).indexOf(Constants.INFORMATION_SEP) != -1)) {
        // TODO: we could remove this restriction if it
        // ever matters ... we can highlight multi-valued
        // fields at search time without stealing a
        // character:
        fail(fd.name, "multiValued and hihglighted fields cannot contain INFORMATION_SEPARATOR (U+001F) character: this character is used internally when highlighting multi-valued fields");
      }
    }

    // Separately index doc values:
    DocValuesType dvType = fd.fieldType.docValuesType();
    if (dvType == DocValuesType.BINARY || dvType == DocValuesType.SORTED) {
      if (o instanceof String == false) {
        fail(fd.name, "expected String but got: " + o);
      }
      BytesRef br = new BytesRef((String) o);
      if (fd.fieldType.docValuesType() == DocValuesType.BINARY) {
        doc.add(new BinaryDocValuesField(fd.name, br));
      } else {
        doc.add(new SortedDocValuesField(fd.name, br));
      }
    } else if (dvType == DocValuesType.SORTED_SET) {
      if (o instanceof List) { 
        List<String> values = (List<String>) o;
        for(String _o : values) {
          doc.add(new SortedSetDocValuesField(fd.name, new BytesRef(_o)));
        }
      } else {
        doc.add(new SortedSetDocValuesField(fd.name, new BytesRef((String) o)));
      }
    } else if (fd.valueType == FieldDef.FieldValueType.LAT_LON && dvType == DocValuesType.SORTED_NUMERIC) {
      double[] latLon = (double[]) o;
      doc.add(new LatLonDocValuesField(fd.name, latLon[0], latLon[1]));
    } else if (dvType == DocValuesType.NUMERIC || dvType == DocValuesType.SORTED_NUMERIC) {
      if (fd.valueType == FieldDef.FieldValueType.FLOAT) {
        if (fd.multiValued) {
          doc.add(new SortedNumericDocValuesField(fd.name, NumericUtils.floatToSortableInt(((Number) o).floatValue())));
        } else {
          doc.add(new FloatDocValuesField(fd.name, ((Number) o).floatValue()));
        }
      } else if (fd.valueType == FieldDef.FieldValueType.DOUBLE) {
        if (fd.multiValued) {
          doc.add(new SortedNumericDocValuesField(fd.name, NumericUtils.doubleToSortableLong(((Number) o).doubleValue())));
        } else {
          doc.add(new DoubleDocValuesField(fd.name, ((Number) o).doubleValue()));
        }
      } else if (fd.valueType == FieldDef.FieldValueType.INT) {
        if (fd.multiValued) {
          doc.add(new SortedNumericDocValuesField(fd.name, ((Number) o).intValue()));
        } else {
          doc.add(new NumericDocValuesField(fd.name, ((Number) o).intValue()));
        }
      } else if (fd.valueType == FieldDef.FieldValueType.LONG || fd.valueType == FieldDef.FieldValueType.DATE_TIME) {
        if (fd.multiValued) {
          doc.add(new SortedNumericDocValuesField(fd.name, ((Number) o).longValue()));
        } else {
          doc.add(new NumericDocValuesField(fd.name, ((Number) o).longValue()));
        }
      } else {
        assert fd.valueType == FieldDef.FieldValueType.BOOLEAN;
        if (fd.multiValued) {
          doc.add(new SortedNumericDocValuesField(fd.name, ((Integer) o).intValue()));
        } else {
          doc.add(new NumericDocValuesField(fd.name, ((Integer) o).intValue()));
        }
      }
    }

    // maybe add separate points field:
    if (fd.usePoints) {
      if (fd.valueType == FieldDef.FieldValueType.INT) {
        doc.add(new IntPoint(fd.name, ((Number) o).intValue()));
      } else if (fd.valueType == FieldDef.FieldValueType.LONG || fd.valueType == FieldDef.FieldValueType.LONG) {
        doc.add(new LongPoint(fd.name, ((Number) o).longValue()));
      } else if (fd.valueType == FieldDef.FieldValueType.FLOAT) {
        doc.add(new FloatPoint(fd.name, ((Number) o).floatValue()));
      } else if (fd.valueType == FieldDef.FieldValueType.DOUBLE) {
        doc.add(new DoublePoint(fd.name, ((Number) o).doubleValue()));
      } else if (fd.valueType == FieldDef.FieldValueType.LAT_LON) {
        double[] latLon = (double[]) o;
        doc.add(new LatLonPoint(fd.name, latLon[0], latLon[1]));
      } else {
        throw new AssertionError();
      }
    }
      
    if (fd.fieldType.stored() || fd.fieldType.indexOptions() != IndexOptions.NONE) {
      // We use fieldTypeNoDV because we separately added (above) the doc values field:
      Field f = new MyField(fd.name, fd.fieldTypeNoDV, o);
      f.setBoost(boost);
      doc.add(f);
    }
  }

  /** Used by plugins to process a document after it was
   *  created from the JSON request. */
  public interface PostHandle {
    // nocommit need test coverage:
    /** Invoke the handler, non-streaming. */
    public void invoke(IndexState state, Request r, Document doc) throws IOException;
    /** Invoke the handler, streaming. */
    public boolean invoke(IndexState state, String fieldName, JsonParser p, Document doc) throws IOException;
  }

  static final List<PostHandle> postHandlers = new CopyOnWriteArrayList<PostHandle>();
  
  /** Record a new {@link PostHandle}. */
  public static void addPostHandle(PostHandle handler) {
    postHandlers.add(handler);
  }

  /** Parses the string value to the appropriate type. */
  /*
  public static Object fixType(FieldDef fd, String value) {
    Object o;
    if (fd.valueType.equals("int")) {
      o = Integer.valueOf(Integer.parseInt(value));
    } else if (fd.valueType.equals("long")) {
      o = Long.valueOf(Long.parseLong(value));
    } else if (fd.valueType.equals("float")) {
      o = Float.valueOf(Float.parseFloat(value));
    } else if (fd.valueType.equals("double")) {
      o = Double.valueOf(Double.parseDouble(value));
    } else {
      o = value;
    }
    return o;
  }
  */

  static void fail(String fieldName, String message) {
    throw new IllegalArgumentException("field=" + fieldName + ": " + message);
  }

  /** Parses the fields, which should look like {field1:
   *  ..., field2: ..., ...} */
  public static void parseFields(IndexState state, Document doc, JsonParser p) throws IOException {
    JsonToken token = p.nextToken();
    if (token != JsonToken.START_OBJECT) {
      throw new IllegalArgumentException("fields should be an object");
    }
    while (true) {
      token = p.nextToken();
      if (token == JsonToken.END_OBJECT) {
        break;
      }
      assert token == JsonToken.FIELD_NAME;
      parseOneField(p, state, doc, p.getText());
    }
  }

  /** Parse a Document using Jackson's streaming parser
   *  API.  The document should look like {indexName: 'foo',
   *  fields: {..., ...}} */
  public static Document parseDocument(IndexState state, JsonParser p) throws IOException {
    JsonToken token = p.nextToken();
    if (token == JsonToken.END_ARRAY) {
      // nocommit hackish.. caller should tell us this means "end"?
      return null;
    } else if (token != JsonToken.START_OBJECT) {
      throw new IllegalArgumentException("expected JSON Object");
    }

    final Document doc = new Document();
    while (true) {
      token = p.nextToken();
      if (token == JsonToken.END_OBJECT) {
        break;
      }
      assert token == JsonToken.FIELD_NAME: token;

      String fieldName = p.getText();
      if (fieldName.equals("fields")) {
        parseFields(state, doc, p);
      } else {
        // Let a plugin handle it:
        boolean handled = false;
        for(PostHandle postHandle : postHandlers) {
          if (postHandle.invoke(state, fieldName, p, doc)) {
            handled = true;
            break;
          }
        }

        if (!handled) {
          throw new IllegalArgumentException("unrecognized field " + p.getText());
        }
      }

      // nocommit need test that same field name can't
      // appear more than once?  app must put all values for
      // a given field into an array (for a multi-valued
      // field) 
    }

    return doc;
  }

  /** Parses a field's value, which is an array in the
   *  multi-valued case, or an object of the appropriate type
   *  in the single-valued case. */
  private static void parseOneField(JsonParser p, IndexState state, Document doc, String name) throws IOException {
    parseOneValue(state.getField(name), p, doc);
  }

  /** Parses the current json token into the corresponding
   *  java object. */
  private static Object getNativeValue(FieldDef fd, JsonToken token, JsonParser p) throws IOException {
    Object o;
    if (token == JsonToken.VALUE_STRING) {
      o = p.getText();
    } else if (token == JsonToken.VALUE_NUMBER_INT) {
      o = Long.valueOf(p.getLongValue());
    } else if (token == JsonToken.VALUE_NUMBER_FLOAT) {
      o = Double.valueOf(p.getDoubleValue());
    } else if (token == JsonToken.VALUE_TRUE) {
      o = Boolean.TRUE;
    } else if (token == JsonToken.VALUE_FALSE) {
      o = Boolean.FALSE;
    } else if (fd.faceted.equals("hierarchy") && token == JsonToken.START_ARRAY) {
      if (fd.multiValued == false) {
        List<String> values = new ArrayList<>();
        while (true) {
          token = p.nextToken();
          if (token == JsonToken.END_ARRAY) {
            break;
          } else if (token != JsonToken.VALUE_STRING) {
            if (token == JsonToken.START_ARRAY) {
              fail(fd.name, "expected array of strings, but saw array inside array");
            } else {
              fail(fd.name, "expected array of strings, but saw " + token + " inside array");
            }
          }
          values.add(p.getText());
        }
        o = values;
      } else  {
        List<List<String>> values = new ArrayList<>();
        while (true) {
          token = p.nextToken();
          if (token == JsonToken.END_ARRAY) {
            break;
          } else if (token == JsonToken.START_ARRAY) {
            List<String> sub = new ArrayList<>();
            values.add(sub);
            while (true) {
              token = p.nextToken();
              if (token == JsonToken.VALUE_STRING) {
                sub.add(p.getText());
              } else if (token == JsonToken.END_ARRAY) {
                break;
              } else {
                fail(fd.name, "expected array of strings or array of array of strings, but saw " + token + " inside inner array");
              }
            }
          } else if (token == JsonToken.VALUE_STRING) {
            List<String> sub = new ArrayList<>();
            values.add(sub);
            sub.add(p.getText());
          } else if (token == JsonToken.START_ARRAY) {
            fail(fd.name, "expected array of strings, but saw array inside array");
          } else {
            fail(fd.name, "expected array of strings, but saw " + token + " inside array");
          }
        }
        o = values;
      }
    } else if (fd.valueType == FieldDef.FieldValueType.LAT_LON) {
      if (token != JsonToken.START_ARRAY) {
        fail(fd.name, "latlon field must be [lat, lon] value; got " + token);
      }
      double[] latLon = new double[2];
      token = p.nextToken();
      if (token != JsonToken.VALUE_NUMBER_FLOAT) {
        fail(fd.name, "latlon field must be [lat, lon] value; got " + token);
      }
      latLon[0] = p.getDoubleValue();
      token = p.nextToken();
      if (token != JsonToken.VALUE_NUMBER_FLOAT) {
        fail(fd.name, "latlon field must be [lat, lon] value; got " + token);
      }
      latLon[1] = p.getDoubleValue();
      token = p.nextToken();
      if (token != JsonToken.END_ARRAY) {
        fail(fd.name, "latlon field must be [lat, lon] value; got " + token);
      }
      o = latLon;
    } else {
      String message;
      if (token == JsonToken.VALUE_NULL) {
        message = "null field value not supported; just omit this field from the document instead";
      } else {
        message = "value in inner object field value should be string, int/long, float/double or boolean; got " + token;
      }

      fail(fd.name, message);

      // Dead code but compiler disagrees:
      o = null;
    }
    return o;
  }
  
  /** Parse one value for a field, which is either an
   *  object matching the type of the field, or a {boost:
   *  ..., value: ...}. */
  private static boolean parseOneValue(FieldDef fd, JsonParser p, Document doc) throws IOException {

    Object o = null;
    float boost = 1.0f;

    JsonToken token = p.nextToken();
    if (token == JsonToken.START_ARRAY) {
      if ("hierarchy".equals(fd.faceted) || fd.valueType == FieldDef.FieldValueType.LAT_LON) {
        o = getNativeValue(fd, token, p);
      } else {
        if (fd.multiValued == false) {
          fail(fd.name, "expected single value, not array, since this field is not multiValued");        
        }
        while (true) {
          if (!parseOneValue(fd, p, doc)) {
            break;
          }
        }
        return true;
      }
    } else {
      
      if (token == JsonToken.END_ARRAY) {
        assert fd.multiValued;
        return false;
      }

      if (fd.fieldType.indexOptions() != IndexOptions.NONE && token == JsonToken.START_OBJECT) {
        // Parse a {boost: X, value: Y}
        while(true) {
          token = p.nextToken();
          if (token == JsonToken.END_OBJECT) {
            break;
          }
          assert token == JsonToken.FIELD_NAME;
          String key = p.getText();
          if (key.equals("boost")) {
            token = p.nextToken(); 
            if (token == JsonToken.VALUE_NUMBER_INT || token == JsonToken.VALUE_NUMBER_FLOAT) {
              boost = p.getFloatValue();
            } else {
              fail(fd.name, "boost in inner object field value must have float or int value; got: " + token);
            }
          } else if (key.equals("value")) {
            o = getNativeValue(fd, p.nextToken(), p);
          } else {
            fail(fd.name, "unrecognized json key \"" + key + "\" in inner object field value; must be boost or value");
          }
        }
        if (o == null) {
          fail(fd.name, "missing 'value' key");
        }
      } else {
        // Parse a native value:
        o = getNativeValue(fd, token, p);
      }
    }
    
    parseOneNativeValue(fd, doc, o, boost);
    return true;
  }

  @Override
  public FinishRequest handle(final IndexState indexState, final Request r, Map<String,List<String>> params) throws Exception {

    indexState.verifyStarted(r);

    // NOTE: somewhat wasteful since we re-serialize to
    // string only to re-parse the JSON, but this allows
    // single-source (bulk) for parsing, and apps that care
    // about performance will use bulk APIs:

    JSONObject raw = r.getRawParams();
    StringBuilder sb = new StringBuilder();
    sb.append(raw.get("fields").toString());
    sb.append('\n');
    raw.clear();

    final String bulkRequestString = sb.toString();

    return new FinishRequest() {
      @Override
      public String finish() throws Exception {
        String result = globalState.getHandler("bulkAddDocument").handleStreamed(new StringReader(bulkRequestString),
                                                                                 Collections.singletonMap("indexName", Collections.singletonList(indexState.name)));
        if (result.indexOf("errors") != -1) {
          JSONObject o = (JSONObject) JSONValue.parseStrict(result);
          if (o.containsKey("errors")) {
            JSONObject err = (JSONObject) ((JSONArray) o.get("errors")).get(0);
            throw new IllegalArgumentException((String) err.get("exception"));
          }
        }
        return result;
      }
    };
  }
}
