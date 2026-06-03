########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Container Domain Plugin

Extracts and summarizes Kubernetes container platform configuration
from a StarlingX collect bundle: cluster state, pod health, helm
releases, kubelet config, and events.
"""

import sys

sys.dont_write_bytecode = True

from domains.container.config import build_summary  # noqa: E402
from domains.container.config import load_config    # noqa: E402
from domains.container.output import write_json     # noqa: E402
from domains.container.output import write_text     # noqa: E402

__all__ = ['build_summary', 'load_config', 'write_json', 'write_text']

NAME = 'Container'
FILE_PREFIX = 'container_config'

INPUT_FILES = [
    ('containerization_kube.info', 'var/extra/containerization_kube.info'),
    ('containerization_helm.info', 'var/extra/containerization_helm.info'),
    ('containerization_host.info', 'var/extra/containerization_host.info'),
    ('containerization_events.info', 'var/extra/containerization_events.info'),
    ('kubelet config', 'etc/default/kubelet'),
]
