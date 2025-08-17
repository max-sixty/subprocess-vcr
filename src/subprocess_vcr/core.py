"""Core VCR functionality for subprocess recording and replay."""

from __future__ import annotations

import base64
import copy
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .filters import BaseFilter

# Module logger
logger = logging.getLogger(__name__)

# Save the original Popen before any patching
_ORIGINAL_POPEN = subprocess.Popen

# Global lock to protect patching/unpatching operations
_PATCH_LOCK = threading.RLock()

# Constants
DEFAULT_CASSETTE_VERSION = 1
DEFAULT_ENCODING = "utf-8"
PIPE_MARKER = "PIPE"
MOCK_PID = 12345
CONTROL_CHAR_REGEX = r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]"


class SubprocessVCRError(Exception):
    """Base exception for subprocess VCR errors."""

    pass


def _format_command(cmd: list[str] | str) -> str:
    """Format a command for display."""
    __tracebackhide__ = True
    if isinstance(cmd, str):
        return repr(cmd)
    return "[" + ", ".join(repr(arg) for arg in cmd) + "]"


def _find_command_differences(cmd1: list[str], cmd2: list[str]) -> list[str]:
    """Find differences between two commands.

    Returns:
        List of difference descriptions
    """
    __tracebackhide__ = True
    differences = []

    if len(cmd1) != len(cmd2):
        differences.append(f"Length: {len(cmd1)} != {len(cmd2)}")
        # Still compare what we can
        min_len = min(len(cmd1), len(cmd2))
        for i in range(min_len):
            if cmd1[i] != cmd2[i]:
                differences.append(f"Argument {i}: {repr(cmd1[i])} != {repr(cmd2[i])}")
        # Note extra arguments
        if len(cmd1) > len(cmd2):
            for i in range(len(cmd2), len(cmd1)):
                differences.append(f"Argument {i}: {repr(cmd1[i])} (extra in actual)")
        else:
            for i in range(len(cmd1), len(cmd2)):
                differences.append(
                    f"Argument {i}: {repr(cmd2[i])} (missing from actual)"
                )
    else:
        # Same length, find differences
        for i in range(len(cmd1)):
            if cmd1[i] != cmd2[i]:
                differences.append(f"Argument {i}: {repr(cmd1[i])} != {repr(cmd2[i])}")

    return differences


# YAML formatting with literal block style for readability
class _LiteralDumper(yaml.SafeDumper):
    """YAML dumper that uses literal style for multiline strings."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure Unicode is handled properly
        self.allow_unicode = True


def _literal_str_representer(dumper, data):
    """Use literal block style for multiline strings."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


# Register the representer
_LiteralDumper.add_representer(str, _literal_str_representer)


def yaml_dump(data, stream=None, **kwargs):
    """Dump YAML with sensible formatting defaults and literal blocks for multiline strings.

    Args:
        data: The data to serialize to YAML
        stream: Optional stream to write to (if None, returns string)
        **kwargs: Additional arguments passed to yaml.dump

    Returns:
        If stream is None, returns the YAML string. Otherwise writes to stream.
    """
    # Set our defaults
    kwargs.setdefault("Dumper", _LiteralDumper)
    kwargs.setdefault("default_flow_style", False)
    kwargs.setdefault("sort_keys", False)
    kwargs.setdefault("allow_unicode", True)
    # Use a wide width to avoid line wrapping for long lines
    kwargs.setdefault("width", 1000)

    return yaml.dump(data, stream, **kwargs)


