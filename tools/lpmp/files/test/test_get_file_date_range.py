#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""
Test coverage for get_file_date_range function.

Tests the file date range extraction functionality including:
- Regular files with timestamps
- Gzipped files with timestamps
- Caching behavior
- Edge cases (empty files, no timestamps, single line)
- Error handling (missing files, permission errors)
"""

from datetime import datetime
import gzip
import os
import sys
import tempfile
import unittest
from unittest.mock import mock_open
from unittest.mock import patch

from lpmp_utils import _file_date_range_cache
from lpmp_utils import get_file_date_range

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGetFileDateRange(unittest.TestCase):
    """Test get_file_date_range function."""

    def setUp(self):
        """Set up test fixtures."""
        # Clear the cache before each test
        _file_date_range_cache.clear()

        # Create temporary directory for test files
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary files
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

        # Clear cache after each test
        _file_date_range_cache.clear()

    def test_regular_file_with_timestamps(self):
        """Test regular file with valid timestamps."""
        # Create test file with timestamps
        test_file = os.path.join(self.temp_dir, 'test.log')
        with open(test_file, 'w') as f:
            f.write('2024-01-06T10:00:00.123 First log entry\n')
            f.write('2024-01-06T10:05:00.456 Middle log entry\n')
            f.write('2024-01-06T10:10:00.789 Last log entry\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 10, 0, 789000))

    def test_sysinv_format_timestamps(self):
        """Test file with sysinv format timestamps."""
        test_file = os.path.join(self.temp_dir, 'sysinv.log')
        with open(test_file, 'w') as f:
            f.write('sysinv 2024-01-06 10:00:00.123 First sysinv entry\n')
            f.write('sysinv 2024-01-06 10:05:00.456 Middle sysinv entry\n')
            f.write('sysinv 2024-01-06 10:10:00.789 Last sysinv entry\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 10, 0, 789000))

    def test_gzipped_file_with_timestamps(self):
        """Test gzipped file with valid timestamps."""
        test_file = os.path.join(self.temp_dir, 'test.log.gz')
        with gzip.open(test_file, 'wt', encoding='utf-8') as f:
            f.write('2024-01-06T10:00:00.123 First compressed entry\n')
            f.write('2024-01-06T10:05:00.456 Middle compressed entry\n')
            f.write('2024-01-06T10:10:00.789 Last compressed entry\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 10, 0, 789000))

    def test_mixed_timestamp_formats(self):
        """Test file with mixed ISO and sysinv timestamp formats."""
        test_file = os.path.join(self.temp_dir, 'mixed.log')
        with open(test_file, 'w') as f:
            f.write('2024-01-06T10:00:00.123 ISO format first\n')
            f.write('sysinv 2024-01-06 10:05:00.456 sysinv format middle\n')
            f.write('2024-01-06T10:10:00.789 ISO format last\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 10, 0, 789000))

    def test_file_with_no_timestamps(self):
        """Test file with no valid timestamps."""
        test_file = os.path.join(self.temp_dir, 'no_timestamps.log')
        with open(test_file, 'w') as f:
            f.write('This is a log line without timestamp\n')
            f.write('Another line with no timestamp\n')
            f.write('Final line also without timestamp\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNone(first_ts)
        self.assertIsNone(last_ts)

    def test_empty_file(self):
        """Test empty file."""
        test_file = os.path.join(self.temp_dir, 'empty.log')
        with open(test_file, 'w') as f:
            pass  # Create empty file

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNone(first_ts)
        self.assertIsNone(last_ts)

    def test_single_line_file(self):
        """Test file with single line containing timestamp."""
        test_file = os.path.join(self.temp_dir, 'single.log')
        with open(test_file, 'w') as f:
            f.write('2024-01-06T10:00:00.123 Only one line\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))

    def test_timestamps_only_at_beginning(self):
        """Test file where only first few lines have timestamps."""
        test_file = os.path.join(self.temp_dir, 'partial_timestamps.log')
        with open(test_file, 'w') as f:
            f.write('2024-01-06T10:00:00.123 First timestamped line\n')
            f.write('2024-01-06T10:01:00.456 Second timestamped line\n')
            f.write('Line without timestamp\n')
            f.write('Another line without timestamp\n')
            f.write('Final line without timestamp\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 1, 0, 456000))

    def test_timestamps_only_at_end(self):
        """Test file where only last few lines have timestamps."""
        test_file = os.path.join(self.temp_dir, 'end_timestamps.log')
        with open(test_file, 'w') as f:
            f.write('Line without timestamp\n')
            f.write('Another line without timestamp\n')
            f.write('2024-01-06T10:08:00.123 First timestamped line\n')
            f.write('2024-01-06T10:09:00.456 Last timestamped line\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 8, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 9, 0, 456000))

    def test_large_file_efficiency(self):
        """Test that function reads only first 10 and last 50 lines efficiently."""
        test_file = os.path.join(self.temp_dir, 'large.log')
        with open(test_file, 'w') as f:
            # Write first timestamped line
            f.write('2024-01-06T10:00:00.123 First line\n')

            # Write many lines without timestamps (should be skipped)
            for i in range(100):
                f.write(f'Line {i + 2} without timestamp\n')

            # Write last timestamped line
            f.write('2024-01-06T10:30:00.789 Last line\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 30, 0, 789000))

    def test_caching_behavior(self):
        """Test that results are cached and reused."""
        test_file = os.path.join(self.temp_dir, 'cached.log')
        with open(test_file, 'w') as f:
            f.write('2024-01-06T10:00:00.123 Test line\n')

        # First call should read file and cache result
        first_ts1, last_ts1 = get_file_date_range(test_file)

        # Verify result is in cache
        self.assertIn(test_file, _file_date_range_cache)

        # Mock open to verify second call doesn't read file
        with patch('builtins.open', mock_open()) as mock_file:
            first_ts2, last_ts2 = get_file_date_range(test_file)

            # Verify file was not opened (cache hit)
            mock_file.assert_not_called()

            # Verify same results returned
            self.assertEqual(first_ts1, first_ts2)
            self.assertEqual(last_ts1, last_ts2)

    def test_cache_hit_path(self):
        """Test explicit cache hit behavior."""
        test_file = os.path.join(self.temp_dir, 'cache_test.log')
        expected_first = datetime(2024, 1, 6, 10, 0, 0, 123000)
        expected_last = datetime(2024, 1, 6, 10, 30, 0, 789000)

        # Manually populate cache
        _file_date_range_cache[test_file] = (expected_first, expected_last)

        # Call function - should return cached values without reading file
        first_ts, last_ts = get_file_date_range(test_file)

        self.assertEqual(first_ts, expected_first)
        self.assertEqual(last_ts, expected_last)

    def test_nonexistent_file(self):
        """Test behavior with non-existent file."""
        nonexistent_file = os.path.join(self.temp_dir, 'does_not_exist.log')

        first_ts, last_ts = get_file_date_range(nonexistent_file)

        self.assertIsNone(first_ts)
        self.assertIsNone(last_ts)

        # Verify result is cached (even for failures)
        self.assertIn(nonexistent_file, _file_date_range_cache)
        self.assertEqual(_file_date_range_cache[nonexistent_file], (None, None))

    def test_permission_denied_file(self):
        """Test behavior with permission denied file."""
        test_file = os.path.join(self.temp_dir, 'permission_denied.log')

        # Create file first
        with open(test_file, 'w') as f:
            f.write('2024-01-06T10:00:00.123 Test line\n')

        # Mock open to raise PermissionError
        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            first_ts, last_ts = get_file_date_range(test_file)

            self.assertIsNone(first_ts)
            self.assertIsNone(last_ts)

            # Verify result is cached
            self.assertIn(test_file, _file_date_range_cache)
            self.assertEqual(_file_date_range_cache[test_file], (None, None))

    def test_gzipped_file_error_handling(self):
        """Test error handling for corrupted gzipped files."""
        test_file = os.path.join(self.temp_dir, 'corrupted.log.gz')

        # Create invalid gzip file
        with open(test_file, 'wb') as f:
            f.write(b'This is not a valid gzip file')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNone(first_ts)
        self.assertIsNone(last_ts)

        # Verify result is cached
        self.assertIn(test_file, _file_date_range_cache)
        self.assertEqual(_file_date_range_cache[test_file], (None, None))

    def test_gzipped_file_seek_behavior(self):
        """Test that gzipped files use sequential read (no seeking)."""
        test_file = os.path.join(self.temp_dir, 'sequential.log.gz')
        with gzip.open(test_file, 'wt', encoding='utf-8') as f:
            f.write('2024-01-06T10:00:00.123 First line\n')
            f.write('2024-01-06T10:05:00.456 Middle line\n')
            f.write('2024-01-06T10:10:00.789 Last line\n')

        # Mock gzip.open to track calls
        with patch('gzip.open', wraps=gzip.open) as mock_gzip:
            first_ts, last_ts = get_file_date_range(test_file)

            # Verify gzip.open was called
            mock_gzip.assert_called_once()

            # Verify results are correct
            self.assertIsNotNone(first_ts)
            self.assertIsNotNone(last_ts)
            self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
            self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 10, 0, 789000))

    def test_regular_file_seek_behavior(self):
        """Test that regular files use seeking for efficiency."""
        test_file = os.path.join(self.temp_dir, 'seekable.log')
        with open(test_file, 'w') as f:
            f.write('2024-01-06T10:00:00.123 First line\n')
            # Add many lines to make seeking worthwhile
            for i in range(100):
                f.write(f'2024-01-06T10:{i:02d}:30.000 Middle line {i}\n')
            f.write('2024-01-06T10:59:59.789 Last line\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 59, 59, 789000))

    def test_malformed_timestamps(self):
        """Test file with malformed timestamps."""
        test_file = os.path.join(self.temp_dir, 'malformed.log')
        with open(test_file, 'w') as f:
            f.write('2024-01-06T10:00:00.123 Valid timestamp\n')
            f.write('2024-13-45T25:99:99.999 Invalid timestamp\n')
            f.write('sysinv 2024-01-06 10:05:00.456 Valid sysinv timestamp\n')
            f.write('sysinv 2024-99-99 99:99:99.999 Invalid sysinv timestamp\n')
            f.write('2024-01-06T10:10:00.789 Final valid timestamp\n')

        first_ts, last_ts = get_file_date_range(test_file)

        # Should find first and last valid timestamps, ignoring malformed ones
        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 10, 0, 789000))

    def test_unicode_content(self):
        """Test file with unicode content."""
        test_file = os.path.join(self.temp_dir, 'unicode.log')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('2024-01-06T10:00:00.123 Unicode content: 你好世界\n')
            f.write('2024-01-06T10:05:00.456 More unicode: café résumé\n')
            f.write('2024-01-06T10:10:00.789 Final unicode: 🚀🌟\n')

        first_ts, last_ts = get_file_date_range(test_file)

        self.assertIsNotNone(first_ts)
        self.assertIsNotNone(last_ts)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0, 123000))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 10, 0, 789000))


if __name__ == '__main__':
    unittest.main()
