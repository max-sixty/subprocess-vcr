"""Comprehensive tests for PathFilter pytest path normalization."""

import subprocess
import sys

import pytest

from subprocess_vcr import SubprocessVCR
from subprocess_vcr.filters import PathFilter


class TestPathFilterComprehensive:
    """Test PathFilter handles all pytest path variations correctly."""

    def test_pytest_paths_macos(self):
        """Test normalization of macOS pytest paths."""
        filter = PathFilter()

        test_cases = [
            # Full pytest path with test name
            (
                "/private/var/folders/wf/s6ycxvvs4ln8qsdbfx40hnc40000gn/T/pytest-of-maximilian/pytest-463/popen-gw2/test_name0",
                "<TMP>/test_name0",
            ),
            # Without worker ID
            (
                "/private/var/folders/xx/yy/zz/T/pytest-of-user/pytest-999/test_something",
                "<TMP>/test_something",
            ),
            # Just the pytest directory (no test name)
            (
                "/private/var/folders/aa/bb/cc/T/pytest-of-runner/pytest-123/popen-gw4",
                "<TMP>",
            ),
            # Generic macOS temp path (not pytest)
            ("/private/var/folders/aa/bb/cc/T/some_file.txt", "<TMP>/some_file.txt"),
        ]

        for input_path, expected in test_cases:
            interaction = {"args": ["echo", input_path]}
            result = filter.before_record(interaction)
            assert result["args"][1] == expected, (
                f"Expected {expected}, got {result['args'][1]}"
            )

    def test_pytest_paths_linux(self):
        """Test normalization of Linux pytest paths."""
        filter = PathFilter()

        test_cases = [
            # Full pytest path with worker and test name
            ("/tmp/pytest-of-runner/pytest-123/popen-gw0/test_file", "<TMP>/test_file"),
            # Without worker ID
            ("/tmp/pytest-of-user/pytest-456/test_simple", "<TMP>/test_simple"),
            # Just the pytest directory
            ("/tmp/pytest-of-user/pytest-789", "<TMP>"),
            # mktemp style path
            ("/tmp/tmpab3d_xyz/test.txt", "<TMP>/test.txt"),
        ]

        for input_path, expected in test_cases:
            interaction = {"args": ["echo", input_path]}
            result = filter.before_record(interaction)
            assert result["args"][1] == expected, (
                f"Expected {expected}, got {result['args'][1]}"
            )

    def test_non_pytest_paths_preserved(self):
        """Test that non-pytest paths are not over-normalized."""
        filter = PathFilter()

        test_cases = [
            # Container paths should not be normalized
            ("/tmp/test.txt", "/tmp/test.txt"),
            ("/tmp/netguard-ready", "/tmp/netguard-ready"),
            ("/var/log/app.log", "/var/log/app.log"),
            # Non-temp paths
            ("/etc/config", "/etc/config"),
            ("/opt/app/bin", "/opt/app/bin"),
        ]

        for input_path, expected in test_cases:
            interaction = {"args": ["echo", input_path]}
            result = filter.before_record(interaction)
            assert result["args"][1] == expected, (
                f"Expected {expected}, got {result['args'][1]}"
            )

    @pytest.mark.xfail(
        sys.platform == "win32", reason="Windows HOME path handling differs"
    )
    def test_home_directory_normalization(self):
        """Test home directory normalization works correctly."""
        import os

        # Get the real home directory
        import sys

        if sys.platform != "win32":
            import pwd

            # This is not affected by pytest's HOME manipulation on Unix
            home = pwd.getpwuid(os.getuid()).pw_dir
        else:
            # Windows fallback
            from pathlib import Path

            home = str(Path.home())

        # PathFilter now automatically detects and handles real vs test home
        filter = PathFilter()

        # Test actual home directory normalization
        test_cases = [
            (f"{home}/code", "<HOME>/code"),
            (f"{home}/project", "<HOME>/project"),
            (f"{home}/.config", "<HOME>/.config"),
            (home, "<HOME>"),  # Just the home directory itself
        ]

        for input_path, expected in test_cases:
            interaction = {"args": ["echo", input_path]}
            result = filter.before_record(interaction)
            assert result["args"][1] == expected, (
                f"Expected {expected}, got {result['args'][1]}"
            )

    def test_pytest_modified_home_normalization(self):
        """Test that pytest-modified HOME is normalized."""
        from pathlib import Path

        filter = PathFilter()

        # If home is modified (e.g., by pytest)
        if filter.home_is_modified:
            # Test that the current (pytest-modified) home is normalized
            env_home = str(Path.home())

            interaction = {"args": ["echo", f"{env_home}/test_data"]}
            result = filter.before_record(interaction)

            # When test_runner_cwd equals env_home, it could be normalized to either
            # TEST_RUNNER_CWD, TEST_HOME, or CWD depending on pattern order and
            # whether the current working directory matches
            assert result["args"][1] in [
                "<TEST_HOME>/test_data",
                "<TEST_RUNNER_CWD>/test_data",
                "<CWD>/test_data",  # CWD pattern now takes precedence
            ], (
                f"Expected <TEST_HOME>/test_data, <TEST_RUNNER_CWD>/test_data, or <CWD>/test_data, got {result['args'][1]}"
            )

    def test_path_in_stdout_stderr(self):
        """Test that paths in stdout/stderr are also normalized."""
        filter = PathFilter()

        pytest_path = "/tmp/pytest-of-user/pytest-123/popen-gw0/test_output"
        interaction = {
            "args": ["cat", pytest_path],
            "stdout": f"Reading from {pytest_path}\nContent here",
            "stderr": f"Error in {pytest_path}",
        }

        result = filter.before_record(interaction)

        # Args should be normalized
        assert result["args"][1] == "<TMP>/test_output"

        # stdout should be normalized
        assert result["stdout"] == "Reading from <TMP>/test_output\nContent here"

        # stderr should be normalized
        assert result["stderr"] == "Error in <TMP>/test_output"

    def test_path_in_cwd(self):
        """Test that cwd paths are normalized correctly."""
        filter = PathFilter()

        interaction = {
            "args": ["ls"],
            "kwargs": {
                "cwd": "/private/var/folders/aa/bb/cc/T/pytest-of-user/pytest-999/test_dir"
            },
        }

        result = filter.before_record(interaction)
        # With integrated CwdFilter, cwd is always normalized to <CWD>
        assert result["kwargs"]["cwd"] == "<CWD>"

    def test_multiple_paths_in_command(self):
        """Test commands with multiple paths are all normalized."""
        filter = PathFilter()

        interaction = {
            "args": [
                "cp",
                "/tmp/pytest-of-user/pytest-123/test_src/file.txt",
                "/tmp/pytest-of-user/pytest-123/test_dst/file.txt",
            ]
        }

        result = filter.before_record(interaction)
        assert result["args"][1] == "<TMP>/test_src/file.txt"
        assert result["args"][2] == "<TMP>/test_dst/file.txt"

    def test_complex_pytest_path_variations(self):
        """Test various complex pytest path patterns."""
        filter = PathFilter()

        test_cases = [
            # Nested test directories
            (
                "/tmp/pytest-of-user/pytest-123/popen-gw0/test_nested/subdir/file.txt",
                "<TMP>/test_nested/subdir/file.txt",
            ),
            # Test with numbers
            (
                "/tmp/pytest-of-user/pytest-999/test_123_numbers",
                "<TMP>/test_123_numbers",
            ),
            # Test with underscores and hyphens
            (
                "/tmp/pytest-of-user/pytest-100/test_with-hyphens_and_underscores0",
                "<TMP>/test_with-hyphens_and_underscores0",
            ),
        ]

        for input_path, expected in test_cases:
            interaction = {"args": ["echo", input_path]}
            result = filter.before_record(interaction)
            assert result["args"][1] == expected, (
                f"Expected {expected}, got {result['args'][1]}"
            )


