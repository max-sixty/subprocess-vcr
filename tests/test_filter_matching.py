"""Test that filters work correctly during command matching."""

import subprocess
import sys

import pytest

from subprocess_vcr import SubprocessVCR
from subprocess_vcr.filters import PathFilter


@pytest.mark.xfail(sys.platform == "win32", reason="Windows path separators differ")
def test_cwd_filter_normalizes_for_matching(tmp_path):
    """Test that PathFilter normalizes CWD paths during matching, not just recording."""
    cassette_path = tmp_path / "test_matching.yaml"

    # First, record with PathFilter from one directory
    record_dir = tmp_path / "record_dir"
    record_dir.mkdir()
    config_file = record_dir / "config.yaml"
    config_file.write_text("test: true")

    with SubprocessVCR(cassette_path, mode="reset", filters=[PathFilter()]):
        # Record from record_dir
        result = subprocess.run(
            ["cat", str(config_file)],
            capture_output=True,
            text=True,
            cwd=str(record_dir),
        )
        assert result.returncode == 0

    # Verify the cassette has normalized paths
    import yaml

    with open(cassette_path) as f:
        data = yaml.safe_load(f)

    # The recorded command should have <CWD>/config.yaml
    assert data["interactions"][0]["args"][1] == "<CWD>/config.yaml"
    assert data["interactions"][0]["kwargs"]["cwd"] == "<CWD>"

    # Now replay from a different directory - this should still match!
    replay_dir = tmp_path / "replay_dir"
    replay_dir.mkdir()
    different_config = replay_dir / "config.yaml"
    different_config.write_text("different content")

    with SubprocessVCR(cassette_path, mode="replay", filters=[PathFilter()]):
        # This should match even though the actual path is different
        result = subprocess.run(
            ["cat", str(different_config)],
            capture_output=True,
            text=True,
            cwd=str(replay_dir),
        )
        assert result.returncode == 0
        # Should get the recorded output, not the actual file content
        assert "test: true" in result.stdout


@pytest.mark.xfail(sys.platform == "win32", reason="Windows path normalization differs")
def test_path_filter_normalizes_for_matching(tmp_path):
    """Test that PathFilter normalizes paths during matching."""
    cassette_path = tmp_path / "test_path_matching.yaml"

    # Record with PathFilter
    with SubprocessVCR(cassette_path, mode="reset", filters=[PathFilter()]):
        # Use a path that will be normalized
        result = subprocess.run(
            ["echo", str(tmp_path / "test.txt")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    # Verify normalization in cassette
    import yaml

    with open(cassette_path) as f:
        data = yaml.safe_load(f)

    # Should be normalized to <TMP>
    recorded_arg = data["interactions"][0]["args"][1]
    assert "<TMP>" in recorded_arg

    # Now replay with the same path structure but it should still match
    # because both will be normalized to the same pattern
    with SubprocessVCR(cassette_path, mode="replay", filters=[PathFilter()]):
        # Use the exact same path - it should match after normalization
        result = subprocess.run(
            ["echo", str(tmp_path / "test.txt")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0


def test_multiple_filters_normalize_for_matching(tmp_path):
    """Test that multiple filters work together during matching."""
    cassette_path = tmp_path / "test_multi_filter.yaml"

    # Set up a scenario that uses both CWD and path normalization
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    work_file = work_dir / "file.txt"
    work_file.write_text("test")

    # Record with PathFilter (which now includes CWD normalization)
    filters: list = [PathFilter()]

    with SubprocessVCR(cassette_path, mode="reset", filters=filters):
        # Command that includes both cwd-relative and absolute paths
        result = subprocess.run(
            ["echo", str(work_file), "relative.txt"],
            capture_output=True,
            text=True,
            cwd=str(work_dir),
        )
        assert result.returncode == 0

    # Now replay from a totally different location
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_file = other_dir / "file.txt"
    other_file.write_text("test")

    with SubprocessVCR(cassette_path, mode="replay", filters=filters):
        # Different paths but should still match after normalization
        result = subprocess.run(
            ["echo", str(other_file), "relative.txt"],
            capture_output=True,
            text=True,
            cwd=str(other_dir),
        )
        assert result.returncode == 0


@pytest.mark.xfail(sys.platform == "win32", reason="Windows path separators differ")
def test_no_match_shows_normalized_command(tmp_path):
    """Test that error messages show both original and normalized commands."""
    cassette_path = tmp_path / "test_error.yaml"

    # Create a file to normalize
    test_file = tmp_path / "file.txt"
    test_file.write_text("test")

    # Record a simple command
    with SubprocessVCR(cassette_path, mode="reset", filters=[PathFilter()]):
        subprocess.run(
            ["echo", "hello"],
            capture_output=True,
            cwd=str(tmp_path),
        )

    # Try to match a different command that will fail
    with pytest.raises(Exception) as exc_info:
        with SubprocessVCR(cassette_path, mode="replay", filters=[PathFilter()]):
            subprocess.run(
                ["cat", str(test_file)],
                capture_output=True,
                cwd=str(tmp_path),
            )

    # Error should show both original and normalized commands
    error_msg = str(exc_info.value)
    assert "Actual command:" in error_msg
    assert "Normalized command" in error_msg
    assert "<CWD>/file.txt" in error_msg
