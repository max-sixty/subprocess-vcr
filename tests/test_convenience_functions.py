"""Test subprocess convenience functions with VCR."""

import subprocess
import sys

import pytest


@pytest.mark.subprocess_vcr
@pytest.mark.xfail(sys.platform == "win32", reason="Windows shell quoting differs")
def test_getoutput_recording():
    """Test that subprocess.getoutput() is recorded and replayed correctly."""
    # Record a simple command
    output = subprocess.getoutput("echo 'Hello from getoutput'")
    assert output == "Hello from getoutput"

    # Try a command that fails
    output = subprocess.getoutput("echo 'Error' >&2; exit 1")
    # getoutput captures both stdout and stderr
    assert "Error" in output


@pytest.mark.subprocess_vcr
@pytest.mark.xfail(sys.platform == "win32", reason="Windows shell quoting differs")
def test_getstatusoutput_recording():
    """Test that subprocess.getstatusoutput() is recorded and replayed correctly."""
    # Record a successful command
    status, output = subprocess.getstatusoutput("echo 'Hello from getstatusoutput'")
    assert status == 0
    assert output == "Hello from getstatusoutput"

    # Try a command that fails
    status, output = subprocess.getstatusoutput("echo 'Error' >&2; exit 42")
    assert status == 42
    # getstatusoutput captures both stdout and stderr
    assert "Error" in output


if sys.version_info >= (3, 10):

    @pytest.mark.subprocess_vcr
    def test_getoutput_with_encoding():
        """Test getoutput with encoding parameter."""
        # This uses the encoding parameter introduced in Python 3.10
        output = subprocess.getoutput("echo 'UTF-8 test: café'", encoding="utf-8")  # type: ignore[call-arg,unused-ignore]
        assert "café" in output

    @pytest.mark.subprocess_vcr
    def test_getstatusoutput_with_encoding():
        """Test getstatusoutput with encoding parameter."""
        status, output = subprocess.getstatusoutput(
            "echo 'UTF-8 test: café'",
            encoding="utf-8",  # type: ignore[call-arg,unused-ignore]
        )
        assert status == 0
        assert "café" in output


@pytest.mark.subprocess_vcr
@pytest.mark.xfail(sys.platform == "win32", reason="Windows shell behavior differs")
def test_shell_special_characters():
    """Test that shell special characters work correctly."""
    # getoutput and getstatusoutput use shell=True
    output = subprocess.getoutput("echo $HOME | grep -o '/[^/]*$'")
    # Should get the last component of HOME path
    assert output.startswith("/")

    status, output = subprocess.getstatusoutput("echo 'test' | wc -c")
    assert status == 0
    # wc -c counts characters including newline
    assert output.strip() in ["5", "6"]  # Different platforms may vary
