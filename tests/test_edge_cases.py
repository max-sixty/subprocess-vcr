"""Edge case tests for subprocess_vcr.

This module tests complex scenarios that could break in production
or have unexpected behavior.
"""

import subprocess
import sys
import time
from subprocess import PIPE

import pytest
import yaml

from subprocess_vcr import SubprocessVCR, SubprocessVCRError

# Note: These tests don't use @pytest.mark.subprocess_vcr because they manage
# VCR instances manually to test different modes and configurations


class TestShellCommandComplexity:
    """Test complex shell commands."""

    def test_shell_pipes_complex(self, tmp_path):
        """Test shell commands with multiple pipes."""
        cassette = tmp_path / "complex_pipes.yaml"

        # Create test data
        test_file = tmp_path / "data.txt"
        test_file.write_text("apple\nbanana\ncherry\napricot\nblueberry\n")

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Complex pipe: cat | grep | sort | head
        result = subprocess.run(
            f"cat {test_file} | grep '^a' | sort | head -2",
            shell=True,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "apple" in result.stdout
        assert "apricot" in result.stdout
        assert "banana" not in result.stdout

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            f"cat {test_file} | grep '^a' | sort | head -2",
            shell=True,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "apple" in result.stdout
        assert "apricot" in result.stdout

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows shell quoting differs")
    def test_shell_redirects(self, tmp_path):
        """Test shell redirects (>, >>, 2>&1)."""
        cassette = tmp_path / "redirects.yaml"
        output_file = tmp_path / "output.txt"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Test redirect stdout to file
        result = subprocess.run(
            f"echo 'test output' > {output_file}",
            shell=True,
            capture_output=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert output_file.read_text().strip() == "test output"

        # Test stderr redirect
        cassette2 = tmp_path / "stderr_redirect.yaml"
        vcr = SubprocessVCR(cassette2, mode="reset")
        vcr.patch()

        # Command that writes to stderr, redirect to stdout
        result2 = subprocess.run(
            f"{sys.executable} -c \"import sys; print('error', file=sys.stderr)\" 2>&1",
            shell=True,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result2.returncode == 0
        assert "error" in result2.stdout
        assert result2.stderr == ""  # stderr was redirected

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows shell behavior differs")
    def test_shell_command_substitution(self, tmp_path):
        """Test command substitution in shell."""
        cassette = tmp_path / "cmd_substitution.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Use command substitution
        result = subprocess.run(
            'echo "Current directory: $(pwd)"',
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert str(tmp_path) in result.stdout

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            'echo "Current directory: $(pwd)"',
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert str(tmp_path) in result.stdout


class TestProcessManagement:
    """Test process management scenarios."""

    @pytest.mark.slow
    def test_long_running_process(self, tmp_path):
        """Test recording/replay of long-running processes."""
        cassette = tmp_path / "long_running.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Process that takes some time
        start = time.time()
        result = subprocess.run(
            [sys.executable, "-c", "import time; time.sleep(1); print('done')"],
            capture_output=True,
            text=True,
        )
        duration = time.time() - start

        vcr.unpatch()

        assert result.returncode == 0
        assert "done" in result.stdout
        assert duration >= 0.9  # Should take at least 1 second

        # Verify duration was recorded
        with open(cassette) as f:
            data = yaml.safe_load(f)

        assert data["interactions"][0]["duration"] >= 0.9

        # Replay - should be instant
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        start = time.time()
        result = subprocess.run(
            [sys.executable, "-c", "import time; time.sleep(1); print('done')"],
            capture_output=True,
            text=True,
        )
        duration = time.time() - start

        vcr.unpatch()

        assert result.returncode == 0
        assert "done" in result.stdout
        assert duration < 0.5  # Should be much faster in replay

    def test_process_exit_codes(self, tmp_path):
        """Test various process exit codes."""
        for exit_code in [0, 1, 2, 127, 255]:
            cassette = tmp_path / f"exit_{exit_code}.yaml"

            # Record
            vcr = SubprocessVCR(cassette, mode="reset")
            vcr.patch()

            result = subprocess.run(
                [sys.executable, "-c", f"import sys; sys.exit({exit_code})"],
                capture_output=True,
            )

            vcr.unpatch()

            assert result.returncode == exit_code

            # Replay
            vcr = SubprocessVCR(cassette, mode="replay")
            vcr.patch()

            result = subprocess.run(
                [sys.executable, "-c", f"import sys; sys.exit({exit_code})"],
                capture_output=True,
            )

            vcr.unpatch()

            assert result.returncode == exit_code

    def test_process_termination(self, tmp_path):
        """Test process termination handling."""
        cassette = tmp_path / "termination.yaml"

        # This test is tricky - we can't easily record actual termination
        # but we can test that the recording captures the final state

        # Record a process that exits normally
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.1); print('finished')"],
            stdout=PIPE,
        )
        proc.wait()
        stdout, _ = proc.communicate()

        vcr.unpatch()

        assert proc.returncode == 0
        assert b"finished" in stdout


class TestDataHandling:
    """Test handling of various data sizes and types."""

    def test_large_output(self, tmp_path):
        """Test recording/replaying processes with large output."""
        cassette = tmp_path / "large_output.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Generate 1MB of output programmatically
        result = subprocess.run(
            [sys.executable, "-c", "print('x' * 1024 * 1024, end='')"],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert len(result.stdout) >= 1024 * 1024

        # Verify cassette size
        cassette_size = cassette.stat().st_size
        assert cassette_size > 1024 * 1024  # Should be at least 1MB

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [sys.executable, "-c", "print('x' * 1024 * 1024, end='')"],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert len(result.stdout) >= 1024 * 1024
        assert result.stdout == "x" * 1024 * 1024

    def test_binary_data(self, tmp_path):
        """Test recording/replaying binary output."""
        cassette = tmp_path / "binary_data.yaml"

        # Record - generate some binary data
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Generate binary data including non-UTF8 bytes
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(bytes(range(256)))",
            ],
            capture_output=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert len(result.stdout) == 256
        assert result.stdout == bytes(range(256))

        # Verify binary data was base64 encoded in cassette
        with open(cassette) as f:
            data = yaml.safe_load(f)

        stdout_data = data["interactions"][0]["stdout"]
        assert isinstance(stdout_data, dict)
        assert stdout_data.get("_binary") is True
        assert "data" in stdout_data

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(bytes(range(256)))",
            ],
            capture_output=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert result.stdout == bytes(range(256))

    def test_mixed_text_binary_streams(self, tmp_path):
        """Test mixed text/binary in different streams."""
        cassette = tmp_path / "mixed_streams.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # stdout as text, stderr as binary with high bytes (non-ASCII but not control chars)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; print('text output'); "
                "sys.stderr.buffer.write(bytes([0x80, 0x81, 0xFF, 0xFE])); sys.stderr.flush()",
            ],
            capture_output=True,
            text=False,  # Binary mode to capture both properly
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert b"text output" in result.stdout
        # The binary data should be preserved
        assert result.stderr == bytes([0x80, 0x81, 0xFF, 0xFE])

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; print('text output'); "
                "sys.stderr.buffer.write(bytes([0x80, 0x81, 0xFF, 0xFE])); sys.stderr.flush()",
            ],
            capture_output=True,
            text=False,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert b"text output" in result.stdout
        assert result.stderr == bytes([0x80, 0x81, 0xFF, 0xFE])

    def test_empty_output(self, tmp_path):
        """Test handling of empty stdout/stderr."""
        cassette = tmp_path / "empty_output.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Command with no output
        result = subprocess.run(
            [sys.executable, "-c", "pass"],
            capture_output=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert result.stdout == b""
        assert result.stderr == b""

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [sys.executable, "-c", "pass"],
            capture_output=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert result.stdout == b""
        assert result.stderr == b""

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows encoding differs")
    def test_unicode_handling(self, tmp_path):
        """Test various Unicode scenarios."""
        cassette = tmp_path / "unicode.yaml"

        # Test various Unicode strings
        test_strings = [
            "Hello 世界",  # Chinese
            "Привет мир",  # Russian
            "🐍 Python 🎉",  # Emojis
            "Café ☕",  # Accented characters
            "\u200b\u200c\u200d",  # Zero-width characters
        ]

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        for test_str in test_strings:
            result = subprocess.run(
                [sys.executable, "-c", f"print({repr(test_str)})"],
                capture_output=True,
                text=True,
            )
            assert test_str in result.stdout

        vcr.unpatch()

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        for test_str in test_strings:
            result = subprocess.run(
                [sys.executable, "-c", f"print({repr(test_str)})"],
                capture_output=True,
                text=True,
            )
            assert test_str in result.stdout

        vcr.unpatch()


class TestConcurrentAccess:
    """Test concurrent access scenarios."""

    def test_sequential_vcr_instances(self, tmp_path):
        """Test multiple VCR instances using same cassette sequentially."""
        cassette = tmp_path / "shared_cassette.yaml"

        # First VCR instance records
        vcr1 = SubprocessVCR(cassette, mode="reset")
        vcr1.patch()

        result1 = subprocess.run(["echo", "first"], capture_output=True, text=True)

        vcr1.unpatch()

        assert result1.stdout.strip() == "first"

        # Second VCR instance replays
        vcr2 = SubprocessVCR(cassette, mode="replay")
        vcr2.patch()

        result2 = subprocess.run(["echo", "first"], capture_output=True, text=True)

        vcr2.unpatch()

        assert result2.stdout.strip() == "first"

    def test_multiple_recordings_same_cassette(self, tmp_path):
        """Test appending multiple recordings to same cassette."""
        cassette = tmp_path / "append_test.yaml"

        # First recording session
        vcr1 = SubprocessVCR(cassette, mode="record")
        vcr1.patch()

        subprocess.run(["echo", "recording1"], capture_output=True)

        vcr1.unpatch()

        # Second recording session - should append
        vcr2 = SubprocessVCR(cassette, mode="record")
        vcr2.patch()

        subprocess.run(["echo", "recording2"], capture_output=True)

        vcr2.unpatch()

        # Verify both recordings exist
        with open(cassette) as f:
            data = yaml.safe_load(f)

        assert len(data["interactions"]) == 2
        assert any(
            "recording1" in str(i.get("stdout", "")) for i in data["interactions"]
        )
        assert any(
            "recording2" in str(i.get("stdout", "")) for i in data["interactions"]
        )

    @pytest.mark.slow
    def test_parallel_subprocess_calls(self, tmp_path):
        """Test recording parallel subprocess calls."""
        cassette = tmp_path / "parallel.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Launch multiple subprocesses in parallel
        procs = []
        for i in range(3):
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    f"import time; time.sleep(0.1); print('proc{i}')",
                ],
                stdout=PIPE,
                text=True,
            )
            procs.append(proc)

        # Wait for all to complete
        results = []
        for proc in procs:
            stdout, _ = proc.communicate()
            results.append(stdout.strip())

        vcr.unpatch()

        assert sorted(results) == ["proc0", "proc1", "proc2"]

        # Verify all were recorded
        with open(cassette) as f:
            data = yaml.safe_load(f)

        assert len(data["interactions"]) == 3


