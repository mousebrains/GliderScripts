#
# Construct a logger object
#
# Feb-2020, Pat Welch, pat@mousebrains.com

import argparse
import logging
import logging.handlers
import socket
import getpass

def addArgs(parser:argparse.ArgumentParser) -> None:
    grp = parser.add_argument_group('Logger Related Options')
    grp.add_argument('--logfile', type=str, metavar='filename', help='Name of logfile')
    grp.add_argument('--logBytes', type=int, default=10000000, metavar='length',
            help='Maximum logfile size in bytes')
    grp.add_argument('--logCount', type=int, default=3, metavar='count',
            help='Number of backup files to keep')
    grp.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    grp.add_argument('--mailTo', help='Who to mail errors to', action='append')
    grp.add_argument('--mailHost', help='SMTP hostname', default='localhost')
    grp.add_argument('--mailFrom', help='Who mail is coming from',
            default=getpass.getuser() + '@' + socket.gethostname())
    grp.add_argument('--mailSubject', help='Subject of mail',
            default="ERROR: " + socket.gethostname())

def mkLogger(args:argparse.ArgumentParser) -> logging.Logger:
    logger = logging.getLogger()
    if args.logfile:
        ch = logging.handlers.RotatingFileHandler(args.logfile,
                maxBytes=args.logBytes,
                backupCount=args.logCount)
    else:
        ch = logging.StreamHandler()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        ch.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
        ch.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s %(threadName)s %(levelname)s: %(message)s')
    ch.setFormatter(formatter)

    logger.addHandler(ch)

    if args.mailTo:
        ch = logging.handlers.SMTPHandler(args.mailHost, args.mailFrom, args.mailTo, 
                args.mailSubject)
        ch.setLevel(logging.ERROR)
        ch.setFormatter(logging.Formatter('%(threadName)s:%(levelname)s - %(message)s'))
        logger.addHandler(ch)

    return logger
