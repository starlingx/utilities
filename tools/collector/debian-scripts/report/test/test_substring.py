#!/usr/bin/env python3
# #######################################################################
#
# Copyright (c) 2022 -2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# #######################################################################
#
# This file contains the functions for the system info plugin algorithm.
#
# The system info plugin algorithm gathers top level system information,
# such at the build type, sw version, and more.
#
# #######################################################################
"""Tests for the substring algorithm (plugin_algs/substring.py)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugin_algs.substring import _continue  # noqa: E402
from plugin_algs.substring import substring  # noqa: E402


class TestSubstringSearch(unittest.TestCase):
    """Test the main substring search function."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_log(self, lines):
        with open(self.log_file, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def test_finds_matching_lines(self):
        """Should find lines containing the substring."""
        self._write_log([
            "2025-01-01T10:00:00.000 normal message",
            "2025-01-01T10:00:01.000 Error : something failed",
            "2025-01-01T10:00:02.000 another normal message",
            "2025-01-01T10:00:03.000 Error : another failure",
        ])
        result = substring(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00",
            ["Error :"], [self.log_file]
        )
        self.assertEqual(len(result), 2)
        self.assertIn("Error : something failed", result[0])
        self.assertIn("Error : another failure", result[1])

    def test_respects_date_range(self):
        """Should only return lines within the date range."""
        self._write_log([
            "2025-01-01T08:00:00.000 before range Error : early",
            "2025-01-01T12:00:00.000 in range Error : match",
            "2025-01-01T20:00:00.000 after range Error : late",
        ])
        result = substring(
            "2025-01-01T10:00:00", "2025-01-01T15:00:00",
            ["Error :"], [self.log_file]
        )
        self.assertEqual(len(result), 1)
        self.assertIn("in range", result[0])

    def test_multiple_substrings(self):
        """Should find lines matching any of the substrings."""
        self._write_log([
            "2025-01-01T10:00:00.000 Heartbeat Loss detected",
            "2025-01-01T10:00:01.000 normal message",
            "2025-01-01T10:00:02.000 MNFA ENTER triggered",
        ])
        result = substring(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00",
            ["Heartbeat Loss", "MNFA ENTER"], [self.log_file]
        )
        self.assertEqual(len(result), 2)

    def test_exclude_list(self):
        """Should exclude lines containing exclude patterns."""
        self._write_log([
            "2025-01-01T10:00:00.000 Error : real problem",
            "2025-01-01T10:00:01.000 Error : Failed to set alarm",
            "2025-01-01T10:00:02.000 Error : another real problem",
        ])
        result = substring(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00",
            ["Error :"], [self.log_file],
            exclude_list=["Failed to set alarm"]
        )
        self.assertEqual(len(result), 2)
        for line in result:
            self.assertNotIn("Failed to set alarm", line)

    def test_missing_file(self):
        """Should handle missing files gracefully."""
        result = substring(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00",
            ["Error :"], ["/nonexistent/path/file.log"]
        )
        self.assertEqual(len(result), 1)
        self.assertIn("File not found", result[0])

    def test_empty_file(self):
        """Should handle empty files."""
        self._write_log([])
        result = substring(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00",
            ["Error :"], [self.log_file]
        )
        self.assertEqual(len(result), 0)

    def test_results_sorted(self):
        """Results should be sorted chronologically."""
        self._write_log([
            "2025-01-01T10:00:03.000 Error : third",
            "2025-01-01T10:00:01.000 Error : first",
            "2025-01-01T10:00:02.000 Error : second",
        ])
        result = substring(
            "2025-01-01T00:00:00", "2025-01-02T00:00:00",
            ["Error :"], [self.log_file]
        )
        self.assertEqual(len(result), 3)
        self.assertIn("first", result[0])
        self.assertIn("second", result[1])
        self.assertIn("third", result[2])


class TestContinueFunction(unittest.TestCase):
    """Test the _continue() date range check."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_file(self, filename, first_line):
        path = os.path.join(self.temp_dir, filename)
        with open(path, 'w') as f:
            f.write(first_line + '\n')
        return path

    def test_file_before_start(self):
        """File starting before start date → CONTINUE_CURRENT (0)."""
        path = self._write_file("test.log",
                                "2024-01-01T10:00:00.000 old message")
        result = _continue("2025-01-01T00:00:00", "2025-12-31T00:00:00", path)
        self.assertEqual(result, 0)

    def test_file_in_range(self):
        """File starting within range → CONTINUE_CURRENT_OLD (1)."""
        path = self._write_file("test.log",
                                "2025-06-01T10:00:00.000 mid message")
        result = _continue("2025-01-01T00:00:00", "2025-12-31T00:00:00", path)
        self.assertEqual(result, 1)

    def test_file_after_end(self):
        """File starting after end date → CONTINUE_OLD (2)."""
        path = self._write_file("test.log",
                                "2026-06-01T10:00:00.000 future message")
        result = _continue("2025-01-01T00:00:00", "2025-12-31T00:00:00", path)
        self.assertEqual(result, 2)

    def test_unparseable_timestamp(self):
        """File with no valid timestamp → CONTINUE_CURRENT_OLD (1)."""
        path = self._write_file("test.log", "no timestamp here")
        result = _continue("2025-01-01T00:00:00", "2025-12-31T00:00:00", path)
        self.assertEqual(result, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
