#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for Log Pattern Matching Profiler (LPMP)

This test suite covers:
- Timestamp parsing
- Variable substitution
- Duration formatting
- Log line formatting
- Bundle host detection
- File handling and pattern searching
- Wildcard expansion
- Timeline block processing
- Optional block warnings
- Error handling
- Integration tests
- Edge cases

See also: test_model.py, test_process_blocks.py, test_cli_arguments.py
"""

from datetime import datetime
import gzip
from io import StringIO
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import apply_variable_substitution  # noqa: E402
from lpmp_engine import find_pattern_in_files        # noqa: E402
from lpmp_engine import process_blocks_auto_detect   # noqa: E402
from lpmp_utils import detect_bundle_hosts           # noqa: E402
from lpmp_utils import expand_and_sort_log_files     # noqa: E402
from lpmp_utils import format_duration               # noqa: E402
from lpmp_utils import format_log_line_for_output    # noqa: E402
from lpmp_utils import load_model                    # noqa: E402
from lpmp_utils import parse_timestamp               # noqa: E402
from lpmp_utils import substitute_variables          # noqa: E402
import lpmptool                                      # noqa: E402 - For main() function
from test_base import LPMPTestBase                   # noqa: E402


class TestTimestampParsing(LPMPTestBase):
    """Test timestamp parsing functionality"""

    def test_parse_sysinv_timestamp(self):
        """Test parsing sysinv format timestamps"""
        line = "sysinv 2024-01-06 12:30:45.123 some message"
        result = parse_timestamp(line)
        expected = datetime(2024, 1, 6, 12, 30, 45, 123000)
        self.assertEqual(result, expected)

    def test_parse_iso_timestamp(self):
        """Test parsing ISO format timestamps"""
        line = "2024-01-06T12:30:45.123 some message"
        result = parse_timestamp(line)
        expected = datetime(2024, 1, 6, 12, 30, 45, 123000)
        self.assertEqual(result, expected)

    def test_parse_invalid_timestamp(self):
        """Test handling of invalid timestamps"""
        line = "invalid timestamp format"
        result = parse_timestamp(line)
        self.assertIsNone(result)

    def test_parse_malformed_sysinv(self):
        """Test handling of malformed sysinv timestamps"""
        line = "sysinv 2024-13-45 25:70:90.999 invalid"
        result = parse_timestamp(line)
        self.assertIsNone(result)


class TestVariableSubstitution(LPMPTestBase):
    """Test variable substitution functionality"""

    def test_substitute_hostname(self):
        """Test hostname variable substitution"""
        text = "{hostname} Unlock Action"
        variables = {"hostname": "controller-0"}
        result = substitute_variables(text, variables)
        self.assertEqual(result, "controller-0 Unlock Action")

    def test_substitute_multiple_variables(self):
        """Test multiple variable substitution"""
        text = "{hostname} service {service} status"
        variables = {"hostname": "controller-0", "service": "nova"}
        result = substitute_variables(text, variables)
        self.assertEqual(result, "controller-0 service nova status")

    def test_substitute_missing_variable(self):
        """Test handling of missing variables"""
        text = "{hostname} {missing} Action"
        variables = {"hostname": "controller-0"}
        with patch('sys.stderr', new_callable=StringIO):
            result = substitute_variables(text, variables)
        self.assertEqual(result, "{hostname} {missing} Action")

    def test_bundle_mode_hostname_substitution(self):
        """Test hostname variable substitution in bundle mode"""
        # Test that blocks get fresh copies with correct hostname
        original_blocks = [
            {
                'label': '{hostname} Mtce',
                'file': 'mtcAgent.log',
                'timeline': ['maintenance']
            }
        ]

        # Simulate bundle mode processing for different hosts
        hostnames = ['controller-0', 'controller-1', 'worker-0']

        for hostname in hostnames:
            # Create fresh copies (simulating bundle mode)
            blocks = [block.copy() for block in original_blocks]
            variables = {'hostname': hostname}

            # Apply variable substitution
            apply_variable_substitution(blocks, variables)

            # Verify the hostname was substituted correctly
            expected_label = f"{hostname} Mtce"
            self.assertEqual(blocks[0]['label'], expected_label)


class TestFormatDuration(LPMPTestBase):
    """Test duration formatting functionality"""

    def test_format_seconds(self):
        """Test formatting seconds"""
        result = format_duration(5.123)
        self.assertEqual(result, "00:00:05.123")

    def test_format_minutes(self):
        """Test formatting minutes and seconds"""
        result = format_duration(125.456)
        self.assertEqual(result, "00:02:05.456")

    def test_format_hours(self):
        """Test formatting hours, minutes, and seconds"""
        result = format_duration(3665.789)
        self.assertEqual(result, "01:01:05.789")


class TestLogLineFormatting(LPMPTestBase):
    """Test log line formatting for output"""

    def test_format_sysinv_log_line(self):
        """Test formatting sysinv log lines"""
        line = "sysinv 2024-01-06 12:30:45.123 message"
        filename = "sysinv.log"
        result = format_log_line_for_output(line, filename)
        self.assertEqual(result, "2024-01-06 12:30:45.123 message")

    def test_format_regular_log_line(self):
        """Test formatting regular log lines"""
        line = "2024-01-06T12:30:45.123 message"
        filename = "app.log"
        result = format_log_line_for_output(line, filename)
        self.assertEqual(result, "2024-01-06T12:30:45.123 message")


class TestBundleHostDetection(LPMPTestBase):
    """Test bundle host detection functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_detect_valid_bundle_hosts(self):
        """Test detection of valid bundle hosts with same date"""
        os.makedirs(os.path.join(self.temp_dir, 'controller-0_20251218.082339'))
        os.makedirs(os.path.join(self.temp_dir, 'controller-1_20251218.082339'))
        os.makedirs(os.path.join(self.temp_dir, 'worker-0_20251218.082339'))

        hostnames, dated_dirs = detect_bundle_hosts(self.temp_dir)
        self.assertEqual(hostnames, ['controller-0', 'controller-1', 'worker-0'])
        self.assertEqual(
            dated_dirs,
            [
                'controller-0_20251218.082339',
                'controller-1_20251218.082339',
                'worker-0_20251218.082339'
            ]
        )

    def test_detect_multiple_hosts_same_date(self):
        """Test detection of multiple hosts with same date"""
        os.makedirs(os.path.join(self.temp_dir, 'controller-0_20251218.082339'))
        os.makedirs(os.path.join(self.temp_dir, 'controller-1_20251218.082339'))
        os.makedirs(os.path.join(self.temp_dir, 'worker-0_20251218.082339'))
        os.makedirs(os.path.join(self.temp_dir, 'worker-1_20251218.082339'))
        os.makedirs(os.path.join(self.temp_dir, 'storage-0_20251218.082339'))

        hostnames, dated_dirs = detect_bundle_hosts(self.temp_dir)
        self.assertEqual(len(hostnames), 5)
        self.assertEqual(len(dated_dirs), 5)

    def test_detect_system_root_returns_empty(self):
        """Test system root returns empty lists"""
        hostnames, dated_dirs = detect_bundle_hosts('/')
        self.assertEqual(hostnames, [])
        self.assertEqual(dated_dirs, [])

    def test_detect_mixed_date_parts_error(self):
        """Test error when bundle hosts have different date parts"""
        os.makedirs(os.path.join(self.temp_dir, 'controller-0_20251218.082339'))
        os.makedirs(os.path.join(self.temp_dir, 'controller-1_20251219.082339'))

        with self.assertRaises(SystemExit):
            detect_bundle_hosts(self.temp_dir)

    def test_detect_no_bundle_hosts_error(self):
        """Test error when no bundle hosts found"""
        os.makedirs(os.path.join(self.temp_dir, 'some_other_dir'))

        with self.assertRaises(SystemExit):
            detect_bundle_hosts(self.temp_dir)

    def test_detect_bundle_hosts_verbose(self):
        """Test bundle host detection with verbose output"""
        os.makedirs(os.path.join(self.temp_dir, 'controller-0_20251218.082339'))
        os.makedirs(os.path.join(self.temp_dir, 'controller-1_20251218.082339'))

        # Set verbose level to enable vlog1 output
        from lpmp_utils import set_verbose_level
        set_verbose_level(1)

        with patch('builtins.print') as mock_print:
            hostnames, dated_dirs = detect_bundle_hosts(self.temp_dir)
            self.assertEqual(mock_print.call_count, 2)
            calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any('bundle_host_list' in call for call in calls))
            self.assertTrue(any('bundle_host_list_dated' in call for call in calls))

        # Reset verbose level
        set_verbose_level(0)


