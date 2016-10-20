import io
import gzip
import traceback
#import sys
#sys.path.insert(0, '/home/ec2-user/src/ui')
import util
import handle

# Entry point in production:
def application(environ, startResponse):
  return util.handleOnePage(environ, startResponse, handle.handleQuery)
