"""Integration tests for subprocess_vcr pytest plugin.

These tests verify that the plugin works correctly in real pytest scenarios.

Assertion Pattern Guidelines:
- Use result.assert_outcomes() for standard pytest outcomes (passed/failed/errors)
- Use direct string checking for VCR-specific status markers (vcr_reset, vcr_record)
- Use result.stdout.fnmatch_lines() for pattern matching in output
"""


class TestPytestPluginIntegration:
    """Test real-world pytest plugin usage scenarios."""

    def test_plugin_with_multiple_modes(self, isolated_pytester):
        """Test that the plugin works correctly across different modes."""
        isolated_pytester.makepyfile(
            test_modes="""
            import subprocess
            import pytest

            @pytest.mark.subprocess_vcr
            def test_echo_command(subprocess_vcr):
                result = subprocess.run(
                    ["echo", "hello world"],
                    capture_output=True,
                    text=True
                )
                assert result.returncode == 0
                assert "hello world" in result.stdout
        """
        )

        # First run in reset mode to create cassette
        result = isolated_pytester.runpytest("-v", "--subprocess-vcr=reset")
        # VCR-specific: In reset mode, tests show custom status marker
        assert "1 vcr_reset" in result.stdout.str()

        # Verify cassette was created
        cassette_dir = isolated_pytester.path / "_vcr_cassettes"
        assert cassette_dir.exists()
        cassettes = list(cassette_dir.glob("*.yaml"))
        assert len(cassettes) == 1

        # Run in replay mode
        result = isolated_pytester.runpytest("-v", "--subprocess-vcr=replay")
        # Standard pytest: In replay mode, tests pass normally
        result.assert_outcomes(passed=1)

    def test_plugin_with_custom_filters(self, isolated_pytester):
        """Test that custom filters work through the plugin."""
        isolated_pytester.makepyfile(
            test_filters="""
            import subprocess
            import pytest
            from pathlib import Path
            from subprocess_vcr.filters import PathFilter

            @pytest.mark.subprocess_vcr(filters=[PathFilter()])
            def test_with_cwd_filter(subprocess_vcr):
                # This path will be normalized
                cwd = Path.cwd()
                result = subprocess.run(
                    ["echo", str(cwd / "file.txt")],
                    capture_output=True,
                    text=True
                )
                assert result.returncode == 0
                assert "file.txt" in result.stdout
        """
        )

        # Run test
        result = isolated_pytester.runpytest("-v", "--subprocess-vcr=reset")
        # VCR-specific: In reset mode, tests show custom status marker
        assert "1 vcr_reset" in result.stdout.str()

    def test_plugin_with_parametrized_tests(self, isolated_pytester):
        """Test that the plugin works with pytest parametrize."""
        isolated_pytester.makepyfile(
            test_parametrized="""
            import subprocess
            import pytest

            @pytest.mark.subprocess_vcr
            @pytest.mark.parametrize("message", ["hello", "world", "test"])
            def test_echo_parametrized(subprocess_vcr, message):
                result = subprocess.run(
                    ["echo", message],
                    capture_output=True,
                    text=True
                )
                assert result.returncode == 0
                assert message in result.stdout
        """
        )

        # Run tests
        result = isolated_pytester.runpytest("-v", "--subprocess-vcr=reset")
        # VCR-specific: Multiple parametrized tests show multiple vcr_reset markers
        assert "3 vcr_reset" in result.stdout.str()

        # Verify separate cassettes for each parameter
        cassette_dir = isolated_pytester.path / "_vcr_cassettes"
        cassettes = list(cassette_dir.glob("*.yaml"))
        assert len(cassettes) == 3  # One for each parameter value

    def test_plugin_disable_mode(self, isolated_pytester):
        """Test that disable mode bypasses VCR completely."""
        isolated_pytester.makepyfile(
            test_disable="""
            import subprocess
            import pytest

            @pytest.mark.subprocess_vcr
            def test_in_disable_mode(subprocess_vcr):
                # This should run the actual command
                result = subprocess.run(
                    ["echo", "disable mode test"],
                    capture_output=True,
                    text=True
                )
                assert result.returncode == 0
                assert "disable mode test" in result.stdout
        """
        )

        # Run in disable mode
        result = isolated_pytester.runpytest("-v", "--subprocess-vcr=disable")
        # Standard pytest: Disable mode runs tests normally without VCR
        result.assert_outcomes(passed=1)

        # Verify no cassette was created
        cassette_dir = isolated_pytester.path / "_vcr_cassettes"
        assert not cassette_dir.exists()

    def test_plugin_error_handling(self, isolated_pytester):
        """Test that plugin handles errors gracefully."""
        isolated_pytester.makepyfile(
            test_errors="""
            import subprocess
            import pytest

            @pytest.mark.subprocess_vcr
            def test_command_not_found(subprocess_vcr):
                # This should fail in replay mode if not recorded
                result = subprocess.run(
                    ["echo", "test"],
                    capture_output=True,
                    text=True
                )
                assert result.returncode == 0
        """
        )

        # Run in replay mode without a cassette - should fail
        result = isolated_pytester.runpytest("-v", "--subprocess-vcr=replay")
        # Standard pytest: Missing cassette causes test failure
        result.assert_outcomes(failed=1)
        # Pattern matching: Verify specific error message appears
        result.stdout.fnmatch_lines(["*No recording found*"])

    def test_cassette_path_resolution(self, isolated_pytester):
        """Test that cassettes are created in the correct location."""
        # Create a nested test structure
        test_dir = isolated_pytester.path / "tests" / "unit"
        test_dir.mkdir(parents=True)

        isolated_pytester.makepyfile(
            **{
                "tests/unit/test_nested.py": """
            import subprocess
            import pytest

            @pytest.mark.subprocess_vcr
            def test_nested_location(subprocess_vcr):
                result = subprocess.run(
                    ["echo", "nested test"],
                    capture_output=True,
                    text=True
                )
                assert result.returncode == 0
        """
            }
        )

        # Run test
        result = isolated_pytester.runpytest(
            "tests/unit/test_nested.py",
            "-v",
            "--subprocess-vcr=reset",
        )
        # VCR-specific: In reset mode, tests show custom status marker
        assert "1 vcr_reset" in result.stdout.str()

        # Verify cassette is in the right place
        cassette_dir = test_dir / "_vcr_cassettes"
        assert cassette_dir.exists()
        cassettes = list(cassette_dir.glob("*.yaml"))
        assert len(cassettes) == 1
        assert "test_nested.test_nested_location" in cassettes[0].name
