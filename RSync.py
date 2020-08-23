#! /usr/bin/env python3
#
# Execute rsync in a thread
#
# Aug-2020, Pat Welch, pat@mousebrains.com

import threading
import argparse
import logging
import queue
import subprocess

class RSync(threading.Thread):
    def __init__(self, args:argparse.ArgumentParser, logger:logging.Logger) -> None:
        threading.Thread.__init__(self, daemon=True)
        self.name = "RSync"
        self.__args = args
        self.__logger = logger
        self.__queue = queue.Queue() # Incoming actions to do

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

    def put(self, sources:tuple) -> None:
        self.__queue.put(sources)

    def __doit(self, sources:tuple) -> bool:
        args = self.__args
        logger = self.__logger
        target = args.rsyncTarget
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
        p = subprocess.run(cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if p.returncode == 0: # Success
            if len(p.stdout):
                try:
                    logger.info("rsynced %s to %s\n%s", sources, target, str(p.stdout, "UTF-8"))
                except:
                    logger.info("rsynced %s to %s\n%s", sources, target, p.stdout)
            else:
                logger.info("rsynced %s to %s", sources, target)
            return True
        logger.error("Error rsyncing %s to %s\n%s\n%s", sources, target, cmd, p.stdout)
        return False

    def join(self) -> None:
        """ Override threading join to wait for queue to be finished """
        if not self.is_alive(): return 
        self.__queue.join()

    def run(self) -> None:
        logger = self.__logger
        queue = self.__queue
        logger.info("Starting")
        while True:
            sources = queue.get()
            logger.info("Sources %s", sources)
            try:
                self.__doit(sources)
            except:
                logger.exception("Error executing rsync for %s", sources)
            queue.task_done()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    RSync.addArgs(parser)
    parser.add_argument("src", nargs="+", metavar="dir", help="Sources to rsync")
    args = parser.parse_args()

    logger = logging
    logger.basicConfig(format="%(asctime)s %(threadName)s %(levelname)s:%(message)s",
            level=logging.DEBUG)
    logger.info("args=%s", args)

    a = RSync(args, logger)
    a.start()
    a.put(args.src)

    a.join() # Let the thread finish al items in the queue
