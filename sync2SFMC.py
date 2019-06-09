#! /usr/bin/env python3
#
# Monitor a directory recursively for updates using inotifywait.
# The directory structure below src is expected to be
#   glider/file
#
# which will then be copied to 
#   tgt/glider/to-glider/file
#
# A dated copy of the file will be archived into
#   archive/glider/file.YYYYMMDD.HHMMSS
#
# This is designed to run as a service.
#
# March-2019, Pat Welch, pat@mousebrains.com

import sys
import time
import os.path
import argparse
import logging
import logging.handlers
import threading
import queue
import subprocess
import getpass
import socket
import re
import io
import smtplib
from email.message import EmailMessage

class MyBaseThread(threading.Thread):
  def __init__(self, name, logger, qExcept):
    threading.Thread.__init__(self, daemon=True)
    self.name = name
    self.logger = logger
    self.qExcept = qExcept

  def run(self): # Called on thread start. Will pass any exception to qExcept so program can exit
    q = self.qExcept
    try:
      self.runMain()
    except Exception as e:
      self.logger.exception('Unexpected exception')
      q.put(e)

  def runMain(self): # Should be overridden by main thread
    raise Exception('runMain not overridden by derived class')

class Monitor(MyBaseThread):
  def __init__(self, src, fn, logger, qExcept, doit):
    MyBaseThread.__init__(self, 'Monitor', logger, qExcept)
    self.src = src
    self.fn = fn
    self.doit = doit

  def runMain(self): # Called on thread start
    src = self.src
    if not os.path.isdir(src):
      raise Exception('Source "' + src + '" is not a directory')

    self.logger.info('Starting %s: %s', self.src, str(self.fn))

    files = set()
    for fn in self.fn:
      files.add(fn)
    self.logger.info(files)

    cmd = ['/usr/bin/inotifywait', \
		'--monitor', \
		'--quiet', \
		'--recursive', \
		'--event', 'close_write', \
		'--event', 'attrib', \
		'--event', 'moved_to', \
		'--format', '%w%f', \
                self.src]

    self.logger.debug('cmd %s', ' '.join(cmd))

    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
      while True:
        line = proc.stdout.readline()
        if line == '' and proc.poll() is not None:
          raise Exception('inotifywait failed, ' + str(cmd))
        if not line:
          self.logger.warn('empty line')
          continue
        line = str(line.strip(), 'utf-8')
        fn = os.path.basename(line) # Filename to consider
        if fn not in files: # Not a file of interest
          self.logger.warn('%s is not in files list', line)
          continue
        prefix = os.path.dirname(line)
        if os.path.dirname(prefix) != self.src:
          self.logger.warn('Invalid directory structure for %s', line)
          continue
        gld = os.path.basename(prefix)
        self.logger.debug('file %s glider %s file %s', line, gld, fn)
        self.doit.put((time.time(), line, gld, fn))

class LineIO: # Iterable class of lines
  def __init__(self, lines):
    self.index = 0 # Next index to read
    self.lines = []
    if lines is None:
      return
    for line in lines:
      index = line.find('#') # Find a comment character
      if index >= 0:
         line = line[0:index] # Drop off trailing comment
      line = line.strip()
      if line: # non-empty line, so append
        self.lines.append(line)

  def __iter__(self):
    return self;

  def __next__(self):
    if self.index < len(self.lines): # something to return
      self.index = self.index + 1
      return self.lines[self.index - 1]
    raise StopIteration
    
