"""Test configuration for subprocess_vcr tests."""

import pytest

from subprocess_vcr.filters import PathFilter, PythonExecutableFilter

# The plugin is automatically loaded via entry points, we only need pytester
pytest_plugins = ["pytester"]


@pytest.fixture(scope="session")
def subprocess_vcr_config():
    """Global VCR configuration with standard filters for all tests.

    Note: This configuration only applies to subprocess-vcr's internal test suite.
    Users of the library need to define their own subprocess_vcr_config fixture
    in their conftest.py if they want global filters.
    """
    return {
        "filters": [
            PythonExecutableFilter(),  # Normalize Python executable paths
            PathFilter(),  # Normalize dynamic paths (temp dirs, home, CWD, etc.)
        ]
    }


@pytest.fixture
def project_dir(tmp_path, request):
    """Create a stable project directory for tests.

    This fixture creates a predictable directory name based on the test name,
    avoiding pytest-xdist's incremented paths (e.g., "test_foo0", "test_foo1").

    For a test named "test_fallback_with_path_matching", it creates "fallback_project".
    """
    # Get the test name without parametrization info
    test_name = request.node.name.split("[")[0]

    # Remove "test_" prefix and take first word
    if test_name.startswith("test_"):
        test_name = test_name[5:]

    # Take only the first word (before any underscore)
    first_word = test_name.split("_")[0]

    # Create the project directory
    project_path = tmp_path / f"{first_word}_project"
    project_path.mkdir()

    return project_path


@pytest.fixture(autouse=True)
def configure_pytester_asyncio(pytester):
    """Configure pytest-asyncio for pytester runs to avoid deprecation warnings."""
    # Create a pytest.ini file with asyncio configuration for isolated test runs
    pytester.makefile(
        ".ini",
        pytest="""
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
""",
    )


@pytest.fixture
def isolated_pytester(pytester, monkeypatch):
    """Pytester configured for complete plugin isolation.

    This fixture ensures tests run in a clean plugin environment by:
    1. Disabling automatic plugin loading via PYTEST_DISABLE_PLUGIN_AUTOLOAD
    2. Always using subprocess execution for true isolation
    3. Providing a standard config for subprocess_vcr tests

    Usage:
        def test_something(isolated_pytester):
            result = isolated_pytester.runpytest(
                "--subprocess-vcr=replay",
                "test_file.py"
            )
    """
    # Disable all plugin autoloading for complete isolation
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

    class IsolatedPytester:
        """Wrapper that ensures subprocess execution and provides standard config."""

        def __init__(self, pytester):
            self._pytester = pytester
            # Standard plugins that most subprocess_vcr tests need
            self.standard_plugins = ["-p", "subprocess_vcr.pytest_plugin"]

        def runpytest(self, *args, **kwargs):
            """Run pytest in subprocess with standard plugins loaded."""
            # Combine standard plugins with any provided args
            all_args = list(self.standard_plugins) + list(args)
            return self._pytester.runpytest_subprocess(*all_args, **kwargs)

        def runpytest_with_plugins(self, plugins, *args, **kwargs):
            """Run pytest with additional plugins beyond the standard set."""
            plugin_args = []
            for plugin in plugins:
                plugin_args.extend(["-p", plugin])
            all_args = list(self.standard_plugins) + plugin_args + list(args)
            return self._pytester.runpytest_subprocess(*all_args, **kwargs)

        # Delegate all other methods to the wrapped pytester
        def __getattr__(self, name):
            return getattr(self._pytester, name)

    return IsolatedPytester(pytester)
