#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for host_utils.py — section parsing, host discovery, helpers.
#
#
########################################################################

import os
import shutil
import sys
import tempfile
import unittest

CONFTOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CONFTOOL_DIR)

from host_utils import extract_host_identity   # noqa: E402
from host_utils import find_host_dir           # noqa: E402
from host_utils import human_bytes             # noqa: E402
from host_utils import note_source             # noqa: E402
from host_utils import parse_info_sections     # noqa: E402
from host_utils import set_verbose_level       # noqa: E402


class TestParseInfoSections(unittest.TestCase):
    """Test .info file section parsing across header formats."""

    def test_format_a_empty_hostname(self):
        """Format A: empty hostname field between colons."""
        text = (
            "----\n"
            "Tue 16 Dec 2025 11:58:55 AM KST :  : ip -s link\n"
            "----\n"
            "output line 1\n"
            "output line 2\n"
        )
        sections = parse_info_sections(text)
        self.assertIn('ip -s link', sections)
        self.assertIn('output line 1', sections['ip -s link'])

    def test_format_b_with_hostname(self):
        """Format B: hostname present between colons."""
        text = (
            "----\n"
            "Tue 20 Jan 2026 08:00:20 AM UTC : controller-0 : ip addr show\n"
            "----\n"
            "1: lo: <LOOPBACK>\n"
        )
        sections = parse_info_sections(text)
        self.assertIn('ip addr show', sections)

    def test_format_c_different_date(self):
        """Format C: different date layout."""
        text = (
            "----\n"
            "Fri Apr 24 12:20:08 UTC 2026 : controller-0 : ceph status\n"
            "----\n"
            "health: HEALTH_OK\n"
        )
        sections = parse_info_sections(text)
        self.assertIn('ceph status', sections)
        self.assertIn('HEALTH_OK', sections['ceph status'])

    def test_multiple_sections(self):
        """Multiple sections in one file."""
        text = (
            "----\n"
            "Mon 01 Jan 2025 12:00:00 PM UTC : host : cmd1\n"
            "----\n"
            "output1\n"
            "----\n"
            "Mon 01 Jan 2025 12:00:01 PM UTC : host : cmd2\n"
            "----\n"
            "output2\n"
        )
        sections = parse_info_sections(text)
        self.assertEqual(len(sections), 2)
        self.assertIn('cmd1', sections)
        self.assertIn('cmd2', sections)

    def test_empty_input(self):
        """Empty string returns empty dict."""
        self.assertEqual(parse_info_sections(''), {})

    def test_command_with_colons(self):
        """Command containing colons (e.g. grep patterns)."""
        text = (
            "----\n"
            "Tue 16 Dec 2025 11:58:55 AM UTC : host : "
            "grep -r pattern:value /etc\n"
            "----\n"
            "match line\n"
        )
        sections = parse_info_sections(text)
        self.assertIn('grep -r pattern:value /etc', sections)


class TestFindHostDir(unittest.TestCase):
    """Test host directory discovery in bundle layouts."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        set_verbose_level(0)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_flat_layout(self):
        """Flat bundle: <bundle>/<host>_<ts>/var/."""
        host_dir = os.path.join(self.temp_dir, 'controller-0_20250101.120000')
        os.makedirs(os.path.join(host_dir, 'var'))
        result = find_host_dir(self.temp_dir, 'controller-0')
        self.assertEqual(result, host_dir)

    def test_nested_layout(self):
        """Nested bundle: <bundle>/<host>_<ts>/<host>_<ts>/var/."""
        outer = os.path.join(self.temp_dir, 'controller-0_20250101.120000')
        inner = os.path.join(outer, 'controller-0_20250101.120000')
        os.makedirs(os.path.join(inner, 'var'))
        result = find_host_dir(self.temp_dir, 'controller-0')
        self.assertEqual(result, inner)

    def test_latest_timestamp_selected(self):
        """When multiple timestamps exist, pick the latest."""
        old = os.path.join(self.temp_dir, 'controller-0_20240101.120000')
        new = os.path.join(self.temp_dir, 'controller-0_20250601.120000')
        os.makedirs(os.path.join(old, 'var'))
        os.makedirs(os.path.join(new, 'var'))
        result = find_host_dir(self.temp_dir, 'controller-0')
        self.assertEqual(result, new)

    def test_host_not_found(self):
        """Returns None when hostname not found."""
        result = find_host_dir(self.temp_dir, 'nonexistent-host')
        self.assertIsNone(result)


class TestExtractHostIdentity(unittest.TestCase):
    """Test hostname/timestamp extraction from directory names."""

    def test_standard_format(self):
        hostname, ts = extract_host_identity(
            '/bundle/controller-0_20250101.120000')
        self.assertEqual(hostname, 'controller-0')
        self.assertEqual(ts, '20250101.120000')

    def test_worker_hostname(self):
        hostname, ts = extract_host_identity(
            '/bundle/worker-3_20250601.090000')
        self.assertEqual(hostname, 'worker-3')
        self.assertEqual(ts, '20250601.090000')

    def test_no_timestamp(self):
        hostname, ts = extract_host_identity('/bundle/controller-0')
        self.assertEqual(hostname, 'controller-0')
        self.assertEqual(ts, '')

    def test_trailing_slash(self):
        hostname, ts = extract_host_identity(
            '/bundle/controller-0_20250101.120000/')
        self.assertEqual(hostname, 'controller-0')
        self.assertEqual(ts, '20250101.120000')


class TestHumanBytes(unittest.TestCase):
    """Test human-readable byte formatting."""

    def test_bytes(self):
        self.assertEqual(human_bytes(500), '500B')

    def test_kilobytes(self):
        self.assertEqual(human_bytes(1024), '1.0K')

    def test_megabytes(self):
        self.assertEqual(human_bytes(1048576), '1.0M')

    def test_gigabytes(self):
        self.assertEqual(human_bytes(1073741824), '1.0G')

    def test_zero(self):
        self.assertEqual(human_bytes(0), '0B')


class TestNoteSource(unittest.TestCase):
    """Test shared note_source helper."""

    def test_appends_to_key(self):
        config = {}
        note_source(config, 'test_files', '/path/a')
        note_source(config, 'test_files', '/path/b')
        self.assertEqual(config['test_files'], ['/path/a', '/path/b'])

    def test_creates_key_if_missing(self):
        config = {}
        note_source(config, 'new_key', '/path/x')
        self.assertIn('new_key', config)


if __name__ == '__main__':
    unittest.main()
