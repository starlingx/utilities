#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for output.py modules — text and JSON rendering.
#
########################################################################

import json
import os
import sys
import tempfile
import unittest

CONFTOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CONFTOOL_DIR)
sys.path.insert(0, os.path.join(CONFTOOL_DIR, 'test'))

from domains.container.output import write_json as ct_write_json  # noqa: E402
from domains.container.output import write_text as ct_write_text  # noqa: E402
from domains.network.output import write_json as nw_write_json    # noqa: E402
from domains.network.output import write_text as nw_write_text    # noqa: E402
from domains.software.output import write_json as sw_write_json   # noqa: E402
from domains.software.output import write_text as sw_write_text   # noqa: E402
from host_utils import set_verbose_level                          # noqa: E402


SOFTWARE_SUMMARY = {
    'build': {
        'sw_version': '24.09',
        'build_type': 'formal',
        'build_id': 'r1',
        'build_date': '2026-01-01',
        'job': 'build-job',
        'build_number': '100',
    },
    'host_loads': [
        {'hostname': 'ctrl-0', 'running_release': '24.09'},
    ],
    'deploy_status': 'none',
    'deploy_hosts': [
        {'hostname': 'ctrl-0', 'state': 'deployed'},
    ],
    'releases': [
        {'release_id': 'stx-24.09', 'state': 'deployed',
         'reboot_required': False},
        {'release_id': 'stx-24.10', 'state': 'available',
         'reboot_required': True},
    ],
    'release_details': [
        {'release_id': 'stx-24.09', 'summary': 'Base release',
         'requires': 'none', 'fixes': ['fix-1', 'fix-2'],
         'packages': ['pkg-a', 'pkg-b']},
    ],
    'ostree': {
        'active': 'abc123',
        'rollback': 'def456',
    },
    'cross_check': [
        {'status': 'OK', 'check': 'version_match', 'detail': 'all match'},
        {'status': 'WARN', 'check': 'stale_release', 'detail': 'old'},
    ],
    'source_files': ['software.info'],
}

CONTAINER_SUMMARY = {
    'cluster': {
        'ready_count': 2,
        'node_count': 2,
        'nodes': [
            {'name': 'ctrl-0', 'status': 'Ready', 'roles': 'control-plane'},
        ],
    },
    'pods': {
        'total': 50,
        'running': 48,
        'total_restarts': 5,
        'by_status': {'Running': 48, 'Pending': 2},
        'by_namespace': {'kube-system': 30, 'default': 20},
        'problem_pods': [
            {'name': 'pod-x', 'namespace': 'kube-system',
             'status': 'Pending', 'restarts': 3},
        ],
        'not_running': [
            {'name': 'pod-x', 'namespace': 'kube-system',
             'status': 'Pending', 'restarts': 3, 'node': 'ctrl-0'},
        ],
    },
    'helm': {
        'release_count': 1,
        'by_status': {'deployed': 1},
        'releases': [
            {'name': 'app1', 'namespace': 'default',
             'status': 'deployed', 'chart': 'app1-1.0'},
        ],
    },
    'events': {
        'total': 2,
        'warning_count': 1,
        'by_reason': {'OOM': 1},
        'recent_warnings': [
            {'type': 'Warning', 'reason': 'OOM', 'object': 'pod/x',
             'message': 'killed', 'count': 2},
        ],
    },
    'cross_check': [
        {'status': 'OK', 'check': 'pods_healthy', 'detail': 'all good'},
    ],
    'source_files': ['container.info'],
}

NETWORK_SUMMARY = {
    'host': {'hostname': 'ctrl-0', 'personality': 'controller',
             'subfunctions': 'controller,worker',
             'system_type': 'All-in-one', 'system_mode': 'simplex',
             'sw_version': '24.09', 'collected': '2026-01-01 00:00'},
    'interfaces': [
        {'name': 'lo', 'state': 'UP', 'mtu': 65536,
         'addresses': ['127.0.0.1/8'], 'verbose_only': False},
        {'name': 'eth0', 'state': 'UP', 'mtu': 1500,
         'addresses': ['10.0.0.1/24'], 'verbose_only': False},
    ],
    'bonds': [],
    'vlans': [],
    'routes_v4': [
        {'destination': 'default', 'gateway': '10.0.0.1', 'device': 'eth0'},
    ],
    'routes_v6': [],
    'listeners': {
        'sshd': [{'proto': 'tcp', 'addr': '0.0.0.0', 'port': 22}],
    },
    'dns': {'nameservers': ['8.8.8.8']},
    'hosts_entries': [{'ip': '127.0.0.1', 'names': ['localhost']}],
    'cross_check': [
        {'status': 'OK', 'check': 'interfaces_up', 'detail': 'all up'},
    ],
    'source_files': ['network.info'],
}


class TestSoftwareOutput(unittest.TestCase):
    """Test software domain output writers."""

    def test_write_json(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            sw_write_json(SOFTWARE_SUMMARY, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data['build']['sw_version'], '24.09')
        finally:
            os.unlink(path)

    def test_write_text(self):
        lines = []
        sw_write_text(SOFTWARE_SUMMARY, lines)
        text = '\n'.join(lines)
        self.assertIn('24.09', text)
        self.assertIn('deployed', text)
        self.assertIn('OSTree', text)
        self.assertIn('Cross-Check', text)
        self.assertIn('Packages', text)
        self.assertIn('Source Files', text)


class TestContainerOutput(unittest.TestCase):
    """Test container domain output writers."""

    def test_write_json(self):
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            ct_write_json(CONTAINER_SUMMARY, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data['cluster']['ready_count'], 2)
        finally:
            os.unlink(path)

    def test_write_text(self):
        lines = []
        ct_write_text(CONTAINER_SUMMARY, lines)
        text = '\n'.join(lines)
        self.assertIn('Cluster', text)
        self.assertIn('ctrl-0', text)


class TestNetworkOutput(unittest.TestCase):
    """Test network domain output writers."""

    def test_write_json(self):
        set_verbose_level(4)
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            nw_write_json(NETWORK_SUMMARY, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data['interfaces']), 2)
        finally:
            os.unlink(path)

    def test_write_json_filters_verbose(self):
        set_verbose_level(1)
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name
        try:
            nw_write_json(NETWORK_SUMMARY, path)
            with open(path) as f:
                data = json.load(f)
            self.assertTrue(len(data['interfaces']) >= 1)
        finally:
            os.unlink(path)

    def test_write_text(self):
        set_verbose_level(2)
        lines = []
        nw_write_text(NETWORK_SUMMARY, lines)
        text = '\n'.join(lines)
        self.assertIn('eth0', text)


if __name__ == '__main__':
    unittest.main()
