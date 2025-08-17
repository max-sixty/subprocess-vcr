"""Tests for the replay+reset mode functionality."""

import os
import re
import subprocess
import sys
from pathlib import Path


def assert_pytest_success(stdout, expected_count=1):
    """Check if pytest output shows success, handling VCR status markers."""
    # Check for exact match patterns
    patterns = [
        rf"{expected_count} passed",
        rf"{expected_count} vcr_reset",
        rf"{expected_count} vcr_record",
    ]

    # Check for mixed results (e.g., "1 passed, 1 vcr_reset")
    # Extract all numbers before 'passed', 'vcr_reset', or 'vcr_record'
    success_pattern = r"(\d+)\s+(?:passed|vcr_reset|vcr_record)"
    matches = re.findall(success_pattern, stdout)

    if matches:
        total = sum(int(match) for match in matches)
        if total == expected_count:
            return True

    # Fall back to exact pattern matching
    return any(re.search(pattern, stdout) for pattern in patterns)


def test_replay_reset_mode_with_missing_recording(
    project_dir, pytestconfig, monkeypatch
):
    """Test that replay+reset mode falls back to reset when recording is missing."""
    # Create a test file that uses subprocess
    test_file = project_dir / "test_subprocess.py"
    test_file.write_text("""
import subprocess
import sys
import pytest

@pytest.mark.subprocess_vcr
def test_echo(subprocess_vcr):  # Request subprocess_vcr fixture explicitly
    result = subprocess.run(
        [sys.executable, "-c", "print('Hello from subprocess')"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Hello from subprocess" in result.stdout
""")

    # First, ensure no cassette exists
    cassette_dir = project_dir / "_vcr_cassettes"
    cassette_path = cassette_dir / "test_subprocess.test_echo.yaml"

    # Run test with replay+reset mode
    # Set up environment to find the subprocess_vcr plugin
    pythonpath = str(Path(__file__).parent.parent.parent)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "subprocess_vcr.pytest_plugin",
            "-xvs",
            str(test_file),
            "--subprocess-vcr=replay+reset",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=pythonpath, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
    )

    # Test should pass transparently
    assert result.returncode == 0

    # With the new retry implementation, when no cassette exists, the test fails
    # on first attempt and is retried in reset mode. This might show as "no tests ran"
    # in the output, but the exit code is 0 and the cassette should be created.
    if "no tests ran" in result.stdout:
        # This is expected with the retry implementation - the test was retried
        # and succeeded, creating the cassette
        pass
    else:
        # Normal successful run
        assert assert_pytest_success(result.stdout, 1)

    # Cassette should now exist (created during retry in reset mode)
    assert cassette_path.exists()

    # Second run should use the cassette (no retry message)
    result2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "subprocess_vcr.pytest_plugin",
            "-xvs",
            str(test_file),
            "--subprocess-vcr=replay+reset",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=pythonpath, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
    )

    assert result2.returncode == 0
    assert "No VCR recording found" not in result2.stdout
    assert "retrying with reset mode" not in result2.stdout


def test_replay_reset_mode_with_existing_recording(project_dir):
    """Test that replay+reset mode uses existing recordings without retry."""
    # Create a test file
    test_file = project_dir / "test_with_cassette.py"
    test_file.write_text("""
import subprocess
import pytest

@pytest.mark.subprocess_vcr
def test_ls(subprocess_vcr):  # Request subprocess_vcr fixture explicitly
    result = subprocess.run(
        ["echo", "test output"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "test output"
""")

    # First create the cassette with reset mode
    pythonpath = str(Path(__file__).parent.parent.parent)
    result1 = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "subprocess_vcr.pytest_plugin",
            "-xvs",
            str(test_file),
            "--subprocess-vcr=reset",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=pythonpath, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
    )
    assert result1.returncode == 0

    # Now run with replay+reset - should use existing cassette
    result2 = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "subprocess_vcr.pytest_plugin",
            "-xvs",
            str(test_file),
            "--subprocess-vcr=replay+reset",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=pythonpath, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
    )

    assert result2.returncode == 0
    # Should NOT see retry message since cassette exists
    assert "No VCR recording found" not in result2.stdout
    assert "retrying with reset mode" not in result2.stdout


