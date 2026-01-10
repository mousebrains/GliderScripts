#! /usr/bin/env python3
#
# Execute rsync in a thread with retry logic
#
# Aug-2020, Pat Welch, pat@mousebrains.com

import threading
import argparse
import logging
import queue
import subprocess
import time
from typing import Optional, Set

class RSync(threading.Thread):
    """Threaded rsync executor with retry logic and graceful shutdown."""

    def __init__(self, args: argparse.Namespace, logger: logging.Logger) -> None:
        threading.Thread.__init__(self, daemon=True)
        self.name = "RSync"
        self.__args = args
        self.__logger = logger
        self.__queue: queue.Queue[Set[str]] = queue.Queue()
        self.__stop_event = threading.Event()

    @staticmethod
    def addArgs(parser:argparse.ArgumentParser) -> None:
        grp = parser.add_argument_group(description="RSync options")
        grp.add_argument("--rsyncCmd", type=str, default="/usr/bin/rsync", metavar="filename",
                help="Full path to rsync command to execute")
        grp.add_argument("--rsyncTarget", type=str, required=True, metavar="foo.com:foobar",
                help="rsync target directory")
        grp.add_argument("--rsyncchmod", type=str, default="Do+rx,Fo+r", metavar="Do+rx",
                help="argument for --chmod on rsync command")
        grp.add_argument("--rsyncOpt", type=str, action="append",
                help="Additional rsync options to use")
        grp.add_argument("--rsyncDryRun", action="store_true",
                help="Should the actual rsync command be run?")
        grp.add_argument("--rsyncExclude", type=str, action="append", metavar="pattern",
                help="arguments to rsync's --exclude option")
        grp.add_argument("--rsyncRetries", type=int, default=3, metavar="count",
                help="Number of retry attempts for failed rsync (default: 3)")

    def put(self, sources: Set[str]) -> None:
        """Queue a set of source paths to sync."""
        self.__queue.put(sources)

    def stop(self) -> None:
        """Signal the thread to stop after completing current work."""
        self.__stop_event.set()

    def __doit(self, sources: Set[str]) -> bool:
        args = self.__args
        logger = self.__logger
        target = args.rsyncTarget
        max_retries = getattr(args, 'rsyncRetries', 3)

        cmd = [args.rsyncCmd,
                "--archive",
                "--delete-delay",
                "--delete-excluded",
                "--delete-missing-args",
                "--delay-updates",
                "--chmod",
                args.rsyncchmod]

        if args.rsyncOpt is not None:
            cmd.extend(args.rsyncOpt)

        if args.rsyncExclude is not None:
            for item in args.rsyncExclude:
                cmd.append("--exclude")
                cmd.append(item)

        cmd.extend(list(sources))
        cmd.append(target)
        logger.info("cmd %s", cmd)

        if args.rsyncDryRun:
            logger.info("Dryrun command %s", cmd)
            return True

        # Retry loop with exponential backoff
        for attempt in range(max_retries):
            try:
                p = subprocess.run(cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if p.returncode == 0: # Success
                    if len(p.stdout):
                        try:
                            logger.info("rsynced %s to %s\n%s", sources, target, str(p.stdout, "UTF-8"))
                        except UnicodeDecodeError:
                            logger.info("rsynced %s to %s\n%s", sources, target, p.stdout)
                    else:
                        logger.info("rsynced %s to %s", sources, target)
                    return True

                # Non-zero return code
                error_msg = p.stdout.decode("UTF-8", errors="replace") if p.stdout else "unknown error"
                if attempt < max_retries - 1:
                    delay = 5 * (attempt + 1)  # 5s, 10s, 15s backoff
                    logger.warning("rsync failed (attempt %d/%d), retrying in %ds: %s",
                                   attempt + 1, max_retries, delay, error_msg)
                    time.sleep(delay)
                else:
                    logger.error("rsync failed after %d attempts: %s to %s\n%s\n%s",
                                 max_retries, sources, target, cmd, error_msg)

            except OSError as e:
                if attempt < max_retries - 1:
                    delay = 5 * (attempt + 1)
                    logger.warning("rsync OS error (attempt %d/%d), retrying in %ds: %s",
                                   attempt + 1, max_retries, delay, e)
                    time.sleep(delay)
                else:
                    logger.error("rsync OS error after %d attempts: %s", max_retries, e)

        return False

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for pending rsync operations to complete, then join thread."""
        if not self.is_alive():
            return
        self.__queue.join()  # Wait for all queued items to be processed
        super().join(timeout)  # Then properly join the thread

    def run(self) -> None:
        """Main loop - process queued sync requests until stopped."""
        logger = self.__logger
        q = self.__queue
        logger.info("Starting")

        while not self.__stop_event.is_set():
            try:
                # Use timeout to periodically check stop_event
                sources = q.get(timeout=1.0)
            except queue.Empty:
                continue

            logger.info("Sources %s", sources)
            try:
                self.__doit(sources)
            except Exception:
                logger.exception("Error executing rsync for %s", sources)
            q.task_done()

        logger.info("Stopping")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    RSync.addArgs(parser)
    parser.add_argument("src", nargs="+", metavar="dir", help="Sources to rsync")
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s %(threadName)s %(levelname)s:%(message)s",
            level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    logger.info("args=%s", args)

    a = RSync(args, logger)
    a.start()
    a.put(set(args.src))

    a.join()  # Let the thread finish all items in the queue
