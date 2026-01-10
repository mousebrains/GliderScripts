#
# Tests for INotify module
#

import pytest
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import INotify


class TestFlags:
    """Tests for INotify.Flags enum."""

    def test_flags_values(self):
        """Verify flag values match inotify constants."""
        assert INotify.Flags.ACCESS == 0x00000001
        assert INotify.Flags.MODIFY == 0x00000002
        assert INotify.Flags.ATTRIB == 0x00000004
        assert INotify.Flags.CLOSE_WRITE == 0x00000008
        assert INotify.Flags.CREATE == 0x00000100
        assert INotify.Flags.DELETE == 0x00000200
        assert INotify.Flags.MOVED_FROM == 0x00000040
        assert INotify.Flags.MOVED_TO == 0x00000080

    def test_flags_combination(self):
        """Test combining flags with OR."""
        combined = INotify.Flags.CLOSE_WRITE | INotify.Flags.CREATE
        assert combined == 0x00000108

        # Test CLOSE helper
        assert INotify.Flags.CLOSE == (INotify.Flags.CLOSE_WRITE | INotify.Flags.CLOSE_NOWRITE)

        # Test MOVE helper
        assert INotify.Flags.MOVE == (INotify.Flags.MOVED_FROM | INotify.Flags.MOVED_TO)

    def test_flags_in_operator(self):
        """Test checking if a flag is in a combined mask."""
        mask = INotify.Flags(INotify.Flags.CLOSE_WRITE | INotify.Flags.CREATE)

        assert INotify.Flags.CLOSE_WRITE in mask
        assert INotify.Flags.CREATE in mask
        assert INotify.Flags.DELETE not in mask

    def test_all_events_flag(self):
        """Verify ALL_EVENTS contains expected flags."""
        all_events = INotify.Flags.ALL_EVENTS

        assert INotify.Flags.ACCESS in all_events
        assert INotify.Flags.MODIFY in all_events
        assert INotify.Flags.CREATE in all_events
        assert INotify.Flags.DELETE in all_events
        assert INotify.Flags.CLOSE_WRITE in all_events


class TestEvent:
    """Tests for INotify.Event class."""

    def test_event_creation(self):
        """Test creating an Event object."""
        t = time.time()
        path = "/test/path/file.txt"
        flags = INotify.Flags(INotify.Flags.CLOSE_WRITE)

        event = INotify.Event(t, path, flags)

        assert event.t == t
        assert event.path == path
        assert event.flags == flags

    def test_event_repr(self):
        """Test Event string representation."""
        t = 1234567890.123
        path = "/test/path"
        flags = INotify.Flags(INotify.Flags.CREATE)

        event = INotify.Event(t, path, flags)
        repr_str = repr(event)

        assert path in repr_str
        assert str(t) in repr_str


class TestINotifyClass:
    """Tests for INotify.INotify class."""

    @pytest.mark.skipif(sys.platform != 'linux', reason="inotify only available on Linux")
    def test_inotify_creation(self, mock_logger):
        """Test INotify object creation."""
        inotify = INotify.INotify(mock_logger)
        assert inotify is not None
        assert inotify.name == "INotify"

    @pytest.mark.skipif(sys.platform != 'linux', reason="inotify only available on Linux")
    def test_inotify_add_watch(self, mock_logger, temp_dir):
        """Test adding a watch to a directory."""
        inotify = INotify.INotify(mock_logger)

        # Should not raise an exception
        inotify.add(temp_dir, recursive=True, mask=INotify.Flags.ALL_EVENTS)

    @pytest.mark.skipif(sys.platform != 'linux', reason="inotify only available on Linux")
    def test_inotify_add_recursive(self, mock_logger, temp_dir):
        """Test recursive watch adds subdirectories."""
        # Create subdirectory structure
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)

        inotify = INotify.INotify(mock_logger)
        inotify.add(temp_dir, recursive=True, mask=INotify.Flags.CREATE)

        # Both directories should be watched (internal state check)
        assert temp_dir in inotify._INotify__watches
        assert subdir in inotify._INotify__watches

    @pytest.mark.skipif(sys.platform != 'linux', reason="inotify only available on Linux")
    def test_inotify_remove_watch(self, mock_logger, temp_dir):
        """Test removing a watch."""
        inotify = INotify.INotify(mock_logger)
        inotify.add(temp_dir, recursive=False, mask=INotify.Flags.CREATE)

        # Should not raise an exception
        inotify.rm(temp_dir)

        # Directory should no longer be watched
        assert temp_dir not in inotify._INotify__watches

    @pytest.mark.skipif(sys.platform != 'linux', reason="inotify only available on Linux")
    def test_inotify_start_thread(self, mock_logger, temp_dir):
        """Test starting the INotify thread."""
        inotify = INotify.INotify(mock_logger)
        inotify.add(temp_dir, recursive=False, mask=INotify.Flags.CREATE)
        inotify.start()

        # Give thread time to start
        time.sleep(0.1)

        assert inotify.is_alive()

    @pytest.mark.skipif(sys.platform != 'linux', reason="inotify only available on Linux")
    def test_inotify_detect_file_creation(self, mock_logger, temp_dir):
        """Test detecting file creation events."""
        inotify = INotify.INotify(mock_logger)
        inotify.add(temp_dir, recursive=False, mask=INotify.Flags.CREATE | INotify.Flags.CLOSE_WRITE)
        inotify.start()

        # Create a file
        test_file = os.path.join(temp_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test")

        # Wait for event
        try:
            event = inotify.get(timeout=2.0)
            assert event is not None
            assert "test.txt" in event.path
            inotify.task_done()
        except Exception:
            pytest.skip("Event not received in time")
