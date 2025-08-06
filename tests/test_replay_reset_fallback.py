"""Test replay+reset mode fallback behavior."""

import subprocess
import sys

import pytest


class TestReplayResetFallback:
    """Test that replay+reset falls back to reset on any failure."""

    @pytest.mark.subprocess_vcr
    def test_fallback_on_no_recording(self, tmp_path):
        """Test fallback when no recording exists."""
        # This test should pass even though no cassette exists
        # because replay+reset should fall back to reset mode
        result = subprocess.run(
            [sys.executable, "-c", "print('hello fallback')"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "hello fallback" in result.stdout

    @pytest.mark.subprocess_vcr
    def test_fallback_on_mismatched_command(self, tmp_path):
        """Test fallback when command doesn't match recording."""
        # First run to create a cassette with one command
        subprocess.run(
            [sys.executable, "-c", "print('first command')"],
            capture_output=True,
            text=True,
        )

        # Second run with different command should fall back to reset
        # instead of failing
        result = subprocess.run(
            [sys.executable, "-c", "print('different command')"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "different command" in result.stdout

    @pytest.mark.subprocess_vcr
    def test_multiple_fallbacks_in_same_test(self):
        """Test that once in reset mode, it stays in reset mode."""
        # First command - no recording, should fall back to reset
        result1 = subprocess.run(
            ["echo", "fallback1"],
            capture_output=True,
            text=True,
        )
        assert result1.returncode == 0
        assert "fallback1" in result1.stdout

        # Second command - should also use reset mode (not try replay again)
        result2 = subprocess.run(
            ["echo", "fallback2"],
            capture_output=True,
            text=True,
        )
        assert result2.returncode == 0
        assert "fallback2" in result2.stdout

    @pytest.mark.subprocess_vcr
    def test_fallback_with_path_matching(self, project_dir):
        """Test fallback works with path filtering."""
        # Create a test script
        script = project_dir / "test_script.py"
        script.write_text("print('path matching test')")

        # Run the script - should work even with no recording
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "path matching test" in result.stdout
