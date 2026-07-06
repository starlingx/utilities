#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test coverage for lpmp_graph.py functions.

Tests the graph generation functionality including data extraction from timeline
files, CSV creation, and graph generation with matplotlib.
"""

import csv
from datetime import datetime
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from lpmp_graph import create_csv
from lpmp_graph import create_graph
from lpmp_graph import create_state_csv
from lpmp_graph import create_state_graph
from lpmp_graph import create_system_graph
from lpmp_graph import extract_state_data
from lpmp_graph import extract_usage_data
from lpmp_graph import main as lpmp_graph_main
from lpmp_graph import parse_bound_date
from lpmp_graph import parse_timestamp_str
from lpmp_graph import run_combine_mode
from lpmp_graph import system_color_cycle
from lpmp_utils import get_verbose_level
from lpmp_utils import set_verbose_level
from test_base import LPMPTestBase

# Add the parent directory to the path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock the optional dependencies for testing
sys.modules['pandas'] = MagicMock()
sys.modules['matplotlib'] = MagicMock()
sys.modules['matplotlib.pyplot'] = MagicMock()

# Import after mocking dependencies


class TestLpmpGraphFunctions(LPMPTestBase):
    """Test lpmp_graph.py functions"""

    def setUp(self):
        """Set up test environment with temporary directory"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_timeline_file = os.path.join(self.temp_dir, 'test_timeline.log')
        self.test_csv_file = os.path.join(self.temp_dir, 'test_output.csv')
        self.test_png_file = os.path.join(self.temp_dir, 'test_graph.png')
        # Capture and reset the global vlog level so tests stay isolated.
        self._prev_verbose_level = get_verbose_level()
        set_verbose_level(0)

    def tearDown(self):
        """Clean up temporary directory"""
        # Restore vlog level so a verbose test does not leak into peers.
        set_verbose_level(self._prev_verbose_level)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_test_timeline_file(self, content_lines):
        """Helper to create test timeline file with given content"""
        with open(self.test_timeline_file, 'w') as f:
            # Write header
            f.write("Delta(HH:MM:SS)\tHostname\tBlock Label\tLog File\tData\n")
            f.write("-------------\t--------\t-----------\t--------\t----\n")
            # Write content lines
            for line in content_lines:
                f.write(line + '\n')

    # -------------------------------------------------------------------------
    # extract_usage_data() Tests
    # -------------------------------------------------------------------------

    def test_extract_usage_data_platform_cpu_debounce(self):
        """Test extract_usage_data with Platform CPU debounce format"""
        content_lines = [
            "00:00:01.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t2024-03-22T10:30:45.123 platform cpu usage debounce (85.5)",  # noqa: E501
            "00:00:02.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t2024-03-22T10:30:46.456 platform cpu usage debounce (92.1)",  # noqa: E501
        ]
        self._create_test_timeline_file(content_lines)

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU')

        self.assertEqual(len(usage_data), 2)
        self.assertEqual(usage_data[0], ('2024-03-22T10:30:45.123', 85.5))
        self.assertEqual(usage_data[1], ('2024-03-22T10:30:46.456', 92.1))

    def test_extract_usage_data_platform_cpu_reading(self):
        """Test extract_usage_data with Platform CPU reading format"""
        content_lines = [
            "00:00:01.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t2024-03-22T10:30:45.123 platform cpu usage reading: 78.3 % usage",  # noqa: E501
            "00:00:02.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t2024-03-22T10:30:46.456 platform cpu usage reading: 82.7 % usage",  # noqa: E501
        ]
        self._create_test_timeline_file(content_lines)

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU')

        self.assertEqual(len(usage_data), 2)
        self.assertEqual(usage_data[0], ('2024-03-22T10:30:45.123', 78.3))
        self.assertEqual(usage_data[1], ('2024-03-22T10:30:46.456', 82.7))

    def test_extract_usage_data_platform_memory(self):
        """Test extract_usage_data with Platform Memory format"""
        content_lines = [
            "00:00:01.000\tcontroller-0\tPlatform Mem Usage\ttest.log\t2024-03-22T10:30:45.123 platform memory usage: Usage: 65.4%",  # noqa: E501
            "00:00:02.000\tcontroller-0\tPlatform Mem Usage\ttest.log\t2024-03-22T10:30:46.456 platform memory usage: Usage: 71.2%",  # noqa: E501
        ]
        self._create_test_timeline_file(content_lines)

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform Mem')

        self.assertEqual(len(usage_data), 2)
        self.assertEqual(usage_data[0], ('2024-03-22T10:30:45.123', 65.4))
        self.assertEqual(usage_data[1], ('2024-03-22T10:30:46.456', 71.2))

    def test_extract_usage_data_platform_cpu_plugin(self):
        """Test extract_usage_data with Platform CPU plugin format"""
        content_lines = [
            "00:00:01.000\tcontroller-0\tPlatform Cpu Usage\ttest.log\t2024-03-22T10:30:45.123 platform cpu usage plugin Usage: 88.9%",  # noqa: E501
            "00:00:02.000\tcontroller-0\tPlatform Cpu Usage\ttest.log\t2024-03-22T10:30:46.456 platform cpu usage plugin Usage: 91.3%",  # noqa: E501
        ]
        self._create_test_timeline_file(content_lines)

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform Cpu')

        self.assertEqual(len(usage_data), 2)
        self.assertEqual(usage_data[0], ('2024-03-22T10:30:45.123', 88.9))
        self.assertEqual(usage_data[1], ('2024-03-22T10:30:46.456', 91.3))

    def test_extract_usage_data_no_matches(self):
        """Test extract_usage_data with no matching usage type"""
        content_lines = [
            "00:00:01.000\tcontroller-0\tOther Block\ttest.log\t2024-03-22T10:30:45.123 some other data",
            "00:00:02.000\tcontroller-0\tAnother Block\ttest.log\t2024-03-22T10:30:46.456 more data",
        ]
        self._create_test_timeline_file(content_lines)

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU')

        self.assertEqual(len(usage_data), 0)

    def test_extract_usage_data_malformed_lines(self):
        """Test extract_usage_data handles malformed lines gracefully"""
        content_lines = [
            "incomplete_line",
            "00:00:01.000\tcontroller-0\tPlatform CPU Usage\ttest.log",  # Missing data column
            "00:00:02.000\tcontroller-0\tPlatform CPU Usage\ttest.log\tno timestamp here",  # No timestamp
            "00:00:03.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t"
            "2024-03-22T10:30:45.123 platform cpu usage debounce (75.5)",  # Valid line
        ]
        self._create_test_timeline_file(content_lines)

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU')

        # Should only extract the one valid line
        self.assertEqual(len(usage_data), 1)
        self.assertEqual(usage_data[0], ('2024-03-22T10:30:45.123', 75.5))

    def test_extract_usage_data_verbose_mode(self):
        """Test extract_usage_data emits vlog debug output at -vvv."""
        content_lines = [
            "00:00:01.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t"
            "2024-03-22T10:30:45.123 platform cpu usage debounce (85.5)",
        ]
        self._create_test_timeline_file(content_lines)

        # Bump the shared vlog level so vlog2/vlog3 calls inside the
        # function emit. setUp/tearDown reset it around each test.
        set_verbose_level(3)

        # Capture stdout to verify verbose output
        with patch('builtins.print') as mock_print:
            usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU')

            # Verify data extraction worked
            self.assertEqual(len(usage_data), 1)
            self.assertEqual(usage_data[0], ('2024-03-22T10:30:45.123', 85.5))

            # Verify verbose output was generated via vlog (timestamped
            # "[YYYY-MM-DD HH:MM:SS.fff] Debug N:" prefix).
            self.assertTrue(mock_print.called)
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            debug_messages = [msg for msg in print_calls if 'Debug' in str(msg)]
            self.assertGreater(len(debug_messages), 0)

    def test_extract_usage_data_mixed_formats(self):
        """Test extract_usage_data with mixed data formats"""
        content_lines = [
            "00:00:01.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t"
            "2024-03-22T10:30:45.123 platform cpu usage debounce (85.5)",
            "00:00:02.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t"
            "2024-03-22T10:30:46.456 platform cpu usage reading: 78.3 % usage",
            "00:00:03.000\tcontroller-0\tPlatform Mem Usage\ttest.log\t"
            "2024-03-22T10:30:47.789 platform memory usage: Usage: 65.4%",
        ]
        self._create_test_timeline_file(content_lines)

        # Test CPU extraction
        cpu_data = extract_usage_data(self.test_timeline_file, 'Platform CPU')
        self.assertEqual(len(cpu_data), 2)
        self.assertEqual(cpu_data[0], ('2024-03-22T10:30:45.123', 85.5))
        self.assertEqual(cpu_data[1], ('2024-03-22T10:30:46.456', 78.3))

        # Test Memory extraction
        mem_data = extract_usage_data(self.test_timeline_file, 'Platform Mem')
        self.assertEqual(len(mem_data), 1)
        self.assertEqual(mem_data[0], ('2024-03-22T10:30:47.789', 65.4))

    # -------------------------------------------------------------------------
    # create_csv() Tests
    # -------------------------------------------------------------------------

    def test_create_csv_basic_functionality(self):
        """Test create_csv creates proper CSV file"""
        usage_data = [
            ('2024-03-22T10:30:45.123', 85.5),
            ('2024-03-22T10:30:46.456', 92.1),
            ('2024-03-22T10:30:47.789', 78.3),
        ]

        create_csv(usage_data, self.test_csv_file, 'Platform CPU')

        # Verify file was created
        self.assertTrue(os.path.exists(self.test_csv_file))

        # Verify CSV content
        with open(self.test_csv_file, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Check header
        self.assertEqual(rows[0], ['Timestamp', 'Platform_CPU_Usage'])

        # Check data rows
        self.assertEqual(len(rows), 4)  # Header + 3 data rows
        self.assertEqual(rows[1], ['2024-03-22T10:30:45.123', '85.5'])
        self.assertEqual(rows[2], ['2024-03-22T10:30:46.456', '92.1'])
        self.assertEqual(rows[3], ['2024-03-22T10:30:47.789', '78.3'])

    def test_create_csv_column_name_formatting(self):
        """Test create_csv formats column names correctly"""
        usage_data = [('2024-03-22T10:30:45.123', 65.4)]

        create_csv(usage_data, self.test_csv_file, 'Platform Memory')

        with open(self.test_csv_file, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)

        # Spaces should be replaced with underscores
        self.assertEqual(header, ['Timestamp', 'Platform_Memory_Usage'])

    def test_create_csv_empty_data(self):
        """Test create_csv with empty usage data"""
        usage_data = []

        create_csv(usage_data, self.test_csv_file, 'Platform CPU')

        # Verify file was created with just header
        self.assertTrue(os.path.exists(self.test_csv_file))

        with open(self.test_csv_file, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 1)  # Only header
        self.assertEqual(rows[0], ['Timestamp', 'Platform_CPU_Usage'])

    def test_create_csv_verbose_mode(self):
        """Test create_csv emits vlog debug output at -vv."""
        usage_data = [('2024-03-22T10:30:45.123', 85.5)]

        # create_csv only uses vlog2 entries, so level 2 is enough.
        set_verbose_level(2)

        with patch('builtins.print') as mock_print:
            create_csv(usage_data, self.test_csv_file, 'Platform CPU')

            # Verify verbose output was generated via vlog.
            self.assertTrue(mock_print.called)
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            debug_messages = [msg for msg in print_calls if 'Debug' in str(msg)]
            self.assertGreater(len(debug_messages), 0)

    # -------------------------------------------------------------------------
    # create_graph() Tests (with mocked matplotlib)
    # -------------------------------------------------------------------------

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_create_graph_basic_functionality(self, mock_plt, mock_pd):
        """Test create_graph with mocked pandas and matplotlib"""
        # Setup mock DataFrame
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=3)
        mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        # Create test CSV file
        usage_data = [
            ('2024-03-22T10:30:45.123', 85.5),
            ('2024-03-22T10:30:46.456', 92.1),
        ]
        create_csv(usage_data, self.test_csv_file, 'Platform CPU')

        # Test graph creation
        create_graph(self.test_csv_file, self.test_png_file, 'Platform CPU', (0, 100))

        # Verify pandas was called correctly
        mock_pd.read_csv.assert_called_once_with(self.test_csv_file)
        mock_pd.to_datetime.assert_called_once()

        # Verify matplotlib was called
        mock_plt.figure.assert_called_once_with(figsize=(12, 6))
        mock_plt.plot.assert_called_once()
        mock_plt.title.assert_called_once_with('Platform CPU Usage Over Time')  # noqa: E501
        mock_plt.xlabel.assert_called_once_with('Time')
        mock_plt.ylabel.assert_called_once_with('Usage (%)')
        mock_plt.ylim.assert_called_once_with(0, 100)  # noqa: E501
        mock_plt.savefig.assert_called_once_with(self.test_png_file,  # noqa: E501
                                                 dpi=300, bbox_inches='tight')
        mock_plt.close.assert_called_once()

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_create_graph_verbose_mode(self, mock_plt, mock_pd):
        """Test create_graph emits vlog debug output at -vv."""
        # Setup mock DataFrame
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=2)
        mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        # Create test CSV file
        usage_data = [('2024-03-22T10:30:45.123', 85.5)]
        create_csv(usage_data, self.test_csv_file, 'Platform CPU')

        # create_graph uses vlog2 entries; level 2 is enough.
        set_verbose_level(2)

        with patch('builtins.print') as mock_print:
            create_graph(self.test_csv_file, self.test_png_file,  # noqa: E501
                         'Platform CPU', (0, 100))

            # Verify verbose output was generated via vlog.
            self.assertTrue(mock_print.called)
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            debug_messages = [msg for msg in print_calls if 'Debug' in str(msg)]
            self.assertGreater(len(debug_messages), 0)

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_create_graph_custom_y_range(self, mock_plt, mock_pd):
        """Test create_graph with custom Y-axis range"""
        # Setup mock DataFrame
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=1)
        mock_df.columns = ['Timestamp', 'Platform_Memory_Usage']
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        # Create test CSV file
        usage_data = [('2024-03-22T10:30:45.123', 65.4)]
        create_csv(usage_data, self.test_csv_file, 'Platform Memory')

        # Test with custom range
        create_graph(self.test_csv_file, self.test_png_file, 'Platform Memory',  # noqa: E501
                     (0, 80))

        # Verify custom Y-axis range was applied
        mock_plt.ylim.assert_called_once_with(0, 80)
        mock_plt.title.assert_called_once_with('Platform Memory Usage Over Time')  # noqa: E501

    # -------------------------------------------------------------------------
    # Integration Tests
    # -------------------------------------------------------------------------

    def test_end_to_end_workflow(self):
        """Test complete workflow: extract -> CSV -> graph (with mocked matplotlib)"""
        # Create test timeline file
        content_lines = [
            "00:00:01.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t2024-03-22T10:30:45.123 platform cpu usage debounce (85.5)",  # noqa: E501
            "00:00:02.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t2024-03-22T10:30:46.456 platform cpu usage reading: 78.3 % usage",  # noqa: E501
            "00:00:03.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t2024-03-22T10:30:47.789 platform cpu usage debounce (92.1)",  # noqa: E501
        ]
        self._create_test_timeline_file(content_lines)

        # Step 1: Extract usage data
        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU')
        self.assertEqual(len(usage_data), 3)

        # Step 2: Create CSV
        create_csv(usage_data, self.test_csv_file, 'Platform CPU')
        self.assertTrue(os.path.exists(self.test_csv_file))

        # Verify CSV content
        with open(self.test_csv_file, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 4)  # Header + 3 data rows
        self.assertEqual(rows[0], ['Timestamp', 'Platform_CPU_Usage'])
        self.assertEqual(rows[1], ['2024-03-22T10:30:45.123', '85.5'])
        self.assertEqual(rows[2], ['2024-03-22T10:30:46.456', '78.3'])
        self.assertEqual(rows[3], ['2024-03-22T10:30:47.789', '92.1'])

        # Step 3: Create graph (mocked)
        with patch('lpmp_graph.pd') as mock_pd, patch('lpmp_graph.plt') as mock_plt:
            mock_df = MagicMock()
            mock_df.__len__ = MagicMock(return_value=3)
            mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
            mock_pd.read_csv.return_value = mock_df
            mock_pd.to_datetime.return_value = mock_df['Timestamp']

            create_graph(self.test_csv_file, self.test_png_file, 'Platform CPU',  # noqa: E501
                         (0, 100))

            # Verify graph creation was attempted
            mock_plt.savefig.assert_called_once_with(self.test_png_file, dpi=300,  # noqa: E501
                                                     bbox_inches='tight')

    def test_file_error_handling(self):
        """Test error handling for file operations"""
        # Test extract_usage_data with non-existent file
        with self.assertRaises(FileNotFoundError):
            extract_usage_data('/non/existent/file.log', 'Platform CPU')

        # Test create_csv with invalid output path
        usage_data = [('2024-03-22T10:30:45.123', 85.5)]
        invalid_path = '/invalid/path/output.csv'

        with self.assertRaises(FileNotFoundError):
            create_csv(usage_data, invalid_path, 'Platform CPU')


