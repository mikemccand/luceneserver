package org.apache.lucene.server.util;

/*
 * Javolution - Java(TM) Solution for Real-Time and Embedded Systems
 * Copyright (C) 2012 - Javolution (http://javolution.org/)
 * All rights reserved.
 * 
 * Permission to use, copy, modify, and distribute this software is
 * freely granted, provided that this notice is preserved.
 */

import java.nio.charset.StandardCharsets;

// TODO: port the algorithms from http://dl.acm.org/citation.cfm?id=2717032

public class MathUtil {

  private static final int INT_MAX_DIV10 = Integer.MAX_VALUE / 10;
  private static final long LONG_MAX_DIV10 = Long.MAX_VALUE / 10;

  private static final long MASK_63 = 0x7FFFFFFFFFFFFFFFL;

  private static final long MASK_32 = 0xFFFFFFFFL;

  private static final int[] POW5_INT = { 1, 5, 25, 125, 625, 3125, 15625,
                                          78125, 390625, 1953125, 9765625, 48828125, 244140625, 1220703125 };

  private MathUtil() {
    // no
  }

  /**
   * Returns the closest <code>double</code> representation of the
   * specified <code>long</code> number multiplied by a power of two.
   *
   * @param m the <code>long</code> multiplier. (must be non-negative)
   * @param n the power of two exponent.
   * @return <code>m * 2<sup>n</sup></code>.
   */
  private static double toDoublePow2(long m, int n) {
    assert m >= 0;
    if (m == 0)
      return 0.0;
    int bitLength = Long.SIZE - Long.numberOfLeadingZeros(m);
    int shift = bitLength - 53;
    long exp = 1023L + 52 + n + shift; // Use long to avoid overflow.
    if (exp >= 0x7FF)
      return Double.POSITIVE_INFINITY;
    if (exp <= 0) { // Degenerated number (subnormal, assume 0 for bit 52)
      if (exp <= -54)
        return 0.0;
      return toDoublePow2(m, n + 54) / 18014398509481984L; // 2^54 Exact.
    }
    // Normal number.
    long bits = (shift > 0) ? (m >> shift) + ((m >> (shift - 1)) & 1) : // Rounding.
      m << -shift;
    if (((bits >> 52) != 1) && (++exp >= 0x7FF))
      return Double.POSITIVE_INFINITY;
    bits &= 0x000fffffffffffffL; // Clears MSB (bit 52)
    bits |= exp << 52;
    return Double.longBitsToDouble(bits);
  }

