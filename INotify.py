#! /usr/bin/python3 -Es
#
# This is an interface into the system's inotify mechanism
# using Python's ctype mechanism.
# It is based on INotify_simple as an example.
#
# If the kernel's event queue overflows, an Event with path None and
# Flags.Q_OVERFLOW is queued, since events were lost, so the caller should rescan.
#
# Aug-2020, Pat Welch, pat@mousebrains.com

import threading
import queue
import logging
import time
import os
import os.path
from enum import IntFlag
import ctypes
import ctypes.util
from errno import EINTR, EINVAL, ENOENT, ENOSPC, ENOTDIR
from io import FileIO
from fcntl import ioctl
from termios import FIONREAD
import struct
import select
from typing import Dict, Any, Optional

class Flags(IntFlag):
    ACCESS        = 0x00000001 # File was accessed
    MODIFY        = 0x00000002 # File was modified
    ATTRIB        = 0x00000004 # Metadata was changed
    CLOSE_WRITE   = 0x00000008 # Writtable file was closed
    CLOSE_NOWRITE = 0x00000010 # Unwrittable file closed
    OPEN          = 0x00000020 # File was opened
    MOVED_FROM    = 0x00000040 # File was moved from X
    MOVED_TO      = 0x00000080 # File was moved to Y
    CREATE        = 0x00000100 # Subfile was created
    DELETE        = 0x00000200 # Subfile was deleted
    DELETE_SELF   = 0x00000400 # Self was deleted
    MOVE_SELF     = 0x00000800 # Self was moved

    # the following are legal events.  they are sent as needed to any watch
    UNMOUNT       = 0x00002000 # Backing fs was unmounted
    Q_OVERFLOW    = 0x00004000 # Event queued overflowed
    IGNORED       = 0x00008000 # File was ignored


    # special flags
    ONLYDIR       = 0x01000000 # only watch the path if it is a directory
    DONT_FOLLOW   = 0x02000000 # don't follow a sym link
    EXCL_UNLINK   = 0x04000000 # exclude events on unlinked objects
    MASK_CREATE   = 0x10000000 # only create watches
    MASK_ADD      = 0x20000000 # add to the mask of an already existing watch
    ISDIR         = 0x40000000 # event occurred against dir
    ONESHOT       = 0x80000000 # only send event once

    # helper events
    CLOSE = (CLOSE_WRITE | CLOSE_NOWRITE) # close
    MOVE = (MOVED_FROM | MOVED_TO) # moves
    ALL_EVENTS = (
            ACCESS | MODIFY | ATTRIB | CLOSE_WRITE |
            CLOSE_NOWRITE | OPEN | MOVED_FROM |
            MOVED_TO | DELETE | CREATE | DELETE_SELF |
            MOVE_SELF
            )

class Event:
    def __init__(self, t: float, path: Optional[str], flags: Flags) -> None:
        self.t = t
        self.path = path
        self.flags = flags

    def __repr__(self) -> str:
        return str(self.path) + " " + str(self.flags) + " " + str(self.t)