class TestFileHandling(unittest.TestCase):
    """Test file handling and pattern searching"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")
        self.gz_file = os.path.join(self.temp_dir, "test.log.gz")

    def tearDown(self):
        """Clean up test fixtures"""
        for f in [self.log_file, self.gz_file]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_find_pattern_in_regular_file(self):
        """Test finding pattern in regular log file"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 target pattern here
2024-01-06T10:02:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        result = find_pattern_in_files(
            self.temp_dir, "test.log", "target pattern"
        )

        self.assertIsNotNone(result)
        timestamp, pos, line, filename = result
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 1, 0))
        self.assertIn("target pattern", line)
        self.assertEqual(filename, "test.log")

    def test_find_pattern_in_gzipped_file(self):
        """Test finding pattern in gzipped log file"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 target pattern here
2024-01-06T10:02:00.000 last message"""

        with gzip.open(self.gz_file, 'wt') as f:
            f.write(log_content)

        result = find_pattern_in_files(
            self.temp_dir, "test.log.gz", "target pattern"
        )

        self.assertIsNotNone(result)
        timestamp, pos, line, filename = result
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 1, 0))
        self.assertIn("target pattern", line)
        self.assertEqual(filename, "test.log.gz")

    def test_pattern_not_found(self):
        """Test handling when pattern is not found"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 second message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        result = find_pattern_in_files(
            self.temp_dir, "test.log", "missing pattern"
        )

        self.assertIsNone(result)

    def test_file_not_found(self):
        """Test handling when log file does not exist"""
        result = find_pattern_in_files(
            self.temp_dir, "nonexistent.log", "any pattern"
        )

        self.assertIsNone(result)

    def test_corrupted_gzip_file(self):
        """Test handling corrupted gzip files"""
        # Create a file with .gz extension but invalid gzip content
        with open(self.gz_file, 'w') as f:
            f.write("This is not valid gzip content")

        result = find_pattern_in_files(
            self.temp_dir, "test.log.gz", "any pattern"
        )

        # Should handle the error gracefully and return None
        self.assertIsNone(result)

    def test_empty_file(self):
        """Test handling empty log files"""
        # Create empty file
        with open(self.log_file, 'w') as f:
            pass

        result = find_pattern_in_files(
            self.temp_dir, "test.log", "any pattern"
        )

        self.assertIsNone(result)

    def test_file_without_timestamps(self):
        """Test handling files with lines that have no valid timestamps"""
        log_content = """line without timestamp
