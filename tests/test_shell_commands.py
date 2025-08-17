"""Test shell command handling in subprocess VCR."""

import subprocess
import sys

import pytest
import yaml


class TestShellCommands:
    """Test proper handling of shell=True commands."""

    @pytest.mark.xfail(sys.platform == "win32", reason="Windows shell quoting differs")
    def test_shell_command_recorded_as_string(self, tmp_path):
        """Test that shell commands are recorded as strings, not character lists."""
        from subprocess_vcr import SubprocessVCR

        cassette = tmp_path / "shell_string.yaml"

        # Record a shell command
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            "echo 'Hello from shell'", shell=True, capture_output=True, text=True
        )

        vcr.unpatch()

        assert result.stdout.strip() == "Hello from shell"
        assert result.returncode == 0

        # Check the cassette format
        with open(cassette) as f:
            data = yaml.safe_load(f)

        # The command should be stored as a single string
        recorded_args = data["interactions"][0]["args"]
        assert isinstance(recorded_args, str), (
            f"Expected string, got {type(recorded_args)}"
        )
        assert recorded_args == "echo 'Hello from shell'"

    def test_shell_command_replay(self, tmp_path):
        """Test that shell commands can be replayed correctly."""
        from subprocess_vcr import SubprocessVCR

        cassette = tmp_path / "shell_replay.yaml"

        # Record
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result1 = subprocess.run(
            "echo 'Test replay'", shell=True, capture_output=True, text=True
        )

        vcr.unpatch()

        # Replay
        vcr = SubprocessVCR(cassette, mode="replay")
        vcr.patch()

        result2 = subprocess.run(
            "echo 'Test replay'", shell=True, capture_output=True, text=True
        )

        vcr.unpatch()

        assert result1.stdout == result2.stdout
        assert result1.returncode == result2.returncode

    def test_mixed_shell_and_list_commands(self, tmp_path):
        """Test recording both shell and list commands in same cassette."""
        from subprocess_vcr import SubprocessVCR

        cassette = tmp_path / "mixed_commands.yaml"

        # Record both types
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        # Shell command
        subprocess.run(
            "echo 'Shell command'", shell=True, capture_output=True, text=True
        )

        # List command
        subprocess.run(
            [sys.executable, "-c", "print('List command')"],
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        # Check cassette has both formats
        with open(cassette) as f:
            data = yaml.safe_load(f)

        assert len(data["interactions"]) == 2

        # First should be string
        assert isinstance(data["interactions"][0]["args"], str)
        assert data["interactions"][0]["args"] == "echo 'Shell command'"

        # Second should be list
        assert isinstance(data["interactions"][1]["args"], list)
        assert data["interactions"][1]["args"][0] == sys.executable

    def test_shell_command_with_pipes(self, tmp_path):
        """Test shell commands with pipes and redirects."""
        from subprocess_vcr import SubprocessVCR

        cassette = tmp_path / "shell_pipes.yaml"

        # Record complex shell command
        vcr = SubprocessVCR(cassette, mode="reset")
        vcr.patch()

        result = subprocess.run(
            "echo 'Line 1' && echo 'Line 2' | grep '2'",
            shell=True,
            capture_output=True,
            text=True,
        )

        vcr.unpatch()

        assert "Line 1" in result.stdout
        assert "Line 2" in result.stdout

        # Check it's stored as single string
        with open(cassette) as f:
            data = yaml.safe_load(f)

        recorded_cmd = data["interactions"][0]["args"]
        assert isinstance(recorded_cmd, str)
        assert "&&" in recorded_cmd
        assert "|" in recorded_cmd

    @pytest.mark.subprocess_vcr
    @pytest.mark.xfail(sys.platform == "win32", reason="Windows shell quoting differs")
    def test_convenience_functions_use_proper_format(self):
        """Test that getoutput/getstatusoutput record shell commands as strings."""
        # These use shell=True internally
        output = subprocess.getoutput("echo 'getoutput test'")
        assert output == "getoutput test"

        status, output = subprocess.getstatusoutput("echo 'getstatusoutput test'")
        assert status == 0
        assert output == "getstatusoutput test"
