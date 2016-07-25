import json

id = 0
pending = []
pendingByteCount = 0
pendingDocCount = 0
with open('/lucenedata/enwiki/enwiki-20120502-lines-1k-fixed-utf8.txt', 'r', encoding='utf-8') as f, open('/lucenedata/enwiki/enwiki-20120502-lines-1k-fixed-utf8.txt.blocks', 'wb') as fOut:
  f.readline()
  while True:
    line = f.readline()
    if line == '':
      break
    title, date, body = line.split('\t')
    if id > 0:
      pending.append(',\n'.encode('utf-8'))
      pendingByteCount += 2
    s = json.dumps({'fields': {'body': body, 'title': title, 'id': id}}).encode('utf-8')
    pending.append(s)
    pendingByteCount += len(s)
    pendingDocCount += 1
    id += 1

    if pendingByteCount > 128*1024:
      fOut.write(('%d %d\n' % (pendingByteCount, pendingDocCount)).encode('utf-8'))
      fOut.write(b''.join(pending))
      pending.clear()
      pendingByteCount = 0
      pendingDocCount = 0
