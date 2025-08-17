"""Tests for the filter system."""

import subprocess
import sys

import pytest

from subprocess_vcr import SubprocessVCR
from subprocess_vcr.filters import (
    PathFilter,
    PythonExecutableFilter,
    RedactFilter,
)


class TestPathFilter:
    """Test path normalization filter.

    Note: PathFilter now includes CWD normalization and test runner context
    functionality that was previously in separate CwdFilter and TestRunnerCwdFilter classes.
    """

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows path separators differ")
    def test_normalizes_pytest_paths(self, tmp_path):
        """Test that pytest temporary paths are normalized."""
        cassette_path = tmp_path / "test_paths.yaml"
        filter = PathFilter()

        # Record with filter
        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            # Use a path that includes tmp_path
            result = subprocess.run(
                ["echo", str(tmp_path / "test.txt")],
                capture_output=True,
                text=True,
                cwd=tmp_path,
            )
            assert result.returncode == 0

        # Check recorded cassette has normalized paths
        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        # Command arg should be normalized to <CWD>/test.txt since tmp_path is the cwd
        normalized_arg = interaction["args"][1]
        assert normalized_arg == "<CWD>/test.txt"
        assert str(tmp_path) not in normalized_arg

        # cwd should be normalized to <CWD> (from integrated CWD functionality)
        normalized_cwd = interaction["kwargs"]["cwd"]
        assert normalized_cwd == "<CWD>"

        # stdout should contain normalized path
        assert "<CWD>/test.txt" in interaction["stdout"]
        assert str(tmp_path) not in interaction["stdout"]

    def test_custom_path_replacements(self, tmp_path):
        """Test custom path replacement patterns."""
        cassette_path = tmp_path / "test_custom_paths.yaml"
        filter = PathFilter(
            replacements={
                r"/opt/app": "<APP_ROOT>",
                r"/var/log/\w+": "<LOG_DIR>",
            }
        )

        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                ["echo", "/opt/app/config.json /var/log/myapp"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

        # Check normalization
        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        assert interaction["args"][1] == "<APP_ROOT>/config.json <LOG_DIR>"
        assert "<APP_ROOT>" in interaction["stdout"]
        assert "<LOG_DIR>" in interaction["stdout"]

    @pytest.mark.xfail(
        sys.platform == "win32", reason="Windows HOME path handling differs"
    )
    def test_home_directory_normalization(self, tmp_path):
        """Test that home directories are normalized."""
        import os

        # Get the real home directory
        import sys

        if sys.platform != "win32":
            import pwd

            # This is not affected by pytest's HOME manipulation on Unix
            real_home = pwd.getpwuid(os.getuid()).pw_dir
        else:
            # Windows fallback
            from pathlib import Path

            real_home = str(Path.home())

        cassette_path = tmp_path / "test_home.yaml"
        # PathFilter now automatically detects and handles real vs test home
        filter = PathFilter()

        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            # Use the real home directory
            result = subprocess.run(
                ["echo", f"{real_home}/documents"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        assert interaction["args"][1] == "<HOME>/documents"
        assert "<HOME>" in interaction["stdout"]
        assert real_home not in interaction["stdout"]

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows path separators differ")
    def test_cwd_normalization(self, tmp_path):
        """Test that CWD paths are normalized (integrated functionality)."""
        cassette_path = tmp_path / "test_cwd.yaml"
        filter = PathFilter()

        # Create a subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "test.txt"
        test_file.write_text("test")

        # Record with filter - run from tmp_path
        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                ["cat", str(test_file)],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            assert result.returncode == 0

        # Check recorded cassette
        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        # Command arg should use <CWD> for the file path
        assert interaction["args"][1] == "<CWD>/subdir/test.txt"
        # cwd itself should be <CWD>
        assert interaction["kwargs"]["cwd"] == "<CWD>"

    def test_preserves_non_cwd_paths(self, tmp_path):
        """Test that paths outside cwd are not changed."""
        cassette_path = tmp_path / "test_non_cwd.yaml"
        filter = PathFilter()

        # Record with filter
        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                ["echo", "/etc/passwd"],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            assert result.returncode == 0

        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        # /etc/passwd is not under cwd, should be unchanged
        assert interaction["args"][1] == "/etc/passwd"

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows path handling differs")
    def test_normalizes_paths_in_stdout_stderr(self, tmp_path):
        """Test that paths in stdout/stderr are normalized."""
        cassette_path = tmp_path / "test_output_normalization.yaml"
        filter = PathFilter()

        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            # Use Python to ensure cross-platform compatibility
            import sys

            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"print('Working in: {tmp_path}'); print('File: {tmp_path}/test.txt')",
                ],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
            )
            assert result.returncode == 0

        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        # stdout should have normalized paths
        assert "Working in: <CWD>" in interaction["stdout"]
        assert "File: <CWD>/test.txt" in interaction["stdout"]
        assert str(tmp_path) not in interaction["stdout"]

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows path separators differ")
    def test_normalizes_env_vars_with_paths(self, tmp_path):
        """Test that environment variables containing paths are normalized."""
        cassette_path = tmp_path / "test_env_normalization.yaml"
        filter = PathFilter()

        import os

        # Create the config directory so it exists
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        test_env = os.environ.copy()
        test_env["MY_PATH"] = str(tmp_path)
        test_env["CONFIG_DIR"] = str(config_dir)
        test_env["EXTERNAL_PATH"] = "/usr/local/bin"
        test_env["NOT_A_PATH"] = "just_a_string"

        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                ["env"],
                capture_output=True,
                text=True,
                cwd=str(tmp_path),
                env=test_env,
            )
            assert result.returncode == 0

        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        env = interaction["kwargs"]["env"]
        # Paths under cwd should be normalized
        assert env["MY_PATH"] == "<CWD>"
        assert env["CONFIG_DIR"] == "<CWD>/config"
        # External paths should be unchanged
        assert env["EXTERNAL_PATH"] == "/usr/local/bin"
        assert env["NOT_A_PATH"] == "just_a_string"


