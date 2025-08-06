"""Test pytest status markers for VCR actions."""

import subprocess

import pytest


@pytest.mark.subprocess_vcr
def test_record_marker():
    """Test that should show 'r' when recording a new cassette."""
    result = subprocess.run(["echo", "Recording test"], capture_output=True, text=True)
    assert result.stdout == "Recording test\n"


@pytest.mark.subprocess_vcr
def test_reset_marker():
    """Test that should show 'R' when resetting a cassette."""
    result = subprocess.run(["echo", "Reset test"], capture_output=True, text=True)
    assert result.stdout == "Reset test\n"


@pytest.mark.subprocess_vcr
def test_replay_marker():
    """Test that should show '.' when replaying from cassette."""
    result = subprocess.run(["echo", "Replay test"], capture_output=True, text=True)
    assert result.stdout == "Replay test\n"


def test_no_vcr_marker():
    """Test without VCR should show normal '.'."""
    # This test doesn't use subprocess_vcr
    assert True
