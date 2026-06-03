#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for the container domain.
#
#
########################################################################
"""Tests for the container domain — parsing and summary building."""
import os
import shutil
import sys
import tempfile
import unittest

CONFTOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CONFTOOL_DIR)
sys.path.insert(0, os.path.join(CONFTOOL_DIR, 'test'))

from domains.container.config import _parse_get_nodes   # noqa: E402
from domains.container.config import _parse_get_pods    # noqa: E402
from domains.container.config import build_summary  # noqa: E402
from domains.container.config import load_config    # noqa: E402
from host_utils import set_verbose_level            # noqa: E402
from mock_factory import CONTAINER_GET_NODES        # noqa: E402
from mock_factory import CONTAINER_GET_PODS         # noqa: E402
from mock_factory import create_bundle              # noqa: E402


class TestParseGetNodes(unittest.TestCase):
    """Test kubectl get nodes parsing."""

    def test_nodes_parsed(self):
        config = {}
        _parse_get_nodes(CONTAINER_GET_NODES, config)
        nodes = config['kube_nodes']
        self.assertEqual(len(nodes), 4)

    def test_node_version(self):
        config = {}
        _parse_get_nodes(CONTAINER_GET_NODES, config)
        self.assertEqual(config['kube_nodes'][0]['version'], 'v1.29.2')

    def test_node_internal_ip(self):
        config = {}
        _parse_get_nodes(CONTAINER_GET_NODES, config)
        self.assertEqual(config['kube_nodes'][0]['internal_ip'],
                         '192.168.206.20')

    def test_empty_input(self):
        config = {}
        _parse_get_nodes('', config)
        self.assertNotIn('kube_nodes', config)


class TestParseGetPods(unittest.TestCase):
    """Test kubectl get pods parsing."""

    def test_pods_parsed(self):
        config = {}
        _parse_get_pods(CONTAINER_GET_PODS, config)
        pods = config['kube_pods']
        self.assertEqual(len(pods), 4)

    def test_pod_status(self):
        config = {}
        _parse_get_pods(CONTAINER_GET_PODS, config)
        statuses = [p['status'] for p in config['kube_pods']]
        self.assertIn('Running', statuses)
        self.assertIn('CrashLoopBackOff', statuses)

    def test_pod_namespace(self):
        config = {}
        _parse_get_pods(CONTAINER_GET_PODS, config)
        namespaces = {p['namespace'] for p in config['kube_pods']}
        self.assertIn('kube-system', namespaces)
        self.assertIn('monitoring', namespaces)


class TestContainerLoadAndSummary(unittest.TestCase):
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
        self.assertIn('cluster', summary)
        self.assertEqual(summary['cluster']['node_count'], 4)
        self.assertEqual(summary['cluster']['ready_count'], 4)

    def test_problem_pods_detected(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        problems = summary.get('pods', {}).get('problem_pods', [])
        self.assertTrue(len(problems) > 0)

    def test_helm_releases(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        helm = summary.get('helm', {})
        self.assertEqual(helm.get('release_count'), 4)
        failed = helm.get('failed_releases', [])
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['name'], 'stuck-release')

    def test_cross_checks_nodes_ok(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        checks = summary['cross_check']
        node_checks = [c for c in checks
                       if c['check'].startswith('node ')]
        self.assertTrue(all(c['status'] == 'OK' for c in node_checks))


if __name__ == '__main__':
    unittest.main()
