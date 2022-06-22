#
# Copyright (c) 2021 StarlingX.
#
# SPDX-License-Identifier: Apache-2.0
#
# All Rights Reserved.
#

import unittest

import mock

from pci_irq_affinity import nova_provider
from pci_irq_affinity.config import CONF


class TestNovaProvider(unittest.TestCase):
    AUTH_URL = "http://keystone.local"
    USERNAME = "my-name"
    CACERT = "cacert.pem"
    KEYRING_SERVICE = "CGCS"
    PASSWORD = "my-pass"

    def setUp(self):
        CONF.set_override("auth_url", self.AUTH_URL, group="openstack")
        CONF.set_override("username", self.USERNAME, group="openstack")
        CONF.set_override("cacert", self.CACERT, group="openstack")
        CONF.set_override("keyring_service", self.KEYRING_SERVICE,
                          group="openstack")

    def tearDown(self):
        CONF.clear_override("auth_url", group="openstack")
        CONF.clear_override("username", group="openstack")
        CONF.clear_override("cacert", group="openstack")
        CONF.clear_override("keyring_service", group="openstack")
        CONF.clear_override("password", group="openstack")

    def test__get_keystone_creds(self):
        CONF.set_override("password", "my-pass", group="openstack")

        instance = nova_provider.NovaProvider()
        creds = instance._get_keystone_creds()

        expected = {
            "auth_url": self.AUTH_URL,
            "username": self.USERNAME,
            "password": self.PASSWORD,
            # "project_domain_name": None,
            # "project_name": None,
            # "user_domain_name": None
        }
        self.assertDictEqual(expected, creds)

    @mock.patch.object(nova_provider, "keyring")
    def test__get_keystone_creds_no_password(self, mock_keyring):
        keyring_pass = "keyring-pass"
        mock_keyring.get_password.return_value = keyring_pass
        instance = nova_provider.NovaProvider()
        mock_keyring.get_password.reset_mock()

        creds = instance._get_keystone_creds()

        expected = {
            "auth_url": self.AUTH_URL,
            "username": self.USERNAME,
            "password": keyring_pass,
            # "project_domain_name": None,
            # "project_name": None,
        }
        self.assertDictEqual(expected, creds)
        mock_keyring.get_password.assert_called_once_with(
            self.KEYRING_SERVICE,
            self.USERNAME,
        )

    def test__singleton_instantiation(self):
        nc1 = nova_provider.NovaProvider()
        nc2 = nova_provider.NovaProvider()
        nc3 = nova_provider.NovaProvider()
        self.assertTrue(nc1 is nc2 is nc3)