class SubprocessVCR:
    """Record and replay subprocess executions."""

    # Valid recording modes
    VALID_MODES = {"record", "reset", "replay", "replay+reset", "disable"}

    def __init__(
        self,
        cassette_path: Path,
        mode: str = "replay",
        metadata: dict[str, Any] | None = None,
        strict: bool = False,
        filters: list[BaseFilter] | None = None,
    ):
        """Initialize VCR.

        Args:
            cassette_path: Path to the cassette file
            mode: Recording mode - one of:
                - "record": Record new interactions, replay existing ones
                - "reset": Always record, replacing existing cassettes
                - "replay": Replay only, fail if interaction not found
                - "disable": Disable VCR entirely (pass through to real subprocess)
            metadata: Optional metadata to store in the cassette (test name, timestamp, etc.)
            strict: If True, fail immediately in 'replay' mode if cassette doesn't exist
            filters: List of filters to apply when recording/replaying interactions
        """
        self.cassette_path = cassette_path
        self.mode = self.validate_mode(mode)
        self.metadata = metadata or {}
        self.strict = strict
        self.filters = filters or []
        self.interactions: list[dict[str, Any]] = []
        self._original_popen: type[subprocess.Popen[Any]] | None = None
        self._interaction_index = 0
        self._new_interactions: list[dict[str, Any]] = []  # For recording modes
        self._pytest_request: Any | None = (
            None  # Optional pytest request object for dynamic mode checking
        )
        # Track what action was taken during this session
        self.cassette_action: str | None = None  # 'recorded', 'reset', 'replayed', None

        # Strict mode check
        if self.strict and self.mode == "replay" and not self.cassette_path.exists():
            raise ValueError(
                f"Cassette required in strict replay mode: {self.cassette_path}"
            )

        # Debug log filters if any are configured
        if self.filters:
            filter_names = [f.__class__.__name__ for f in self.filters]
            logger.debug(f"Configured filters: {filter_names}")

        self._load_cassette()

    def __enter__(self):
        """Context manager entry - start patching."""
        self.patch()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop patching."""
        self.unpatch()
        return False

    @classmethod
    def validate_mode(cls, mode: str) -> str:
        """Validate and normalize mode name.

        Args:
            mode: The mode to validate

        Returns:
            The validated mode

        Raises:
            ValueError: If mode is invalid
        """
        if mode not in cls.VALID_MODES:
            raise ValueError(
                f"Invalid mode: {mode}. Must be one of: {sorted(cls.VALID_MODES)}"
            )
        return mode

    def _load_cassette(self) -> None:
        """Load existing cassette based on mode."""
        if self.mode == "disable":
            # No cassette needed in disable mode
            return

        if self.cassette_path.exists():
            # Load cassette for modes that use existing recordings
            if self.mode == "replay" or self.mode == "replay+reset":
                try:
                    with open(self.cassette_path) as f:
                        data = yaml.safe_load(f)
                        self.interactions = data.get("interactions", [])
                    logger.debug(
                        f"Loaded {len(self.interactions)} interactions from {self.cassette_path}"
                    )
                except yaml.YAMLError as e:
                    if self.mode == "replay+reset":
                        # In replay+reset mode, corrupted cassettes are handled gracefully
                        logger.debug(
                            f"Cassette corrupted in replay+reset mode, will fallback to reset on first command: {e}"
                        )
                        self.interactions = []  # Empty interactions will cause replay to fail
                    else:
                        # In replay mode, corrupted cassettes are a fatal error
                        raise ValueError(
                            f"Failed to load VCR cassette {self.cassette_path}: {e}"
                        ) from e
            elif self.mode == "record":
                # Record mode loads existing cassette to replay
                try:
                    with open(self.cassette_path) as f:
                        data = yaml.safe_load(f)
                        self.interactions = data.get("interactions", [])
                    logger.debug(
                        f"Loaded {len(self.interactions)} interactions from {self.cassette_path} for appending"
                    )
                except yaml.YAMLError as e:
                    # In record mode, corrupted cassettes are a fatal error
                    raise ValueError(
                        f"Failed to load VCR cassette {self.cassette_path}: {e}"
                    ) from e
            elif self.mode == "reset":
                # Reset mode starts fresh but we note the cassette exists
                logger.debug(
                    f"Reset mode: will replace existing cassette at {self.cassette_path}"
                )
                # Try to check if the file is corrupted for logging purposes
                try:
                    with open(self.cassette_path) as f:
                        yaml.safe_load(f)
                except yaml.YAMLError:
                    logger.debug(
                        f"Reset mode: existing cassette at {self.cassette_path} appears to be corrupted, will be replaced"
                    )
        else:
            if self.mode == "replay":
                # In replay mode, cassette must exist (unless handled by strict mode)
                logger.debug(
                    f"Warning: Cassette not found in 'replay' mode: {self.cassette_path}"
                )
            else:
                # For all other modes, no cassette is fine
                logger.debug(f"No cassette to load (mode={self.mode}, will create new)")

    def patch(self) -> None:
        """Start intercepting subprocess.Popen."""
        if self.mode == "disable":
            logger.debug("Disable mode: not patching subprocess")
            return

        with _PATCH_LOCK:
            if self._original_popen is not None:
                logger.debug("Warning: Already patched!")
                return

            # Store the current Popen - might already be patched by another VCR
            current_popen = subprocess.Popen

            # Only save if it's not already an intercept function
            if (
                hasattr(current_popen, "__name__")
                and current_popen.__name__ == "_intercept_popen"
            ):
                logger.debug(
                    "Warning: subprocess.Popen already patched by another VCR instance"
                )
                # Use the global original instead
                self._original_popen = _ORIGINAL_POPEN
            else:
                self._original_popen = current_popen

            subprocess.Popen = self._intercept_popen  # type: ignore[misc,assignment]
            self._interaction_index = 0  # Reset for clean replay
            logger.debug(f"Patched subprocess.Popen (mode={self.mode})")

    def unpatch(self) -> None:
        """Stop intercepting subprocess.Popen."""
        if self.mode == "disable":
            return

        with _PATCH_LOCK:
            if self._original_popen:
                subprocess.Popen = self._original_popen  # type: ignore[misc]
                self._original_popen = None  # Clear reference
                logger.debug("Unpatched subprocess.Popen")

        # Save cassette based on mode
        if self.mode == "reset":
            # Reset mode saves only new recordings
            self._save_cassette()
        elif self.mode == "record":
            # Record mode merges new recordings with existing ones
            self._save_cassette_with_merge()
        elif self.mode == "replay+reset":
            # For replay+reset, save if we recorded anything new
            if self._new_interactions:
                self._save_cassette()

    def _save_cassette(self) -> None:
        """Save recorded interactions to YAML."""
        __tracebackhide__ = True
        self.cassette_path.parent.mkdir(parents=True, exist_ok=True)

        # For "reset" and "replay+reset" modes, save only new interactions
        interactions_to_save = (
            self._new_interactions
            if self.mode in ("reset", "replay+reset")
            else self.interactions
        )

        cassette_data: dict[str, Any] = {
            "version": DEFAULT_CASSETTE_VERSION,
            "interactions": interactions_to_save,
        }

        # Add metadata if provided
        if self.metadata:
            cassette_data["metadata"] = self.metadata
        else:
            cassette_data["metadata"] = {}

        # Always add cassette count to metadata
        cassette_data["metadata"]["cassette_count"] = len(interactions_to_save)

        try:
            with open(self.cassette_path, "w") as f:
                yaml_dump(cassette_data, f)
        except Exception as e:
            # Extract what failed to serialize
            failed_obj = str(e).split("cannot represent an object")[-1].strip()
            if failed_obj:
                failed_obj = failed_obj.strip(", ()")

            # Try to find what interaction caused this
            problematic_interactions = []
            for i, interaction in enumerate(interactions_to_save):
                try:
                    # Try to serialize each interaction individually
                    yaml_dump(interaction, None)
                except Exception:
                    problematic_interactions.append((i, interaction))

            error_msg = f"""
