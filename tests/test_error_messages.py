"""Test error messages from subprocess-vcr."""

import subprocess
import sys
from pathlib import Path

import pytest

from subprocess_vcr import SubprocessVCR, SubprocessVCRError
from subprocess_vcr.filters import PathFilter


@pytest.mark.xfail(sys.platform == "win32", reason="Windows path separators differ")
def test_error_message_shows_normalized_differences_when_using_cwd(tmp_path):
    """Test that error messages show normalized paths in differences section."""
    cassette_path = tmp_path / "test_normalized_diff.yaml"

    # Create subdirs and files
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    work_file = work_dir / "file.txt"
    work_file.write_text("test")

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_file = other_dir / "file.txt"
    other_file.write_text("test")

    # Record with one path using cwd
    with SubprocessVCR(cassette_path, mode="reset", filters=[PathFilter()]):
        # Run subprocess with cwd set
        subprocess.run(
            ["echo", str(work_file), "relative.txt"], check=True, cwd=tmp_path
        )

    # Try to replay with different path
    with pytest.raises(SubprocessVCRError) as exc_info:
        with SubprocessVCR(cassette_path, mode="replay", filters=[PathFilter()]):
            subprocess.run(
                ["echo", str(other_file), "relative.txt"], check=True, cwd=tmp_path
            )

    error_msg = str(exc_info.value)
    print(f"Error message:\n{error_msg}")

    # Check that the error message contains normalized paths in differences
    assert "Normalized command (what we're trying to match):" in error_msg
    assert "<CWD>/other/file.txt" in error_msg

    # Most importantly, check that differences show normalized paths
    assert "Differences:" in error_msg
    assert "- Argument 1: '<CWD>/other/file.txt' != '<CWD>/work/file.txt'" in error_msg

    # The old bug would show the full path on the left side
    assert tmp_path.as_posix() not in error_msg.split("Differences:")[1]


def test_error_message_shows_normalized_differences_simple():
    """Test the fix directly - ensure normalized paths appear in differences."""
    # Create a simple test that shows the issue was in the error message
    from subprocess_vcr.filters import BaseFilter

    class SimpleNormalizer(BaseFilter):
        """Simple filter that replaces /tmp/ with <TMP>."""

        def before_record(self, interaction):
            if "args" in interaction:
                interaction["args"] = [
                    arg.replace("/tmp/", "<TMP>/") for arg in interaction["args"]
                ]
            return interaction

    # Manually create a cassette with normalized paths
    cassette_path = Path("test_cassette.yaml")
    cassette_path.write_text("""version: 1
interactions:
- args:
  - echo
  - <TMP>/work/file.txt
  kwargs: {}
  duration: 0.001
  returncode: 0
  stdout: null
  stderr: null
""")

    try:
        # Try to replay with different normalized path
        with pytest.raises(SubprocessVCRError) as exc_info:
            with SubprocessVCR(
                cassette_path, mode="replay", filters=[SimpleNormalizer()]
            ):
                subprocess.run(["echo", "/tmp/other/file.txt"], check=True)

        error_msg = str(exc_info.value)
        print(f"Error message:\n{error_msg}")

        # The fix ensures differences show normalized paths on both sides
        assert "Differences:" in error_msg
        assert (
            "- Argument 1: '<TMP>/other/file.txt' != '<TMP>/work/file.txt'" in error_msg
        )

        # Not the un-normalized path
        assert "'/tmp/other/file.txt'" not in error_msg.split("Differences:")[1]
    finally:
        cassette_path.unlink(missing_ok=True)