  /**
   * Returns the closest <code>double</code> representation of the
   * specified <code>long</code> number multiplied by a power of ten.
   *
   * @param m the <code>long</code> multiplier. (must be non-negative)
   * @param n the power of ten exponent.
   * @return <code>multiplier * 10<sup>n</sup></code>.
   **/
  private static double toDoublePow10(long m, int n) {
    assert m >= 0;
    if (m == 0)
      return 0.0;
    if (n >= 0) { // Positive power.
      if (n > 308)
        return Double.POSITIVE_INFINITY;
      // Works with 4 x 32 bits registers (x3:x2:x1:x0)
      long x0 = 0; // 32 bits.
      long x1 = 0; // 32 bits.
      long x2 = m & MASK_32; // 32 bits.
      long x3 = m >>> 32; // 32 bits.
      int pow2 = 0;
      while (n != 0) {
        int i = (n >= POW5_INT.length) ? POW5_INT.length - 1 : n;
        int coef = POW5_INT[i]; // 31 bits max.

        if (((int) x0) != 0)
          x0 *= coef; // 63 bits max.
        if (((int) x1) != 0)
          x1 *= coef; // 63 bits max.
        x2 *= coef; // 63 bits max.
        x3 *= coef; // 63 bits max.

        x1 += x0 >>> 32;
        x0 &= MASK_32;

        x2 += x1 >>> 32;
        x1 &= MASK_32;

        x3 += x2 >>> 32;
        x2 &= MASK_32;

        // Adjusts powers.
        pow2 += i;
        n -= i;

        // Normalizes (x3 should be 32 bits max).
        long carry = x3 >>> 32;
        if (carry != 0) { // Shift.
          x0 = x1;
          x1 = x2;
          x2 = x3 & MASK_32;
          x3 = carry;
          pow2 += 32;
        }
      }

      // Merges registers to a 63 bits mantissa.
      assert x3 >= 0;
      int shift = 31 - (Long.SIZE - Long.numberOfLeadingZeros(x3)); // -1..30
      pow2 -= shift;
      long mantissa = (shift < 0) ? (x3 << 31) | (x2 >>> 1) : // x3 is 32 bits.
        (((x3 << 32) | x2) << shift) | (x1 >>> (32 - shift));
      return toDoublePow2(mantissa, pow2);

    } else { // n < 0
      if (n < -324 - 20)
        return 0.0;

      // Works with x1:x0 126 bits register.
      long x1 = m; // 63 bits.
      long x0 = 0; // 63 bits.
      int pow2 = 0;
      while (true) {

        // Normalizes x1:x0
        int shift = 63 - (Long.SIZE - Long.numberOfLeadingZeros(x1));
        x1 <<= shift;
        x1 |= x0 >>> (63 - shift);
        x0 = (x0 << shift) & MASK_63;
        pow2 -= shift;

        // Checks if division has to be performed.
        if (n == 0)
          break; // Done.

        // Retrieves power of 5 divisor.
        int i = (-n >= POW5_INT.length) ? POW5_INT.length - 1 : -n;
        int divisor = POW5_INT[i];

        // Performs the division (126 bits by 31 bits).
        long wh = (x1 >>> 32);
        long qh = wh / divisor;
        long r = wh - qh * divisor;
        long wl = (r << 32) | (x1 & MASK_32);
        long ql = wl / divisor;
        r = wl - ql * divisor;
        x1 = (qh << 32) | ql;

        wh = (r << 31) | (x0 >>> 32);
        qh = wh / divisor;
        r = wh - qh * divisor;
        wl = (r << 32) | (x0 & MASK_32);
        ql = wl / divisor;
        x0 = (qh << 32) | ql;

        // Adjusts powers.
        n += i;
        pow2 -= i;
      }
      return toDoublePow2(x1, pow2);
    }
  }

  /**
   * Parses the specified byte slice as a signed int.
   */
  public static int parseInt(byte[] bytes, int start, int length) {
    int end = start + length;

    int negMul = -1;
    int i = start;
    if (length > 0) {
      char c = (char) bytes[i];
      if (c == '-') {
        negMul = 1;
        i++;
      } else if (c == '+') {
        i++;
      }
    } else {
      throw new NumberFormatException("cannot convert empty string to int");
    }

    int result = 0; // Accumulates negatively (avoid MIN_VALUE overflow).
    
    for (; i < end; i++) {
      char c = (char) bytes[i];
                        
      int digit =  c - '0';
            
      if (digit >= 10 || digit < 0) {
        throw newNumberFormatException("invalid integer representation", bytes, start, length);
      }
            
      int newResult = result * 10 - digit;
      if (newResult > result) {
        throw newNumberFormatException("overflow", bytes, start, length);
      }
      result = newResult;
    }
        
    // Requires one valid digit character and checks for opposite overflow.
    if ((result == 0) && ((char) bytes[i-1] != '0')) {
      throw newNumberFormatException("invalid integer representation", bytes, start, length);
    }
    if ((result == Integer.MIN_VALUE) && negMul == 1) {
      throw newNumberFormatException("overflow", bytes, start, length);
    }
    return negMul * result;
  }

