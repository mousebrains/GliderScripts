# Installation Guide

This guide covers installation of GliderScripts for syncing SFMC dockserver directories.

## Prerequisites

### System Requirements
- Linux (Debian/Ubuntu, RHEL/CentOS, or similar)
- Python 3.6 or later
- rsync
- systemd (for service installation)

### Network Requirements
- SSH access to the target backup server
- SSH key authentication configured (no password prompts)

## Quick Start

```bash
# Clone repository
git clone https://github.com/mousebrains/GliderScripts.git
cd GliderScripts

# Run tests
python3 -m pytest tests/ -v

# Install service
sudo cp syncGMC2fs2.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable syncGMC2fs2
sudo systemctl start syncGMC2fs2
```

## Detailed Installation

### 1. Install System Dependencies

**Debian/Ubuntu:**
```bash
sudo apt-get update
sudo apt-get install -y python3 rsync openssh-client
```

**RHEL/CentOS:**
```bash
sudo yum install -y python3 rsync openssh-clients
```

### 2. Download GliderScripts

```bash
# Option A: Clone with git
git clone https://github.com/mousebrains/GliderScripts.git

# Option B: Download tarball
wget https://github.com/mousebrains/GliderScripts/archive/refs/heads/master.tar.gz
tar xzf master.tar.gz
mv GliderScripts-master GliderScripts
```

### 3. Install Scripts

```bash
# Create bin directory if needed
mkdir -p ~/bin

# Copy scripts
cp GliderScripts/*.py ~/bin/
chmod +x ~/bin/syncGMC.py

# Verify installation
~/bin/syncGMC.py --help
```

### 4. Configure SSH Access

The service uses SSH for rsync to remote servers. Set up key-based authentication:

```bash
# Generate SSH key (if not already done)
ssh-keygen -t ed25519 -f ~/.ssh/glider_sync -N ""

# Copy public key to backup server
ssh-copy-id -i ~/.ssh/glider_sync.pub user@backup-server

# Test connection
ssh -i ~/.ssh/glider_sync user@backup-server "echo OK"
```

Configure SSH alias in `~/.ssh/config`:
```
Host fs2
    HostName backup-server.example.com
    User syncuser
    IdentityFile ~/.ssh/glider_sync
    IdentitiesOnly yes
    BatchMode yes
    ConnectTimeout 30
```

Test the alias:
```bash
ssh fs2 "echo OK"
rsync --dry-run -av /tmp/ fs2:/tmp/test/
```

### 5. Create Log Directory

```bash
mkdir -p ~/logs
```

### 6. Configure the Service

Edit the service file to match your environment:

```bash
cp GliderScripts/syncGMC2fs2.service /tmp/my-sync.service
nano /tmp/my-sync.service
```

Key settings to modify:
- `User=` and `Group=` - your username
- `WorkingDirectory=` - path to logs directory
- `ExecStart=` - path to syncGMC.py and your specific options
- `--rsyncTarget=` - your backup server destination
- `--trigger=` - directories to monitor
- `--logfile=` - log file path
- `--mailTo=` - notification email addresses

### 7. Install the Service

```bash
# Copy service file
sudo cp /tmp/my-sync.service /etc/systemd/system/syncGMC.service

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable syncGMC

# Start the service
sudo systemctl start syncGMC

# Check status
sudo systemctl status syncGMC
```

### 8. Verify Operation

```bash
# Watch logs
tail -f ~/logs/fs2.log

# Or use journalctl
journalctl -u syncGMC -f

# Create a test file to trigger sync
touch /var/opt/sfmc-dockserver/stations/test-project/test-glider/from-glider/test.txt
```

## Hardened Installation (Recommended)

For production systems, use the hardened service file:

```bash
# Copy hardened service
sudo cp GliderScripts/probar.service /etc/systemd/system/syncGMC.service

# Check security score
systemd-analyze security syncGMC.service

# Start service
sudo systemctl daemon-reload
sudo systemctl start syncGMC

# Watch for permission errors
journalctl -u syncGMC -f
```

If you encounter permission errors, see the Troubleshooting section.

## Configuration Reference

### syncGMC.py Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `dir` | Yes | - | Directories to monitor (positional) |
| `--trigger` | Yes | - | Directory patterns that trigger sync |
| `--exclude` | No | None | Directory patterns to exclude |
| `--delay` | No | 30 | Seconds to wait before syncing |
| `--noInitial` | No | False | Skip initial sync on startup |
| `--rsyncTarget` | Yes | - | Rsync destination |
| `--rsyncCmd` | No | /usr/bin/rsync | Path to rsync |
| `--rsyncRetries` | No | 3 | Retry attempts for failed sync |
| `--rsyncExclude` | No | None | Rsync exclude patterns |
| `--rsyncDryRun` | No | False | Don't execute rsync |
| `--rsyncchmod` | No | Do+rx,Fo+r | File permissions |
| `--logfile` | No | Console | Log file path |
| `--logBytes` | No | 10000000 | Max log file size |
| `--logCount` | No | 3 | Number of log backups |
| `--verbose` | No | False | Debug logging |
| `--mailTo` | No | None | Error notification emails |
| `--mailHost` | No | localhost | SMTP server |

### Service File Options

See `probar.service` for a fully documented example with security hardening.

## Troubleshooting

### Service won't start

```bash
# Check for syntax errors
sudo systemd-analyze verify /etc/systemd/system/syncGMC.service

# View detailed errors
journalctl -u syncGMC -n 50 --no-pager
```

### Permission denied errors

1. Check file ownership:
   ```bash
   ls -la ~/bin/syncGMC.py
   ls -la ~/logs/
   ```

2. For hardened service, add paths to `ReadWritePaths=` or `ReadOnlyPaths=`

3. Check SELinux/AppArmor:
   ```bash
   # SELinux
   sudo ausearch -m AVC -ts recent

   # AppArmor
   sudo aa-status
   ```

### rsync failures

1. Test rsync manually:
   ```bash
   rsync -av --dry-run /var/opt/sfmc-dockserver/stations/ fs2:/data/test/
   ```

2. Check SSH connectivity:
   ```bash
   ssh -v fs2 "echo OK"
   ```

3. Verify SSH key permissions:
   ```bash
   chmod 600 ~/.ssh/glider_sync
   chmod 700 ~/.ssh
   ```

### inotify watch limit

```bash
# Check current limit
cat /proc/sys/fs/inotify/max_user_watches

# Increase temporarily
sudo sysctl fs.inotify.max_user_watches=524288

# Increase permanently
echo 'fs.inotify.max_user_watches=524288' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### High CPU usage

Increase the `--delay` value to reduce sync frequency:
```bash
--delay=60  # Wait 60 seconds instead of 30
```

## Uninstallation

```bash
# Stop and disable service
sudo systemctl stop syncGMC
sudo systemctl disable syncGMC

# Remove service file
sudo rm /etc/systemd/system/syncGMC.service
sudo systemctl daemon-reload

# Remove scripts (optional)
rm ~/bin/syncGMC.py ~/bin/INotify.py ~/bin/RSync.py ~/bin/MyLogger.py
```

## Upgrading

```bash
# Stop service
sudo systemctl stop syncGMC

# Backup current scripts
cp ~/bin/syncGMC.py ~/bin/syncGMC.py.bak

# Update scripts
cd GliderScripts
git pull
cp *.py ~/bin/

# Restart service
sudo systemctl start syncGMC

# Verify
sudo systemctl status syncGMC
tail -f ~/logs/fs2.log
```
