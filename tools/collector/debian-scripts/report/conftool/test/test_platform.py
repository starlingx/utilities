#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for the platform domain — parsing and summary building.
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

from domains.platform.config import _parse_dmidecode     # noqa: E402
from domains.platform.config import _parse_lscpu         # noqa: E402
from domains.platform.config import _parse_meminfo       # noqa: E402
from domains.platform.config import _parse_uptime        # noqa: E402
from domains.platform.config import build_summary    # noqa: E402
from domains.platform.config import load_config      # noqa: E402
from host_utils import set_verbose_level             # noqa: E402
from mock_factory import create_bundle               # noqa: E402
from mock_factory import PLATFORM_DMIDECODE          # noqa: E402
from mock_factory import PLATFORM_LSCPU              # noqa: E402
from mock_factory import PLATFORM_MEMINFO            # noqa: E402
from mock_factory import PLATFORM_UPTIME             # noqa: E402


class TestParseDmidecode(unittest.TestCase):
    """Test dmidecode output parsing."""

    def test_system_info(self):
        config = {}
        _parse_dmidecode(PLATFORM_DMIDECODE, config)
        self.assertEqual(config['dmi_system']['Manufacturer'], 'Dell Inc.')
        self.assertEqual(config['dmi_system']['Product Name'],
                         'PowerEdge R750')
        self.assertEqual(config['dmi_system']['Serial Number'], 'DXG4N34')

    def test_bios_info(self):
        config = {}
        _parse_dmidecode(PLATFORM_DMIDECODE, config)
        self.assertEqual(config['dmi_bios']['Vendor'], 'Dell Inc.')
        self.assertEqual(config['dmi_bios']['Version'], '1.14.1')
        self.assertEqual(config['dmi_bios']['Release Date'], '03/11/2024')

    def test_empty_input(self):
        config = {}
        _parse_dmidecode('', config)
        self.assertEqual(config['dmi_system'], {})
        self.assertEqual(config['dmi_bios'], {})


class TestParseLscpu(unittest.TestCase):
    """Test lscpu output parsing."""

    def test_cpu_fields(self):
        config = {}
        _parse_lscpu(PLATFORM_LSCPU, config)
        self.assertEqual(config['lscpu']['CPU(s)'], '128')
        self.assertEqual(config['lscpu']['Socket(s)'], '2')
        self.assertEqual(config['lscpu']['Core(s) per socket'], '32')
        self.assertIn('Xeon', config['lscpu']['Model name'])


class TestParseUptime(unittest.TestCase):
    """Test uptime output parsing."""

    def test_uptime_extracted(self):
        config = {}
        _parse_uptime(PLATFORM_UPTIME, config)
        self.assertIn('47 min', config['uptime'])

    def test_load_average(self):
        config = {}
        _parse_uptime(PLATFORM_UPTIME, config)
        self.assertIn('4.67', config['load_average'])


class TestParseMeminfo(unittest.TestCase):
    """Test /proc/meminfo parsing."""

    def test_mem_fields(self):
        config = {}
        _parse_meminfo(PLATFORM_MEMINFO, config)
        self.assertEqual(config['meminfo']['MemTotal'], 261189476)
        self.assertEqual(config['meminfo']['MemAvailable'], 242280860)
        self.assertEqual(config['meminfo']['HugePages_Total'], 0)


class TestPlatformLoadAndSummary(unittest.TestCase):
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
        self.assertIn('system', summary)
        self.assertEqual(summary['system']['manufacturer'], 'Dell Inc.')
        self.assertEqual(summary['system']['product'], 'PowerEdge R750')

    def test_cpu_summary(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertIn('cpu', summary)
        self.assertEqual(summary['cpu']['cpus'], '128')
        self.assertEqual(summary['cpu']['sockets'], '2')

    def test_memory_summary(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertIn('memory', summary)
        self.assertIn('total', summary['memory'])

    def test_sm_services_parsed(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        sm = summary.get('sm_services', [])
        self.assertTrue(len(sm) > 0)
        names = [s['name'] for s in sm]
        self.assertIn('controller-services', names)
        self.assertIn('oam-services', names)

    def test_sm_all_active(self):
        """All SM services in real data are active/active — no mismatch."""
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        checks = summary['cross_check']
        sm_fails = [c for c in checks
                    if c['check'].startswith('SM ')
                    and c['status'] == 'FAIL']
        self.assertEqual(len(sm_fails), 0)

    def test_no_coredumps(self):
        """Real bundle has no coredumps."""
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertEqual(summary['coredumps'], [])


if __name__ == '__main__':
    unittest.main()
