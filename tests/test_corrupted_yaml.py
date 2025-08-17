"""Tests for handling corrupted YAML cassettes.

Assertion Pattern Guidelines:
- Use result.assert_outcomes(errors=1) for YAML parsing errors (happen during setup)
- Use direct string checking for VCR-specific status markers
- Check both stdout and stderr for error messages since location varies
"""

import yaml


def assert_in_output(result, text):
    """Check if text appears in either stdout or stderr.

    Error messages can appear in either stream depending on pytest configuration.
    """
    return text in result.stdout.str() or text in result.stderr.str()


def create_corrupted_cassette_test(pytester, test_name):
    """Create a test file and corrupted cassette for testing error handling.

    Args:
        pytester: The pytester fixture
        test_name: Name to use for the test file and cassette

    Returns:
        Path to the created cassette file
    """
    # Create a test file
    pytester.makepyfile("""
import subprocess
import pytest

@pytest.mark.subprocess_vcr
def test_with_corrupted_cassette():
    result = subprocess.run(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout.strip() == "hello"
""")

    # Create cassette directory and corrupted cassette
    cassette_dir = pytester.path / "_vcr_cassettes"
    cassette_dir.mkdir()
    cassette_path = cassette_dir / f"{test_name}.test_with_corrupted_cassette.yaml"

    # Write invalid YAML (missing colon after key)
    cassette_path.write_text(
        """interactions:
  - request
      command: ["echo", "hello"]
    response:
      stdout: "hello\\n"
"""
    )

    return cassette_path


def test_corrupted_yaml_replay_mode_fails(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    """Test that replay mode fails with clear error on corrupted YAML."""
    create_corrupted_cassette_test(pytester, "test_corrupted_yaml_replay_mode_fails")

    # Run test in replay mode - should fail with clear error
    result = pytester.runpytest_subprocess(
        "-p",
        "subprocess_vcr.pytest_plugin",
        "-xvs",
        "--subprocess-vcr=replay",
    )

    # Setup errors: YAML parsing fails during test setup, not execution
    result.assert_outcomes(errors=1)
    # Error location varies: Check both stdout and stderr
    assert assert_in_output(result, "Failed to load VCR cassette")


def test_corrupted_yaml_reset_mode_succeeds(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    """Test that reset mode succeeds even with corrupted YAML."""
    cassette_path = create_corrupted_cassette_test(
        pytester, "test_corrupted_yaml_reset_mode_succeeds"
    )

    # Run test in reset mode - should succeed and replace cassette
    result = pytester.runpytest_subprocess(
        "-p",
        "subprocess_vcr.pytest_plugin",
        "-xvs",
        "--subprocess-vcr=reset",
    )

    # VCR-specific: Reset mode shows custom status marker
    assert "1 vcr_reset" in result.stdout.str()

    # Verify cassette was replaced with valid YAML
    with open(cassette_path) as f:
        data = yaml.safe_load(f)
    assert "interactions" in data
    assert len(data["interactions"]) == 1


def test_corrupted_yaml_record_mode_fails(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    """Test that record mode fails with clear error on corrupted YAML."""
    create_corrupted_cassette_test(pytester, "test_corrupted_yaml_record_mode_fails")

    # Run test in record mode - should fail with clear error
    result = pytester.runpytest_subprocess(
        "-p",
        "subprocess_vcr.pytest_plugin",
        "-xvs",
        "--subprocess-vcr=record",
    )

    # Setup errors: YAML parsing fails during test setup, not execution
    result.assert_outcomes(errors=1)
    # Error location varies: Check both stdout and stderr
    assert assert_in_output(result, "Failed to load VCR cassette")


def test_replay_reset_with_corrupted_yaml(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    """Test that replay+reset mode falls back to reset when YAML is corrupted."""
    cassette_path = create_corrupted_cassette_test(
        pytester, "test_replay_reset_with_corrupted_yaml"
    )

    # Run test in replay+reset mode
    result = pytester.runpytest_subprocess(
        "-p",
        "subprocess_vcr.pytest_plugin",
        "-xvs",
        "--subprocess-vcr=replay+reset",
    )

    # With the new retry implementation, tests that fail during setup due to
    # corrupted YAML are retried in reset mode. The test should pass but
    # pytester might show "no tests ran" due to how it captures the retry.
    # Check for success (exit code 0) which indicates the retry worked.
    assert result.ret == 0, (
        f"Test should succeed after retry, got exit code {result.ret}"
    )

    # The retry happens transparently, so we might see "no tests ran" in output
    # but the cassette should be replaced with valid YAML

    # Verify cassette was replaced with valid YAML - this is the key test
    with open(cassette_path) as f:
        data = yaml.safe_load(f)
    assert "interactions" in data
    assert len(data["interactions"]) == 1

    # The test passed (exit code 0) and cassette was replaced - retry worked!
