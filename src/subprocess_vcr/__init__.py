"""Subprocess VCR - Record and replay subprocess commands for testing."""

__version__ = "0.1.0"

from .core import SubprocessVCR, SubprocessVCRError
from .filters import (
    BaseFilter,
    PathFilter,
    PythonExecutableFilter,
    RedactFilter,
)

__all__ = [
    # Core
    "SubprocessVCR",
    "SubprocessVCRError",
    # Filters
    "BaseFilter",
    "PathFilter",
    "PythonExecutableFilter",
    "RedactFilter",
]
