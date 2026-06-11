# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

from collections import defaultdict
import ipaddress

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _get_addrpool_list
from network_platform_audit.sysinv import _get_network_addrpool_list
from network_platform_audit.sysinv import _get_network_list
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import local_hostname


def test_addrpools():
    cat = "TestSuite 8 - Networks and Address Pools"
    desc = [
        "1) system network-list / addrpool-list / network-addrpool-list",
        "2) Verify every network has at least one pool",
        "3) Ping floating addresses of mgmt/oam/cluster-host pools",
        "4) Ping pool gateways (WARN if unreachable)",
        "5) Detect overlapping pool ranges",
        "6) Ping floating addresses from all remote hosts (validates cluster-wide reachability)",
    ]
    print_category(cat, description=desc)

    networks = _get_network_list()
    addrpools = _get_addrpool_list()
    net_addrpools = _get_network_addrpool_list()

    if not networks:
        state.category_failures[cat].append("system network-list returned no results")
        return

    pool_by_name = {p.get("name", ""): p for p in addrpools}
    pools_per_net = defaultdict(list)
    for na in net_addrpools:
        net_name = na.get("network_name", na.get("network", ""))
        pool_name = na.get("addrpool_name", na.get("pool", ""))
        pools_per_net[net_name].append(pool_name)

    for net in networks:
        net_name = net.get("name", "?")
        if pools_per_net.get(net_name):
            log_result(f"network {net_name}: has address pool", "PASS")
        else:
            log_result(f"network {net_name}: has address pool", "FAILED")
            state.category_failures[cat].append(f"network {net_name} has no address pool assigned")

    floating_nets = {"mgmt", "oam", "cluster-host"}
    for net in networks:
        net_name = net.get("name", "?")
        if net_name not in floating_nets:
            continue
        for pool_name in pools_per_net.get(net_name, []):
            pool = pool_by_name.get(pool_name, {})
            floating = pool.get("floating_address", "")
            if not floating or floating in ("-", "None", ""):
                continue
            flag = "-6" if ":" in floating else ""
            rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", floating])
            if rc == 0:
                log_result(f"floating address {floating} ({net_name}) reachable", "PASS")
            else:
                log_result(f"floating address {floating} ({net_name}) reachable", "FAILED")
                state.category_failures[cat].append(f"floating address {floating} ({net_name}) unreachable")

    for pool in addrpools:
        gateway = pool.get("gateway", pool.get("gateway_address", ""))
        pname = pool.get("name", "?")
        if not gateway or gateway in ("-", "None", ""):
            continue
        flag = "-6" if ":" in gateway else ""
        rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", gateway])
        if rc == 0:
            log_result(f"gateway {gateway} ({pname}) reachable", "PASS")
        else:
            log(f"  [WARN] gateway {gateway} ({pname}) unreachable")
            state.category_warnings[cat].append(f"gateway {gateway} ({pname}) unreachable")

    pool_ranges = []
    for pool in addrpools:
        pname = pool.get("name", "?")
        network = pool.get("network", pool.get("subnet", ""))
        prefix = pool.get("prefix", pool.get("prefix_length", ""))
        if not network or not prefix:
            continue
        try:
            net_obj = ipaddress.ip_network(f"{network}/{prefix}", strict=False)
            pool_ranges.append((pname, net_obj))
        except ValueError:
            continue

    overlap_found = False
    for i in range(len(pool_ranges)):
        for j in range(i + 1, len(pool_ranges)):
            n1, net1 = pool_ranges[i]
            n2, net2 = pool_ranges[j]
            if net1.overlaps(net2):
                both_oam = ("oam" in n1.lower() and "oam" in n2.lower())
                if both_oam:
                    log_result(f"pool overlap (ignored - both OAM): {n1} {net1} <-> {n2} {net2}", "PASS")
                    continue
                overlap_found = True
                log_result(f"pool overlap: {n1} {net1} <-> {n2} {net2}", "FAILED")
                state.category_failures[cat].append(f"address pool overlap: {n1} {net1} <-> {n2} {net2}")

    if not overlap_found:
        log_result("no address pool range overlaps detected", "PASS")

    remote_hosts = [h.get("hostname") for h in state.HOST_LIST
                    if h.get("hostname") and h.get("hostname") != local_hostname()]
    if remote_hosts:
        log("")
        log("[INFO] pinging floating addresses from remote hosts...")

    for rhost in remote_hosts:
        if rhost in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, rhost, "floating address reachability")
            continue

        floatings_checked = 0
        for net in networks:
            net_name = net.get("name", "?")
            if net_name not in floating_nets:
                continue
            for pool_name in pools_per_net.get(net_name, []):
                pool = pool_by_name.get(pool_name, {})
                floating = (pool.get("floating_address")
                            or pool.get("floating_addr")
                            or pool.get("floating-address")
                            or "")
                if not floating or floating in ("-", "None", ""):
                    continue
                floatings_checked += 1
                flag = "-6" if ":" in floating else ""
                ping_cmd = ["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", floating]
                rc, _, _ = _run_on_host(rhost, ping_cmd, silent=True)
                if rc == 0:
                    log_result(f"[{rhost}] floating {floating} ({net_name}) reachable", "PASS")
                elif rc is None:
                    log_result(f"[{rhost}] floating {floating} ({net_name}) reachable", "SKIP")
                else:
                    log_result(f"[{rhost}] floating {floating} ({net_name}) reachable", "FAILED")
                    state.category_failures[cat].append(
                        f"{rhost}: floating address {floating} ({net_name}) unreachable"
                    )
        if floatings_checked == 0:
            log(f"  [INFO] {rhost}: no floating addresses found for mgmt/oam/cluster-host pools")

    # Populate multicast subnets for test_heartbeat_extended()
    state._multicast_subnets = []
    for pool in addrpools:
        for key in ("multicast_subnet_ipv4", "multicast_subnet_ipv6",
                    "multicast-subnet-ipv4", "multicast-subnet-ipv6"):
            val = pool.get(key, "")
            if val and val not in ("-", "None", ""):
                state._multicast_subnets.append(val)
