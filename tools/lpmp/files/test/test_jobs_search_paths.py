#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Tests for jobs spec discovery and search-path resolution.

Covers the jobs analogues of the model search-path helpers:
- get_jobs_search_paths ordering and installed-vs-source behavior
- find_jobs_file resolution (bare name, .json, explicit/absolute path)
- collect_jobs_files listing + basename de-dup across paths
- load_jobs_spec resolving a bare name through the search path
"""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

import lpmp_jobs                              # noqa: E402
from lpmp_jobs import _resolve_lpmptool_path  # noqa: E402
import lpmp_utils                             # noqa: E402
from lpmp_utils import collect_jobs_files     # noqa: E402
from lpmp_utils import find_jobs_file         # noqa: E402
from lpmp_utils import get_jobs_search_paths  # noqa: E402


class TestGetJobsSearchPaths(unittest.TestCase):
    """get_jobs_search_paths ordering and installed-layout behavior."""

    def test_current_dir_is_always_highest_priority(self):
        with mock.patch.object(
                lpmp_utils.os.path, 'dirname',
                return_value='/opt/lpmp/files'):
            paths = get_jobs_search_paths()
        # Current directory always wins, so a same-named spec there
        # overrides any built-in or packaged default.
        self.assertEqual(paths[0], './')
        self.assertEqual(paths[1], '/etc/lpmp.d/jobs/')

    def test_source_layout_includes_tool_jobs_after_overrides(self):
        with mock.patch.object(
                lpmp_utils.os.path, 'dirname',
                return_value='/opt/lpmp/files'):
            paths = get_jobs_search_paths()
        self.assertIn(os.path.join('/opt/lpmp/files', 'jobs'), paths)
        # System locations are always present further down.
        self.assertIn('/var/lib/lpmp_jobs/', paths)

    def test_installed_layout_skips_tool_jobs(self):
        with mock.patch.object(
                lpmp_utils.os.path, 'dirname',
                return_value='/usr/lib/python3/dist-packages/lpmp'):
            paths = get_jobs_search_paths()
        # No dist-packages 'jobs' dir should be prepended.
        self.assertFalse(any('dist-packages' in p for p in paths))
        self.assertEqual(paths[0], './')
        self.assertIn('/var/lib/lpmp_jobs/', paths)


class TestFindJobsFile(unittest.TestCase):
    """find_jobs_file resolution across name forms and search paths."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.jobs_dir = os.path.join(self.tmp, 'jobs')
        os.makedirs(self.jobs_dir)
        self._write('mtce_job.json', {'jobs': [{'model': 'a.yaml'}]})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, payload):
        path = os.path.join(self.jobs_dir, name)
        with open(path, 'w') as f:
            json.dump(payload, f)
        return path

    def test_absolute_path_used_as_is(self):
        target = os.path.join(self.jobs_dir, 'mtce_job.json')
        self.assertEqual(find_jobs_file(target), target)

    def test_absolute_path_missing_returns_none(self):
        self.assertIsNone(find_jobs_file(os.path.join(self.tmp, 'nope.json')))

    def test_bare_name_resolved_via_search_path(self):
        with mock.patch.object(lpmp_utils, 'get_jobs_search_paths',
                               return_value=[self.jobs_dir]):
            resolved = find_jobs_file('mtce_job')
        self.assertEqual(os.path.normpath(resolved),
                         os.path.normpath(os.path.join(self.jobs_dir,
                                                       'mtce_job.json')))

    def test_name_with_extension_resolved(self):
        with mock.patch.object(lpmp_utils, 'get_jobs_search_paths',
                               return_value=[self.jobs_dir]):
            resolved = find_jobs_file('mtce_job.json')
        self.assertTrue(resolved.endswith('mtce_job.json'))

    def test_unknown_name_returns_none(self):
        with mock.patch.object(lpmp_utils, 'get_jobs_search_paths',
                               return_value=[self.jobs_dir]):
            self.assertIsNone(find_jobs_file('does_not_exist'))


