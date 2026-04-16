#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
import glob
import sys

import yaml


def find_file(pattern, config_dir):
    """Find a file matching the pattern in the config directory."""
    files = glob.glob(f"{config_dir}/{pattern}")
    return files[0] if files else None


def extract_yaml_value(filepath, key):
    """Extract a value from a YAML file."""
    with open(filepath, encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data.get(key) if data else None


def log_error(message):
    """Log an error message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"ERROR [{timestamp}]: {message}", file=sys.stderr)


def log_info(message):
    """Log an info message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"INFO [{timestamp}]: {message}")
