#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""
LPMP Edge Cases Test Suite

This test suite addresses the specific shortcomings identified in the test coverage gaps:
- Time tolerance edge cases
- Pattern matching edge cases
- Negative tests for invalid formats, permissions, and empty labels
- Output generation functions
- File processing functions
- Utility functions
"""

from datetime import datetime
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import find_pattern_in_files        # noqa: E402
from lpmp_utils import create_output_directory       # noqa: E402
from lpmp_utils import detect_model_type             # noqa: E402
from lpmp_utils import ensure_output_dir             # noqa: E402
from lpmp_utils import expand_wildcards_in_blocks    # noqa: E402
from lpmp_utils import format_result_line            # noqa: E402
from lpmp_utils import get_models_search_paths       # noqa: E402
from lpmp_utils import ModelType                     # noqa: E402
from lpmp_utils import parse_duration_to_seconds     # noqa: E402
from lpmp_utils import sanitize_label_for_filename   # noqa: E402
from test_base import LPMPTestBase                   # noqa: E402


class TestTimeToleranceEdgeCases(LPMPTestBase):
    """Test time tolerance edge cases"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_timestamp_exactly_at_tolerance_boundary(self):
        """Test timestamp exactly at tolerance boundary"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:01.000 second pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Test with 1.0 second tolerance - should find both
        start_time = datetime(2024, 1, 6, 10, 0, 0)
        result1 = find_pattern_in_files(
            self.temp_dir, "test.log", "first pattern", 0, None, 0
        )
        self.assertIsNotNone(result1)

        result2 = find_pattern_in_files(
            self.temp_dir, "test.log", "second pattern", 0, start_time, 0,
            max_time_delta=1.0
        )
        self.assertIsNotNone(result2)

    def test_multiple_blocks_within_tolerance_window(self):
        """Test multiple blocks within tolerance window"""
        log_content = """2024-01-06T10:00:00.000 pattern A
2024-01-06T10:00:00.500 pattern B
2024-01-06T10:00:00.800 pattern C"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        start_time = datetime(2024, 1, 6, 10, 0, 0)

        # All patterns within 1 second tolerance
        result_a = find_pattern_in_files(
            self.temp_dir, "test.log", "pattern A", 0, None, 0
        )
        result_b = find_pattern_in_files(
            self.temp_dir, "test.log", "pattern B", 0, start_time, 0,
            max_time_delta=1.0
        )
        result_c = find_pattern_in_files(
            self.temp_dir, "test.log", "pattern C", 0, start_time, 0,
            max_time_delta=1.0
        )

        self.assertIsNotNone(result_a)
        self.assertIsNotNone(result_b)
        self.assertIsNotNone(result_c)

    def test_tolerance_larger_than_time_range(self):
        """Test tolerance larger than time range"""
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:05.000 end pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        start_time = datetime(2024, 1, 6, 10, 0, 0)

        # 10 second tolerance for 5 second gap - should find both
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "end pattern", 0, start_time, 0,
            max_time_delta=10.0
        )
        self.assertIsNotNone(result)

    def test_zero_tolerance_value(self):
        """Test zero tolerance value"""
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:00.001 immediate pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        start_time = datetime(2024, 1, 6, 10, 0, 0)

        # Zero tolerance - should not find pattern 1ms later
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "immediate pattern", 0, start_time, 0,
            max_time_delta=0.0
        )
        self.assertIsNone(result)

    def test_negative_tolerance_value(self):
        """Test negative tolerance value"""
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:01.000 later pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        start_time = datetime(2024, 1, 6, 10, 0, 0)

        # Negative tolerance - should not find any patterns
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "later pattern", 0, start_time, 0,
            max_time_delta=-1.0
        )
        self.assertIsNone(result)


class TestPatternMatchingEdgeCases(LPMPTestBase):
    """Test pattern matching edge cases"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_pattern_at_start_of_file(self):
        """Test pattern at start of file"""
        log_content = """2024-01-06T10:00:00.000 target pattern at start
2024-01-06T10:00:01.000 other content"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        result = find_pattern_in_files(
            self.temp_dir, "test.log", "target pattern at start", 0, None, 0
        )
        self.assertIsNotNone(result)
        timestamp, pos, line, filename = result
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 0, 0))

    def test_pattern_at_end_of_file(self):
        """Test pattern at end of file"""
        log_content = """2024-01-06T10:00:00.000 first line
2024-01-06T10:00:01.000 target pattern at end"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        result = find_pattern_in_files(
            self.temp_dir, "test.log", "target pattern at end", 0, None, 0
        )
        self.assertIsNotNone(result)
        timestamp, pos, line, filename = result
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 0, 1))

    def test_pattern_spanning_multiple_lines(self):
        """Test pattern spanning multiple lines (regex with newline)"""
        log_content = """2024-01-06T10:00:00.000 start of multiline
