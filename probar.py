#! /usr/bin/env python3
#
# Monitor a target directory, .../glider/to-glider, ...
# and when there is a new file, then copy a tbd and an sbd file
# into a from-glider directory for testing purposes
#
# This assumes sync2FMC0.py is running and writing files into --src
#
# This is designed to run as a service.
#
# March-2019, Pat Welch, pat@mousebrains.com

import sys
import shutil
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
import re
import io
import random

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

class Historical(MyBaseThread):
  def __init__(self, gld, logger, qExcept, args):
    MyBaseThread.__init__(self, 'Hist(' + gld + ')', logger, qExcept)
    self.gld = gld
    self.args = args
    self.queue = queue.Queue()

  def put(self, item):
    self.queue.put(item)

  def __initialize__(self):
    self.index = 0
    a = {}
    for root, dirs, files in os.walk(os.path.join(self.args.historical, self.gld)):
      for fn in files:
        (seq, suffix) = os.path.splitext(fn)
        if seq not in a:
          a[seq] = []
        a[seq].append(os.path.join(root, fn))

    self.files = []
    for key in sorted(a):
      self.files.append(a[key])

  def __initDirs__(self):
    self.tgt = os.path.join(self.args.toGlider, self.gld, 'from-glider')
    if not os.path.isdir(self.tgt):
      os.makedirs(self.tgt)
    for root, dirs, files in os.walk(self.tgt):
      for fn in files:
        fn = os.path.join(root, fn)
        self.logger.debug('Removing %s', fn)
        os.unlink(fn)

  def __copyNext__(self, delayInit, sigmaInit): 
    index = self.index
    if index < len(self.files):
      name = self.tgt
      self.__delay__(delayInit, sigmaInit)
      for fn in self.files[index]:
        self.logger.debug('Copy %s into %s', fn, name)
        shutil.copyfile(fn, os.path.join(name, os.path.basename(fn)))
        self.__delay__(self.args.delayIntra, self.args.delayIntraSigma)
      self.index += 1

  def __delay__(self, delay, sigma):
    if delay is not None and sigma is not None:
      delay = random.gauss(delay, sigma)
      if delay <= 0:
        delay = None
    if delay is not None and delay > 0:
      self.logger.info('Sleeping for %s seconds', delay)
      time.sleep(delay)

  def runMain(self): # Called on thread start
    self.__initialize__()
    self.__initDirs__()
    self.__copyNext__(self.args.delayInit, self.args.delayInitSigma)
    q = self.queue
    lastTime = 0
    while True:
      (t, gld) = q.get()
      q.task_done()
      if t <= lastTime:
        continue
      self.logger.info("t=%s", t)
      self.__copyNext__(self.args.delayPostMA, self.args.delayPostMASigma)
      self.__delay__(self.args.delayDive, self.args.delayDiveSigma)
      lastTime = time.time()
    
    return

class Monitor(MyBaseThread):
  def __init__(self, gld, src, fn, logger, qExcept, doit):
    MyBaseThread.__init__(self, 'Mon(' + gld + ')', logger, qExcept)
    self.gld = gld
    self.src = src
    self.fn = fn
    self.doit = doit

  def runMain(self): # Called on thread start
    src = os.path.join(self.src, self.gld, 'to-glider')
    if not os.path.isdir(src):
      raise Exception('Source "' + src + '" is not a directory')

    self.logger.info('Starting %s', src)

    files = set()
    for fn in self.fn:
      files.add(fn)
    self.logger.info('Files=%s', str(files))

    cmd = ['/usr/bin/inotifywait', \
		'--monitor', \
		'--quiet', \
		'--recursive', \
		'--event', 'close_write', \
		'--event', 'attrib', \
		'--event', 'moved_to', \
		'--format', '%w%f', \
                src]

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
          self.logger.debug('%s is not in files list', line)
          continue
        self.logger.debug('file %s glider %s file %s', line, self.gld, fn)
        self.doit.put((time.time(), self.gld))

parser = argparse.ArgumentParser()
parser.add_argument('--gliders', action='append', required=True, help='List of gliders to process')
parser.add_argument('--historical', required=True, help='Historical source directory')
parser.add_argument('--toGlider', required=True, help='to-glider directory')
parser.add_argument('--delayInit', type=float, help='Delay before starting to populate to-glider')
parser.add_argument('--delayInitSigma', type=float, \
                    help='Noise in delay before starting to populate to-glider')
parser.add_argument('--delayPostMA', type=float, help='Delay after an MA file is seen')
parser.add_argument('--delayPostMASigma', type=float, \
                    help='Noise in delay after an MA file is seen')
parser.add_argument('--delayIntra', type=float, help='Delay between TBD and SBD copies')
parser.add_argument('--delayIntraSigma', type=float, \
                    help='Noise in delay between TBD and SBD copies')
parser.add_argument('--delayDive', type=float, help='Dive duration in seconds')
parser.add_argument('--delayDiveSigma', type=float, help='Noise in dive duration')

parser.add_argument('--src', required=True, help='Source directory to monitor')
parser.add_argument('--fn', required=True, action='append', \
                    help='Filename to send from src to tgt when it changes')
parser.add_argument('--log', help='Log filename, if not specified use the console')
parser.add_argument('--maxlogsize', type=int, default=10000000, \
                    help='How large to let the log file grow to')
parser.add_argument('--backupcount', type=int, default=5, help='How many logfiles to keep')
parser.add_argument('--delay', type=int, default=10, help='How many logfiles to keep')
parser.add_argument('--verbosity', default='ERROR', \
                    help='Logging verbosity level ERROR|WARN|INFO|DEBUG')
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

try:
  logger.debug('Args %s', args)

  excQueue = queue.Queue() # Where thread exceptions are sent

  threads = []
  for gld in args.gliders:
    thrH = Historical(gld, logger, excQueue, args)
    thrH.start()
    thrM = Monitor(gld, args.src, args.fn, logger, excQueue, thrH)
    thrM.start()
    threads.append(thrH)
    threads.append(thrM)

  e = excQueue.get() # Wait for an exception from a thread
  raise(e)
except Exception as e:
  logger.exception('Thread exception')

sys.exit(1)