  /**
   * Parses the specified char slice as a signed int.
   */
  public static int parseInt(char[] chars, int start, int length) {
    int end = start + length;

    int negMul = -1;
    int i = start;
    if (length > 0) {
      char c = chars[i];
      if (c == '-') {
        negMul = 1;
        i++;
      } else if (c == '+') {
        i++;
      }
    } else {
      throw new NumberFormatException("cannot convert empty string to int");
    }

    int result = 0; // Accumulates negatively (avoid MIN_VALUE overflow).
    
    for (; i < end; i++) {
      char c = chars[i];
                        
      int digit =  c - '0';
            
      if (digit >= 10 || digit < 0) {
        throw newNumberFormatException("invalid integer representation", chars, start, length);
      }
            
      int newResult = result * 10 - digit;
      if (newResult > result) {
        throw newNumberFormatException("overflow", chars, start, length);
      }
      result = newResult;
    }
        
    // Requires one valid digit character and checks for opposite overflow.
    if ((result == 0) && chars[i-1] != '0') {
      throw newNumberFormatException("invalid integer representation", chars, start, length);
    }
    if ((result == Integer.MIN_VALUE) && negMul == 1) {
      throw newNumberFormatException("overflow", chars, start, length);
    }
    return negMul * result;
  }

  /**
   * Parses the byte[] slice as a long.
   */
  public static long parseLong(byte[] bytes, int start, int length) {
    final int end = start + length;
    int i = start;
    
    long negMul = -1;
    if (length > 0) {
      char c = (char) bytes[i];
      if (c == '-') {
        negMul = 1;
        i++;
      } else if (c == '+') {
        i++;
      }
    } else {
      throw new NumberFormatException("cannot convert empty string to int");
    }
        
    long result = 0; // Accumulates negatively (avoid MIN_VALUE overflow).
    for (; i < end; i++) {
      char c = (char) bytes[i];
            
      int digit = c - '0';
            
      if (digit >= 10 || digit < 0) {
        throw newNumberFormatException("invalid integer representation", bytes, start, length);
      }
            
      long newResult = result * 10 - digit;
      if (newResult > result) {
        throw newNumberFormatException("overflow", bytes, start, length);
      }
      result = newResult;
    }
    
    // Requires one valid digit character and checks for opposite overflow.
    if ((result == 0) && (bytes[i-1] != (byte) '0')) {
      throw newNumberFormatException("invalid integer representation", bytes, start, length);
    }

    if ((result == Long.MIN_VALUE) && negMul == 1) {
      throw newNumberFormatException("overflow", bytes, start, length);
    }

    return negMul * result;
  }

  /**
   * Parses the char[] slice as a long.
   */
  public static long parseLong(char[] chars, int start, int length) {
    final int end = start + length;
    int i = start;
    
    long negMul = -1;
    if (length > 0) {
      char c = chars[i];
      if (c == '-') {
        negMul = 1;
        i++;
      } else if (c == '+') {
        i++;
      }
    } else {
      throw new NumberFormatException("cannot convert empty string to int");
    }
        
    long result = 0; // Accumulates negatively (avoid MIN_VALUE overflow).
    for (; i < end; i++) {
      char c = chars[i];
            
      int digit = c - '0';
            
      if (digit >= 10 || digit < 0) {
        throw newNumberFormatException("invalid integer representation", chars, start, length);
      }
            
      long newResult = result * 10 - digit;
      if (newResult > result) {
        throw newNumberFormatException("overflow", chars, start, length);
      }
      result = newResult;
    }
    
    // Requires one valid digit character and checks for opposite overflow.
    if ((result == 0) && chars[i-1] != '0') {
      throw newNumberFormatException("invalid integer representation", chars, start, length);
    }

    if ((result == Long.MIN_VALUE) && negMul == 1) {
      throw newNumberFormatException("overflow", chars, start, length);
    }

    return negMul * result;
  }

  /**
   * Parses the specified byte[] slice as a <code>float</code>.
   */
  public static float parseFloat(byte[] bytes, int start, int length) throws NumberFormatException {
    return (float) parseDouble(bytes, start, length);
  }

  /**
   * Parses the specified char[] slice as a <code>float</code>.
   */
  public static float parseFloat(char[] chars, int start, int length) throws NumberFormatException {
    return (float) parseDouble(chars, start, length);
  }

