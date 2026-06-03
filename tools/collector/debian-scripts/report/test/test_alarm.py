#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the unit tests for the alarm algorithm.
#
#
########################################################################
"""Tests for the alarm algorithm (plugin_algs/alarm.py)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugin_algs.alarm import alarm  # noqa: E402


# FM database data line format (tab-separated, 11+ fields):
# 0:created_at 1:updated_at 2:deleted_at 3:id 4:uuid
# 5:alarm_id 6:action 7:entity_type_id 8:entity_instance_id
# 9:alarm_date 10:severity
COPY_HEADER = "COPY public.event_log (created_at, updated_at) FROM stdin;\n"
END_MARKER = "\\.\n"


def make_entry(alarm_id, action, entity_id, date, severity, idx=1):
    """Build a tab-separated FM database entry line."""
    return (f"2025-01-01\t\\N\t\\N\t{idx}\tuuid{idx}\t"
            f"{alarm_id}\t{action}\thost\t{entity_id}\t{date}\t{severity}\n")


class TestAlarmParsing(unittest.TestCase):
    """Test FM database alarm parsing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.host_dir = os.path.join(self.temp_dir, "controller-0")
        os.makedirs(os.path.join(self.host_dir, "var", "extra", "database"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_fm_db(self, entries):
        path = os.path.join(self.host_dir, "var", "extra", "database",
                            "fm.db.sql.txt")
        with open(path, 'w') as f:
            f.write(COPY_HEADER)
            for entry in entries:
                f.write(entry)
            f.write(END_MARKER)

    def test_no_fm_database(self):
        """Should return None, None if fm.db.sql.txt doesn't exist."""
        shutil.rmtree(os.path.join(self.host_dir, "var", "extra", "database"))
        alarms, logs = alarm(self.host_dir,
                             "2025-01-01T00:00:00", "2025-12-31T00:00:00")
        self.assertIsNone(alarms)
        self.assertIsNone(logs)

    def test_parses_alarm_set_clear(self):
        """Should parse alarm set and clear events."""
        self._write_fm_db([
            make_entry("200.001", "set", "host=controller-0",
                       "2025-06-01 10:00:00", "warning", 1),
            make_entry("200.001", "clear", "host=controller-0",
                       "2025-06-01 11:00:00", "warning", 2),
        ])
        alarms, logs = alarm(self.host_dir,
                             "2025-01-01T00:00:00", "2025-12-31T00:00:00")
        self.assertIsNotNone(alarms)
        self.assertEqual(len(alarms), 1)

    def test_alarm_exclude(self):
        """Should exclude alarms matching alarm_exclude patterns."""
        self._write_fm_db([
            make_entry("200.001", "set", "host=controller-0",
                       "2025-06-01 10:00:00", "warning", 1),
            make_entry("400.001", "set", "host=controller-0",
                       "2025-06-01 10:00:00", "major", 2),
        ])
        alarms, logs = alarm(self.host_dir,
                             "2025-01-01T00:00:00", "2025-12-31T00:00:00",
                             alarm_exclude=["400."])
        self.assertEqual(len(alarms), 1)
        self.assertTrue(any("200.001" in k for k in alarms.keys()))

    def test_entity_exclude(self):
        """Should exclude alarms matching entity_exclude patterns."""
        self._write_fm_db([
            make_entry("200.001", "set", "host=controller-0",
                       "2025-06-01 10:00:00", "warning", 1),
            make_entry("200.001", "set", "subsystem=vim",
                       "2025-06-01 10:00:00", "warning", 2),
        ])
        alarms, logs = alarm(self.host_dir,
                             "2025-01-01T00:00:00", "2025-12-31T00:00:00",
                             entity_exclude=["subsystem=vim"])
        self.assertEqual(len(alarms), 1)
        self.assertTrue(any("controller-0" in k for k in alarms.keys()))

    def test_log_events_separated(self):
        """Log events should go to logs dict, not alarms."""
        self._write_fm_db([
            make_entry("200.001", "log", "host=controller-0",
                       "2025-06-01 10:00:00", "warning", 1),
            make_entry("200.001", "set", "host=controller-0",
                       "2025-06-01 11:00:00", "warning", 2),
        ])
        alarms, logs = alarm(self.host_dir,
                             "2025-01-01T00:00:00", "2025-12-31T00:00:00")
        self.assertEqual(len(alarms), 1)
        self.assertEqual(len(logs), 1)

    def test_date_range_filter(self):
        """Should only include alarms within date range."""
        self._write_fm_db([
            make_entry("200.001", "set", "host=controller-0",
                       "2025-01-01 10:00:00", "warning", 1),
            make_entry("200.002", "set", "host=controller-0",
                       "2025-06-01 10:00:00", "warning", 2),
            make_entry("200.003", "set", "host=controller-0",
                       "2025-12-01 10:00:00", "warning", 3),
        ])
        alarms, logs = alarm(self.host_dir,
                             "2025-05-01T00:00:00", "2025-07-01T00:00:00")
        self.assertEqual(len(alarms), 1)
        self.assertTrue(any("200.002" in k for k in alarms.keys()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
