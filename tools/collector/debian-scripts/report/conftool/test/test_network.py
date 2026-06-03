#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for the network domain — parsing and summary building.
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

from domains.network.config import build_summary      # noqa: E402
from domains.network.config import load_config        # noqa: E402
from domains.network.config import parse_ip_link      # noqa: E402
from domains.network.config import parse_ip_route_v4  # noqa: E402
from domains.network.config import parse_netstat_listeners  # noqa: E402
from host_utils import set_verbose_level    # noqa: E402
from mock_factory import create_bundle       # noqa: E402
from mock_factory import NETWORK_IP_LINK     # noqa: E402
from mock_factory import NETWORK_IP_ROUTE    # noqa: E402


class TestParseIpLink(unittest.TestCase):
    """Test ip link output parsing."""

    def test_parses_interfaces(self):
        config = {}
        parse_ip_link(NETWORK_IP_LINK, config)
        ifaces = config['interfaces']
        names = [i['name'] for i in ifaces]
        self.assertIn('eno12399', names)
        self.assertIn('vlan41', names)
        self.assertIn('vlan113', names)
        self.assertEqual(len(ifaces), 5)

    def test_pod_interfaces_separated(self):
        config = {}
        parse_ip_link(NETWORK_IP_LINK, config)
        pod_names = [i['name'] for i in config['pod_interfaces']]
        self.assertIn('cali3a818d1e072', pod_names)
        self.assertEqual(len(config['pod_interfaces']), 1)

    def test_vlan_parent_detected(self):
        config = {}
        parse_ip_link(NETWORK_IP_LINK, config)
        vlan = next(i for i in config['interfaces']
                    if i['name'] == 'vlan113')
        self.assertEqual(vlan['parent'], 'eno12399')

    def test_traffic_counters(self):
        config = {}
        parse_ip_link(NETWORK_IP_LINK, config)
        eno = next(i for i in config['interfaces']
                   if i['name'] == 'eno12399')
        self.assertEqual(eno['rx_bytes'], 1629705965)
        self.assertEqual(eno['tx_bytes'], 1498180265)

    def test_altname_detected(self):
        config = {}
        parse_ip_link(NETWORK_IP_LINK, config)
        eno = next(i for i in config['interfaces']
                   if i['name'] == 'eno12399')
        self.assertEqual(eno['altname'], 'enp51s0f0')


class TestParseIpRoute(unittest.TestCase):
    """Test ip route output parsing."""

    def test_default_gateway(self):
        config = {}
        parse_ip_route_v4(NETWORK_IP_ROUTE, config)
        gw = config['routing']['default_gateway']
        self.assertEqual(gw['ip'], '10.64.13.1')
        self.assertEqual(gw['dev'], 'vlan113')

    def test_connected_routes(self):
        config = {}
        parse_ip_route_v4(NETWORK_IP_ROUTE, config)
        connected = config['routing']['connected']
        subnets = [r['subnet'] for r in connected]
        self.assertIn('10.81.81.0/24', subnets)
        self.assertIn('192.168.206.0/24', subnets)

    def test_pod_cidrs(self):
        config = {}
        parse_ip_route_v4(NETWORK_IP_ROUTE, config)
        self.assertIn('172.16.192.64/26',
                      config['routing']['pod_cidrs'])

    def test_bgp_routes(self):
        config = {}
        parse_ip_route_v4(NETWORK_IP_ROUTE, config)
        bgp = config['routing']['bgp_routes']
        self.assertEqual(len(bgp), 3)
        self.assertEqual(bgp[0]['subnet'], '172.16.103.128/26')
        self.assertEqual(bgp[0]['via'], '192.168.206.150')


class TestParseNetstatListeners(unittest.TestCase):
    """Test netstat listener parsing."""

    def test_listen_detected(self):
        text = (
            "tcp  0  0  0.0.0.0:22  0.0.0.0:*  LISTEN  1234/sshd\n"
            "tcp  0  0  10.10.10.2:6443  0.0.0.0:*  LISTEN  "
            "5678/kube-apiserver\n"
            "tcp  0  0  10.10.10.2:6443  10.10.10.3:45678  "
            "ESTABLISHED  5678/kube-apiserver\n"
        )
        config = {}
        parse_netstat_listeners(text, config)
        services = config['services']
        self.assertEqual(len(services), 2)

    def test_connection_states_counted(self):
        text = (
            "tcp  0  0  0.0.0.0:22  0.0.0.0:*  LISTEN  1/sshd\n"
            "tcp  0  0  1.1.1.1:22  2.2.2.2:111  ESTABLISHED  1/sshd\n"
            "tcp  0  0  1.1.1.1:22  3.3.3.3:222  ESTABLISHED  1/sshd\n"
            "tcp  0  0  1.1.1.1:22  4.4.4.4:333  TIME_WAIT  1/sshd\n"
        )
        config = {}
        parse_netstat_listeners(text, config)
        self.assertEqual(config['connection_states']['ESTABLISHED'], 2)
        self.assertEqual(config['connection_states']['TIME_WAIT'], 1)


class TestNetworkLoadAndSummary(unittest.TestCase):
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
        self.assertIn('interfaces', summary)
        self.assertIn('routing', summary)
        self.assertIn('host', summary)
        self.assertEqual(summary['host']['personality'], 'controller')

    def test_interface_roles_assigned(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        networks = summary.get('networks', {})
        self.assertIn('mgmt', networks)
        self.assertIn('oam', networks)
        self.assertIn('cluster_host', networks)

    def test_cross_checks_present(self):
        config = {'hostname': 'controller-0',
                  'collected': '20250211.212225', 'warnings': []}
        load_config(self._get_host_dir(), config)
        summary = build_summary(config)
        self.assertIn('cross_check', summary)
        self.assertTrue(len(summary['cross_check']) > 0)


if __name__ == '__main__':
    unittest.main()
