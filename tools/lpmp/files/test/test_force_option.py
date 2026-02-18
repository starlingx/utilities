#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for LPMP --force / -f option

--force treats required block failures as warnings for all blocks after
the first. The first block must still succeed — it establishes the anchor.
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
from lpmp_utils import expand_wildcards_in_blocks   # noqa: E402
from lpmp_utils import load_model                   # noqa: E402
import lpmptool                                     # noqa: E402


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestForceOption(unittest.TestCase):
    """Test --force / -f command line option"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")
        self.model_file = os.path.join(self.temp_dir, "model.yaml")

        with open(self.log_file, 'w') as f:
            f.write("2024-01-06T10:00:00.000 first pattern here\n")
            f.write("2024-01-06T10:00:20.000 second pattern here\n")
            f.write("2024-01-06T10:00:40.000 third pattern here\n")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _make_model(self, blocks, settings=None):
        data = {'blocks': blocks}
        if settings:
            data['settings'] = settings
        with open(self.model_file, 'w') as f:
            yaml.dump(data, f)

    def _mock_args(self, force=False):
        class MockArgs:
            def __init__(self, temp_dir, model_file, force_val):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.block_time_tolerance = 1.0
                self.model_file = model_file
                self.all_optional_warnings = []
                self.force = force_val
        return MockArgs(self.temp_dir, self.model_file, force)

    def _run(self, blocks, force=False, settings=None):
        self._make_model(blocks, settings)
        args = self._mock_args(force=force)
        blks, _, _ = load_model(self.model_file)
        expand_wildcards_in_blocks(blks, self.temp_dir)
        return process_blocks_auto_detect(
            args, blks, datetime(2024, 1, 6, 9, 0, 0), 45,
            {'hostname': 'controller-0'}
        )

    # -----------------------------------------------------------------
    # CLI parsing
    # -----------------------------------------------------------------
    def test_force_flag_short(self):
        """Test -f is parsed"""
        captured = {}

        def cap(args, *a, **kw):
            captured['force'] = args.force
            return (False, None, None, 0, [], [])

        self._make_model([
            {'label': 'T', 'file': 'test.log', 'patterns': ['first pattern']}
        ])
        with patch('sys.argv', ['X', '-l', self.temp_dir, '-m', self.model_file, '-f']):
            with patch('lpmptool.process_blocks_auto_detect', side_effect=cap):
                with patch('builtins.print'):
                    try:
                        lpmptool.main()
                    except SystemExit:
                        pass
        self.assertTrue(captured.get('force'))

    def test_force_flag_long(self):
        """Test --force is parsed"""
        captured = {}

        def cap(args, *a, **kw):
            captured['force'] = args.force
            return (False, None, None, 0, [], [])

        self._make_model([
            {'label': 'T', 'file': 'test.log', 'patterns': ['first pattern']}
        ])
        with patch('sys.argv', ['X', '-l', self.temp_dir, '-m', self.model_file, '--force']):
            with patch('lpmptool.process_blocks_auto_detect', side_effect=cap):
                with patch('builtins.print'):
                    try:
                        lpmptool.main()
                    except SystemExit:
                        pass
        self.assertTrue(captured.get('force'))

    def test_force_default_false(self):
        """Test --force defaults to False"""
        captured = {}

        def cap(args, *a, **kw):
            captured['force'] = args.force
            return (False, None, None, 0, [], [])

        self._make_model([
            {'label': 'T', 'file': 'test.log', 'patterns': ['first pattern']}
        ])
        with patch('sys.argv', ['X', '-l', self.temp_dir, '-m', self.model_file]):
            with patch('lpmptool.process_blocks_auto_detect', side_effect=cap):
                with patch('builtins.print'):
                    try:
                        lpmptool.main()
                    except SystemExit:
                        pass
        self.assertFalse(captured.get('force', True))

    # -----------------------------------------------------------------
    # First block must always succeed (force does not apply)
    # -----------------------------------------------------------------
    def test_first_block_fails_even_with_force(self):
        """--force does not save a missing first block"""
        success, _, _, found, _, _ = self._run([
            {'label': 'Missing', 'file': 'test.log', 'patterns': ['nonexistent']},
            {'label': 'Second', 'file': 'test.log', 'patterns': ['second pattern']},
        ], force=True)
        self.assertFalse(success)
        self.assertEqual(found, 0)

    # -----------------------------------------------------------------
    # Force applies to non-first blocks
    # -----------------------------------------------------------------
    def test_second_block_forced(self):
        """--force turns a missing second block into a warning"""
        success, _, _, found, warnings, _ = self._run([
            {'label': 'Found', 'file': 'test.log', 'patterns': ['first pattern']},
            {'label': 'Missing', 'file': 'test.log', 'patterns': ['nonexistent']},
        ], force=True)
        self.assertTrue(success)
        self.assertEqual(found, 1)
        self.assertEqual(len(warnings), 1)
        self.assertTrue(any('Missing' in w for w in warnings))

    def test_middle_block_forced_rest_continues(self):
        """--force skips a missing middle block and continues to later blocks"""
        success, _, _, found, warnings, _ = self._run([
            {'label': 'First', 'file': 'test.log', 'patterns': ['first pattern']},
            {'label': 'Missing', 'file': 'test.log', 'patterns': ['nonexistent']},
            {'label': 'Third', 'file': 'test.log', 'patterns': ['third pattern']},
        ], force=True)
        self.assertTrue(success)
        self.assertEqual(found, 2)
        self.assertEqual(len(warnings), 1)

    def test_multiple_failures_forced(self):
        """--force handles multiple missing non-first blocks"""
        success, _, _, found, warnings, _ = self._run([
            {'label': 'First', 'file': 'test.log', 'patterns': ['first pattern']},
            {'label': 'Miss1', 'file': 'test.log', 'patterns': ['nope1']},
            {'label': 'Miss2', 'file': 'test.log', 'patterns': ['nope2']},
            {'label': 'Last', 'file': 'test.log', 'patterns': ['third pattern']},
        ], force=True)
        self.assertTrue(success)
        self.assertEqual(found, 2)
        self.assertEqual(len(warnings), 2)

    # -----------------------------------------------------------------
    # Without --force, non-first failures still error
    # -----------------------------------------------------------------
    def test_second_block_fails_without_force(self):
        """Without --force, a missing second block is a real error"""
        success, _, _, found, _, _ = self._run([
            {'label': 'Found', 'file': 'test.log', 'patterns': ['first pattern']},
            {'label': 'Missing', 'file': 'test.log', 'patterns': ['nonexistent']},
        ], force=False)
        self.assertFalse(success)
        self.assertEqual(found, 1)

    # -----------------------------------------------------------------
    # Force does not change optional block behavior
    # -----------------------------------------------------------------
    def test_optional_block_unaffected_by_force(self):
        """Optional blocks behave the same with or without --force"""
        success, _, _, found, warnings, _ = self._run([
            {'label': 'Found', 'file': 'test.log', 'patterns': ['first pattern']},
            {'label': 'Opt', 'file': 'test.log',
             'patterns': ['nonexistent'], 'optional': True},
        ], force=True)
        self.assertTrue(success)
        self.assertEqual(found, 1)
        self.assertEqual(len(warnings), 1)

    # -----------------------------------------------------------------
    # Force with pair blocks
    # -----------------------------------------------------------------
    def test_force_pair_block_after_first(self):
        """--force turns a missing pair block (after first) into a warning"""
        success, _, _, found, warnings, _ = self._run([
            {'label': 'Anchor', 'file': 'test.log', 'patterns': ['first pattern']},
            {'label': 'MissPair', 'file': 'test.log',
             'start': 'no start', 'stop': 'no stop'},
            {'label': 'GoodPair', 'file': 'test.log',
             'start': 'second pattern', 'stop': 'third pattern'},
        ], force=True)
        self.assertTrue(success)
        self.assertEqual(found, 2)
        self.assertTrue(any('MissPair' in w for w in warnings))

    # -----------------------------------------------------------------
    # Backward compat: no force attribute on args
    # -----------------------------------------------------------------
    def test_getattr_fallback(self):
        """Engine works when args has no force attribute"""
        self._make_model([
            {'label': 'Found', 'file': 'test.log', 'patterns': ['first pattern']},
            {'label': 'Missing', 'file': 'test.log', 'patterns': ['nonexistent']},
        ])

        class MinimalArgs:
            def __init__(self, td, mf):
                self.logs_dir = td
                self.verbose = 0
                self.max_log_length = 180
                self.block_time_tolerance = 1.0
                self.model_file = mf
                self.all_optional_warnings = []

        args = MinimalArgs(self.temp_dir, self.model_file)
        blks, _, _ = load_model(self.model_file)
        expand_wildcards_in_blocks(blks, self.temp_dir)
        success, _, _, _, _, _ = process_blocks_auto_detect(
            args, blks, datetime(2024, 1, 6, 9, 0, 0), 45,
            {'hostname': 'controller-0'}
        )
        self.assertFalse(success)


if __name__ == '__main__':
    unittest.main()