# =============================================================================
# Tests for parse_bound_date, parse_timestamp_str, bounds in extract_usage_data
# =============================================================================

class TestParseHelpers(LPMPTestBase):
    """Unit tests for the small parsing helpers in lpmp_graph.py."""

    def test_parse_bound_date_none_returns_none(self):
        self.assertIsNone(parse_bound_date(None, 'start'))
        self.assertIsNone(parse_bound_date('', 'stop'))

    def test_parse_bound_date_date_only_start_anchors_to_midnight(self):
        result = parse_bound_date('2026-06-08', 'start')
        self.assertEqual(result,
                         datetime(2026, 6, 8, 0, 0, 0))

    def test_parse_bound_date_date_only_stop_anchors_to_end_of_day(self):
        result = parse_bound_date('2026-06-08', 'stop')
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 6)
        self.assertEqual(result.day, 8)
        self.assertEqual(result.hour, 23)
        self.assertEqual(result.minute, 59)
        self.assertEqual(result.second, 59)

    def test_parse_bound_date_full_iso_t_separator(self):
        result = parse_bound_date('2026-06-08T14:30:15', 'start')
        self.assertEqual(result, datetime(2026, 6, 8, 14, 30, 15))

    def test_parse_bound_date_full_iso_space_separator(self):
        # Anything other than 'T' at index 10 should be normalised to 'T'
        result = parse_bound_date('2026-06-08 14:30:15', 'start')
        self.assertEqual(result, datetime(2026, 6, 8, 14, 30, 15))

    def test_parse_bound_date_hour_minute_only(self):
        result = parse_bound_date('2026-06-08T14:30', 'stop')
        self.assertEqual(result, datetime(2026, 6, 8, 14, 30, 0))

    def test_parse_bound_date_invalid_format_exits(self):
        with self.assertRaises(SystemExit) as cm:
            parse_bound_date('not-a-date', 'start')
        self.assertEqual(cm.exception.code, 1)

    def test_parse_timestamp_str_valid_iso(self):
        result = parse_timestamp_str('2026-06-08T14:30:15.123')
        self.assertEqual(result, datetime(2026, 6, 8, 14, 30, 15, 123000))

    def test_parse_timestamp_str_invalid_returns_none(self):
        self.assertIsNone(parse_timestamp_str('garbage'))