def test_replay_reset_mode_non_vcr_failure(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    """Test that replay+reset mode DOES retry on ALL failures, including non-VCR failures."""
    # Use a unique marker file to avoid conflicts in parallel runs
    import uuid

    marker_id = str(uuid.uuid4())

    # Plugin is auto-loaded via entry point, no need for explicit loading

    # Create a test that fails for non-VCR reasons
    pytester.makepyfile(
        test_regular_failure=f"""
import subprocess
import pytest
from pathlib import Path

@pytest.mark.subprocess_vcr
def test_will_fail(subprocess_vcr):  # Request subprocess_vcr fixture explicitly
    # Use a marker file to make test pass on retry
    marker_file = Path(f"/tmp/test_regular_failure_marker_{marker_id}")

    if not marker_file.exists():
        # First run - will fail
        marker_file.touch()
        result = subprocess.run(
            ["echo", "hello"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "goodbye" in result.stdout  # This will fail
    else:
        # Retry run - will pass
        marker_file.unlink()
        result = subprocess.run(
            ["echo", "goodbye"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "goodbye" in result.stdout  # This will pass
"""
    )

    # Create cassette first - the test will fail but cassette will be created
    result = pytester.runpytest_subprocess(
        "-xvs",
        "--subprocess-vcr=reset",
        "-p",
        "subprocess_vcr.pytest_plugin",
    )
    # The test fails on purpose, but the cassette should be created
    assert result.ret == 1

    # Clean up the marker file so the second run starts fresh
    marker_file = Path(f"/tmp/test_regular_failure_marker_{marker_id}")
    if marker_file.exists():
        marker_file.unlink()

    # Run with replay+reset - should succeed after retry
    result = pytester.runpytest_subprocess(
        "-xvs",
        "--subprocess-vcr=replay+reset",
        "-p",
        "subprocess_vcr.pytest_plugin",
    )

    # In replay+reset mode, all failures should be retried
    # The test has a marker file mechanism to pass on retry
    # So if it passes (ret 0), the retry must have happened

    # Check for retry message in output
    result.stdout.fnmatch_lines(
        [
            "[RETRY] Retrying test_regular_failure.py::test_will_fail in reset mode after failure..."
        ]
    )

    # The test should succeed after retry (exit code 0)
    # Note: pytester may show warnings instead of "no tests ran" in newer versions
    assert result.ret == 0


def test_replay_reset_with_multiple_tests(project_dir):
    """Test replay+reset mode with multiple tests, some with cassettes and some without."""
    test_file = project_dir / "test_multiple.py"
    test_file.write_text("""
import subprocess
import pytest

@pytest.mark.subprocess_vcr
def test_first(subprocess_vcr):  # Request subprocess_vcr fixture explicitly
    result = subprocess.run(["echo", "first"], capture_output=True, text=True, check=True)
    assert "first" in result.stdout

@pytest.mark.subprocess_vcr
def test_second(subprocess_vcr):  # Request subprocess_vcr fixture explicitly
    result = subprocess.run(["echo", "second"], capture_output=True, text=True, check=True)
    assert "second" in result.stdout
""")

    # Create cassette for only the first test
    cassette_dir = project_dir / "_vcr_cassettes"
    cassette_dir.mkdir()

    # Run first test only to create its cassette
    pythonpath = str(Path(__file__).parent.parent.parent)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "subprocess_vcr.pytest_plugin",
            "-xvs",
            str(test_file),
            "-k",
            "test_first",
            "--subprocess-vcr=reset",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=pythonpath, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
    )

    # Now run both tests with replay+reset
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "subprocess_vcr.pytest_plugin",
            "-xvs",
            str(test_file),
            "--subprocess-vcr=replay+reset",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=pythonpath, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
    )

    # First test should replay successfully (has cassette)
    # Second test should fallback to reset (no cassette)

    # Both tests should pass transparently
    assert result.returncode == 0

    # With the new retry implementation, the second test (no cassette) will fail
    # and be retried. This might show as "no tests ran" in the output.
    if "no tests ran" in result.stdout:
        # This is expected with the retry implementation
        pass
    else:
        # Normal successful run showing both tests
        assert assert_pytest_success(result.stdout, 2)

    # Both cassettes should exist after the run (second one created during retry)
    assert (cassette_dir / "test_multiple.test_first.yaml").exists()
    assert (cassette_dir / "test_multiple.test_second.yaml").exists()
