#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for graceful permission-error handling.

The tool records paths it cannot access due to permission errors, excludes
them, and continues rather than aborting. Covered here:
- the module-level collector (record/get/clear, dedup + order)
- discover_window_files records an unreadable directory and marks it
  'permission denied' in the skipped list instead of raising
"""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import extract_context_lines       # noqa: E402
from lpmp_utils import _is_skippable_file           # noqa: E402
from lpmp_utils import clear_permission_errors      # noqa: E402
from lpmp_utils import discover_window_files        # noqa: E402
from lpmp_utils import get_permission_errors        # noqa: E402
from lpmp_utils import record_permission_error      # noqa: E402


IS_ROOT = hasattr(os, 'getuid') and os.getuid() == 0


class TestPermissionErrorCollector(unittest.TestCase):
    """Unit tests for the permission-error collector functions."""

    def setUp(self):
        clear_permission_errors()

    def tearDown(self):
        clear_permission_errors()

    def test_record_and_get(self):
        record_permission_error('/var/log/apache2')
        self.assertEqual(get_permission_errors(), ['/var/log/apache2'])

    def test_record_dedups(self):
        record_permission_error('/a')
        record_permission_error('/a')
        record_permission_error('/b')
        self.assertEqual(get_permission_errors(), ['/a', '/b'])

    def test_record_preserves_order(self):
        for p in ['/z', '/y', '/x']:
            record_permission_error(p)
        self.assertEqual(get_permission_errors(), ['/z', '/y', '/x'])

    def test_clear_resets(self):
        record_permission_error('/a')
        clear_permission_errors()
        self.assertEqual(get_permission_errors(), [])
        # After clear, a previously-seen path can be recorded again.
        record_permission_error('/a')
        self.assertEqual(get_permission_errors(), ['/a'])

    def test_get_returns_copy(self):
        record_permission_error('/a')
        snapshot = get_permission_errors()
        snapshot.append('/mutated')
        self.assertEqual(get_permission_errors(), ['/a'])


@unittest.skipIf(IS_ROOT, "root bypasses filesystem permission checks")
class TestDiscoverWindowFilesPermission(unittest.TestCase):
    """discover_window_files must skip unreadable dirs, not raise."""

    def setUp(self):
        clear_permission_errors()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Restore perms so cleanup can remove the tree.
        secret = os.path.join(self.temp_dir, 'secret')
        if os.path.isdir(secret):
            os.chmod(secret, 0o755)
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        clear_permission_errors()

    def _write(self, relpath, line):
        path = os.path.join(self.temp_dir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(line + "\n")
        return path

    def test_unreadable_dir_recorded_and_skipped_not_raised(self):
        # A readable log plus an unreadable directory both matched by '*'.
        self._write('app.log', '2024-01-06T10:00:00.000 hello')
        secret = os.path.join(self.temp_dir, 'secret')
        os.makedirs(secret)
        self._write('secret/hidden.log', '2024-01-06T10:00:10.000 nope')
        os.chmod(secret, 0o000)

        # Must not raise despite the unreadable directory.
        matched, skipped = discover_window_files(self.temp_dir, '*')

        # The readable file is still matched.
        self.assertTrue(any('app.log' in m[0] for m in matched))
        # The unreadable directory is recorded in the collector.
        perr = get_permission_errors()
        self.assertTrue(any('secret' in p for p in perr),
                        f"expected 'secret' in permission errors, got {perr}")


@unittest.skipIf(IS_ROOT, "root bypasses filesystem permission checks")
class TestIsSkippableFilePermission(unittest.TestCase):
    """_is_skippable_file records unreadable files, not just skips them."""

    def setUp(self):
        clear_permission_errors()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        secret = os.path.join(self.temp_dir, 'secret.log')
        if os.path.isfile(secret):
            os.chmod(secret, 0o644)
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        clear_permission_errors()

    def test_unreadable_file_recorded_and_skipped(self):
        secret = os.path.join(self.temp_dir, 'secret.log')
        with open(secret, 'w') as f:
            f.write('2024-01-06T10:00:00.000 sensitive\n')
        os.chmod(secret, 0o000)

        # Unreadable file is treated as skippable and does not raise.
        self.assertTrue(_is_skippable_file(secret))
        # And it is recorded for the end-of-run report.
        self.assertIn(secret, get_permission_errors())

    def test_readable_text_file_not_skipped_or_recorded(self):
        readable = os.path.join(self.temp_dir, 'app.log')
        with open(readable, 'w') as f:
            f.write('2024-01-06T10:00:00.000 hello\n')

        self.assertFalse(_is_skippable_file(readable))
        self.assertEqual(get_permission_errors(), [])


@unittest.skipIf(IS_ROOT, "root bypasses filesystem permission checks")
class TestExtractContextLinesPermission(unittest.TestCase):
    """extract_context_lines records unreadable files, returns empty context."""

    def setUp(self):
        clear_permission_errors()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        secret = os.path.join(self.temp_dir, 'secret.log')
        if os.path.isfile(secret):
            os.chmod(secret, 0o644)
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        clear_permission_errors()

    def test_unreadable_file_recorded_returns_empty_context(self):
        secret = os.path.join(self.temp_dir, 'secret.log')
        with open(secret, 'w') as f:
            f.write('line-before\nMATCH here\nline-after\n')
        os.chmod(secret, 0o000)

        before, after = extract_context_lines(
            self.temp_dir, 'secret.log', 'MATCH here',
            context_before=1, context_after=1)

        # Empty context on failure, no exception raised.
        self.assertEqual(before, [])
        self.assertEqual(after, [])
        # The unreadable file is recorded (path is log_dir/filename).
        self.assertIn(secret, get_permission_errors())

    def test_readable_file_returns_context_no_record(self):
        readable = os.path.join(self.temp_dir, 'app.log')
        with open(readable, 'w') as f:
            f.write('line-before\nMATCH here\nline-after\n')

        before, after = extract_context_lines(
            self.temp_dir, 'app.log', 'MATCH here',
            context_before=1, context_after=1)

        self.assertEqual(before, ['line-before'])
        self.assertEqual(after, ['line-after'])
        self.assertEqual(get_permission_errors(), [])


if __name__ == '__main__':
    unittest.main()
