"""Light tests for subprocess VCR core functionality."""

import subprocess

import pytest
import yaml

from subprocess_vcr import SubprocessVCR, SubprocessVCRError

# Note: These tests don't use @pytest.mark.subprocess_vcr because they manage
# VCR instances manually to test different modes and configurations


class TestRecording:
    """Test recording functionality."""

    def test_record_simple_command(self, tmp_path):
        """Test basic recording of a simple echo command."""
        cassette = tmp_path / "test.yaml"
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        subprocess.run(["echo", "hello"], capture_output=True, text=True)

        vcr.unpatch()

        # Verify cassette was created
        assert cassette.exists()

        # Verify basic structure
        with open(cassette) as f:
            data = yaml.safe_load(f)

        assert data["version"] == 1
        assert len(data["interactions"]) == 1
        assert data["interactions"][0]["stdout"] == "hello\n"
        assert data["interactions"][0]["returncode"] == 0

    def test_metadata_recording(self, tmp_path):
        """Test that metadata is saved in cassettes when provided."""
        cassette_path = tmp_path / "test.yaml"
        metadata = {
            "test_name": "test_metadata_recording",
            "recorded_at": "2024-01-15T10:30:00Z",
            "python_version": "3.11.0",
            "platform": "Linux-5.10.0",
        }

        vcr = SubprocessVCR(cassette_path, mode="reset", metadata=metadata)
        vcr.patch()

        # Record a simple command
        result = subprocess.run(["echo", "test"], capture_output=True, text=True)
        assert result.returncode == 0

        vcr.unpatch()

        # Verify metadata was saved
        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        assert "metadata" in data
        assert data["metadata"]["test_name"] == "test_metadata_recording"
        assert data["metadata"]["recorded_at"] == "2024-01-15T10:30:00Z"
        assert data["metadata"]["python_version"] == "3.11.0"
        assert data["metadata"]["platform"] == "Linux-5.10.0"

        # Verify interactions still work
        assert len(data["interactions"]) == 1
        assert data["interactions"][0]["args"] == ["echo", "test"]

        # Verify cassette count is included
        assert data["metadata"]["cassette_count"] == 1

    def test_cassette_count_in_metadata(self, tmp_path):
        """Test that cassette count is automatically added to metadata."""
        cassette_path = tmp_path / "test.yaml"

        # Test without explicit metadata
        vcr = SubprocessVCR(cassette_path, mode="reset")
        vcr.patch()

        # Record multiple commands
        subprocess.run(["echo", "first"], capture_output=True)
        subprocess.run(["echo", "second"], capture_output=True)
        subprocess.run(["echo", "third"], capture_output=True)

        vcr.unpatch()

        # Verify cassette count
        with open(cassette_path) as f:
            data = yaml.safe_load(f)

        assert "metadata" in data
        assert data["metadata"]["cassette_count"] == 3
        assert len(data["interactions"]) == 3

    def test_cassette_count_record_mode(self, tmp_path):
        """Test that cassette count is correctly updated in record mode (merge)."""
        cassette_path = tmp_path / "test.yaml"

        # First recording session
        vcr = SubprocessVCR(cassette_path, mode="reset")
        vcr.patch()
        subprocess.run(["echo", "first"], capture_output=True)
        subprocess.run(["echo", "second"], capture_output=True)
        vcr.unpatch()

        # Verify initial count
        with open(cassette_path) as f:
            data = yaml.safe_load(f)
        assert data["metadata"]["cassette_count"] == 2

        # Second recording session with record mode (merges with existing)
        vcr2 = SubprocessVCR(cassette_path, mode="record")
        vcr2.patch()
        subprocess.run(["echo", "third"], capture_output=True)
        subprocess.run(["echo", "fourth"], capture_output=True)
        vcr2.unpatch()

        # Verify count includes all interactions
        with open(cassette_path) as f:
            data = yaml.safe_load(f)
        assert data["metadata"]["cassette_count"] == 4
        assert len(data["interactions"]) == 4

    def test_record_with_stderr(self, tmp_path):
        """Test recording includes stderr output."""
        cassette = tmp_path / "test.yaml"
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Use sh to write to stderr
        subprocess.run(["sh", "-c", "echo error >&2"], capture_output=True, text=True)

        vcr.unpatch()

        with open(cassette) as f:
            data = yaml.safe_load(f)

        assert data["interactions"][0]["stderr"] == "error\n"