  // nocommit make the exceptions nicer: include the offending string!!

  /**
   * Parses the specified byte[] slice as a <code>double</code>.
   */
  public static double parseDouble(byte[] bytes, int start, int length) throws NumberFormatException {
    if (length == 0) {
      throw new NumberFormatException("cannot parse empty string as double");
    }
    
    int end = start + length;
    int i = start;
    char c = (char) bytes[i];

    // Checks for NaN.
    if (c == 'N') {
      if (match("NaN", bytes, i, end)) {
        return Double.NaN;
      } else {
        throw newNumberFormatException("cannot parse string as double", bytes, start, length);
      }
    }

    // Reads sign.
    double sigNum;
    if (c == '-') {
      sigNum = -1D;
      i++;
      c = (char) bytes[i];
    } else if (c == '+') {
      sigNum = 1D;
      i++;
      c = (char) bytes[i];
    } else {
      sigNum = 1D;
    }

    // Checks for Infinity.
    if (c == 'I') {
      if (match("Infinity", bytes, i, end)) {
        return sigNum == -1 ? Double.NEGATIVE_INFINITY : Double.POSITIVE_INFINITY;
      } else {
        throw newNumberFormatException("cannot parse string as double", bytes, start, length);
      }
    }

    // At least one digit or a '.' required.
    if ((c < '0' || c > '9') && c != '.') {
      throw newNumberFormatException("leading digit or '.' required", bytes, start, length);
    }

    // Reads decimal and fraction (both merged to a long).
    long decimal = 0;
    int decimalPoint = -1;
    while (true) {
      int digit = c - '0';
      if (digit >= 0 && digit < 10) {
        long tmp = decimal * 10 + digit;
        if (decimal > LONG_MAX_DIV10 || tmp < decimal) {
          // we'd overflow here, fall back to BigDecimal method
          // TODO: improve this: can we detect up front?
          return Double.parseDouble(new String(bytes, start, length, StandardCharsets.UTF_8));
        }
        decimal = tmp;
      } else if (c == '.' && decimalPoint == -1) {
        decimalPoint = i;
      } else {
        break;
      }

      if (++i >= end) {
        break;
      }
      c = (char) bytes[i];
    }

    int fractionLength = (decimalPoint >= 0) ? i - decimalPoint - 1 : 0;

    // Reads exponent.
    int exp = 0;
    if (i < end) {
      if (c == 'E' || c == 'e') {
        c = (char) bytes[++i];
        boolean isNegativeExp = (c == '-');
        if ((isNegativeExp || (c == '+')) && (++i < end)) {
          c = (char) bytes[i];
        }
        if ((c < '0') || (c > '9')) { // At least one digit required.  
          throw newNumberFormatException("invalid exponent", bytes, start, length);
        }
        while (true) {
          int digit = c - '0';
          if ((digit >= 0) && (digit < 10)) {
            int tmp = exp * 10 + digit;
            if ((exp > INT_MAX_DIV10) || (tmp < exp)) {
              // we'd overflow here, fall back to BigDecimal method
              // TODO: improve this: can we detect up front?
              return Double.parseDouble(new String(bytes, start, length, StandardCharsets.UTF_8));
            }
            exp = tmp;
          } else
            break;
          if (++i >= end) {
            break;
          }
          c = (char) bytes[i];
        }
        if (isNegativeExp) {
          exp = -exp;
        }
      } else {
        throw newNumberFormatException("extra characters", bytes, start, length);
      }
    }

    return sigNum * toDoublePow10(decimal, exp - fractionLength);
  }

