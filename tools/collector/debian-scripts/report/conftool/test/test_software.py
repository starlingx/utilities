#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for the software domain — parsing and summary building
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

from domains.software.config import _parse_deploy_host_list  # noqa: E402
from domains.software.config import _parse_deploy_show     # noqa: E402
from domains.software.config import _parse_software_list   # noqa: E402
from domains.software.config import build_summary   # noqa: E402
from domains.software.config import load_config     # noqa: E402
from host_utils import set_verbose_level            # noqa: E402
from mock_factory import create_bundle              # noqa: E402
from mock_factory import SOFTWARE_LIST              # noqa: E402


class TestParseSoftwareList(unittest.TestCase):
    """Test software list table parsing."""

    def test_releases_parsed(self):
        config = {}
        _parse_software_list(SOFTWARE_LIST, config)
        releases = config['software_releases']
        self.assertEqual(len(releases), 2)

    def test_release_fields(self):
        config = {}
        _parse_software_list(SOFTWARE_LIST, config)
        r = config['software_releases'][0]
        self.assertEqual(r['release_id'], 'WRCP-24.09.0')
        self.assertTrue(r['reboot_required'])
        self.assertEqual(r['state'], 'deployed')

    def test_all_deployed(self):
        config = {}
        _parse_software_list(SOFTWARE_LIST, config)
        for r in config['software_releases']:
            self.assertEqual(r['state'], 'deployed')

    def test_empty_input(self):
        config = {}
        _parse_software_list('', config)
        self.assertEqual(config['software_releases'], [])

    def test_no_duplicates(self):
        """Verify fix: no double-parse duplicates."""
        config = {}
        _parse_software_list(SOFTWARE_LIST, config)
        ids = [r['release_id'] for r in config['software_releases']]
        self.assertEqual(len(ids), len(set(ids)))


class TestParseDeployShow(unittest.TestCase):
    """Test deploy show parsing."""

    def test_no_deploy(self):
        config = {}
        _parse_deploy_show('No deploy in progress', config)
        self.assertEqual(config['deploy_status'], 'none')

    def test_deploy_in_progress(self):
        config = {}
        _parse_deploy_show('from_release: 24.09.0\nto_release: 24.09.1',
                           config)
        self.assertEqual(config['deploy_status'], 'in_progress')


class TestParseDeployHostList(unittest.TestCase):
    """Test deploy host-list parsing."""

    def test_no_deploy(self):
        config = {}
        _parse_deploy_host_list('No deploy in progress', config)
        self.assertNotIn('deploy_hosts', config)

    def test_hosts_parsed(self):
        text = (
            "+----------------+-----------+\n"
            "| Hostname       | State     |\n"
            "+----------------+-----------+\n"
            "| controller-0   | deployed  |\n"
            "| controller-1   | pending   |\n"
            "+----------------+-----------+\n"
        )
        config = {}
        _parse_deploy_host_list(text, config)
        hosts = config['deploy_hosts']
        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[0]['hostname'], 'controller-0')
        self.assertEqual(hosts[1]['state'], 'pending')


class TestSoftwareLoadAndSummary(unittest.TestCase):
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
        self.assertIn('build', summary)
        self.assertEqual(summary['build']['sw_version'], '24.09')

    def test_deploy_status_none(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertEqual(summary['deploy_status'], 'none')

    def test_releases_in_summary(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertIn('releases', summary)
        self.assertEqual(len(summary['releases']), 2)

    def test_build_info_fields(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        build = summary['build']
        self.assertEqual(build['build_type'], 'Formal')
        self.assertEqual(build['build_number'], '22')


if __name__ == '__main__':
    unittest.main()
