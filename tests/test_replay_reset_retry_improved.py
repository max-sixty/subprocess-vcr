"""Improved tests for replay+reset retry functionality."""


def test_replay_reset_retries_with_environment_tracking(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    """Test retry detection using environment variables for state tracking."""
    # Create a test that uses environment variables to track retry state
    pytester.makepyfile("""
import os
import subprocess
import pytest

@pytest.mark.subprocess_vcr
def test_with_env_tracking(request):
    # TODO: Using environment variables for retry detection is not ideal
    # We need this because pytester runs tests in a subprocess where we can't
    # easily share state between retry attempts. A better solution would be
    # to have subprocess-vcr provide a proper API for detecting retries.
    # Use environment variable to detect retry - this is safe for parallel execution
    retry_key = f"SUBPROCESS_VCR_RETRY_{os.getpid()}"
    retry_count = int(os.environ.get(retry_key, "0"))

    if retry_count == 0:
        # First run - set counter and fail
        os.environ[retry_key] = "1"

        result = subprocess.run(
            ["echo", "First run"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "First run"

        # Fail to trigger retry
        pytest.fail("Intentional failure to trigger retry")
    else:
        # Retry run - clean up and succeed
        del os.environ[retry_key]

        result = subprocess.run(
            ["echo", "Retry run"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "Retry run"
""")

    # Run test in replay+reset mode
    result = pytester.runpytest_subprocess(
        "-p",
        "subprocess_vcr.pytest_plugin",
        "-xvs",
        "--subprocess-vcr=replay+reset",
    )

    # Should see retry message
    assert "[RETRY] Retrying" in result.stdout.str()

    # TODO: Same pytester limitation - "no tests ran" may appear for retried tests
    # Test should pass after retry
    assert result.ret == 0


def test_replay_reset_with_dynamic_commands(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    """Test that replay+reset handles dynamic command changes correctly."""
    # First, create a cassette with an initial command
    cassette_dir = pytester.path / "_vcr_cassettes"
    cassette_dir.mkdir(exist_ok=True)
    cassette_path = cassette_dir / "test_dynamic.test_changing_commands.yaml"

    # Create initial cassette
    cassette_path.write_text("""
cassette_version: 1
metadata:
  test_name: test_changing_commands
entries:
- args: ["echo", "original"]
  returncode: 0
  stdout: "original\\n"
  stderr: ""
""")

    # Create test that runs different commands based on cassette existence
    pytester.makepyfile(
        test_dynamic="""
import subprocess
import pytest
from pathlib import Path

@pytest.mark.subprocess_vcr
def test_changing_commands():
    # Check if cassette has been reset (will have different content after retry)
    cassette_path = Path(__file__).parent / "_vcr_cassettes" / "test_dynamic.test_changing_commands.yaml"

    # Run a different command than what's in the original cassette
    # This will trigger a retry in replay+reset mode
    result = subprocess.run(
        ["echo", "updated command"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "updated command"
"""
    )

    # Run test in replay+reset mode
    result = pytester.runpytest(
        "-p",
        "subprocess_vcr.pytest_plugin",
        "-xvs",
        "--subprocess-vcr=replay+reset",
        "test_dynamic.py",
    )

    # Command mismatch triggers VCR-level fallback, not pytest retry
    # Check exit code - 0 means success
    assert result.ret == 0

    # TODO: pytester doesn't properly capture VCR-level fallback execution
    # Due to pytester limitations with subprocess-vcr, we might see "no tests ran"
    stdout = result.stdout.str()

    if "no tests ran" in stdout:
        # TODO: Verifying cassette updates as a proxy for test execution is fragile
        # A better approach would be to have subprocess-vcr report its actions
        # in a way that pytester can capture
        # Verify the cassette was updated as proof test ran
        updated_cassette = cassette_path.read_text()
        assert "updated command" in updated_cassette
        assert "original" not in updated_cassette  # Original was replaced
    else:
        # Normal case
        assert "1 passed" in stdout
