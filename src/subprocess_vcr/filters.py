"""Filter system for subprocess VCR - modify interactions before recording/playback."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any


class BaseFilter:
    """Base class for filters with common functionality.

    Filters receive copies of interactions and must return the modified dictionary.
    """

    def before_record(self, interaction: dict[str, Any]) -> dict[str, Any]:
        """Modify interaction before recording to cassette.

        Args:
            interaction: The interaction dict with keys like 'args', 'kwargs',
                        'stdout', 'stderr', 'returncode', etc.

        Returns:
            The modified interaction dict that will be recorded.
        """
        return interaction

    def before_playback(self, interaction: dict[str, Any]) -> dict[str, Any]:
        """Modify interaction before playback from cassette.

        Args:
            interaction: The interaction dict loaded from cassette.

        Returns:
            The modified interaction dict used for matching.
        """
        return interaction

    def _apply_to_args(
        self,
        args: list[str] | str,
        replacements: list[tuple[str, str | Callable[[re.Match[str]], str]]],
    ) -> list[str] | str:
        """Apply regex replacements to command arguments."""
        # Convert to list for uniform processing
        args_list = [args] if isinstance(args, str) else args

        # Apply all replacements to each argument
        result = []
        for arg in args_list:
            for pattern, replacement in replacements:
                arg = re.sub(pattern, replacement, arg)
            result.append(arg)

        # Return in original format
        return result[0] if isinstance(args, str) else result

    def _apply_to_text(
        self,
        text: str | None,
        replacements: list[tuple[str, str | Callable[[re.Match[str]], str]]],
    ) -> str | None:
        """Apply regex replacements to text content."""
        if text is None:
            return None

        result = text
        for pattern, replacement in replacements:
            result = re.sub(pattern, replacement, result)
        return result


class PathFilter(BaseFilter):
    """Normalize filesystem paths.

    Handles common dynamic paths that change between test runs:
    - pytest temporary directories
    - home directories (both real and test-modified)
    - Windows user profiles
    - Custom path mappings
    """

    @staticmethod
    def _pytest_path_repl(match: re.Match[str]) -> str:
        """Replace pytest paths, preserving test name if present."""
        test_name = match.group(1)
        return f"<TMP>/{test_name}" if test_name else "<TMP>"

    def __init__(
        self,
        replacements: dict[str, str] | None = None,
    ):
        """Initialize path filter.

        Args:
            replacements: Custom path replacements mapping regex patterns to replacements.
                         If None, uses default patterns.
        """
        if replacements is None:
            self._setup_default_replacements()
        else:
            self._setup_custom_replacements(replacements)

    def _setup_default_replacements(self):
        """Set up default path replacement patterns."""
        # Detect system paths
        self._detect_system_paths()

        # Build pattern lists
        home_patterns = self._build_home_patterns()
        temp_patterns = self._build_temp_patterns()

        # Combine patterns
        self.replacements = home_patterns + temp_patterns

    def _setup_custom_replacements(self, replacements: dict[str, str]):
        """Set up custom replacement patterns."""
        self.replacements = [(pattern, repl) for pattern, repl in replacements.items()]

    def _detect_system_paths(self):
        """Detect and store system paths."""
        # Capture real system paths (unaffected by pytest)
        import sys
        from pathlib import Path

        if sys.platform != "win32":
            try:
                import pwd

                self.real_home = pwd.getpwuid(os.getuid()).pw_dir
            except (KeyError, AttributeError):
                # Fallback for unusual environments
                self.real_home = str(Path.home())
        else:
            # Windows
            self.real_home = str(Path.home())

        # Capture current environment (might be pytest-modified)
        self.env_home = str(Path.home())

        # Capture test runner's cwd
        self.test_runner_cwd = str(Path.cwd().resolve())

        # Check if home was modified (e.g., by pytest)
        self.home_is_modified = self.real_home != self.env_home

    def _build_home_patterns(
        self,
    ) -> list[tuple[str, str | Callable[[re.Match[str]], str]]]:
        """Build patterns for home directory normalization."""
        # Always include all patterns - duplicates are harmless
        # Order matters: more specific patterns first
        return [
            # TEST_RUNNER_CWD (most specific)
            (re.escape(self.test_runner_cwd), "<TEST_RUNNER_CWD>"),
            # HOME directories
            (re.escape(self.real_home), "<HOME>"),
            (re.escape(self.env_home), "<TEST_HOME>"),
        ]

    def _build_temp_patterns(
        self,
    ) -> list[tuple[str, str | Callable[[re.Match[str]], str]]]:
        """Build patterns for temporary directory normalization."""
        return [
            # === PYTEST TEMPORARY DIRECTORIES ===
            # Full pytest paths with test names - preserve test name only
            # macOS: /private/var/folders/xx/yy/T/pytest-of-user/pytest-123/popen-gw4/test_name0
            # Becomes: <TMP>/test_name0
            (
                r"/private/var/folders/[^/]+/[^/]+(?:/[^/]+)?/T/pytest-of-[^/]+/pytest-\d+(?:/popen-gw\d+)?(?:/(.+))?",
                PathFilter._pytest_path_repl,
            ),
            # Linux: /tmp/pytest-of-user/pytest-123/popen-gw4/test_name0
            # Becomes: <TMP>/test_name0
            (
                r"/tmp/pytest-of-[^/]+/pytest-\d+(?:/popen-gw\d+)?(?:/(.+))?",
                PathFilter._pytest_path_repl,
            ),
            # Pytest directories without test names - normalize entirely
            (
                r"/private/var/folders/[^/]+/[^/]+(?:/[^/]+)?/T/pytest-of-[^/]+/pytest-\d+(?:/popen-gw\d+)?",
                "<TMP>",
            ),
            (
                r"/tmp/pytest-of-[^/]+/pytest-\d+(?:/popen-gw\d+)?",
                "<TMP>",
            ),
            # === GENERIC TEMPORARY DIRECTORIES ===
            # macOS temp paths (with or without /private prefix)
            (r"(?:/private)?/var/folders/[^/]+/[^/]+/T/[^\s\"']+", "<TMP>"),
            # macOS temp base directories
            (r"/private/var/folders/[^/]+/[^/]+(?:/[^/]+)?/T", "<TMP>"),
            (r"/private/var/folders/[^/]+/[^/]+(?:/[^/]+)?", "<TMP>"),
            # Specific /tmp patterns that are test-related
            (r"/tmp/pytest-[^/]+", "<TMP>"),  # Older pytest format
            (r"/tmp/tmp[a-zA-Z0-9_]+", "<TMP>"),  # mktemp style paths
            # === WINDOWS PATHS ===
            (r"C:\\Users\\[^\\]+", "<USERPROFILE>"),
            (r"C:\\\\Users\\\\[^\\\\]+", "<USERPROFILE>"),  # Escaped backslashes
        ]

    def before_record(self, interaction: dict[str, Any]) -> dict[str, Any]:
        """Normalize paths before recording."""
        from pathlib import Path

        # Get the subprocess cwd (from kwargs or current directory)
        cwd = interaction.get("kwargs", {}).get("cwd") or Path.cwd()

        # Build CWD patterns first to ensure they take precedence
        # Include both original and resolved paths to handle symlinks
        cwd_patterns = [
            (re.escape(str(Path(cwd).resolve())), "<CWD>"),  # Resolved path
            (re.escape(str(cwd)), "<CWD>"),  # Original path
        ]

        dynamic_replacements = cwd_patterns + self.replacements

        # Apply to command arguments
        if "args" in interaction:
            interaction["args"] = self._apply_to_args(
                interaction["args"], dynamic_replacements
            )

        # Apply to kwargs that might contain paths
        if "kwargs" in interaction:
            kwargs = interaction["kwargs"]

            # Normalize cwd itself to <CWD>
            if "cwd" in kwargs and kwargs["cwd"] is not None:
                kwargs["cwd"] = "<CWD>"

            # Normalize env vars that might contain paths
            if env := kwargs.get("env"):
                kwargs["env"] = {
                    key: self._apply_to_text(value, dynamic_replacements)
                    if isinstance(value, str)
                    else value
                    for key, value in env.items()
                }

        # Apply to stdout/stderr
        interaction["stdout"] = self._apply_to_text(
            interaction.get("stdout"), dynamic_replacements
        )
        interaction["stderr"] = self._apply_to_text(
            interaction.get("stderr"), dynamic_replacements
        )

        return interaction


class RedactFilter(BaseFilter):
    """Remove sensitive information.

    Can redact:
    - Custom regex patterns
    - Environment variable values
    - Common sensitive patterns (API keys, tokens, etc.)
    """

    def __init__(
        self,
        patterns: list[str] | None = None,
        env_vars: list[str] | None = None,
        use_common_patterns: bool = True,
    ):
        """Initialize redaction filter.

        Args:
            patterns: List of regex patterns to redact
            env_vars: List of environment variable names whose values should be redacted
            use_common_patterns: Whether to include common sensitive patterns
        """
        self.patterns = patterns or []
        self.env_vars = env_vars or []

        # Common patterns for sensitive data
        if use_common_patterns:
            self.patterns.extend(
                [
                    # API keys and tokens
                    r"(?i)(?:api[_-]?key|token|secret|password)[\s=:]+[\w-]+",
                    # Bearer tokens
                    r"Bearer\s+[\w-]+",
                    # Basic auth
                    r"Basic\s+[A-Za-z0-9+/]+=*",
                    # AWS keys
                    r"(?:AKIA|ASIA)[0-9A-Z]{16}",
                    # URLs with credentials
                    r"(?:https?|ftp)://[^:]+:[^@]+@[^\s]+",
                ]
            )

        # Compile patterns for efficiency
        self.compiled_patterns = [re.compile(p) for p in self.patterns]

    def before_record(self, interaction: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive information before recording."""

        # Helper to apply all redaction patterns
        def redact_text(text: str) -> str:
            for pattern in self.compiled_patterns:
                text = pattern.sub("<REDACTED>", text)
            return text

        # Redact from command arguments
        if "args" in interaction:
            args = interaction["args"]
            if isinstance(args, str):
                interaction["args"] = redact_text(args)
            else:
                interaction["args"] = [redact_text(arg) for arg in args]

        # Redact environment variables
        if env := interaction.get("kwargs", {}).get("env"):
            # No need to copy - interaction is already a deep copy from core.py
            for var_name in self.env_vars:
                if var_name in env:
                    env[var_name] = "<REDACTED>"

        # Redact from stdout/stderr
        for field in ["stdout", "stderr"]:
            if text := interaction.get(field):
                interaction[field] = redact_text(text)

        return interaction

    def before_playback(self, interaction: dict[str, Any]) -> dict[str, Any]:
        """Default implementation - no changes on playback."""
        return interaction


