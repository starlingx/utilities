#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for original-glob preservation (block['file_spec']).

expand_wildcards_in_blocks replaces block['file'] with the concrete files
a glob expands to (e.g. 'daemon.log*' -> ['daemon.log', 'daemon.log.1']).
Before doing so it stashes the ORIGINAL model spec in block['file_spec']
so not-found error/warning messages can show the model's glob rather than
a resolved filename. A re-entry guard ensures a second expansion pass
cannot overwrite the preserved original with an already-expanded list.
"""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_utils import expand_wildcards_in_blocks  # noqa: E402


class TestFileSpecPreservation(unittest.TestCase):
    """block['file_spec'] keeps the original glob across expansion."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _touch(self, name):
        with open(os.path.join(self.temp_dir, name), 'w') as f:
            f.write("2024-01-06T10:00:00.000 line\n")

    def test_string_glob_preserved_and_file_expanded(self):
        self._touch('daemon.log')
        self._touch('daemon.log.1')
        blocks = [{'label': 'B', 'file': 'daemon.log*', 'patterns': ['x']}]
        expand_wildcards_in_blocks(blocks, self.temp_dir)
        # Original glob preserved.
        self.assertEqual(blocks[0]['file_spec'], 'daemon.log*')
        # file expanded to concrete matches (glob no longer present).
        self.assertIn('daemon.log', blocks[0]['file'])
        self.assertNotEqual(blocks[0]['file'], 'daemon.log*')

    def test_list_glob_preserved(self):
        self._touch('daemon.log')
        self._touch('mtcAgent.log')
        blocks = [{'label': 'B',
                   'file': ['daemon.log*', 'mtcAgent.log*'],
                   'patterns': ['x']}]
        expand_wildcards_in_blocks(blocks, self.temp_dir)
        self.assertEqual(blocks[0]['file_spec'],
                         ['daemon.log*', 'mtcAgent.log*'])

    def test_reentry_guard_keeps_original_glob(self):
        """A second expansion pass must not overwrite file_spec."""
        self._touch('daemon.log')
        self._touch('daemon.log.1')
        blocks = [{'label': 'B', 'file': 'daemon.log*', 'patterns': ['x']}]
        expand_wildcards_in_blocks(blocks, self.temp_dir)
        first_spec = blocks[0]['file_spec']
        # Second pass: block['file'] is now the expanded list.
        expand_wildcards_in_blocks(blocks, self.temp_dir)
        self.assertEqual(blocks[0]['file_spec'], first_spec)
        self.assertEqual(blocks[0]['file_spec'], 'daemon.log*')


if __name__ == '__main__':
    unittest.main()
