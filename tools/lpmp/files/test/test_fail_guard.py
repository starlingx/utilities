#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for the fail-guard pattern-block modifier (fail: true).

A pattern block with 'fail: true' reverses polarity: matching the pattern
(within the block's max_time_delta window) fails the whole run; not matching
is a silent pass. Fail-guards are pattern-block only and mutually exclusive
with 'optional'/'present' (enforced by validation, covered in
test_validate_model.py).

These tests exercise the full loader + engine path:
- pattern found  -> process_blocks_auto_detect returns success=False
- pattern absent -> guard is a silent pass, run succeeds
- a fail-guard match does not emit a result row / advance the cursor
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
class TestFailGuard(unittest.TestCase):
    """Full-stack behavior tests for the fail: true pattern-block modifier."""

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
        data = {'description': 'Fail-guard test model.', 'blocks': blocks}
        with open(self.model_file, 'w') as f:
            yaml.dump(data, f)

    def _mock_args(self):
        class MockArgs:
            def __init__(self, temp_dir, model_file):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.block_time_tolerance = 1.0
                self.model_file = model_file
                self.force = False
        return MockArgs(self.temp_dir, self.model_file)

    def _run(self, blocks):
        self._make_model(blocks)
        args = self._mock_args()
        blks, _, _ = load_model(self.model_file)
        expand_wildcards_in_blocks(blks, self.temp_dir)
        with patch('builtins.print'):  # suppress the ❌ FAIL / table output
            return process_blocks_auto_detect(
                args, blks, datetime(2024, 1, 6, 9, 0, 0), 45,
                {'hostname': 'controller-0'}
            )

    # --- fail-guard triggers ---

    def test_fail_guard_triggers_when_pattern_found(self):
        """Run fails (success=False) when the fail pattern is present."""
        self._write_log([
            "2024-01-06T10:00:00.000 Unlock Action",
            "2024-01-06T10:00:05.000 Kernel panic - not syncing",
        ])
        blocks = [
            {'label': 'ANCHOR', 'file': 'test.log',
             'patterns': ['Unlock Action'], 'max_time_delta': 600},
            {'label': 'NO PANIC', 'file': 'test.log',
             'patterns': ['Kernel panic'], 'fail': True,
             'max_time_delta': 600},
        ]
        success, _start, _end, _found, _warn, _results = self._run(blocks)
        self.assertFalse(success)

    def test_fail_guard_passes_when_pattern_absent(self):
        """Run succeeds when the fail pattern is not present (silent pass)."""
        self._write_log([
            "2024-01-06T10:00:00.000 Unlock Action",
            "2024-01-06T10:00:30.000 all good",
        ])
        blocks = [
            {'label': 'ANCHOR', 'file': 'test.log',
             'patterns': ['Unlock Action'], 'max_time_delta': 600},
            {'label': 'NO PANIC', 'file': 'test.log',
             'patterns': ['Kernel panic'], 'fail': True,
             'max_time_delta': 600},
        ]
        success, _start, _end, patterns_found, _warn, _results = self._run(blocks)
        self.assertTrue(success)
        # The anchor matched (1 pattern); the not-triggered guard records nothing.
        self.assertEqual(patterns_found, 1)

    def test_fail_guard_absent_does_not_add_result_row(self):
        """A non-triggered fail-guard emits no structured result row."""
        self._write_log([
            "2024-01-06T10:00:00.000 Unlock Action",
        ])
        blocks = [
            {'label': 'ANCHOR', 'file': 'test.log',
             'patterns': ['Unlock Action'], 'max_time_delta': 600},
            {'label': 'NO PANIC', 'file': 'test.log',
             'patterns': ['Kernel panic'], 'fail': True,
             'max_time_delta': 600},
        ]
        _s, _st, _e, _f, _w, results = self._run(blocks)
        labels = [getattr(r, 'block_label', None) for r in results]
        self.assertNotIn('NO PANIC', labels)

    def test_fail_guard_first_block_unbounded_triggers(self):
        """A fail-guard as the first block scans unbounded and can trigger."""
        self._write_log([
            "2024-01-06T10:00:05.000 Kernel panic - not syncing",
        ])
        blocks = [
            {'label': 'NO PANIC', 'file': 'test.log',
             'patterns': ['Kernel panic'], 'fail': True},
        ]
        success, _start, _end, _found, _warn, _results = self._run(blocks)
        self.assertFalse(success)

    def test_fail_guard_or_pattern_triggers_on_any(self):
        """A stacked (OR-expanded) fail-guard triggers if any pattern matches."""
        self._write_log([
            "2024-01-06T10:00:00.000 Unlock Action",
            "2024-01-06T10:00:05.000 segfault at 0",
        ])
        blocks = [
            {'label': 'ANCHOR', 'file': 'test.log',
             'patterns': ['Unlock Action'], 'max_time_delta': 600},
            {'label': 'GUARD', 'file': 'test.log',
             'patterns': ['Kernel panic', 'segfault'], 'fail': True,
             'max_time_delta': 600},
        ]
        success, _start, _end, _found, _warn, _results = self._run(blocks)
        self.assertFalse(success)


if __name__ == '__main__':
    unittest.main()