class PythonExecutableFilter(BaseFilter):
    """Normalize Python executable paths to a portable placeholder.

    This filter replaces any Python executable path with <PYTHON> to make
    cassettes portable across different environments, virtual environments,
    and Python installations.
    """

    def before_record(self, interaction: dict[str, Any]) -> dict[str, Any]:
        """Replace Python executable paths with <PYTHON> placeholder."""
        # Only process non-shell commands with args
        args = interaction.get("args", [])
        if args and isinstance(args, list) and isinstance(args[0], str):
            if self._is_python_executable(args[0]):
                interaction["args"][0] = "<PYTHON>"

        return interaction

    def _is_python_executable(self, path: str) -> bool:
        """Check if a path points to a Python executable."""
        import os

        # Check if file exists and is executable
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            return False

        # Check if the filename indicates it's Python
        basename = os.path.basename(path)
        if basename.startswith("python"):
            return True

        # Check if it's in a typical Python location
        if "python" in path.lower() and (
            "/bin/" in path or "\\scripts\\" in path.lower()
        ):
            return True

        # For virtual environments, check if it's in a venv/bin or Scripts directory
        path_parts = path.split(os.sep)
        if len(path_parts) >= 2:
            # Check for .venv/bin/python or venv/Scripts/python.exe patterns
            for i in range(len(path_parts) - 1):
                if "venv" in path_parts[i].lower() and path_parts[i + 1] in (
                    "bin",
                    "Scripts",
                ):
                    return True

        return False
