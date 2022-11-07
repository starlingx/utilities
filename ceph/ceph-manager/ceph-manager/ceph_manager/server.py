#
# Copyright (c) 2016-2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# https://chrigl.de/posts/2014/08/27/oslo-messaging-example.html
# https://docs.openstack.org/oslo.messaging/latest/reference/server.html

import sys

# noinspection PyUnresolvedReferences
import eventlet
# noinspection PyUnresolvedReferences
from fm_api import fm_api
# noinspection PyUnresolvedReferences
from oslo_config import cfg
# noinspection PyUnresolvedReferences
from oslo_log import log as logging
# noinspection PyUnresolvedReferences
import oslo_messaging as messaging
# noinspection PyUnresolvedReferences
from oslo_service import service
# noinspection PyUnresolvedReferences
from oslo_service.periodic_task import PeriodicTasks

from ceph_manager import constants
from ceph_manager import utils
from ceph_manager.i18n import _LI
from ceph_manager.monitor import Monitor
from cephclient import wrapper


eventlet.monkey_patch(all=True)

CONF = cfg.CONF
CONF.register_opts([
    cfg.StrOpt('sysinv_api_bind_ip',
               default='0.0.0.0',
               help='IP for the Ceph Manager server to bind to')])
CONF.logging_default_format_string = (
    '%(asctime)s.%(msecs)03d %(process)d '
    '%(levelname)s %(name)s [-] %(message)s')
logging.register_options(CONF)
logging.setup(CONF, __name__)
LOG = logging.getLogger(__name__)


class Service(service.Service):

    def __init__(self, conf):
        super(Service, self).__init__()
        self.conf = conf
        self.ceph_api = None
        self.entity_instance_id = ''
        self.fm_api = fm_api.FaultAPIs()
        self.monitor = Monitor(self, conf)
        self.config = None
        self.config_desired = None
        self.config_applied = None

    def start(self):
        super(Service, self).start()
        self.ceph_api = wrapper.CephWrapper(
            endpoint='http://localhost:{}'.format(constants.CEPH_MGR_PORT))
        eventlet.spawn_n(self.monitor.run)

    def stop(self, graceful=False):
        super(Service, self).stop(graceful)


def run_service():
    CONF(sys.argv[1:])
    logging.setup(CONF, "ceph-manager")
    launcher = service.launch(CONF, Service(CONF), workers=1)
    launcher.wait()


if __name__ == "__main__":
    run_service()
