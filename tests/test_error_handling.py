"""Test error handling and diagnostics in subprocess-vcr."""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from subprocess_vcr import SubprocessVCR, SubprocessVCRError


@pytest.mark.xfail(sys.platform == "win32", reason="Windows file locking differs")
def test_file_handle_error_message(tmp_path):
    """Test that file handles produce a helpful error message."""
    cassette_path = tmp_path / "test.yaml"

    # Create a temporary file to use as stdout
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
        temp_file_path = temp_file.name

        try:
            with SubprocessVCR(cassette_path, mode="record"):
                # This should fail with our improved error message
                with pytest.raises(SubprocessVCRError) as exc_info:
                    # Try to use the file handle as stdout
                    subprocess.Popen(
                        ["echo", "test"], stdout=temp_file, stderr=subprocess.PIPE
                    )

            # Check that the error message is helpful
            error_msg = str(exc_info.value)
            assert "Cannot record subprocess with file handle" in error_msg
            assert "stdout is a file object" in error_msg
            assert temp_file_path in error_msg
            assert "Solutions:" in error_msg
            assert "@pytest.mark.subprocess_vcr" in error_msg
            assert "subprocess.PIPE" in error_msg

        finally:
            # Clean up
            Path(temp_file_path).unlink(missing_ok=True)


@pytest.mark.xfail(sys.platform == "win32", reason="Windows file locking differs")
def test_file_handle_stderr_error(tmp_path):
    """Test that stderr file handles also produce good error messages."""
    cassette_path = tmp_path / "test.yaml"

    with tempfile.NamedTemporaryFile(mode="w", delete=False) as log_file:
        log_file_path = log_file.name

        try:
            with SubprocessVCR(cassette_path, mode="record"):
                with pytest.raises(SubprocessVCRError) as exc_info:
                    subprocess.Popen(
                        ["echo", "error message"],
                        stdout=subprocess.PIPE,
                        stderr=log_file,  # File handle for stderr
                    )

            error_msg = str(exc_info.value)
            assert "stderr is a file object" in error_msg
            assert "Cannot record subprocess with file handle" in error_msg
            assert "Background processes redirect output to log files" in error_msg

        finally:
            Path(log_file_path).unlink(missing_ok=True)


def test_complex_object_serialization_error(tmp_path):
    """Test error handling for non-serializable objects."""
    cassette_path = tmp_path / "test.yaml"

    # Create a custom object that can't be serialized
    class CustomObject:
        def __init__(self):
            self.data = lambda x: x * 2  # Lambda can't be serialized

    with SubprocessVCR(cassette_path, mode="record"):
        # This should work initially (subprocess runs)
        proc = subprocess.run(["echo", "test"], capture_output=True, text=True)
        assert proc.returncode == 0

    # Now let's manually try to add a non-serializable interaction
    # to test the cassette save error handling
    vcr = SubprocessVCR(cassette_path, mode="reset")
    vcr._new_interactions = [
        {
            "args": ["echo", "test"],
            "kwargs": {"custom": CustomObject()},  # This will fail to serialize
            "returncode": 0,
            "stdout": "test",
            "stderr": "",
        }
    ]

    # This should fail when trying to save
    with pytest.raises(SubprocessVCRError) as exc_info:
        vcr._save_cassette()

    error_msg = str(exc_info.value)
    assert "YAML serialization failed" in error_msg
    assert "Common causes:" in error_msg


def test_early_detection_helps_debugging(tmp_path):
    """Test that early detection provides good context."""
    cassette_path = tmp_path / "test.yaml"

    def run_subprocess_with_file():
        """Inner function to test stack trace extraction."""
        with tempfile.NamedTemporaryFile(mode="w") as f:
            with SubprocessVCR(cassette_path, mode="record"):
                # This should fail immediately with context
                subprocess.Popen(["python", "-c", "print('hello')"], stdout=f)

    with pytest.raises(SubprocessVCRError) as exc_info:
        run_subprocess_with_file()

    error_msg = str(exc_info.value)
    # Should have a clear error message
    assert "Cannot record subprocess with file handle" in error_msg
    assert "stdout is a file object" in error_msg
    # Should provide solutions
    assert "Solutions:" in error_msg
    assert "subprocess.PIPE" in error_msg
