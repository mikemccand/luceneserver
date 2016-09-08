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

import java.math.BigDecimal;
import java.math.BigInteger;
import java.math.MathContext;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;

import org.apache.lucene.util.BytesRef;
import org.apache.lucene.util.LuceneTestCase;
import org.apache.lucene.util.TestUtil;
import org.junit.Ignore;

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

  public void testReallyRandomDoubles() throws Exception {
    int iters = atLeast(10000);
    for(int i=0;i<iters;i++) {
      long bits = TestUtil.nextLong(random(), Long.MIN_VALUE, Long.MAX_VALUE);
      double v1 = Double.longBitsToDouble(bits);
      String s = Double.toString(v1);
      BytesRef bytes = getBytes(s);
      double v2 = MathUtil.parseDouble(bytes.bytes, bytes.offset, bytes.length);
      assertEquals(v1, v2, 0.0);
    }
  }

  /**
   * Checks double parse
   * @param expected expected value
   * @param string unparsed string
   * @param delta allowed number of ulps difference
   */
  private void checkDouble(double expected, String string, int delta) {
    long expectedBits = Double.doubleToRawLongBits(expected);
    BytesRef bytes = getBytes(string);
    final double v;
    try {
      v = MathUtil.parseDouble(bytes.bytes, bytes.offset, bytes.length);
    } catch (Throwable t) {
      throw new AssertionError(string + " didn't parse to " + expected + ", instead hit " + t, t);
    }
    try {
      long actualBits = Double.doubleToRawLongBits(v);
      long actualDelta = Math.abs(expectedBits - actualBits);
      if (actualDelta > delta) {
        throw new AssertionError("expected: <" + expectedBits + "> but was:<" + actualBits + ">");
      }
    } catch (Throwable t) {
      throw new AssertionError(string + " didn't parse to " + expected + ", instead: " + v, t);
    }
  }

  public void testInterestingDoubles() throws Exception {
    checkDouble(Double.NaN, Double.toString(Double.NaN), 0);
    checkDouble(Double.POSITIVE_INFINITY, Double.toString(Double.POSITIVE_INFINITY), 0);
    checkDouble(Double.NEGATIVE_INFINITY, Double.toString(Double.NEGATIVE_INFINITY), 0);
    checkDouble(Double.MIN_VALUE, Double.toString(Double.MIN_VALUE), 0);
    checkDouble(Double.MAX_VALUE, Double.toString(Double.MAX_VALUE), 0);
    checkDouble(-Double.MAX_VALUE, Double.toString(-Double.MAX_VALUE), 0);
    checkDouble(Double.MIN_NORMAL, Double.toString(Double.MIN_NORMAL), 0);
    checkDouble(-0D, Double.toString(-0D), 0);
    checkDouble(0D, Double.toString(0D), 0);
  }

  /**
   * Makes something like a random "database" fixed point double, toString's it, and checks parsing.
   * we check up to 100 digits for now.
   */
  public void testDoublesLargerThanLife() throws Exception {
    int iters = atLeast(100000);
    for (int i = 0; i < iters; i++) {
      BigInteger unscaled = TestUtil.nextBigInteger(random(), 42); // ~ log2(10^100)/8
      int scale = TestUtil.nextInt(random(), -100, 100);
      int precision = TestUtil.nextInt(random(), 1, 100);
      BigDecimal bigDecimal = new BigDecimal(unscaled, scale, new MathContext(precision, RoundingMode.HALF_EVEN));
      String encoded = bigDecimal.toString();
      double v = Double.parseDouble(encoded);
      checkDouble(v, encoded, 1);
    }
  }

  @Ignore("1 ulp difference")
  public void testBigDouble() throws Exception {
    String s = "-48687525606695076.0";
    double x1 = Double.parseDouble(s);
    byte[] bytes = s.getBytes("UTF-8");
    double x2 = MathUtil.parseDouble(bytes, 0, bytes.length);
    assertEquals(x1, x2, 0d);
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

  public void testReallyRandomFloats() throws Exception {
    int iters = atLeast(10000);
    for(int i=0;i<iters;i++) {
      int bits = random().nextInt();
      float v1 = Float.intBitsToFloat(bits);
      String s = Float.toString(v1);
      BytesRef bytes = getBytes(s);
      float v2 = MathUtil.parseFloat(bytes.bytes, bytes.offset, bytes.length);
      assertEquals(v1, v2, 0.0);
    }
  }

  /**
   * Checks float parse
   * @param expected expected value
   * @param string unparsed string
   * @param delta allowed number of ulps difference
   */
  private void checkFloat(float expected, String string, int delta) {
    int expectedBits = Float.floatToRawIntBits(expected);
    BytesRef bytes = getBytes(string);
    final float v;
    try {
      v = MathUtil.parseFloat(bytes.bytes, bytes.offset, bytes.length);
    } catch (Throwable t) {
      throw new AssertionError(string + " didn't parse to " + expected + ", instead hit " + t, t);
    }
    try {
      int actualBits = Float.floatToRawIntBits(v);
      int actualDelta = Math.abs(expectedBits - actualBits);
      if (actualDelta > delta) {
        throw new AssertionError("expected: <" + expectedBits + "> but was:<" + actualBits + ">");
      }
    } catch (Throwable t) {
      throw new AssertionError(string + " didn't parse to " + expected + ", instead: " + v, t);
    }
  }

  public void testInterestingFloats() throws Exception {
    checkFloat(Float.NaN, Float.toString(Float.NaN), 0);
    checkFloat(Float.POSITIVE_INFINITY, Float.toString(Float.POSITIVE_INFINITY), 0);
    checkFloat(Float.NEGATIVE_INFINITY, Float.toString(Float.NEGATIVE_INFINITY), 0);
    checkFloat(Float.MIN_VALUE, Float.toString(Float.MIN_VALUE), 0);
    checkFloat(Float.MAX_VALUE, Float.toString(Float.MAX_VALUE), 0);
    checkFloat(-Float.MAX_VALUE, Float.toString(-Float.MAX_VALUE), 0);
    checkFloat(Float.MIN_NORMAL, Float.toString(Float.MIN_NORMAL), 0);
    checkFloat(-0F, Float.toString(-0F), 0);
    checkFloat(0F, Float.toString(0F), 0);
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
