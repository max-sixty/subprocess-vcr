"""Comprehensive test coverage for all subprocess APIs across all recording modes.

This module ensures that all subprocess methods work correctly with subprocess_vcr
in every recording mode.
"""

from __future__ import annotations

import os
import subprocess
import sys
from subprocess import PIPE, CalledProcessError, CompletedProcess, TimeoutExpired

import pytest
import yaml

from subprocess_vcr import SubprocessVCR, SubprocessVCRError
from subprocess_vcr.filters import PathFilter

# Note: These tests don't use @pytest.mark.subprocess_vcr because they manage
# VCR instances manually to test different modes and configurations


class TestSubprocessAPIMethods:
    """Test all subprocess API methods with VCR."""

    @pytest.mark.parametrize("mode", ["record", "reset", "replay"])
    @pytest.mark.parametrize(
        "api_method,check_result",
        [
            (
                lambda cmd, **kw: subprocess.run(cmd, capture_output=True, **kw),
                lambda result: isinstance(result, CompletedProcess),
            ),
            (
                lambda cmd, **kw: subprocess.Popen(
                    cmd, stdout=PIPE, stderr=PIPE, **kw
                ).communicate(),
                lambda result: isinstance(result, tuple) and len(result) == 2,
            ),
            (
                lambda cmd, **kw: subprocess.check_output(
                    cmd, stderr=subprocess.DEVNULL, **kw
                ),
                lambda result: isinstance(result, (bytes, str)),
            ),
            (
                lambda cmd, **kw: subprocess.call(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw
                ),
                lambda result: isinstance(result, int),
            ),
        ],
    )
    def test_subprocess_api_matrix(self, tmp_path, mode, api_method, check_result):
        """Test each subprocess API method works correctly in each mode."""
        cassette = tmp_path / "api_test.yaml"

        # First pass: record or reset
        if mode == "replay":
            # Need to create a cassette first
            vcr_record = SubprocessVCR(cassette, mode="reset")
            vcr_record.patch()
            api_method([sys.executable, "-c", "print('test output')"])
            vcr_record.unpatch()

        # Test pass
        vcr = SubprocessVCR(cassette, mode=mode)
        vcr.patch()

        result = api_method([sys.executable, "-c", "print('test output')"])

        vcr.unpatch()

        # Verify the API returned expected type
        assert check_result(result)

        # For methods that return output, verify it
        if isinstance(result, CompletedProcess):
            assert b"test output" in result.stdout
        elif isinstance(result, tuple):  # communicate() returns (stdout, stderr)
            assert b"test output" in result[0]
        elif isinstance(result, bytes):  # check_output
            assert b"test output" in result

    def test_check_call_success(self, tmp_path):
        """Test subprocess.check_call with successful command."""
        cassette = tmp_path / "check_call_success.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.check_call(
            [sys.executable, "-c", "import sys; print('success'); sys.exit(0)"]
        )

        vcr.unpatch()

        assert result == 0

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.check_call(
            [sys.executable, "-c", "import sys; print('success'); sys.exit(0)"]
        )

        vcr.unpatch()

        assert result == 0

    def test_check_call_failure(self, tmp_path):
        """Test subprocess.check_call with failing command."""
        cassette = tmp_path / "check_call_failure.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        with pytest.raises(CalledProcessError) as exc_info:
            subprocess.check_call([sys.executable, "-c", "import sys; sys.exit(1)"])

        vcr.unpatch()

        assert exc_info.value.returncode == 1

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        with pytest.raises(CalledProcessError) as exc_info:
            subprocess.check_call([sys.executable, "-c", "import sys; sys.exit(1)"])

        vcr.unpatch()

        assert exc_info.value.returncode == 1


