# Subprocess VCR - TODO

## High Priority Issues

### Thread Safety and Concurrency

- **Cassette file locking**: Add file locking for concurrent cassette access
  - Multiple test workers can write to same cassette file simultaneously
  - Use `fcntl` on Unix or `portalocker` for cross-platform support
  - Consider atomic writes (write to temp file, then rename)
- **Process-specific cassettes**: For better test isolation with pytest-xdist
  - Consider using worker ID or process ID in cassette filenames
  - Example: `test_name.worker-{worker_id}.yaml`
- **Thread-local storage**: Consider refactoring to use thread-local VCR
  instances
  - Would eliminate most global state issues
  - More complex but more robust for concurrent usage

### Missing Subprocess API Coverage

- ✅ `subprocess.getoutput()` - Fully supported (added tests in
  test_convenience_functions.py)
- ✅ `subprocess.getstatusoutput()` - Fully supported (added tests in
  test_convenience_functions.py)

### Shell Command Recording

- ✅ Fixed shell=True command recording - Commands are now properly stored as
  strings instead of character arrays
  - Fixed in core.py RecordingPopen.**init** to preserve string commands
  - Added comprehensive tests in test_shell_commands.py
  - Cassette files are now much more readable for shell commands

### Process Control Implementation

- ✅ `Popen.terminate()` and `Popen.kill()` - Fully implemented (added in
  core.py)
  - RecordingPopen forwards calls to real process
  - SimpleMockPopen provides no-op implementations
  - Added comprehensive tests in test_process_control.py
- Record and replay `TimeoutExpired` exceptions properly
  - Currently, timeouts result in killed processes (returncode -9) being
    recorded
  - In replay mode, this causes `CalledProcessError` instead of `TimeoutExpired`
  - Need to record timeout metadata in cassette format to properly replay
    timeouts

### Encoding Improvements

- Use `locale.getpreferredencoding(False)` as default encoding instead of UTF-8
- Match subprocess module's encoding behavior more closely

## Future Enhancements

### Better Debug Output

- Show matching process step-by-step when replay fails
- Log why each recording was skipped during matching
- Rich diff output showing exact command differences

### Command Matching Improvements

- Multiple matching strategies (e.g., match on program only, prefix matching)
- Smart matching for common patterns (container IDs, timestamps, versions)

### Packaging for PyPI

- Create proper `pyproject.toml` with metadata
- Add `__version__` to `__init__.py`
- Set up GitHub Actions for CI/CD
- Add LICENSE file

### CLI Tools

- `python -m subprocess_vcr inspect path/to/cassette.yaml` - inspect cassette
  contents
- `python -m subprocess_vcr validate` - check all cassettes for issues
- `python -m subprocess_vcr stats` - show performance gains from using VCR

### Advanced Features (Lower Priority)

- Streaming support for long-running processes
- Process interaction recording (stdin/stdout exchanges)
- Performance mode (skip output capture for speed)
- Parallel safety with file locking for cassette access
