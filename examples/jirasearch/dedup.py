with open('allIssues.txt', 'rb') as f, open('allIssues.dedup.txt', 'wb') as fOut:
  seen = set()
  while True:
    l = f.readline()
    if l == b'':
      break
    i = l.find(b':')
    key = l[:i]
    if key not in seen:
      seen.add(key)
      fOut.write(l)
    else:
      print('skip dup %s' % key)
