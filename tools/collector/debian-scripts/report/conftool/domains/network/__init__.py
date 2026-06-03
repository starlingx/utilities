########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Network Domain Plugin

Extracts and summarizes network configuration from a StarlingX
collect bundle: interfaces, bonds, VLANs, routing, listeners,
connections, /etc/hosts, and cross-checks.
"""

import sys

sys.dont_write_bytecode = True

from domains.network.config import build_summary  # noqa: E402
from domains.network.config import load_config    # noqa: E402
from domains.network.output import write_json     # noqa: E402
from domains.network.output import write_text     # noqa: E402

__all__ = ['build_summary', 'load_config', 'write_json', 'write_text']

NAME = 'Network'
FILE_PREFIX = 'network_config'

INPUT_FILES = [
    ('networking.info', 'var/extra/networking.info'),
    ('interface.info', 'var/extra/interface.info'),
    ('netstat.info', 'var/extra/netstat.info'),
    ('platform.conf', 'etc/platform/platform.conf'),
    ('hosts', 'etc/hosts'),
]
