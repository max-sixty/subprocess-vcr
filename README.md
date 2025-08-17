# Subprocess VCR

A Video Cassette Recorder (VCR) for subprocess commands that dramatically speeds
up test execution by recording and replaying subprocess calls.

## Quick Start

```python
import subprocess
import pytest

# Mark test to use VCR - that's it!
@pytest.mark.subprocess_vcr
def test_with_vcr():
    result = subprocess.run(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout == "hello\n"
```

Run tests:

```bash
# Record new interactions, replay existing ones
pytest --subprocess-vcr=record

# Replay only - fails if subprocess call not in cassette (for CI)
pytest --subprocess-vcr=replay
```

## Recording Modes

Subprocess VCR supports several recording modes:

- **`record`** - Replays existing recordings, records new ones. For each
  subprocess call, it first checks if a recording exists. If found, it replays
  that recording. If not found, it executes and records the new subprocess call.
  Useful for incremental test development.

- **`replay`** - Replay only. Fails if a subprocess call is not found in the
  cassette. Ensures deterministic test execution in CI.

- **`reset`** - Always record, replacing any existing cassettes and their
  metadata. Use this to refresh all recordings or when library behavior has
  changed.

- **`replay+reset`** - Attempts to replay from existing cassettes, but on any
  test failure or missing recording, automatically retries the ENTIRE test in
  reset mode. This has the benefit over `reset` of only resetting the cassette
  _where necessary_: when replay succeeds, the existing cassette and metadata
  are preserved.

- **`disable`** - No VCR, subprocess calls execute normally (default).

## Filters for Normalization and Redaction

Subprocess VCR provides a powerful filter system to normalize dynamic values and
redact sensitive information in your recordings. This ensures cassettes are
portable, secure, and deterministic.

### Built-in Filters

#### PathFilter

Normalizes filesystem paths that change between test runs, including paths
relative to the current working directory:

```python
from subprocess_vcr.filters import PathFilter

# Default normalization (pytest paths, home dirs, CWD, etc.)
@pytest.mark.subprocess_vcr(filters=[PathFilter()])
def test_with_paths():
    # Pytest temp paths
    subprocess.run(["ls", "/tmp/pytest-of-user/pytest-123/test_dir"])
    # Recorded as: ["ls", "<TMP>/test_dir"]

    # Current working directory paths
    subprocess.run(["cat", "/home/user/project/data/file.txt"], cwd="/home/user/project")
    # Recorded as: ["cat", "<CWD>/data/file.txt"] with cwd: "<CWD>"

# Custom path replacements
filter = PathFilter(replacements={
    r"/opt/myapp": "<APP_ROOT>",
    r"/var/log/\w+": "<LOG_DIR>",
})
```

#### RedactFilter

Removes sensitive information:

```python
from subprocess_vcr.filters import RedactFilter

# Redact by patterns
filter = RedactFilter(
    patterns=[r"api_key=\w+", r"Bearer \w+"],
    env_vars=["API_KEY", "DATABASE_URL"],
)

@pytest.mark.subprocess_vcr(filters=[filter])
def test_with_secrets():
    subprocess.run(["curl", "-H", "Authorization: Bearer abc123"])
    # Recorded as: ["curl", "-H", "Authorization: <REDACTED>"]
```

### Combining Filters

#### Using Multiple Filters

Filters are applied in order:

```python
@pytest.mark.subprocess_vcr(filters=[
    PathFilter(),  # Handles all path normalization including CWD
    RedactFilter(env_vars=["API_KEY", "DATABASE_URL"]),
])
def test_complex_command():
    subprocess.run(["docker", "build", "-t", "myapp:latest", "."])
```

#### Global Configuration

Set filters for all tests in `conftest.py`:

```python
@pytest.fixture(scope="session")
def subprocess_vcr_config():
    return {
        "filters": [
            PathFilter(),  # Handles all path normalization
            RedactFilter(env_vars=["API_KEY"]),
        ]
    }
```

### Creating Custom Filters

Inherit from `BaseFilter`:

```python
from subprocess_vcr.filters import BaseFilter

class MyCustomFilter(BaseFilter):
    def before_record(self, interaction: dict) -> dict:
        """Modify interaction before saving to cassette."""
        # Example: normalize custom IDs in output
        if interaction.get("stdout"):
            interaction["stdout"] = re.sub(
                r"request-id: \w+",
                "request-id: <REQUEST_ID>",
                interaction["stdout"]
            )
        return interaction

    def before_playback(self, interaction: dict) -> dict:
        """Modify interaction when loading from cassette."""
        # Usually just return unchanged
        return interaction

# Use the custom filter
@pytest.mark.subprocess_vcr(filters=[MyCustomFilter()])
def test_with_custom_filter():
    subprocess.run(["myapp", "process"])
```

## VCR Context in Test Reports

When tests fail while using subprocess VCR, pytest shows additional context in
the test report to help with debugging:

```
----------------------------- subprocess-vcr -----------------------------
This test replayed subprocess calls from VCR cassette: test_example.yaml
To re-record this test, run with: --subprocess-vcr=reset
```

This context appears for ANY test failure when VCR is replaying, helping you
understand whether the failure might be due to outdated recordings.

## Example Cassette

```yaml
version: "1.0"
interactions:
  - args:
      - echo
      - hello world
    kwargs:
      stdout: PIPE
      stderr: PIPE
      text: true
    duration: 0.005
    returncode: 0
    stdout: |
      hello world
    stderr: ""
    pid: 12345
```
