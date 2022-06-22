#
# Copyright (c) 2019-2022 StarlingX.
#
# SPDX-License-Identifier: Apache-2.0
#

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# All Rights Reserved.
#

""" Define configuration info for pci-irq-affinity-agent"""

from os import path
import sys

from oslo_config import cfg

CONF = cfg.CONF

openstack_opts = [
    cfg.BoolOpt("openstack_enabled"),
    cfg.IntOpt("authorization_port"),
    cfg.StrOpt("username"),
    cfg.StrOpt("password"),
    cfg.StrOpt("tenant"),
    cfg.StrOpt("authorization_protocol"),
    cfg.StrOpt("authorization_ip"),
    cfg.StrOpt("user_domain_name"),
    cfg.StrOpt("project_domain_name"),
    cfg.StrOpt("project_name"),
    cfg.StrOpt("keyring_service"),
    cfg.StrOpt("auth_url"),
    cfg.StrOpt("cacert"),
]

amqp_opts = [
    cfg.IntOpt("port"),
    cfg.StrOpt("host"),
    cfg.StrOpt("user_id"),
    cfg.StrOpt("password"),
    cfg.StrOpt("virt_host"),
    cfg.StrOpt("topic"),
]

parameters_opts = [
    cfg.IntOpt("pci_affine_interval",
               default=60,
               help="Number of seconds between pci affinity updates"),
    cfg.IntOpt("msi_irq_timeout",
               default=45,
               help="Number of seconds to wait for msi irq configuration"),
    cfg.IntOpt("msi_irq_since",
               default=6,
               help="Number of seconds to wait for msi irqs to stabilize"),
    cfg.IntOpt("msi_irq_check_interval",
               default=2,
               help="Check interval in seconds for msi irqs to stabilize"),
    cfg.IntOpt("log_level",
               default=20,
               help="Set the log level for the agent"),
]

CONF.register_opts(openstack_opts, cfg.OptGroup("openstack"))
CONF.register_opts(amqp_opts, cfg.OptGroup("amqp"))
CONF.register_opts(parameters_opts, cfg.OptGroup("parameters"))

# load "--config-file" passed as parameter
config_file = None
for i in range(1, len(sys.argv)):
    if "--config-file" in sys.argv[i]:
        if "=" in sys.argv[i]:
            config_file = sys.argv[i].split("=")
        else:
            config_file = sys.argv[i:i+2]
        break

if config_file and path.isfile(config_file[1]):
    CONF(config_file)
