#!/usr/bin/env python3
"""Demo of subprocess convenience functions with VCR."""

import subprocess
from pathlib import Path

from subprocess_vcr import SubprocessVCR


def main():
    """Demonstrate getoutput and getstatusoutput with VCR."""
    cassette_path = Path("convenience_demo.yaml")

    print("=== Recording Phase ===")
    with SubprocessVCR(cassette_path, mode="reset"):
        # Using getoutput() - returns just the output as a string
        output = subprocess.getoutput("echo 'Hello from getoutput!'")
        print(f"getoutput result: {output!r}")

        # Using getstatusoutput() - returns (status, output) tuple
        status, output = subprocess.getstatusoutput(
            "echo 'Hello from getstatusoutput!'"
        )
        print(f"getstatusoutput result: status={status}, output={output!r}")

        # Error case
        status, output = subprocess.getstatusoutput(
            "echo 'This is an error' >&2; exit 42"
        )
        print(f"Error case: status={status}, output={output!r}")

        # Complex shell command
        output = subprocess.getoutput("echo 'Line 1'; echo 'Line 2'; echo 'Line 3'")
        print(f"Multi-line output:\n{output}")

    print("\n=== Replay Phase ===")
    with SubprocessVCR(cassette_path, mode="replay"):
        # Same commands will be replayed from cassette
        output = subprocess.getoutput("echo 'Hello from getoutput!'")
        print(f"Replayed getoutput: {output!r}")

        status, output = subprocess.getstatusoutput(
            "echo 'Hello from getstatusoutput!'"
        )
        print(f"Replayed getstatusoutput: status={status}, output={output!r}")

        status, output = subprocess.getstatusoutput(
            "echo 'This is an error' >&2; exit 42"
        )
        print(f"Replayed error: status={status}, output={output!r}")

        output = subprocess.getoutput("echo 'Line 1'; echo 'Line 2'; echo 'Line 3'")
        print(f"Replayed multi-line:\n{output}")

    print("\n✅ Convenience functions work perfectly with subprocess VCR!")
    print("   Both getoutput() and getstatusoutput() are automatically supported")
    print("   because they use subprocess.Popen internally.")


if __name__ == "__main__":
    main()