another line without timestamp
yet another line"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        result = find_pattern_in_files(
            self.temp_dir, "test.log", "without timestamp"
        )

        # Should return None because no valid timestamps found
        self.assertIsNone(result)


class TestWildcardExpansion(unittest.TestCase):
    """Test wildcard file pattern expansion"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        # Create test files
        for i in range(3):
            with open(os.path.join(self.temp_dir, f"test{i}.log"), 'w') as f:
                f.write("test content")

    def tearDown(self):
        """Clean up test fixtures"""
        for i in range(3):
            f = os.path.join(self.temp_dir, f"test{i}.log")
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_expand_wildcard_pattern(self):
        """Test expanding wildcard patterns"""
        result = expand_and_sort_log_files(self.temp_dir, "test*.log")
        self.assertEqual(len(result), 3)
        self.assertIn("test0.log", result)
        self.assertIn("test1.log", result)
        self.assertIn("test2.log", result)

    def test_no_wildcard_pattern(self):
        """Test handling patterns without wildcards"""
        result = expand_and_sort_log_files(self.temp_dir, "specific.log")
        self.assertEqual(result, ["specific.log"])

    def test_wildcard_no_matches(self):
        """Test wildcard pattern that matches no files"""
        result = expand_and_sort_log_files(self.temp_dir, "nomatch*.log")
        # Should return the original pattern when no matches found
        self.assertEqual(result, ["nomatch*.log"])

    def test_wildcard_nonexistent_directory(self):
        """Test wildcard expansion in nonexistent directory"""
        result = expand_and_sort_log_files("/nonexistent/dir", "*.log")
        # Should return the original pattern when directory doesn't exist
        self.assertEqual(result, ["*.log"])


# Disabled unless PyYAML is installed (pip3 install --user pyyaml)
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestTimelineBlocks(unittest.TestCase):
    """Test timeline block processing and ordering"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "timeline.log")
        self.model_file = os.path.join(self.temp_dir, "model.yaml")

        model_data = {
            'blocks': [
                {'label': 'Dummy', 'file': 'timeline.log', 'patterns': ['dummy']}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.block_time_tolerance = 1.0
                self.hostname = 'controller-0'
                self.variables = None
                self.model_file = os.path.join(temp_dir, "model.yaml")

        self.args = MockArgs(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        if os.path.exists(self.model_file):
            os.remove(self.model_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_timeline_block_collects_matches(self):
        """Test timeline block collects and orders matches"""
        log_content = """2024-01-06T10:00:02.000 Alpha event
2024-01-06T10:00:01.000 Beta event"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        blocks = [
            {
                'label': 'Timeline Block',
                'file': 'timeline.log',
                'timeline': ['Alpha event', 'Beta event']
            }
        ]

        start_date = datetime(2024, 1, 6, 9, 0, 0)

        with patch('builtins.print'):
            (
                success,
                start_time,
                end_time,
                patterns_found,
                optional_warnings,
                structured_results
            ) = process_blocks_auto_detect(
                self.args,
                blocks,
                start_date
            )

        self.assertTrue(success)
        self.assertEqual(patterns_found, 2)
        self.assertEqual(len(structured_results), 2)
        self.assertIn("Beta event", structured_results[0].log_line)
        self.assertIn("Alpha event", structured_results[1].log_line)


class TestOptionalWarnings(unittest.TestCase):
    """Test optional block warnings in auto-detect mode"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")
        self.model_file = os.path.join(self.temp_dir, "model.yaml")

        model_data = {
            'blocks': [
                {'label': 'Dummy', 'file': 'test.log', 'patterns': ['dummy']}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.block_time_tolerance = 1.0
                self.model_file = os.path.join(temp_dir, "model.yaml")

        self.args = MockArgs(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        if os.path.exists(self.model_file):
            os.remove(self.model_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_optional_block_warning_in_results(self):
        """Test optional missing block emits warning line and continues"""
        log_content = "2024-01-06T10:00:00.000 first pattern\n"
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        blocks = [
            {
                'label': 'First Block',
                'file': 'test.log',
                'patterns': ['first pattern']
            },
            {
                'label': 'Optional Missing',
                'file': 'test.log',
                'patterns': ['missing pattern'],
                'optional': True
            }
        ]

        start_date = datetime(2024, 1, 6, 9, 0, 0)

        with patch('builtins.print'):
            (
                success,
                start_time,
                end_time,
                patterns_found,
                optional_warnings,
                structured_results
            ) = process_blocks_auto_detect(
                self.args,
                blocks,
                start_date
            )

        self.assertTrue(success)
        self.assertEqual(len(structured_results), 2)
        self.assertTrue(structured_results[1].is_warning)
        self.assertIn("Warn: block 'Optional Missing' pattern 'missing pattern' "
                      "not found", structured_results[1].warning_text)


class TestErrorHandling(unittest.TestCase):
    """Test error handling and edge cases"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_invalid_regex_pattern(self):
        """Test handling of invalid regex patterns"""
        log_content = """2024-01-06T10:00:00.000 test message
2024-01-06T10:01:00.000 another message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Use an invalid regex pattern
        invalid_pattern = "[unclosed bracket"

        # Should fall back to literal string matching
        result = find_pattern_in_files(
            self.temp_dir, "test.log", invalid_pattern
        )

        # Should return None since literal string doesn't match
        self.assertIsNone(result)

    def test_regex_fallback_to_literal(self):
        """Test regex fallback to literal string matching"""
        log_content = """2024-01-06T10:00:00.000 test [unclosed bracket message
2024-01-06T10:01:00.000 another message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Use an invalid regex pattern that exists as literal text
        invalid_pattern = "[unclosed bracket"

        # Should fall back to literal string matching and find it
        result = find_pattern_in_files(
            self.temp_dir, "test.log", invalid_pattern
        )

        self.assertIsNotNone(result)
        timestamp, pos, line, filename = result
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 0, 0))
        self.assertIn("[unclosed bracket", line)

    def test_permission_denied_file(self):
        """Test handling of files with permission issues"""
        # Create a file and make it unreadable (if possible on this system)
        with open(self.log_file, 'w') as f:
            f.write("test content")

        try:
            os.chmod(self.log_file, 0o000)  # Remove all permissions

            result = find_pattern_in_files(
                self.temp_dir, "test.log", "test"
            )

            # Should handle permission error gracefully
            self.assertIsNone(result)
        finally:
            # Restore permissions for cleanup
            os.chmod(self.log_file, 0o644)

    def test_very_long_log_lines(self):
        """Test handling of very long log lines"""
        # Create a log with a very long line
        long_message = "x" * 10000
        log_content = f"2024-01-06T10:00:00.000 {long_message} target pattern here"

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        result = find_pattern_in_files(
            self.temp_dir, "test.log", "target pattern"
        )

        self.assertIsNotNone(result)
        timestamp, pos, line, filename = result
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 0, 0))
        self.assertIn("target pattern", line)


# Disabled unless PyYAML is installed (pip3 install --user pyyaml)
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestIntegration(unittest.TestCase):
    """Integration tests for complete workflows"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")
        self.model_file = os.path.join(self.temp_dir, "model.yaml")
        self.output_dir = os.path.join(self.temp_dir, "out")

    def tearDown(self):
        """Clean up test fixtures"""
        for f in [self.log_file, self.model_file]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)
        os.rmdir(self.temp_dir)

    @patch('sys.argv', ['LPMP.py', '--version'])
    def test_version_flag(self):
        """Test --version flag functionality"""
        with self.assertRaises(SystemExit) as cm:
            lpmptool.main()
        self.assertEqual(cm.exception.code, 0)

    def test_mixed_model_processing(self):
        """Test processing mixed pattern and pair blocks"""
        # Create test log
        log_content = """2024-01-06T10:00:00.000 boot started
2024-01-06T10:01:00.000 service start
2024-01-06T10:02:00.000 service ready
2024-01-06T10:02:30.000 network starting
2024-01-06T10:03:00.000 network up"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Create test model: trigger pattern + pair blocks only
        model_data = {
            'blocks': [
                {
                    'label': 'Boot Event',
                    'file': 'test.log',
                    'patterns': ['boot started']
                },
                {
                    'label': 'Service Timing',
                    'file': 'test.log',
                    'start': 'service start',
                    'stop': 'service ready'
                },
                {
                    'label': 'Network Timing',
                    'file': 'test.log',
                    'start': 'network starting',
                    'stop': 'network up'
                }
            ]
        }

        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Test the processing
        with patch('sys.argv', [
            'LPMP.py',
            '--logs-dir', self.temp_dir,
            '--model-file', self.model_file,
            '--output', self.output_dir
        ]):
            with patch('builtins.print'):  # Suppress output
                try:
                    lpmptool.main()
                except SystemExit:
                    pass  # Expected for some test conditions

        # Verify output files were created (if successful)
        timing_file = os.path.join(self.output_dir, 'lab_profile.timing')
        csv_file = os.path.join(self.output_dir, 'lab_profile.timing.csv')
        if os.path.exists(timing_file):
            self.assertTrue(os.path.exists(csv_file))

    def test_profile_block_file_output(self):
        """Test per-block profile file creation and summary header"""
        log_content = """2024-01-06T10:00:00.000 blackout start
2024-01-06T10:00:05.000 blackout end"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        model_data = {
            'blocks': [
                {
                    'label': 'Blackout Time',
                    'file': 'test.log',
                    'patterns': ['blackout start', 'blackout end'],
                    'profile': True
                }
            ]
        }

        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'LPMP.py',
            '--logs-dir', self.temp_dir,
            '--model-file', self.model_file,
            '--output', self.output_dir
        ]):
            with patch('builtins.print'):
                lpmptool.main()

        # After stacked pattern expansion, expect 2 profile files
        # Output is nested under lpmp_<lab>/<timestamp>_<model>/ so search recursively
        timing_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.timing'):
                    timing_files.append(os.path.join(root, f))

        # At least one profile file should exist
        self.assertTrue(len(timing_files) > 0, f"No .timing files found under {self.output_dir}")

        # Check the content of the first timing file found
        with open(timing_files[0], 'r') as f:
            contents = f.read()
        self.assertIn("Block Timing Summary", contents)
        self.assertIn("Samples", contents)


# Disabled unless PyYAML is installed (pip3 install --user pyyaml)
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, "model.yaml")

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.model_file):
            os.remove(self.model_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_model_with_unicode_characters(self):
        """Test model file with unicode characters"""
        model_data = {
            'blocks': [
                {'label': 'Test éàü', 'file': 'test.log', 'patterns': ['test 中文']}
            ]
        }
        with open(self.model_file, 'w', encoding='utf-8') as f:
            yaml.dump(model_data, f, allow_unicode=True)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertIn('é', blocks[0]['label'])

    def test_model_with_very_long_label(self):
        """Test model with very long label"""
        long_label = 'A' * 1000
        model_data = {
            'blocks': [
                {'label': long_label, 'file': 'test.log', 'patterns': ['test']}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['label'], long_label)

    def test_model_with_special_characters_in_patterns(self):
        """Test model with special regex characters in patterns"""
        model_data = {
            'blocks': [
                {'label': 'Test', 'file': 'test.log', 'patterns': [r'\[.*\]', r'\d+\.\d+']}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        # After expand_stacked_patterns, 2 patterns become 2 blocks
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]['label'], 'Test_1')
        self.assertEqual(blocks[1]['label'], 'Test_2')
        self.assertEqual(len(blocks[0]['patterns']), 1)
        self.assertEqual(len(blocks[1]['patterns']), 1)

    def test_model_with_empty_string_pattern(self):
        """Test model with empty string pattern"""
        model_data = {
            'blocks': [
                {'label': 'Test', 'file': 'test.log', 'patterns': ['']}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['patterns'], [''])

    def test_model_with_numeric_values(self):
        """Test model handles numeric values in unexpected places"""
        model_data = {
            'blocks': [
                {'label': 123, 'file': 'test.log', 'patterns': [456]}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        # YAML will convert these to appropriate types

    def test_zero_loops(self):
        """Test loops=0 (until EOF)"""
        # This is a valid configuration
        model_data = {
            'blocks': [
                {'label': 'Test', 'file': 'test.log', 'patterns': ['test']}
            ],
            'settings': {'loops': 0}
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(settings['loops'], 0)

    def test_load_model_with_block_level_max_time_delta(self):
        """Test loading model with block-level max_time_delta"""
        model_data = {
            'blocks': [
                {
                    'label': 'Test Block Level Setting',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern',
                    'max_time_delta': 120
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['max_time_delta'], 120)
        self.assertEqual(blocks[0]['label'], 'Test Block Level Setting')

    def test_load_model_mixed_max_time_delta_settings(self):
        """Test loading model with mixed block-level and no max_time_delta"""
        model_data = {
            'blocks': [
                {
                    'label': 'Block Without Setting',
                    'file': 'test.log',
                    'patterns': ['test pattern']
                },
                {
                    'label': 'Block With Setting',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern',
                    'max_time_delta': 60
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 2)
        # Block without explicit max_time_delta should not have the key
        self.assertNotIn('max_time_delta', blocks[0])
        self.assertEqual(blocks[1]['max_time_delta'], 60)


# Disabled unless PyYAML is installed (pip3 install --user pyyaml)
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class CustomTestResult(unittest.TextTestResult):
    """Custom test result class for aligned output"""

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.test_count = 0

    def addSuccess(self, test):
        self.test_count += 1
        test_name = f"{test.__class__.__name__}.{test._testMethodName}"
        self.stream.write(f"{test_name[:100]:<100} ok\n")
        self.stream.flush()

    def addError(self, test, err):
        self.test_count += 1
        test_name = f"{test.__class__.__name__}.{test._testMethodName}"
        self.stream.write(f"{test_name[:100]:<100} ERROR\n")
        self.stream.flush()

    def addFailure(self, test, err):
        self.test_count += 1
        test_name = f"{test.__class__.__name__}.{test._testMethodName}"
        self.stream.write(f"{test_name[:100]:<100} FAIL\n")
        self.stream.flush()


class CustomTestRunner(unittest.TextTestRunner):
    """Custom test runner using aligned result class"""
    resultclass = CustomTestResult

    def run(self, test):
        result = self.resultclass(self.stream, self.descriptions, self.verbosity)
        test(result)
        self.stream.write("\n----------------------------------------------------------------------\n")
        self.stream.write(f"Ran {result.test_count} tests\n\n")
        if result.wasSuccessful():
            self.stream.write("OK\n")
        else:
            self.stream.write(f"FAILED (failures={len(result.failures)}, errors={len(result.errors)})\n")
        return result


if __name__ == '__main__':
    # Run tests with coverage if coverage module is available
    coverage_available = False
    try:
        import coverage
        coverage_available = True
        cov = coverage.Coverage()
        cov.start()
    except ImportError:
        print("Warning: Coverage module not available. Install with: pip install coverage")
        print("Running tests without coverage...")

    # Run the tests with custom runner
    runner = CustomTestRunner(stream=sys.stdout, descriptions=True, verbosity=2)
    unittest.main(testRunner=runner, exit=False, verbosity=0)

    if coverage_available:
        cov.stop()
        cov.save()

        print("\n" + "="*60)
        print("CODE COVERAGE REPORT")
        print("="*60)
        cov.report(show_missing=True)