class TestMultipleRecordings:
    """Test handling of multiple recordings of the same command."""

    def test_sequential_same_command(self, tmp_path):
        """Test that multiple recordings of same command replay in order."""
        cassette = tmp_path / "test.yaml"

        # Record phase - run same command 3 times
        vcr_record = SubprocessVCR(cassette, mode="reset")
        vcr_record.patch()

        results_record = []
        for i in range(3):
            # Use echo with different outputs to verify correct replay
            result = subprocess.run(
                ["sh", "-c", f"echo test{i}"], capture_output=True, text=True
            )
            results_record.append(result.stdout.strip())

        vcr_record.unpatch()

        # Verify we recorded different outputs
        assert results_record == ["test0", "test1", "test2"]

        # Replay phase - should get same outputs in same order
        vcr_replay = SubprocessVCR(cassette, mode="replay")
        vcr_replay.patch()

        results_replay = []
        for i in range(3):
            result = subprocess.run(
                ["sh", "-c", f"echo test{i}"], capture_output=True, text=True
            )
            results_replay.append(result.stdout.strip())

        vcr_replay.unpatch()

        # Should get same sequence
        assert results_replay == ["test0", "test1", "test2"]

    def test_interleaved_commands(self, tmp_path):
        """Test replay of interleaved different commands."""
        cassette = tmp_path / "test.yaml"

        # Record: A, B, A, B pattern
        vcr_record = SubprocessVCR(cassette, mode="reset")
        vcr_record.patch()

        subprocess.run(["echo", "A1"], capture_output=True, text=True)
        subprocess.run(["echo", "B1"], capture_output=True, text=True)
        subprocess.run(["echo", "A2"], capture_output=True, text=True)
        subprocess.run(["echo", "B2"], capture_output=True, text=True)

        vcr_record.unpatch()

        # Replay in same order
        vcr_replay = SubprocessVCR(cassette, mode="replay")
        vcr_replay.patch()

        r1 = subprocess.run(["echo", "A1"], capture_output=True, text=True)
        r2 = subprocess.run(["echo", "B1"], capture_output=True, text=True)
        r3 = subprocess.run(["echo", "A2"], capture_output=True, text=True)
        r4 = subprocess.run(["echo", "B2"], capture_output=True, text=True)

        vcr_replay.unpatch()

        # Verify correct outputs
        assert r1.stdout.strip() == "A1"
        assert r2.stdout.strip() == "B1"
        assert r3.stdout.strip() == "A2"
        assert r4.stdout.strip() == "B2"


class TestReplay:
    """Test replay functionality."""

    def test_replay_exact_match(self, tmp_path):
        """Test replay with exact command match."""
        cassette = tmp_path / "test.yaml"
        cassette.write_text("""version: 1
interactions:
  - args: ["echo", "test"]
    kwargs:
      stdout: PIPE
      stderr: PIPE
      text: true
    stdout: |
      replayed output
    stderr: ""
    returncode: 0
    duration: 0.1
""")

        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(["echo", "test"], capture_output=True, text=True)

        vcr.unpatch()

        assert result.stdout == "replayed output\n"
        assert result.returncode == 0

    def test_replay_no_match_error(self, tmp_path):
        """Test clear error when no recording matches."""
        cassette = tmp_path / "test.yaml"
        cassette.write_text("""version: 1
interactions: []
""")

        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        with pytest.raises(SubprocessVCRError, match="No recording found"):
            subprocess.run(["echo", "unrecorded"], capture_output=True)

        vcr.unpatch()


class TestTextBinaryModes:
    """Test text vs binary output handling."""

    def test_text_mode_preserved(self, tmp_path):
        """Test text mode output is returned as strings."""
        cassette = tmp_path / "test.yaml"
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            ["echo", "text"],
            capture_output=True,
            text=True,  # Text mode
        )

        vcr.unpatch()

        # Verify output is string
        assert isinstance(result.stdout, str)
        assert result.stdout == "text\n"

    def test_binary_mode_preserved(self, tmp_path):
        """Test binary mode output is returned as bytes."""
        cassette = tmp_path / "test.yaml"
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            ["echo", "binary"],
            capture_output=True,
            # No text=True, so binary mode
        )

        vcr.unpatch()

        # Verify output is bytes
        assert isinstance(result.stdout, bytes)
        assert result.stdout == b"binary\n"


