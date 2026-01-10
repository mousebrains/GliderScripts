# Changelog

All notable changes to GliderScripts will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Retry logic with exponential backoff for failed rsync operations (`--rsyncRetries` option)
- Graceful shutdown handling for SIGTERM and SIGINT signals
- Hardened systemd service template (`probar.service`)
- Comprehensive installation documentation (`INSTALL.md`)
- Test suite with pytest (`tests/`)
  - `test_mylogger.py`: Tests for logging configuration
  - `test_inotify.py`: Tests for Flags, Event, and INotify classes
  - `test_rsync.py`: Tests for RSync class including retry logic
  - `test_syncgmc.py`: Tests for pattern matching and initial sync
- pytest configuration (`pytest.ini`, `requirements-dev.txt`)
- GitHub Actions CI/CD workflows (`.github/workflows/`)
  - `ci.yml`: Automated testing, linting (ruff), and type checking (mypy)
  - `release.yml`: Automated release creation on version tags
- Type annotations throughout codebase for mypy compatibility
- This changelog

### Changed
- Replaced bare `except:` clauses with `except Exception:` for better error handling
- Cached compiled regex patterns in `syncGMC.py` for improved performance
- Fixed undefined `logger` variable bug in `INotify.py` (was `logger`, now `self.__logger`)
- Updated `README.md` with current file structure and usage examples
- **INotify.py thread safety**: Added `threading.Lock` to protect shared dictionaries
- **INotify.py graceful shutdown**: Added `stop()` method and `select()` timeout for clean exit
- **INotify.py init failure**: Now re-raises exception to prevent invalid object usage
- **INotify.py overflow handling**: Now logs warning on inotify queue overflow
- **RSync.py graceful shutdown**: Added `stop()` method for clean thread termination
- **RSync.py join() fix**: Now calls `super().join()` after `queue.join()` for proper cleanup
- **MyLogger.py named logger**: Uses named logger (`GliderScripts`) instead of root logger
- Improved docstrings throughout codebase
- Fixed symlink handling in `os.walk()` calls (`followlinks=False`)

### Removed
- Removed unused sync scripts: `sync2SFMC.py`, `syncCache.py`, `probar.py`
- Removed unused service files: `sync2FMC0.service`, `sync683-686.service`, `syncCache2vm3.service`, `syncGMC2vm3.service`
- Removed legacy bash scripts: `sync2osudock`, `syncToFMC0`

## [1.0.0] - 2020-08-15

### Added
- Custom `INotify.py` module using ctypes (replaces pyinotify dependency)
- `RSync.py` threaded rsync wrapper module
- `MyLogger.py` centralized logging configuration

### Changed
- Refactored rsync execution into reusable `RSync` class
- Improved modularity by factoring out common functionality

## [0.1.0] - 2019-03-01

### Added
- Initial release
- `syncGMC.py` for monitoring and syncing SFMC dockserver directories
- Support for recursive inotify monitoring
- Event coalescing with configurable delay
- Email notifications for errors
- Systemd service integration
