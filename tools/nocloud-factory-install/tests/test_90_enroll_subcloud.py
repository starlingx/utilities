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
from unittest.mock import mock_open
from unittest.mock import patch

from nocloud_utils.utils import log_error
from nocloud_utils.utils import log_info

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../onsite-enrollment/scripts/90-enroll-subcloud",
)
TEST_CONFIG_DIR = "/home/sysadmin/enroll-config/20260115-120000"
TEST_OLD_CONFIG_DIR = "/home/sysadmin/enroll-config/20260115-110000"


class TestEnrollSubcloud(unittest.TestCase):
    """Test cases for the 90-enroll-subcloud script."""

    @classmethod
    def setUpClass(cls):
        # Mock everything before loading the module
        cls.patches = [
            patch("glob.glob", return_value=[]),
            patch("builtins.open", mock_open()),
            patch("sys.exit"),
        ]
        for p in cls.patches:
            p.start()

        spec = spec_from_file_location(
            "enroll_subcloud",
            SCRIPT_PATH,
            loader=SourceFileLoader("enroll_subcloud", SCRIPT_PATH),
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
        self.mock_requests_head = patch("requests.head").start()
        self.mock_requests_post = patch("requests.post").start()
        self.mock_subprocess = patch("subprocess.run").start()
        self.mock_isdir.return_value = True
        self.mock_exists.return_value = True
        self.mock_glob.return_value = [TEST_CONFIG_DIR]
        self.base = self.module.BaseClass()

    def tearDown(self):
        patch.stopall()

    def test_base_find_file(self):
        """Test finding a file matching a pattern."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [f"{TEST_CONFIG_DIR}/test.yaml"],
        ]
        base = self.module.BaseClass()
        result = base.find_file_in_config("*test*")
        self.assertEqual(result, f"{TEST_CONFIG_DIR}/test.yaml")

    def test_base_find_file_not_found(self):
        """Test finding a file that doesn't exist."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [],
        ]
        base = self.module.BaseClass()
        result = base.find_file_in_config("*nonexistent*")
        self.assertIsNone(result)

    def test_base_extract_yaml_value(self):
        """Test extracting a value from a YAML file."""
        yaml_content = "name: subcloud1\n"
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            result = self.base.extract_yaml("/fake/path", "name")
        self.assertEqual(result, "subcloud1")

    def test_base_extract_yaml_value_not_found(self):
        """Test extracting a missing key from a YAML file."""
        yaml_content = "other_key: value\n"
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            result = self.base.extract_yaml("/fake/path", "missing_key")
        self.assertIsNone(result)

    def test_extract_systemcontroller_oam(self):
        """Test extracting systemcontroller OAM address."""
        yaml_content = "systemcontroller_oam_address: 10.10.10.1\n"
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            result = self.base.extract_yaml(
                "/fake/path", "systemcontroller_oam_address"
            )
        self.assertEqual(result, "10.10.10.1")

    def test_extract_credentials(self):
        """Test extracting admin password from YAML."""
        yaml_content = "admin_password: secret\n"
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            password = self.base.extract_yaml(
                "/fake/path", "admin_password"
            )
        self.assertEqual(password, "secret")

    def test_base_log_info(self):
        """Test logging an info message."""
        with patch("builtins.print") as mock_print:
            log_info("test message")
            mock_print.assert_called_once()
            self.assertIn("test message", str(mock_print.call_args))

    def test_base_log_error(self):
        """Test logging an error message and exiting."""
        with patch("builtins.print") as mock_print, \
             patch("sys.exit") as mock_exit:
            log_error("error message")
            mock_print.assert_called_once()
            mock_exit.assert_called_once_with(1)
            self.assertIn("error message", str(mock_print.call_args))

    def test_subcloud_setup_get_ssl_ca_cert_path_exists(self):
        """Test getting SSL CA certificate path when it exists."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [f"{TEST_CONFIG_DIR}/bootstrap.yaml"],
        ]
        setup = self.module.SubcloudSetup()
        yaml_content = (
            "ssl_ca_cert: cert.pem\nsystemcontroller_oam_address: 10.10.10.1\n"
        )
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            setup.load_common_files()
            self.mock_exists.return_value = True
            result = setup.get_ssl_ca_cert_path()
        self.assertEqual(result, f"{TEST_CONFIG_DIR}/cert.pem")

    def test_subcloud_setup_get_ssl_ca_cert_path_none(self):
        """Test getting SSL CA certificate path when not configured."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [f"{TEST_CONFIG_DIR}/bootstrap.yaml"],
        ]
        setup = self.module.SubcloudSetup()
        yaml_content = (
            "other_key: value\nsystemcontroller_oam_address: 10.10.10.1\n"
        )
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            setup.load_common_files()
            result = setup.get_ssl_ca_cert_path()
        self.assertIsNone(result)

    def test_central_cloud_auth_sync_time_from_remote(self):
        """Test syncing time from remote system controller."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.1"
        config.config_dir = TEST_CONFIG_DIR
        auth = self.module.CentralCloudAuth(config)
        self.mock_requests_head.return_value.headers = {
            "Date": "Mon, 01 Jan 2026 12:00:00 GMT"
        }
        with patch("time.monotonic", return_value=0):
            auth.sync_time_from_remote()
        self.mock_requests_head.assert_called_once()
        self.mock_subprocess.assert_called()

    def test_central_cloud_auth_get_keystone_auth_token(self):
        """Test getting Keystone authentication token."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.1"
        config.config_dir = TEST_CONFIG_DIR
        auth = self.module.CentralCloudAuth(config)
        auth.admin_password = "password"  # nosec B105
        self.mock_requests_post.return_value.headers = {
            "X-Subject-Token": "token123"
        }
        self.mock_requests_post.return_value.raise_for_status = lambda: None
        result = auth.get_keystone_auth_token()
        self.assertEqual(result, "token123")
        self.assertEqual(auth.auth_token, "token123")

    def test_base_load_common_files(self):
        """Test loading common configuration files."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [f"{TEST_CONFIG_DIR}/bootstrap.yaml"],
        ]
        base = self.module.BaseClass()
        yaml_content = "systemcontroller_oam_address: 10.10.10.1\n"
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            base.load_common_files()
        self.assertEqual(
            base.bootstrap_values, f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        )
        self.assertEqual(base.systemcontroller_oam, "10.10.10.1")

    def test_subcloud_setup_install_ssl_ca(self):
        """Test installing SSL CA certificate."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [f"{TEST_CONFIG_DIR}/bootstrap.yaml"],
        ]
        setup = self.module.SubcloudSetup()
        yaml_content = (
            "ssl_ca_cert: cert.pem\nsystemcontroller_oam_address: 10.10.10.1\n"
        )
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            setup.load_common_files()
            self.mock_exists.return_value = True
            setup.install_ssl_ca()
        self.mock_subprocess.assert_called_once()

    def test_subcloud_setup_install_ssl_ca_no_cert(self):
        """Test installing SSL CA when no certificate is configured."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [f"{TEST_CONFIG_DIR}/bootstrap.yaml"],
        ]
        setup = self.module.SubcloudSetup()
        yaml_content = (
            "other_key: value\nsystemcontroller_oam_address: 10.10.10.1\n"
        )
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            setup.load_common_files()
            setup.install_ssl_ca()
        self.mock_subprocess.assert_not_called()

    def test_systemcontroller_url_ipv4(self):
        """Test system controller URL formatting for IPv4."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.1"
        config.config_dir = TEST_CONFIG_DIR
        base = self.module.BaseClass(config)
        self.assertEqual(base.systemcontroller_url, "https://10.10.10.1")

    def test_systemcontroller_url_ipv6(self):
        """Test system controller URL formatting for IPv6."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "fd00::1"
        config.config_dir = TEST_CONFIG_DIR
        base = self.module.BaseClass(config)
        self.assertEqual(base.systemcontroller_url, "https://[fd00::1]")

    def test_sync_time_timeout(self):
        """Test syncing time when connection times out."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.1"
        config.config_dir = TEST_CONFIG_DIR
        auth = self.module.CentralCloudAuth(config)
        # Simulate exception to trigger retry logic
        self.mock_requests_head.side_effect = Exception("Connection failed")
        # Simulate timeout by making monotonic return values that exceed timeout
        with patch("time.monotonic", side_effect=[0, 600]), \
             patch("time.sleep"), \
             patch("sys.exit") as mock_exit:
            auth.sync_time_from_remote()
            mock_exit.assert_called_once_with(1)

    def test_sync_time_small_diff(self):
        """Test syncing time when time difference is small."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.1"
        config.config_dir = TEST_CONFIG_DIR
        auth = self.module.CentralCloudAuth(config)
        # Set Date header to a time within 20 seconds of current time
        self.mock_requests_head.return_value.headers = {
            "Date": "Mon, 01 Jan 2026 12:00:00 GMT"
        }
        with patch("time.monotonic", return_value=0), \
             patch("time.time", return_value=1767268810):  # 10 seconds diff
            auth.sync_time_from_remote()
        # Should not call subprocess when diff is <= 20 seconds
        self.mock_subprocess.assert_not_called()

    def test_subcloud_setup_execute(self):
        """Test executing subcloud setup."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [f"{TEST_CONFIG_DIR}/bootstrap.yaml"],
        ]
        setup = self.module.SubcloudSetup()
        yaml_content = (
            "ssl_ca_cert: cert.pem\nsystemcontroller_oam_address: 10.10.10.1\n"
        )
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            self.mock_exists.return_value = True
            setup.execute()
        self.mock_subprocess.assert_called_once()

    def test_central_cloud_auth_load_config_values(self):
        """Test loading configuration values for authentication."""
        self.mock_glob.side_effect = [
            [TEST_OLD_CONFIG_DIR, TEST_CONFIG_DIR],
            [f"{TEST_CONFIG_DIR}/bootstrap.yaml"],
        ]
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.1"
        config.config_dir = TEST_CONFIG_DIR
        auth = self.module.CentralCloudAuth(config)
        yaml_content = (
            "systemcontroller_oam_address: 10.10.10.1\nadmin_password: pass\n"
        )
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            auth.load_config_values()
        self.assertEqual(auth.admin_password, "pass")

    def test_subcloud_add_without_deploy_config(self):
        """Test adding subcloud without deploy configuration."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.1"
        config.config_dir = TEST_CONFIG_DIR
        subcloud_enroll = self.module.SubcloudEnroll(config, "token123")
        self.mock_glob.side_effect = [
            [f"{TEST_CONFIG_DIR}/install.yaml"],
            [],
        ]
        yaml_content = (
            "systemcontroller_oam_address: 10.10.10.1\n"
            "name: subcloud1\n"
            "sysadmin_password: syspass\n"
        )
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            subcloud_enroll.load_subcloud_config()
        self.assertEqual(
            subcloud_enroll.install_values, f"{TEST_CONFIG_DIR}/install.yaml"
        )
        self.assertEqual(subcloud_enroll.subcloud_name, "subcloud1")
        self.assertEqual(subcloud_enroll.sysadmin_password, "syspass")
        self.assertIsNone(subcloud_enroll.deploy_config)

    def test_subcloud_add_with_deploy_config(self):
        """Test adding subcloud with deploy configuration."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.1"
        config.config_dir = TEST_CONFIG_DIR
        subcloud_enroll = self.module.SubcloudEnroll(config, "token123")
        self.mock_glob.side_effect = [
            [f"{TEST_CONFIG_DIR}/install.yaml"],
            [f"{TEST_CONFIG_DIR}/deploy.yaml"],
        ]
        yaml_content = (
            "systemcontroller_oam_address: 10.10.10.1\n"
            "name: subcloud1\n"
            "external_oam_floating_address: 10.10.10.5\n"
            "sysadmin_password: syspass\n"
        )
        m = mock_open(read_data=yaml_content)
        self.mock_requests_post.return_value.json.return_value = {"id": 1}
        self.mock_requests_post.return_value.raise_for_status = lambda: None
        with patch("builtins.open", m):
            subcloud_enroll.load_subcloud_config()
            result = subcloud_enroll.enroll_subcloud()
        self.assertEqual(
            subcloud_enroll.deploy_config, f"{TEST_CONFIG_DIR}/deploy.yaml"
        )
        self.assertEqual(result, {"id": 1})
        call_kwargs = self.mock_requests_post.call_args[1]
        expected_sysadmin = base64.b64encode(b"syspass").decode("utf-8")
        self.assertEqual(
            call_kwargs["data"]["sysadmin_password"], expected_sysadmin
        )
        self.assertNotIn("bmc_password", call_kwargs["data"])

    def test_subcloud_enroll_on_site_parameter(self):
        """Test that on_site parameter is set correctly in enrollment."""
        config = self.module.EnrollmentConfig()
        config.bootstrap_values = f"{TEST_CONFIG_DIR}/bootstrap.yaml"
        config.systemcontroller_oam = "10.10.10.2"
        config.config_dir = TEST_CONFIG_DIR
        subcloud_enroll = self.module.SubcloudEnroll(config, "token123")
        self.mock_glob.side_effect = [
            [f"{TEST_CONFIG_DIR}/install.yaml"],
            [],
        ]
        yaml_content = (
            "systemcontroller_oam_address: 10.10.10.2\n"
            "name: subcloud1\n"
            "external_oam_floating_address: 10.10.10.12\n"
            "sysadmin_password: syspass\n"
        )
        m = mock_open(read_data=yaml_content)
        self.mock_requests_post.return_value.json.return_value = {"id": 1}
        self.mock_requests_post.return_value.raise_for_status = lambda: None
        with patch("builtins.open", m):
            subcloud_enroll.load_subcloud_config()
            result = subcloud_enroll.enroll_subcloud()
        self.assertEqual(result, {"id": 1})
        call_kwargs = self.mock_requests_post.call_args[1]
        self.assertEqual(call_kwargs["data"]["on_site"], "true")
        self.assertNotIn("skip_enroll_init", call_kwargs["data"])


if __name__ == "__main__":
    unittest.main()