class TestPopenMethods:
    """Test direct Popen usage with various methods."""

    def test_popen_communicate(self, tmp_path):
        """Test Popen with communicate() method."""
        cassette = tmp_path / "popen_communicate.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "print('stdout'); import sys; print('stderr', file=sys.stderr)",
            ],
            stdout=PIPE,
            stderr=PIPE,
        )
        stdout, stderr = proc.communicate()

        vcr.unpatch()

        assert b"stdout" in stdout
        assert b"stderr" in stderr
        assert proc.returncode == 0

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "print('stdout'); import sys; print('stderr', file=sys.stderr)",
            ],
            stdout=PIPE,
            stderr=PIPE,
        )
        stdout, stderr = proc.communicate()

        vcr.unpatch()

        assert b"stdout" in stdout
        assert b"stderr" in stderr
        assert proc.returncode == 0

    def test_popen_wait(self, tmp_path):
        """Test Popen with wait() method."""
        cassette = tmp_path / "popen_wait.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.1); print('done')"]
        )
        exit_code = proc.wait()

        vcr.unpatch()

        assert exit_code == 0

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.1); print('done')"]
        )
        exit_code = proc.wait()

        vcr.unpatch()

        assert exit_code == 0

    def test_popen_poll(self, tmp_path):
        """Test Popen with poll() method."""
        cassette = tmp_path / "popen_poll.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "print('instant')"], stdout=PIPE, stderr=PIPE
        )
        # communicate() waits for process completion
        stdout, stderr = proc.communicate()
        exit_code = proc.poll()

        vcr.unpatch()

        assert exit_code == 0

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "print('instant')"], stdout=PIPE, stderr=PIPE
        )
        # In replay, poll should immediately return the exit code
        exit_code = proc.poll()

        vcr.unpatch()

        assert exit_code == 0

    def test_popen_with_context_manager(self, tmp_path):
        """Test Popen used as context manager."""
        cassette = tmp_path / "popen_context.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        with subprocess.Popen(
            [sys.executable, "-c", "print('context manager')"],
            stdout=PIPE,
        ) as proc:
            stdout, _ = proc.communicate()
            assert b"context manager" in stdout

        vcr.unpatch()

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        with subprocess.Popen(
            [sys.executable, "-c", "print('context manager')"],
            stdout=PIPE,
        ) as proc:
            stdout, _ = proc.communicate()
            assert b"context manager" in stdout

        vcr.unpatch()


class TestShellCommands:
    """Test shell command handling."""

    @pytest.mark.parametrize("mode", ["record", "reset", "replay"])
    def test_shell_true(self, tmp_path, mode):
        """Test shell=True commands."""
        cassette = tmp_path / "shell_test.yaml"

        if mode == "replay":
            # Create cassette first
            vcr_record = SubprocessVCR(cassette, mode="reset")
            vcr_record.patch()
            subprocess.run(
                "echo 'shell test'", shell=True, capture_output=True, text=True
            )
            vcr_record.unpatch()

        vcr = SubprocessVCR(cassette, mode=mode)
        vcr.patch()

        result = subprocess.run(
            "echo 'shell test'", shell=True, capture_output=True, text=True
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "shell test" in result.stdout

    def test_shell_with_pipes(self, tmp_path):
        """Test shell commands with pipes."""
        cassette = tmp_path / "shell_pipes.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Create a test file first
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = subprocess.run(
            f"cat {test_file} | grep line2",
            shell=True,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "line2" in result.stdout
        assert "line1" not in result.stdout

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        # Note: file doesn't need to exist in replay mode
        result = subprocess.run(
            f"cat {test_file} | grep line2",
            shell=True,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "line2" in result.stdout

    @pytest.mark.xfail(
        sys.platform == "win32", reason="Windows env var expansion differs"
    )
    def test_shell_with_env_vars(self, tmp_path):
        """Test shell commands with environment variable expansion."""
        cassette = tmp_path / "shell_env.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            "echo $HOME",
            shell=True,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert result.stdout.strip() == os.environ.get("HOME")

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            "echo $HOME",
            shell=True,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        # In replay, should get same output even if HOME changed
        assert result.stdout.strip() == os.environ.get("HOME")


class TestProcessCommunication:
    """Test process communication with stdin."""

    def test_stdin_input(self, tmp_path):
        """Test providing input via stdin."""
        cassette = tmp_path / "stdin_input.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; data = sys.stdin.read(); print(f'Got: {data}')",
            ],
            input="test input",
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "Got: test input" in result.stdout

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; data = sys.stdin.read(); print(f'Got: {data}')",
            ],
            input="test input",
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "Got: test input" in result.stdout

    def test_communicate_with_input(self, tmp_path):
        """Test Popen.communicate() with input."""
        cassette = tmp_path / "communicate_input.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
            stdin=PIPE,
            stdout=PIPE,
            text=True,
        )
        stdout, _ = proc.communicate(input="hello world")

        vcr.unpatch()

        assert proc.returncode == 0
        assert "HELLO WORLD" in stdout

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
            stdin=PIPE,
            stdout=PIPE,
            text=True,
        )
        stdout, _ = proc.communicate(input="hello world")

        vcr.unpatch()

        assert proc.returncode == 0
        assert "HELLO WORLD" in stdout


