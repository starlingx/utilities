import unittest

from keystoneauth1.exceptions import base
import mock

from ceph_manager.sysinv_api import upgrade

SYSINV_CONF = {
    'sysinv_api_bind_ip': '192.168.1.1',
    'sysinv_api_port': 12345
}
KEYSTONE_CONF = {
    'auth_url': 'http://example.com',
    'username': 'sysadmin',
    'password': 'hunter2',
    'user_domain_name': 'Default',
    'project_name': 'sysinv',
    'project_domain_name': 'Default'
}

UPGRADE_DICT = {
    'from_version': '123',
    'to_version': '456',
    'state': 'done'
}


class SysinvUpgradeApiTest(unittest.TestCase):
    def setUp(self):
        conf = mock.MagicMock()
        conf._namespace._normalized.return_value = [{'DEFAULT': SYSINV_CONF}]
        conf._namespace._normalized.return_value = [
            {'keystone_authtoken': KEYSTONE_CONF}]

        self.api = upgrade.SysinvUpgradeApi(conf)

        self.session_mock = mock.MagicMock()
        self.response_mock = mock.MagicMock()

        self.session_mock.request.return_value = self.response_mock

        self.api._get_session = mock.MagicMock(return_value=self.session_mock)

    def test_get_software_upgrade_status_has_upgrade(self):
        self.response_mock.json.return_value = {'upgrades': [UPGRADE_DICT]}

        status = self.api.get_software_upgrade_status()

        self.session_mock.request.assert_called_once()
        assert status == UPGRADE_DICT

    def test_get_software_upgrade_status_no_upgrade(self):
        expected = {
            'from_version': None,
            'to_version': None,
            'state': None
        }
        self.response_mock.json.return_value = {'upgrades': []}

        status = self.api.get_software_upgrade_status()

        self.session_mock.request.assert_called_once()
        assert status == expected

    def test_retry_get_software_upgrade_status_should_retry(self):
        self.response_mock.json.return_value = {'upgrades': [UPGRADE_DICT]}
        self.session_mock.request.side_effect = [
            base.ClientException('Boom!'), self.response_mock]

        status = self.api.retry_get_software_upgrade_status()

        assert self.session_mock.request.call_count == 2
        assert status == UPGRADE_DICT

    def test_retry_get_software_upgrade_status_retry_limit(self):
        ex = base.ClientException('Boom!')
        self.session_mock.request.side_effect = [
            ex for _ in range(upgrade.MAX_RETRY+1)]

        with self.assertRaises(base.ClientException) as context:
            self.api.retry_get_software_upgrade_status()

        assert context.exception == ex
        assert self.session_mock.request.call_count == upgrade.MAX_RETRY
