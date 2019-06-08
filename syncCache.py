#! /usr/bin/env python3.6
#
# Copy all files in a set of source directories to a target directory
# As new files show up, copy them too.
#
# Don't delete files from the target directory
#
# Designed for handling SFMC cache files which are in:
# /var/opt/sfmc-dataserver/stations/*/dataFiles/cache
#
# April-2019, Pat Welch, pat@mousebrains.com

import sys
import time
import os
import os.path
import argparse
import logging
import logging.handlers
import threading
import queue
import subprocess
import getpass
import socket

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
  def __init__(self, args, src, logger, qExcept, syncer):
    MyBaseThread.__init__(self, 'Mon.{}'.format(src), logger, qExcept)
    self.args = args
    self.src = src
    self.syncer = syncer

  def runMain(self): # Called on thread start
    args = self.args
    syncer = self.syncer
    logger = self.logger

    rootDir = os.path.join(args.prefix, self.src, args.suffix)

    logger.info('Starting: %s', rootDir)

    cmd = [self.args.inotifywait, '--monitor', '--quiet', '--recursive', '--format', '%w', \
          '--event', 'close_write', \
          '--event', 'attrib', \
          '--event', 'move', \
          rootDir]

    logger.debug(' '.join(cmd))

    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc: # Incase of exception
      if not args.noInitial: # Do after we start the subprocess, so hopefully we won't miss updates
        syncer.put((time.time(), rootDir))
      while True:
        line = proc.stdout.readline()
        if line == '' and proc.poll() is not None:
          raise Exception('inotifywait failed, ' + ' '.join(cmd))
        if not line:
          continue
        line = str(line.rstrip(b"\n/"), 'utf-8')
        src = line
        tgt = []
        logger.debug('Line "%s"', line)
        syncer.put((time.time(), line))

class Syncer(MyBaseThread):
  def __init__(self, logger, qExcept, args):
    MyBaseThread.__init__(self, 'Syncer', logger, qExcept)
    self.args = args
    self.queue = queue.Queue()

  def put(self, a): # Put things in my queue, called by MonitorGMC
    self.queue.put(a)

  def runMain(self): # Called on thread start
    args = self.args
    logger = self.logger
    q = self.queue
    logger.info('Starting %s', self.args.tgt)
    prevTime = {}

    while True:
      (t, src) = q.get()
      logger.debug('t=%s src=%s', t, src)
      q.task_done()
      if src in prevTime and t < prevTime[src]: # Skip recent updates
        continue
      logger.debug('delay=%s for src=%s', args.delay, src)
      time.sleep(args.delay)
      prevTime[src] = t + args.delay
      self.syncit(src)

  def syncit(self, src):
    args = self.args
    logger = self.logger
    tgt = args.tgt
    cmd = [args.rsync, \
	   '--archive', \
	   '--delay-updates', \
	   '--chmod=' + args.chmod, \
           src, \
           tgt]

    logger.debug(' '.join(cmd))
    if args.dryrun:
      logger.info('Not syncing %s to %s due to dryrun', src, tgt)
      return True
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode == 0: # Success
      logger.info('Synced %s to %s', src, tgt)
    else:
      logger.error('Error syncing %s to %s\n, %s', src, tgt, p.stdout)


parser = argparse.ArgumentParser()
parser.add_argument('--prefix', default='/var/opt/sfmc-dataserver/stations', 
                    help='Directory prefix to be prepended to src')
parser.add_argument('--suffix', default='dataFiles/cache',
                    help='Directory suffix to be appended to src')
parser.add_argument('--src', action='append', required=True, 
                    help='Top of directory tree to monitor')
parser.add_argument('--tgt', help='Where to send the files', required=True)
parser.add_argument('--log', help='Log filename, if not specified use the console')
parser.add_argument('--delay', default=1, type=int,
       help='How long to wait after an inotify event to wait before starting rsync in seconds')
parser.add_argument('--maxlogsize', default=10000000, type=int,
       help='How large to let the log file grow to')
parser.add_argument('--backupcount', default=5, type=int, help='How many logfiles to keep')
parser.add_argument('--chmod', default='Do+rx,Fo+r', help='chmod on rync command')
parser.add_argument('--dryrun', help='Do not actually copy the files', action='store_true')
parser.add_argument('--verbosity', help='Logging verbosity level ERROR|WARN|INFO|DEBUG', default='ERROR')
parser.add_argument('--inotifywait', default='/usr/bin/inotifywait', help='inotifywait command to use')
parser.add_argument('--rsync', default='/usr/bin/rsync', help='rsync command to use')
parser.add_argument('--noInitial', action='store_true', help='Do not do an initial sync')
parser.add_argument('--mailTo', help='Who to mail errors to', action='append')
parser.add_argument('--mailHost', help='SMTP hostname', default='localhost')
parser.add_argument('--mailFrom', help='Who mail is coming from',
                    default=getpass.getuser() + '@' + socket.gethostname())
parser.add_argument('--mailSubject', help='Subject of mail',
                    default="ERROR: " + socket.gethostname())
args = parser.parse_args()

logger = logging.getLogger(__name__)
logger.setLevel(args.verbosity)

ch = logging.StreamHandler() if args.log is None else \
     logging.handlers.RotatingFileHandler(args.log, maxBytes=args.maxlogsize, backupCount=args.backupcount)
ch.setLevel(args.verbosity)
ch.setFormatter(logging.Formatter('%(asctime)s: %(threadName)s:%(levelname)s - %(message)s'))
logger.addHandler(ch)

if args.mailTo:
  ch = logging.handlers.SMTPHandler(args.mailHost, args.mailFrom, args.mailTo, args.mailSubject)
  ch.setLevel(logging.ERROR)
  ch.setFormatter(logging.Formatter('%(threadName)s:%(levelname)s - %(message)s'))
  logger.addHandler(ch)

try:
  logger.info('Args %s', args)

  qExcept = queue.Queue() # Where thread exceptions are sent

  thrSyncer = Syncer(logger, qExcept, args)
  thrSyncer.start()

  threads = []
  for src in args.src:
    thr = Monitor(args, src, logger, qExcept, thrSyncer)
    thr.start()
    threads.append(thr)

  e = qExcept.get() # Wait for an exception from a thread
  qExcept.task_done()
  raise(e)
except Exception as e:
  logger.exception('Thread exception')

sys.exit(1)