class INotify(threading.Thread):
    """Thread-safe inotify interface for monitoring filesystem events."""

    def __init__(self, logger: logging.Logger, inheritable: bool = False, nonBlocking: bool = False):
        super().__init__(daemon=True)
        self.name = "INotify"
        self.__logger = logger
        self.__queue: queue.Queue[Event] = queue.Queue()
        self.__lock = threading.RLock()  # Protects watches/paths/recursive/mask dicts
        self.__stop_event = threading.Event()  # For graceful shutdown
        self.__watches: Dict[str, int] = {}
        self.__paths: Dict[int, str] = {}
        self.__recursive: Dict[int, bool] = {}
        self.__mask: Dict[int, Flags] = {}
        self.__fp: Optional[FileIO] = None

        try:
            libfn = ctypes.util.find_library("c")
            if libfn is None:
                raise OSError("Unable to find the libc library")
            self.__libc = ctypes.CDLL(libfn, use_errno=True)  # use_errno so get_errno works
            flags = ((not inheritable) * os.O_CLOEXEC) | (nonBlocking * os.O_NONBLOCK)
            self.__fp = FileIO(int(self.__callLibC("inotify_init1", flags)), mode='rb')
        except Exception:
            logger.exception("Unable to initialize inotify")
            raise  # Re-raise to prevent using invalid object

    def __callLibC(self, name: str, *args: Any) -> int:
        """Call a libc function, retrying on EINTR. Raises OSError on failure."""
        function = self.__libc[name] # Function pointer into libc
        while True:
            rc = function(*args)
            if rc != -1:
                return rc
            errno = ctypes.get_errno()
            if errno != EINTR:
                raise OSError(errno, os.strerror(errno))

    def get(self, timeout=None) -> Event:
        return self.__queue.get(timeout=timeout)

    def task_done(self) -> None:
        """Mark the last retrieved event as processed."""
        self.__queue.task_done()

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to finish."""
        self.__stop_event.set()
        if self.is_alive():
            self.join(timeout=5.0)

    def __addWatch(self, path: str, recursive: bool, mask: Flags) -> None:
        """Add a watch for a path (thread-safe)."""
        with self.__lock:
            if path in self.__watches:
                return
            if self.__fp is None:
                return
            try:
                wd = self.__callLibC("inotify_add_watch", self.__fp.fileno(), os.fsencode(path), mask)
            except OSError as e:
                if e.errno in (ENOENT, ENOTDIR):  # Removed before we got to it
                    self.__logger.debug("%s vanished before a watch was added", path)
                elif e.errno == ENOSPC:
                    self.__logger.error("Watch limit reached adding %s, %s, %s", path,
                            "increase fs.inotify.max_user_watches",
                            "until then, updates will be missed")
                else:
                    self.__logger.exception("Error adding a watch for %s", path)
                return
            if wd in self.__paths:  # Same inode via another path, so drop the old path
                self.__watches.pop(self.__paths[wd], None)
            self.__watches[path] = wd
            self.__paths[wd] = path
            self.__recursive[wd] = recursive and os.path.isdir(path)
            self.__mask[wd] = mask

    def __forget(self, wd: int) -> None:
        """Drop our records of a watch, without telling the kernel (thread-safe)."""
        with self.__lock:
            path = self.__paths.pop(wd, None)
            if path is not None and self.__watches.get(path) == wd:
                del self.__watches[path]
            self.__recursive.pop(wd, None)
            self.__mask.pop(wd, None)

    def __rmWatch(self, path: str) -> bool:
        """Remove a watch for a path (thread-safe). Returns True if was recursive."""
        with self.__lock:
            if path not in self.__watches:
                return False
            wd = self.__watches[path]
            recursive = self.__recursive[wd]
            del self.__watches[path]
            del self.__paths[wd]
            del self.__recursive[wd]
            del self.__mask[wd]
            try:
                if self.__fp is not None:
                    self.__callLibC("inotify_rm_watch", self.__fp.fileno(), wd)
            except OSError as e:
                if e.errno != EINVAL:  # EINVAL if the kernel already removed the watch
                    self.__logger.exception("Error removing a watch for %s", path)
            return recursive


    def add(self, path: str, recursive: bool = True, mask: Flags = Flags.ALL_EVENTS) -> None:
        """Add a watch for the given path, optionally recursing into subdirectories."""
        self.__addWatch(path, recursive, mask)
        if (not recursive) or (not os.path.isdir(path)):
            return
        # Don't follow symbolic links below the top level directory
        subMask = mask | Flags.DONT_FOLLOW | Flags.ONLYDIR
        for (root, dirs, files) in os.walk(path, followlinks=False):
            for item in dirs:
                self.__addWatch(os.path.join(root, item), recursive, subMask)

    def rm(self, path: str) -> None:
        """Remove watch for the given path and any child watches."""
        if not self.__rmWatch(path):
            return
        # Collect paths to remove (can't modify dict during iteration)
        with self.__lock:
            toRemove = [key for key in self.__watches if key.startswith(path + os.sep)]
        for key in toRemove:
            self.__rmWatch(key)

    def run(self) -> None:
        """Main event loop - monitors inotify fd and processes events."""
        logger = self.__logger
        logger.info("Starting")
        buffer = bytearray()
        fp = self.__fp

        if fp is None:
            logger.error("Cannot start - inotify not initialized")
            return

        try:
            while not self.__stop_event.is_set():
                # Use timeout to periodically check stop_event
                (rd, _, _) = select.select((fp,), (), (), 1.0)
                if not rd:
                    continue  # Timeout, check stop_event
                nAvail = ctypes.c_int()
                ioctl(fp, FIONREAD, nAvail)
                if nAvail.value <= 0:
                    continue
                buffer = self.__procBuffer(buffer + (fp.read(nAvail.value) or b""))
        except Exception:
            logger.exception("Unexpected exception")
            raise

        logger.info("Stopping")

    def __procBuffer(self, buffer: bytearray) -> bytearray:
        """Process buffered inotify events (thread-safe dict access)."""
        hdrFormat = "iIII"
        hdrSize = struct.calcsize(hdrFormat)
        t = time.time()

        while len(buffer) >= hdrSize:
            (wd, mask, cookie, n) = struct.unpack_from(hdrFormat, buffer[0:hdrSize])

            # Queue overflow, events were lost, so tell the caller to rescan
            if mask & Flags.Q_OVERFLOW:
                self.__logger.warning("inotify event queue overflow - some events were lost")
                self.__queue.put(Event(t, None, Flags(mask)))
                buffer = buffer[(hdrSize + n):]
                continue

            # Thread-safe access to lookup dicts
            with self.__lock:
                if wd not in self.__paths:
                    buffer = buffer[(hdrSize + n):]
                    continue
                path = self.__paths[wd]
                is_recursive = self.__recursive.get(wd, False)
                watch_mask = self.__mask.get(wd, Flags.ALL_EVENTS)

            if mask & Flags.IGNORED:  # Kernel removed this watch, e.g. directory deleted
                self.__forget(wd)
                buffer = buffer[(hdrSize + n):]
                continue

            if n > 0:
                name_bytes = bytes(buffer[hdrSize:(hdrSize + n)]).split(b'\x00', 1)[0]
                path = os.path.join(path, os.fsdecode(name_bytes))  # fsdecode handles non-UTF-8 names

            evt = Event(t, path, Flags(mask))
            self.__queue.put(evt)

            # Handle directory creation/deletion for recursive watches
            if Flags.ISDIR in evt.flags:
                if (Flags.CREATE in evt.flags) or (Flags.MOVED_TO in evt.flags):
                    if is_recursive:
                        self.__addNewDir(t, path, watch_mask)
                elif (Flags.DELETE in evt.flags) or \
                        (Flags.DELETE_SELF in evt.flags) or \
                        (Flags.MOVED_FROM in evt.flags):
                    self.rm(path)

            buffer = buffer[(hdrSize + n):]

        return buffer

    def __addNewDir(self, t: float, path: str, mask: Flags) -> None:
        """Watch a new directory, then queue events for anything which showed up
        before the watches were in place, so they are not missed."""
        self.add(path, True, mask)
        for (root, dirs, files) in os.walk(path, followlinks=False):
            for item in dirs:
                self.__queue.put(Event(t, os.path.join(root, item), Flags.CREATE | Flags.ISDIR))
            for item in files:
                self.__queue.put(Event(t, os.path.join(root, item), Flags.CREATE))

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test a simple iNotify interface")
    parser.add_argument("dir", nargs="+", metavar="directory", help="Directories to monitor")
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s %(threadName)s %(levelname)s:%(message)s",
            level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.info("args=%s", args)

    a = INotify(logger)
    a.start()

    mask = Flags( \
            Flags.CLOSE_WRITE |
            Flags.MOVED_TO |
            Flags.MOVED_FROM |
            Flags.DELETE |
            Flags.DELETE_SELF |
            Flags.CREATE) # For directory recursion

    for path in args.dir:
        a.add(path, recursive=True, mask=mask)

    while a.is_alive():
        evt = a.get()
        logger.info("%s", evt)
        a.task_done()
