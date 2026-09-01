#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
import glob
import sys

import requests
import yaml

# System CA trust bundle on Debian. 'system ca-certificate-install' installs
# the CA into this file asynchronously, via a puppet runtime manifest that
# runs 'update-ca-certificates'. requests/certifi verifies against its own
# bundled trust store by default and never sees this file, so verification is
# pinned to it explicitly (see new_verified_session).
SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def new_verified_session():
    """Return a fresh requests.Session that verifies against SYSTEM_CA_BUNDLE.

    Verification is pinned to the on-disk system CA bundle rather than
    requests/certifi's bundled trust store, which never sees the CA installed
    by 'system ca-certificate-install'. requests re-reads this file when
    building a new connection's SSL context, so a verified call recovers once
    the asynchronously rebuilt CA lands on disk.
    """
    session = requests.Session()
    session.verify = SYSTEM_CA_BUNDLE
    return session


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
