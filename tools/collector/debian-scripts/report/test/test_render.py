#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the unit tests for the render module.
#
#
########################################################################

"""Tests for the render module (render.py)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render  # noqa: E402


class TestRemoveTimestamp(unittest.TestCase):
    """Tests for remove_timestamp, which strips a leading timestamp from
    each line of a report summary section.
    """

    def test_strips_timestamp(self):
        line = '2024-09-21T00:47:53 controller-0 uncontrolled swact'
        self.assertEqual(render.remove_timestamp(line),
                         'controller-0 uncontrolled swact')

    def test_strips_timestamp_with_fractional_seconds(self):
        line = '2024-09-21T00:47:53.123456 controller-0 swact'
        self.assertEqual(render.remove_timestamp(line), 'controller-0 swact')

    def test_non_timestamp_line_is_unchanged(self):
        # Regression test. This raised ValueError on Python 3.7 and later,
        # and AttributeError on Python 3.6 where fromisoformat is absent.
        line = 'Events       : 3 /path/to/events'
        self.assertEqual(render.remove_timestamp(line), line)

    def test_bare_timestamp_with_no_message_is_unchanged(self):
        # No space means nothing follows the timestamp to keep. This
        # previously raised IndexError.
        line = '2024-09-21T00:47:53'
        self.assertEqual(render.remove_timestamp(line), line)

    def test_indented_line_is_unchanged(self):
        # Plugin summary lines are indented, so the first field is empty.
        line = '  355 ./report_analysis/plugins/swact_activity'
        self.assertEqual(render.remove_timestamp(line), line)

    def test_date_without_time_is_unchanged(self):
        # Narrower than datetime.fromisoformat(), which accepted a bare
        # date. Report logs always prefix a full timestamp.
        line = '2024-09-21 controller-0 swact'
        self.assertEqual(render.remove_timestamp(line), line)

    def test_timestamp_with_trailing_characters_is_unchanged(self):
        # The pattern is anchored, so a partial match is not a timestamp.
        line = '2024-09-21T00:47:53junk controller-0 swact'
        self.assertEqual(render.remove_timestamp(line), line)

    def test_empty_string(self):
        self.assertEqual(render.remove_timestamp(''), '')

    def test_mixed_content_over_several_lines(self):
        text = '\n'.join([
            '2024-09-21T00:47:53 controller-0 swact',
            'Events       : 3 /path/to/events',
            '',
            '  355 ./report_analysis/plugins/log',
        ])
        expected = '\n'.join([
            'controller-0 swact',
            'Events       : 3 /path/to/events',
            '',
            '  355 ./report_analysis/plugins/log',
        ])
        self.assertEqual(render.remove_timestamp(text), expected)


if __name__ == '__main__':
    unittest.main()
