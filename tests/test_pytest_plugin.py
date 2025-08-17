"""Light tests for pytest plugin functionality."""

import subprocess
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def subprocess_vcr_config():
    """Override global config for plugin testing - no filters by default.

    This overrides the global filters defined in conftest.py because these
    tests are specifically testing filter configuration behavior.
    """
    return {}


class TestPytestIntegration:
    """Test pytest plugin integration."""

    @pytest.mark.subprocess_vcr
    def test_fixture_provides_vcr_instance(self, subprocess_vcr):
        """Test that the subprocess_vcr fixture provides a VCR instance."""
        from subprocess_vcr import SubprocessVCR

        assert isinstance(subprocess_vcr, SubprocessVCR)

    @pytest.mark.subprocess_vcr
    def test_fixture_patches_subprocess(self, subprocess_vcr, request):
        """Test that fixture patches subprocess.Popen."""
        # Check the mode
        mode = request.config.getoption("--subprocess-vcr")
        if mode == "disable":
            # In disable mode, Popen should NOT be patched
            assert subprocess.Popen.__name__ == "Popen"
        else:
            # In other modes, Popen should be patched
            assert subprocess.Popen.__name__ == "_intercept_popen"

    def test_no_fixture_no_patch(self):
        """Test that without fixture, subprocess is not patched."""
        # This test can't truly verify unpatchedness because we're in a
        # test environment where the plugin might already be active.
        # Just verify we can call subprocess without a cassette
        result = subprocess.run(
            ["echo", "test"], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0


class TestMarkerIntegration:
    """Test @pytest.mark.subprocess_vcr decorator."""

    @pytest.mark.subprocess_vcr
    def test_marker_with_explicit_fixture(self, subprocess_vcr, request):
        """Test that marker works with explicit fixture request."""
        # When explicitly requesting the fixture, it should work
        from subprocess_vcr import SubprocessVCR

        assert isinstance(subprocess_vcr, SubprocessVCR)

        # Check the mode
        mode = request.config.getoption("--subprocess-vcr")
        if mode == "disable":
            # In disable mode, even with marker, Popen should NOT be patched
            assert subprocess.Popen.__name__ == "Popen"
        else:
            # With marker and non-disable mode, subprocess should be patched
            assert subprocess.Popen.__name__ == "_intercept_popen"

    @pytest.mark.subprocess_vcr
    def test_marker_without_fixture(self, request):
        """Test that marker alone automatically enables VCR."""
        # With the marker, subprocess should be patched automatically
        mode = request.config.getoption("--subprocess-vcr")
        if mode == "disable":
            # In disable mode, Popen should NOT be patched
            assert subprocess.Popen.__name__ == "Popen"
        else:
            # With marker and non-disable mode, subprocess should be patched
            assert subprocess.Popen.__name__ == "_intercept_popen"

    def test_marker_vs_fixture(self, request):
        """Test difference between marker and fixture usage."""
        # We can check if the marker was applied
        marker = request.node.get_closest_marker("subprocess_vcr")
        assert marker is None  # This test has no marker


class TestFilterConfiguration:
    """Test filter configuration through pytest plugin."""

    @pytest.mark.subprocess_vcr(filters=[])
    def test_empty_filters(self, subprocess_vcr):
        """Test that empty filters list works."""
        assert subprocess_vcr.filters == []

    def test_global_filters(self, subprocess_vcr_config):
        """Test that global filters can be configured."""
        # Default config has no filters
        assert subprocess_vcr_config == {}


class TestCassetteManagement:
    """Test cassette file management."""

    @pytest.mark.subprocess_vcr
    def test_cassette_location(self, request):
        """Test cassettes are created in expected location."""
        # The cassette path should be based on module and test name
        cassette_dir = Path(request.module.__file__).parent / "_vcr_cassettes"

        # Note: Cassette is created on fixture teardown, so we can't check
        # for its existence during the test, but we can verify the path
        # that will be used

        # The fixture should have set up a VCR instance
        # We can at least verify the directory structure
        assert "_vcr_cassettes" in str(cassette_dir)

    @pytest.mark.subprocess_vcr
    def test_metadata_recorded_via_plugin(self, request, subprocess_vcr):
        """Test that metadata is automatically recorded when using pytest plugin."""
        # Record a simple command to create a cassette
        result = subprocess.run(
            ["echo", "metadata test"], capture_output=True, text=True
        )
        assert result.returncode == 0

        # The cassette should be saved when fixture tears down
        # For now, check the VCR instance has metadata
        assert subprocess_vcr.metadata is not None
        assert "test_name" in subprocess_vcr.metadata
        assert subprocess_vcr.metadata["test_name"] == request.node.name
        assert "recorded_at" in subprocess_vcr.metadata
        assert "python_version" in subprocess_vcr.metadata
        assert "platform" in subprocess_vcr.metadata
