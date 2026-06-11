# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only


def test_openstack_endpoints():
    cat = "TestSuite 17 - OpenStack / Keystone Endpoints"
    desc = [
        "1) openstack endpoint list - filter sysinv-related services only",
        "2) Verify each sysinv port in LISTEN (ss -tlnp)",
        "3) Test TCP accessibility for publicURL and internalURL",
    ]
    print_category(cat, description=desc)

    rc, ep_out, _ = run_log_only("openstack endpoint list 2>/dev/null")
    if rc != 0 or not ep_out:
        log("[INFO] no OpenStack endpoints found or openstack CLI failed")
        return

    SYSINV_SERVICES = {"sysinv", "platform", "stx-sysinv"}

    rc, ss_out, _ = run_log_only("ss -tlnp")

    checked_ports = set()
    for line in ep_out.splitlines():
        if not line.strip() or line.startswith("+") or "| ID" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 7:
            continue
        service_name = parts[2].lower()
        interface = parts[5].lower()
        url = parts[6]

        if not any(svc in service_name for svc in SYSINV_SERVICES):
            continue

        m = re.match(r"https?://\[([^\]]+)\]:(\d+)", url)
        if m:
            host = m.group(1)
            port = m.group(2)
        else:
            m = re.match(r"https?://([^/:]+):(\d+)", url)
            if not m:
                continue
            host = m.group(1)
            port = m.group(2)

        if port not in checked_ports:
            checked_ports.add(port)
            if ss_out and f":{port} " in ss_out:
                log_result(f"sysinv endpoint port {port} ({service_name}) in LISTEN", "PASS")
            else:
                log_result(f"sysinv endpoint port {port} ({service_name}) in LISTEN", "FAILED")
                state.category_failures[cat].append(f"sysinv endpoint port {port} ({service_name}) not listening")

        if interface in ("public", "internal"):
            if ":" in host:
                nc_cmd = f"nc -6 -vz -w 3 {host} {port}"
            else:
                nc_cmd = f"nc -vz -w 3 {host} {port}"
            rc2, _, _ = run_log_only(nc_cmd)
            if rc2 == 0:
                log_result(f"sysinv endpoint {interface} {host}:{port} TCP accessible", "PASS")
            else:
                log_result(f"sysinv endpoint {interface} {host}:{port} TCP accessible", "FAILED")
                state.category_failures[cat].append(f"sysinv endpoint {interface} {host}:{port} TCP unreachable")

    if not checked_ports:
        log("[INFO] no sysinv-related endpoints found in keystone")
