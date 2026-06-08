#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import base64
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec
from importlib.util import spec_from_file_location
import os
import unittest
import unittest.mock
from unittest.mock import mock_open
from unittest.mock import patch

import requests as _requests

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../onsite-restore/scripts/90-trigger-onsite-restore",
)
TEST_CONFIG_DIR = "/home/sysadmin/enroll-config/20260507-120000"
TEST_OLD_CONFIG_DIR = "/home/sysadmin/enroll-config/20260507-110000"


class TestTriggerOnsiteRestore(unittest.TestCase):
    """Test cases for the 90-trigger-onsite-restore script."""

    @classmethod
    def setUpClass(cls):
        cls.patches = [
            patch("glob.glob", return_value=[]),
            patch("builtins.open", mock_open()),
            patch("sys.exit"),
        ]
        for p in cls.patches:
            p.start()

        spec = spec_from_file_location(
            "trigger_onsite_restore",
            SCRIPT_PATH,
            loader=SourceFileLoader("trigger_onsite_restore", SCRIPT_PATH),
        )
        cls.module = module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()

    def setUp(self):
        self.mock_glob = patch("glob.glob").start()
        self.mock_isdir = patch("os.path.isdir").start()
        self.mock_open_file = patch("builtins.open", mock_open()).start()
        self.mock_print = patch("builtins.print").start()
        self.mock_exit = patch("sys.exit").start()
        self.mock_exists = patch("os.path.exists").start()
        self.mock_requests_patch = patch("requests.patch").start()
        self.mock_isdir.return_value = True
        self.mock_exists.return_value = True
        self.mock_glob.return_value = [TEST_CONFIG_DIR]

    def tearDown(self):
        patch.stopall()

    def _build_trigger(self):
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap-values.yaml"
        config.systemcontroller_oam = "10.10.10.2"
        config.config_dir = TEST_CONFIG_DIR
        return self.module.OnsiteRestoreTrigger(config, "token123")

    def test_load_restore_config_remote(self):
        """Loads name, sysadmin_password, local_only=false, timeout."""
        trigger = self._build_trigger()
        self.mock_glob.side_effect = [
            [f"{TEST_CONFIG_DIR}/restore-values.yaml"],
        ]
        # extract_yaml is called once per key
        with patch.object(
            trigger,
            "extract_yaml",
            side_effect=[
                "subcloud1",   # name
                "syspass",     # sysadmin_password
                False,         # local_only
                3600,          # restore_timeout
            ],
        ):
            trigger.load_restore_config()

        self.assertEqual(trigger.subcloud_name, "subcloud1")
        self.assertEqual(trigger.sysadmin_password, "syspass")
        self.assertFalse(trigger.local_only)
        self.assertEqual(trigger.restore_timeout, 3600)

    def test_load_restore_config_local_only(self):
        """local_only=true is honored."""
        trigger = self._build_trigger()
        self.mock_glob.side_effect = [
            [f"{TEST_CONFIG_DIR}/restore-values.yaml"],
        ]
        with patch.object(
            trigger,
            "extract_yaml",
            side_effect=["subcloud1", "syspass", True, None],
        ):
            trigger.load_restore_config()

        self.assertTrue(trigger.local_only)
        # restore_timeout falls back to default when None in YAML
        self.assertEqual(
            trigger.restore_timeout, self.module.DEFAULT_RESTORE_TIMEOUT
        )

    def test_trigger_restore_payload_remote(self):
        """PATCH carries on_site=true, local_only=false, b64 password."""
        trigger = self._build_trigger()
        trigger.subcloud_name = "subcloud1"
        trigger.sysadmin_password = "syspass"  # nosec B105
        trigger.local_only = False
        trigger.restore_timeout = 5400
        trigger.restore_values_file = f"{TEST_CONFIG_DIR}/restore-values.yaml"

        self.mock_requests_patch.return_value.json.return_value = {"id": 1}
        self.mock_requests_patch.return_value.content = b'{"id": 1}'
        self.mock_requests_patch.return_value.raise_for_status = lambda: None

        with patch("builtins.open", mock_open(read_data=b"yaml")):
            result = trigger.trigger_restore()

        self.assertEqual(result, {"id": 1})
        self.mock_requests_patch.assert_called_once()
        call_args, call_kwargs = self.mock_requests_patch.call_args
        url = call_args[0]
        self.assertIn("/v1.0/subcloud-backup?verb=restore", url)
        self.assertEqual(
            call_kwargs["headers"], {"X-Auth-Token": "token123"}
        )
        data = call_kwargs["data"]
        self.assertEqual(data["subcloud"], "subcloud1")
        self.assertEqual(data["on_site"], "true")
        self.assertEqual(data["local_only"], "false")
        self.assertEqual(
            data["sysadmin_password"],
            base64.b64encode(b"syspass").decode("utf-8"),
        )
        self.assertIn("restore_values", call_kwargs["files"])

    def test_trigger_restore_payload_local_only(self):
        """local_only=true sets the form field to 'true'."""
        trigger = self._build_trigger()
        trigger.subcloud_name = "subcloud1"
        trigger.sysadmin_password = "syspass"   # nosec B105
        trigger.local_only = True
        trigger.restore_timeout = 5400
        trigger.restore_values_file = f"{TEST_CONFIG_DIR}/restore-values.yaml"

        self.mock_requests_patch.return_value.json.return_value = {}
        self.mock_requests_patch.return_value.content = b""
        self.mock_requests_patch.return_value.raise_for_status = lambda: None

        with patch("builtins.open", mock_open(read_data=b"yaml")):
            trigger.trigger_restore()

        call_kwargs = self.mock_requests_patch.call_args[1]
        self.assertEqual(call_kwargs["data"]["local_only"], "true")

    def test_trigger_restore_url_ipv6(self):
        """IPv6 system controller address is bracketed in the URL."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap-values.yaml"
        config.systemcontroller_oam = "fd00::2"
        config.config_dir = TEST_CONFIG_DIR
        trigger = self.module.OnsiteRestoreTrigger(config, "token123")
        trigger.subcloud_name = "subcloud1"
        trigger.sysadmin_password = "syspass"  # nosec B105
        trigger.local_only = False
        trigger.restore_timeout = 5400
        trigger.restore_values_file = f"{TEST_CONFIG_DIR}/restore-values.yaml"

        self.mock_requests_patch.return_value.json.return_value = {}
        self.mock_requests_patch.return_value.content = b""
        self.mock_requests_patch.return_value.raise_for_status = lambda: None

        with patch("builtins.open", mock_open(read_data=b"yaml")):
            trigger.trigger_restore()

        url = self.mock_requests_patch.call_args[0][0]
        self.assertIn("https://[fd00::2]:8119", url)

    def test_write_status_file_remote(self):
        """Status file contains local_only=false only (no subcloud_name)."""
        trigger = self._build_trigger()
        trigger.subcloud_name = "subcloud1"
        trigger.local_only = False

        m = mock_open()
        with patch("builtins.open", m):
            trigger.write_status_file()

        m.assert_called_once_with(
            self.module.STATUS_FILE, "w", encoding="utf-8"
        )
        handle = m()
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertIn("local_only=false", written)
        self.assertNotIn("subcloud_name", written)

    def test_write_status_file_local(self):
        """Status file lists local_only=true."""
        trigger = self._build_trigger()
        trigger.subcloud_name = "subcloud1"
        trigger.local_only = True

        m = mock_open()
        with patch("builtins.open", m):
            trigger.write_status_file()

        handle = m()
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertIn("local_only=true", written)

    def test_write_status_file_no_subcloud_name(self):
        """Status file does not include subcloud_name."""
        trigger = self._build_trigger()
        trigger.subcloud_name = "subcloud1"
        trigger.local_only = False

        m = mock_open()
        with patch("builtins.open", m):
            trigger.write_status_file()

        handle = m()
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        self.assertNotIn("subcloud_name", written)

    def test_missing_bootstrap_values_exits(self):
        """sys.exit(1) is called when bootstrap-values file is absent."""
        trigger = self._build_trigger()
        self.mock_glob.return_value = []
        trigger.load_common_files()
        self.mock_exit.assert_called_with(1)

    def test_missing_restore_values_exits(self):
        """sys.exit(1) is called when restore-values file is absent."""
        trigger = self._build_trigger()
        self.mock_glob.return_value = []
        trigger.load_restore_config()
        self.mock_exit.assert_called_with(1)

    def test_http_error_exits_without_writing_status_file(self):
        """4xx/5xx from API calls sys.exit(1) before write_status_file runs."""

        trigger = self._build_trigger()
        trigger.subcloud_name = "subcloud1"
        trigger.sysadmin_password = "syspass"  # nosec B105
        trigger.local_only = False
        trigger.restore_timeout = 5400
        trigger.restore_values_file = f"{TEST_CONFIG_DIR}/restore-values.yaml"

        mock_resp = unittest.mock.MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        self.mock_requests_patch.side_effect = _requests.exceptions.HTTPError(
            response=mock_resp
        )

        with patch("builtins.open", mock_open(read_data=b"yaml")):
            trigger.trigger_restore()
        self.mock_exit.assert_called_with(1)


if __name__ == "__main__":
    unittest.main()
