"""Test process control methods (terminate, kill) in subprocess VCR."""

import subprocess
import sys
import time

import pytest

from subprocess_vcr import SubprocessVCR


class TestProcessControl:
    """Test terminate() and kill() methods."""

    def test_terminate_recording(self, tmp_path):
        """Test that terminate() works during recording."""
        cassette = tmp_path / "terminate_recording.yaml"

        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Give process time to start
        time.sleep(0.1)

        # Terminate should work
        proc.terminate()

        # Wait for termination
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pytest.fail("Process did not terminate within timeout")

        vcr.unpatch()

        # Process should have been terminated
        # Return code varies by platform: -15 (SIGTERM) on Unix, 1 on Windows
        assert proc.returncode in [-15, 1, 15, 143]  # 143 = 128 + 15

    def test_kill_recording(self, tmp_path):
        """Test that kill() works during recording."""
        cassette = tmp_path / "kill_recording.yaml"

        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Give process time to start
        time.sleep(0.1)

        # Kill should work
        proc.kill()

        # Wait for termination
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pytest.fail("Process did not die within timeout")

        vcr.unpatch()

        # Process should have been killed
        # Return code varies by platform: -9 (SIGKILL) on Unix, 1 on Windows
        assert proc.returncode in [-9, 1, 9, 137]  # 137 = 128 + 9

    def test_terminate_replay(self, tmp_path):
        """Test that terminate() works during replay."""
        cassette = tmp_path / "terminate_replay.yaml"

        # First record a terminated process
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; print('Started'); time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        time.sleep(0.1)
        proc.terminate()
        stdout_rec, stderr_rec = proc.communicate(timeout=5)
        returncode_rec = proc.returncode

        vcr.unpatch()

        # Now replay and verify terminate() doesn't error
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; print('Started'); time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Terminate should not error in replay mode
        proc.terminate()

        # Should return recorded values
        stdout, stderr = proc.communicate()

        vcr.unpatch()

        assert proc.returncode == returncode_rec
        assert stdout == stdout_rec
        # VCR should NOT modify stderr output
        assert stderr == stderr_rec

    def test_subprocess_run_with_timeout(self, tmp_path):
        """Test that subprocess.run with timeout works correctly."""
        cassette = tmp_path / "run_timeout.yaml"

        # Record a timeout scenario
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        with pytest.raises(subprocess.TimeoutExpired) as exc_info:
            subprocess.run(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                timeout=0.1,
                capture_output=True,
                text=True,
            )

        vcr.unpatch()

        # The TimeoutExpired exception should have been raised
        assert exc_info.value.timeout == 0.1
        # On some platforms the command might be modified
        assert "sleep" in str(exc_info.value.cmd)

    @pytest.mark.subprocess_vcr
    def test_process_control_with_marker(self):
        """Test process control works with pytest marker."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Give process time to start
        time.sleep(0.1)

        # Both methods should work without errors
        proc.terminate()
        proc.kill()  # Can call both, second is no-op if process already dead

        # Wait for process to finish
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pytest.fail("Process did not terminate")

        # Should have a return code indicating termination
        assert proc.returncode is not None
        assert proc.returncode != 0  # Should not be normal exit
