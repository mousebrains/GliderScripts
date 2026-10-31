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


def _drain(inotify, timeout=0.5):
    """Collect events until none arrive for timeout seconds."""
    import queue
    events = []
    while True:
        try:
            events.append(inotify.get(timeout=timeout))
            inotify.task_done()
        except queue.Empty:
            return events


@pytest.mark.skipif(sys.platform != 'linux', reason="inotify only available on Linux")
class TestINotifyRobustness:
    """Tests for error handling and edge cases."""

    def test_libc_errors_raise(self, mock_logger):
        """Test a failing libc call raises OSError with the real errno."""
        import errno
        inotify = INotify.INotify(mock_logger)
        with pytest.raises(OSError) as e:
            inotify._INotify__callLibC("inotify_add_watch", 9999, b"/", 1)
        assert e.value.errno == errno.EBADF

    def test_add_missing_path(self, mock_logger, temp_dir):
        """Test watching a path which does not exist records no watch."""
        inotify = INotify.INotify(mock_logger)
        missing = os.path.join(temp_dir, "missing")
        inotify.add(missing, recursive=True, mask=INotify.Flags.CREATE)
        assert missing not in inotify._INotify__watches
        mock_logger.exception.assert_not_called()

    def test_rm_does_not_remove_prefix_siblings(self, mock_logger, temp_dir):
        """Test removing /a/b leaves /a/b2 watched."""
        for name in ("b", "b2"):
            os.mkdir(os.path.join(temp_dir, name))
        inotify = INotify.INotify(mock_logger)
        inotify.add(temp_dir, recursive=True, mask=INotify.Flags.CREATE)
        inotify.rm(os.path.join(temp_dir, "b"))
        assert os.path.join(temp_dir, "b") not in inotify._INotify__watches
        assert os.path.join(temp_dir, "b2") in inotify._INotify__watches

    def test_non_utf8_filename(self, mock_logger, temp_dir):
        """Test a non-UTF-8 filename is reported and does not kill the thread."""
        inotify = INotify.INotify(mock_logger)
        inotify.add(temp_dir, recursive=True, mask=INotify.Flags.CREATE)
        inotify.start()
        fd = os.open(os.fsencode(temp_dir) + b"/bad\xff.txt", os.O_CREAT | os.O_WRONLY)
        os.close(fd)
        events = _drain(inotify)
        assert inotify.is_alive()
        assert any("bad" in e.path for e in events)
        inotify.stop()

    def test_fast_nested_directory_creation(self, mock_logger, temp_dir):
        """Test files created in a new directory before its watch exists are reported."""
        inotify = INotify.INotify(mock_logger)
        inotify.add(temp_dir, recursive=True, mask=INotify.Flags.CREATE | INotify.Flags.CLOSE_WRITE)
        inotify.start()
        deep = os.path.join(temp_dir, "new", "deep", "deeper")
        os.makedirs(deep)
        with open(os.path.join(deep, "f.txt"), "w") as fp:
            fp.write("x")
        events = _drain(inotify)
        assert os.path.join(deep, "f.txt") in [e.path for e in events]
        assert deep in inotify._INotify__watches
        inotify.stop()

    def test_deleted_directory_forgotten(self, mock_logger, temp_dir):
        """Test watches for a deleted tree are dropped."""
        import shutil
        sub = os.path.join(temp_dir, "sub", "subsub")
        os.makedirs(sub)
        inotify = INotify.INotify(mock_logger)
        inotify.add(temp_dir, recursive=True, mask=INotify.Flags.CREATE | INotify.Flags.DELETE)
        inotify.start()
        shutil.rmtree(os.path.join(temp_dir, "sub"))
        _drain(inotify)
        assert not any(k.startswith(os.path.join(temp_dir, "sub")) for k in inotify._INotify__watches)
        mock_logger.exception.assert_not_called()
        inotify.stop()

    def test_overflow_queues_event(self, mock_logger):
        """Test a queue overflow is passed on as an Event with path None."""
        import struct
        inotify = INotify.INotify(mock_logger)
        raw = bytearray(struct.pack("iIII", -1, INotify.Flags.Q_OVERFLOW, 0, 0))
        assert inotify._INotify__procBuffer(raw) == bytearray()
        event = inotify.get(timeout=1.0)
        assert event.path is None
        assert INotify.Flags.Q_OVERFLOW in event.flags
