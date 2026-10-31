#
# Tests for RSync module
#

import sys
import os
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from RSync import RSync


class TestRSyncAddArgs:
    """Tests for RSync.addArgs static method."""

    def test_addargs_creates_arguments(self):
        """Verify addArgs adds the expected arguments to parser."""
        import argparse
        parser = argparse.ArgumentParser()
        RSync.addArgs(parser)

        # Parse with required args
        args = parser.parse_args(['--rsyncTarget', 'host:/path'])

        assert hasattr(args, 'rsyncCmd')
        assert hasattr(args, 'rsyncTarget')
        assert hasattr(args, 'rsyncchmod')
        assert hasattr(args, 'rsyncOpt')
        assert hasattr(args, 'rsyncDryRun')
        assert hasattr(args, 'rsyncExclude')
        assert hasattr(args, 'rsyncRetries')

    def test_addargs_default_values(self):
        """Verify default argument values."""
        import argparse
        parser = argparse.ArgumentParser()
        RSync.addArgs(parser)
        args = parser.parse_args(['--rsyncTarget', 'host:/path'])

        assert args.rsyncCmd == '/usr/bin/rsync'
        assert args.rsyncchmod == 'Do+rx,Fo+r'
        assert args.rsyncOpt is None
        assert args.rsyncDryRun is False
        assert args.rsyncExclude is None
        assert args.rsyncRetries == 3

    def test_addargs_custom_values(self):
        """Verify custom argument values are parsed correctly."""
        import argparse
        parser = argparse.ArgumentParser()
        RSync.addArgs(parser)
        args = parser.parse_args([
            '--rsyncTarget', 'backup:/data',
            '--rsyncCmd', '/opt/bin/rsync',
            '--rsyncRetries', '5',
            '--rsyncDryRun',
            '--rsyncExclude', '*.tmp',
            '--rsyncExclude', '*.log'
        ])

        assert args.rsyncTarget == 'backup:/data'
        assert args.rsyncCmd == '/opt/bin/rsync'
        assert args.rsyncRetries == 5
        assert args.rsyncDryRun is True
        assert args.rsyncExclude == ['*.tmp', '*.log']