class TestTimeoutBehavior:
    """Test timeout parameter in all modes."""

    @pytest.mark.parametrize("mode", ["record", "reset", "replay"])
    def test_timeout_success(self, tmp_path, mode):
        """Test commands that complete before timeout."""
        cassette = tmp_path / "timeout_success.yaml"

        if mode == "replay":
            # Create cassette first
            vcr_record = SubprocessVCR(cassette, mode="reset")
            vcr_record.patch()
            subprocess.run(
                [sys.executable, "-c", "print('quick')"],
                timeout=5,
                capture_output=True,
                text=True,
            )
            vcr_record.unpatch()

        vcr = SubprocessVCR(cassette, mode=mode)
        vcr.patch()

        result = subprocess.run(
            [sys.executable, "-c", "print('quick')"],
            timeout=5,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "quick" in result.stdout

    def test_timeout_exceeded_recording(self, tmp_path):
        """Test timeout handling during recording."""
        cassette = tmp_path / "timeout_exceeded.yaml"

        # Record - this will actually timeout
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        with pytest.raises(TimeoutExpired):
            subprocess.run(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                timeout=0.1,
                capture_output=True,
            )

        vcr.unpatch()

        # The cassette might not have a complete recording for timeout cases
        # This is expected behavior - timeouts interrupt the process


class TestWorkingDirectory:
    """Test cwd parameter effects."""

    def test_cwd_recording_replay(self, tmp_path):
        """Test that cwd is properly handled in recording and replay."""
        cassette = tmp_path / "cwd_test.yaml"

        # Create test directories
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        # Create test files
        (dir1 / "file1.txt").write_text("content1")
        (dir2 / "file2.txt").write_text("content2")

        # Record from dir1
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            ["ls"],
            cwd=str(dir1),
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert "file1.txt" in result.stdout

        # Replay with different cwd should work with PathFilter
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            ["ls"],
            cwd=str(dir1),  # Must use same cwd for exact matching
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert "file1.txt" in result.stdout

    def test_cwd_with_path_filter(self, tmp_path):
        """Test that PathFilter properly normalizes cwd paths."""
        cassette = tmp_path / "cwd_filter.yaml"

        # Create a test directory
        test_dir = tmp_path / "test_project"
        test_dir.mkdir()

        # Record from test_dir
        vcr = SubprocessVCR(cassette, mode="reset", filters=[PathFilter()])
        vcr.patch()

        result = subprocess.run(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            cwd=str(test_dir),
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert str(test_dir) in result.stdout

        # Check that the cassette has normalized paths
        with open(cassette) as f:
            data = yaml.safe_load(f)

        # The cwd should be normalized to <CWD>
        interaction = data["interactions"][0]
        assert "kwargs" in interaction
        assert "cwd" in interaction["kwargs"]
        cwd_value = interaction["kwargs"]["cwd"]
        assert cwd_value == "<CWD>", f"Expected cwd to be <CWD>, got {cwd_value}"


class TestEnvironmentVariables:
    """Test env parameter handling."""

    def test_custom_env_vars(self, tmp_path):
        """Test commands with custom environment variables."""
        cassette = tmp_path / "env_vars.yaml"

        # Record with custom env
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        custom_env = os.environ.copy()
        custom_env["TEST_VAR"] = "test_value"
        custom_env["ANOTHER_VAR"] = "another_value"

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ.get('TEST_VAR', 'not found'))",
            ],
            env=custom_env,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert "test_value" in result.stdout

        # Verify env was recorded
        with open(cassette) as f:
            data = yaml.safe_load(f)

        assert data["interactions"][0]["kwargs"]["env"]["TEST_VAR"] == "test_value"
        assert (
            data["interactions"][0]["kwargs"]["env"]["ANOTHER_VAR"] == "another_value"
        )

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        # Use same custom env for matching
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; print(os.environ.get('TEST_VAR', 'not found'))",
            ],
            env=custom_env,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert "test_value" in result.stdout

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows command not found")
    def test_env_affects_behavior(self, tmp_path):
        """Test that env changes can affect command behavior."""
        cassette = tmp_path / "env_behavior.yaml"

        # Record with PATH that includes custom directory
        test_script = tmp_path / "custom_bin" / "test_cmd"
        test_script.parent.mkdir()
        test_script.write_text("#!/bin/sh\necho 'custom command'")
        test_script.chmod(0o755)

        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        custom_env = os.environ.copy()
        custom_env["PATH"] = f"{test_script.parent}:{custom_env['PATH']}"

        # This will find our custom test_cmd
        result = subprocess.run(
            ["test_cmd"],
            env=custom_env,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert result.returncode == 0
        assert "custom command" in result.stdout


class TestTextBinaryModes:
    """Test text vs binary mode handling across all APIs."""

    @pytest.mark.parametrize("text_mode", [True, False])
    @pytest.mark.parametrize("api", ["run", "check_output", "Popen"])
    def test_text_binary_consistency(self, tmp_path, text_mode, api):
        """Test that text/binary mode is preserved across all APIs."""
        cassette = tmp_path / f"text_binary_{api}_{text_mode}.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        if api == "run":
            result = subprocess.run(
                [sys.executable, "-c", "print('test output')"],
                capture_output=True,
                text=text_mode,
            )
            output = result.stdout
        elif api == "check_output":
            output = subprocess.check_output(
                [sys.executable, "-c", "print('test output')"],
                text=text_mode,
            )
        else:  # Popen
            proc = subprocess.Popen(
                [sys.executable, "-c", "print('test output')"],
                stdout=PIPE,
                text=text_mode,
            )
            output, _ = proc.communicate()

        vcr.unpatch()

        # Verify output type
        if text_mode:
            assert isinstance(output, str)
            assert "test output" in output
        else:
            assert isinstance(output, bytes)
            assert b"test output" in output

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        if api == "run":
            result = subprocess.run(
                [sys.executable, "-c", "print('test output')"],
                capture_output=True,
                text=text_mode,
            )
            output = result.stdout
        elif api == "check_output":
            output = subprocess.check_output(
                [sys.executable, "-c", "print('test output')"],
                text=text_mode,
            )
        else:  # Popen
            proc = subprocess.Popen(
                [sys.executable, "-c", "print('test output')"],
                stdout=PIPE,
                text=text_mode,
            )
            output, _ = proc.communicate()

        vcr.unpatch()

        # Verify output type is preserved in replay
        if text_mode:
            assert isinstance(output, str)
            assert "test output" in output
        else:
            assert isinstance(output, bytes)
            assert b"test output" in output


class TestCaptureOutputParameter:
    """Test capture_output parameter (subprocess.run specific)."""

    def test_capture_output_true(self, tmp_path):
        """Test capture_output=True parameter."""
        cassette = tmp_path / "capture_output.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "print('stdout'); import sys; print('stderr', file=sys.stderr)",
            ],
            capture_output=True,
        )

        vcr.unpatch()

        assert b"stdout" in result.stdout
        assert b"stderr" in result.stderr

        # Verify it was recorded properly
        with open(cassette) as f:
            data = yaml.safe_load(f)

        # capture_output=True is translated to stdout=PIPE, stderr=PIPE
        assert data["interactions"][0]["kwargs"]["stdout"] == "PIPE"
        assert data["interactions"][0]["kwargs"]["stderr"] == "PIPE"

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "print('stdout'); import sys; print('stderr', file=sys.stderr)",
            ],
            capture_output=True,
        )

        vcr.unpatch()

        assert b"stdout" in result.stdout
        assert b"stderr" in result.stderr


class TestErrorHandling:
    """Test error handling for various subprocess scenarios."""

    def test_nonexistent_command(self, tmp_path):
        """Test handling of nonexistent commands."""
        cassette = tmp_path / "nonexistent.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        with pytest.raises(FileNotFoundError):
            subprocess.run(["this_command_does_not_exist"])

        vcr.unpatch()

        # In recording mode, the actual error occurs
        # VCR doesn't record failed Popen attempts

        # Replay - should fail with SubprocessVCRError since command wasn't recorded
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        with pytest.raises(SubprocessVCRError, match="No recording found"):
            subprocess.run(["this_command_does_not_exist"])

        vcr.unpatch()

    @pytest.mark.xfail(
        sys.platform == "win32", reason="Windows encoding handling differs"
    )
    def test_encoding_parameter(self, tmp_path):
        """Test encoding parameter handling."""
        cassette = tmp_path / "encoding.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            [sys.executable, "-c", "print('café')"],
            capture_output=True,
            encoding="utf-8",
        )

        vcr.unpatch()

        assert "café" in result.stdout

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result = subprocess.run(
            [sys.executable, "-c", "print('café')"],
            capture_output=True,
            encoding="utf-8",
        )

        vcr.unpatch()

        assert "café" in result.stdout
