# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

from collections import defaultdict
import ipaddress

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.sysinv import _get_addr_list
from network_platform_audit.sysinv import _get_if_list
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def test_mtu_functional():
    cat = "TestSuite 18 - MTU Functional Test"
    desc = [
        "1) Build a map of all IPs per network (subnet) across all hosts",
        "2) For each network, find the local interface MTU and local IP",
        "3) Ping each REMOTE host IP on that network from the local controller",
        "   using full-size packets (payload = MTU - IP/ICMP headers, DF bit set)",
        "4) Tests both IPv4 and IPv6 networks separately",
        "5) A failure means the path between controllers cannot carry MTU-sized frames",
    ]
    print_category(cat, description=desc)

    IPV4_OVERHEAD = 28
    IPV6_OVERHEAD = 48

    local_host = local_hostname()

    local_ifaces = _get_if_list(local_host)
    local_mtu_by_ifname = {}
    for iface in local_ifaces:
        ifname = iface.get("name", "")
        mtu_str = iface.get("mtu", "")
        ifclass = iface.get("class", "")
        if ifclass in ("platform", "") and mtu_str:
            try:
                local_mtu_by_ifname[ifname] = int(mtu_str)
            except ValueError:
                pass

    subnet_hosts = defaultdict(lambda: defaultdict(list))
    subnet_mtu = {}

    for hostname in get_host_names():
        addrs = _get_addr_list(hostname)
        for addr in addrs:
            ifname = addr.get("ifname", "")
            ip = addr.get("address", "")
            prefix = addr.get("prefix", "")
            if not ip or not prefix:
                continue
            try:
                ip_obj = ipaddress.ip_address(ip)
                if ip_obj.is_loopback:
                    continue
                net_obj = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
                subnet = str(net_obj)
            except ValueError:
                continue

            subnet_hosts[subnet][hostname].append(ip)

            if hostname == local_host and ifname in local_mtu_by_ifname:
                subnet_mtu[subnet] = local_mtu_by_ifname[ifname]

    tested = False
    for subnet, hosts_map in sorted(subnet_hosts.items()):
        local_ips = hosts_map.get(local_host, [])
        remote_ips = {h: ips for h, ips in hosts_map.items() if h != local_host}

        if not local_ips or not remote_ips:
            continue

        mtu = subnet_mtu.get(subnet)
        if not mtu:
            continue

        is_v6 = ":" in subnet
        overhead = IPV6_OVERHEAD if is_v6 else IPV4_OVERHEAD
        payload = mtu - overhead
        if payload <= 0:
            continue

        tested = True
        log(f"  [NET] {subnet}  mtu={mtu}  local_ip={local_ips[0]}")

        for remote_host, r_ips in sorted(remote_ips.items()):
            for r_ip in r_ips:
                if is_v6:
                    cmd = ["ping6", "-c", "1", "-W", "3", "-s", str(payload), "-M", "do", r_ip]
                else:
                    cmd = ["ping", "-c", "1", "-W", "3", "-s", str(payload), "-M", "do", r_ip]

                rc, _, _ = run_log_only(cmd)
                label = f"  {local_host} -> {remote_host} ({r_ip}) subnet={subnet} payload={payload}"
                if rc == 0:
                    log_result(label, "PASS")
                else:
                    log_result(label, "FAILED")
                    state.category_failures[cat].append(
                        f"MTU {mtu} functional test FAILED: {local_host} -> "
                        f"{remote_host} ({r_ip}) on {subnet} payload={payload}"
                    )

    if not tested:
        log("[INFO] no shared subnets with remote hosts found - skipping MTU functional test")
