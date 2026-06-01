#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""
Test runner for LPMP test suite

This script runs the LPMP test suite with code coverage reporting.
It provides multiple execution modes and detailed reporting.

Usage:
    python run_tests.py              # Run all tests without coverage
    python run_tests.py --with-cov   # Run tests with coverage
    python run_tests.py --verbose    # Run with verbose output
    python run_tests.py --bundle /path/to/bundle  # Enable bundle regression tests
    python run_tests.py --bundle default            # Use built-in default bundle path
    python run_tests.py --bundle                    # Same as --bundle default
    python run_tests.py --model /path/to/model.yaml  # Enable model regression tests
"""

import argparse
from contextlib import redirect_stdout
import io
import os
import subprocess
import sys
import unittest

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True


class ColoredTestResult(unittest.TextTestResult):
    """Custom test result class with colored output"""

    def __init__(self, stream, descriptions, verbosity, verbose_mode=False):
        super().__init__(stream, descriptions, verbosity)
        self.test_results = []
        self.failures_details = []
        self.errors_details = []
        self.verbose_mode = verbose_mode
        self.start_time = None
        self._real_stderr = sys.__stderr__  # For progress dots when stdout is captured

    def startTest(self, test):
        super().startTest(test)
        self.current_test = test
        if self.verbose_mode:
            import time
            self.start_time = time.time()
            test_name = f"{test.__class__.__module__}.{test.__class__.__name__}.{test._testMethodName}"
            print(f"\n🔄 STARTING: {test_name}", flush=True)

    def addSuccess(self, test):
        super().addSuccess(test)
        test_name = test._testMethodName
        class_name = test.__class__.__name__
        full_name = f"{class_name}.{test_name}"
        self.test_results.append(
            (full_name, "PASS", "\033[92m"))  # Green

        if not self.verbose_mode:
            print('.', end='', flush=True, file=self._real_stderr)

        if self.verbose_mode:
            import time
            elapsed = time.time() - self.start_time if self.start_time else 0
            print(f"✅ PASSED: {full_name} ({elapsed:.3f}s)", flush=True)

    def addError(self, test, err):
        super().addError(test, err)
        test_name = test._testMethodName
        class_name = test.__class__.__name__
        full_name = f"{class_name}.{test_name}"
        self.test_results.append((full_name, "ERROR", "\033[91m"))  # Red
        self.errors_details.append(
            (full_name, self._exc_info_to_string(err, test)))

        if not self.verbose_mode:
            print('E', end='', flush=True, file=self._real_stderr)

        if self.verbose_mode:
            import time
            elapsed = time.time() - self.start_time if self.start_time else 0
            print(f"❌ ERROR: {full_name} ({elapsed:.3f}s)", flush=True)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        test_name = test._testMethodName
        class_name = test.__class__.__name__
        full_name = f"{class_name}.{test_name}"
        self.test_results.append((full_name, "FAIL", "\033[91m"))  # Red
        self.failures_details.append(
            (full_name, self._exc_info_to_string(err, test)))

        if not self.verbose_mode:
            print('F', end='', flush=True, file=self._real_stderr)

        if self.verbose_mode:
            import time
            elapsed = time.time() - self.start_time if self.start_time else 0
            print(f"❌ FAILED: {full_name} ({elapsed:.3f}s)", flush=True)

    def print_results(self):
        print('', file=self._real_stderr)  # Newline after progress dots
        print("\nLPMP Test Runner v1.0 - Test Results:")
        print("=" * 80)

        # Calculate maximum test name length for proper alignment
        max_length = max(
            len(test_name) for test_name, _, _ in self.test_results
        ) if self.test_results else 50
        # Add some padding and ensure minimum width
        width = max(max_length + 5, 55)

        for test_name, status, color in self.test_results:
            reset_color = "\033[0m"
            print(f"{test_name:<{width}} {color}{status}{reset_color}")

    def print_failure_details(self):
        if self.failures_details or self.errors_details:
            print("\n" + "=" * 60)
            print("FAILURE DETAILS")
            print("=" * 60)

            for test_name, details in self.failures_details + self.errors_details:
                print(f"\n{test_name}:")
                print("-" * 40)
                print(details)


class ColoredTestRunner(unittest.TextTestRunner):
    """Custom test runner with colored results"""

    def __init__(self, verbose_mode=False, **kwargs):
        super().__init__(**kwargs)
        self.verbose_mode = verbose_mode

    def _makeResult(self):
        return ColoredTestResult(
            self.stream, self.descriptions, self.verbosity, self.verbose_mode)


def run_tests_with_coverage():
    """Run tests with coverage reporting"""
    try:
        # Check if coverage is installed
        import coverage

        print("Running LPMP Test Suite with Code Coverage")
        print("Test Runner Version: v1.0")
        print("=" * 50)

        # Initialize coverage
        # Get parent directory (files/) for coverage
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cov = coverage.Coverage(source=[parent_dir], omit=['*/test/*'])
        cov.start()

        # Redirect ALL output (stdout and stderr) to file
        output_file = "/tmp/lpmptool_test_coverage.output"
        with open(output_file, 'w') as f:
            # Write header with version and LPMP tool info
            f.write("LPMP Test Suite Output\n")
            f.write("Test Runner Version: v1.0\n")
            f.write("LPMP Tool: Log Pattern Matching Profiler\n")
            f.write("=" * 50 + "\n\n")

            # Capture both stdout and stderr
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = f
            sys.stderr = f

            try:
                loader = unittest.TestLoader()
                suite = loader.discover('.', pattern='test_*.py')
                runner = ColoredTestRunner(verbosity=0, stream=f)
                result = runner.run(suite)
            finally:
                # Restore stdout and stderr
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        # Print colored results to console
        result.print_results()

        # Stop coverage and generate report
        cov.stop()
        cov.save()

        print("\n" + "=" * 60)
        print("CODE COVERAGE REPORT")
        print("=" * 60)

        # Capture coverage report to extract percentage
        coverage_output = io.StringIO()
        with redirect_stdout(coverage_output):
            cov.report(show_missing=True, file=coverage_output)

        coverage_text = coverage_output.getvalue()
        print(coverage_text)

        # Extract individual file coverage and overall
        coverage_pct = "unknown"
        lpmp_engine_cov = lpmp_output_cov = lpmp_graph_cov = lpmp_utils_cov = lpmptool_cov = "N/A"
        lines = coverage_text.strip().split('\n')
        for line in lines:
            if 'lpmp_engine.py' in line:
                parts = line.split()
                for part in parts:
                    if '%' in part:
                        lpmp_engine_cov = part
                        break
            elif 'lpmp_output.py' in line:
                parts = line.split()
                for part in parts:
                    if '%' in part:
                        lpmp_output_cov = part
                        break
            elif 'lpmp_graph.py' in line:
                parts = line.split()
                for part in parts:
                    if '%' in part:
                        lpmp_graph_cov = part
                        break
            elif 'lpmp_utils.py' in line:
                parts = line.split()
                for part in parts:
                    if '%' in part:
                        lpmp_utils_cov = part
                        break
            elif 'lpmptool' in line and 'lpmptool.py' not in line:
                parts = line.split()
                for part in parts:
                    if '%' in part:
                        lpmptool_cov = part
                        break
            elif 'TOTAL' in line:
                parts = line.split()
                for part in parts:
                    if '%' in part:
                        coverage_pct = part
                        break

        # Generate HTML report (optional)
        try:
            # Only generate HTML if explicitly requested or if environment variable is set
            if os.environ.get('LPMP_COVERAGE_HTML', '').lower() in ('1', 'true', 'yes'):
                cov.html_report(directory='coverage_html')
        except Exception:
            pass

        # Print concise coverage summary
        skipped_count = len(result.skipped)
        failed_count = len(result.failures) + len(result.errors)
        passed_count = result.testsRun - failed_count - skipped_count

        print("\n" + "=" * 60)
        print(f"lpmp_engine.py : {lpmp_engine_cov} coverage")
        print(f"lpmp_output.py : {lpmp_output_cov} coverage")
        print(f"lpmp_graph.py  : {lpmp_graph_cov} coverage")
        print(f"lpmp_utils.py  : {lpmp_utils_cov} coverage")
        print(f"lpmptool.py    : {lpmptool_cov} coverage")
        skip_info = f" ({skipped_count} skipped)" if skipped_count else ""
        print(f"Overall        : {coverage_pct} coverage with"
              f" {passed_count} of {result.testsRun} tests passing{skip_info}")
        print("=" * 60)

        # Report success/failure with coverage
        if result.wasSuccessful():
            print(f"\n\033[92m✅ {passed_count} tests passed\033[0m")
            if skipped_count:
                print(f"   ({skipped_count} tests skipped)")
            print(f"Full test output saved to: {output_file}")
        else:
            print(f"\n\033[91m❌ Tests failed "
                  f"({failed_count}/{result.testsRun} failed)\033[0m")
            print(f"Full test output saved to: {output_file}")
            result.print_failure_details()

        return result.wasSuccessful()

    except ImportError:
        print("Coverage module not installed.")
        print("Install with: pip install coverage")
        return run_tests_without_coverage()


def run_tests_without_coverage(verbose_mode=False):
    """Run tests without coverage reporting"""
    print("Running LPMP Test Suite (no coverage)")
    print("Test Runner Version: v1.0")
    if verbose_mode:
        print("Verbose Mode: ON - Will show test names as they run")
    print("=" * 40)

    if verbose_mode:
        # In verbose mode, don't redirect output so we can see test names
        loader = unittest.TestLoader()
        suite = loader.discover('.', pattern='test_*.py')
        runner = ColoredTestRunner(verbosity=2, verbose_mode=True)
        result = runner.run(suite)

        # Print summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        result.print_results()
    else:
        # Redirect ALL output (stdout and stderr) to file
        output_file = "/tmp/lpmptool_test_no_coverage.output"
        with open(output_file, 'w') as f:
            # Write header with version and LPMP tool info
            f.write("LPMP Test Suite Output\n")
            f.write("Test Runner Version: v1.0\n")
            f.write("LPMP Tool: Log Pattern Matching Profiler\n")
            f.write("=" * 50 + "\n\n")

            # Capture both stdout and stderr
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = f
            sys.stderr = f

            try:
                loader = unittest.TestLoader()
                suite = loader.discover('.', pattern='test_*.py')
                runner = ColoredTestRunner(verbosity=0, stream=f)
                result = runner.run(suite)
            finally:
                # Restore stdout and stderr
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        # Print colored results to console
        result.print_results()

    # Report success/failure
    skipped_count = len(result.skipped)
    failed_count = len(result.failures) + len(result.errors)
    passed_count = result.testsRun - failed_count - skipped_count

    if result.wasSuccessful():
        skip_info = f" ({skipped_count} skipped)" if skipped_count else ""
        print(f"\n\033[92m✅ {passed_count} of {result.testsRun}"
              f" tests passed{skip_info}\033[0m")
        if not verbose_mode:
            print(f"Full test output saved to: {output_file}")
    else:
        print(f"\n\033[91m❌ Tests failed "
              f"({failed_count}/{result.testsRun} failed)\033[0m")
        if not verbose_mode:
            print(f"Full test output saved to: {output_file}")
        result.print_failure_details()

    return result.wasSuccessful()


def run_with_pytest():
    """Run tests using pytest with coverage"""
    try:
        # Check if pytest is available
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', '--version'],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise FileNotFoundError("pytest not available")

        cmd = [
            sys.executable, '-m', 'pytest',
            'test_lpmp.py',
            '--cov=../lpmp_utils',
            '--cov=../lpmp_engine',
            '--cov=../lpmptool',
            '--cov-report=term-missing',
            '--cov-report=html:coverage_html'
        ]

        print("Running tests with pytest and coverage...")
        print("Test Runner Version: v1.0")
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Save pytest output to file with LPMP tool info
        pytest_output_file = "/tmp/lpmptool_test_pytest.output"
        with open(pytest_output_file, 'w') as f:
            f.write("LPMP Test Suite Output (pytest)\n")
            f.write("Test Runner Version: v1.0\n")
            f.write("LPMP Tool: Log Pattern Matching Profiler\n")
            f.write("=" * 50 + "\n\n")
            f.write(result.stdout)
            if result.stderr:
                f.write("\nSTDERR:\n")
                f.write(result.stderr)

        # Print the output
        print(result.stdout)
        if result.stderr:
            print(result.stderr)

        # Check if tests passed and extract coverage
        if result.returncode == 0:
            # Extract coverage percentage from output
            coverage_line = None
            for line in result.stdout.split('\n'):
                if 'TOTAL' in line and '%' in line:
                    coverage_line = line
                    break

            if coverage_line:
                # Extract percentage (last column with %)
                parts = coverage_line.split()
                for part in reversed(parts):
                    if '%' in part:
                        coverage_pct = part
                        break
                print(f"\n✅ Tests passed with {coverage_pct} coverage")
            else:
                print("\n✅ Tests passed")
            return True
        else:
            print("\n❌ Tests failed")
            return False

    except (FileNotFoundError, subprocess.CalledProcessError):
        print("pytest not found. Falling back to unittest with coverage...")
        return run_tests_with_coverage()


def test_runner_arguments():
    """Test the test runner argument handling"""
    print("Testing Test Runner Argument Handling")
    print("=" * 40)

    test_cases = [
        ([], "default (coverage)"),
        (['--with-cov'], "with coverage"),
        (['--pytest'], "pytest mode"),
        (['--verbose'], "verbose mode"),
        (['--help'], "help display"),
        (['--invalid'], "invalid argument (should fail)"),
        (['--with-cov', '--pytest'], "conflicting args"),
    ]

    passed = 0
    failed = 0

    for args, description in test_cases:
        try:
            print(f"Testing {description:<25} ", end="")

            if '--help' in args:
                # Help should exit with 0
                result = subprocess.run(
                    [sys.executable, __file__] + args,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0 and 'usage:' in result.stdout:
                    print("\033[92mPASS\033[0m")
                    passed += 1
                else:
                    print("\033[91mFAIL\033[0m")
                    failed += 1
            elif '--invalid' in args:
                # Invalid args should fail
                result = subprocess.run(
                    [sys.executable, __file__] + args,
                    capture_output=True, text=True)
                if (result.returncode != 0 and
                        'unrecognized arguments' in result.stderr):
                    print("\033[92mPASS\033[0m")
                    passed += 1
                else:
                    print("\033[91mFAIL\033[0m")
                    failed += 1
            else:
                # Valid args should parse without error
                parser = argparse.ArgumentParser()
                parser.add_argument('--test', action='store_true')
                parser.add_argument('--with-cov', action='store_true')
                parser.add_argument('--pytest', action='store_true')
                parser.add_argument('--verbose', action='store_true')

                parsed_args = parser.parse_args(args)
                print("\033[92mPASS\033[0m")
                passed += 1

        except Exception as e:
            print(f"\033[91mFAIL\033[0m ({str(e)})")
            failed += 1

    print(f"\nArgument Handling Tests: {passed} passed, {failed} failed")

    if failed == 0:
        print("\033[92m✅ All argument handling tests passed\033[0m")
        return True
    else:
        print("\033[91m❌ Some argument handling tests failed\033[0m")
        return False


def main():
    parser = argparse.ArgumentParser(description='Run LPMP test suite')
    parser.add_argument(
        '--test', action='store_true',
        help='Test the test runner itself')
    parser.add_argument(
        '--with-cov', action='store_true',
        help='Run tests with coverage')
    parser.add_argument(
        '--bundle', '-b', nargs='?', const='default', default=None,
        help='Enable bundle regression tests (path or "default" for built-in path)')
    parser.add_argument(
        '--model', default=None,
        help='Path to model file for optional regression tests')
    parser.add_argument(
        '--pytest', action='store_true',
        help='Use pytest instead of unittest')
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Verbose output - show test names as they run')

    args = parser.parse_args()

    # Change to test directory
    test_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(test_dir)

    # Expose bundle path via environment variable for test discovery
    if args.bundle:
        bundle_path = args.bundle
        if bundle_path == 'default':
            # Use internal default path
            bundle_path = '/localdisk/lpmptool_demo/TIMELINE/ALL_NODES_20260227.190103'
        if not os.path.isdir(bundle_path):
            print(f"Error: Bundle path '{bundle_path}' not found or is not a directory", file=sys.stderr)
            sys.exit(1)
        os.environ['LPMP_TEST_BUNDLE'] = bundle_path
        print(f"Bundle regression tests enabled: {bundle_path}")

    # Expose model path via environment variable for test discovery
    if args.model:
        if not os.path.isfile(args.model):
            print(f"Error: Model file '{args.model}' not found", file=sys.stderr)
            sys.exit(1)
        os.environ['LPMP_TEST_MODEL'] = os.path.abspath(args.model)
        print(f"Model regression tests enabled: {args.model}")

    # Test the test runner itself
    if args.test:
        success = test_runner_arguments()
        sys.exit(0 if success else 1)

    success = False

    if args.pytest:
        success = run_with_pytest()
    elif args.with_cov:
        success = run_tests_with_coverage()
    else:
        success = run_tests_without_coverage(args.verbose)

    # Report skipped bundle tests if --bundle was not provided
    if not args.bundle and not os.environ.get('LPMP_TEST_BUNDLE'):
        print("\nNote: 10 bundle regression tests were skipped.")
        print("  Use --bundle <path> (bundle with 2+ controllers and 1+ other node)")
        print("  or --bundle default to enable them.")

    # Exit with appropriate code - success/failure already reported
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