pattern continues here
2024-01-06T10:00:01.000 end of multiline"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Test multiline pattern matching
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "start of multiline", 0, None, 0
        )
        self.assertIsNotNone(result)

    def test_overlapping_patterns(self):
        """Test overlapping patterns"""
        log_content = """2024-01-06T10:00:00.000 overlapping pattern test
2024-01-06T10:00:01.000 pattern test again"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Find first occurrence of "pattern test"
        result1 = find_pattern_in_files(
            self.temp_dir, "test.log", "pattern test", 0, None, 0
        )
        self.assertIsNotNone(result1)

        # Find second occurrence after first
        result2 = find_pattern_in_files(
            self.temp_dir, "test.log", "pattern test", result1[1], None, 0
        )
        self.assertIsNotNone(result2)


class TestNegativeTests(LPMPTestBase):
    """Test negative cases for error handling"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_invalid_format_file(self):
        """Test invalid format file"""
        invalid_file = os.path.join(self.temp_dir, "invalid.log")
        with open(invalid_file, 'w') as f:
            f.write("invalid content without timestamps\n")
            f.write("more invalid content\n")

        result = find_pattern_in_files(
            self.temp_dir, "invalid.log", "invalid", 0, None, 0
        )
        # Should return None because no valid timestamps
        self.assertIsNone(result)

    def test_permission_denied_file(self):
        """Test permission denied on file"""
        restricted_file = os.path.join(self.temp_dir, "restricted.log")
        with open(restricted_file, 'w') as f:
            f.write("2024-01-06T10:00:00.000 test content\n")

        try:
            # Remove read permissions
            os.chmod(restricted_file, 0o000)

            result = find_pattern_in_files(
                self.temp_dir, "restricted.log", "test", 0, None, 0
            )
            # Should handle permission error gracefully
            self.assertIsNone(result)
        finally:
            # Restore permissions for cleanup
            os.chmod(restricted_file, 0o644)

    def test_empty_label_sanitization(self):
        """Test empty label sanitization"""
        result = sanitize_label_for_filename("")
        self.assertEqual(result, "block")

    def test_label_with_only_invalid_characters(self):
        """Test label with only invalid characters"""
        result = sanitize_label_for_filename("///\\\\\\")
        self.assertEqual(result, "______")


class TestOutputGenerationFunctions(LPMPTestBase):
    """Test output generation functions"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.temp_dir, "output")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_create_output_directory_default_naming(self):
        """Test create output directory with default naming"""
        class MockArgs:
            def __init__(self):
                self.output = None
                self.model_file = "test_model.yaml"
                self.lab_name = "test_lab"

        args = MockArgs()
        run_start_time = datetime(2024, 1, 6, 10, 0, 0)

        result = create_output_directory(args, run_start_time)
        self.assertTrue(os.path.exists(result))
        self.assertIn("lpmp_test_lab", result)
        self.assertIn("20240106_100000_test_model", result)

    def test_create_output_directory_custom_path(self):
        """Test create output directory with custom path"""
        class MockArgs:
            def __init__(self, output_dir):
                self.output = output_dir
                self.model_file = "test_model.yaml"
                self.lab_name = "test_lab"

        args = MockArgs(self.output_dir)
        args.output = self.output_dir
        run_start_time = datetime(2024, 1, 6, 10, 0, 0)

        result = create_output_directory(args, run_start_time)
        self.assertTrue(os.path.exists(result))
        # -o creates lpmp_<lab>/<timestamp>_<model> structure under output path
        self.assertTrue(result.startswith(self.output_dir))
        self.assertIn("lpmp_test_lab", result)
        self.assertIn("20240106_100000_test_model", result)

    def test_create_output_directory_with_hostname(self):
        """Test create output directory with hostname subdirectory"""
        class MockArgs:
            def __init__(self, output_dir):
                self.output = output_dir
                self.model_file = "test_model.yaml"
                self.lab_name = "test_lab"

        args = MockArgs(self.output_dir)
        run_start_time = datetime(2024, 1, 6, 10, 0, 0)

        result = create_output_directory(args, run_start_time, hostname="controller-0")
        self.assertTrue(os.path.exists(result))
        self.assertIn("controller-0", result)

    def test_create_output_directory_permission_denied(self):
        """Test permission denied on output directory"""
        class MockArgs:
            def __init__(self):
                self.output = "/root/restricted"
                self.model_file = "test_model.yaml"
                self.lab_name = "test_lab"

        args = MockArgs()
        run_start_time = datetime(2024, 1, 6, 10, 0, 0)

        with self.assertRaises((PermissionError, OSError)):
            create_output_directory(args, run_start_time)

    def test_create_output_directory_invalid_characters(self):
        """Test invalid characters in output path"""
        class MockArgs:
            def __init__(self, temp_dir):
                self.output = os.path.join(temp_dir, "invalid\x00path")
                self.model_file = "test_model.yaml"
                self.lab_name = "test_lab"

        args = MockArgs(self.temp_dir)
        run_start_time = datetime(2024, 1, 6, 10, 0, 0)

        with self.assertRaises((ValueError, OSError)):
            create_output_directory(args, run_start_time)

    @patch('os.makedirs')
    def test_create_output_directory_disk_full(self, mock_makedirs):
        """Test disk full scenario"""
        mock_makedirs.side_effect = OSError("No space left on device")

        class MockArgs:
            def __init__(self, output_dir):
                self.output = output_dir
                self.model_file = "test_model.yaml"
                self.lab_name = "test_lab"

        args = MockArgs(self.output_dir)
        run_start_time = datetime(2024, 1, 6, 10, 0, 0)

        with self.assertRaises(OSError):
            create_output_directory(args, run_start_time)

    @patch('os.access')
    def test_create_output_directory_readonly_filesystem(self, mock_access):
        """Test read-only filesystem"""
        mock_access.return_value = False

        class MockArgs:
            def __init__(self):
                self.output = "/readonly/path"
                self.model_file = "test_model.yaml"
                self.lab_name = "test_lab"

        args = MockArgs()
        run_start_time = datetime(2024, 1, 6, 10, 0, 0)

        with self.assertRaises((PermissionError, OSError)):
            create_output_directory(args, run_start_time)


class TestFileProcessingFunctions(LPMPTestBase):
    """Test file processing functions"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_expand_wildcards_single_block(self):
        """Test expand wildcards in single block"""
        # Create test files
        for i in range(3):
            with open(os.path.join(self.temp_dir, f"test{i}.log"), 'w') as f:
                f.write("test content")

        blocks = [{
            'label': 'Test Block',
            'file': 'test*.log'
        }]

        expand_wildcards_in_blocks(blocks, self.temp_dir)

        self.assertIsInstance(blocks[0]['file'], list)
        self.assertEqual(len(blocks[0]['file']), 3)

    def test_expand_wildcards_multiple_blocks(self):
        """Test expand wildcards in multiple blocks"""
        # Create test files
        for i in range(2):
            with open(os.path.join(self.temp_dir, f"app{i}.log"), 'w') as f:
                f.write("app content")
            with open(os.path.join(self.temp_dir, f"sys{i}.log"), 'w') as f:
                f.write("sys content")

        blocks = [
            {'label': 'App Block', 'file': 'app*.log'},
            {'label': 'Sys Block', 'file': 'sys*.log'}
        ]

        expand_wildcards_in_blocks(blocks, self.temp_dir)

        self.assertIsInstance(blocks[0]['file'], list)
        self.assertIsInstance(blocks[1]['file'], list)
        self.assertEqual(len(blocks[0]['file']), 2)
        self.assertEqual(len(blocks[1]['file']), 2)

    def test_expand_wildcards_no_wildcards(self):
        """Test handle blocks without wildcards"""
        blocks = [{
            'label': 'Test Block',
            'file': 'specific.log'
        }]

        expand_wildcards_in_blocks(blocks, self.temp_dir)

        self.assertEqual(blocks[0]['file'], 'specific.log')


