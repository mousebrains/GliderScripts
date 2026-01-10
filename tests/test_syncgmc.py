#
# Tests for syncGMC module
#

import sys
import os
from argparse import Namespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the functions we need to test
import syncGMC


class TestCompilePatterns:
    """Tests for _compile_patterns function."""

    def test_compile_patterns_caches_trigger(self):
        """Test that patterns are compiled and cached."""
        # Reset global patterns
        syncGMC._trigger_pattern = None
        syncGMC._exclude_pattern = None

        args = Namespace(
            trigger=['/from-glider', '/to-glider'],
            exclude=None
        )

        syncGMC._compile_patterns(args)

        assert syncGMC._trigger_pattern is not None
        assert syncGMC._exclude_pattern is None

    def test_compile_patterns_caches_exclude(self):
        """Test that exclude patterns are compiled when provided."""
        # Reset global patterns
        syncGMC._trigger_pattern = None
        syncGMC._exclude_pattern = None

        args = Namespace(
            trigger=['/from-glider'],
            exclude=['.archived-deployments']
        )

        syncGMC._compile_patterns(args)

        assert syncGMC._trigger_pattern is not None
        assert syncGMC._exclude_pattern is not None

    def test_compile_patterns_reuses_cached(self):
        """Test that patterns are reused after first compilation."""
        # Reset global patterns
        syncGMC._trigger_pattern = None
        syncGMC._exclude_pattern = None

        args = Namespace(
            trigger=['/from-glider'],
            exclude=None
        )

        syncGMC._compile_patterns(args)
        first_pattern = syncGMC._trigger_pattern

        # Call again - should reuse
        syncGMC._compile_patterns(args)

        assert syncGMC._trigger_pattern is first_pattern


class TestMkPath:
    """Tests for mkPath function."""

    def setup_method(self):
        """Reset cached patterns before each test."""
        syncGMC._trigger_pattern = None
        syncGMC._exclude_pattern = None

    def test_mkpath_matches_trigger(self):
        """Test mkPath returns correct path for matching trigger."""
        args = Namespace(
            trigger=['/from-glider', '/to-glider'],
            exclude=None
        )

        path = "/var/opt/sfmc-dockserver/stations/project/glider/from-glider/data.txt"
        result = syncGMC.mkPath(path, args)

        assert result == "/var/opt/sfmc-dockserver/stations/project/glider"

    def test_mkpath_no_match(self):
        """Test mkPath returns None for non-matching path."""
        args = Namespace(
            trigger=['/from-glider', '/to-glider'],
            exclude=None
        )

        path = "/var/opt/sfmc-dockserver/stations/project/glider/logs/test.log"
        result = syncGMC.mkPath(path, args)

        assert result is None

    def test_mkpath_excludes_pattern(self):
        """Test mkPath returns None for excluded paths."""
        args = Namespace(
            trigger=['/from-glider', '/to-glider'],
            exclude=['.archived-deployments']
        )

        path = "/var/opt/sfmc-dockserver/stations/.archived-deployments/project/from-glider/data.txt"
        result = syncGMC.mkPath(path, args)

        assert result is None

    def test_mkpath_multiple_triggers(self):
        """Test mkPath works with multiple trigger patterns."""
        args = Namespace(
            trigger=['/archive', '/configuration', '/from-glider', '/to-glider'],
            exclude=None
        )

        # Test different triggers
        paths = [
            "/data/stations/proj/glider/archive/file.txt",
            "/data/stations/proj/glider/configuration/config.xml",
            "/data/stations/proj/glider/from-glider/data.dbd",
        ]

        for path in paths:
            result = syncGMC.mkPath(path, args)
            assert result is not None
            assert "/glider" in result or result.endswith("glider")


class TestInitialSync:
    """Tests for initialSync function."""

    def setup_method(self):
        """Reset cached patterns before each test."""
        syncGMC._trigger_pattern = None
        syncGMC._exclude_pattern = None

    def test_initial_sync_finds_matching_dirs(self, temp_dir):
        """Test initialSync finds directories matching trigger patterns."""
        # Create directory structure
        from_glider = os.path.join(temp_dir, "project", "glider", "from-glider")
        to_glider = os.path.join(temp_dir, "project", "glider", "to-glider")
        logs = os.path.join(temp_dir, "project", "glider", "logs")

        os.makedirs(from_glider)
        os.makedirs(to_glider)
        os.makedirs(logs)

        # Create some files
        open(os.path.join(from_glider, "data.txt"), 'w').close()
        open(os.path.join(to_glider, "cmd.txt"), 'w').close()
        open(os.path.join(logs, "log.txt"), 'w').close()

        args = Namespace(
            dir=[temp_dir],
            trigger=['/from-glider', '/to-glider'],
            exclude=None
        )

        # Mock RSync
        from unittest.mock import Mock
        mock_rsync = Mock()
        captured_paths = []

        def capture_put(paths):
            captured_paths.extend(paths)

        mock_rsync.put = capture_put

        syncGMC.initialSync(args, mock_rsync)

        # Should have found the matching directories
        assert len(captured_paths) > 0
        # The parent directory of from-glider should be captured
        glider_dir = os.path.join(temp_dir, "project", "glider")
        assert glider_dir in captured_paths

    def test_initial_sync_respects_exclude(self, temp_dir):
        """Test initialSync excludes matching patterns."""
        # Create directory structure with archived
        archived = os.path.join(temp_dir, ".archived-deployments", "glider", "from-glider")
        active = os.path.join(temp_dir, "active", "glider", "from-glider")

        os.makedirs(archived)
        os.makedirs(active)

        args = Namespace(
            dir=[temp_dir],
            trigger=['/from-glider'],
            exclude=['.archived-deployments']
        )

        from unittest.mock import Mock
        mock_rsync = Mock()
        captured_paths = []

        def capture_put(paths):
            captured_paths.extend(paths)

        mock_rsync.put = capture_put

        syncGMC.initialSync(args, mock_rsync)

        # Should not include archived paths
        for path in captured_paths:
            assert '.archived-deployments' not in path

    def test_initial_sync_empty_directory(self, temp_dir):
        """Test initialSync handles empty directories."""
        args = Namespace(
            dir=[temp_dir],
            trigger=['/from-glider'],
            exclude=None
        )

        from unittest.mock import Mock
        mock_rsync = Mock()

        # Should not raise an exception
        syncGMC.initialSync(args, mock_rsync)

        # put should not be called if no matches
        mock_rsync.put.assert_not_called()


class TestSignalHandler:
    """Tests for signal handling."""

    def test_signal_handler_globals_exist(self):
        """Test that signal handler global variables exist."""
        # These are set during main execution
        assert hasattr(syncGMC, '_rsync')
        assert hasattr(syncGMC, '_logger')

    def test_signal_handler_function_exists(self):
        """Test that signal_handler function is defined."""
        assert callable(syncGMC.signal_handler)
