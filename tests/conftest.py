#
# Pytest configuration and fixtures for GliderScripts tests
#

import pytest
import sys
import os
import tempfile
import logging
from unittest.mock import Mock
from argparse import Namespace

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    logger = Mock(spec=logging.Logger)
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.debug = Mock()
    logger.exception = Mock()
    return logger


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def rsync_args():
    """Create minimal args namespace for RSync testing."""
    return Namespace(
        rsyncCmd='/usr/bin/rsync',
        rsyncTarget='testhost:/data/test',
        rsyncchmod='Do+rx,Fo+r',
        rsyncOpt=None,
        rsyncDryRun=False,
        rsyncExclude=None,
        rsyncRetries=3
    )


@pytest.fixture
def syncgmc_args(temp_dir):
    """Create minimal args namespace for syncGMC testing."""
    return Namespace(
        dir=[temp_dir],
        delay=30,
        trigger=['/from-glider', '/to-glider'],
        exclude=None,
        noInitial=True,
        rsyncCmd='/usr/bin/rsync',
        rsyncTarget='testhost:/data/test',
        rsyncchmod='Do+rx,Fo+r',
        rsyncOpt=None,
        rsyncDryRun=True,
        rsyncExclude=None,
        rsyncRetries=3
    )
