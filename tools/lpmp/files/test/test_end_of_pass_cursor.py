#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for end-of-pass cursor semantics (declaration-order).

process_blocks_auto_detect returns an end_time used as the search start
for the next analysis pass (loop). The cursor must reflect the LAST block
matched in DECLARED ORDER, not a running maximum across all blocks. This
is the kpi-unlock-skipped-iteration fix (Option 1): overwrite end_time
unconditionally for each matched block instead of keeping the max.

Why it matters: with a running max, a block that matched a later timestamp
(e.g. an earlier-declared pair with a long duration, or a pattern that
matched slightly forward) would hijack the cursor and push the next pass
start past legitimate events, silently skipping an iteration.

These tests set up blocks where a LATER-declared block matches an EARLIER
timestamp than an earlier-declared block, then assert the returned
end_time equals the last-declared block's match (declaration order), which
is strictly less than the running max the old code would have produced.
"""

from datetime import datetime
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

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import process_blocks_auto_detect  # noqa: E402
from lpmp_utils import expand_wildcards_in_blocks    # noqa: E402
from lpmp_utils import load_model                     # noqa: E402


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestEndOfPassCursor(unittest.TestCase):
    """Returned end_time follows declared order, not a running max."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")
        self.model_file = os.path.join(self.temp_dir, "model.yaml")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _write_log(self, lines):
        with open(self.log_file, 'w') as f:
            f.write("\n".join(lines) + "\n")

    def _make_model(self, blocks):
        data = {'description': 'Cursor test model.', 'blocks': blocks}
        with open(self.model_file, 'w') as f:
            yaml.dump(data, f)

    def _mock_args(self):
        class MockArgs:
            def __init__(self, temp_dir, model_file):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.block_time_tolerance = 5.0
                self.model_file = model_file
                self.force = False
        return MockArgs(self.temp_dir, self.model_file)

    def _run(self, blocks, start):
        self._make_model(blocks)
        args = self._mock_args()
        blks, _, _ = load_model(self.model_file)
        expand_wildcards_in_blocks(blks, self.temp_dir)
        with patch('builtins.print'):  # suppress the result table output
            return process_blocks_auto_detect(
                args, blks, start, 45, {'hostname': 'controller-0'}
            )

    def test_pattern_cursor_is_last_declared_not_max(self):
        """A later-declared pattern matching an earlier time sets the cursor.

        Block B (declared second) matches 10:00:08, which is before block A's
        10:00:10 match. The end-of-pass cursor must be B's 10:00:08 (last in
        declared order), not the running max 10:00:10.
        """
        self._write_log([
            "2024-01-06T10:00:10.000 EVENT A here",
            "2024-01-06T10:00:08.000 EVENT B here",
        ])
        blocks = [
            {'label': 'A', 'file': 'test.log', 'patterns': ['EVENT A']},
            {'label': 'B', 'file': 'test.log', 'patterns': ['EVENT B']},
        ]
        success, _start, end_time, _found, _warn, _results = self._run(
            blocks, datetime(2024, 1, 6, 9, 0, 0))
        self.assertTrue(success)
        self.assertEqual(end_time, datetime(2024, 1, 6, 10, 0, 8))
        # Guard against a regression to running-max behavior.
        self.assertNotEqual(end_time, datetime(2024, 1, 6, 10, 0, 10))

    def test_pair_cursor_is_last_declared_stop_not_max_stop(self):
        """A later-declared pair with an earlier stop sets the cursor.

        Pair A (declared first) runs 10:00:00 -> 10:00:09 (long). Pair B
        (declared second) runs 10:00:01 -> 10:00:05 (short, earlier stop).
        The cursor must be B's stop 10:00:05, not A's later stop 10:00:09.
        """
        self._write_log([
            "2024-01-06T10:00:00.000 A start",
            "2024-01-06T10:00:01.000 B start",
            "2024-01-06T10:00:05.000 B stop",
            "2024-01-06T10:00:09.000 A stop",
        ])
        blocks = [
            {'label': 'A', 'file': 'test.log',
             'start': 'A start', 'stop': 'A stop', 'max_time_delta': 600},
            {'label': 'B', 'file': 'test.log',
             'start': 'B start', 'stop': 'B stop', 'max_time_delta': 600},
        ]
        # Start just before the first event: a pair block's block-level
        # max_time_delta also bounds its start search from the run start.
        success, _start, end_time, _found, _warn, _results = self._run(
            blocks, datetime(2024, 1, 6, 9, 59, 55))
        self.assertTrue(success)
        self.assertEqual(end_time, datetime(2024, 1, 6, 10, 0, 5))
        # Old running-max code would have kept A's later stop.
        self.assertNotEqual(end_time, datetime(2024, 1, 6, 10, 0, 9))


if __name__ == '__main__':
    unittest.main()