def test_filter_preserves_trailing_slash():
    """Test that trailing slashes are preserved in paths."""
    filter = PathFilter()

    interaction = {"args": ["ls", "/tmp/pytest-of-user/pytest-123/test_dir/"]}

    result = filter.before_record(interaction)
    assert result["args"][1] == "<TMP>/test_dir/"


def test_filter_with_vcr_integration(tmp_path):
    """Test PathFilter works correctly with VCR recording and replay."""
    cassette_path = tmp_path / "test_integration.yaml"

    # Create test file
    test_file = tmp_path / "data.txt"
    test_file.write_text("test data")

    # Record with filter
    with SubprocessVCR(cassette_path, mode="reset", filters=[PathFilter()]):
        result1 = subprocess.run(
            ["cat", str(test_file)],
            capture_output=True,
            text=True,
        )
        assert result1.returncode == 0
        assert "test data" in result1.stdout

    # Simulate different pytest run by modifying tmp_path
    # We'll just replay the same command - the filter should normalize the changing pytest path
    with SubprocessVCR(cassette_path, mode="replay", filters=[PathFilter()]):
        result2 = subprocess.run(
            ["cat", str(test_file)],
            capture_output=True,
            text=True,
        )
        assert result2.returncode == 0
        assert "test data" in result2.stdout