# =============================================================================
# Tests for extract_usage_data with -s/-e bounds
# =============================================================================

class TestExtractUsageDataBounds(LPMPTestBase):
    """Cover the start/stop_date filtering branches in extract_usage_data."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_timeline_file = os.path.join(self.temp_dir, 'bounds.log')
        self._prev_verbose_level = get_verbose_level()
        set_verbose_level(0)

    def tearDown(self):
        set_verbose_level(self._prev_verbose_level)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _write_lines(self, lines):
        with open(self.test_timeline_file, 'w') as f:
            f.write("Delta(HH:MM:SS)\tHostname\tBlock Label\tLog File\tData\n")
            f.write("-------------\t--------\t-----------\t--------\t----\n")
            for line in lines:
                f.write(line + '\n')

    def _line(self, ts, value):
        return (f"00:00:01.000\tcontroller-0\tPlatform CPU\ttest.log\t"
                f"{ts} platform cpu dispatch Usage: {value}%")

    def test_start_date_drops_earlier_rows(self):
        self._write_lines([
            self._line('2026-06-08T10:00:00.000', '10.0'),
            self._line('2026-06-09T10:00:00.000', '20.0'),
            self._line('2026-06-10T10:00:00.000', '30.0'),
        ])
        data = extract_usage_data(
            self.test_timeline_file, 'Platform CPU',
            start_date=datetime(2026, 6, 9, 0, 0, 0))
        # Only the two rows on or after 2026-06-09 should remain
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0][1], 20.0)
        self.assertEqual(data[1][1], 30.0)

    def test_stop_date_drops_later_rows(self):
        self._write_lines([
            self._line('2026-06-08T10:00:00.000', '10.0'),
            self._line('2026-06-09T10:00:00.000', '20.0'),
            self._line('2026-06-10T10:00:00.000', '30.0'),
        ])
        data = extract_usage_data(
            self.test_timeline_file, 'Platform CPU',
            stop_date=datetime(2026, 6, 9, 23, 59, 59))
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0][1], 10.0)
        self.assertEqual(data[1][1], 20.0)

    def test_both_bounds_narrow_window(self):
        self._write_lines([
            self._line('2026-06-08T10:00:00.000', '10.0'),
            self._line('2026-06-09T10:00:00.000', '20.0'),
            self._line('2026-06-10T10:00:00.000', '30.0'),
        ])
        data = extract_usage_data(
            self.test_timeline_file, 'Platform CPU',
            start_date=datetime(2026, 6, 9, 0, 0, 0),
            stop_date=datetime(2026, 6, 9, 23, 59, 59))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0][1], 20.0)

    def test_bounds_with_unparseable_timestamp_dropped(self):
        # Timestamp regex matches digits, but a future format change could
        # produce something fromisoformat cannot parse. The bounded path
        # should drop those rows silently rather than crash.
        with patch('lpmp_graph.parse_timestamp_str', return_value=None):
            self._write_lines([
                self._line('2026-06-09T10:00:00.000', '20.0'),
            ])
            data = extract_usage_data(
                self.test_timeline_file, 'Platform CPU',
                start_date=datetime(2026, 6, 9, 0, 0, 0))
            self.assertEqual(len(data), 0)


# =============================================================================
# Tests for system_color_cycle
# =============================================================================

class TestSystemColorCycle(LPMPTestBase):
    """Cover the three palette branches in system_color_cycle."""

    def test_tab10_for_small_systems(self):
        colors = system_color_cycle(5)
        self.assertEqual(len(colors), 5)

    def test_tab10_at_boundary(self):
        colors = system_color_cycle(10)
        self.assertEqual(len(colors), 10)

    def test_tab20_for_medium_systems(self):
        colors = system_color_cycle(15)
        self.assertEqual(len(colors), 15)

    def test_tab20_at_boundary(self):
        colors = system_color_cycle(20)
        self.assertEqual(len(colors), 20)

    def test_hsv_for_large_systems(self):
        colors = system_color_cycle(30)
        self.assertEqual(len(colors), 30)

    def test_exception_path_returns_defaults(self):
        # Force the inner block to throw so the except: branch runs.
        with patch('lpmp_graph.plt') as mock_plt:
            mock_plt.get_cmap.side_effect = RuntimeError("boom")
            colors = system_color_cycle(3)
            self.assertEqual(len(colors), 3)
            # Defaults are a stable strings list
            for c in colors:
                self.assertIsInstance(c, str)


# =============================================================================
# Tests for create_system_graph
# =============================================================================

class TestCreateSystemGraph(LPMPTestBase):
    """Cover create_system_graph's success, skip and short-circuit paths."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._prev_verbose_level = get_verbose_level()
        set_verbose_level(0)

    def tearDown(self):
        set_verbose_level(self._prev_verbose_level)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _make_csv(self, name):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write("Timestamp,Platform_CPU_Usage\n")
            f.write("2026-06-08T10:00:00.000,10.0\n")
            f.write("2026-06-08T10:00:30.000,12.0\n")
        return path

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_multi_host_happy_path(self, mock_plt, mock_pd):
        csv_a = self._make_csv('a.csv')
        csv_b = self._make_csv('b.csv')

        # Build a mock DataFrame that satisfies the function's access pattern
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=2)
        mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        png_path = os.path.join(self.temp_dir, 'system.png')
        ok = create_system_graph(
            [('controller-1', csv_b), ('controller-0', csv_a)],
            png_path, 'Platform CPU', (0, 110))

        self.assertTrue(ok)
        mock_plt.savefig.assert_called_once()
        mock_plt.title.assert_called_once()
        mock_plt.legend.assert_called_once()
        # Two host series → two plt.plot calls
        self.assertEqual(mock_plt.plot.call_count, 2)

    def test_no_csvs_present_returns_false(self):
        png_path = os.path.join(self.temp_dir, 'system.png')
        ok = create_system_graph(
            [('controller-0', '/does/not/exist.csv')],
            png_path, 'Platform CPU', (0, 110))
        self.assertFalse(ok)
        self.assertFalse(os.path.exists(png_path))

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_column_missing_skips_host(self, mock_plt, mock_pd):
        csv_a = self._make_csv('a.csv')

        # DataFrame has the wrong column → host should be skipped, no save
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=2)
        mock_df.columns = ['Timestamp']  # missing Platform_CPU_Usage
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        png_path = os.path.join(self.temp_dir, 'system.png')
        ok = create_system_graph(
            [('controller-0', csv_a)],
            png_path, 'Platform CPU', (0, 110))

        # No rows plotted → returns False, no savefig
        self.assertFalse(ok)
        mock_plt.savefig.assert_not_called()

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_read_failure_is_warning_not_crash(self, mock_plt, mock_pd):
        csv_a = self._make_csv('a.csv')
        csv_b = self._make_csv('b.csv')

        # First read raises, second succeeds. The function should warn and
        # still plot the second host.
        good_df = MagicMock()
        good_df.__len__ = MagicMock(return_value=2)
        good_df.columns = ['Timestamp', 'Platform_CPU_Usage']
        mock_pd.read_csv.side_effect = [RuntimeError("bad csv"), good_df]
        mock_pd.to_datetime.return_value = good_df['Timestamp']

        png_path = os.path.join(self.temp_dir, 'system.png')
        ok = create_system_graph(
            [('controller-0', csv_a), ('controller-1', csv_b)],
            png_path, 'Platform CPU', (0, 110))

        self.assertTrue(ok)
        self.assertEqual(mock_plt.plot.call_count, 1)


