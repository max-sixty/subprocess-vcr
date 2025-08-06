"""Test that filters don't mutate original interaction data."""

from __future__ import annotations

import subprocess
from typing import Any

from subprocess_vcr import SubprocessVCR
from subprocess_vcr.filters import PathFilter


def test_filters_dont_mutate_original_interaction(tmp_path):
    """Test that applying filters doesn't mutate the original interaction dict."""
    # Create a test interaction with paths that PathFilter will normalize
    original_interaction: dict[str, Any] = {
        "args": ["echo", "/tmp/pytest-of-user/pytest-123/test_foo0/file.txt"],
        "kwargs": {
            "cwd": "/tmp/pytest-of-user/pytest-123/test_foo0",
            "env": {"TMPDIR": "/tmp/pytest-of-user/pytest-123"},
            "stdout": subprocess.PIPE,
        },
        "returncode": 0,
        "stdout": "Output from /tmp/pytest-of-user/pytest-123/test_foo0/file.txt",
        "stderr": "",
    }

    # Create a vcr instance with PathFilter
    cassette_path = tmp_path / "test.yaml"
    vcr = SubprocessVCR(cassette_path)
    vcr.filters = [PathFilter()]

    # Apply filters (should create a copy internally)
    filtered: dict[str, Any] = vcr._apply_filters_before_record(original_interaction)

    # Original should be unchanged
    assert original_interaction["args"] == [
        "echo",
        "/tmp/pytest-of-user/pytest-123/test_foo0/file.txt",
    ]
    assert (
        original_interaction["kwargs"]["cwd"]
        == "/tmp/pytest-of-user/pytest-123/test_foo0"
    )
    assert (
        original_interaction["kwargs"]["env"]["TMPDIR"]
        == "/tmp/pytest-of-user/pytest-123"
    )
    assert (
        original_interaction["stdout"]
        == "Output from /tmp/pytest-of-user/pytest-123/test_foo0/file.txt"
    )

    # Filtered should have replacements
    # Since cwd is the test directory, paths under it get normalized to <CWD>/...
    assert filtered["args"] == ["echo", "<CWD>/file.txt"]
    assert filtered["kwargs"]["cwd"] == "<CWD>"
    assert filtered["stdout"] == "Output from <CWD>/file.txt"


def test_playback_filters_dont_mutate_cassette_data(tmp_path):
    """Test that playback filters don't mutate the cassette interaction."""
    # Create a cassette interaction (as loaded from file)
    cassette_interaction: dict[str, Any] = {
        "args": ["echo", "<HOME>/test"],
        "kwargs": {
            "cwd": "<HOME>/project",
            "stdout": subprocess.PIPE,
        },
        "returncode": 0,
        "stdout": "Output from <HOME>/test",
    }

    # Create a vcr instance
    cassette_path = tmp_path / "test.yaml"
    vcr = SubprocessVCR(cassette_path)
    vcr.filters = [
        PathFilter()
    ]  # PathFilter doesn't modify on playback, but test anyway

    # Apply playback filters
    filtered: dict[str, Any] = vcr._apply_filters_before_playback(cassette_interaction)

    # Original cassette data should be unchanged
    assert cassette_interaction["args"] == ["echo", "<HOME>/test"]
    assert cassette_interaction["kwargs"]["cwd"] == "<HOME>/project"
    assert cassette_interaction["stdout"] == "Output from <HOME>/test"

    # In this case, filtered should be the same (PathFilter doesn't have before_playback)
    assert filtered["args"] == ["echo", "<HOME>/test"]
    assert filtered["kwargs"]["cwd"] == "<HOME>/project"


def test_multiple_filters_dont_interfere(tmp_path):
    """Test that multiple filters don't interfere with each other due to mutation."""
    from subprocess_vcr.filters import RedactFilter

    # Create interaction with sensitive data and pytest paths
    original_interaction: dict[str, Any] = {
        "args": [
            "curl",
            "-H",
            "Authorization: Bearer secret123",
            "/tmp/pytest-of-user/pytest-123/api",
        ],
        "kwargs": {"cwd": "/tmp/pytest-of-user/pytest-123/test_api0"},
        "returncode": 0,
        "stdout": "Response from /tmp/pytest-of-user/pytest-123/api",
    }

    # Create vcr with multiple filters
    cassette_path = tmp_path / "test.yaml"
    vcr = SubprocessVCR(cassette_path)
    vcr.filters = [
        PathFilter(),  # Should replace pytest paths
        RedactFilter(patterns=[r"Bearer \w+"]),  # Should redact token
    ]

    # Apply filters
    filtered: dict[str, Any] = vcr._apply_filters_before_record(original_interaction)

    # Original should be completely unchanged
    assert original_interaction["args"] == [
        "curl",
        "-H",
        "Authorization: Bearer secret123",
        "/tmp/pytest-of-user/pytest-123/api",
    ]
    assert (
        original_interaction["kwargs"]["cwd"]
        == "/tmp/pytest-of-user/pytest-123/test_api0"
    )

    # Filtered should have both filters applied
    assert "<TMP>" in str(filtered["args"])  # Path replaced
    assert "Bearer secret123" not in str(filtered["args"])  # Token redacted
    assert "REDACTED" in str(filtered["args"]) or "***" in str(filtered["args"])
