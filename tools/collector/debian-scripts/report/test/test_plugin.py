#!/usr/bin/env python3
# #######################################################################
#
# Copyright (c) 2022 -2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# #######################################################################
#
# This file contains the functions for the system info plugin algorithm.
#
# The system info plugin algorithm gathers top level system information,
# such at the build type, sw version, and more.
#
# #######################################################################
"""Tests for plugin.py — plugin file parsing and validation."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugin import Plugin  # noqa: E402


class TestPluginFileParsing(unittest.TestCase):
    """Test parsing of plugin definition files."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_plugin(self, name, content):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_simple_algorithm_plugin(self):
        """Parse a simple single-line plugin."""
        path = self._write_plugin("heartbeat_loss", "algorithm=heartbeat_loss\n")  # noqa: E501
        p = Plugin(path)
        self.assertEqual(p.state['algorithm'], 'heartbeat_loss')
        self.assertEqual(p.state['hosts'], [])

    def test_substring_plugin(self):
        """Parse a substring plugin with all labels."""
        path = self._write_plugin("my_search", (
            "algorithm=substring\n"
            "files=var/log/mtcAgent.log,var/log/sm.log\n"
            "hosts=controllers\n"
            "substring=operation failed\n"
            "substring=Error : \n"
        ))
        p = Plugin(path)
        self.assertEqual(p.state['algorithm'], 'substring')
        self.assertEqual(p.state['files'], ['var/log/mtcAgent.log', 'var/log/sm.log'])  # noqa: E501
        self.assertEqual(p.state['hosts'], ['controllers'])
        self.assertEqual(len(p.state['substring']), 2)

    def test_alarm_plugin_with_excludes(self):
        """Parse alarm plugin with exclude lists."""
        path = self._write_plugin("alarm", (
            "algorithm=alarm\n"
            "alarm_exclude=400.,800.\n"
            "entity_exclude=subsystem=vim\n"
        ))
        p = Plugin(path)
        self.assertEqual(p.state['algorithm'], 'alarm')
        self.assertEqual(p.state['alarm_exclude'], ['400.', '800.'])
        self.assertEqual(p.state['entity_exclude'], ['subsystem=vim'])

    def test_comments_and_empty_lines_ignored(self):
        """Comments and empty lines should be skipped."""
        path = self._write_plugin("test", (
            "# This is a comment\n"
            "\n"
            "algorithm=heartbeat_loss\n"
            "# Another comment\n"
        ))
        p = Plugin(path)
        self.assertEqual(p.state['algorithm'], 'heartbeat_loss')

    def test_exclude_label(self):
        """Multiple exclude labels should accumulate."""
        path = self._write_plugin("test", (
            "algorithm=maintenance_errors\n"
            "exclude=task clear\n"
            "exclude=another exclude\n"
        ))
        p = Plugin(path)
        self.assertEqual(len(p.state['exclude']), 2)


class TestPluginValidation(unittest.TestCase):
    """Test plugin validation rules."""

    def test_unknown_algorithm_rejected(self):
        """Unknown algorithm should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            Plugin(opts={
                'algorithm': 'fake_algorithm',
                'files': [], 'hosts': [], 'substring': [],
                'exclude': [], 'alarm_exclude': [],
                'entity_exclude': [], 'start': None, 'end': None,
            })
        self.assertIn('unsupported', str(ctx.exception))

    def test_substring_requires_hosts(self):
        """Substring without hosts should raise ValueError."""
        with self.assertRaises(ValueError):
            Plugin(opts={
                'algorithm': 'substring',
                'files': ['var/log/test.log'], 'hosts': [],
                'substring': ['test'], 'exclude': [],
                'alarm_exclude': [], 'entity_exclude': [],
                'start': None, 'end': None,
            })

    def test_substring_requires_files(self):
        """Substring without files should raise ValueError."""
        with self.assertRaises(ValueError):
            Plugin(opts={
                'algorithm': 'substring',
                'files': [], 'hosts': ['controllers'],
                'substring': ['test'], 'exclude': [],
                'alarm_exclude': [], 'entity_exclude': [],
                'start': None, 'end': None,
            })

    def test_substring_requires_substring(self):
        """Substring without substring patterns should raise ValueError."""
        with self.assertRaises(ValueError):
            Plugin(opts={
                'algorithm': 'substring',
                'files': ['var/log/test.log'], 'hosts': ['controllers'],
                'substring': [], 'exclude': [],
                'alarm_exclude': [], 'entity_exclude': [],
                'start': None, 'end': None,
            })

    def test_non_substring_rejects_hosts(self):
        """Non-substring algorithms should reject hosts label."""
        with self.assertRaises(ValueError):
            Plugin(opts={
                'algorithm': 'heartbeat_loss',
                'files': [], 'hosts': ['controllers'],
                'substring': [], 'exclude': [],
                'alarm_exclude': [], 'entity_exclude': [],
                'start': None, 'end': None,
            })

    def test_valid_host_values(self):
        """Only controllers, workers, storages, all are valid hosts."""
        # Valid
        p = Plugin(opts={
            'algorithm': 'substring',
            'files': ['var/log/test.log'], 'hosts': ['all'],
            'substring': ['test'], 'exclude': [],
            'alarm_exclude': [], 'entity_exclude': [],
            'start': None, 'end': None,
        })
        self.assertEqual(p.state['hosts'], ['all'])

    def test_invalid_host_value(self):
        """Invalid host value should raise ValueError."""
        with self.assertRaises(ValueError):
            Plugin(opts={
                'algorithm': 'substring',
                'files': ['var/log/test.log'], 'hosts': ['invalid_host'],
                'substring': ['test'], 'exclude': [],
                'alarm_exclude': [], 'entity_exclude': [],
                'start': None, 'end': None,
            })

    def test_all_known_algorithms_accepted(self):
        """All known algorithm names should be accepted."""
        import algorithms
        known = [
            algorithms.ALARM, algorithms.HEARTBEAT_LOSS,
            algorithms.SWACT_ACTIVITY, algorithms.PUPPET_ERRORS,
            algorithms.PROCESS_FAILURES, algorithms.DAEMON_FAILURES,
            algorithms.STATE_CHANGES, algorithms.SYSTEM_INFO,
            algorithms.MAINTENANCE_ERR,
        ]
        for alg in known:
            p = Plugin(opts={
                'algorithm': alg,
                'files': [], 'hosts': [], 'substring': [],
                'exclude': [], 'alarm_exclude': [],
                'entity_exclude': [], 'start': None, 'end': None,
            })
            self.assertEqual(p.state['algorithm'], alg)


if __name__ == '__main__':
    unittest.main(verbosity=2)
