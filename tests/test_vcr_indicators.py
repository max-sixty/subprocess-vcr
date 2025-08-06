"""Test that VCR preserves subprocess output exactly without modification."""

import subprocess

import pytest

from subprocess_vcr import SubprocessVCR


class TestVCRIndicators:
    """Test that VCR preserves subprocess output without modification."""

    def test_vcr_indicator_not_in_stderr(self, tmp_path):
        """Test that VCR does NOT modify stderr output."""
        cassette = tmp_path / "error_with_stderr.yaml"

        # Record a command that returns non-zero with stderr
        with SubprocessVCR(cassette, mode="reset"):
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                subprocess.run(
                    ["ls", "/nonexistent/path"], capture_output=True, check=True
                )

        # Save the original stderr for comparison
        original_stderr = exc_info.value.stderr

        # Replay and verify stderr is unchanged
        with SubprocessVCR(cassette, mode="replay"):
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                subprocess.run(
                    ["ls", "/nonexistent/path"], capture_output=True, check=True
                )

        # Replayed error should have EXACT same stderr (no VCR indicator)
        assert exc_info.value.stderr == original_stderr
        assert b"[Replayed from VCR cassette:" not in exc_info.value.stderr

    def test_vcr_preserves_empty_stderr(self, tmp_path):
        """Test that VCR preserves empty stderr exactly."""
        cassette = tmp_path / "error_no_stderr.yaml"

        # Create a cassette with non-zero exit but empty stderr
        cassette.write_text("""version: 1
interactions:
  - args: ["false"]
    kwargs:
      stdout: PIPE
      stderr: PIPE
    stdout: ""
    stderr: ""
    returncode: 1
    duration: 0.001
""")

        # Replay - should preserve empty stderr without modification
        with SubprocessVCR(cassette, mode="replay"):
            result = subprocess.run(["false"], capture_output=True)

        assert result.returncode == 1
        assert result.stderr == b""  # Exact empty bytes, no indicator

    def test_no_vcr_indicator_on_success(self, tmp_path):
        """Test that VCR indicator is not added for successful commands."""
        cassette = tmp_path / "success.yaml"

        # Record a successful command
        with SubprocessVCR(cassette, mode="reset"):
            result = subprocess.run(["echo", "hello"], capture_output=True, text=True)

        assert result.returncode == 0

        # Replay - should not add VCR indicator for success
        with SubprocessVCR(cassette, mode="replay"):
            result = subprocess.run(["echo", "hello"], capture_output=True, text=True)

        assert result.returncode == 0
        assert result.stderr == ""  # No indicator added

    def test_vcr_preserves_text_mode_stderr(self, tmp_path):
        """Test VCR preserves stderr in text mode without modification."""
        cassette = tmp_path / "text_error.yaml"

        # Record in text mode
        with SubprocessVCR(cassette, mode="reset"):
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                subprocess.run(
                    ["ls", "/nonexistent"], capture_output=True, check=True, text=True
                )

        # Save original stderr
        original_stderr = exc_info.value.stderr

        # Replay in text mode
        with SubprocessVCR(cassette, mode="replay"):
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                subprocess.run(
                    ["ls", "/nonexistent"], capture_output=True, check=True, text=True
                )

        # Verify stderr is unchanged
        assert exc_info.value.stderr == original_stderr
        assert "[Replayed from VCR cassette:" not in exc_info.value.stderr
        assert isinstance(exc_info.value.stderr, str)  # Should be string in text mode

    def test_vcr_preserves_stderr_without_check(self, tmp_path):
        """Test VCR preserves stderr even without check=True."""
        cassette = tmp_path / "no_check.yaml"

        # Record a command that returns non-zero without check=True
        with SubprocessVCR(cassette, mode="reset"):
            result = subprocess.run(["ls", "/nonexistent"], capture_output=True)

        assert result.returncode != 0
        original_stderr = result.stderr

        # Replay without check=True
        with SubprocessVCR(cassette, mode="replay"):
            result = subprocess.run(["ls", "/nonexistent"], capture_output=True)

        # Should have exact same stderr (no VCR indicator)
        assert result.stderr == original_stderr
        assert b"[Replayed from VCR cassette:" not in result.stderr

    def test_vcr_handles_missing_stderr_key(self, tmp_path):
        """Test VCR handles missing stderr key correctly."""
        cassette = tmp_path / "no_stderr_key.yaml"

        # Create a cassette without stderr key (simulating old recordings)
        cassette.write_text("""version: 1
interactions:
  - args: ["false"]
    kwargs:
      stdout: PIPE
    stdout: ""
    returncode: 1
    duration: 0.001
""")

        # Replay - should return None for stderr when key is missing
        with SubprocessVCR(cassette, mode="replay"):
            result = subprocess.run(["false"], capture_output=True)

        assert result.returncode == 1
        assert result.stderr is None  # No stderr key means None, not empty bytes


@pytest.mark.subprocess_vcr
class TestVCRPytestIntegration:
    """Test that VCR integrates with pytest reporting correctly."""

    @pytest.mark.xfail(
        reason="Intentionally failing test to demonstrate VCR pytest integration"
    )
    def test_vcr_failure_shows_in_pytest_report(self):
        """Test that pytest shows VCR info in failure reports.

        This test will fail intentionally to demonstrate the pytest integration.
        To see the VCR context in the failure report, run:
        pytest subprocess_vcr/tests/test_vcr_indicators.py::TestVCRPytestIntegration::test_vcr_failure_shows_in_pytest_report -v
        """
        # This test uses the subprocess_vcr marker, so it will record/replay
        result = subprocess.run(["false"], capture_output=True)

        # This assertion will fail, demonstrating the VCR context in pytest output
        assert result.returncode == 0, "Expected success but command failed"

    def test_vcr_success_no_extra_output(self):
        """Test that successful tests don't show VCR context."""
        # Record/replay a successful command
        result = subprocess.run(["echo", "hello"], capture_output=True, text=True)

        assert result.returncode == 0
        assert result.stdout.strip() == "hello"
