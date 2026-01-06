#!/usr/bin/env python3
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Script to safely read and output the contents of
# /etc/kubernetes/pki/ca.crt.
#
import sys

CA_CERT_PATH = "/etc/kubernetes/pki/ca.crt"

try:
    with open(CA_CERT_PATH, "r") as f:
        sys.stdout.write(f.read())
except PermissionError:
    sys.stderr.write("Permission denied reading CA cert\n")
    sys.exit(1)
except Exception as e:
    sys.stderr.write(f"Error: {e}\n")
    sys.exit(1)
