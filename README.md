# GliderScripts

[![CI](https://github.com/mousebrains/GliderScripts/actions/workflows/ci.yml/badge.svg)](https://github.com/mousebrains/GliderScripts/actions/workflows/ci.yml)

A lightweight Python tool for real-time file synchronization from SFMC dockserver directories to remote machines using inotify and rsync.

## Overview

GliderScripts monitors specified directories on an SFMC (Science File Management System) dockserver and automatically syncs changes to a remote target using rsync. It uses Linux's inotify mechanism for efficient file system monitoring.

## Features

- **Real-time monitoring** using native Linux inotify (no external dependencies)
- **Automatic retry** with exponential backoff for failed rsync operations
- **Event coalescing** to prevent excessive syncs during rapid changes
- **Graceful shutdown** handling for SIGTERM and SIGINT
- **Email notifications** for error conditions
- **Systemd integration** for reliable service deployment
- **No external Python dependencies** - uses only standard library

## Requirements

- Linux (for inotify support)
- Python 3.6+
- rsync

## Files

```
GliderScripts/
├── syncGMC.py            # Main monitoring and sync script
├── INotify.py            # Native inotify interface using ctypes
├── RSync.py              # Threaded rsync wrapper with retry logic
├── MyLogger.py           # Logging configuration with file rotation
├── syncGMC2fs2.service   # Example systemd service file
├── probar.service        # Security-hardened service template
├── tests/                # Unit test suite
│   ├── conftest.py       # Pytest fixtures
│   ├── test_mylogger.py  # Logger tests
│   ├── test_inotify.py   # INotify tests
│   ├── test_rsync.py     # RSync tests
│   └── test_syncgmc.py   # Main script tests
├── .github/workflows/    # CI/CD workflows
│   ├── ci.yml            # Test, lint, type check on push/PR
│   └── release.yml       # Create releases on version tags
├── pytest.ini            # Pytest configuration
├── requirements-dev.txt  # Development dependencies
├── INSTALL.md            # Installation guide
├── CHANGELOG.md          # Version history
├── LICENSE               # GPL v3
└── README.md
```

## Installation

1. Clone or copy the scripts to your target machine:
   ```bash
   git clone https://github.com/mousebrains/GliderScripts.git
   cd GliderScripts
   ```

2. Ensure rsync is installed:
   ```bash
   sudo apt-get install rsync  # Debian/Ubuntu
   ```

3. Configure and install the systemd service:
   ```bash
   # Edit the service file with your paths and settings
   sudo cp syncGMC2fs2.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable syncGMC2fs2
   sudo systemctl start syncGMC2fs2
   ```

## Usage

### Command Line

```bash
python3 syncGMC.py /var/opt/sfmc-dockserver/stations \
    --trigger=/from-glider \
    --trigger=/to-glider \
    --trigger=/archive \
    --rsyncTarget=backup-server:/data/gliders \
    --logfile=/var/log/glider/sync.log \
    --verbose
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `dir` | Directories to monitor (positional, required) | - |
| `--trigger` | Directory patterns that trigger sync (required, repeatable) | - |
| `--exclude` | Directory patterns to exclude (repeatable) | None |
| `--delay` | Seconds to wait after event before syncing | 30 |
| `--noInitial` | Skip initial sync on startup | False |
| `--rsyncTarget` | Rsync destination (required) | - |
| `--rsyncRetries` | Number of retry attempts | 3 |
| `--rsyncExclude` | Rsync exclude patterns (repeatable) | None |
| `--rsyncDryRun` | Log commands without executing | False |
| `--logfile` | Log file path (uses console if not set) | Console |
| `--verbose` | Enable debug logging | False |
| `--mailTo` | Email address for error notifications (repeatable) | None |

### Example Service Configuration

```ini
[Unit]
Description=Sync SFMC dockserver to backup

[Service]
User=pat
Group=pat
ExecStart=/home/pat/bin/syncGMC.py \
    --rsyncTarget=backup:/data/gliders \
    --trigger=/from-glider \
    --trigger=/to-glider \
    --logfile=/var/log/glider/sync.log \
    /var/opt/sfmc-dockserver/stations
Restart=always
RestartSec=300

[Install]
WantedBy=multi-user.target
```

## Directory Structure

The script expects the SFMC dockserver structure:

```
/var/opt/sfmc-dockserver/stations/
└── {project}/
    └── {glider}/
        ├── from-glider/   # Data from glider
        ├── to-glider/     # Commands to glider
        ├── archive/       # Archived data
        └── logs/          # Log files
```

## How It Works

1. **Startup**: Optionally performs an initial sync of all matching directories
2. **Monitoring**: Uses inotify to watch for file system events (create, modify, delete, move)
3. **Coalescing**: Waits `--delay` seconds after the first event to batch changes
4. **Syncing**: Executes rsync with automatic retry on failure
5. **Shutdown**: Handles SIGTERM/SIGINT gracefully, waiting for pending syncs

## Testing

Run the test suite with pytest:

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
python3 -m pytest

# Run with verbose output
python3 -m pytest -v

# Run with coverage report
python3 -m pytest --cov=. --cov-report=term-missing

# Run only non-Linux tests (for macOS/other platforms)
python3 -m pytest -v -k "not linux"
```

Note: Some tests require Linux (for inotify support) and will be skipped on other platforms.

## Troubleshooting

### Check service status
```bash
sudo systemctl status syncGMC2fs2
sudo journalctl -u syncGMC2fs2 -f
```

### inotify watch limit
If monitoring many directories, you may need to increase the limit:
```bash
echo 'fs.inotify.max_user_watches=524288' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### Test rsync manually
```bash
rsync -av --dry-run /source/path/ user@host:/dest/path/
```

## Contributing

Contributions are welcome! The project uses GitHub Actions for CI/CD:

- **On push/PR**: Runs linting (ruff), type checking (mypy), and tests across Python 3.8-3.12
- **On version tag**: Creates a GitHub release automatically

Before submitting a PR, ensure your changes pass all checks:

```bash
# Install dev dependencies
pip install -r requirements-dev.txt
pip install ruff mypy

# Run linter
ruff check .

# Run type checker
mypy --ignore-missing-imports *.py

# Run tests
python -m pytest tests/ -v
```

## License

GNU General Public License v3.0

## Author

Pat Welch <pat@mousebrains.com>
