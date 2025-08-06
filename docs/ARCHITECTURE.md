# Subprocess VCR Architecture

## Overview

Subprocess VCR intercepts subprocess.Popen calls to record and replay subprocess
executions during tests. This dramatically speeds up test suites that rely
heavily on subprocess calls (like Docker operations).

## Core Design Decisions

### 1. Interception at Popen Level

We intercept at `subprocess.Popen` rather than higher-level APIs because:

- All subprocess functions (`run()`, `check_output()`, etc.) use Popen
  internally
- Captures the full lifecycle including concurrent execution patterns
- Allows accurate replay of streaming output and process state

### 2. Sequential Replay Mechanism

Multiple executions of the same command replay in sequence:

```python
# Recording: docker ps (returns A) → docker ps (returns A,B)
# Replay: First call returns A, second call returns A,B
```

Implementation tracks position with `_interaction_index` to ensure correct
sequential replay.

### 3. Module-Level Original Popen

To handle nested VCR instances, we save the original Popen at module load:

```python
_ORIGINAL_POPEN = subprocess.Popen  # Before any patching
```

## Stage 2: ThreadedMockPopen

### The Concurrent Execution Problem

Safety Net uses concurrent subprocess execution:

```python
# Start container (long-running)
proc1 = subprocess.Popen(["docker", "run", "-it", "alpine", "sh"])

# While container is starting, run exec
proc2 = subprocess.Popen(["docker", "exec", container_id, "echo", "test"])

# Both processes running simultaneously
output2 = proc2.communicate()  # Completes first
output1 = proc1.communicate()  # Completes later
```

### ThreadedMockPopen Design

```python
class ThreadedMockPopen:
    """Mock Popen that preserves timing relationships."""

    def __init__(self, recording):
        self.recording = recording
        self.args = recording.get("args", [])
        self.returncode = None
        self._output_ready = threading.Event()
        self._output = None

        # Start background thread to simulate execution time
        self._thread = threading.Thread(target=self._simulate_execution)
        self._thread.daemon = True
        self._thread.start()

    def _simulate_execution(self):
        # Wait for recorded duration to simulate process execution
        time.sleep(self.recording["duration"])

        # Make output available
        self._output = (
            self.recording.get("stdout", ""),
            self.recording.get("stderr", "")
        )
        self.returncode = self.recording["returncode"]
        self._output_ready.set()

    def wait(self, timeout=None):
        # Block until process completes
        if not self._output_ready.wait(timeout):
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode

    def poll(self):
        # Check if process has completed
        if self._output_ready.is_set():
            return self.returncode
        return None
```

### Thread Cleanup Strategy

To prevent thread leaks:

1. Threads are daemon threads (won't prevent exit)
2. Short max duration (5 minutes) prevents long waits
3. Explicit cleanup on communicate/wait
4. Process cleanup via context manager

## Command Matching Strategy

### Basename Matching

To handle dynamic paths (especially pytest's temporary directories), VCR uses
basename matching by default:

```python
def _commands_match(self, cmd1: list[str], cmd2: list[str]) -> bool:
    """Check if two commands match using basename comparison for paths."""
    if len(cmd1) != len(cmd2):
        return False

    for arg1, arg2 in zip(cmd1, cmd2):
        # If both arguments look like paths, compare only basenames
        if ("/" in arg1 or "\\" in arg1) and ("/" in arg2 or "\\" in arg2):
            if Path(arg1).name != Path(arg2).name:
                return False
        else:
            # Exact match for non-path arguments
            if arg1 != arg2:
                return False
    return True
```

This allows tests to work despite pytest creating different temporary
directories each run:

- `/tmp/pytest-123/test_0/config.yaml` matches
  `/tmp/pytest-456/test_0/config.yaml`
- Both have the same basename: `config.yaml`

### Future: Stage 2 Normalization

For more complex cases (container IDs, timestamps), Stage 2 will add regex-based
normalization:

```python
# TODO: Stage 2 will support patterns like:
PATTERNS = [
    # Container IDs in commands
    (r'[0-9a-f]{12,64}', '<CONTAINER_ID>'),
    # Timestamps
    (r'backup-\d+\.tar', 'backup-<TIMESTAMP>.tar'),
]
```

### Important: No Output Normalization

Test outputs are NEVER normalized because tests parse and reuse values:

```python
# Test code
result = subprocess.run(["docker", "create", "alpine"])
container_id = result.stdout.strip()  # Parse output
subprocess.run(["docker", "start", container_id])  # Reuse value
```

## Cassette Format

```yaml
version: "1.0"
interactions:
  - args: ["docker", "run", "-d", "alpine", "sleep", "100"]
    normalized_args: ["docker", "run", "-d", "alpine", "sleep", "100"]
    kwargs:
      stdout: PIPE
      stderr: PIPE
    stdout: "8f3a6c2d1e5b\n"
    stderr: ""
    returncode: 0
    duration: 0.523
    pid: 12345
```

## Design Constraints

### Limited Popen API

Based on ORIGINAL_PLAN.md analysis, we only need to support:

- `wait()` - Wait for completion
- `poll()` - Check if still running
- `terminate()` - Send SIGTERM
- `kill()` - Send SIGKILL
- `send_signal(sig)` - Send arbitrary signal
- `pid` - Process ID attribute
- `returncode` - Exit code after completion
- `stdout` - File-like object if stdout=PIPE

We don't need: stdin handling, complex pipe setups, or communicate() with
timeouts.

### Thread Safety

- Each VCR instance maintains its own state
- Module-level `_ORIGINAL_POPEN` is read-only after import
- Thread-local storage not needed (each test runs serially)
