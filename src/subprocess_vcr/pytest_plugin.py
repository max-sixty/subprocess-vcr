"""Pytest plugin for Subprocess VCR."""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest
from _pytest.runner import runtestprotocol
from pytest import Config, Item, StashKey

from .core import SubprocessVCR

# Define stash keys at module level - this is the canonical pytest pattern
# These are type-safe and avoid conflicts with other plugins
vcr_instance_key = StashKey[Optional[SubprocessVCR]]()
vcr_force_mode_key = StashKey[str]()
vcr_is_retry_key = StashKey[bool]()

# For session-level state, use config.stash
retried_tests_key: StashKey[set[str]] = StashKey()


def pytest_addoption(parser):
    """Add VCR options."""
    parser.addoption(
        "--subprocess-vcr",
        default="disable",
        choices=["record", "reset", "replay", "replay+reset", "disable"],
        help="Subprocess VCR mode: record (add new recordings), reset (replace existing), replay (replay only), replay+reset (replay with fallback to reset), disable (no VCR)",
    )


def pytest_configure(config: Config):
    """Register the subprocess_vcr markers and initialize session state."""
    config.addinivalue_line(
        "markers", "subprocess_vcr: mark test to use subprocess VCR recording/replay"
    )
    config.addinivalue_line(
        "markers",
        "no_subprocess_vcr: mark test to explicitly skip subprocess VCR patching",
    )

    # Initialize session-level state in config.stash
    config.stash[retried_tests_key] = set()


def pytest_sessionfinish(session):
    """Clean up retry state after session."""
    # Clean up via config.stash
    if retried_tests_key in getattr(session.config, "stash", {}):
        session.config.stash[retried_tests_key].clear()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item: Item, nextitem):
    """Retry entire test in reset mode if it fails during replay+reset mode."""
    # Only for subprocess_vcr tests in replay+reset mode
    marker = item.get_closest_marker("subprocess_vcr")
    if not marker:
        return None

    mode = item.config.getoption("--subprocess-vcr")
    if mode != "replay+reset":
        return None

    # Access session-level state from config.stash
    retried_tests = item.config.stash[retried_tests_key]

    # Skip if already retried
    if item.nodeid in retried_tests:
        return None

    # Run test normally (will use replay mode)
    reports = runtestprotocol(item, nextitem=nextitem, log=False)

    # Check for failure in setup or call phase (excluding teardown)
    # We don't retry on teardown failures as they indicate cleanup issues
    test_failed = any(r.failed for r in reports if r.when != "teardown")

    if test_failed:
        # Mark as retried using stash
        retried_tests.add(item.nodeid)

        # Force reset mode for retry using stash
        item.stash[vcr_force_mode_key] = "reset"

        # Clean up any existing VCR state from stash
        if vcr_instance_key in item.stash:
            vcr = item.stash[vcr_instance_key]
            if vcr:
                vcr.unpatch()
            # Clear the instance from stash so it gets recreated
            item.stash[vcr_instance_key] = None

        # Log retry (this will be visible in verbose mode)
        item.add_report_section(
            "",
            "subprocess-vcr-retry",
            f"Test {item.nodeid} failed in replay mode, retrying in reset mode...",
        )

        # Also print to stdout for better visibility during test runs
        if item.config.getoption("-v"):
            print(f"\n[RETRY] Retrying {item.nodeid} in reset mode after failure...")

        # Store that this is a retry so we can force the reset indicator
        item.stash[vcr_is_retry_key] = True

        # Run entire test again
        retry_reports = runtestprotocol(item, nextitem=nextitem, log=False)

        # Add retry info to the final report
        for report in retry_reports:
            if report.when == "call":
                if not hasattr(report, "sections"):
                    report.sections = []
                report.sections.append(
                    (
                        "subprocess-vcr-retry",
                        "This test was automatically retried in reset mode after failing in replay mode",
                    )
                )

        # Return retry reports
        return retry_reports

    # Return None to let pytest handle normally
    return None


@pytest.fixture(scope="session")
def subprocess_vcr_config(request):
    """Global VCR configuration fixture.

    Users can override this fixture in their conftest.py to provide
    global filter configuration.

    Example:
        @pytest.fixture(scope="session")
        def subprocess_vcr_config():
            return {
                "filters": [
                    PathFilter(),
                    RedactFilter(),
                ]
            }
    """
    return {}


