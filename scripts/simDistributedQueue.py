import time
import random
import threading

# TODO: get fifo working

printLock = threading.Lock()

def message(s):
  if False:
    with printLock:
      print(s)

class Node(threading.Thread):

  def __init__(self, id, nodes):
    threading.Thread.__init__(self)
    self.id = id
    self.queueLock = threading.Condition()
    self.queryQueue = {}
    self.queryDone = []
    self.nodes = nodes

  def addQuery(self, queryID, text):
    message('N%d: add query Q%s' % (self.id, queryID))
    with self.queueLock:
      if queryID in self.queryQueue:
        if self.queryQueue[queryID][1] == 0:
          raise RuntimeError('duplicated query ID %s' % queryID)
        else:
          x = self.queryQueue.pop(queryID)
          self.queryDone.append((queryID, text, x[2]))
      else:
        self.queryQueue[queryID] = [text, 0]
        self.queueLock.notify()

  def takeNextQuery(self):
    with self.queueLock:
      while True:
        for queryID, l in self.queryQueue.items():
          text, state = l
          if state == 0:
            # 2 means "I am taking this query"
            l[1] = 2
            return queryID
        self.queueLock.wait()

  def takeQuery(self, queryID, remoteNodeID):
        
    with self.queueLock:
      l = self.queryQueue.get(queryID)
      if l is not None:
        if l[1] in (0, 1) or remoteNodeID < self.id:
          # Resolve race condition by always yielding to the lower numbered node ID
          self.queryDone.append((queryID, l[0], remoteNodeID))
          del self.queryQueue[queryID]
          return True
        else:
          if remoteNodeID == self.id:
            raise RuntimeError('duplicated node ID %s' % remoteNodeID);
          message('N%d: reject take query Q%d' % (self.id, queryID))
          return False
      else:
        # It's a new query, that hasn't yet been enqueued here:
        message('N%d: take brand new query Q%d' % (self.id, queryID))
        self.queryQueue[queryID] = [None, 1, remoteNodeID]
        return True

  def finishedQuery(self, queryID):
    with self.queueLock:
      x = self.queryQueue.pop(queryID)
      self.queryDone.append((queryID, x[0], self.id))
      message('N%d: finishQuery Q%s; now %s done' % (self.id, queryID, len(self.queryDone)))

  def run(self):
    while True:

      # Find a query we can try to take:
      queryID = self.takeNextQuery()
      message('N%d: try to take Q%s' % (self.id, queryID))

      # Ask the other nodes if it's OK if we take this one:
      for node in self.nodes:
        if node != self:
          if not node.takeQuery(queryID, self.id):
            message('N%d: failed to take Q%d' % (self.id, queryID))
            break
      else:
        # OK we execute the query!
        message('N%s: run query Q%s' % (self.id, queryID))
        sleepTimeUS = random.randint(0, 1000)
        time.sleep(sleepTimeUS/1000000.)
        self.finishedQuery(queryID)

def main():

  numNodes = 2
  nodes = []
  for nodeID in range(numNodes):
    message('start node %s' % nodeID)
    node = Node(nodeID, nodes)
    nodes.append(node)
    node.start()

  for queryID in range(1000):
    for node in nodes:
      node.addQuery(queryID, 'text')
    sleepTimeUS = random.randint(0, 1000)
    time.sleep(sleepTimeUS/1000000.)

  while True:
    for node in nodes:
      if len(node.queryQueue) > 0:
        time.sleep(0.1)
        message('N%s still has %d queries in its queue...' % (node.id, len(node.queryQueue)))
        with node.queueLock:
          for queryID, l in node.queryQueue.items():
            message('  query Q%d: flag %s' % (queryID, l[1]))
        break
    else:
      break

  seen = set()
  for node in nodes:
    message('N%d finished %d queries' % (node.id, len(node.queryDone)))
    for queryID, queryText, remoteNodeID in node.queryDone:
      if remoteNodeID == node.id:
        if queryID in seen:
          raise RuntimeError('query Q%s ran more than once' % queryID)
        seen.add(queryID)
      
            
  print('done!')

if __name__ == '__main__':
  main()
  
