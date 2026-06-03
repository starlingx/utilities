#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for the correlator algorithm.
#
########################################################################
"""Tests for the correlator (correlator.py)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from correlator import Correlator  # noqa: E402


class TestCorrelatorRun(unittest.TestCase):
    """Test the correlator's run() method."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_plugin_file(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def test_empty_plugin_dir(self):
        """Correlator with no plugin output should return empty results."""
        c = Correlator(self.temp_dir)
        failures, events, alarms, state_changes = c.run("all")
        self.assertEqual(failures, [])
        self.assertEqual(events, [])
        self.assertEqual(alarms, [])
        self.assertEqual(state_changes, [])

    def test_state_changes_enabled(self):
        """Should detect host enabled state changes."""
        self._write_plugin_file("state_changes", [
            "2025-01-01T10:00:00.000 controller-0 mtcAgent Info : controller-0 is ENABLED",  # noqa: E501
            "2025-01-01T11:00:00.000 controller-0 mtcAgent Info : controller-1 is ENABLED",  # noqa: E501
        ])
        c = Correlator(self.temp_dir)
        _, _, _, state_changes = c.run("all")
        self.assertEqual(len(state_changes), 2)
        self.assertIn("controller-0", state_changes[0])
        self.assertIn("enabled", state_changes[0])

    def test_state_changes_disabled(self):
        """Should detect host disabled state changes."""
        self._write_plugin_file("state_changes", [
            "2025-01-01T10:00:00.000 controller-0 mtcAgent Info : controller-1 unlocked-disabled",  # noqa: E501
        ])
        c = Correlator(self.temp_dir)
        _, _, _, state_changes = c.run("all")
        self.assertEqual(len(state_changes), 1)
        self.assertIn("disabled", state_changes[0])

    def test_state_changes_hostname_filter(self):
        """Should filter state changes by hostname."""
        self._write_plugin_file("state_changes", [
            "2025-01-01T10:00:00.000 controller-0 mtcAgent Info : controller-0 is ENABLED",  # noqa: E501
            "2025-01-01T11:00:00.000 controller-0 mtcAgent Info : controller-1 is ENABLED",  # noqa: E501
        ])
        c = Correlator(self.temp_dir)
        _, _, _, state_changes = c.run("controller-0")
        self.assertEqual(len(state_changes), 1)
        self.assertIn("controller-0", state_changes[0])

    def test_events_force_failed(self):
        """Should detect 'force failed by SM' events."""
        self._write_plugin_file("maintenance_errors", [
            "2025-01-01T10:00:00.000 controller-0 mtcAgent"  # noqa: E501
            " Error : controller-1 is being force failed by SM",
        ])
        c = Correlator(self.temp_dir)
        _, events, _, _ = c.run("all")
        self.assertEqual(len(events), 1)
        self.assertIn("force failed by SM", events[0])

    def test_events_graceful_recovery_failed(self):
        """Should detect graceful recovery failed events."""
        self._write_plugin_file("maintenance_errors", [
            "2025-01-01T10:00:00.000 controller-0 mtcAgent Info : compute-0 Task: Graceful Recovery Failed",  # noqa: E501
        ])
        c = Correlator(self.temp_dir)
        _, events, _, _ = c.run("all")
        self.assertEqual(len(events), 1)
        self.assertIn("graceful recovery failed", events[0])

    def test_alarms_set_and_clear(self):
        """Should count alarm set and clear events."""
        self._write_plugin_file("alarm", [
            "200.001 host=controller-0 warning:",
            "   2025-01-01 10:00:00 set",
            "   2025-01-01 11:00:00 clear",
            "   2025-01-01 12:00:00 set",
        ])
        c = Correlator(self.temp_dir)
        _, _, alarms, _ = c.run("all")
        self.assertEqual(len(alarms), 1)
        self.assertIn("set: 2", alarms[0])
        self.assertIn("clear: 1", alarms[0])

    def test_alarms_hostname_filter(self):
        """Should filter alarms by hostname."""
        self._write_plugin_file("alarm", [
            "200.001 host=controller-0 warning:",
            "   2025-01-01 10:00:00 set",
            "200.001 host=controller-1 warning:",
            "   2025-01-01 10:00:00 set",
        ])
        c = Correlator(self.temp_dir)
        _, _, alarms, _ = c.run("controller-0")
        self.assertEqual(len(alarms), 1)
        self.assertIn("controller-0", alarms[0])


class TestCorrelatorSwact(unittest.TestCase):
    """Test uncontrolled swact detection."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_plugin_file(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def test_no_swact_activity_file(self):
        """No swact_activity file should produce no failures."""
        c = Correlator(self.temp_dir)
        failures, _, _, _ = c.run("all")
        self.assertEqual(failures, [])

    def test_controlled_swact_not_failure(self):
        """Controlled swacts should not appear as failures."""
        self._write_plugin_file("swact_activity", [
            "2025-01-01T10:00:00.000 controller-0 sm: Swact has started, host will be standby",  # noqa: E501
            "2025-01-01T10:00:30.000 controller-0 sm: Swact update: controller-0 is now standby",  # noqa: E501
        ])
        c = Correlator(self.temp_dir)
        failures, _, _, _ = c.run("all")
        self.assertEqual(failures, [])


class TestCorrelatorMtcErrors(unittest.TestCase):
    """Test maintenance error correlation."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_plugin_file(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def test_no_maintenance_errors_file(self):
        """No maintenance_errors file should produce no failures."""
        c = Correlator(self.temp_dir)
        failures, _, _, _ = c.run("all")
        self.assertEqual(failures, [])

    def test_goenable_failure_detected(self):
        """Should detect go-enable test failures."""
        self._write_plugin_file("maintenance_errors", [
            "2025-01-01T10:00:00.000 controller-0 mtcAgent Error : compute-0 got GOENABLED Failed",  # noqa: E501
            "2025-01-01T10:00:05.000 compute-0 mtcClient --- Error : FAILED: /etc/goenabled.d/test.sh (1)",  # noqa: E501
            "2025-01-01T10:00:10.000 controller-0 mtcAgent Info : compute-0 Task: In-Test Failure, threshold reached",  # noqa: E501
        ])
        c = Correlator(self.temp_dir)
        failures, _, _, _ = c.run("all")
        self.assertEqual(len(failures), 1)
        self.assertIn("Go-enable test failure", failures[0])
        self.assertIn("compute-0", failures[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
