#import sys
#sys.path.insert(0, '/home/changingbits/src/ui')
import util
import handle

# Entry point in production:
def application(environ, startResponse):
  return util.handleOnePage(environ, startResponse, handle.handleSuggest)
