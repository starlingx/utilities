# Copyright (c) 2022, 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from oslo_log import log
from retrying import retry
from sysinv.common.rest_api import get_token
from sysinv.common.rest_api import rest_api_request_raise

from ceph_manager.i18n import _LI
from ceph_manager.i18n import _LW


LOG = log.getLogger(__name__)
MAX_RETRY = 5

class UsmApi(object):
    def __init__(self, conf):
        # pylint: disable=protected-access
        auth_conf = conf._namespace._normalized[0]['openstack_keystone_authtoken']
        self.region = auth_conf['region_name']
        self.token = None

    def _update_token(self):
        if not self.token or self.token.is_expired():
            LOG.debug("Requesting a new token")
            self.token = get_token(self.region)
        else:
            LOG.debug("Token is still valid. Reusing.")

    def _get_usm_endpoint(self):
        if self.token:
            service_type = "usm"
            service_name = "usm"
            region_name = self.region[0] if self.region else None
            return self.token.get_service_internal_url(service_type,
                                                       service_name,
                                                       region_name)
        return "http://127.0.0.1:5493"

    def _get_upgrades(self):
        self._update_token()
        endpoint = self._get_usm_endpoint() + '/v1/deploy/software_upgrade'
        return rest_api_request_raise(self.token, "GET", endpoint, timeout=10)

    def get_software_upgrade_status(self):
        LOG.info(_LI("Getting software upgrade status from usm"))
        upgrade = {
            'from_release': None,
            'to_release': None,
            'state': None
        }

        response = self._get_upgrades()
        if response:
            upgrade = response

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