class TestRSyncClass:
    """Tests for RSync class."""

    def test_rsync_creation(self, mock_logger, rsync_args):
        """Test RSync object creation."""
        rsync = RSync(rsync_args, mock_logger)

        assert rsync is not None
        assert rsync.name == "RSync"

    def test_rsync_put_items(self, mock_logger, rsync_args):
        """Test putting items in the queue."""
        rsync = RSync(rsync_args, mock_logger)

        # Should not raise an exception
        rsync.put({'/path/to/source'})

    def test_rsync_dryrun_mode(self, mock_logger, rsync_args):
        """Test dry run mode doesn't execute rsync."""
        rsync_args.rsyncDryRun = True
        rsync = RSync(rsync_args, mock_logger)
        rsync.start()

        rsync.put({'/test/path'})
        rsync.stop()
        rsync.join()

        # In dry run, should log but not execute
        mock_logger.info.assert_called()

    @patch('subprocess.run')
    def test_rsync_successful_sync(self, mock_run, mock_logger, rsync_args):
        """Test successful rsync execution."""
        # Mock successful subprocess
        mock_process = Mock()
        mock_process.returncode = 0
        mock_process.stdout = b"sending incremental file list\n"
        mock_run.return_value = mock_process

        rsync = RSync(rsync_args, mock_logger)
        rsync.start()

        rsync.put({'/test/source'})
        rsync.stop()
        rsync.join()

        # Should have called subprocess.run
        assert mock_run.called

    @patch('subprocess.run')
    def test_rsync_builds_correct_command(self, mock_run, mock_logger, rsync_args):
        """Test rsync builds the command correctly."""
        mock_process = Mock()
        mock_process.returncode = 0
        mock_process.stdout = b""
        mock_run.return_value = mock_process

        rsync = RSync(rsync_args, mock_logger)
        rsync.start()

        rsync.put({'/test/source'})
        rsync.stop()
        rsync.join()

        # Check the command that was passed
        call_args = mock_run.call_args
        cmd = call_args[0][0]

        assert rsync_args.rsyncCmd in cmd
        assert '--archive' in cmd
        assert '--chmod' in cmd
        assert rsync_args.rsyncchmod in cmd
        assert '/test/source' in cmd
        assert rsync_args.rsyncTarget in cmd

    @patch('subprocess.run')
    def test_rsync_includes_exclude_patterns(self, mock_run, mock_logger, rsync_args):
        """Test rsync includes exclude patterns in command."""
        rsync_args.rsyncExclude = ['*.tmp', '*.log']

        mock_process = Mock()
        mock_process.returncode = 0
        mock_process.stdout = b""
        mock_run.return_value = mock_process

        rsync = RSync(rsync_args, mock_logger)
        rsync.start()

        rsync.put({'/test/source'})
        rsync.stop()
        rsync.join()

        cmd = mock_run.call_args[0][0]

        assert '--exclude' in cmd
        assert '*.tmp' in cmd
        assert '*.log' in cmd

    @patch('subprocess.run')
    @patch('time.sleep')
    def test_rsync_retry_on_failure(self, mock_sleep, mock_run, mock_logger, rsync_args):
        """Test rsync retries on failure."""
        # First two calls fail, third succeeds
        mock_process_fail = Mock()
        mock_process_fail.returncode = 1
        mock_process_fail.stdout = b"connection refused"

        mock_process_success = Mock()
        mock_process_success.returncode = 0
        mock_process_success.stdout = b""

        mock_run.side_effect = [mock_process_fail, mock_process_fail, mock_process_success]

        rsync = RSync(rsync_args, mock_logger)
        rsync.start()

        rsync.put({'/test/source'})
        rsync.stop()
        rsync.join()

        # Should have been called 3 times
        assert mock_run.call_count == 3
        # Should have logged warnings for retries
        assert mock_logger.warning.called

    @patch('subprocess.run')
    @patch('time.sleep')
    def test_rsync_max_retries_exceeded(self, mock_sleep, mock_run, mock_logger, rsync_args):
        """Test rsync logs error after max retries."""
        rsync_args.rsyncRetries = 2

        mock_process = Mock()
        mock_process.returncode = 1
        mock_process.stdout = b"connection refused"
        mock_run.return_value = mock_process

        rsync = RSync(rsync_args, mock_logger)
        rsync.start()

        rsync.put({'/test/source'})
        rsync.stop()
        rsync.join()

        # Should have been called rsyncRetries times
        assert mock_run.call_count == 2
        # Should have logged an error
        mock_logger.error.assert_called()

    @patch('subprocess.run')
    def test_rsync_handles_os_error(self, mock_run, mock_logger, rsync_args):
        """Test rsync handles OSError gracefully."""
        mock_run.side_effect = OSError("No such file or directory")

        rsync = RSync(rsync_args, mock_logger)
        rsync.start()

        rsync.put({'/test/source'})
        rsync.stop()
        rsync.join()

        # Should log warning/error but not crash
        assert mock_logger.warning.called or mock_logger.error.called

    def test_rsync_join_without_start(self, mock_logger, rsync_args):
        """Test join() when thread hasn't started."""
        rsync = RSync(rsync_args, mock_logger)

        # Should not raise an exception
        rsync.join()

    def test_rsync_stop_method(self, mock_logger, rsync_args):
        """Test stop() method signals thread to exit."""
        rsync = RSync(rsync_args, mock_logger)
        rsync.start()

        # Should be alive after start
        assert rsync.is_alive()

        # Stop and wait
        rsync.stop()
        rsync.join(timeout=3.0)

        # Should have exited
        assert not rsync.is_alive()


class TestRSyncHardening:
    """Tests for command hardening and retrying failed syncs."""

    @patch('subprocess.run')
    def test_command_options(self, mock_run, mock_logger, rsync_args):
        """Test timeout, non-interactive ssh, and -- before the sources."""
        mock_run.return_value = Mock(returncode=0, stdout=b"")
        rsync = RSync(rsync_args, mock_logger)
        rsync.start()
        rsync.put({'/test/b', '/test/a'})
        rsync.stop()
        rsync.join()

        cmd = mock_run.call_args[0][0]
        assert '--timeout' in cmd
        rsh = cmd[cmd.index('--rsh') + 1]
        assert 'BatchMode=yes' in rsh
        # Sources are sorted and follow --, then the target is last
        assert cmd[-4:] == ['--', '/test/a', '/test/b', rsync_args.rsyncTarget]
        assert mock_run.call_args[1]['stdin'] is not None

    @patch('subprocess.run')
    @patch('time.sleep')
    def test_failed_sources_are_retried(self, mock_sleep, mock_run, mock_logger, rsync_args):
        """Test sources which fail every attempt are retried later, with one error logged."""
        import threading
        rsync_args.rsyncRetries = 1
        rsync_args.rsyncRetryDelay = 0
        fail = Mock(returncode=255, stdout=b"ssh: connection refused")
        success = Mock(returncode=0, stdout=b"")
        mock_run.side_effect = [fail, fail, success]

        rsync = RSync(rsync_args, mock_logger)
        rsync.start()
        rsync.put({'/test/source'})
        for _ in range(50):  # Retries happen in the background, time.sleep is patched
            if mock_run.call_count >= 3:
                break
            threading.Event().wait(0.1)
        rsync.stop()
        rsync.join(timeout=3.0)

        assert mock_run.call_count == 3
        for call in mock_run.call_args_list:
            assert '/test/source' in call[0][0]
        assert mock_logger.error.call_count == 1  # Only the first failure mails
        assert mock_logger.warning.called