class Doit(MyBaseThread):
  def __init__(self, logger, qExcept, args):
    MyBaseThread.__init__(self, 'Doit', logger, qExcept)
    self.archiveDir = args.archive
    self.tgt = args.tgt
    self.qDryrun = args.dryrun
    self.delay = args.delay
    self.notify = args.notify
    self.mailFrom = args.mailFrom
    self.mailHost = args.mailHost
    self.queue = queue.Queue()
    self.bargPattern = re.compile("^\w+(\w+)$", flags=re.ASCII)

  def put(self, a):
    self.queue.put(a)

  def runMain(self): # Called on thread start
    q = self.queue
    self.logger.info('Starting')
    history = {}
    delay = self.delay
    if delay <= 0:
      delay = 0.1

    while True:
      (t, src, gld, fn) = q.get()
      q.task_done()
      if src in history and (t <= (history[src] + delay)): # Ignore quick updates
        continue
      history[src] = t
      time.sleep(delay) # Wait a bit for everything to settle
      (lines, afn) = self.archiveFile(t, src, gld, fn)
      if lines is None: # Unable to open the file
        continue
      if not self.qSane(lines, afn):
        continue
      self.logger.debug('afn=%s\n', afn)
      self.syncit(afn, os.path.join(self.tgt, gld, 'to-glider', fn))
      if args.notify:
        self.notifier(lines.lines, fn, gld)

  def archiveFile(self, t, src, gld, fn):
    adir = os.path.join(self.archiveDir, gld)
    if not os.path.isdir(adir):
      os.makedirs(adir)
    afn = os.path.join(adir, str(time.strftime("%Y%m%d.%H%M%S.")) + os.path.basename(fn))
    try:
      ifp = open(src, 'r')
    except FileNotFoundError as e:
      self.logger.error("Error opening %s for reading", src)
      return (None, afn)
    lines = []
    with open(afn, 'w') as ofp, ifp:
      lines = ifp.readlines()
      ofp.writelines(lines)
    os.remove(src)
    self.logger.info('Copied and removed %s to %s', src, afn)
    return (LineIO(lines), afn)


  def qSane(self, lines, fn):
    for line in lines:
      if line == "behavior_name=goto_list": # Must be first non-blank line
        return self.qSaneGoto(lines, fn)
      self.logger.error("Unsupported behavior file '%s' %s", fn, line)
      return False
    self.logger.error('No behavior_name line found in %s', fn)
    return False

  def qSaneGoto(self, lines, fn):
    bargs = None
    waypts = -1
    for line in lines:
      if line == "<start:b_arg>":
        bargs = self.qSaneBArg(lines, fn)
        if not bargs:
          return False
      elif line == "<start:waypoints>":
        waypts = self.qSaneWaypoints(lines, fn)
        if waypts is None:
          return False
      else:
        self.logger.error('Unsupported line "%s" in %s', line, fn)
        return False
    if 'num_waypoints(nodim)' not in bargs:
      self.logger.error('num_waypoints(nodim) not in %s', fn);
      return False
    if bargs['num_waypoints(nodim)'] != waypts:
      self.logger.error('num_waypoints(nodim) (%s) and number of waypoints (%s) do not match in %s', bargs['num_waypoints(nodim)'], waypts, fn)
      return False
    if bargs['num_waypoints(nodim)'] > 8:
      self.logger.error('num_waypoints(nodim) (%s) must be 8 or less in %s', bargs['num_waypoints(nodim)'], fn)
      return False
    if bargs['num_waypoints(nodim)'] < 1:
      self.logger.error('num_waypoints(nodim) (%s) must be >= 1 in %s', bargs['num_waypoints(nodim)'], fn)
      return False
    if bargs['num_waypoints(nodim)'] > 8:
      self.logger.error('num_waypoints(nodim) (%s) must be <= 8 in %s', bargs['num_waypoints(nodim)'], fn)
      return False
    return True

  def qSaneBArg(self, lines, fn):
    info = {}
    for line in lines:
      if line == "<end:b_arg>":
         return info
      fields = line.split()
      if len(fields) != 3:
        self.logger.error('Line "%s" does not have three fields', line)
        return False
      if fields[0] != 'b_arg:':
        self.logger.error('Line "%s" does not begin with b_arg:', line)
        return {}
      if re.match(self.bargPattern, fields[1]):
        self.logger.error('Variable in "%s" is not formated properly', line)
        return {}
      try:
        val = float(fields[2])
        info[fields[1]] = val
      except ValueError:
        self.logger.error('Third field in "%s" is not numeric', line)
        return {}
   
    self.logger.error('No <end:b_arg> found for %s', fn)
    return {}

  def qSaneWaypoints(self, lines, fn):
    count = 0
    for line in lines:
      if not line:
        continue
      if line == "<end:waypoints>":
        if count > 0:
          return count
        self.logger.error('No waypoints found in %s', fn)
        return None
      fields = line.split()
      if len(fields) != 2:
        self.logger.error('Line "%s" in %s does not have two fields', line, fn)
        return {}
      try:
        lon = float(fields[0])
        lat = float(fields[1])
        if lon < -18000 or lon > 18000:
          self.logger.error('Longitude(%s) is out of range in %s', line, fn)
          return None
        if lat < -9000 or lat > 9000:
          self.logger.error('Latitude(%s) is out of range in %s', line, fn)
          return None
        if (abs(lon) % 100) >= 60:
          self.logger.error('Longitude(%s) minutes are out of range in %s', line, fn)
          return None
        if (abs(lat) % 100) >= 60:
          self.logger.error('Latitude(%s) minutes are out of range in %s', line, fn)
          return None
        count += 1
      except ValueError:
        self.logger.error('Unable to convert "%s" into a pair of numbers in %s', line, fn)
        return None
     
    self.logger.error('No <end:waypoints> found in %s', fn)
    return None

  def syncit(self, src, tgt):
    cmd = ['/usr/bin/rsync', '--quiet', '--archive', '--delay-updates', src, tgt]
    self.logger.debug(' '.join(cmd))
    if self.qDryrun:
      self.logger.info('Not syncing %s to %s due to dryrun', src, tgt)
      return True
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode == 0: # Success
      self.logger.info('Synced %s to %s', src, tgt)
      return True
    self.logger.error('Error syncing %s to %s\n, %s', src, tgt, str(p.stdout, 'utf-8'))
    return False 

  def notifier(self, lines, fn, gld):
    msg = EmailMessage()
    msg['Subject'] = "{} {}".format(gld, fn)
    msg['From'] = self.mailFrom
    msg['To'] = self.notify
    a = []
    state = 0
    for line in lines:
      if state == 0 and line == '<start:waypoints>':
        state = 1
      elif state == 1:
        if line == '<end:waypoints>':
          state == 0
        else:
          a.append(line)
    msg.set_content('\n'.join(a))
    s = smtplib.SMTP(self.mailHost)
    s.send_message(msg)
    s.quit()

