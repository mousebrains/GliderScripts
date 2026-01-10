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
import sys
import time
import queue
import logging
import re
import signal
from typing import Optional, Set
import MyLogger
import INotify
from RSync import RSync

# Cached compiled regex patterns
_trigger_pattern: Optional[re.Pattern] = None
_exclude_pattern: Optional[re.Pattern] = None

def _compile_patterns(args: argparse.Namespace) -> None:
    """Compile and cache regex patterns from args."""
    global _trigger_pattern, _exclude_pattern
    if _trigger_pattern is None:
        _trigger_pattern = re.compile("(.*)(" + "|".join(args.trigger) + ")")
    if _exclude_pattern is None and args.exclude is not None:
        _exclude_pattern = re.compile("(" + "|".join(args.exclude) + ")")

def mkPath(path: str, args: argparse.Namespace) -> Optional[str]:
    """Extract the sync path from a file path if it matches trigger patterns."""
    _compile_patterns(args)

    if _trigger_pattern is None:
        return None

    a = _trigger_pattern.search(path)
    if a is None:
        return None

    if _exclude_pattern is not None:
        if _exclude_pattern.search(path) is not None:
            return None
    return a[1]

def doit(args: argparse.Namespace,
        logger: logging.Logger,
        inotify: INotify.INotify,
        rsync: RSync) -> None:
    """Main event loop: monitor inotify events and trigger rsync."""
    timeout: Optional[float] = None
    paths: Set[str] = set()

    while inotify.is_alive():
        try:
            dt: Optional[float] = None if timeout is None else max(0.001, (timeout - time.time()))
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

def initialSync(args: argparse.Namespace, rsync: RSync) -> None:
    """Perform initial sync of all matching directories."""
    paths: Set[str] = set()
    _compile_patterns(args)

    for path in args.dir:
        for (root, dirs, files) in os.walk(path):
            for name in dirs:
                a = mkPath(os.path.join(root, name), args)
                if a is not None:
                    paths.add(a)
            for name in files:
                a = mkPath(os.path.join(root, name), args)
                if a is not None:
                    paths.add(a)
    if len(paths):
        rsync.put(paths)


# Global references for signal handler
_rsync: Optional[RSync] = None
_inotify: Optional[INotify.INotify] = None
_logger: Optional[logging.Logger] = None

def signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals gracefully."""
    sig_name = signal.Signals(signum).name
    if _logger:
        _logger.info("Received %s, shutting down gracefully...", sig_name)
    if _inotify:
        _inotify.stop()  # Stop monitoring
    if _rsync:
        _rsync.stop()  # Signal rsync to stop
        _rsync.join()  # Wait for pending rsync operations
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor directories and sync changes via rsync")
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
    _logger = logger  # Store for signal handler

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    rsync = RSync(args, logger)
    _rsync = rsync  # Store for signal handler
    rsync.start()

    inotify = INotify.INotify(logger)
    _inotify = inotify  # Store for signal handler
    inotify.start()

    mask = INotify.Flags(
                INotify.Flags.CLOSE_WRITE |
                INotify.Flags.MOVED_TO |
                INotify.Flags.MOVED_FROM |
                INotify.Flags.MOVE_SELF |
                INotify.Flags.DELETE |
                INotify.Flags.DELETE_SELF |
                INotify.Flags.CREATE)  # For directory recursion

    for path in args.dir:
        inotify.add(path, recursive=True, mask=mask)

    if not args.noInitial:
        initialSync(args, rsync)

    try:
        doit(args, logger, inotify, rsync)
    except Exception:
        logger.exception("Unexpected exception, waiting for rsync to finish before exiting")

    # Graceful shutdown
    inotify.stop()
    rsync.stop()
    rsync.join()  # Wait for rsync tasks to complete
