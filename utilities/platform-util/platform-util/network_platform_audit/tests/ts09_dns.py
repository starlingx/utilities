# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_checked
from network_platform_audit.run import run_log_only


def test_dns_extended():
    cat = "TestSuite 9 - DNS"
    desc = [
        "1) system dns-show - get configured nameservers",
        "2) Compare vs /etc/resolv.conf",
        "3) Ping each nameserver (ICMP)",
        "4) Test TCP port 53 and UDP port 53",
        "5) Resolve platform hostnames (controller-0, controller)",
    ]
    print_category(cat, description=desc)

    rc, dns_out, _ = run_log_only("system dns-show")
    sysinv_ns = []
    if rc == 0 and dns_out:
        m = re.search(r"nameservers\s*\|\s*([^\|]+)", dns_out)
        if m:
            sysinv_ns = [ns.strip() for ns in m.group(1).split(",") if ns.strip()]

    resolv_ns = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        resolv_ns.append(parts[1])
    except Exception:
        pass

    for ns in sysinv_ns:
        if ns in resolv_ns:
            log_result(f"nameserver {ns} in /etc/resolv.conf", "PASS")
        else:
            log_result(f"nameserver {ns} in /etc/resolv.conf", "FAILED")
            state.category_failures[cat].append(f"nameserver {ns} in sysinv but not in /etc/resolv.conf")

    all_ns = list(dict.fromkeys(sysinv_ns + resolv_ns))
    for ns in all_ns:
        flag = "-6" if ":" in ns else ""
        run_checked(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", ns])
        run_checked(["nc", "-vz", "-w", "2", ns, "53"])
        run_checked(["nc", "-vzu", "-w", "2", ns, "53"])
        log("")

    for hostname in ("controller-0", "controller"):
        rc, out, _ = run_log_only(["getent", "hosts", hostname])
        if rc == 0 and out.strip():
            log_result(f"resolve {hostname}", "PASS")
        else:
            log_result(f"resolve {hostname}", "FAILED")
            state.category_failures[cat].append(f"hostname {hostname!r} did not resolve")
