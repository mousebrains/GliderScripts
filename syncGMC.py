#! /usr/bin/env python3
#
# This script is designed to handle TWR's dockerserver, both legacy and SFMC with projects.
#
# It recursively monitors gmcRoot, typically 
#    /var/opt/gmc for the legacy dockserver and
#    /var/opt/sfmc-dockserver/stations for SFMC.
#
# Anytime a low level directory, matching one of the src directories,
# typically from-glider and logs, is updated, the tree is synced to 
# to the target, with the project removed is it exists.
#
# N.B. The service has a supplemental group, localuser, which can
#      access the directory /var/opt/sfmc-dockserver
#
# March-2019, Pat Welch, pat@mousebrains.com
# Aug-2020, Pat Welch, pat@mousebrains.com, modified for SFMC 8.5 structure change

import argparse
import os
import os.path
import time
import queue
import logging
import re
import MyLogger
import INotify
from RSync import RSync

def mkPath(path:str, args:argparse.ArgumentParser) -> str:
    trigger = re.compile("(.*)(" + "|".join(args.trigger) + ")")
    a = trigger.search(path)
    if a is None: return None

    if args.exclude is not None:
        b = re.search("(" + "|".join(args.exclude) + ")", path)
        if b is not None:
            return None
    return a[1]

def doit(args:argparse.ArgumentParser,
        logger:logging.Logger,
        inotify:INotify.INotify,
        rsync:RSync) -> None:
    timeout = None
    paths = set()

    while inotify.is_alive(): # This should be forever
        try:
            dt = None if timeout is None else max(0.001, (timeout - time.time()))
            evt = inotify.get(timeout=dt)
            inotify.task_done()

            if evt.flags.IGNORED in evt.flags:
                continue

            a = mkPath(evt.path, args)
            if a is None:
                continue

            paths.add(a if os.path.isdir(a) else os.path.dirname(a))
            if timeout is None:
                timeout = evt.t + args.delay # Time out in args.delay seconds from now
        except queue.Empty:
            rsync.put(paths)
            paths = set()
            timeout = None

def initialSync(args:argparse.ArgumentParser, rsync:RSync) -> None:
    paths = set()
    trigger = re.compile("(.*)(" + "|".join(args.trigger) + ")")
    for path in args.dir:
        for (root, dirs, files) in os.walk(path):
            for name in dirs:
                a = mkPath(os.path.join(root, name), args)
                if a is not None: paths.add(a)
            for name in files:
                a = mkPath(os.path.join(root, name), args)
                if a is not None: paths.add(a)
    if len(paths):
        rsync.put(paths)


parser = argparse.ArgumentParser(description="Test a simple iNotify interface")
parser.add_argument("dir", nargs="+", metavar="directory", help="Directories to monitor")
parser.add_argument("--delay", type=int, default=30, metavar="seconds",
        help="After a trigger event is received, how long before rsync is initiated")
parser.add_argument("--trigger", type=str, action="append", required=True, metavar="/from_glider", 
        help="Directories that initiate an rsync event")
parser.add_argument("--exclude", type=str, action="append", metavar="/.archived-deployments",
        help="Directories to ignore updates from")
parser.add_argument("--noInitial", action="store_true", help="Do not do an initial sync")
MyLogger.addArgs(parser)
RSync.addArgs(parser)
args = parser.parse_args()

logger = MyLogger.mkLogger(args)

rsync = RSync(args, logger)
rsync.start()
inotify = INotify.INotify(logger)
inotify.start()

mask = INotify.Flags( \
            INotify.Flags.CLOSE_WRITE |
            INotify.Flags.MOVED_TO |
            INotify.Flags.MOVED_FROM |
            INotify.Flags.MOVE_SELF | 
            INotify.Flags.DELETE |
            INotify.Flags.DELETE_SELF |
            INotify.Flags.CREATE) # For directory recursion

for path in args.dir:
    inotify.add(path, recursive=True, mask=mask)

if not args.noInitial:
    initialSync(args, rsync) 

try:
    doit(args, logger, inotify, rsync)
except:
    logger.exception("Unexpected exception, waiting for rsync to finish before exiting")

rsync.join() # Wait for rsync tasks to complete