@pytest.fixture(autouse=True)
def _subprocess_vcr_autouse(request, subprocess_vcr_config):
    """Auto-activate VCR for tests marked with subprocess_vcr."""
    # Skip if test explicitly disables subprocess_vcr
    if request.node.get_closest_marker("no_subprocess_vcr"):
        yield
        return

    # Only activate if test has the subprocess_vcr marker
    marker = request.node.get_closest_marker("subprocess_vcr")
    if not marker:
        yield
        return

    # Get mode from stash (for retries) or command line
    mode = request.node.stash.get(vcr_force_mode_key, None)
    if mode is None:
        mode = request.config.getoption("--subprocess-vcr")

    # Even in disable mode, we need to create the VCR instance
    # The VCR instance will handle not patching in disable mode

    # Get cassette path
    test_file = Path(request.module.__file__)
    test_name = request.node.name
    cassette_dir = test_file.parent / "_vcr_cassettes"
    cassette_path = cassette_dir / f"{test_file.stem}.{test_name}.yaml"

    # Get marker kwargs if any
    marker_kwargs = marker.kwargs if marker else {}

    # Get filters from marker and/or global config
    filters = []

    # Add global filters from subprocess_vcr_config fixture
    if "filters" in subprocess_vcr_config:
        filters.extend(subprocess_vcr_config["filters"])

    # Add per-test filters from marker
    if "filters" in marker_kwargs:
        test_filters = marker_kwargs["filters"]
        if not isinstance(test_filters, list):
            test_filters = [test_filters]
        filters.extend(test_filters)

    # Collect metadata for the cassette
    metadata = {
        "test_name": test_name,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.system() + "-" + platform.release(),
    }

    # Create VCR instance
    vcr = SubprocessVCR(
        cassette_path,
        mode,
        metadata=metadata,
        filters=filters,
    )
    vcr.patch()

    # Store VCR instance in stash for subprocess_vcr fixture and other hooks to access
    request.node.stash[vcr_instance_key] = vcr

    yield

    vcr.unpatch()


@pytest.fixture
def subprocess_vcr(request):
    """Provide access to the VCR instance for tests that need it."""
    # Get from stash instead of direct attribute
    vcr = request.node.stash.get(vcr_instance_key, None)
    if vcr is None:
        raise RuntimeError("subprocess_vcr fixture used without VCR being active")
    return vcr


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Transfer VCR action from VCR instance to test report and add failure context."""
    outcome = yield
    report = outcome.get_result()

    # Only process the 'call' phase (not setup or teardown)
    if call.when == "call":
        # Check for retry first using stash
        if item.stash.get(vcr_is_retry_key, False):
            report._subprocess_vcr_action = "reset"
        elif vcr_instance_key in item.stash:
            vcr = item.stash[vcr_instance_key]
            # Transfer VCR action for status reporting
            if vcr and hasattr(vcr, "cassette_action") and vcr.cassette_action:
                report._subprocess_vcr_action = vcr.cassette_action

        # Add VCR context to test failures
        if report.failed and vcr_instance_key in item.stash:
            vcr = item.stash[vcr_instance_key]
            if (
                vcr
                and hasattr(vcr, "cassette_action")
                and vcr.cassette_action == "replayed"
            ):
                # Add a section to the report with VCR information
                if not hasattr(report, "sections"):
                    report.sections = []

                report.sections.append(
                    (
                        "subprocess-vcr",
                        f"This test replayed subprocess calls from VCR cassette: {vcr.cassette_path.name}\n"
                        f"To re-record this test, run with: --subprocess-vcr=reset",
                    )
                )


def pytest_report_teststatus(report, config):
    """Customize test status reporting for VCR tests."""
    if report.when == "call" and hasattr(report, "outcome"):
        # Check if this test used subprocess_vcr and took an action
        if hasattr(report, "_subprocess_vcr_action") and report.outcome == "passed":
            action = report._subprocess_vcr_action

            if action == "reset":
                # Reset cassette - uppercase R like regtest
                return ("vcr_reset", "R", "RESET")
            elif action == "recorded":
                # New recording added - lowercase r
                return ("vcr_record", "r", "RECORDED")
            elif action == "replayed":
                # Successfully replayed from cassette - just use normal pass
                # We could use 'V' for verified, but normal '.' is cleaner
                return None

    # Return None to let pytest handle normally
    return None
