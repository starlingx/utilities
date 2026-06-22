########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Platform Domain Plugin

Extracts hardware and platform state from a StarlingX collect bundle:
system identity, CPU topology, memory, top processes, PCI devices,
kernel/boot config, and BMC sensors.
"""

import sys

sys.dont_write_bytecode = True

from domains.platform.config import build_summary  # noqa: E402
from domains.platform.config import load_config    # noqa: E402
from domains.platform.output import write_json     # noqa: E402
from domains.platform.output import write_text     # noqa: E402

__all__ = ['build_summary', 'load_config', 'write_json', 'write_text']

NAME = 'Platform'
FILE_PREFIX = 'platform_config'

INPUT_FILES = [
    ('host.info', 'var/extra/host.info'),
    ('memory.info', 'var/extra/memory.info'),
    ('process.info', 'var/extra/process.info'),
    ('bmc.info', 'var/extra/bmc.info'),
]