SubprocessVCR cannot save cassette - YAML serialization failed!

Error: {e}
Cassette path: {self.cassette_path}

Problematic interactions found: {len(problematic_interactions)}
"""

            if problematic_interactions:
                for idx, interaction in problematic_interactions[:3]:  # Show first 3
                    error_msg += f"\nInteraction {idx}: {interaction.get('args', [])[0] if interaction.get('args') else 'unknown'}"
                    # Check for file handles
                    for key in ["stdout", "stderr"]:
                        if key in interaction.get("kwargs", {}):
                            value = interaction["kwargs"][key]
                            if hasattr(value, "mode"):
                                error_msg += f"\n  -> Has file handle in {key}: {getattr(value, 'name', 'unknown')}"

            error_msg += """

Common causes:
1. File handles passed to stdout/stderr (use subprocess.PIPE instead)
2. Lambda functions or other non-serializable objects in kwargs
3. Custom objects without proper YAML representation

Solutions:
1. Remove @pytest.mark.subprocess_vcr from the failing test
2. Use mode='disable' to skip recording
3. Fix the subprocess call to use serializable values
"""
            raise SubprocessVCRError(error_msg) from e

        logger.debug(
            f"Saved {len(interactions_to_save)} interactions to {self.cassette_path}"
        )

        # Track what action was taken
        if self.mode == "reset" or (
            self.mode == "replay+reset" and self._new_interactions
        ):
            self.cassette_action = "reset"
        elif self._new_interactions:
            self.cassette_action = "recorded"

    def _save_cassette_with_merge(self) -> None:
        """Save cassette by merging new recordings with existing ones."""
        __tracebackhide__ = True

        # Only save if we have new interactions to record
        if not self._new_interactions:
            logger.debug(f"No new interactions to save for {self.cassette_path}")
            return

        self.cassette_path.parent.mkdir(parents=True, exist_ok=True)

        # Merge existing interactions with new ones
        all_interactions = self.interactions + self._new_interactions

        # Simplify cassette data creation with merged metadata
        cassette_data: dict[str, Any] = {
            "version": DEFAULT_CASSETTE_VERSION,
            "interactions": all_interactions,
            "metadata": {
                **(self.metadata or {}),
                "cassette_count": len(all_interactions),
            },
        }

        with open(self.cassette_path, "w") as f:
            yaml_dump(cassette_data, f)

        logger.debug(
            f"Saved {len(all_interactions)} interactions ({len(self._new_interactions)} new) to {self.cassette_path}"
        )

        # Track that we recorded new interactions
        self.cassette_action = "recorded"

    def _validate_serializable(
        self, cmd: list[str] | str, kwargs: dict[str, Any]
    ) -> None:
        """Validate that command and kwargs can be serialized.

        This runs before creating any Popen objects to fail fast.
        """
        __tracebackhide__ = True

        # Check for file handles in stdout/stderr
        for key in ["stdout", "stderr"]:
            if key in kwargs:
                value = kwargs[key]
                # Check for file handles
                if hasattr(value, "mode") and hasattr(value, "name"):
                    error_msg = f"""
