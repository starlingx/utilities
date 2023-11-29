################################################################################
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
import logging


K8S_COREDUMP_LOG = "/var/log/k8s-coredump.log"
K8S_COREDUMP_CONF = "/etc/k8s-coredump-conf.json"
K8S_COREDUMP_TOKEN = "k8s_coredump_token"
LOCALHOST_URL = "https://localhost:10250/pods"
SYSTEMD_COREDUMP = "/usr/lib/systemd/systemd-coredump"


logging.basicConfig(filename=K8S_COREDUMP_LOG, level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%FT%T')
LOG = logging.getLogger("k8s-coredump")
