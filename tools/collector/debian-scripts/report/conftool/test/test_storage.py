#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for the storage domain — parsing and summary building
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
sys.path.insert(0, os.path.join(CONFTOOL_DIR, 'test'))

from domains.storage.config import _parse_ceph_status    # noqa: E402
from domains.storage.config import _parse_df             # noqa: E402
from domains.storage.config import _parse_drbd           # noqa: E402
from domains.storage.config import _parse_lsblk          # noqa: E402
from domains.storage.config import build_summary    # noqa: E402
from domains.storage.config import load_config      # noqa: E402
from host_utils import set_verbose_level            # noqa: E402
from mock_factory import create_bundle              # noqa: E402
from mock_factory import STORAGE_CEPH_STATUS        # noqa: E402
from mock_factory import STORAGE_DF                 # noqa: E402
from mock_factory import STORAGE_DRBD               # noqa: E402
from mock_factory import STORAGE_LSBLK              # noqa: E402


class TestParseCephStatus(unittest.TestCase):
    """Test ceph status parsing."""

    def test_health(self):
        config = {}
        _parse_ceph_status(STORAGE_CEPH_STATUS, config)
        self.assertEqual(config['ceph']['health'], 'HEALTH_OK')

    def test_fsid(self):
        config = {}
        _parse_ceph_status(STORAGE_CEPH_STATUS, config)
        self.assertEqual(config['ceph']['fsid'],
                         '471183b8-9997-45cd-90ef-7e7e78615412')

    def test_services(self):
        config = {}
        _parse_ceph_status(STORAGE_CEPH_STATUS, config)
        self.assertIn('mon', config['ceph'])
        self.assertIn('mgr', config['ceph'])
        self.assertIn('osd_summary', config['ceph'])

    def test_usage(self):
        config = {}
        _parse_ceph_status(STORAGE_CEPH_STATUS, config)
        self.assertIn('usage', config['ceph'])
        self.assertIn('13 GiB', config['ceph']['usage'])


class TestParseDrbd(unittest.TestCase):
    """Test /proc/drbd parsing."""

    def test_resources_parsed(self):
        config = {}
        _parse_drbd(STORAGE_DRBD, config)
        drbd = config['drbd']
        self.assertEqual(len(drbd), 3)

    def test_resource_fields(self):
        config = {}
        _parse_drbd(STORAGE_DRBD, config)
        r = config['drbd'][0]
        self.assertEqual(r['minor'], 0)
        self.assertEqual(r['connection'], 'Connected')
        self.assertIn('UpToDate/UpToDate', r['disk_state'])

    def test_out_of_sync(self):
        config = {}
        _parse_drbd(STORAGE_DRBD, config)
        for r in config['drbd']:
            self.assertEqual(r['out_of_sync_kb'], 0)


class TestParseDf(unittest.TestCase):
    """Test df output parsing."""

    def test_filesystems_parsed(self):
        config = {}
        _parse_df(STORAGE_DF, config)
        fs = config['filesystems']
        self.assertEqual(len(fs), 6)

    def test_filesystem_fields(self):
        config = {}
        _parse_df(STORAGE_DF, config)
        root = next(f for f in config['filesystems']
                    if f['mount'] == '/sysroot')
        self.assertEqual(root['type'], 'ext4')
        self.assertEqual(root['use_pct'], '40')

    def test_all_usage_low(self):
        """Real bundle has no high-usage filesystems."""
        config = {}
        _parse_df(STORAGE_DF, config)
        for fs in config['filesystems']:
            pct = int(fs['use_pct'])
            self.assertLess(pct, 85)


class TestParseLsblk(unittest.TestCase):
    """Test lsblk output parsing."""

    def test_devices_parsed(self):
        config = {}
        _parse_lsblk(STORAGE_LSBLK, config)
        devs = config['block_devices']
        self.assertTrue(len(devs) > 0)

    def test_disk_type(self):
        config = {}
        _parse_lsblk(STORAGE_LSBLK, config)
        disks = [d for d in config['block_devices']
                 if d['type'] == 'disk']
        self.assertEqual(len(disks), 2)
        names = [d['name'] for d in disks]
        self.assertIn('sda', names)
        self.assertIn('sdb', names)

    def test_partitions(self):
        config = {}
        _parse_lsblk(STORAGE_LSBLK, config)
        parts = [d for d in config['block_devices']
                 if d['type'] == 'part']
        self.assertTrue(len(parts) >= 5)


class TestStorageLoadAndSummary(unittest.TestCase):
    """Test full load_config -> build_summary pipeline."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        set_verbose_level(0)
        create_bundle(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _get_host_dir(self):
        return os.path.join(self.temp_dir,
                            'controller-0_20250211.212225')

    def test_load_and_build(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertIn('ceph', summary)
        self.assertEqual(summary['ceph']['health'], 'HEALTH_OK')

    def test_drbd_in_summary(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertIn('drbd', summary)
        self.assertEqual(len(summary['drbd']), 3)

    def test_no_filesystem_warning(self):
        """Real data has low usage — no warnings expected."""
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        warnings = summary.get('warnings', [])
        self.assertEqual(len(warnings), 0)

    def test_ceph_cross_check_ok(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        checks = summary['cross_check']
        ceph_checks = [c for c in checks
                       if c['check'] == 'ceph health']
        self.assertEqual(len(ceph_checks), 1)
        self.assertEqual(ceph_checks[0]['status'], 'OK')

    def test_drbd_cross_check_ok(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        checks = summary['cross_check']
        drbd_checks = [c for c in checks
                       if c['check'].startswith('drbd')]
        self.assertTrue(all(c['status'] == 'OK' for c in drbd_checks))

    def test_block_devices_in_summary(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertIn('block_devices', summary)
        disk_names = [d['name'] for d in summary['block_devices']]
        self.assertIn('sda', disk_names)


if __name__ == '__main__':
    unittest.main()
