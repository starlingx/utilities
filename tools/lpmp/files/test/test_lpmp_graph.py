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
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from lpmp_graph import create_csv
from lpmp_graph import create_graph
from lpmp_graph import extract_usage_data
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

    def tearDown(self):
        """Clean up temporary directory"""
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

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU', verbose=False)

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

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU', verbose=False)

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

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform Mem', verbose=False)

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

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform Cpu', verbose=False)

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

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU', verbose=False)

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

        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU', verbose=False)

        # Should only extract the one valid line
        self.assertEqual(len(usage_data), 1)
        self.assertEqual(usage_data[0], ('2024-03-22T10:30:45.123', 75.5))

    def test_extract_usage_data_verbose_mode(self):
        """Test extract_usage_data with verbose mode enabled"""
        content_lines = [
            "00:00:01.000\tcontroller-0\tPlatform CPU Usage\ttest.log\t"
            "2024-03-22T10:30:45.123 platform cpu usage debounce (85.5)",
        ]
        self._create_test_timeline_file(content_lines)

        # Capture stdout to verify verbose output
        with patch('builtins.print') as mock_print:
            usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU', verbose=True)

            # Verify data extraction worked
            self.assertEqual(len(usage_data), 1)
            self.assertEqual(usage_data[0], ('2024-03-22T10:30:45.123', 85.5))

            # Verify verbose output was generated
            self.assertTrue(mock_print.called)
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            debug_messages = [msg for msg in print_calls if msg.startswith('Debug:')]
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
        cpu_data = extract_usage_data(self.test_timeline_file, 'Platform CPU', verbose=False)
        self.assertEqual(len(cpu_data), 2)
        self.assertEqual(cpu_data[0], ('2024-03-22T10:30:45.123', 85.5))
        self.assertEqual(cpu_data[1], ('2024-03-22T10:30:46.456', 78.3))

        # Test Memory extraction
        mem_data = extract_usage_data(self.test_timeline_file, 'Platform Mem', verbose=False)
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

        create_csv(usage_data, self.test_csv_file, 'Platform CPU', verbose=False)

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

        create_csv(usage_data, self.test_csv_file, 'Platform Memory', verbose=False)

        with open(self.test_csv_file, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)

        # Spaces should be replaced with underscores
        self.assertEqual(header, ['Timestamp', 'Platform_Memory_Usage'])

    def test_create_csv_empty_data(self):
        """Test create_csv with empty usage data"""
        usage_data = []

        create_csv(usage_data, self.test_csv_file, 'Platform CPU', verbose=False)

        # Verify file was created with just header
        self.assertTrue(os.path.exists(self.test_csv_file))

        with open(self.test_csv_file, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 1)  # Only header
        self.assertEqual(rows[0], ['Timestamp', 'Platform_CPU_Usage'])

    def test_create_csv_verbose_mode(self):
        """Test create_csv with verbose mode enabled"""
        usage_data = [('2024-03-22T10:30:45.123', 85.5)]

        with patch('builtins.print') as mock_print:
            create_csv(usage_data, self.test_csv_file, 'Platform CPU', verbose=True)

            # Verify verbose output was generated
            self.assertTrue(mock_print.called)
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            debug_messages = [msg for msg in print_calls if msg.startswith('Debug:')]
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
        create_csv(usage_data, self.test_csv_file, 'Platform CPU', verbose=False)

        # Test graph creation
        create_graph(self.test_csv_file, self.test_png_file, 'Platform CPU', (0, 100), verbose=False)

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
        """Test create_graph with verbose mode enabled"""
        # Setup mock DataFrame
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=2)
        mock_df.columns = ['Timestamp', 'Platform_CPU_Usage']
        mock_pd.read_csv.return_value = mock_df
        mock_pd.to_datetime.return_value = mock_df['Timestamp']

        # Create test CSV file
        usage_data = [('2024-03-22T10:30:45.123', 85.5)]
        create_csv(usage_data, self.test_csv_file, 'Platform CPU', verbose=False)

        with patch('builtins.print') as mock_print:
            create_graph(self.test_csv_file, self.test_png_file,  # noqa: E501
                         'Platform CPU', (0, 100), verbose=True)

            # Verify verbose output was generated
            self.assertTrue(mock_print.called)
            print_calls = [call[0][0] for call in mock_print.call_args_list]
            debug_messages = [msg for msg in print_calls if msg.startswith('Debug:')]
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
        create_csv(usage_data, self.test_csv_file, 'Platform Memory', verbose=False)

        # Test with custom range
        create_graph(self.test_csv_file, self.test_png_file, 'Platform Memory',  # noqa: E501
                     (0, 80), verbose=False)

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
        usage_data = extract_usage_data(self.test_timeline_file, 'Platform CPU', verbose=False)
        self.assertEqual(len(usage_data), 3)

        # Step 2: Create CSV
        create_csv(usage_data, self.test_csv_file, 'Platform CPU', verbose=False)
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
                         (0, 100), verbose=False)

            # Verify graph creation was attempted
            mock_plt.savefig.assert_called_once_with(self.test_png_file, dpi=300,  # noqa: E501
                                                     bbox_inches='tight')

    def test_file_error_handling(self):
        """Test error handling for file operations"""
        # Test extract_usage_data with non-existent file
        with self.assertRaises(FileNotFoundError):
            extract_usage_data('/non/existent/file.log', 'Platform CPU',  # noqa: E501
                               verbose=False)

        # Test create_csv with invalid output path
        usage_data = [('2024-03-22T10:30:45.123', 85.5)]
        invalid_path = '/invalid/path/output.csv'

        with self.assertRaises(FileNotFoundError):
            create_csv(usage_data, invalid_path, 'Platform CPU',  # noqa: E501
                       verbose=False)


if __name__ == '__main__':
    unittest.main()