class TestErrorScenarios:
    """Test various error conditions."""

    def test_corrupted_cassette(self, tmp_path):
        """Test handling of corrupted cassette files."""
        cassette = tmp_path / "corrupted.yaml"

        # Write invalid YAML
        cassette.write_text("{ invalid: yaml: content: ][")

        # Should handle gracefully
        with pytest.raises(Exception):  # yaml.YAMLError or similar
            SubprocessVCR(cassette, mode="replay")

    def test_malformed_cassette_structure(self, tmp_path):
        """Test cassette with wrong structure."""
        cassette = tmp_path / "malformed.yaml"

        # Write valid YAML but wrong structure
        cassette.write_text("""
version: 1
interactions: "should be a list not a string"
""")

        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        # Should fail when trying to replay
        with pytest.raises(Exception):
            subprocess.run(["echo", "test"], capture_output=True)

        vcr.unpatch()

    def test_incomplete_cassette_data(self, tmp_path):
        """Test cassette missing required fields."""
        cassette = tmp_path / "incomplete.yaml"

        # Missing stdout, stderr, returncode
        cassette.write_text("""
version: 1
interactions:
  - args: ["echo", "test"]
    kwargs: {}
    duration: 0.1
""")

        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        # Should fail when required fields are missing
        with pytest.raises((KeyError, AttributeError)):
            subprocess.run(["echo", "test"], capture_output=True)

        vcr.unpatch()

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod not reliable on Windows")
    def test_permission_denied_cassette(self, tmp_path, monkeypatch):
        """Test handling when cassette file has permission issues."""
        cassette = tmp_path / "no_perms.yaml"

        # Create cassette
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()
        subprocess.run(["echo", "test"], capture_output=True)
        vcr.unpatch()

        # Remove write permissions
        cassette.chmod(0o444)

        # For root users (e.g., in Docker), we need to simulate the permission error
        # since root can write to read-only files
        import os
        import sys

        if sys.platform != "win32" and os.getuid() == 0:
            original_open = open

            def mock_open(path, mode="r", *args, **kwargs):
                # Only raise error for our specific test file when writing
                if str(path) == str(cassette) and "w" in mode:
                    raise PermissionError(f"[Errno 13] Permission denied: '{path}'")
                return original_open(path, mode, *args, **kwargs)

            monkeypatch.setattr("builtins.open", mock_open)

        try:
            # Try to write to read-only cassette
            vcr = SubprocessVCR(cassette, mode="reset")
            vcr.patch()
            subprocess.run(["echo", "test2"], capture_output=True)

            # Should fail on unpatch when trying to save
            with pytest.raises(SubprocessVCRError, match="Permission denied"):
                vcr.unpatch()
        finally:
            # Restore permissions for cleanup
            cassette.chmod(0o644)

    def test_disk_space_simulation(self, tmp_path):
        """Test behavior when disk is full (simulated)."""
        # This is hard to test reliably across platforms
        # We'll test what happens with very large output instead

        cassette = tmp_path / "large_test.yaml"

        # Try to record extremely large output
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Generate 10MB of output (reasonable test size)
        subprocess.run(
            [sys.executable, "-c", "print('x' * (10 * 1024 * 1024), end='')"],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        # Should succeed - cassette should be written
        assert cassette.exists()
        assert cassette.stat().st_size > 10 * 1024 * 1024

    def test_network_commands_simulation(self, tmp_path):
        """Test commands that might fail differently in different environments."""
        cassette = tmp_path / "network_sim.yaml"

        # Record a command that might behave differently
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Use a command that exists everywhere but might have different output
        result = subprocess.run(
            ["hostname"],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        original_hostname = result.stdout.strip()

        # Replay - should get same hostname even on different machine
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            ["hostname"],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.stdout.strip() == original_hostname


class TestSpecialCases:
    """Test special edge cases."""

    def test_control_characters_in_output(self, tmp_path):
        """Test handling of control characters in output."""
        cassette = tmp_path / "control_chars.yaml"

        # Record output with control characters
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Generate output with various control characters (except null)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                r"print('Hello\x07\x08\x0c\x1b[31mRed\x1b[0m\x7fWorld')",
            ],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        # Control chars should be stripped for YAML safety
        with open(cassette) as f:
            content = f.read()
            # Should not contain raw control characters
            assert "\x07" not in content
            assert "\x08" not in content

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                r"print('Hello\x07\x08\x0c\x1b[31mRed\x1b[0m\x7fWorld')",
            ],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        # Output should have some control chars stripped but ESC sequences preserved
        assert "Hello" in result.stdout
        assert "Red" in result.stdout
        assert "World" in result.stdout
        # The bell, backspace, form feed, and delete chars should be stripped
        assert "\x07" not in result.stdout  # Bell
        assert "\x08" not in result.stdout  # Backspace
        assert "\x0c" not in result.stdout  # Form feed
        assert "\x7f" not in result.stdout  # Delete
        # But ESC sequences are preserved (for ANSI colors etc)
        assert "\x1b[31m" in result.stdout or "[31m" in result.stdout

    def test_very_long_command_lines(self, tmp_path):
        """Test handling of very long command lines."""
        cassette = tmp_path / "long_cmd.yaml"

        # Create a very long argument
        long_arg = "x" * 1000

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            [sys.executable, "-c", "import sys; print(len(sys.argv[1]))", long_arg],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "1000" in result.stdout

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [sys.executable, "-c", "import sys; print(len(sys.argv[1]))", long_arg],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "1000" in result.stdout

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows filename restrictions")
    def test_special_filenames(self, tmp_path):
        """Test handling of special characters in filenames."""
        # Create files with special names
        special_names = [
            "file with spaces.txt",
            "file'with'quotes.txt",
            'file"with"doublequotes.txt',
            "file;with;semicolon.txt",
            "file|with|pipe.txt",
        ]

        for name in special_names:
            (tmp_path / name).write_text("content")

        cassette = tmp_path / "special_files.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # List files
        result = subprocess.run(
            ["ls", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        for name in special_names:
            assert name in result.stdout

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            ["ls", str(tmp_path)],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        for name in special_names:
            assert name in result.stdout

    def test_non_zero_exit_with_output(self, tmp_path):
        """Test processes that fail but still produce output."""
        cassette = tmp_path / "fail_with_output.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
print("This is stdout")
print("This is stderr", file=sys.stderr)
sys.exit(42)
""",
            ],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 42
        assert "This is stdout" in result.stdout
        assert "This is stderr" in result.stderr

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
print("This is stdout")
print("This is stderr", file=sys.stderr)
sys.exit(42)
""",
            ],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 42
        assert "This is stdout" in result.stdout
        assert "This is stderr" in result.stderr
