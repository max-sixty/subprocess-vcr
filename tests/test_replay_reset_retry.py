"""Test that replay+reset mode actually retries the entire test."""


def test_replay_reset_retries_entire_test_on_failure(isolated_pytester):
    """Test that replay+reset mode retries the entire test when it fails."""
    # Create a test file that will fail initially and pass on retry
    isolated_pytester.makepyfile("""
import subprocess
import pytest

@pytest.mark.subprocess_vcr
def test_retry_behavior(request):
    # Check if we're in retry mode by checking for the force mode attribute
    # This is set by our retry mechanism and persists across retry attempts
    is_retry = (
        hasattr(request.node, "_subprocess_vcr_force_mode")
        and request.node._subprocess_vcr_force_mode == "reset"
    )

    if not is_retry:
        # First run - run a command that will succeed
        result = subprocess.run(
            ["echo", "First run"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "First run"

        # Now fail the test intentionally
        pytest.fail("Intentional failure to trigger retry")
    else:
        # Retry run - succeed
        result = subprocess.run(
            ["echo", "Retry run"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "Retry run"
""")

    # Run test in replay+reset mode
    result = isolated_pytester.runpytest(
        "-xvs",
        "--subprocess-vcr=replay+reset",
    )

    # Should see retry message
    assert "[RETRY] Retrying" in result.stdout.str()

    # TODO: pytester shows "no tests ran" when tests are retried via pytest hooks
    # This is a known limitation where pytester doesn't properly capture the output
    # of retried tests. We verify success via exit code instead.
    # Due to pytester limitations with retried tests, we see "no tests ran"
    # but the test actually passed on retry (exit code 0)
    assert result.ret == 0


def test_replay_reset_with_cassette_mismatch(isolated_pytester):
    """Test retry when cassette doesn't match commands."""
    # Create an initial cassette with a different command
    cassette_dir = isolated_pytester.path / "_vcr_cassettes"
    cassette_dir.mkdir(exist_ok=True)
    cassette_path = cassette_dir / "test_cassette_mismatch.test_mismatch.yaml"

    # Create a cassette with a different command
    cassette_path.write_text("""
cassette_version: 1
metadata:
  test_name: test_mismatch
entries:
- args: ["echo", "wrong command"]
  returncode: 0
  stdout: "wrong command\\n"
  stderr: ""
""")

    # Create test that expects a different command
    isolated_pytester.makepyfile(
        test_cassette_mismatch="""
import subprocess
import pytest

@pytest.mark.subprocess_vcr
def test_mismatch(request):
    # This will cause a mismatch in replay mode
    result = subprocess.run(
        ["echo", "expected command"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "expected command"
"""
    )

    # Run test in replay+reset mode
    result = isolated_pytester.runpytest(
        "-xvs",
        "--subprocess-vcr=replay+reset",
        "test_cassette_mismatch.py",
    )

    # For this test, the mismatch happens at VCR level (not test failure)
    # So replay+reset mode falls back to reset without pytest retry

    # Check exit code - 0 means success
    assert result.ret == 0

    # TODO: pytester doesn't capture subprocess-vcr's internal test execution properly
    # When VCR falls back from replay to reset mode, pytester may report "no tests ran"
    # even though the test actually executed. This is because the fallback happens
    # at the VCR level, not the pytest level.
    # With subprocess execution, we verify the test ran by checking the cassette was updated
    updated_content = cassette_path.read_text()
    assert "expected command" in updated_content


def test_replay_reset_with_corrupted_cassette(isolated_pytester):
    """Test that corrupted cassettes are handled by VCR fallback."""
    # Create a corrupted cassette
    cassette_dir = isolated_pytester.path / "_vcr_cassettes"
    cassette_dir.mkdir(exist_ok=True)
    cassette_path = cassette_dir / "test_corrupted.test_with_corruption.yaml"

    # Write invalid YAML
    cassette_path.write_text("This is not valid YAML: {{{")

    # Create test
    isolated_pytester.makepyfile(
        test_corrupted="""
import subprocess
import pytest

@pytest.mark.subprocess_vcr
def test_with_corruption():
    # This should succeed because replay+reset will fallback to reset mode
    result = subprocess.run(
        ["echo", "Success despite corruption"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "Success despite corruption"
"""
    )

    # Run test in replay+reset mode
    result = isolated_pytester.runpytest(
        "-xvs",
        "--subprocess-vcr=replay+reset",
        "test_corrupted.py",
    )

    # Corrupted cassette triggers VCR-level fallback, not pytest retry
    # Check exit code - 0 means success
    assert result.ret == 0

    # TODO: Same pytester limitation as above - VCR-level fallbacks aren't captured
    # With subprocess execution, we verify the test ran by checking the cassette was updated
    assert cassette_path.exists()
    new_content = cassette_path.read_text()
    assert "Success despite corruption" in new_content
    assert "version: 1" in new_content  # Valid YAML now
