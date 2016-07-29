package org.apache.lucene.server.util;

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

import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.LuceneTestCase;
import org.junit.AfterClass;
import org.junit.BeforeClass;

import java.nio.charset.StandardCharsets;

public class TestMathUtil extends LuceneTestCase {

  public void testRandomDoubles() throws Exception {
    int iters = atLeast(10000);
    for(int i=0;i<iters;i++) {
      double v1 = random().nextDouble();
      String s = Double.toString(v1);
      BytesRef bytes = getBytes(s);
      double v2 = MathUtil.parseDouble(bytes.bytes, bytes.offset, bytes.length);
      assertEquals(v1, v2, 0.0);
    }
  }

  public void testRandomFloats() throws Exception {
    int iters = atLeast(10000);
    for(int i=0;i<iters;i++) {
      float v1 = random().nextFloat();
      String s = Float.toString(v1);
      BytesRef bytes = getBytes(s);
      float v2 = MathUtil.parseFloat(bytes.bytes, bytes.offset, bytes.length);
      assertEquals(v1, v2, 0.0);
    }
  }

  public void testRandomLongs() throws Exception {
    int iters = atLeast(10000);
    for(int i=0;i<iters;i++) {
      long v1 = random().nextLong();
      String s = Long.toString(v1);
      BytesRef bytes = getBytes(s);
      long v2 = MathUtil.parseLong(bytes.bytes, bytes.offset, bytes.length);
      assertEquals(v1, v2);
    }
  }

  public void testRandomInts() throws Exception {
    int iters = atLeast(10000);
    for(int i=0;i<iters;i++) {
      int v1 = random().nextInt();
      String s = Integer.toString(v1);
      BytesRef bytes = getBytes(s);
      int v2 = MathUtil.parseInt(bytes.bytes, bytes.offset, bytes.length);
      assertEquals(v1, v2);
    }
  }

  private BytesRef getBytes(String s) {
    byte[] bytes = s.getBytes(StandardCharsets.UTF_8);
    if (random().nextBoolean()) {
      return new BytesRef(bytes);
    } else {
      int prefix = random().nextInt(20);
      int suffix = random().nextInt(20);
      byte[] totalBytes = new byte[prefix + bytes.length + suffix];
      System.arraycopy(bytes, 0, totalBytes, prefix, bytes.length);
      return new BytesRef(totalBytes, prefix, bytes.length);
    }
  }
}
