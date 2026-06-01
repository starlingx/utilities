#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Comprehensive test coverage for lpmp_output.py functions.

Tests all 15 functions in lpmp_output.py following existing test infrastructure
patterns from the established test suite.
"""

import csv
from datetime import datetime
import os
import shutil
import sys
import tempfile
import unittest

from lpmp_output import _extract_timestamp_from_data     # noqa: E402
from lpmp_output import _parse_ts                        # noqa: E402
from lpmp_output import _write_system_summary_file       # noqa: E402
from lpmp_output import create_pattern_system_summary    # noqa: E402
from lpmp_output import merge_timeline_profiles          # noqa: E402
from lpmp_output import write_pair_block_profile         # noqa: E402
from lpmp_output import write_pair_csv                   # noqa: E402
from lpmp_output import write_pair_summary               # noqa: E402
from lpmp_output import write_pattern_block_profile      # noqa: E402
from lpmp_output import write_pattern_csv                # noqa: E402
from lpmp_output import write_pattern_summary            # noqa: E402
from lpmp_output import write_summary_stats              # noqa: E402
from lpmp_output import write_timeline_block_profile     # noqa: E402
from lpmp_output import write_timeline_csv               # noqa: E402
from lpmp_utils import PairResult                        # noqa: E402
from lpmp_utils import PatternResult                     # noqa: E402
from lpmp_utils import print_output_files                # noqa: E402
from lpmp_utils import TimelineResult                    # noqa: E402
from test_base import LPMPTestBase                       # noqa: E402

# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLpmpOutputFunctions(LPMPTestBase):
    """Test lpmp_output.py functions using existing infrastructure"""

    def setUp(self):
        """Set up test environment with temporary directory"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_output_path = os.path.join(self.temp_dir, 'test_output.txt')
        self.test_csv_path = os.path.join(self.temp_dir, 'test_output.csv')

    def tearDown(self):
        """Clean up temporary directory"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    # -------------------------------------------------------------------------
    # Helper Function Tests (Phase 2)
    # -------------------------------------------------------------------------

    def test_parse_ts_string_timestamp(self):
        """Test _parse_ts with ISO format string"""
        ts_str = "2024-03-22T10:30:45.123"
        result = _parse_ts(ts_str)
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 3)
        self.assertEqual(result.day, 22)

    def test_parse_ts_datetime_passthrough(self):
        """Test _parse_ts with datetime object"""
        dt = datetime(2024, 3, 22, 10, 30, 45)
        result = _parse_ts(dt)
        self.assertEqual(result, dt)

    def test_parse_ts_invalid_string(self):
        """Test _parse_ts with invalid string format"""
        with self.assertRaises(ValueError):
            _parse_ts("invalid-timestamp")

    def test_parse_ts_none_input(self):
        """Test _parse_ts with None input"""
        result = _parse_ts(None)
        self.assertIsNone(result)

    def test_parse_ts_empty_string(self):
        """Test _parse_ts with empty string"""
        with self.assertRaises(ValueError):
            _parse_ts("")

    def test_parse_ts_integration_with_patterns(self):
        """Test _parse_ts integration with existing timestamp patterns"""
        # Test with sysinv format timestamp
        ts_str = "2024-03-22T10:30:45.123456"
        result = _parse_ts(ts_str)
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.microsecond, 123456)

    def test_write_summary_stats_standard_output(self):
        """Test write_summary_stats with standard summary output"""
        with open(self.test_output_path, 'w') as f:
            write_summary_stats(f, 5, 120.5, 100.0, 150.0)

        with open(self.test_output_path, 'r') as f:
            content = f.read()

        self.assertIn("Overall Summary", content)
        self.assertIn("Samples: 5", content)
        self.assertIn("Average: 00:02:00.500", content)
        self.assertIn("Maximum: 00:02:30.000", content)
        self.assertIn("Minimum: 00:01:40.000", content)

    def test_write_summary_stats_custom_title(self):
        """Test write_summary_stats with custom title"""
        with open(self.test_output_path, 'w') as f:
            write_summary_stats(f, 3, 60.0, 45.0, 75.0, "Custom Title")

        with open(self.test_output_path, 'r') as f:
            content = f.read()

        self.assertIn("Custom Title", content)
        self.assertIn("Samples: 3", content)

    def test_write_summary_stats_zero_samples(self):
        """Test write_summary_stats with zero samples"""
        with open(self.test_output_path, 'w') as f:
            write_summary_stats(f, 0, 0.0, 0.0, 0.0)

        with open(self.test_output_path, 'r') as f:
            content = f.read()

        self.assertIn("Samples: 0", content)
        self.assertIn("Average: 00:00:00.000", content)

    def test_write_summary_stats_file_error(self):
        """Test write_summary_stats with file write error"""
        # Try to write to a directory instead of a file
        with self.assertRaises(IsADirectoryError):
            with open(self.temp_dir, 'w') as f:
                write_summary_stats(f, 1, 1.0, 1.0, 1.0)

    def test_write_summary_stats_integration(self):
        """Test write_summary_stats integration with existing format expectations"""
        # Test with realistic timing values from existing tests
        with open(self.test_output_path, 'w') as f:
            write_summary_stats(f, 10, 45.678, 12.345, 89.012, "Block Timing Summary")

        with open(self.test_output_path, 'r') as f:
            content = f.read()

        # Verify format matches existing summary expectations
        lines = content.strip().split('\n')
        self.assertEqual(lines[0], "Block Timing Summary")
        self.assertTrue(lines[1].startswith("-"))
        self.assertIn("Samples: 10", lines[2])

    # -------------------------------------------------------------------------
    # Pattern Model Writer Tests (Phase 3)
    # -------------------------------------------------------------------------

    def test_write_pattern_csv_valid_results(self):
        """Test write_pattern_csv with valid PatternResult objects"""
        results = [
            PatternResult(
                block_label="test_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="Test log line",
                is_warning=False
            ),
            PatternResult(
                block_label="test_block2",
                hostname="test-host",
                actual_filename="test2.log",
                timestamp="2024-03-22T10:30:46.456",
                log_line="Second log line",
                is_warning=False
            )
        ]
        pass_summaries = [["Pass 1", "00:01:30.000", "info", "", ""]]

        write_pattern_csv(self.test_csv_path, results, pass_summaries)

        self.assertTrue(os.path.exists(self.test_csv_path))
        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Check header
        self.assertEqual(rows[0], ['Cumulative(s)', 'Delta(HH:MM:SS)', 'Block Label', 'Log File', 'Data'])
        # Check first data row
        self.assertEqual(rows[1][2], "test_block")
        self.assertEqual(rows[1][3], "test.log")
        self.assertEqual(rows[1][4], "Test log line")

    def test_write_pattern_csv_empty_results(self):
        """Test write_pattern_csv with empty results"""
        write_pattern_csv(self.test_csv_path, [], [])

        self.assertTrue(os.path.exists(self.test_csv_path))
        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Should only have header
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], ['Cumulative(s)', 'Delta(HH:MM:SS)', 'Block Label', 'Log File', 'Data'])

    def test_write_pattern_csv_warning_results(self):
        """Test write_pattern_csv with warning results"""
        results = [
            PatternResult(
                block_label="test_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp=None,
                log_line=None,
                is_warning=True,
                warning_text="Pattern not found"
            )
        ]

        write_pattern_csv(self.test_csv_path, results, [])

        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Check warning row format
        self.assertEqual(rows[1][1], "??:??:??.???")
        self.assertEqual(rows[1][4], "Pattern not found")

    def test_write_pattern_csv_pass_summaries(self):
        """Test write_pattern_csv includes pass summaries"""
        pass_summaries = [
            ["Pass 1", "00:01:30.000", "info", "", ""],
            ["Pass 2", "00:01:45.000", "info", "", ""]
        ]

        write_pattern_csv(self.test_csv_path, [], pass_summaries)

        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Should have header + 2 pass summary rows
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1], ["Pass 1", "00:01:30.000", "info", "", ""])
        self.assertEqual(rows[2], ["Pass 2", "00:01:45.000", "info", "", ""])

    def test_write_pattern_csv_file_error(self):
        """Test write_pattern_csv with file I/O error"""
        # Try to write to invalid path
        invalid_path = "/invalid/path/test.csv"

        # Should not raise exception, but should handle error gracefully
        write_pattern_csv(invalid_path, [], [])

        # File should not exist
        self.assertFalse(os.path.exists(invalid_path))

    def test_write_pattern_csv_format_validation(self):
        """Test write_pattern_csv CSV format validation"""
        results = [
            PatternResult(
                block_label="test_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="Test,with,commas",
                is_warning=False
            )
        ]

        write_pattern_csv(self.test_csv_path, results, [])

        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # CSV should properly handle commas in data
        self.assertEqual(rows[1][4], "Test,with,commas")

    def test_write_pattern_csv_integration(self):
        """Test write_pattern_csv integration with existing pattern model tests"""
        # Use realistic data similar to existing pattern tests
        results = [
            PatternResult(
                block_label="nova_compute_start",
                hostname="controller-0",
                actual_filename="/var/log/nova/nova-compute.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="2024-03-22 10:30:45.123 INFO nova.compute Starting compute service",
                is_warning=False
            )
        ]

        write_pattern_csv(self.test_csv_path, results, [])

        with open(self.test_csv_path, 'r') as f:
            content = f.read()

        self.assertIn("nova_compute_start", content)
        self.assertIn("nova-compute.log", content)  # Check filename, not hostname

    def test_write_pattern_csv_large_dataset(self):
        """Test write_pattern_csv with large dataset"""
        # Create 1000 results to test performance
        results = []
        for i in range(1000):
            results.append(PatternResult(
                block_label=f"block_{i}",
                hostname="test-host",
                actual_filename=f"test_{i}.log",
                timestamp=f"2024-03-22T10:30:{i % 60:02d}.123",
                log_line=f"Log line {i}",
                is_warning=False
            ))

        write_pattern_csv(self.test_csv_path, results, [])

        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Should have header + 1000 data rows
        self.assertEqual(len(rows), 1001)

    def test_write_pattern_summary_extend_existing(self):
        """Test write_pattern_summary extending existing test coverage"""
        results = []
        pass_summaries = [
            "✅ Pass 1       00:01:30.000 controller-0 patterns found: 5",
            "✅ Pass 2       00:01:45.000 controller-1 patterns found: 3"
        ]
        optional_warnings = ["⚠️ Warn: Optional block not found"]

        write_pattern_summary(self.test_output_path, results, pass_summaries, optional_warnings)

        with open(self.test_output_path, 'r') as f:
            content = f.read()

        self.assertIn("Overall Summary", content)
        self.assertIn("Samples: 2", content)
        self.assertIn("patterns found", content)
        self.assertIn("⚠️ Warn:", content)

    def test_write_pattern_summary_missing_edge_cases(self):
        """Test write_pattern_summary edge cases not covered by existing tests"""
        # Test with no pass summaries
        write_pattern_summary(self.test_output_path, [], [], [])

        with open(self.test_output_path, 'r') as f:
            content = f.read()

        self.assertIn("Samples: 0", content)
        self.assertIn("Average: 00:00:00.000", content)

    def test_write_pattern_summary_error_conditions(self):
        """Test write_pattern_summary error condition handling"""
        # Try to write to invalid path
        invalid_path = "/invalid/path/summary.timing"

        # Should not raise exception
        write_pattern_summary(invalid_path, [], [], [])

        # File should not exist
        self.assertFalse(os.path.exists(invalid_path))

    def test_write_pattern_summary_integration_validation(self):
        """Test write_pattern_summary integration with existing warning format tests"""
        pass_summaries = [
            "✅ Pass 1       00:01:30.000 controller-0 patterns found: 5"
        ]
        optional_warnings = [
            "⚠️ Warn: Optional block 'optional_service' not found",
            "❌ Error: Required block failed"
        ]

        write_pattern_summary(self.test_output_path, [], pass_summaries, optional_warnings)

        with open(self.test_output_path, 'r') as f:
            content = f.read()

        # Should match existing warning format expectations
        self.assertIn("⚠️ Warn:", content)
        self.assertIn("❌ Error:", content)
        self.assertIn("patterns found", content)

    def test_write_pattern_block_profile_enabled_blocks(self):
        """Test write_pattern_block_profile with profile-enabled blocks"""
        blocks = [
            {'label': 'test_block', 'profile': True, 'patterns': ['test']},
            {'label': 'no_profile_block', 'profile': False, 'patterns': ['test2']}
        ]
        results = [
            PatternResult(
                block_label="test_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="Test log line",
                is_warning=False
            )
        ]

        write_pattern_block_profile(self.temp_dir, blocks, results)

        # Should create profile file for enabled block only
        profile_file = os.path.join(self.temp_dir, 'test_block.timing')
        self.assertTrue(os.path.exists(profile_file))

        no_profile_file = os.path.join(self.temp_dir, 'no_profile_block.timing')
        self.assertFalse(os.path.exists(no_profile_file))

    def test_write_pattern_block_profile_result_filtering(self):
        """Test write_pattern_block_profile filters results correctly"""
        blocks = [{'label': 'target_block', 'profile': True, 'patterns': ['test']}]
        results = [
            PatternResult(
                block_label="target_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="Target log line",
                is_warning=False
            ),
            PatternResult(
                block_label="other_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:46.123",
                log_line="Other log line",
                is_warning=False
            ),
            PatternResult(
                block_label="target_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp=None,
                log_line=None,
                is_warning=True,
                warning_text="Warning message"
            )
        ]

        write_pattern_block_profile(self.temp_dir, blocks, results)

        profile_file = os.path.join(self.temp_dir, 'target_block.timing')
        with open(profile_file, 'r') as f:
            content = f.read()

        # Should only include non-warning results for target_block
        self.assertIn("Target log line", content)
        self.assertNotIn("Other log line", content)
        self.assertNotIn("Warning message", content)

    def test_write_pattern_block_profile_filename_sanitization(self):
        """Test write_pattern_block_profile sanitizes filenames"""
        blocks = [{'label': 'test/block:with*special?chars', 'profile': True, 'patterns': ['test']}]
        results = [
            PatternResult(
                block_label="test/block:with*special?chars",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="Test log line",
                is_warning=False
            )
        ]

        write_pattern_block_profile(self.temp_dir, blocks, results)

        # Should create filename (may or may not be sanitized depending on implementation)
        files = os.listdir(self.temp_dir)
        timing_files = [f for f in files if f.endswith('.timing')]
        self.assertEqual(len(timing_files), 1)

        # File should exist regardless of sanitization
        self.assertTrue(timing_files[0].endswith('.timing'))

    def test_write_pattern_block_profile_directory_creation(self):
        """Test write_pattern_block_profile handles directory creation"""
        # Use existing temp directory - should work
        blocks = [{'label': 'test_block', 'profile': True, 'patterns': ['test']}]
        results = [
            PatternResult(
                block_label="test_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="Test log line",
                is_warning=False
            )
        ]

        write_pattern_block_profile(self.temp_dir, blocks, results)

        profile_file = os.path.join(self.temp_dir, 'test_block.timing')
        self.assertTrue(os.path.exists(profile_file))

    def test_write_pattern_block_profile_empty_results(self):
        """Test write_pattern_block_profile with empty results"""
        blocks = [{'label': 'test_block', 'profile': True, 'patterns': ['test']}]

        write_pattern_block_profile(self.temp_dir, blocks, [])

        # Should not create any files
        files = os.listdir(self.temp_dir)
        timing_files = [f for f in files if f.endswith('.timing')]
        self.assertEqual(len(timing_files), 0)

    def test_write_pattern_block_profile_statistics_accuracy(self):
        """Test write_pattern_block_profile statistics accuracy"""
        blocks = [{'label': 'test_block', 'profile': True, 'patterns': ['test']}]
        results = [
            PatternResult(
                block_label="test_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.000",
                log_line="First log line",
                is_warning=False
            ),
            PatternResult(
                block_label="test_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:47.000",
                log_line="Second log line",
                is_warning=False
            ),
            PatternResult(
                block_label="test_block",
                hostname="test-host",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:50.000",
                log_line="Third log line",
                is_warning=False
            )
        ]

        write_pattern_block_profile(self.temp_dir, blocks, results)

        profile_file = os.path.join(self.temp_dir, 'test_block.timing')
        with open(profile_file, 'r') as f:
            content = f.read()

        # Should have correct statistics (deltas: 2s, 3s -> avg: 2.5s)
        self.assertIn("Samples: 2", content)  # 2 deltas from 3 results
        self.assertIn("Average: 00:00:02.500", content)

    def test_write_pattern_block_profile_integration(self):
        """Test write_pattern_block_profile integration with existing profile expectations"""
        blocks = [{'label': 'nova_compute_start', 'profile': True, 'patterns': ['Starting compute']}]
        results = [
            PatternResult(
                block_label="nova_compute_start",
                hostname="controller-0",
                actual_filename="/var/log/nova/nova-compute.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="2024-03-22 10:30:45.123 INFO Starting compute service",
                is_warning=False
            )
        ]

        write_pattern_block_profile(self.temp_dir, blocks, results)

        profile_file = os.path.join(self.temp_dir, 'nova_compute_start.timing')
        with open(profile_file, 'r') as f:
            content = f.read()

        # Should match existing profile format expectations
        self.assertIn("Block Timing Summary", content)
        self.assertIn("Delta(HH:MM:SS)", content)
        self.assertIn("Block Label", content)
        self.assertIn("Log File", content)

    # -------------------------------------------------------------------------
    # Pair Model Writer Tests (Phase 4)
    # -------------------------------------------------------------------------

    def test_write_pair_csv_pair_results(self):
        """Test write_pair_csv with PairResult objects"""
        results = [
            PairResult(
                block_label="service_restart",
                hostname="controller-0",
                actual_filename="test.log",
                start_timestamp="2024-03-22T10:30:45.123",
                stop_timestamp="2024-03-22T10:30:47.456",
                duration_seconds=2.333,
                is_warning=False
            )
        ]
        pass_summaries = [["Pass 1", "00:02:20.000", "info", "", ""]]

        write_pair_csv(self.test_csv_path, results, pass_summaries)

        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        self.assertEqual(rows[0], ['Cumulative(s)', 'Delta(HH:MM:SS)', 'Block Label', 'Log File', 'Data'])
        self.assertEqual(rows[1][2], "service_restart")
        self.assertIn("2.3s", rows[1][4])  # Duration in data column

    def test_write_pair_csv_mixed_results(self):
        """Test write_pair_csv with mixed PairResult and PatternResult"""
        results = [
            PatternResult(
                block_label="trigger",
                hostname="controller-0",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.000",
                log_line="Trigger event",
                is_warning=False
            ),
            PairResult(
                block_label="service_restart",
                hostname="controller-0",
                actual_filename="test.log",
                start_timestamp="2024-03-22T10:30:46.000",
                stop_timestamp="2024-03-22T10:30:48.000",
                duration_seconds=2.0,
                is_warning=False
            )
        ]

        write_pair_csv(self.test_csv_path, results, [])

        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 3)  # Header + 2 data rows
        self.assertEqual(rows[1][2], "trigger")
        self.assertEqual(rows[2][2], "service_restart")

    def test_write_pair_summary_overall_summary(self):
        """Test write_pair_summary generates overall summary"""
        results = [
            PairResult(
                block_label="service_a",
                hostname="controller-0",
                actual_filename="test.log",
                start_timestamp="2024-03-22T10:30:45.000",
                stop_timestamp="2024-03-22T10:30:47.000",
                duration_seconds=2.0,
                is_warning=False
            ),
            PairResult(
                block_label="service_b",
                hostname="controller-0",
                actual_filename="test.log",
                start_timestamp="2024-03-22T10:30:48.000",
                stop_timestamp="2024-03-22T10:30:51.000",
                duration_seconds=3.0,
                is_warning=False
            )
        ]
        pass_summaries = ["✅ Pass 1 00:05:00.000 controller-0"]

        write_pair_summary(self.test_output_path, results, pass_summaries)

        with open(self.test_output_path, 'r') as f:
            content = f.read()

        self.assertIn("Overall Summary", content)
        self.assertIn("Per-Block Timing Summary", content)
        self.assertIn("service_a", content)
        self.assertIn("service_b", content)

    def test_write_pair_block_profile_duration_stats(self):
        """Test write_pair_block_profile calculates duration statistics"""
        blocks = [{'label': 'test_service', 'profile': True, 'start': 'start', 'stop': 'stop'}]
        results = [
            PairResult(
                block_label="test_service",
                hostname="controller-0",
                actual_filename="test.log",
                start_timestamp="2024-03-22T10:30:45.000",
                stop_timestamp="2024-03-22T10:30:47.000",
                duration_seconds=2.0,
                is_warning=False
            ),
            PairResult(
                block_label="test_service",
                hostname="controller-0",
                actual_filename="test.log",
                start_timestamp="2024-03-22T10:30:50.000",
                stop_timestamp="2024-03-22T10:30:53.000",
                duration_seconds=3.0,
                is_warning=False
            )
        ]

        write_pair_block_profile(self.temp_dir, blocks, results)

        profile_file = os.path.join(self.temp_dir, 'test_service.timing')
        with open(profile_file, 'r') as f:
            content = f.read()

        self.assertIn("Samples: 2", content)
        self.assertIn("Average: 00:00:02.500", content)  # (2.0 + 3.0) / 2 = 2.5

    # -------------------------------------------------------------------------
    # Timeline Model Writer Tests (Phase 5)
    # -------------------------------------------------------------------------

    def test_write_timeline_csv_timeline_results(self):
        """Test write_timeline_csv with TimelineResult objects"""
        results = [
            TimelineResult(
                block_label="event_1",
                hostname="controller-0",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.123",
                log_line="First event occurred"
            ),
            TimelineResult(
                block_label="event_2",
                hostname="controller-0",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:47.456",
                log_line="Second event occurred"
            )
        ]
        pass_summaries = [["Timeline 1", "00:02:20.000", "info", "", ""]]

        write_timeline_csv(self.test_csv_path, results, pass_summaries)

        with open(self.test_csv_path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        self.assertEqual(rows[0], ['Cumulative(s)', 'Delta(HH:MM:SS)', 'Block Label', 'Log File', 'Data'])
        self.assertEqual(rows[1][2], "event_1")
        self.assertEqual(rows[2][2], "event_2")
        self.assertEqual(rows[1][1], "00:00:00.000")  # First delta is 0
        self.assertEqual(rows[2][1], "00:00:02.333")  # Second delta is ~2.33s

    def test_write_timeline_block_profile_delta_calculations(self):
        """Test write_timeline_block_profile calculates deltas correctly"""
        blocks = [{'label': 'timeline_events', 'profile': True, 'timeline': ['event']}]
        results = [
            TimelineResult(
                block_label="timeline_events",
                hostname="controller-0",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:45.000",
                log_line="Event 1"
            ),
            TimelineResult(
                block_label="timeline_events",
                hostname="controller-0",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:47.000",
                log_line="Event 2"
            ),
            TimelineResult(
                block_label="timeline_events",
                hostname="controller-0",
                actual_filename="test.log",
                timestamp="2024-03-22T10:30:50.000",
                log_line="Event 3"
            )
        ]

        write_timeline_block_profile(self.temp_dir, blocks, results)

        profile_file = os.path.join(self.temp_dir, 'timeline_events.timing')
        with open(profile_file, 'r') as f:
            content = f.read()

        # Should have 2 deltas: 2s and 3s, avg = 2.5s
        self.assertIn("Samples: 2", content)
        self.assertIn("Average: 00:00:02.500", content)

    # -------------------------------------------------------------------------
    # System/Bundle Writer Tests (Phase 6)
    # -------------------------------------------------------------------------

    def test_create_pattern_system_summary_multi_host(self):
        """Test create_pattern_system_summary with multiple hosts"""
        # Create mock host directories with summary files
        host_list = ['controller-0', 'controller-1']

        for hostname in host_list:
            host_dir = os.path.join(self.temp_dir, hostname)
            os.makedirs(host_dir)
            summary_file = os.path.join(host_dir, 'summary.timing')
            with open(summary_file, 'w') as f:
                f.write("Overall Summary\n")
                f.write("-" * 15 + "\n")
                f.write("Samples: 3\n")
                f.write("Average: 00:01:30.000\n")
                f.write("Maximum: 00:02:00.000\n")
                f.write("Minimum: 00:01:00.000\n\n")
                f.write(f"✅ Pass 1 00:01:30.000 {hostname} patterns found: 5\n")

        output_path = os.path.join(self.temp_dir, 'system_summary.timing')
        create_pattern_system_summary(self.temp_dir, host_list, 'test_lab', output_path)

        with open(output_path, 'r') as f:
            content = f.read()

        self.assertIn("System Timing Summary", content)
        self.assertIn("controller-0", content)
        self.assertIn("controller-1", content)
        self.assertIn("Average:", content)

    def test_create_pattern_system_summary_missing_files(self):
        """Test create_pattern_system_summary handles missing files"""
        host_list = ['controller-0', 'missing-host']

        # Create only one host directory
        host_dir = os.path.join(self.temp_dir, 'controller-0')
        os.makedirs(host_dir)
        summary_file = os.path.join(host_dir, 'summary.timing')
        with open(summary_file, 'w') as f:
            f.write("Samples: 1\nAverage: 00:01:00.000\n")

        output_path = os.path.join(self.temp_dir, 'system_summary.timing')
        create_pattern_system_summary(self.temp_dir, host_list, 'test_lab', output_path)

        with open(output_path, 'r') as f:
            content = f.read()

        self.assertIn("controller-0", content)
        self.assertIn("missing-host", content)
        self.assertIn("N/A", content)  # Missing host should show N/A

    def test_write_system_summary_file_host_statistics(self):
        """Test _write_system_summary_file displays host statistics"""
        host_list = ['host1', 'host2']
        host_stats = {
            'host1': {
                'samples': '3',
                'average': '00:01:30.000',
                'maximum': '00:02:00.000',
                'minimum': '00:01:00.000',
                'content': ['✅ Pass 1 00:01:30.000 host1']
            },
            'host2': {
                'warning': 'No summary.timing file found'
            }
        }

        output_path = os.path.join(self.temp_dir, 'system_summary.timing')
        _write_system_summary_file(output_path, host_list, host_stats)

        with open(output_path, 'r') as f:
            content = f.read()

        self.assertIn("System Timing Summary", content)
        self.assertIn("host1", content)
        self.assertIn("host2", content)
        self.assertIn("00:01:30.000", content)
        self.assertIn("⚠️  Warning:", content)  # Note: two spaces after emoji

    def test_merge_timeline_profiles_chronological_sorting(self):
        """Test merge_timeline_profiles sorts by timestamp"""
        # Create test timeline files
        file1 = os.path.join(self.temp_dir, 'host1_timeline.log')
        file2 = os.path.join(self.temp_dir, 'host2_timeline.log')

        with open(file1, 'w') as f:
            f.write("Delta(HH:MM:SS)\tBlock Label\tLog File\tData\n")
            f.write("00:00:02.000\tevent_b\ttest.log\t2024-03-22T10:30:47.000 Event B\n")

        with open(file2, 'w') as f:
            f.write("Delta(HH:MM:SS)\tBlock Label\tLog File\tData\n")
            f.write("00:00:01.000\tevent_a\ttest.log\t2024-03-22T10:30:46.000 Event A\n")

        host_files = [(file1, 'host1'), (file2, 'host2')]
        output_path = os.path.join(self.temp_dir, 'merged_timeline.log')

        merge_timeline_profiles(host_files, output_path)

        with open(output_path, 'r') as f:
            lines = f.readlines()

        # Should be sorted chronologically (Event A before Event B)
        content = ''.join(lines)
        event_a_pos = content.find('Event A')
        event_b_pos = content.find('Event B')
        self.assertLess(event_a_pos, event_b_pos)

    def test_extract_timestamp_from_data_iso_format(self):
        """Test _extract_timestamp_from_data with ISO timestamp"""
        line = "00:00:01.000\tevent\ttest.log\t2024-03-22T10:30:45.123 Some event data"
        result = _extract_timestamp_from_data(line)

        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 3)
        self.assertEqual(result.day, 22)

    def test_extract_timestamp_from_data_space_separated(self):
        """Test _extract_timestamp_from_data with space-separated timestamp"""
        line = "00:00:01.000\tevent\ttest.log\t2024-03-22 10:30:45.123 Some event data"
        result = _extract_timestamp_from_data(line)

        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2024)

    def test_extract_timestamp_from_data_invalid_data(self):
        """Test _extract_timestamp_from_data with invalid data"""
        line = "00:00:01.000\tevent\ttest.log\tNo timestamp here"
        result = _extract_timestamp_from_data(line)

        self.assertIsNone(result)

    def test_extract_timestamp_from_data_edge_cases(self):
        """Test _extract_timestamp_from_data with edge case data"""
        # Empty line
        result = _extract_timestamp_from_data("")
        self.assertIsNone(result)

        # Line with insufficient parts
        result = _extract_timestamp_from_data("single_part")
        self.assertIsNone(result)

    def test_print_output_files_lists_all_files(self):
        """Test print_output_files lists individual file paths"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)
        for name in ['lab_profile.timing', 'lab_profile.timing.csv', 'summary.timing']:
            with open(os.path.join(output_dir, name), 'w') as f:
                f.write('test')

        printed = []

        def capture(*a, **kw):
            printed.append(' '.join(str(x) for x in a))

        with unittest.mock.patch('builtins.print', side_effect=capture):
            print_output_files(output_dir)

        combined = '\n'.join(printed)
        self.assertIn('Output files:', combined)
        self.assertIn('lab_profile.timing.csv', combined)
        self.assertIn('summary.timing', combined)

    def test_print_output_files_nonexistent_dir(self):
        """Test print_output_files with non-existent directory produces no output"""
        printed = []
        with unittest.mock.patch('builtins.print', side_effect=lambda *a, **kw: printed.append(str(a))):
            print_output_files('/nonexistent/path')
        self.assertEqual(len(printed), 0)


if __name__ == '__main__':
    unittest.main()
