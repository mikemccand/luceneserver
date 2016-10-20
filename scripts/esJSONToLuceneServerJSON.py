import struct
import json
import sys

class BlockedFileReader:

  def __init__(self, fileName):
    self.f = open(fileName, 'rb')
    self.pending = self.read()
    self.pendingUpto = 0

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    self.f.close()

  def read(self):
    b = self.f.read(8)
    if len(b) == 0:
      return None
    count, length = struct.unpack('ii', b)
    data = self.f.read(length)
    return data

  def readline(self):
    while True:
      i = self.pending.find(b'\n', self.pendingUpto)
      if i == -1:
        self.pending = self.pending[self.pendingUpto:]
        self.pendingUpto = 0
        inc = self.read()
        if inc is None:
          if len(self.pending) > 0:
            result = self.pending
            self.pending = b''
            return result
          else:
            return None
        else:
          self.pending += inc
      else:
        result = self.pending[self.pendingUpto:i+1]
        self.pendingUpto = i+1
        return result

class BlockedFileWriter:

  def __init__(self, fileName, minBlockBytes):
    self.f = open(fileName, 'wb')
    self.minBlockBytes = minBlockBytes
    self.pending = []
    self.pendingLength = 0

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    self.f.close()

  def add(self, b):
    if b'\n' in b:
      raise RuntimeError('entry cannot contain newline')
    self.pending.append(b)
    self.pendingLength += len(b)+1
    if self.pendingLength > self.minBlockBytes:
      self.flush()

  def flush(self):
    self.f.write(struct.pack('ii', len(self.pending), self.pendingLength))
    self.f.write(b'\n'.join(self.pending) + b'\n')
    self.pending = []
    self.pendingLength = 0

  def close(self):
    if len(self.pending) > 0:
      self.flush()
    self.f.close()
    
srcFile, destFile = sys.argv[1:3]

with BlockedFileReader(srcFile) as fIn, BlockedFileWriter(destFile, 1024*1024) as fOut:
  while True:
    if fIn.readline() is None:
      break
    s = fIn.readline()
    #print("add %s" % s)
    fOut.add(s[:-1])