  /**
   * Parses the specified char[] slice as a <code>double</code>.
   */
  public static double parseDouble(char[] chars, int start, int length) throws NumberFormatException {
    if (length == 0) {
      throw new NumberFormatException("cannot parse empty string as double");
    }
    
    int end = start + length;
    int i = start;
    char c = chars[i];

    // Checks for NaN.
    if (c == 'N') {
      if (match("NaN", chars, i, end)) {
        return Double.NaN;
      } else {
        throw newNumberFormatException("cannot parse string as double", chars, start, length);
      }
    }

    // Reads sign.
    double sigNum;
    if (c == '-') {
      sigNum = -1D;
      i++;
      c = chars[i];
    } else if (c == '+') {
      sigNum = 1D;
      i++;
      c = chars[i];
    } else {
      sigNum = 1D;
    }

    // Checks for Infinity.
    if (c == 'I') {
      if (match("Infinity", chars, i, end)) {
        return sigNum == -1 ? Double.NEGATIVE_INFINITY : Double.POSITIVE_INFINITY;
      } else {
        throw newNumberFormatException("cannot parse string as double", chars, start, length);
      }
    }

    // At least one digit or a '.' required.
    if ((c < '0' || c > '9') && c != '.') {
      throw newNumberFormatException("leading digit or '.' required", chars, start, length);
    }

    // Reads decimal and fraction (both merged to a long).
    long decimal = 0;
    int decimalPoint = -1;
    while (true) {
      int digit = c - '0';
      if (digit >= 0 && digit < 10) {
        long tmp = decimal * 10 + digit;
        if (decimal > LONG_MAX_DIV10 || tmp < decimal) {
          // we'd overflow here, fall back to BigDecimal method
          // TODO: improve this: can we detect up front?
          return Double.parseDouble(new String(chars, start, length));
        }
        decimal = tmp;
      } else if (c == '.' && decimalPoint == -1) {
        decimalPoint = i;
      } else {
        break;
      }

      if (++i >= end) {
        break;
      }
      c = chars[i];
    }

    int fractionLength = (decimalPoint >= 0) ? i - decimalPoint - 1 : 0;

    // Reads exponent.
    int exp = 0;
    if (i < end) {
      if (c == 'E' || c == 'e') {
        c = chars[++i];
        boolean isNegativeExp = (c == '-');
        if ((isNegativeExp || (c == '+')) && (++i < end)) {
          c = chars[i];
        }
        if ((c < '0') || (c > '9')) { // At least one digit required.  
          throw newNumberFormatException("invalid exponent", chars, start, length);
        }
        while (true) {
          int digit = c - '0';
          if ((digit >= 0) && (digit < 10)) {
            int tmp = exp * 10 + digit;
            if ((exp > INT_MAX_DIV10) || (tmp < exp)) {
              // we'd overflow here, fall back to BigDecimal method
              // TODO: improve this: can we detect up front?
              return Double.parseDouble(new String(chars, start, length));
            }
            exp = tmp;
          } else
            break;
          if (++i >= end) {
            break;
          }
          c = chars[i];
        }
        if (isNegativeExp) {
          exp = -exp;
        }
      } else {
        throw newNumberFormatException("extra characters", chars, start, length);
      }
    }

    return sigNum * toDoublePow10(decimal, exp - fractionLength);
  }

  /** Assumes ascii!! */
  private static boolean match(String s, byte[] bytes, int start, int end) {
    int length = s.length();
    if (start+length > end) {
      return false;
    }
    for (int i = 0; i < length; i++) {
      if ((char) bytes[start+i] != s.charAt(i)) {
        return false;
      }
    }

    return true;
  }

  private static boolean match(String s, char[] chars, int start, int end) {
    int length = s.length();
    if (start+length > end) {
      return false;
    }
    for (int i = 0; i < length; i++) {
      if (chars[start+i] != s.charAt(i)) {
        return false;
      }
    }

    return true;
  }

  private static NumberFormatException newNumberFormatException(String message, byte[] bytes, int start, int length) {
    return new NumberFormatException(message + ": \"" + new String(bytes, start, length, StandardCharsets.UTF_8) + "\"");
  }

  private static NumberFormatException newNumberFormatException(String message, char[] chars, int start, int length) {
    return new NumberFormatException(message + ": \"" + new String(chars, start, length) + "\"");
  }
}
