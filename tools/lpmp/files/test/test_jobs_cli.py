#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
CLI-level tests for jobs mode and the graphing dependency precheck in
lpmptool: graphing_available(), --list-jobs, and the -j/--jobs alias.
"""

import io
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
from unittest.mock import MagicMock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

import lpmptool  # noqa: E402


class TestGraphingAvailable(unittest.TestCase):
    """graphing_available() detects/records missing graphing deps."""

    def test_reports_missing_when_find_spec_none(self):
        real_modules = dict(sys.modules)
        sys.modules.pop('pandas', None)
        sys.modules.pop('matplotlib', None)
        try:
            with mock.patch('importlib.util.find_spec', return_value=None):
                ok, missing = lpmptool.graphing_available()
        finally:
            sys.modules.clear()
            sys.modules.update(real_modules)
        self.assertFalse(ok)
        self.assertIn('pandas', missing)
        self.assertIn('matplotlib', missing)

    def test_stubbed_module_in_sys_modules_counts_present(self):
        # A MagicMock stub (as other tests install) has no valid __spec__;
        # graphing_available must treat an already-loaded module as present
        # and must not raise ValueError from find_spec.
        with mock.patch.dict(sys.modules,
                             {'pandas': MagicMock(), 'matplotlib': MagicMock()}):
            ok, missing = lpmptool.graphing_available()
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_find_spec_valueerror_treated_as_missing(self):
        real_modules = dict(sys.modules)
        sys.modules.pop('pandas', None)
        sys.modules.pop('matplotlib', None)
        try:
            with mock.patch('importlib.util.find_spec',
                            side_effect=ValueError('no __spec__')):
                ok, missing = lpmptool.graphing_available()
        finally:
            sys.modules.clear()
            sys.modules.update(real_modules)
        self.assertFalse(ok)
        self.assertEqual(sorted(missing), ['matplotlib', 'pandas'])


class TestListJobsCli(unittest.TestCase):
    """--list-jobs prints available specs and exits 0."""

    def test_list_jobs_prints_and_exits(self):
        fake = [('mtce_job.json', '/var/lib/lpmp_jobs/mtce_job.json'),
                ('graph_job.json', '/var/lib/lpmp_jobs/graph_job.json')]
        out = io.StringIO()
        with mock.patch.object(lpmptool, 'collect_jobs_files',
                               return_value=fake), \
             mock.patch.object(sys, 'argv', ['lpmptool', '--list-jobs']), \
             mock.patch.object(sys, 'stdout', out):
            with self.assertRaises(SystemExit) as cm:
                lpmptool.main()
        self.assertEqual(cm.exception.code, 0)
        printed = out.getvalue()
        self.assertIn('mtce_job', printed)
        self.assertIn('graph_job', printed)

    def test_list_jobs_none_found(self):
        out = io.StringIO()
        with mock.patch.object(lpmptool, 'collect_jobs_files',
                               return_value=[]), \
             mock.patch.object(sys, 'argv', ['lpmptool', '-lj']), \
             mock.patch.object(sys, 'stdout', out):
            with self.assertRaises(SystemExit) as cm:
                lpmptool.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertIn('No jobs spec files found', out.getvalue())


class TestJobsShortFlag(unittest.TestCase):
    """-j is accepted as an alias for --jobs and routes into jobs mode."""

    def test_dash_j_routes_to_jobs_dispatch(self):
        # -j with an unknown spec should reach jobs mode and exit non-zero
        # (spec not found), proving the alias mapped to args.jobs.
        err = io.StringIO()
        with mock.patch.object(
                sys, 'argv',
                ['lpmptool', '-b', '/some/bundle', '-j', '__no_such_spec__']), \
             mock.patch.object(sys, 'stderr', err), \
             mock.patch.object(sys, 'stdout', io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                lpmptool.main()
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn('not found in search paths', err.getvalue())


if __name__ == '__main__':
    unittest.main()
