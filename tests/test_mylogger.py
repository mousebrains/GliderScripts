#
# Tests for MyLogger module
#

import sys
import os
import logging
from argparse import Namespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import MyLogger


class TestAddArgs:
    """Tests for MyLogger.addArgs function."""

    def test_addargs_creates_argument_group(self):
        """Verify addArgs adds the expected arguments to parser."""
        import argparse
        parser = argparse.ArgumentParser()
        MyLogger.addArgs(parser)

        # Parse with defaults
        args = parser.parse_args([])

        assert hasattr(args, 'logfile')
        assert hasattr(args, 'logBytes')
        assert hasattr(args, 'logCount')
        assert hasattr(args, 'verbose')
        assert hasattr(args, 'mailTo')
        assert hasattr(args, 'mailHost')
        assert hasattr(args, 'mailFrom')
        assert hasattr(args, 'mailSubject')

    def test_addargs_default_values(self):
        """Verify default argument values."""
        import argparse
        parser = argparse.ArgumentParser()
        MyLogger.addArgs(parser)
        args = parser.parse_args([])

        assert args.logfile is None
        assert args.logBytes == 10000000
        assert args.logCount == 3
        assert args.verbose is False
        assert args.mailTo is None
        assert args.mailHost == 'localhost'

    def test_addargs_custom_values(self):
        """Verify custom argument values are parsed correctly."""
        import argparse
        parser = argparse.ArgumentParser()
        MyLogger.addArgs(parser)
        args = parser.parse_args([
            '--logfile', '/var/log/test.log',
            '--logBytes', '5000000',
            '--logCount', '5',
            '--verbose',
            '--mailHost', 'smtp.example.com'
        ])

        assert args.logfile == '/var/log/test.log'
        assert args.logBytes == 5000000
        assert args.logCount == 5
        assert args.verbose is True
        assert args.mailHost == 'smtp.example.com'


class TestMkLogger:
    """Tests for MyLogger.mkLogger function."""

    def test_mklogger_console_output(self):
        """Test logger creation with console output (no logfile)."""
        args = Namespace(
            logfile=None,
            logBytes=10000000,
            logCount=3,
            verbose=False,
            mailTo=None,
            mailHost='localhost',
            mailFrom='test@test.com',
            mailSubject='Test'
        )

        # Clear any existing handlers
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)

        logger = MyLogger.mkLogger(args)

        assert logger is not None
        assert logger.level == logging.INFO
        # Should have at least one handler (StreamHandler)
        assert len(logger.handlers) >= 1

    def test_mklogger_file_output(self, temp_dir):
        """Test logger creation with file output."""
        log_file = os.path.join(temp_dir, 'test.log')
        args = Namespace(
            logfile=log_file,
            logBytes=10000000,
            logCount=3,
            verbose=False,
            mailTo=None,
            mailHost='localhost',
            mailFrom='test@test.com',
            mailSubject='Test'
        )

        # Clear any existing handlers
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)

        logger = MyLogger.mkLogger(args)

        assert logger is not None
        # Should have a RotatingFileHandler
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert 'RotatingFileHandler' in handler_types

    def test_mklogger_verbose_mode(self):
        """Test logger creation in verbose mode."""
        args = Namespace(
            logfile=None,
            logBytes=10000000,
            logCount=3,
            verbose=True,
            mailTo=None,
            mailHost='localhost',
            mailFrom='test@test.com',
            mailSubject='Test'
        )

        # Clear any existing handlers
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)

        logger = MyLogger.mkLogger(args)

        assert logger.level == logging.DEBUG

    def test_mklogger_with_email(self):
        """Test logger creation with email notifications."""
        args = Namespace(
            logfile=None,
            logBytes=10000000,
            logCount=3,
            verbose=False,
            mailTo=['admin@example.com'],
            mailHost='smtp.example.com',
            mailFrom='test@test.com',
            mailSubject='Test Error'
        )

        # Clear any existing handlers
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)

        logger = MyLogger.mkLogger(args)

        # Should have SMTPHandler for errors
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert 'SMTPHandler' in handler_types
