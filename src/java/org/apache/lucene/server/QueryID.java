package org.apache.lucene.server;

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

import java.util.Arrays;

import org.apache.lucene.util.StringHelper;

/** Uniquely identifies a query; just a thin wrapper around a byte[] so we can define equals/hashCode. */

public class QueryID {

  public final byte[] id;
    
  public QueryID() {
    this(StringHelper.randomId());
  }
    
  public QueryID(byte[] id) {
    this.id = id;
  }

  @Override
  public boolean equals(Object other) {
    if (other instanceof QueryID) {
      return Arrays.equals(((QueryID) other).id, id);
    } else {
      return false;
    }
  }      

  @Override
  public int hashCode() {
    return Arrays.hashCode(id);
  }

  @Override
  public String toString() {
    return StringHelper.idToString(id);
  }
}
