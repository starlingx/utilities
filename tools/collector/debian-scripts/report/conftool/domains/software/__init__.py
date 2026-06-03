########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Software Domain Plugin

Extracts and summarizes software/patch state from a StarlingX collect
bundle: installed releases, deploy status, build info, and host
running versions.
"""

import sys

sys.dont_write_bytecode = True

from domains.software.config import build_summary  # noqa: E402
from domains.software.config import load_config    # noqa: E402
from domains.software.output import write_json     # noqa: E402
from domains.software.output import write_text     # noqa: E402

__all__ = ['build_summary', 'load_config', 'write_json', 'write_text']

NAME = 'Software'
FILE_PREFIX = 'software_config'

INPUT_FILES = [
    ('usm.info', 'var/extra/usm.info'),
    ('software.json', 'var/extra/software/software.json'),
    ('build.info', 'etc/build.info'),
    ('platform.conf', 'etc/platform/platform.conf'),
]
