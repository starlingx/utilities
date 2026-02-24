#
# Copyright (c) 2022,2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import functools

import netaddr


def is_valid_ipv6(address):
    """ Helper to determine if we need the to add brackets.

    is_valid_ipv6('fd00::1')     -> True
    is_valid_ipv6('[fd00::1]')   -> False
    is_valid_ipv6('192.168.1.1') -> False

    """
    try:
        return netaddr.valid_ipv6(address)
    except Exception:
        return False


def ipv6_bracketed(address):
    """ Helper to ensure IPv6 is bracketed.

    ipv6_bracketed('fd00::1')     -> [fd00::1]
    ipv6_bracketed('[fd00::1]')   -> [fd00::1]
    ipv6_bracketed('192.168.1.1') -> 192.168.1.1

    """
    if is_valid_ipv6(address):
        address = "[%s]" % address
    else:
        address = "%s" % address

    return address


@functools.lru_cache(maxsize=1)
def get_debian_codename():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("VERSION_CODENAME="):
                    return line.strip().split("=")[1]
    except Exception:
        pass
    return None