class TestContextManager:
    """Test context manager protocol support."""

    def test_subprocess_run_uses_context_manager(self, tmp_path):
        """Verify subprocess.run works (it uses context manager internally)."""
        cassette = tmp_path / "test.yaml"
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # This would fail if context manager protocol wasn't implemented
        result = subprocess.run(["echo", "context"], capture_output=True, text=True)

        vcr.unpatch()

        assert result.returncode == 0
        assert "context" in result.stdout


class TestCheckBehavior:
    """Test check=True error propagation."""

    def test_check_true_raises_on_failure(self, tmp_path):
        """Test that check=True raises CalledProcessError on non-zero exit."""
        cassette = tmp_path / "test.yaml"
        cassette.write_text("""version: 1
interactions:
  - args: ["false"]
    kwargs:
      stdout: PIPE
      stderr: PIPE
    stdout: ""
    stderr: |
      Command failed
    returncode: 1
    duration: 0.1
""")

        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            subprocess.run(["false"], capture_output=True, check=True)

        vcr.unpatch()

        assert exc_info.value.returncode == 1
        # VCR should NOT modify stderr output
        assert exc_info.value.stderr == b"Command failed\n"


class TestErrorReporting:
    """Test improved error reporting functionality."""

    def test_detailed_error_with_differences(self, tmp_path):
        """Test detailed error message with command differences."""
        cassette = tmp_path / "test.yaml"
        cassette.write_text("""version: 1
interactions:
  - args: ["docker", "run", "-d", "ubuntu:20.04"]
    kwargs: {}
    stdout: "container-123"
    stderr: ""
    returncode: 0
    duration: 0.5
  - args: ["docker", "ps", "-a"]
    kwargs: {}
    stdout: "CONTAINER ID   IMAGE"
    stderr: ""
    returncode: 0
    duration: 0.1
  - args: ["docker", "exec", "container-123", "echo", "test"]
    kwargs: {}
    stdout: "test"
    stderr: ""
    returncode: 0
    duration: 0.2
""")

        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        try:
            subprocess.run(
                ["docker", "run", "-d", "alpine:latest"], capture_output=True
            )
        except SubprocessVCRError as e:
            error_msg = str(e)
            # Verify error message structure
            assert "Actual command:" in error_msg
            assert "['docker', 'run', '-d', 'alpine:latest']" in error_msg
            assert "Available recordings in cassette:" in error_msg
            assert "1. ['docker', 'run', '-d', 'ubuntu:20.04']" in error_msg
            assert "Differences:" in error_msg
            assert "Argument 3: 'alpine:latest' != 'ubuntu:20.04'" in error_msg
            # Other recordings should be listed but without differences
            assert "2. ['docker', 'ps', '-a']" in error_msg
            assert "3. ['docker', 'exec'," in error_msg
        else:
            pytest.fail("Expected SubprocessVCRError")

        vcr.unpatch()

    def test_error_with_empty_cassette(self, tmp_path):
        """Test error message when cassette has no recordings."""
        cassette = tmp_path / "test.yaml"
        cassette.write_text("""version: 1
interactions: []
""")

        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        try:
            subprocess.run(["ls", "-la"], capture_output=True)
        except SubprocessVCRError as e:
            error_msg = str(e)
            assert "Actual command:" in error_msg
            assert "['ls', '-la']" in error_msg
            assert "No recordings found in cassette." in error_msg
        else:
            pytest.fail("Expected SubprocessVCRError")

        vcr.unpatch()

    def test_error_with_length_mismatch(self, tmp_path):
        """Test error reporting when commands have different lengths."""
        cassette = tmp_path / "test.yaml"
        cassette.write_text("""version: 1
interactions:
  - args: ["git", "commit", "-m", "Initial commit", "--amend"]
    kwargs: {}
    stdout: ""
    stderr: ""
    returncode: 0
    duration: 0.1
""")

        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        try:
            subprocess.run(["git", "commit", "-m", "Fix bug"], capture_output=True)
        except SubprocessVCRError as e:
            error_msg = str(e)
            assert "Length: 4 != 5" in error_msg
            assert "Argument 4: '--amend' (missing from actual)" in error_msg
        else:
            pytest.fail("Expected SubprocessVCRError")

        vcr.unpatch()
