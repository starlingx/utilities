# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import ipaddress
import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _get_addr_list
from network_platform_audit.sysinv import _get_addrpool_list
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def test_addresses_vs_kernel():
    cat = "TestSuite 4 - Address Validation"
    desc = [
        "1) system host-addr-list per host",
        "2) Verify each DB address is assigned in kernel (ip -o addr show)",
        "3) Warn on kernel addresses not in DB",
        "4) Fail on deprecated addresses (non-floating IPs only)",
    ]
    print_category(cat, description=desc)

    addrpools = _get_addrpool_list()
    pool_known_ips = set()
    for pool in addrpools:
        for field in ("floating_address", "floating_addr",
                      "controller0_address", "controller1_address"):
            val = pool.get(field, "")
            if val and val not in ("None", "-", ""):
                pool_known_ips.add(val)

    for hostname in get_host_names():
        log(f"[HOST] {hostname}")
        db_addrs = _get_addr_list(hostname)
        if not db_addrs:
            log(f"  [INFO] no addresses found for {hostname}")
            continue

        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, hostname, "address kernel validation")
            continue

        rc, kernel_out, _ = _run_on_host(hostname, "ip -o addr show")
        if rc != 0 or not kernel_out:
            state.category_failures[cat].append(f"{hostname}: failed to run ip -o addr show")
            continue

        kernel_ips = set()
        deprecated_ips = set()
        for line in kernel_out.splitlines():
            m = re.search(r"inet6?\s+([0-9a-fA-F:.]+)/", line)
            if m:
                kernel_ips.add(m.group(1))
            if "deprecated" in line:
                m2 = re.search(r"inet6?\s+([0-9a-fA-F:.]+)/", line)
                if m2:
                    deprecated_ips.add(m2.group(1))

        db_ip_set = set()
        for addr in db_addrs:
            ip = addr.get("address", addr.get("ip_address", ""))
            if not ip:
                continue
            db_ip_set.add(ip)

            if ip in kernel_ips:
                log_result(f"  {hostname}: {ip} in kernel", "PASS")
            else:
                log_result(f"  {hostname}: {ip} in kernel", "FAILED")
                state.category_failures[cat].append(f"{hostname}: address {ip} in DB but not in kernel")

            if ip in deprecated_ips and ip not in pool_known_ips:
                log_result(f"  {hostname}: {ip} not deprecated", "FAILED")
                state.category_failures[cat].append(f"{hostname}: address {ip} is deprecated in kernel")

        for kip in kernel_ips:
            try:
                addr_obj = ipaddress.ip_address(kip)
                if addr_obj.is_link_local or addr_obj.is_loopback:
                    continue
            except ValueError:
                continue
            if kip not in db_ip_set and kip not in pool_known_ips:
                log(f"  [WARN] {hostname}: kernel address {kip} not in sysinv DB")
                state.category_warnings[cat].append(f"{hostname}: kernel address {kip} not in DB")