parser = argparse.ArgumentParser()
parser.add_argument('--src', help='Source directory to monitor', required=True, action='append')
parser.add_argument('--tgt', help='Where to send the files', required=True)
parser.add_argument('--archive', help='Where to make a dated backup copy of the file at', required=True)
parser.add_argument('--fn', help='Filename to send from src to tgt when it changes', required=True, action='append')
parser.add_argument('--log', help='Log filename, if not specified use the console')
parser.add_argument('--maxlogsize', default=10000000, type=int, \
			help='How large to let the log file grow to')
parser.add_argument('--backupcount', default=5, type=int, help='How many logfiles to keep')
parser.add_argument('--delay', default=10, type=int, help='How many logfiles to keep')
parser.add_argument('--dryrun', help='Do not actually copy the files', action='store_true')
parser.add_argument('--verbosity', help='Logging verbosity level ERROR|WARN|INFO|DEBUG', default='ERROR')
parser.add_argument('--notify', help='Who to mail notifications to', action='append')
parser.add_argument('--mailTo', help='Who to mail errors to', action='append')
parser.add_argument('--mailHost', help='SMTP hostname', default='localhost')
parser.add_argument('--mailFrom', help='Who mail is coming from',
                    default=getpass.getuser() + '@' + socket.gethostname())
parser.add_argument('--mailSubject', help='Subject of mail',
                    default="ERROR: " + socket.gethostname())
args = parser.parse_args()

logger = logging.getLogger(__name__)
logger.setLevel(args.verbosity)

if args.log is None:
  ch = logging.StreamHandler()
else:
  name = os.path.dirname(args.log)
  if not os.path.isdir(name):
    os.makedirs(name)
  ch = logging.handlers.RotatingFileHandler(args.log, \
                 maxBytes=args.maxlogsize, backupCount=args.backupcount)
ch.setLevel(args.verbosity)
ch.setFormatter(logging.Formatter('%(asctime)s: %(threadName)s:%(levelname)s - %(message)s'))
logger.addHandler(ch)

if args.mailTo: # Where to send error messages to
  ch = logging.handlers.SMTPHandler(args.mailHost, args.mailFrom, args.mailTo, args.mailSubject)
  ch.setLevel(logging.ERROR)
  ch.setFormatter(logging.Formatter('%(threadName)s:%(levelname)s - %(message)s'))
  logger.addHandler(ch)

try:
  logger.debug('Args %s', args)

  excQueue = queue.Queue() # Where thread exceptions are sent

  thrDoit = Doit(logger, excQueue, args)
  thrDoit.start()

  threads = []

  for src in args.src:
    thr = Monitor(src, args.fn, logger, excQueue, thrDoit)
    thr.start()
    threads.append(thr)

  e = excQueue.get() # Wait for an exception from a thread
  excQueue.task_done()
  raise(e)
except Exception as e:
  logger.exception('Thread exception')

sys.exit(1)
