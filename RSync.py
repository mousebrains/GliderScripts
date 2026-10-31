#! /usr/bin/python3 -Es
#
# Execute rsync in a thread with retry logic
#
# Each sync is tried --rsyncRetries times with a short backoff. If it still fails,
# the sources are kept and retried every --rsyncRetryDelay seconds, merged with any
# new sources, until they succeed. Only the first failure in a row is logged as an
# error, so a long outage sends one mail rather than one per retry.
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
        grp.add_argument("--rsyncRetryDelay", type=float, default=60, metavar="seconds",
                help="After all retries fail, how long before trying again (default: 60)")
        grp.add_argument("--rsyncTimeout", type=int, default=600, metavar="seconds",
                help="rsync I/O timeout, so a hung connection does not block syncing forever")
        grp.add_argument("--rsyncSSH", type=str, metavar="command",
                default="ssh -o BatchMode=yes -o ServerAliveInterval=60 -o ServerAliveCountMax=3",
                help="Remote shell for rsync to use, BatchMode so it never prompts for a password")

    def put(self, sources: Set[str]) -> None:
        """Queue a set of source paths to sync."""
        self.__queue.put(sources)

    def stop(self) -> None:
        """Signal the thread to stop after completing current work."""
        self.__stop_event.set()

    def __doit(self, sources: Set[str], nFailures: int = 0) -> bool:
        args = self.__args
        logger = self.__logger
        target = args.rsyncTarget
        max_retries = getattr(args, 'rsyncRetries', 3)
        sortedSources = sorted(sources)

        cmd = [args.rsyncCmd,
                "--archive",
                "--delete-delay",
                "--delete-excluded",
                "--delete-missing-args",
                "--delay-updates",
                "--timeout", str(getattr(args, 'rsyncTimeout', 600)),
                "--rsh", getattr(args, 'rsyncSSH', "ssh -o BatchMode=yes"),
                "--chmod",
                args.rsyncchmod]

        if args.rsyncOpt is not None:
            cmd.extend(args.rsyncOpt)

        if args.rsyncExclude is not None:
            for item in args.rsyncExclude:
                cmd.append("--exclude")
                cmd.append(item)

        cmd.append("--")  # Nothing after this is an option, even if it starts with -
        cmd.extend(sortedSources)
        cmd.append(target)
        logger.debug("cmd %s", cmd)

        if args.rsyncDryRun:
            logger.info("Dryrun command %s", cmd)
            return True

        # Retry loop with exponential backoff
        for attempt in range(max_retries):
            try:
                p = subprocess.run(cmd, shell=False, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if p.returncode == 0: # Success
                    if nFailures:
                        logger.info("rsync recovered after %d failed round(s)", nFailures)
                    if len(p.stdout):
                        logger.info("rsynced %s to %s\n%s", sortedSources, target,
                                p.stdout.decode("UTF-8", errors="replace"))
                    else:
                        logger.info("rsynced %s to %s", sortedSources, target)
                    return True

                # Non-zero return code
                error_msg = p.stdout.decode("UTF-8", errors="replace") if p.stdout else "unknown error"
                if attempt < max_retries - 1:
                    delay = 5 * (attempt + 1)  # 5s, 10s, 15s backoff
                    logger.warning("rsync failed (attempt %d/%d), retrying in %ds: %s",
                                   attempt + 1, max_retries, delay, error_msg)
                    time.sleep(delay)
                else:
                    # Only the first failed round in a row is an error, so we don't mail every round
                    (logger.error if nFailures == 0 else logger.warning)(
                               "rsync failed after %d attempts, will retry in %ss: %s to %s\n%s\n%s",
                               max_retries, getattr(args, 'rsyncRetryDelay', 60),
                               sortedSources, target, cmd, error_msg)

            except OSError as e:
                if attempt < max_retries - 1:
                    delay = 5 * (attempt + 1)
                    logger.warning("rsync OS error (attempt %d/%d), retrying in %ds: %s",
                                   attempt + 1, max_retries, delay, e)
                    time.sleep(delay)
                else:
                    (logger.error if nFailures == 0 else logger.warning)(
                               "rsync OS error after %d attempts: %s", max_retries, e)

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

        pending: Set[str] = set()  # Sources which still need to be synced
        nFailures = 0  # Failed rounds in a row
        nextRetry = 0.0  # When to retry pending sources if nothing new shows up
        retryDelay = getattr(self.__args, 'rsyncRetryDelay', 60)

        while not self.__stop_event.is_set():
            n = 0  # Queue items taken this round
            try:
                # Use timeout to periodically check stop_event
                pending.update(q.get(timeout=1.0))
                n += 1
                while True:  # Merge in anything else which is waiting
                    pending.update(q.get_nowait())
                    n += 1
            except queue.Empty:
                pass

            if pending and (n or time.time() >= nextRetry):
                logger.info("Sources %s", sorted(pending))
                try:
                    qOkay = self.__doit(pending, nFailures)
                except Exception:
                    logger.exception("Error executing rsync for %s", sorted(pending))
                    qOkay = False
                if qOkay:
                    pending = set()
                    nFailures = 0
                else:
                    nFailures += 1
                    nextRetry = time.time() + retryDelay

            for _ in range(n):  # After the attempt, so join waits for it
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
