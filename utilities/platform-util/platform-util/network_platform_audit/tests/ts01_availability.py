# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.sysinv import get_host_names


def test_host_availability():
    cat = "TestSuite 1 - Host Availability"
    desc = [
        "1) Query system host-list",
        "2) Verify availability and operational state per host",
    ]
    from network_platform_audit.log import print_category
    print_category(cat, description=desc)

    if not state.HOST_LIST:
        state.category_failures[cat].append("no hosts found in system host-list")
        return

    bad_avail = {"degraded", "failed", "offline", "intest", "power-off"}

    for host in state.HOST_LIST:
        hostname = host.get("hostname", "?")
        avail = host.get("availability", "?")
        oper = host.get("operational", host.get("oper", "?"))

        if avail in bad_avail:
            log_result(f"host {hostname}: availability={avail}", "FAILED")
            state.category_failures[cat].append(
                f"host {hostname} has availability={avail} (expected available)"
            )
        else:
            log_result(f"host {hostname}: availability={avail}", "PASS")

        if oper != "enabled":
            log_result(f"host {hostname}: operational={oper}", "FAILED")
            state.category_failures[cat].append(
                f"host {hostname} has operational={oper} (expected enabled)"
            )
        else:
            log_result(f"host {hostname}: operational={oper}", "PASS")
