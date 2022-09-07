# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from keystoneauth1 import session as ksession
from keystoneauth1.identity import v3
from oslo_log import log
from retrying import retry
from urllib3 import util

from ceph_manager.i18n import _LI
from ceph_manager.i18n import _LW
from ceph_manager.utils import ipv6_bracketed

LOG = log.getLogger(__name__)
MAX_RETRY = 5


class SysinvUpgradeApi(object):
    def __init__(self, conf):
        # pylint: disable=protected-access
        sysinv_conf = conf._namespace._normalized[0]['DEFAULT']
        sysinv_api_bind_ip = sysinv_conf['sysinv_api_bind_ip'][0]
        sysinv_api_port = sysinv_conf['sysinv_api_port'][0]

        self.base_url = util.Url(
            scheme='http',
            host=ipv6_bracketed(sysinv_api_bind_ip),
            port=sysinv_api_port,
            path='/v1').url

        # pylint: disable=protected-access
        auth_conf = conf._namespace._normalized[0]['keystone_authtoken']
        self.auth_url = auth_conf['auth_url'][0]
        self.auth_username = auth_conf['username'][0]
        self.auth_password = auth_conf['password'][0]
        self.auth_user_domain_name = auth_conf['user_domain_name'][0]
        self.auth_project_name = auth_conf['project_name'][0]
        self.auth_project_domain_name = auth_conf['project_domain_name'][0]

    def _rest_api_request(self, method, api_cmd, api_cmd_headers=None,
                          api_cmd_payload=None):
        headers = {}
        headers['Accept'] = "application/json"

        if api_cmd_headers is not None:
            headers.update(api_cmd_headers)

        session = self._get_session()
        response = session.request(
            api_cmd, method, headers=headers, json=api_cmd_payload)

        return response.json()

    def _get_session(self):
        auth = v3.Password(auth_url=self.auth_url + "/v3",
                           username=self.auth_username,
                           password=self.auth_password,
                           project_name=self.auth_project_name,
                           user_domain_name=self.auth_user_domain_name,
                           project_domain_name=self.auth_project_domain_name)
        session = ksession.Session(auth=auth)

        return session

    def _get_upgrades(self):
        url = self.base_url + '/upgrade'
        response = self._rest_api_request('GET', url)
        return response.get('upgrades', [])

    def get_software_upgrade_status(self):
        LOG.info(_LI("Getting software upgrade status from sysinv"))
        upgrade = {
            'from_version': None,
            'to_version': None,
            'state': None
        }

        upgrades = self._get_upgrades()
        if upgrades:
            upgrade = upgrades[0]

        LOG.info(_LI("Software upgrade status: %s") % str(upgrade))
        return upgrade

    @retry(stop_max_attempt_number=MAX_RETRY,
           wait_fixed=1000,
           retry_on_exception=lambda e:
               LOG.warn(_LW(
                   "Getting software upgrade status failed "
                   "with: %s. Retrying... ") % str(e)) or True)
    def retry_get_software_upgrade_status(self):
        return self.get_software_upgrade_status()
