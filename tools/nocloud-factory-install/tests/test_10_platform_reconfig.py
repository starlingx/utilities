#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec
from importlib.util import spec_from_file_location
import os
import unittest
from unittest.mock import mock_open
from unittest.mock import patch

SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__),
    "../cloud-init-config/scripts/10-platform-reconfig",
)


class TestPlatformReconfig(unittest.TestCase):
    """Test cases for the 10-platform-reconfig script."""

    @classmethod
    def setUpClass(cls):
        # Mock everything before loading the module
        cls.patches = [
            patch("glob.glob", return_value=[]),
            patch("builtins.open", mock_open()),
            patch("subprocess.run"),
            patch("shutil.copytree"),
            patch("os.rename"),
            patch("tempfile.mkdtemp"),
            patch("os.path.isdir", return_value=False),
            patch("os.listdir", return_value=[]),
            patch("sys.exit"),
            patch("passlib.hash.sha512_crypt.hash"),
        ]
        for p in cls.patches:
            p.start()

        spec = spec_from_file_location(
            "platform_reconfig",
            SCRIPT_PATH,
            loader=SourceFileLoader("platform_reconfig", SCRIPT_PATH),
        )
        cls.module = module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()

    def setUp(self):
        self.mock_glob = patch("glob.glob").start()
        self.mock_open_file = patch("builtins.open", mock_open()).start()
        self.mock_print = patch("builtins.print").start()
        self.mock_exit = patch("sys.exit").start()
        self.mock_isdir = patch("os.path.isdir").start()
        self.mock_listdir = patch("os.listdir").start()
        self.mock_copytree = patch("shutil.copytree").start()
        self.mock_rename = patch("os.rename").start()
        self.mock_subprocess = patch("subprocess.run").start()
        self.mock_tempfile = patch("tempfile.mkdtemp").start()
        self.mock_stat = patch("os.stat").start()
        self.mock_sha512_crypt = patch(
            "passlib.hash.sha512_crypt.hash"
        ).start()

        # Mock os.stat to return a mock stat object
        class MockStat:
            """Mock stat object for testing."""
            st_uid = 1000
            st_gid = 1000

        self.mock_stat.return_value = MockStat()

        # Mock passlib hash function
        self.mock_sha512_crypt.return_value = "$6$somesalt$hashedpassword"

    def tearDown(self):
        patch.stopall()

    def test_find_file_success(self):
        """Test finding a file successfully."""
        config_dir = "/home/sysadmin/enroll-config/20260115-120000"
        self.mock_glob.return_value = [f"{config_dir}/bootstrap-values.yaml"]
        result = self.module.find_file("*bootstrap-values*", config_dir)
        self.assertEqual(result, f"{config_dir}/bootstrap-values.yaml")

    def test_find_file_not_found(self):
        """Test finding a file that doesn't exist."""
        config_dir = "/home/sysadmin/enroll-config/20260115-120000"
        self.mock_glob.return_value = []
        result = self.module.find_file("*nonexistent*", config_dir)
        self.assertIsNone(result)

    def test_extract_yaml_value(self):
        """Test extracting a value from YAML."""
        yaml_content = "external_oam_subnet: 10.10.10.0/24\n"
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            result = self.module.extract_yaml_value(
                "/fake/path", "external_oam_subnet"
            )
        self.assertEqual(result, "10.10.10.0/24")

    def test_extract_yaml_value_not_found(self):
        """Test extracting a missing key from YAML."""
        yaml_content = "other_key: value\n"
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            result = self.module.extract_yaml_value(
                "/fake/path", "missing_key"
            )
        self.assertIsNone(result)

    def test_extract_yaml_value_with_comma(self):
        """Test extracting a value containing commas."""
        yaml_content = "key: value1, value2\n"
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            result = self.module.extract_yaml_value("/fake/path", "key")
        self.assertEqual(result, "value1, value2")

    def test_validate_input_success(self):
        """Test validating input successfully."""
        result = self.module.validate_input("test_value", "test_key")
        self.assertEqual(result, "test_value")

    def test_validate_input_failure(self):
        """Test validating input that fails."""
        self.module.validate_input(None, "test_key")
        self.mock_exit.assert_called_once_with(1)

    def test_copy_config_files_no_dir(self):
        """Returns None when the config dir is absent."""
        self.mock_isdir.return_value = False
        result = self.module.copy_config_files()
        self.assertIsNone(result)

    def test_copy_config_files_empty_dir(self):
        """Returns None when the config dir exists but is empty."""
        self.mock_isdir.return_value = True
        self.mock_listdir.return_value = []
        result = self.module.copy_config_files()
        self.assertIsNone(result)

    def test_copy_config_files_uses_flat_config_dir(self):
        """copy_config_files reads from a single shared config/ directory."""
        self.mock_isdir.return_value = True
        self.mock_listdir.return_value = ["bootstrap-values.yaml"]
        self.mock_tempfile.return_value = "/home/sysadmin/tmpXXXXXX"
        self.module.copy_config_files()
        src = self.mock_copytree.call_args[0][0]
        self.assertTrue(src.endswith("/config"))

    def test_extract_config_values(self):
        """Test extracting all configuration values."""
        config_dir = "/home/sysadmin/enroll-config/20260115-120000"
        self.mock_glob.side_effect = [
            [f"{config_dir}/bootstrap-values.yaml"],
            [f"{config_dir}/install-values.yaml"],
        ]
        yaml_content = (
            "systemcontroller_oam_address: 10.10.10.1\n"
            "external_oam_subnet: 10.10.10.0/24\n"
            "external_oam_gateway_address: 10.10.10.254\n"
            "external_oam_floating_address: 10.10.10.2\n"
            "admin_password: adminpass\n"
            "sysadmin_password: syspass\n"
        )
        m = mock_open(read_data=yaml_content)
        with patch("builtins.open", m):
            result = self.module.extract_config_values(config_dir)

        self.assertEqual(result["systemcontroller_oam"], "10.10.10.1")
        self.assertEqual(result["oam_subnet"], "10.10.10.0/24")
        self.assertEqual(result["oam_gateway"], "10.10.10.254")
        self.assertEqual(result["oam_ip"], "10.10.10.2")
        self.assertEqual(result["admin_password"], "adminpass")
        self.assertEqual(result["sysadmin_password"], "syspass")


if __name__ == "__main__":
    unittest.main()
