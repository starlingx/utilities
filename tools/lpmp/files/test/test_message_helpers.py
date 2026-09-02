#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for block not-found message helpers and the pair-block
--max-log-length bypass.

Covers the small pure helpers that shape Warn/Error output for failed
blocks:
- _format_search_start: prepends the timestamp a failed block searched
  from (the sequential cursor, or the run start date, or 'beginning of
  log') so a missed-but-present pattern is easy to spot.
- _pair_not_found_detail: names ONLY the pattern that actually failed
  (start OR stop), instead of implying both are missing.
- _select_failed_pattern_file: reports the correct file for the failed
  pattern (stop's file when stop failed) and prefers the original model
  glob ('file_spec', e.g. 'daemon.log*') over an expanded concrete name.

Also covers the output rule that pair-block result lines (tool-generated
"Start -> Stop: ... duration" text) are NOT truncated by
--max-log-length, while pattern/timeline raw log lines still are.
"""

from contextlib import redirect_stdout
from datetime import datetime
import io
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import _format_search_start         # noqa: E402
from lpmp_engine import _pair_not_found_detail       # noqa: E402
from lpmp_engine import _select_failed_pattern_file  # noqa: E402
from lpmp_engine import reorder_and_output_results   # noqa: E402


class TestFormatSearchStart(unittest.TestCase):
    """_format_search_start(prev_timestamp, start_date)"""

    def test_prev_timestamp_wins(self):
        """The running cursor is used when present, in ms precision."""
        prev = datetime(2024, 1, 6, 10, 15, 30, 123456)
        start = datetime(2024, 1, 6, 9, 0, 0)
        self.assertEqual(
            _format_search_start(prev, start),
            "2024-01-06T10:15:30.123")

    def test_falls_back_to_start_date(self):
        """With no cursor yet, the run's start date is used."""
        start = datetime(2024, 1, 6, 9, 0, 0, 500000)
        self.assertEqual(
            _format_search_start(None, start),
            "2024-01-06T09:00:00.500")

    def test_no_lower_bound_returns_beginning_of_log(self):
        """No cursor and no start date -> 'beginning of log'."""
        self.assertEqual(
            _format_search_start(None, None), "beginning of log")


class TestPairNotFoundDetail(unittest.TestCase):
    """_pair_not_found_detail(block, pair_failure_info)"""

    def setUp(self):
        self.block = {
            'label': 'CSI Ready',
            'start': 'Started .*Kubelet',
            'stop': 'k8s-pod-recovery',
        }

    def test_start_failure_names_only_start(self):
        detail = _pair_not_found_detail(self.block, {'reason': 'start'})
        self.assertEqual(
            detail, "start pattern start='Started .*Kubelet' not found")
        self.assertNotIn('stop', detail)

    def test_stop_failure_names_only_stop(self):
        detail = _pair_not_found_detail(self.block, {'reason': 'stop'})
        self.assertEqual(
            detail, "stop pattern stop='k8s-pod-recovery' not found")
        # The word 'start' must not appear (no "start matched but..." preamble).
        self.assertNotIn('start', detail)

    def test_unknown_reason_falls_back_to_both(self):
        detail = _pair_not_found_detail(self.block, {})
        self.assertIn('start=', detail)
        self.assertIn('stop=', detail)


class TestSelectFailedPatternFile(unittest.TestCase):
    """_select_failed_pattern_file(block, block_type, pair_failure_info)"""

    def test_pattern_block_uses_file_spec_glob(self):
        """Original glob is preferred over the expanded concrete filename."""
        block = {
            'label': 'CSI Ready',
            'file': ['daemon.log'],          # expanded
            'file_spec': ['daemon.log*'],    # original glob
            'patterns': ['x'],
        }
        self.assertEqual(
            _select_failed_pattern_file(block, 'pattern', {}),
            'daemon.log*')

    def test_pattern_block_without_file_spec_uses_file(self):
        block = {'label': 'B', 'file': ['daemon.log'], 'patterns': ['x']}
        self.assertEqual(
            _select_failed_pattern_file(block, 'pattern', {}),
            'daemon.log')

    def test_pair_stop_failure_reports_stop_file(self):
        """When stop failed and a second file is listed, report file[1]."""
        block = {
            'label': 'PAIR',
            'file': ['start.log', 'stop.log'],
            'file_spec': ['start.log*', 'stop.log*'],
            'start': 's', 'stop': 'e',
        }
        self.assertEqual(
            _select_failed_pattern_file(block, 'pair', {'reason': 'stop'}),
            'stop.log*')

    def test_pair_start_failure_reports_first_file(self):
        block = {
            'label': 'PAIR',
            'file': ['start.log', 'stop.log'],
            'file_spec': ['start.log*', 'stop.log*'],
            'start': 's', 'stop': 'e',
        }
        self.assertEqual(
            _select_failed_pattern_file(block, 'pair', {'reason': 'start'}),
            'start.log*')

    def test_pair_stop_failure_single_file_falls_back(self):
        """Only one file listed -> report it even for a stop failure."""
        block = {
            'label': 'PAIR',
            'file': ['only.log'],
            'file_spec': ['only.log*'],
            'start': 's', 'stop': 'e',
        }
        self.assertEqual(
            _select_failed_pattern_file(block, 'pair', {'reason': 'stop'}),
            'only.log*')

    def test_string_file_spec_returned_directly(self):
        block = {
            'label': 'B', 'file': 'daemon.log',
            'file_spec': 'daemon.log*', 'patterns': ['x'],
        }
        self.assertEqual(
            _select_failed_pattern_file(block, 'pattern', {}),
            'daemon.log*')


class TestPairMaxLogLengthBypass(unittest.TestCase):
    """Pair result lines are not truncated by --max-log-length."""

    class _Args:
        def __init__(self, max_log_length):
            self.max_log_length = max_log_length
            self.verbose = 0

    def _capture(self, temp_results, max_log_length):
        args = self._Args(max_log_length)
        buf = io.StringIO()
        with redirect_stdout(buf):
            reorder_and_output_results(temp_results, args,
                                       structured_results=[])
        return buf.getvalue()

    def test_pair_data_not_truncated(self):
        """A long pair duration line survives a tiny max_log_length."""
        start_ts = datetime(2024, 1, 6, 10, 0, 0)
        stop_ts = datetime(2024, 1, 6, 10, 9, 58, 485000)
        long_data = (
            "2024-01-06 10:00:00.000: Start -> Stop: "
            "2024-01-06 10:09:58.485: 598.5s")
        pair_block = {'label': 'test outage', 'file': ['a.log', 'b.log'],
                      'start': 's', 'stop': 'e'}
        temp_results = [{
            'timestamp': start_ts,
            'block': pair_block,
            'data': long_data,
            'actual_filename': 'a.log',
            'seq': 0,
            'start_ts': start_ts,
            'stop_ts': stop_ts,
        }]
        out = self._capture(temp_results, max_log_length=10)
        # The full duration/summary text is present despite max_log_length=10.
        self.assertIn('598.5s', out)
        self.assertIn('Start -> Stop', out)

    def test_pattern_data_still_truncated(self):
        """A raw pattern log line is still cut at max_log_length."""
        ts = datetime(2024, 1, 6, 10, 0, 0)
        long_line = 'X' * 200
        pattern_block = {'label': 'pat', 'file': ['a.log'],
                         'patterns': ['X']}
        temp_results = [{
            'timestamp': ts,
            'block': pattern_block,
            'data': long_line,
            'actual_filename': 'a.log',
            'seq': 0,
        }]
        out = self._capture(temp_results, max_log_length=10)
        # The 200-char line must not appear in full.
        self.assertNotIn('X' * 200, out)
        self.assertIn('X' * 10, out)


if __name__ == '__main__':
    unittest.main()