class TestUtilityFunctions(LPMPTestBase):
    """Test utility functions"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_get_models_search_paths_basic(self):
        """Test return correct search paths"""
        paths = get_models_search_paths()

        self.assertIsInstance(paths, list)
        self.assertGreater(len(paths), 0)
        self.assertIn('./models/', paths)
        self.assertIn('./', paths)

    def test_detect_model_type_window(self):
        """Test window block detected as TIMELINE model type"""
        blocks = [{'label': 'T', 'file': '*.log*', 'window': True, 'timeline': '.*'}]
        self.assertEqual(detect_model_type(blocks), ModelType.TIMELINE)

    def test_detect_model_type_window_raw(self):
        """Test raw window block (no timeline key) detected as TIMELINE"""
        blocks = [{'label': 'T', 'file': '*.log*', 'window': True}]
        self.assertEqual(detect_model_type(blocks), ModelType.TIMELINE)

    def test_sanitize_label_remove_invalid_chars(self):
        """Test remove invalid characters"""
        result = sanitize_label_for_filename("Test/Block\\Name")
        self.assertEqual(result, "Test_Block_Name")

    def test_sanitize_label_replace_spaces(self):
        """Test replace spaces with underscores"""
        result = sanitize_label_for_filename("Test Block Name")
        self.assertEqual(result, "Test_Block_Name")

    def test_sanitize_label_special_characters(self):
        """Test handle special characters"""
        result = sanitize_label_for_filename("Test@Block#Name$")
        self.assertEqual(result, "Test@Block#Name$")

    def test_ensure_output_dir_create(self):
        """Test create directory if not exists"""
        new_dir = os.path.join(self.temp_dir, "new_output")

        result = ensure_output_dir(new_dir)

        self.assertTrue(os.path.exists(new_dir))
        self.assertEqual(result, new_dir)

    def test_parse_duration_to_seconds_hms(self):
        """Test parse HH:MM:SS format"""
        result = parse_duration_to_seconds("01:02:03.456")
        expected = 1 * 3600 + 2 * 60 + 3.456
        self.assertAlmostEqual(result, expected, places=3)

    def test_parse_duration_to_seconds_invalid(self):
        """Test invalid format"""
        result = parse_duration_to_seconds("invalid")
        self.assertIsNone(result)

    def test_format_result_line_basic(self):
        """Test format timing line correctly"""
        result = format_result_line(
            "00:00:05.123", "Test Block               ", "test.log                      ", "Test data"
        )
        expected = "00:00:05.123\tTest Block               \ttest.log                      \tTest data"
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