SubprocessVCR Error: Cannot record subprocess with file handle!

Problem: {key} is a file object that cannot be serialized to YAML
File: {getattr(value, "name", "unknown")} (mode: {getattr(value, "mode", "unknown")})

This commonly happens when:
1. Background processes redirect output to log files
2. Tests use 'with open(file) as f: subprocess.Popen(..., stdout=f)'

Solutions:
1. Remove @pytest.mark.subprocess_vcr from this test
2. Use subprocess.PIPE for stdout/stderr instead of file handles
"""
                    raise SubprocessVCRError(error_msg)

        # Could add more validation here in the future
        # e.g., check for other non-serializable objects

    def _intercept_popen(self, cmd, **kwargs):
        """Intercept Popen calls based on mode."""
        __tracebackhide__ = True
        self._log_interception(cmd)

        # Early validation for any mode that might record
        if self.mode in ("record", "reset", "replay+reset"):
            self._validate_serializable(cmd, kwargs)

        # Delegate to mode-specific handler
        return self._handle_mode(cmd, kwargs)

    def _log_interception(self, cmd):
        """Log intercepted command."""
        if isinstance(cmd, str):
            logger.debug(f"Intercepted: {cmd}")
        else:
            logger.debug(f"Intercepted: {' '.join(str(c) for c in cmd)}")
        logger.debug(f"Mode: {self.mode}")
        logger.debug(f"Cassette: {self.cassette_path}")

    def _handle_mode(self, cmd, kwargs):
        """Handle command based on current mode."""
        # Dispatch table for cleaner mode handling
        mode_handlers = {
            "replay": lambda: self._replay_popen(cmd, kwargs),
            "reset": lambda: self._record_popen(
                cmd, kwargs, target_list=self._new_interactions
            ),
            "record": lambda: self._handle_record_mode(cmd, kwargs),
            "replay+reset": lambda: self._handle_replay_reset_mode(cmd, kwargs),
        }

        if handler := mode_handlers.get(self.mode):
            return handler()

        # Should never reach here due to disable check in patch()
        raise ValueError(f"Invalid mode: {self.mode}")

    def _handle_record_mode(self, cmd, kwargs):
        """Handle record mode: try replay first, record if not found."""
        try:
            return self._replay_popen(cmd, kwargs)
        except (ValueError, SubprocessVCRError):
            logger.debug("No existing recording, recording new interaction")
            return self._record_popen(cmd, kwargs, target_list=self._new_interactions)

    def _handle_replay_reset_mode(self, cmd, kwargs):
        """Handle replay+reset mode: try replay first, fallback to reset."""
        try:
            return self._replay_popen(cmd, kwargs)
        except (ValueError, SubprocessVCRError) as e:
            logger.debug(f"Replay failed: {e}")
            # Only log message once per cassette
            if not hasattr(self, "_showed_fallback_message"):
                logger.info(
                    f"VCR replay failed, falling back to reset mode for: {self.cassette_path.name}"
                )
                self._showed_fallback_message = True
            return self._record_popen(cmd, kwargs, target_list=self._new_interactions)

    def _record_popen(self, cmd, kwargs, target_list=None):
        """Record a subprocess execution."""
        __tracebackhide__ = True
        # Execute real subprocess
        start_time = time.time()
        # Always use the true original Popen, not what we saved during patch
        proc = _ORIGINAL_POPEN(cmd, **kwargs)

        # Determine which list to record to
        if target_list is None:
            target_list = self.interactions

        # Track what we're doing based on mode
        if not self.cassette_action:  # Only mark if not already marked
            if self.mode == "reset" or (
                self.mode == "replay+reset" and target_list is self._new_interactions
            ):
                self.cassette_action = "reset"
            elif self.mode == "record" or target_list is self._new_interactions:
                self.cassette_action = "recorded"

        # Wrap in recording wrapper
        return RecordingPopen(proc, cmd, kwargs, start_time, self, target_list)

    def _commands_match(
        self,
        recorded_cmd: list[str] | str,
        actual_cmd: list[str] | str,
        recorded_kwargs: dict | None = None,
        actual_kwargs: dict | None = None,
    ) -> bool:
        """Check if two commands match exactly.

        Args:
            recorded_cmd: The command args from the recording
            actual_cmd: The command args being executed
            recorded_kwargs: The kwargs from the recording (optional)
            actual_kwargs: The kwargs being used (optional)
        """
        __tracebackhide__ = True
        # Handle string commands (shell=True)
        if isinstance(recorded_cmd, str) and isinstance(actual_cmd, str):
            # For string commands, just do direct comparison
            # Path matching doesn't apply to shell command strings
            if recorded_cmd != actual_cmd:
                return False
        elif isinstance(recorded_cmd, str) or isinstance(actual_cmd, str):
            # Type mismatch - one is string, other is list
            return False
        else:
            # Both are lists
            if len(recorded_cmd) != len(actual_cmd):
                return False

            # Exact match for command arguments
            if recorded_cmd != actual_cmd:
                return False

        # If we have kwargs to compare, check critical ones
        if recorded_kwargs is not None and actual_kwargs is not None:
            # For cwd, exact match
            if "cwd" in recorded_kwargs and "cwd" in actual_kwargs:
                # Convert to strings for comparison (handle Path objects)
                rec_cwd = str(recorded_kwargs["cwd"])
                act_cwd = str(actual_kwargs["cwd"])

                # Exact match for cwd
                if rec_cwd != act_cwd:
                    logger.debug(f"CWD mismatch: {rec_cwd} != {act_cwd}")
                    return False

        return True

    def _replay_popen(self, cmd, kwargs):
        """Replay a recorded subprocess execution."""
        __tracebackhide__ = True
        # Keep the command in its original format
        cmd_normalized: str | list[str]
        if isinstance(cmd, str):
            cmd_normalized = cmd
        else:
            cmd_normalized = list(cmd)

        # Create a temporary interaction with the current command to normalize it
        # This ensures we're comparing apples to apples
        current_interaction = {
            "args": cmd_normalized,
            "kwargs": kwargs,
        }

        # Apply filters to normalize the current command for matching
        if self.filters:
            normalized_current = self._apply_filters_before_record(current_interaction)
            normalized_cmd = normalized_current["args"]
            normalized_kwargs = normalized_current.get("kwargs", kwargs)
        else:
            normalized_cmd = cmd_normalized
            normalized_kwargs = kwargs

        # Search from current position forward to support multiple recordings
        for i in range(self._interaction_index, len(self.interactions)):
            interaction = self.interactions[i]
            # Compare normalized commands
            if self._commands_match(
                interaction["args"],
                normalized_cmd,
                interaction.get("kwargs"),
                normalized_kwargs,
            ):
                logger.debug(f"Found match at index {i}")
                # Move past this interaction for next search
                self._interaction_index = i + 1

                # Apply filters before playback
                if self.filters:
                    interaction = self._apply_filters_before_playback(interaction)

                # Track that we successfully replayed
                if not self.cassette_action:  # Only mark if not already marked
                    self.cassette_action = "replayed"

                # Log replay info
                logger.debug(
                    "Replaying subprocess from VCR cassette: %s",
                    self.cassette_path.name,
                )

                return SimpleMockPopen(interaction)

        # No match found - fail explicitly with detailed context
        logger.debug(
            f"No match found for: {cmd_normalized} with kwargs={kwargs} (searched from index {self._interaction_index})"
        )

        # Build and raise detailed error
        error_msg = self._build_replay_error(cmd_normalized, normalized_cmd, kwargs)
        raise SubprocessVCRError(error_msg)

    def _build_replay_error(self, cmd_original, cmd_normalized, kwargs):
        """Build detailed error message for replay failures."""
        error_parts = ["SubprocessVCRError: No recording found for command\n"]

        # Show the actual command
        error_parts.append("Actual command:")
        error_parts.append(f"  {self._format_command_for_error(cmd_original)}")

        # Show normalized command if filters are applied
        if self.filters and cmd_normalized != cmd_original:
            error_parts.append("\nNormalized command (what we're trying to match):")
            error_parts.append(f"  {self._format_command_for_error(cmd_normalized)}")

        # Show active filters
        if self.filters:
            filter_names = [f.__class__.__name__ for f in self.filters]
            error_parts.append(f"\nActive filters: {filter_names}")

        # Show available recordings
        self._add_available_recordings_to_error(error_parts, cmd_normalized)

        return "\n".join(error_parts)

    def _format_command_for_error(self, cmd):
        """Format command for error display."""
        if isinstance(cmd, str):
            return repr(cmd)
        return _format_command(cmd)

    def _add_available_recordings_to_error(self, error_parts, normalized_cmd):
        """Add available recordings section to error message."""
        if not self.interactions:
            error_parts.append("\nNo recordings found in cassette.")
            return

        error_parts.append("\nAvailable recordings in cassette:")

        for i, interaction in enumerate(self.interactions):
            recorded_cmd = interaction.get("args", [])
            error_parts.append(f"  {i + 1}. {_format_command(recorded_cmd)}")

            # Show differences for similar commands
            if self._commands_are_similar(normalized_cmd, recorded_cmd):
                self._add_command_differences(error_parts, normalized_cmd, recorded_cmd)

    def _commands_are_similar(self, cmd1, cmd2):
        """Check if two commands are similar enough to show differences."""
        if isinstance(cmd1, str) and isinstance(cmd2, str):
            return cmd1 != cmd2

        if (
            isinstance(cmd1, list)
            and isinstance(cmd2, list)
            and len(cmd1) > 0
            and len(cmd2) > 0
            and cmd1[0] == cmd2[0]
        ):
            return True

        return False

    def _add_command_differences(self, error_parts, cmd1, cmd2):
        """Add command differences to error message."""
        if isinstance(cmd1, str) and isinstance(cmd2, str):
            error_parts.append(f"\n     Difference: {repr(cmd2)} != {repr(cmd1)}")
        else:
            differences = _find_command_differences(cmd1, cmd2)
            if differences:
                error_parts.append("\n     Differences:")
                for diff in differences:
                    error_parts.append(f"       - {diff}")
                error_parts.append("")  # blank line for readability

    def _apply_filters_before_record(
        self, interaction: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply filters before recording an interaction.

        Args:
            interaction: The interaction to filter

        Returns:
            Filtered interaction
        """
        __tracebackhide__ = True

        # Create a deep copy to prevent filters from mutating the original
        result = copy.deepcopy(interaction)
        for filter_instance in self.filters:
            result = filter_instance.before_record(result)
        return result

    def _apply_filters_before_playback(
        self, interaction: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply filters before replaying an interaction.

        Args:
            interaction: The interaction to filter

        Returns:
            Filtered interaction
        """
        __tracebackhide__ = True

        # Create a deep copy to prevent filters from mutating the original
        result = copy.deepcopy(interaction)
        for filter_instance in self.filters:
            result = filter_instance.before_playback(result)
        return result


class RecordingPopen:
    """Wrapper that records when process completes."""

    def __init__(self, real_proc, cmd, kwargs, start_time, vcr, target_list):
        self._proc = real_proc
        # Keep string commands as strings when shell=True
        self._cmd: str | list[str]
        if isinstance(cmd, str):
            self._cmd = cmd
        else:
            self._cmd = list(cmd)  # Ensure it's a list for non-string commands
        self._kwargs = kwargs
        self._start_time = start_time
        self._vcr = vcr
        self._target_list = target_list
        self._recorded = False

        # Note: Validation is now done in _intercept_popen before we get here

        # Copy through essential attributes
        self.pid = real_proc.pid
        self.returncode = None
        self.stdout = real_proc.stdout
        self.stderr = real_proc.stderr
        self.args = self._cmd  # Tests might access this

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # Ensure we record on exit if not already done
        if not self._recorded and self.returncode is not None:
            self._record_completion(None, None)
        return False

    def communicate(self, input=None, timeout=None):
        """Handle subprocess.run's use of communicate()."""
        # This is critical - subprocess.run uses communicate(), not wait()
        stdout, stderr = self._proc.communicate(input, timeout)

        # Update returncode
        self.returncode = self._proc.returncode

        # Record the interaction if not already done
        if not self._recorded:
            self._record_completion(stdout, stderr)

        return stdout, stderr

    def wait(self, timeout=None):
        """Wait for process completion and record."""
        exit_code = self._proc.wait(timeout)
        self.returncode = exit_code

        # For processes that don't use communicate()
        if not self._recorded:
            self._record_completion(None, None)

        return exit_code

    def poll(self):
        """Check if process has terminated."""
        result = self._proc.poll()
        if result is not None:
            self.returncode = result
        return result

    def terminate(self):
        """Terminate the process with SIGTERM (or platform equivalent)."""
        self._proc.terminate()

    def kill(self):
        """Kill the process with SIGKILL (or platform equivalent)."""
        self._proc.kill()

    def _record_completion(self, stdout_data, stderr_data):
        """Record the subprocess execution."""
        if self._recorded:
            return

        duration = time.time() - self._start_time

        # Handle different types of output
        stdout_final = self._prepare_output(stdout_data)
        stderr_final = self._prepare_output(stderr_data)

        # Build the interaction
        interaction = {
            "args": self._cmd,
            "kwargs": self._serialize_kwargs(self._kwargs),
            "duration": duration,
            "returncode": self.returncode or self._proc.returncode,
            "stdout": stdout_final,
            "stderr": stderr_final,
        }

        # Apply filters before recording
        if self._vcr.filters:
            interaction = self._vcr._apply_filters_before_record(interaction)

        # Record the interaction to the target list
        self._target_list.append(interaction)
        self._recorded = True

        logger.debug(
            f"Recorded interaction: cmd={self._cmd[:2] if isinstance(self._cmd, list) else self._cmd[:50]}..., returncode={self.returncode}"
        )

    def _prepare_output(self, data):
        """Prepare output for storage."""
        if data is None:
            return None

        # Convert bytes to string if possible
        if isinstance(data, bytes):
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError:
                # Store as base64 for binary data
                return {"_binary": True, "data": base64.b64encode(data).decode("ascii")}

        # Clean text output (string at this point)
        if isinstance(data, str):
            return self._clean_text_output(data)

        return data

    def _clean_text_output(self, text: str) -> str:
        """Remove control characters and trailing spaces from text."""
        import re

        # Remove control characters that YAML can't handle
        # Keep newlines, tabs, and other common whitespace
        text = re.sub(CONTROL_CHAR_REGEX, "", text)
        # Strip trailing spaces from each line to enable block literal format
        lines = text.split("\n")
        return "\n".join(line.rstrip() for line in lines)

    def _serialize_kwargs(self, kwargs):
        """Serialize kwargs for storage."""
        # Stage 1: Focus on kwargs that affect output handling
        serialized: dict[str, Any] = {}
        for key in [
            "stdout",
            "stderr",
            "text",
            "capture_output",
            "encoding",
            "errors",
            "cwd",
            "env",
        ]:
            if key in kwargs:
                try:
                    # Store actual values except for PIPE constant
                    if key in ["stdout", "stderr"] and kwargs[key] == subprocess.PIPE:
                        serialized[key] = PIPE_MARKER
                    elif key in ["stdout", "stderr"] and hasattr(kwargs[key], "mode"):
                        # This is a file handle - provide helpful error
                        raise SubprocessVCRError(
                            f"Cannot serialize file handle for {key}. "
                            f"Use subprocess.PIPE instead of file handles."
                        )
                    elif key == "cwd" and kwargs[key] is not None:
                        # Convert Path objects to string
                        serialized[key] = str(kwargs[key])
                    elif key == "env" and kwargs[key] is not None:
                        # Store environment variables
                        serialized[key] = dict(kwargs[key])
                    else:
                        serialized[key] = kwargs[key]
                except Exception as e:
                    # Provide detailed error for any serialization issue
                    raise SubprocessVCRError(
                        f"Cannot serialize {key}={type(kwargs[key]).__name__}: {e}"
                    ) from e
        return serialized


class SimpleMockPopen:
    """Simple mock for stage 1 - no threading."""

    def __init__(self, recording):
        self.recording = recording
        self.returncode = None
        self.pid = MOCK_PID  # Fixed dummy PID for replay mode
        self.args = recording.get("args", [])  # Tests access this

        # Store output for communicate()
        self._stdout_data = self._decode_output(recording.get("stdout"))
        self._stderr_data = self._decode_output(recording.get("stderr"))

        # Set up file-like objects if needed
        self.stdout = None
        self.stderr = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        return False

    def communicate(self, input=None, timeout=None):
        """Return recorded output - this is what subprocess.run uses."""
        # Mark as completed
        self.returncode = self.recording["returncode"]
        return (self._stdout_data, self._stderr_data)

    def wait(self, timeout=None):
        """Immediately return recorded exit code."""
        # Stage 1: No timing simulation
        self.returncode = self.recording["returncode"]
        return self.returncode

    def poll(self):
        """Always indicate process completed."""
        if self.returncode is None:
            self.returncode = self.recording["returncode"]
        return self.returncode

    def terminate(self):
        """Simulate process termination (no-op in replay mode)."""
        # In replay mode, the process has already completed
        # This is a no-op but we should ensure returncode is set
        if self.returncode is None:
            self.returncode = self.recording["returncode"]

    def kill(self):
        """Simulate process kill (no-op in replay mode)."""
        # In replay mode, the process has already completed
        # This is a no-op but we should ensure returncode is set
        if self.returncode is None:
            self.returncode = self.recording["returncode"]

    def _decode_output(self, data):
        """Decode output from storage format."""
        if data is None:
            return None
        if isinstance(data, dict) and data.get("_binary"):
            # Decode base64 binary data
            return base64.b64decode(data["data"])
        # Check if text mode was used in recording
        kwargs = self.recording.get("kwargs", {})
        if kwargs.get("text") or kwargs.get("encoding"):
            # Return as string for text mode
            encoding = kwargs.get("encoding", DEFAULT_ENCODING)
            return data if isinstance(data, str) else data.decode(encoding)
        else:
            # Return as bytes for binary mode
            if isinstance(data, str):
                return data.encode("utf-8")
            return data