class TestCollectJobsFiles(unittest.TestCase):
    """collect_jobs_files listing and basename de-dup across paths."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.high = os.path.join(self.tmp, 'high')
        self.low = os.path.join(self.tmp, 'low')
        os.makedirs(self.high)
        os.makedirs(self.low)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, folder, name):
        with open(os.path.join(folder, name), 'w') as f:
            json.dump({'jobs': [{'model': 'a.yaml'}]}, f)

    def test_lists_json_only_sorted(self):
        self._write(self.high, 'b_job.json')
        self._write(self.high, 'a_job.json')
        self._write(self.high, 'notes.txt')
        found = collect_jobs_files([self.high])
        names = [n for n, _ in found]
        self.assertEqual(names, ['a_job.json', 'b_job.json'])

    def test_higher_priority_path_shadows_lower(self):
        self._write(self.high, 'dup.json')
        self._write(self.low, 'dup.json')
        found = collect_jobs_files([self.high, self.low])
        # De-dup by basename; the high-priority path wins.
        dup_entries = [p for n, p in found if n == 'dup.json']
        self.assertEqual(len(dup_entries), 1)
        self.assertIn('high', dup_entries[0])

    def test_missing_dir_is_skipped(self):
        self._write(self.high, 'x_job.json')
        missing = os.path.join(self.tmp, 'does_not_exist')
        found = collect_jobs_files([missing, self.high])
        self.assertEqual([n for n, _ in found], ['x_job.json'])


class TestLoadJobsSpecNameResolution(unittest.TestCase):
    """load_jobs_spec resolves a bare name through the search path."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.jobs_dir = os.path.join(self.tmp, 'jobs')
        os.makedirs(self.jobs_dir)
        with open(os.path.join(self.jobs_dir, 'named_job.json'), 'w') as f:
            json.dump({'jobs': [{'model': 'a.yaml'}, {'model': 'b.yaml'}]}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bare_name_resolved_and_loaded(self):
        from lpmp_jobs import load_jobs_spec
        with mock.patch.object(lpmp_utils, 'get_jobs_search_paths',
                               return_value=[self.jobs_dir]):
            jobs, top = load_jobs_spec('named_job')
        self.assertEqual(len(jobs), 2)

    def test_unknown_name_exits(self):
        from lpmp_jobs import load_jobs_spec
        with mock.patch.object(lpmp_utils, 'get_jobs_search_paths',
                               return_value=[self.jobs_dir]):
            with self.assertRaises(SystemExit):
                load_jobs_spec('missing_job')


class TestResolveLpmptoolPath(unittest.TestCase):
    """_resolve_lpmptool_path prefers argv0, then sibling, bin, PATH."""

    def test_argv0_used_when_it_is_lpmptool_with_path(self):
        with mock.patch.object(lpmp_jobs.sys, 'argv', ['/usr/local/bin/lpmptool']), \
             mock.patch.object(lpmp_jobs.os.path, 'exists',
                               side_effect=lambda p: p == '/usr/local/bin/lpmptool'):
            self.assertEqual(_resolve_lpmptool_path(), '/usr/local/bin/lpmptool')

    def test_falls_back_to_module_sibling(self):
        here = os.path.dirname(os.path.abspath(lpmp_jobs.__file__))
        sibling = os.path.join(here, 'lpmptool')
        with mock.patch.object(lpmp_jobs.sys, 'argv', ['lpmptool']), \
             mock.patch.object(lpmp_jobs.os.path, 'exists',
                               side_effect=lambda p: p == sibling):
            self.assertEqual(_resolve_lpmptool_path(), sibling)

    def test_falls_back_to_installed_bin(self):
        with mock.patch.object(lpmp_jobs.sys, 'argv', ['lpmptool']), \
             mock.patch.object(lpmp_jobs.os.path, 'exists',
                               side_effect=lambda p: p == '/usr/local/bin/lpmptool'):
            self.assertEqual(_resolve_lpmptool_path(), '/usr/local/bin/lpmptool')

    def test_falls_back_to_path_lookup(self):
        with mock.patch.object(lpmp_jobs.sys, 'argv', ['lpmptool']), \
             mock.patch.object(lpmp_jobs.os.path, 'exists', return_value=False), \
             mock.patch.object(lpmp_jobs.shutil, 'which',
                               return_value='/opt/bin/lpmptool'):
            self.assertEqual(_resolve_lpmptool_path(), '/opt/bin/lpmptool')

    def test_last_resort_absolutises_argv0(self):
        with mock.patch.object(lpmp_jobs.sys, 'argv', ['lpmptool']), \
             mock.patch.object(lpmp_jobs.os.path, 'exists', return_value=False), \
             mock.patch.object(lpmp_jobs.shutil, 'which', return_value=None):
            self.assertEqual(_resolve_lpmptool_path(),
                             os.path.abspath('lpmptool'))


if __name__ == '__main__':
    unittest.main()
