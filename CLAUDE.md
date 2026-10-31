# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GliderScripts is a real-time file synchronization tool for SFMC (Slocum Fleet Mission Control) dockserver directories. It monitors filesystem events using Linux inotify and syncs changes to remote machines via rsync.

**Key constraint:** No external Python dependencies - uses only standard library.

## Common Commands

```bash
# Run tests
python3 -m pytest tests/ -v

# Run single test file
python3 -m pytest tests/test_rsync.py -v

# Run single test
python3 -m pytest tests/test_rsync.py::TestRSyncClass::test_rsync_retry_on_failure -v

# Lint
ruff check .

# Type check
mypy --ignore-missing-imports *.py

# Run with coverage
python3 -m pytest --cov=. --cov-report=term-missing

# Test the main script
python3 syncGMC.py --help
```

## Architecture

### Thread Model

The application uses three threads:
1. **Main thread**: Parses args, sets up signal handlers, runs the event loop (`doit()`)
2. **INotify thread**: Monitors filesystem via inotify, puts events on a queue
3. **RSync thread**: Consumes sync requests from a queue, executes rsync with retries

### Module Responsibilities

- **syncGMC.py**: Entry point, event loop, signal handling. Receives inotify events, coalesces them by waiting `--delay` seconds, then queues paths for rsync.
- **INotify.py**: Thread-safe inotify wrapper using ctypes. Recursively watches directories, auto-adds/removes watches for new/deleted subdirectories.
- **RSync.py**: Threaded rsync executor with backoff retry logic. Sources which fail every attempt are kept and retried every `--rsyncRetryDelay` seconds; only the first failed round in a row logs an error, which is what sends mail.
- **MyLogger.py**: Configures rotating file handler and optional SMTP error notifications.

### Event Flow

```
Filesystem event → INotify thread → event queue → Main thread (coalesce) → RSync queue → RSync thread → rsync subprocess
```

### Thread Safety

- INotify.py uses `threading.Lock` to protect shared watch dictionaries
- Both worker threads have `stop()` methods and check `threading.Event` for graceful shutdown
- RSync.join() waits for queue drain then calls super().join()

### Pattern Matching

The `--trigger` patterns determine which paths trigger syncs. When a path like `/var/opt/sfmc-dockserver/stations/project/glider/from-glider/file.txt` matches trigger `/from-glider`, the sync path becomes `/var/opt/sfmc-dockserver/stations/project/glider` (parent of the trigger match). Triggers and excludes are taken literally and match whole path components, so `/archive` does not match `/archived-deployments`; the first trigger in a path wins.

## Testing Notes

- INotify tests that require Linux are marked with `@pytest.mark.skipif(sys.platform != 'linux', ...)`
- RSync tests mock `subprocess.run` and use `stop()` before `join()` to avoid hangs
- Tests use fixtures from `conftest.py`: `mock_logger`, `temp_dir`, `rsync_args`, `syncgmc_args`
