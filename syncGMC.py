#! /usr/bin/env python3
#
# This is designed to handle TWR's dockserver, both legacy and SFMC with projects.
# It recursively monitors gmcRoot, typically /var/opt/gmc, and anytime
# a low level directory matching one of the src directories, typically from-glider and logs,
# that directory will be synced to the target.
# It is assumed the directory structure is something like:
# /var/opt/gmc/*/gliders/from-glider
# which works with both the legacy and SFMC versions of the dockserver
#
# March-2019, Pat Welch, pat@mousebrains.com

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

def syncit(args, src, tgt, logger):
 try:
  cmd = [args.rsync, \
	 '--archive', \
	 '--delete', \
	 '--delay-updates', \
	 '--chmod=' + args.chmod]
  for item in args.exclude:
    cmd.extend(['--exclude', item])
  cmd.append(src)
  cmd.append(tgt)

  logger.debug(' '.join(cmd))
  if args.dryrun:
    logger.info('Not syncing %s to %s due to dryrun', src, tgt)
    return True
  p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  if p.returncode == 0: # Success
    logger.info('Synced %s to %s', src, tgt)
    return True
  logger.error('Error syncing %s to %s\n, %s', src, tgt, p.stdout)
  return False
 except Exception as e:
  logger.exception('src=%s tgt=%s', src, tgt)
  return False

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

  
class MonitorGMC(MyBaseThread):
  def __init__(self, args, logger, qExcept, syncer):
    MyBaseThread.__init__(self, 'MonitorGMC', logger, qExcept)
    self.args = args
    self.syncer = syncer

  def runMain(self): # Called on thread start
    gmcRoot = self.args.gmcRoot
    self.logger.info('Starting: %s, %s', gmcRoot, self.args.exclude)

    cmd = [self.args.inotifywait, '--monitor', '--quiet', '--recursive', '--format', '%w', \
          '--exclude', '\.~tmp~', \
          '--event', 'close_write', \
          '--event', 'attrib', \
          '--event', 'move', \
          '--event', 'delete']

    for item in self.args.exclude:
      cmd.extend(['--exclude', item])

    cmd.append(gmcRoot)

    self.logger.debug(' '.join(cmd))

    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc: # Incase of exception
      if not args.noInitial: # Do after we start the subprocess, so hopefully we won't miss updates
        self.initialSync()
      while True:
        line = proc.stdout.readline()
        if line == '' and proc.poll() is not None:
          raise Exception('inotifywait failed, ' + ' '.join(cmd))
        if not line:
          continue
        line = str(line.rstrip(b"\n/"), 'utf-8')
        src = line
        tgt = []
        qFoundGliders = False
        # self.logger.debug('TPW Line "%s"', line)
        while (len(line)) > 0 and (len(tgt) < 20):
          # self.logger.debug('WHILE Line "%s"', line)
          tgtFN = os.path.basename(line)
          if tgtFN == '':
            qFoundGliders = False
            break
          tgt.append(tgtFN)
          # self.logger.debug('WHILE tgt "%s"', tgt)
          if tgt[-1] == 'gliders':
            qFoundGliders = True
            break
          line = os.path.dirname(line)
          # self.logger.debug('WHILE End "%s"', line)
        if qFoundGliders:
          tgt.reverse()
          prefix = '/'.join(tgt[1:])
          self.logger.debug('inotify: src %s prefix %s line %s', src, prefix, line)
          self.syncer.put((time.time(), src, prefix, True))
        else:
          self.logger.debug('inotify: src %s skipped', src)

    for (dirpath, dirnames, filenames) in os.walk(self.args.gmcRoot):
      gld = os.path.basename(dirpath)
      for name in dirnames:
        if name not in exclude:
          self.syncer.put((time.time(), name, gld, os.path.join(dirpath, name), False))

  def initialSync(self):
    for (dirpath, dirnames, filenames) in os.walk(self.args.gmcRoot):
      if os.path.basename(dirpath) == 'gliders':
        syncit(self.args, dirpath + '/', self.args.tgt, self.logger)

class Syncer(MyBaseThread):
  def __init__(self, logger, qExcept, args):
    MyBaseThread.__init__(self, 'Syncer', logger, qExcept)
    self.args = args
    self.queue = queue.Queue()

  def put(self, a): # Put things in my queue, called by MonitorGMC
    self.queue.put(a)

  def runMain(self): # Called on thread start
    q = self.queue
    self.logger.info('Starting %s', self.args.tgt)
    prevTime = {}

    while True:
      (t, src, prefix, qDelay) = q.get()
      q.task_done()
      self.logger.info('t=%s src=%s prefix=%s q=%s', t, src, prefix, qDelay)

      if prefix in prevTime and t < prevTime[prefix]: # Ignore quick updates
        self.logger.debug('Ignoring %s at %s', prefix, t)
        continue
      if qDelay and self.args.delay is not None and self.args.delay > 0:
        time.sleep(self.args.delay) # Wait for intermediate inotify events to happen
      prevTime[prefix] = time.time() # Current time
      tgt = os.path.join(self.args.tgt, os.path.dirname(prefix)) # Drop last element of dirpath
      syncit(self.args, src, tgt, self.logger)

parser = argparse.ArgumentParser()
parser.add_argument('--gmcRoot', default='/var/opt/gmc', # For TWR's SFMC/Dockserver
                    help='Prefix for source directories to monitor')
parser.add_argument('--tgt', help='Where to send the files', required=True)
parser.add_argument('--exclude', action='append', 
                    help='Which directories/files to not sync, [.archived-deployments]')
parser.add_argument('--log', help='Log filename, if not specified use the console')
parser.add_argument('--delay', default=10, type=int,
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
  if args.exclude is None:
    args.exclude = ['.archived-deployments']

  logger.debug('Args %s', args)

  qExcept = queue.Queue() # Where thread exceptions are sent

  thrSyncer = Syncer(logger, qExcept, args)
  thrSyncer.start()

  thrGMC = MonitorGMC(args, logger, qExcept, thrSyncer)
  thrGMC.start()

  e = qExcept.get() # Wait for an exception from a thread
  qExcept.task_done()
  raise(e)
except Exception as e:
  logger.exception('Thread exception')

sys.exit(1)