# =============================================================================
# Tests for main() entry point and run_combine_mode
# =============================================================================

class TestMainEntryPoint(LPMPTestBase):
    """End-to-end tests for main() via sys.argv patching."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_timeline_file = os.path.join(self.temp_dir, 'profile.log')
        self._prev_verbose_level = get_verbose_level()
        set_verbose_level(0)
        # Run main() relative to the temp dir so default-named outputs land here
        self._prev_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self._prev_cwd)
        set_verbose_level(self._prev_verbose_level)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _write_basic_timeline(self):
        with open(self.test_timeline_file, 'w') as f:
            f.write("Delta(HH:MM:SS)\tHostname\tBlock Label\tLog File\tData\n")
            f.write("-------------\t--------\t-----------\t--------\t----\n")
            f.write("00:00:01.000\tcontroller-0\tPlatform CPU\ttest.log\t"
                    "2026-06-08T10:00:00.000 platform cpu dispatch Usage: 12.5%\n")

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_main_per_host_happy_path(self, mock_plt, mock_pd):
        self._write_basic_timeline()

        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=1)
        mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        argv = ['lpmp_graph.py',
                '-i', self.test_timeline_file,
                '-n', 'Platform CPU']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

        # CSV next to the cwd should be produced with the synthesized prefix
        produced = [f for f in os.listdir(self.temp_dir) if f.endswith('.csv')]
        self.assertEqual(len(produced), 1)
        self.assertIn('Platform_CPU', produced[0])
        mock_plt.savefig.assert_called_once()

    def test_main_missing_input_returns_without_crash(self):
        argv = ['lpmp_graph.py', '-n', 'Platform CPU']
        with patch.object(sys, 'argv', argv):
            # No --input and no --combine → prints error and returns.
            # Just verify it does not raise.
            lpmp_graph_main()

    def test_main_invalid_range_returns_without_crash(self):
        self._write_basic_timeline()
        argv = ['lpmp_graph.py',
                '-i', self.test_timeline_file,
                '-r', 'not:numbers']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()  # should print error and return

    def test_main_stop_before_start_returns_without_crash(self):
        self._write_basic_timeline()
        argv = ['lpmp_graph.py',
                '-i', self.test_timeline_file,
                '-s', '2026-06-10',
                '-e', '2026-06-08']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()  # rejected with error

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_main_no_data_path(self, mock_plt, mock_pd):
        # Timeline with no matching block label → extract returns []
        with open(self.test_timeline_file, 'w') as f:
            f.write("Delta(HH:MM:SS)\tHostname\tBlock Label\tLog File\tData\n")
            f.write("-------------\t--------\t-----------\t--------\t----\n")
            f.write("00:00:01.000\tcontroller-0\tOther Block\ttest.log\tdata\n")

        argv = ['lpmp_graph.py',
                '-i', self.test_timeline_file,
                '-n', 'Platform CPU',
                '-v']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

        # Verbose mode should also exercise the "Checking first 10 lines"
        # diagnostic branch; we only assert no CSV was produced.
        produced = [f for f in os.listdir(self.temp_dir) if f.endswith('.csv')]
        self.assertEqual(len(produced), 0)

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_main_combine_happy_path(self, mock_plt, mock_pd):
        # Create two host CSVs and let --combine fold them into one PNG
        for name in ('a.csv', 'b.csv'):
            with open(os.path.join(self.temp_dir, name), 'w') as f:
                f.write("Timestamp,Platform_CPU_Usage\n")
                f.write("2026-06-08T10:00:00.000,10.0\n")

        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=1)
        mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        out_png = os.path.join(self.temp_dir, 'system')
        argv = ['lpmp_graph.py', '--combine',
                '-o', out_png,
                '-n', 'Platform CPU',
                '--host-csv', f'controller-0={os.path.join(self.temp_dir, "a.csv")}',
                '--host-csv', f'controller-1={os.path.join(self.temp_dir, "b.csv")}']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

        mock_plt.savefig.assert_called_once()

    def test_main_combine_missing_output_errors(self):
        argv = ['lpmp_graph.py', '--combine',
                '--host-csv', 'controller-0=/tmp/missing.csv']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()  # prints error and returns

    def test_main_combine_missing_host_csv_errors(self):
        argv = ['lpmp_graph.py', '--combine',
                '-o', os.path.join(self.temp_dir, 'out.png')]
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()  # prints error and returns

    def test_main_combine_malformed_host_csv_errors(self):
        argv = ['lpmp_graph.py', '--combine',
                '-o', os.path.join(self.temp_dir, 'out.png'),
                '--host-csv', 'no_equals_sign']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

    def test_main_combine_empty_host_errors(self):
        argv = ['lpmp_graph.py', '--combine',
                '-o', os.path.join(self.temp_dir, 'out.png'),
                '--host-csv', '=/some/path.csv']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

    def test_run_combine_mode_directly_with_dates_logs_note(self):
        # Exercise the "bounds echo" branch in run_combine_mode without
        # going through main(). Reuse a created csv so the rest succeeds.
        csv_path = os.path.join(self.temp_dir, 'a.csv')
        with open(csv_path, 'w') as f:
            f.write("Timestamp,Platform_CPU_Usage\n")
            f.write("2026-06-08T10:00:00.000,10.0\n")

        args = MagicMock()
        args.output = os.path.join(self.temp_dir, 'out')  # exercise .png append
        args.host_csv = [f'controller-0={csv_path}']
        args.name = 'Platform CPU'
        args.range = '0:110'
        args.start_date = '2026-06-08'
        args.stop_date = '2026-06-09'

        set_verbose_level(2)
        with patch('lpmp_graph.pd') as mock_pd, patch('lpmp_graph.plt') as mock_plt:
            mock_df = MagicMock()
            mock_df.__len__ = MagicMock(return_value=1)
            mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
            mock_pd.read_csv.return_value = mock_df
            mock_pd.to_datetime.return_value = mock_df['Timestamp']
            run_combine_mode(args, (0, 110))
            mock_plt.savefig.assert_called_once()

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_main_per_host_with_explicit_output_prefix(self, mock_plt, mock_pd):
        # Exercise the args.output branch of main() per-host mode.
        self._write_basic_timeline()
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=1)
        mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        prefix = os.path.join(self.temp_dir, 'explicit_prefix')
        argv = ['lpmp_graph.py',
                '-i', self.test_timeline_file,
                '-o', prefix,
                '-n', 'Platform CPU']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

        self.assertTrue(os.path.exists(prefix + '.csv'))
        mock_plt.savefig.assert_called_once()

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_main_no_data_with_higher_verbose_lists_lines(self, mock_plt, mock_pd):
        # Hit the "Checking first 10 lines" diagnostic branch (level >= 2).
        with open(self.test_timeline_file, 'w') as f:
            f.write("Delta(HH:MM:SS)\tHostname\tBlock Label\tLog File\tData\n")
            f.write("-------------\t--------\t-----------\t--------\t----\n")
            for i in range(15):
                f.write(f"00:00:0{i:02d}.000\tcontroller-0\tOther\ttest.log\trow {i}\n")

        argv = ['lpmp_graph.py',
                '-i', self.test_timeline_file,
                '-n', 'Platform CPU',
                '-vv']
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

        produced = [f for f in os.listdir(self.temp_dir) if f.endswith('.csv')]
        self.assertEqual(len(produced), 0)

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_run_combine_mode_all_csvs_missing_prints_failure(self,
                                                              mock_plt, mock_pd):
        # No CSVs exist → create_system_graph returns False, run_combine_mode
        # falls through to the "No system graph produced" print path.
        args = MagicMock()
        args.output = os.path.join(self.temp_dir, 'out.png')
        args.host_csv = ['controller-0=/nope/a.csv', 'controller-1=/nope/b.csv']
        args.name = 'Platform CPU'
        args.range = '0:110'
        args.start_date = None
        args.stop_date = None

        run_combine_mode(args, (0, 110))
        mock_plt.savefig.assert_not_called()


# =============================================================================
# Tests for state-mode (collectd overage) graph
# =============================================================================

class TestStateGraph(LPMPTestBase):
    """Cover extract_state_data, create_state_csv, and create_state_graph."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_timeline_file = os.path.join(self.temp_dir, 'overage.log')
        self.test_csv_file = os.path.join(self.temp_dir, 'state.csv')
        self.test_png_file = os.path.join(self.temp_dir, 'state.png')
        self._prev_verbose_level = get_verbose_level()
        set_verbose_level(0)

    def tearDown(self):
        set_verbose_level(self._prev_verbose_level)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _write_lines(self, lines):
        with open(self.test_timeline_file, 'w') as f:
            f.write("Delta(HH:MM:SS)\tHostname\tBlock Label\tLog File\tData\n")
            f.write("-------------\t--------\t-----------\t--------\t----\n")
            for line in lines:
                f.write(line + '\n')

    def _row(self, ts, transition, value, counters, committed):
        # Mirrors the format emitted by collectd: alarm notifier Platform CPU
        # host=<host> debounce 'A -> B' (value) (n:m) <True|False>
        return (
            "00:00:01.000\tcontroller-0\tPlatform CPU\tcollectd.log\t"
            f"{ts} controller-0 collectd[27020]: info alarm notifier "
            f"Platform CPU host=controller-0 debounce '{transition}' "
            f"({value}) ({counters}) {committed}"
        )

    def test_extract_state_data_collects_only_committed_transitions(self):
        self._write_lines([
            # Debouncing rows are ignored even if direction is correct.
            self._row('2026-06-09T10:15:36.600', 'okay -> failure',
                      '99.07', '2:1', 'False'),
            self._row('2026-06-09T10:19:45.785', 'okay -> failure',
                      '99.00', '8:7', 'True'),
            self._row('2026-06-09T11:01:37.112', 'failure -> okay',
                      '70.14', '7:7', 'True'),
            self._row('2026-06-09T11:30:00.000', 'okay -> warning',
                      '90.23', '5:0', 'True'),
        ])
        data = extract_state_data(self.test_timeline_file, 'Platform CPU')

        # 3 committed transitions plus a synthesized baseline row at the
        # first matched-row timestamp showing the prior 'okay' state.
        self.assertEqual(len(data), 4)
        self.assertEqual(data[0][1], 0)  # baseline okay
        # The baseline anchor uses the first matched-row timestamp (here
        # the debouncing row's timestamp, since it carries the same block
        # label).
        self.assertEqual(data[0][0], '2026-06-09T10:15:36.600')
        self.assertEqual(data[1], ('2026-06-09T10:19:45.785', 2))  # failure
        self.assertEqual(data[2], ('2026-06-09T11:01:37.112', 0))  # okay
        self.assertEqual(data[3], ('2026-06-09T11:30:00.000', 1))  # warning

    def test_extract_state_data_respects_bounds(self):
        self._write_lines([
            self._row('2026-06-08T23:00:00.000', 'okay -> failure',
                      '95.0', '7:7', 'True'),
            self._row('2026-06-09T12:00:00.000', 'failure -> okay',
                      '60.0', '5:5', 'True'),
            self._row('2026-06-10T01:00:00.000', 'okay -> warning',
                      '92.0', '4:0', 'True'),
        ])
        data = extract_state_data(
            self.test_timeline_file, 'Platform CPU',
            start_date=datetime(2026, 6, 9, 0, 0, 0),
            stop_date=datetime(2026, 6, 9, 23, 59, 59))

        # In-window: only the 12:00 'failure -> okay' transition. The
        # baseline row at start_date carries the prior 'failure' state.
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0][1], 2)  # baseline failure (prior state)
        self.assertEqual(data[0][0], '2026-06-09T00:00:00.000')  # anchored at start_date
        self.assertEqual(data[1], ('2026-06-09T12:00:00.000', 0))

    def test_extract_state_data_ignores_non_matching_block_label(self):
        self._write_lines([
            "00:00:01.000\tcontroller-0\tOther Block\tcollectd.log\t"
            "2026-06-09T12:00:00.000 ... debounce 'okay -> failure' (99.0) (7:7) True",
        ])
        data = extract_state_data(self.test_timeline_file, 'Platform CPU')
        self.assertEqual(len(data), 0)

    def test_extract_state_data_skips_lines_without_timestamp(self):
        self._write_lines([
            "00:00:01.000\tcontroller-0\tPlatform CPU\tcollectd.log\t"
            "no timestamp here debounce 'okay -> failure' (99.0) (7:7) True",
        ])
        data = extract_state_data(self.test_timeline_file, 'Platform CPU')
        self.assertEqual(len(data), 0)

    def test_create_state_csv_writes_three_columns(self):
        state_data = [
            ('2026-06-09T10:19:45.785', 2),
            ('2026-06-09T11:01:37.112', 0),
        ]
        create_state_csv(state_data, self.test_csv_file, 'Platform CPU')

        with open(self.test_csv_file, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
        self.assertEqual(rows[0],
                         ['Timestamp', 'Platform_CPU_State', 'Level'])
        self.assertEqual(rows[1][2], '2')  # critical
        self.assertEqual(rows[2][2], '0')  # okay

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_create_state_graph_renders_and_saves(self, mock_plt, mock_pd):
        # pd.to_datetime and pd.Timedelta need to behave well enough for
        # the function to compute the trailing tail segment.
        from datetime import timedelta as _td
        mock_pd.to_datetime.side_effect = lambda ts: datetime.fromisoformat(ts)
        mock_pd.Timedelta.side_effect = lambda seconds=0: _td(seconds=seconds)

        state_data = [
            ('2026-06-09T10:19:45.785', 2),
            ('2026-06-09T11:01:37.112', 0),
            ('2026-06-09T11:30:00.000', 1),
        ]
        ok = create_state_graph(state_data, self.test_png_file, 'Platform CPU')

        self.assertTrue(ok)
        mock_plt.step.assert_called_once()
        mock_plt.title.assert_called_once_with('Platform CPU Alarm State Over Time')
        mock_plt.savefig.assert_called_once_with(self.test_png_file,
                                                 dpi=300, bbox_inches='tight')
        mock_plt.close.assert_called_once()

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_create_state_graph_empty_returns_false(self, mock_plt, mock_pd):
        ok = create_state_graph([], self.test_png_file, 'Platform CPU')
        self.assertFalse(ok)
        mock_plt.savefig.assert_not_called()

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_create_state_graph_single_sample_uses_default_tail(self, mock_plt, mock_pd):
        # Single-sample case hits the else branch of the tail-length picker.
        from datetime import timedelta as _td
        mock_pd.to_datetime.side_effect = lambda ts: datetime.fromisoformat(ts)
        mock_pd.Timedelta.side_effect = lambda seconds=0: _td(seconds=seconds)

        state_data = [('2026-06-09T10:19:45.785', 2)]
        ok = create_state_graph(state_data, self.test_png_file, 'Platform CPU')
        self.assertTrue(ok)
        mock_plt.step.assert_called_once()
        mock_plt.savefig.assert_called_once()

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_main_dispatches_to_state_mode(self, mock_plt, mock_pd):
        # End-to-end via sys.argv: --style state should run the state pipeline.
        from datetime import timedelta as _td
        mock_pd.to_datetime.side_effect = lambda ts: datetime.fromisoformat(ts)
        mock_pd.Timedelta.side_effect = lambda seconds=0: _td(seconds=seconds)

        self._write_lines([
            self._row('2026-06-09T10:19:45.785', 'okay -> failure',
                      '99.0', '7:7', 'True'),
            self._row('2026-06-09T11:01:37.112', 'failure -> okay',
                      '60.0', '5:5', 'True'),
        ])

        prefix = os.path.join(self.temp_dir, 'state_out')
        argv = ['lpmp_graph.py',
                '--style', 'state',
                '-i', self.test_timeline_file,
                '-n', 'Platform CPU',
                '-o', prefix]
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

        self.assertTrue(os.path.exists(prefix + '.csv'))
        mock_plt.step.assert_called_once()

    @patch('lpmp_graph.pd')
    @patch('lpmp_graph.plt')
    def test_main_state_mode_with_no_transitions(self, mock_plt, mock_pd):
        # Timeline has the right block label but no committed transitions.
        self._write_lines([
            self._row('2026-06-09T10:15:36.600', 'okay -> failure',
                      '99.07', '2:1', 'False'),
        ])
        prefix = os.path.join(self.temp_dir, 'state_empty')
        argv = ['lpmp_graph.py',
                '--style', 'state',
                '-i', self.test_timeline_file,
                '-n', 'Platform CPU',
                '-o', prefix]
        with patch.object(sys, 'argv', argv):
            lpmp_graph_main()

        # Should not create a CSV or PNG when nothing was committed.
        self.assertFalse(os.path.exists(prefix + '.csv'))
        mock_plt.savefig.assert_not_called()

    def test_extract_state_data_dedupes_consecutive_same_state(self):
        # Collectd often emits multiple committed 'failure -> okay' rows
        # while staying in okay. Only the first such transition should
        # appear in the output (plus the synthesized baseline).
        self._write_lines([
            # A non-transition row earlier than the first transition gives
            # the baseline a real anchor (mirrors real bundle data where
            # 'alarm notifier monitoring ...' lines arrive before any
            # debounce decisions).
            "00:00:01.000\tcontroller-0\tPlatform CPU\tcollectd.log\t"
            "2026-06-09T09:00:00.000 controller-0 collectd[27020]: "
            "info alarm notifier monitoring Platform CPU usage",
            self._row('2026-06-09T10:00:00.000', 'okay -> failure',
                      '99.0', '7:7', 'True'),
            self._row('2026-06-09T10:30:00.000', 'failure -> okay',
                      '50.0', '3:3', 'True'),
            self._row('2026-06-09T10:35:00.000', 'failure -> okay',
                      '40.0', '3:3', 'True'),
            self._row('2026-06-09T10:40:00.000', 'failure -> okay',
                      '60.0', '3:3', 'True'),
        ])
        data = extract_state_data(self.test_timeline_file, 'Platform CPU')

        # baseline okay + failure transition + first okay clear. The two
        # extra okay rows are collapsed.
        self.assertEqual(len(data), 3)
        levels = [lvl for _, lvl in data]
        self.assertEqual(levels, [0, 2, 0])

    def test_extract_state_data_no_baseline_when_no_committed_rows(self):
        # No committed transitions found -> no baseline insertion either.
        self._write_lines([
            self._row('2026-06-09T10:15:36.600', 'okay -> failure',
                      '99.07', '2:1', 'False'),
            self._row('2026-06-09T10:19:00.000', 'okay -> failure',
                      '95.0', '4:3', 'False'),
        ])
        data = extract_state_data(self.test_timeline_file, 'Platform CPU')
        self.assertEqual(data, [])

    def test_extract_state_data_baseline_anchored_at_start_date(self):
        # When -s/-e bounds are applied and start_date is earlier than the
        # first in-window matched row, the baseline anchor uses start_date.
        self._write_lines([
            self._row('2026-06-09T12:00:00.000', 'okay -> failure',
                      '99.0', '7:7', 'True'),
        ])
        data = extract_state_data(
            self.test_timeline_file, 'Platform CPU',
            start_date=datetime(2026, 6, 9, 6, 0, 0))

        self.assertEqual(len(data), 2)
        # Baseline timestamp string format mirrors what extract_state_data
        # emits (millisecond precision, 'T' separator).
        self.assertEqual(data[0], ('2026-06-09T06:00:00.000', 0))
        self.assertEqual(data[1], ('2026-06-09T12:00:00.000', 2))


if __name__ == '__main__':
    unittest.main()
