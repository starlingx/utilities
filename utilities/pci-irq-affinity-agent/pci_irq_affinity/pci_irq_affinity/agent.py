#
# Copyright (c) 2019-2022 StarlingX.
#
# SPDX-License-Identifier: Apache-2.0
#

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# All Rights Reserved.
#

""" Pci interrupt affinity agent daemon entry"""

import os
import sys
import signal
import socket
import eventlet
import threading
import time

from oslo_service import periodic_task
from oslo_service import service
import oslo_messaging

from pci_irq_affinity.affinity import pciIrqAffinity
from pci_irq_affinity.config import CONF
from pci_irq_affinity.log import LOG
from pci_irq_affinity.nova_provider import novaClient
import pci_irq_affinity.utils as pci_utils

stay_on = True


def process_signal_handler(signum, frame):
    """Process Signal Handler"""
    global stay_on

    if signum in [signal.SIGTERM, signal.SIGINT, signal.SIGTSTP]:
        stay_on = False
    else:
        LOG.info("Ignoring signal" % signum)


def get_inst(instance_uuid, callback):
    # get instance info from nova
    inst = novaClient.get_instance(instance_uuid)
    if inst is not None:
        LOG.debug("inst:%s" % inst)
        callback(inst)


def query_instance_callback(inst):
    LOG.debug("query inst:%s" % inst)
    pciIrqAffinity.affine_pci_dev_instance(inst)


@periodic_task.periodic_task(spacing=CONF.parameters.pci_affine_interval)
def audit_affinity(self, context):
    pciIrqAffinity.audit_pci_irq_affinity()


def audit_work(srv, callback):
    srv.tg.add_dynamic_timer(callback, None, None, None)
    srv.tg.wait()


def audits_initialize():
    """Init periodic audit task for pci interrupt affinity check"""
    srv = service.Service()
    periodicTasks = periodic_task.PeriodicTasks(CONF)
    periodicTasks.add_periodic_task(audit_affinity)
    thread = threading.Thread(target=audit_work, args=(srv, periodicTasks.run_periodic_tasks))
    thread.start()
    return srv


class InstanceOnlineNotificationEndpoint(object):
    filter_rule = oslo_messaging.NotificationFilter(
        event_type=pci_utils.get_event_type_regexp(pci_utils.ONLINE_EVENT_TYPES)
    )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        instance_host = payload.get('host', None)
        current_host = os.getenv("COMPUTE_HOSTNAME", default=socket.gethostname())
        if instance_host != current_host:
            LOG.debug("Requeue notification: instance_host=%s != current_host=%s" % (
                instance_host, current_host))
            return oslo_messaging.NotificationResult.REQUEUE

        instance_uuid = payload.get('instance_id', None)
        if instance_uuid:
            LOG.info("Instance online: uuid=%s, instance_host=%s, event_type=%s" % (
                instance_uuid, instance_host, event_type))
            eventlet.spawn(get_inst, instance_uuid, query_instance_callback).wait()


class InstanceOfflineNotificationEndpoint(object):
    filter_rule = oslo_messaging.NotificationFilter(
        event_type=pci_utils.get_event_type_regexp(pci_utils.OFFLINE_EVENT_TYPES)
    )

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        instance_host = payload.get('host', None)
        current_host = os.getenv("COMPUTE_HOSTNAME", default=socket.gethostname())
        if instance_host != current_host:
            LOG.debug("Requeue notification: instance_host=%s != current_host=%s" % (
                instance_host, current_host))
            return oslo_messaging.NotificationResult.REQUEUE

        instance_uuid = payload.get('instance_id', None)
        if instance_uuid:
            LOG.info("Instance offline: uuid=%s, instance_host=%s, event_type=%s" % (
                instance_uuid, instance_host, event_type))
            pciIrqAffinity.reset_irq_affinity(instance_uuid)


def rpc_work(srv):
    srv.start()
    srv.wait()


def start_rabbitmq_client():
    """Start Rabbitmq client to listen instance notifications from Nova"""
    cfg = CONF.amqp
    rabbit_url = "rabbit://%s:%s@%s:%s/%s" % (cfg['user_id'], cfg['password'],
                                              cfg['host'], cfg['port'], cfg['virt_host'])
    LOG.info(rabbit_url)

    target = oslo_messaging.Target(exchange="nova", topic="notifications", server="info",
                                   version="2.1", fanout=True)
    transport = oslo_messaging.get_notification_transport(CONF, url=rabbit_url)
    endpoints = [
        InstanceOnlineNotificationEndpoint(),
        InstanceOfflineNotificationEndpoint(),
    ]

    server = oslo_messaging.get_notification_listener(transport, [target],
                                                      endpoints, "threading", allow_requeue=True)
    thread = threading.Thread(target=rpc_work, args=(server,))
    thread.start()
    LOG.info("Rabbitmq Client Started!")

    return server


def process_main():
    """Entry function for PCI Interrupt Affinity Agent"""

    LOG.info("Enter PCIInterruptAffinity Agent")

    try:
        signal.signal(signal.SIGTSTP, process_signal_handler)
        openstack_enabled = CONF.openstack.openstack_enabled
        if openstack_enabled:
            novaClient.open_libvirt_connect()
            audit_srv = audits_initialize()
            rabbit_client = start_rabbitmq_client()

        while stay_on:
            time.sleep(1)

    except KeyboardInterrupt:
        LOG.info("keyboard Interrupt received.")
        pass

    except Exception as e:
        LOG.info("%s" % e)
        sys.exit(200)

    finally:
        LOG.error("process_main finalized!!!")
        if openstack_enabled:
            novaClient.close_libvirt_connect()
            audit_srv.tg.stop()
            rabbit_client.stop()


if __name__ == '__main__':
    process_main()
