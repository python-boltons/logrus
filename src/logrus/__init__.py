"""logrus package

Better logging made easy with support for structlog and the standard logging
module.
"""

import logging as _logging

from ._core import (
    BetterBoundLogger,
    Log,
    LogFormat,
    Logger,
    LogLevel,
    get_default_logfile,
    init_logging,
)


__all__ = [
    "BetterBoundLogger",
    "Log",
    "LogFormat",
    "Logger",
    "LogLevel",
    "get_default_logfile",
    "init_logging",
]

__author__ = "Bryan M Bugyi"
__email__ = "bryanbugyi34@gmail.com"
__version__ = "0.1.0"

_logging.getLogger(__name__).addHandler(_logging.NullHandler())
