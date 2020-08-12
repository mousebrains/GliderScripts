#! /usr/bin/env python3
#
# This is designed to handle TWR's dockserver, both legacy and SFMC with projects.
# It recursively monitors gmcRoot, typically /var/opt/gmc for legacy servers and
# /var/opt/sfmc-dockserver on SFMC.
# Anytime a low level directory matching one of the src directories,
# typically from-glider and logs,
# that directory will be synced to the target.
# It is assumed the directory structure is something like:
# /var/opt/sfmc-dockserver/stations/*/gliders/from-glider
# which works with both the legacy and SFMC versions of the dockserver
#
# N.B. The service has a supplemental group, localuser, which can 
# access the directory /var/opt/sfmc-dockserver
#
# March-2019, Pat Welch, pat@mousebrains.com
# Aug-2020, Pat Welch, pat@mousebrains.com, modified for SFMC 8.5 structure change

import sys
import os.path
import argparse
import logging
import MyLogger
import pyinotify
import threading
import queue
import re
import time
import subprocess

class Sync(threading.Thread):
    def __init__(self, args:argparse.ArgumentParser, logger:logging.Logger) -> None:
        threading.Thread.__init__(self, daemon=True)
        self.name = "SYNC"
        self.args = args
        self.logger = logger
        self.__queue = queue.Queue()
        self.__exclude = self.__mkRegExp(
                [r"/.archived-deployments/"] if args.exclude is None else args.exclude)
        self.__sources = self.__mkRegExp(
                [r"/.*/gliders/[^/]+/"] if args.source is None else args.source)
        self.__stack = set()

    @staticmethod
    def addArgs(parser:argparse.ArgumentParser) -> None:
        grp = parser.add_argument_group(description="Sync related options")
        grp.add_argument("--exclude", type=str, action="append",
                help="Directories to exclude")
        grp.add_argument("--source", type=str, action="append",
                help="Regular expression to use as sources in rsync")
        grp.add_argument("--rsync", type=str, default="/usr/bin/rsync", metavar="command",
                help="rsync command")
        grp.add_argument("--delay", type=float, default=10, metavar="seconds",
                help="Delay after a notification before starting rsync")
        grp.add_argument("--chmod", type=str, default="Do+rx,Fo+r", help="chmod on rsync command")
        grp.add_argument("--target", type=str, required=True, help="Target of rsync")
        grp.add_argument("--dryrun", action="store_true", help="Do not actually run rsync")

    @staticmethod
    def __mkRegExp(items) -> list:
        a = []
        for item in items:
            a.append(re.compile(item))
        return a

    def put(self, fn:str) -> None:
        self.__queue.put(fn)

    def __processFile(self, fn:str) -> bool:
        for item in self.__exclude:
            if item.search(fn) is not None:
                self.logger.debug("Excluding %s", fn)
                return False
        return True

    def __timedout(self) -> bool:
        logger = self.logger
        cmd = [args.rsync,
                "--archive",
                "--delete",
                "--delay-updates",
                "--chmod=" + args.chmod,
                ]
        cmd.extend(list(self.__stack))
        cmd.append(args.target)
        logger.debug("cmd=%s", cmd)
        if self.args.dryrun: return True
        p = subprocess.run(cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if p.returncode == 0: # Success
            logger.info("Synced %s to %s", self.__stack, args.target)
            return True
        logger.error("Error syncing %s to %s\n%s", self.__stack, args.target, p.stdout)
        return False
        
    def run(self): # Called on start
        args = self.args
        logger = self.logger
        q = self.__queue
        sources = self.__sources
        logger.info("Starting")
        tRef = None
        while True:
            try:
                fn = q.get(timeout=None if tRef is None else max(0.001, tRef - time.time()))
                for item in sources:
                    a = item.search(fn)
                    if a is None: continue
                    if self.__processFile(fn):
                        src = a[0]
                        self.logger.debug("Going to process %s, %s", fn, src)
                        if len(self.__stack) == 0:
                            tRef = time.time() + args.delay
                        self.__stack.add(src[:-1]) # Strip off trailing slash
                    break
                q.task_done()
            except queue.Empty:
                try:
                    self.__timedout()
                except:
                    logger.exception("Unexpected Exception")
                self.__stack = set()
                tRef = None
            except:
                logger.exception("Unexpected Exception")
                break

class Handler(pyinotify.ProcessEvent):
    def __init__(self, sync:Sync, logger:logging.Logger) -> None:
        pyinotify.ProcessEvent.__init__(self)
        self.__sync = sync
        self.__logger = logger

    def process_default(self, event) -> None:
        if not self.__sync.is_alive():
            raise Exception("Sync is not alive for %s", event.pathname)
        self.__sync.put(event.pathname)

parser = argparse.ArgumentParser(description="Various Options")
parser.add_argument("dir", nargs="+", help="Directories to monitor")
parser.add_argument("--NoInitialSync", action="store_true",
                help="Should an initial sync be done?")
Sync.addArgs(parser)
MyLogger.addArgs(parser)
args = parser.parse_args()

logger = MyLogger.mkLogger(args)

sync = Sync(args, logger)
sync.start()

handler = Handler(sync, logger)

wm = pyinotify.WatchManager()
notifier = pyinotify.Notifier(wm, handler)

for name in args.dir:
    if not os.path.isdir(name):
        logger.error("'%s' is not a directory", name)
        notifier.stop()
        sys.exit(1)
    wm.add_watch(name,
            pyinotify.IN_CLOSE_WRITE |
            pyinotify.IN_MOVED_FROM |
            pyinotify.IN_MOVED_TO |
            pyinotify.IN_MOVE_SELF |
            pyinotify.IN_DELETE |
            pyinotify.IN_DELETE_SELF,
            rec=True)

if not args.NoInitialSync:
    for name in args.dir: # Walk through tree to do the initial sync
        for (root, dirs, files) in os.walk(name, topdown="False"):
            for filename in files:
                fn = os.path.join(root, filename)
                sync.put(fn)

notifier.loop()
