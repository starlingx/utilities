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


def _build_local_mtu_map(local_host):
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
    return local_mtu_by_ifname


def _build_subnet_maps(local_host, local_mtu_by_ifname):
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

    return subnet_hosts, subnet_mtu


def _ping_remote_ips(cat, local_host, subnet, mtu, is_v6, payload, remote_ips):
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


JUMBO_MTU = 9000


def _ping_jumbo_once(ip, payload, is_v6):
    """Run a single jumbo ping with fragmentation allowed.

    IPv4: omitting "-M do" lets the local host fragment as usual.
    IPv6: routers never fragment in-transit; "-M want" allows only the
    source host to fragment.
    """
    if is_v6:
        cmd = ["ping6", "-c", "1", "-W", "3", "-s", str(payload), "-M", "want", ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "3", "-s", str(payload), ip]
    return run_log_only(cmd)


def _ping_jumbo_remote_ips(cat, local_host, subnet, mtu, is_v6, payload, remote_ips):
    """Informational probe: can this path carry jumbo (9000) frames via
    fragmentation, given the configured MTU is below that? Reported as WARN,
    not FAILED, since a network not provisioned for jumbo is not required to
    support it.

    Only the fragmentation-allowed mode is tested: this probe only runs when
    the local interface's own MTU is already below JUMBO_MTU, so a "-M do"
    (no fragmentation) attempt would be rejected by the local kernel before
    a single packet reaches the wire (EMSGSIZE) - it can never succeed here
    and would just be a guaranteed-failing extra round trip.
    """
    for remote_host, r_ips in sorted(remote_ips.items()):
        for r_ip in r_ips:
            label_base = (f"  {local_host} -> {remote_host} ({r_ip}) subnet={subnet} "
                          f"jumbo-test payload={payload} (configured mtu={mtu})")

            rc, _, _ = _ping_jumbo_once(r_ip, payload, is_v6)
            if rc == 0:
                log_result(f"{label_base} [with fragmentation]", "PASS")
            else:
                log_result(f"{label_base} [with fragmentation]", "WARN")
                state.category_warnings[cat].append(
                    f"jumbo ({JUMBO_MTU}) not reachable even with fragmentation: "
                    f"{local_host} -> {remote_host} ({r_ip}) on {subnet}, "
                    f"configured mtu={mtu}"
                )


def _test_subnet_mtu(cat, local_host, subnet, hosts_map, subnet_mtu, ipv4_overhead, ipv6_overhead):
    local_ips = hosts_map.get(local_host, [])
    remote_ips = {h: ips for h, ips in hosts_map.items() if h != local_host}

    if not local_ips or not remote_ips:
        return False

    mtu = subnet_mtu.get(subnet)
    if not mtu:
        return False

    is_v6 = ":" in subnet
    overhead = ipv6_overhead if is_v6 else ipv4_overhead
    payload = mtu - overhead
    if payload <= 0:
        return False

    log(f"  [NET] {subnet}  mtu={mtu}  local_ip={local_ips[0]}")

    _ping_remote_ips(cat, local_host, subnet, mtu, is_v6, payload, remote_ips)

    if mtu < JUMBO_MTU:
        jumbo_payload = JUMBO_MTU - overhead
        if jumbo_payload > 0:
            _ping_jumbo_remote_ips(cat, local_host, subnet, mtu, is_v6, jumbo_payload, remote_ips)

    return True


def test_mtu_functional():
    cat = "TestSuite 18 - MTU Functional Test"
    desc = [
        "1) Build a map of all IPs per network (subnet) across all hosts",
        "2) For each network, find the local interface MTU and local IP",
        "3) Ping each REMOTE host IP on that network from the local controller",
        "   using full-size packets (payload = MTU - IP/ICMP headers, DF bit set)",
        "4) Tests both IPv4 and IPv6 networks separately",
        "5) A failure means the path between controllers cannot carry MTU-sized frames",
        "6) On networks configured below jumbo (9000), additionally probe a fixed "
        "9000-byte payload as an informational check (WARN, not FAILED) of whether "
        "the underlying switch/NIC path could carry jumbo frames",
        "7) Jumbo probe allows fragmentation (the local interface MTU is already "
        "below 9000, so a no-fragmentation attempt would always fail locally "
        "before reaching the wire)",
    ]
    print_category(cat, description=desc)

    IPV4_OVERHEAD = 28
    IPV6_OVERHEAD = 48

    local_host = local_hostname()

    local_mtu_by_ifname = _build_local_mtu_map(local_host)

    subnet_hosts, subnet_mtu = _build_subnet_maps(local_host, local_mtu_by_ifname)

    tested = False
    for subnet, hosts_map in sorted(subnet_hosts.items()):
        if _test_subnet_mtu(cat, local_host, subnet, hosts_map, subnet_mtu, IPV4_OVERHEAD, IPV6_OVERHEAD):
            tested = True

    if not tested:
        log("[INFO] no shared subnets with remote hosts found - skipping MTU functional test")
