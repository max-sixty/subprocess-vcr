#!/usr/bin/env python3
"""
Demo: Process Control with subprocess VCR

This demonstrates how subprocess VCR now supports terminate() and kill() methods
on Popen objects, allowing proper process control in both recording and replay modes.
"""

import subprocess
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from subprocess_vcr import SubprocessVCR


def demo_terminate():
    """Demonstrate process termination with VCR."""
    print("=== Process Termination Demo ===\n")

    cassette_path = Path("demo_terminate.yaml")

    # Phase 1: Record a process being terminated
    print("1. Recording a process termination...")
    vcr = SubprocessVCR(cassette_path, mode="reset")
    vcr.patch()

    # Start a long-running process
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import time
print("Process started")
for i in range(10):
    print(f"Working... {i}")
    time.sleep(1)
print("Process completed normally")
""",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Let it run for a bit
    time.sleep(2)

    # Terminate it
    print("   Sending SIGTERM...")
    proc.terminate()

    # Wait for it to exit and collect output
    stdout, stderr = proc.communicate(timeout=5)
    print(f"   Return code: {proc.returncode}")
    print(f"   Output: {stdout.strip()}")

    vcr.unpatch()

    # Phase 2: Replay the termination
    print("\n2. Replaying the termination...")
    vcr = SubprocessVCR(cassette_path, mode="replay")
    vcr.patch()

    # Run the same command
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            """
import time
print("Process started")
for i in range(10):
    print(f"Working... {i}")
    time.sleep(1)
print("Process completed normally")
""",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Terminate it (in replay mode, this is a no-op but doesn't error)
    proc.terminate()

    # Get the recorded output
    stdout, stderr = proc.communicate()
    print(f"   Return code: {proc.returncode}")
    print(f"   Output: {stdout.strip()}")

    vcr.unpatch()

    # Clean up
    cassette_path.unlink()
    print("\n✅ Termination demo complete!")


def demo_timeout():
    """Demonstrate subprocess.run with timeout."""
    print("\n\n=== Timeout Handling Demo ===\n")

    cassette_path = Path("demo_timeout.yaml")

    # Phase 1: Record a timeout
    print("1. Recording a process timeout...")
    vcr = SubprocessVCR(cassette_path, mode="reset")
    vcr.patch()

    try:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import time; print('Starting sleep'); time.sleep(5)",
            ],
            timeout=1,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.TimeoutExpired as e:
        print("   TimeoutExpired raised as expected!")
        print(f"   Timeout value: {e.timeout}")
        print(f"   Partial output: {repr(e.stdout)}")

    vcr.unpatch()

    # Phase 2: Replay the timeout
    print("\n2. Replaying the timeout...")
    vcr = SubprocessVCR(cassette_path, mode="replay")
    vcr.patch()

    try:
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import time; print('Starting sleep'); time.sleep(5)",
            ],
            timeout=1,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.TimeoutExpired:
        print("   TimeoutExpired raised in replay!")
        print("   (Note: In replay mode, the timeout is simulated)")
    except subprocess.CalledProcessError as e:
        # In replay mode, we get the recorded exit code (-9 from kill)
        # This is a known limitation - timeout detection is not yet implemented
        print("   CalledProcessError raised (known limitation)")
        print(f"   Return code: {e.returncode} (process was killed)")
        print("   Note: Full timeout replay support is planned for future versions")

    vcr.unpatch()

    # Clean up
    cassette_path.unlink()
    print("\n✅ Timeout demo complete!")


if __name__ == "__main__":
    demo_terminate()
    demo_timeout()