class TestRedactFilter:
    """Test sensitive information redaction."""

    def test_redacts_custom_patterns(self, tmp_path):
        """Test custom pattern redaction."""
        cassette_path = tmp_path / "test_redact.yaml"
        filter = RedactFilter(
            patterns=[r"secret-\w+", r"key=[\w-]+"], use_common_patterns=False
        )

        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                ["echo", "secret-abc123 api_key=xyz789 key=test-key"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        # Check args are redacted
        assert "<REDACTED>" in data["interactions"][0]["args"][1]
        assert "secret-abc123" not in data["interactions"][0]["args"][1]

        # Check stdout is redacted
        stdout = data["interactions"][0]["stdout"]
        # Our pattern matches "key=" followed by word chars, so it matches both key=xyz789 and key=test-key
        assert (
            stdout.count("<REDACTED>") >= 2
        )  # At least secret-abc123 and key=test-key
        assert "secret-abc123" not in stdout
        assert "key=test-key" not in stdout

    def test_redacts_environment_variables(self, tmp_path):
        """Test environment variable redaction."""
        cassette_path = tmp_path / "test_env_redact.yaml"
        filter = RedactFilter(env_vars=["API_KEY", "DB_PASSWORD"])

        import os

        test_env = os.environ.copy()
        test_env["API_KEY"] = "super-secret-key"
        test_env["DB_PASSWORD"] = "mysecretpass"
        test_env["PUBLIC_VAR"] = "not-secret"

        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                ["env"],
                capture_output=True,
                text=True,
                env=test_env,
            )
            assert result.returncode == 0

        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        # Check env vars are redacted in kwargs
        recorded_env = data["interactions"][0]["kwargs"]["env"]
        assert recorded_env["API_KEY"] == "<REDACTED>"
        assert recorded_env["DB_PASSWORD"] == "<REDACTED>"
        assert recorded_env["PUBLIC_VAR"] == "not-secret"

    def test_common_patterns(self, tmp_path):
        """Test common sensitive patterns are redacted."""
        cassette_path = tmp_path / "test_common_redact.yaml"
        filter = RedactFilter(use_common_patterns=True)

        sensitive_data = [
            "api_key=abc123xyz",
            "Bearer eyJhbGciOiJIUzI1NiIs",
            "https://user:pass@example.com",
            "AKIAIOSFODNN7EXAMPLE",  # AWS key format
        ]

        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                ["echo", " ".join(sensitive_data)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        stdout = data["interactions"][0]["stdout"]
        # All sensitive patterns should be redacted
        assert stdout.count("<REDACTED>") >= 4
        assert "abc123xyz" not in stdout
        assert "eyJhbGciOiJIUzI1NiIs" not in stdout
        assert "user:pass" not in stdout
        assert "AKIAIOSFODNN7EXAMPLE" not in stdout


class TestPythonExecutableFilter:
    """Test Python executable normalization."""

    def test_normalizes_python_executable(self, tmp_path):
        """Test that Python executables are normalized to <PYTHON>."""
        import sys

        cassette_path = tmp_path / "test_python_exec.yaml"
        filter = PythonExecutableFilter()

        # Record with filter
        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                [sys.executable, "-c", "print('hello')"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

        # Check recorded cassette
        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        # Python executable should be <PYTHON>
        assert interaction["args"][0] == "<PYTHON>"
        assert interaction["args"][1:] == ["-c", "print('hello')"]

    def test_preserves_non_python_executables(self, tmp_path):
        """Test that non-Python executables are not changed."""
        cassette_path = tmp_path / "test_non_python.yaml"
        filter = PythonExecutableFilter()

        with SubprocessVCR(cassette_path, mode="reset", filters=[filter]):
            result = subprocess.run(
                ["echo", "hello"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        interaction = data["interactions"][0]
        # echo should not be changed
        assert interaction["args"][0] == "echo"

    def test_handles_missing_args(self, tmp_path):
        """Test that filter handles edge cases gracefully."""
        filter = PythonExecutableFilter()

        # Test with empty args
        result = filter.before_record({"args": [], "kwargs": {}})
        assert result["args"] == []

        # Test with missing args key
        result = filter.before_record({"kwargs": {}})
        assert "args" not in result

        # Test with non-string first arg
        result = filter.before_record({"args": [123, "test"], "kwargs": {}})
        assert result["args"] == [123, "test"]


@pytest.mark.subprocess_vcr(filters=[PathFilter()])
def test_filter_via_pytest_mark(project_dir):
    """Test that filters can be specified via pytest mark."""
    # This test uses the pytest plugin with a filter
    result = subprocess.run(
        ["echo", str(project_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # In replay mode, the path will be normalized by the filter
    # In record mode, it will be the actual path
    # Both are valid - just check that we got some output
    assert result.stdout.strip()  # Should have output
    # Check it's either the actual path OR the normalized path
    assert str(project_dir) in result.stdout or "<TMP>" in result.stdout
