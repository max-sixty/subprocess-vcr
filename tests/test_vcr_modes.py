"""Test different VCR recording modes."""

import subprocess
from pathlib import Path

import pytest

from subprocess_vcr import SubprocessVCR, SubprocessVCRError


class TestVCRModes:
    """Test different VCR recording modes."""

    def test_strict_mode(self, tmp_path):
        """Test that strict mode fails immediately if cassette doesn't exist."""
        cassette_path = tmp_path / "nonexistent.yaml"

        # Without strict mode - just warns
        SubprocessVCR(cassette_path, mode="replay", strict=False)
        assert not cassette_path.exists()

        # With strict mode - fails immediately
        with pytest.raises(ValueError, match="Cassette required in strict replay mode"):
            SubprocessVCR(cassette_path, mode="replay", strict=True)

    def test_mode_validation(self):
        """Test mode validation."""
        # Valid modes should work
        for mode in ["record", "reset", "replay", "disable"]:
            assert SubprocessVCR.validate_mode(mode) == mode

        # Invalid mode should fail
        with pytest.raises(ValueError, match="Invalid mode: invalid"):
            SubprocessVCR.validate_mode("invalid")

        # Also test through constructor
        with pytest.raises(ValueError, match="Invalid mode: bad_mode"):
            SubprocessVCR(Path("test.yaml"), mode="bad_mode")

    def test_record_mode_adds_new_recordings(self, tmp_path):
        """Test that 'record' mode adds new recordings to existing cassette."""
        cassette_path = tmp_path / "test_record.yaml"

        # First recording session
        vcr1 = SubprocessVCR(cassette_path, mode="record")
        vcr1.patch()

        result1 = subprocess.run(
            ["echo", "first"], capture_output=True, text=True, check=True
        )
        assert result1.stdout.strip() == "first"

        vcr1.unpatch()

        # Second session with record mode - should add new recording
        vcr2 = SubprocessVCR(cassette_path, mode="record")
        vcr2.patch()

        # Replay existing
        result2 = subprocess.run(
            ["echo", "first"], capture_output=True, text=True, check=True
        )
        assert result2.stdout.strip() == "first"

        # Record new
        result3 = subprocess.run(
            ["echo", "second"], capture_output=True, text=True, check=True
        )
        assert result3.stdout.strip() == "second"

        vcr2.unpatch()

        # Verify both interactions are saved
        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        assert len(data["interactions"]) == 2
        assert data["interactions"][0]["args"] == ["echo", "first"]
        assert data["interactions"][1]["args"] == ["echo", "second"]

    def test_reset_mode_replaces_existing(self, tmp_path):
        """Test that 'reset' mode always records, replacing existing cassettes."""
        cassette_path = tmp_path / "test_reset.yaml"

        # First recording session
        vcr1 = SubprocessVCR(cassette_path, mode="reset")
        vcr1.patch()

        result1 = subprocess.run(
            ["echo", "first"], capture_output=True, text=True, check=True
        )
        assert result1.stdout.strip() == "first"

        vcr1.unpatch()

        # Verify cassette was created
        assert cassette_path.exists()

        # Second recording session - should reset
        vcr2 = SubprocessVCR(cassette_path, mode="reset")
        vcr2.patch()

        result2 = subprocess.run(
            ["echo", "second"], capture_output=True, text=True, check=True
        )
        assert result2.stdout.strip() == "second"

        vcr2.unpatch()

        # Verify cassette only contains second recording (reset)
        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        assert len(data["interactions"]) == 1
        assert data["interactions"][0]["args"] == ["echo", "second"]

    def test_replay_mode_replay_only(self, tmp_path):
        """Test that 'replay' mode only replays, never records."""
        cassette_path = tmp_path / "test_replay.yaml"

        # First record with 'reset' mode
        vcr_record = SubprocessVCR(cassette_path, mode="reset")
        vcr_record.patch()

        result = subprocess.run(
            ["echo", "test"], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "test"

        vcr_record.unpatch()

        # Now use 'replay' mode - should replay
        vcr_replay = SubprocessVCR(cassette_path, mode="replay")
        vcr_replay.patch()

        result2 = subprocess.run(
            ["echo", "test"], capture_output=True, text=True, check=True
        )
        assert result2.stdout.strip() == "test"

        # Try a new command - should fail
        with pytest.raises(SubprocessVCRError, match="No recording found"):
            subprocess.run(["echo", "new"], capture_output=True, text=True, check=True)

        vcr_replay.unpatch()

    def test_disable_mode(self, tmp_path):
        """Test that 'disable' mode doesn't intercept anything."""
        cassette_path = tmp_path / "test_disable.yaml"

        vcr = SubprocessVCR(cassette_path, mode="disable")
        vcr.patch()

        # Should execute real subprocess
        result = subprocess.run(
            ["echo", "real"], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "real"

        vcr.unpatch()

        # No cassette should be created
        assert not cassette_path.exists()

    def test_mode_transitions(self, tmp_path):
        """Test transitioning between different modes."""
        cassette_path = tmp_path / "test_transitions.yaml"

        # Start with 'record' to create cassette
        vcr1 = SubprocessVCR(cassette_path, mode="record")
        vcr1.patch()
        subprocess.run(["echo", "initial"], capture_output=True, text=True, check=True)
        vcr1.unpatch()

        # Switch to 'replay' mode - should replay
        vcr2 = SubprocessVCR(cassette_path, mode="replay")
        vcr2.patch()
        result = subprocess.run(
            ["echo", "initial"], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "initial"
        vcr2.unpatch()

        # Switch to 'reset' mode - should replace
        vcr3 = SubprocessVCR(cassette_path, mode="reset")
        vcr3.patch()

        # Record new, overwriting old
        result = subprocess.run(
            ["echo", "new"], capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == "new"

        vcr3.unpatch()

        # Verify only new interaction exists
        import yaml

        with open(cassette_path) as f:
            data = yaml.safe_load(f)
        assert len(data["interactions"]) == 1
        assert data["interactions"][0]["args"] == ["echo", "new"]
