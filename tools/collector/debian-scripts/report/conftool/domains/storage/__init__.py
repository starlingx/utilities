########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Storage Domain Plugin

Extracts and summarizes storage configuration from a StarlingX collect
bundle: Ceph cluster health, DRBD replication, LVM layout, filesystem
usage, physical disk SMART health, and block device topology.
"""

import sys

sys.dont_write_bytecode = True

from domains.storage.config import build_summary  # noqa: E402
from domains.storage.config import load_config    # noqa: E402
from domains.storage.output import write_json     # noqa: E402
from domains.storage.output import write_text     # noqa: E402

__all__ = ['build_summary', 'load_config', 'write_json', 'write_text']

NAME = 'Storage'
FILE_PREFIX = 'storage_config'

INPUT_FILES = [
    ('ceph.info', 'var/extra/ceph.info'),
    ('filesystem.info', 'var/extra/filesystem.info'),
    ('disk.info', 'var/extra/disk.info'),
    ('blockdev.info', 'var/extra/blockdev.info'),
    ('iscsi.info', 'var/extra/iscsi.info'),
]
