# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

from collections import defaultdict
import ipaddress
import re

from network_platform_audit import state
from network_platform_audit.kube import _get_gnp_list
from network_platform_audit.kube import _gnp_chain_has_port
from network_platform_audit.kube import _gnp_chain_has_subnet
from network_platform_audit.kube import _gnp_selector_nodetypes
from network_platform_audit.kube import _hosts_for_gnp
from network_platform_audit.kube import _pool_subnet_str
from network_platform_audit.kube import GNP_NETWORK_MAP
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.run import tool_available
from network_platform_audit.ssh import remote_run
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _get_addrpool_list
from network_platform_audit.sysinv import _get_network_addrpool_list
from network_platform_audit.sysinv import _get_sw_version
from network_platform_audit.sysinv import build_pools_by_network_type
from network_platform_audit.sysinv import local_hostname


def _build_pool_subnets(addrpools, pools_by_type):
    pool_subnets_by_gnp = defaultdict(list)
    all_pool_subnets = set()
    for pool in addrpools:
        subnet = _pool_subnet_str(pool)
        if not subnet:
            continue
        all_pool_subnets.add(subnet)

    for gnp_pattern, net_type in GNP_NETWORK_MAP.items():
        for pool in pools_by_type.get(net_type, []):
            subnet = _pool_subnet_str(pool)
            if subnet:
                pool_subnets_by_gnp[gnp_pattern].append(subnet)

    return pool_subnets_by_gnp, all_pool_subnets


def _check_multicast_rules(cat, gnps, pools_by_type, local_sw_ver):
    mcast_pools = pools_by_type.get("multicast", [])
    has_mcast_v4 = any(":" not in p.get("network", "")
                       for p in mcast_pools
                       if p.get("network", "") and p.get("network") != "None")
    has_mcast_v6 = any(":" in p.get("network", "") for p in mcast_pools)

    if local_sw_ver is not None and local_sw_ver < (24, 9, 100):
        mcast_v4_net = "0.0.0.0/32"
    else:
        mcast_v4_net = "0.0.0.0/0"

    mcast_gnps = ("controller-mgmt-if-gnp", "controller-cluster-host-if-gnp")
    gnp_by_name = {g["name"]: g for g in gnps}
    for gnp_name in mcast_gnps:
        gnp = gnp_by_name.get(gnp_name)
        if not gnp:
            continue
        all_nets = set(gnp.get("source_nets", [])) | set(gnp.get("dest_nets", []))
        if has_mcast_v4:
            if mcast_v4_net in all_nets:
                log_result(f"GNP {gnp_name}: multicast IPv4 rule ({mcast_v4_net})", "PASS")
            else:
                log_result(f"GNP {gnp_name}: multicast IPv4 rule ({mcast_v4_net})", "FAILED")
                state.category_failures[cat].append(
                    f"GNP {gnp_name}: multicast IPv4 configured but {mcast_v4_net} missing")
        if has_mcast_v6:
            found_ll = any("fe80::" in n for n in all_nets)
            if found_ll:
                log_result(f"GNP {gnp_name}: multicast IPv6 rule (fe80::/64)", "PASS")
            else:
                log_result(f"GNP {gnp_name}: multicast IPv6 rule (fe80::/64)", "FAILED")
                state.category_failures[cat].append(
                    f"GNP {gnp_name}: multicast IPv6 configured but fe80::/64 missing")


def _subnet_in_nets(subnet, check_nets):
    found = subnet in check_nets
    if not found:
        try:
            target = ipaddress.ip_network(subnet, strict=False)
            for sn in check_nets:
                try:
                    if ipaddress.ip_network(sn, strict=False) == target:
                        found = True
                        break
                except ValueError:
                    pass
        except ValueError:
            pass
    return found


def _check_pool_subnets_in_gnp(cat, gnp_name, expected_subnets, check_nets, nets_label):
    for subnet in expected_subnets:
        found = _subnet_in_nets(subnet, check_nets)

        if found:
            log_result(f"GNP {gnp_name}: pool subnet {subnet} in {nets_label}", "PASS")
        else:
            log_result(f"GNP {gnp_name}: pool subnet {subnet} in {nets_label}", "FAILED")
            state.category_failures[cat].append(
                f"GNP {gnp_name}: pool subnet {subnet} missing from {nets_label}"
            )


def _warn_orphan_gnp_subnets(cat, gnp_name, source_nets, dest_nets, all_pool_subnets, sc_nets):
    all_gnp_nets = set(source_nets) | set(dest_nets)
    orphans_reported = set()

    for net in all_gnp_nets:
        try:
            net_obj = ipaddress.ip_network(net, strict=False)
            if net_obj.is_link_local or net_obj.is_multicast or net_obj.is_unspecified:
                continue
        except ValueError:
            continue
        if net not in all_pool_subnets and net not in orphans_reported:
            is_known = False
            for ps in all_pool_subnets:
                try:
                    if ipaddress.ip_network(ps, strict=False).overlaps(net_obj):
                        is_known = True
                        break
                except ValueError:
                    pass
            if not is_known:
                if net in sc_nets:
                    log(f"  [INFO] GNP {gnp_name}: subnet {net} is a systemcontroller "
                        f"network (stx-ingr-*-systemcontroller rule) - expected orphan")
                elif state.DC_ROLE == "systemcontroller":
                    log(f"  [INFO] GNP {gnp_name}: subnet {net} not in local pools "
                        f"(likely subcloud mgmt/admin network - expected on system controller)")
                else:
                    orphans_reported.add(net)
                    log(f"  [WARN] GNP {gnp_name}: subnet {net} has no matching sysinv pool")
                    state.category_warnings[cat].append(f"GNP {gnp_name}: orphan subnet {net}")


def _check_gnp_pool_subnets(cat, gnps, pool_subnets_by_gnp, all_pool_subnets):
    for gnp in gnps:
        gnp_name = gnp["name"]
        source_nets = gnp["source_nets"]
        dest_nets = gnp.get("dest_nets", [])
        check_nets = list(set(source_nets) | set(dest_nets))
        nets_label = "ingress nets"

        expected_subnets = list(set(pool_subnets_by_gnp.get(gnp_name, [])))
        if not expected_subnets:
            continue

        _check_pool_subnets_in_gnp(cat, gnp_name, expected_subnets, check_nets, nets_label)

        sc_nets = set(gnp.get("systemcontroller_nets", []))
        _warn_orphan_gnp_subnets(cat, gnp_name, source_nets, dest_nets, all_pool_subnets, sc_nets)


def _fetch_local_ruleset(cat, use_nft):
    if use_nft:
        log("[INFO] using nft list ruleset for GNP verification")
        rc, nft_out, _ = run_log_only("nft list ruleset")
        if rc != 0 or not nft_out:
            state.category_failures[cat].append("nft list ruleset failed")
            return None
        return nft_out

    rc, ipt_out, _ = run_log_only("iptables-save | grep -E 'cali-pi-'")
    if rc != 0:
        rc2, _, _ = run_log_only("iptables-save | head -5")
        if rc2 != 0:
            state.category_failures[cat].append("iptables-save failed")
            return None
        ipt_out = ""
    rc6, ip6t_out, _ = run_log_only("ip6tables-save | grep -E 'cali-pi-'")
    if rc6 != 0:
        ip6t_out = ""
    return (ipt_out or "") + "\n" + (ip6t_out or "")


def _check_gnp_in_firewall_local(cat, gnp_name, all_ipt_out, use_nft, fw_label):
    if use_nft:
        pattern = rf'log prefix "(?:API|APE)\d+\|{re.escape(gnp_name)}'
    else:
        pattern = rf"Policy {re.escape(gnp_name)} ingress"
    if re.search(pattern, all_ipt_out):
        log_result(f"GNP {gnp_name}: present in {fw_label}", "PASS")
        return True
    else:
        log_result(f"GNP {gnp_name}: present in {fw_label}", "FAILED")
        state.category_failures[cat].append(f"GNP {gnp_name} not found in {fw_label}")
        return False


def _check_gnp_subnets_in_firewall_local(cat, gnp_name, expected_subnets, all_ipt_out, use_nft, fw_label):
    for subnet in expected_subnets:
        match_type = _gnp_chain_has_subnet(gnp_name, subnet, all_ipt_out, use_nft)
        if match_type == "literal":
            log_result(f"GNP {gnp_name}: {fw_label} has subnet {subnet}", "PASS")
        elif match_type == "ipset":
            log_result(f"GNP {gnp_name}: {fw_label} has subnet {subnet} (via ipset)", "PASS")
        else:
            log(f"  [WARN] GNP {gnp_name}: subnet {subnet} not found in {fw_label}")
            state.category_warnings[cat].append(f"GNP {gnp_name}: subnet {subnet} not in {fw_label}")


def _check_gnp_ports_in_firewall_local(cat, gnp_name, expected_ports, all_ipt_out, use_nft, fw_label):
    for port in expected_ports:
        match_type = _gnp_chain_has_port(gnp_name, port, all_ipt_out, use_nft)
        if match_type == "literal":
            log_result(f"GNP {gnp_name}: {fw_label} has port {port}", "PASS")
        elif match_type == "range":
            log_result(f"GNP {gnp_name}: {fw_label} has port {port} (via range)", "PASS")
        else:
            log(f"  [WARN] GNP {gnp_name}: port {port} not found in {fw_label}")
            state.category_warnings[cat].append(f"GNP {gnp_name}: port {port} not in {fw_label}")


def _check_local_gnp_firewall(cat, gnps, pool_subnets_by_gnp, all_ipt_out, use_nft, fw_label):
    for gnp in gnps:
        gnp_name = gnp["name"]

        local_host = local_hostname()
        gnp_hosts = _hosts_for_gnp(gnp)
        if local_host not in gnp_hosts:
            log(f"  [SKIP] GNP {gnp_name}: selector does not target {local_host} - skipping local check")
            continue

        present = _check_gnp_in_firewall_local(cat, gnp_name, all_ipt_out, use_nft, fw_label)
        if not present:
            continue

        expected_subnets = list(set(pool_subnets_by_gnp.get(gnp_name, [])))
        _check_gnp_subnets_in_firewall_local(cat, gnp_name, expected_subnets, all_ipt_out, use_nft, fw_label)

        expected_ports = list(set(gnp.get("ports_allow", [])))
        _check_gnp_ports_in_firewall_local(cat, gnp_name, expected_ports, all_ipt_out, use_nft, fw_label)


def _fetch_remote_ruleset(cat, rhost, use_nft):
    if use_nft:
        rc4, r_ipt4, _ = remote_run(rhost, "nft list ruleset", use_sudo=True)
        if rc4 != 0:
            log_result(f"[{rhost}] nft list ruleset", "FAILED")
            state.category_failures[cat].append(f"{rhost}: nft list ruleset failed")
            return None
        return r_ipt4

    rc4, r_ipt4, _ = remote_run(rhost, "iptables-save", use_sudo=True)
    rc6, r_ipt6, _ = remote_run(rhost, "ip6tables-save", use_sudo=True)
    if rc4 != 0 and rc6 != 0:
        log_result(f"[{rhost}] iptables-save", "FAILED")
        state.category_failures[cat].append(f"{rhost}: iptables-save failed")
        return None
    return (r_ipt4 if rc4 == 0 else "") + "\n" + (r_ipt6 if rc6 == 0 else "")


def _check_gnp_in_firewall_remote(cat, rhost, gnp_name, r_all_ipt, use_nft, fw_label):
    if use_nft:
        pattern = rf'log prefix "(?:API|APE)\d+\|{re.escape(gnp_name)}'
    else:
        pattern = rf"Policy {re.escape(gnp_name)} ingress"
    if re.search(pattern, r_all_ipt):
        log_result(f"[{rhost}] GNP {gnp_name}: present in {fw_label}", "PASS")
        return True
    else:
        log_result(f"[{rhost}] GNP {gnp_name}: present in {fw_label}", "FAILED")
        state.category_failures[cat].append(
            f"{rhost}: GNP {gnp_name} not found in {fw_label}"
        )
        return False


def _check_gnp_subnets_in_firewall_remote(cat, rhost, gnp_name, expected_subnets, r_all_ipt, use_nft, fw_label):
    for subnet in expected_subnets:
        match_type = _gnp_chain_has_subnet(gnp_name, subnet, r_all_ipt, use_nft)
        if match_type == "literal":
            log_result(f"[{rhost}] GNP {gnp_name}: {fw_label} has subnet {subnet}", "PASS")
        elif match_type == "ipset":
            log_result(f"[{rhost}] GNP {gnp_name}: {fw_label} has subnet {subnet} (via ipset)", "PASS")
        else:
            log(f"  [WARN] [{rhost}] GNP {gnp_name}: subnet {subnet} not found in {fw_label}")
            state.category_warnings[cat].append(
                f"{rhost}: GNP {gnp_name}: subnet {subnet} not in {fw_label}"
            )


def _check_gnp_ports_in_firewall_remote(cat, rhost, gnp_name, expected_ports, r_all_ipt, use_nft, fw_label):
    for port in expected_ports:
        match_type = _gnp_chain_has_port(gnp_name, port, r_all_ipt, use_nft)
        if match_type == "literal":
            log_result(f"[{rhost}] GNP {gnp_name}: {fw_label} has port {port}", "PASS")
        elif match_type == "range":
            log_result(f"[{rhost}] GNP {gnp_name}: {fw_label} has port {port} (via range)", "PASS")
        else:
            log(f"  [WARN] [{rhost}] GNP {gnp_name}: port {port} not found in {fw_label}")
            state.category_warnings[cat].append(
                f"{rhost}: GNP {gnp_name}: port {port} not in {fw_label}"
            )


def _check_remote_gnp_firewall(cat, rhost, gnps, pool_subnets_by_gnp, r_all_ipt, use_nft, fw_label):
    for gnp in gnps:
        gnp_name = gnp["name"]

        gnp_hosts = _hosts_for_gnp(gnp)
        if rhost not in gnp_hosts:
            log(f"  [SKIP] [{rhost}] GNP {gnp_name}: selector does not target this host - skipping")
            continue

        present = _check_gnp_in_firewall_remote(cat, rhost, gnp_name, r_all_ipt, use_nft, fw_label)
        if not present:
            continue

        expected_subnets = list(set(pool_subnets_by_gnp.get(gnp_name, [])))
        _check_gnp_subnets_in_firewall_remote(cat, rhost, gnp_name, expected_subnets, r_all_ipt, use_nft, fw_label)

        expected_ports = list(set(gnp.get("ports_allow", [])))
        _check_gnp_ports_in_firewall_remote(cat, rhost, gnp_name, expected_ports, r_all_ipt, use_nft, fw_label)


def test_gnp_firewall():
    cat = "TestSuite 16 - Firewall / GlobalNetworkPolicy"
    desc = [
        "1) kubectl get globalnetworkpolicies -o json",
        "2) Verify each sysinv pool subnet is in matching GNP ingress nets",
        "3) Warn on GNP subnets with no matching sysinv pool",
        "4) Verify each GNP policy chain exists in iptables/ip6tables (or "
        "nftables) on every target host",
        "5) Verify iptables subnet matches pool subnet",
        "6) Verify GNP destination ports are present in iptables/nftables",
    ]
    print_category(cat, description=desc)

    if not tool_available("kubectl"):
        log("[FAIL] kubectl not available - required for GNP checks")
        state.category_failures[cat].append("kubectl not installed")
        return

    gnps = _get_gnp_list()
    addrpools = _get_addrpool_list()
    net_addrpools = _get_network_addrpool_list()
    pools_by_type = build_pools_by_network_type(net_addrpools, addrpools)

    if not gnps:
        log("[INFO] no GlobalNetworkPolicies found")
        return

    if net_addrpools is None:
        log_result("system network-addrpool-list: command not available in this platform version", "WARN")
        state.category_warnings[cat].append("system network-addrpool-list not available - pool-to-GNP subnet checks skipped")

    pool_subnets_by_gnp, all_pool_subnets = _build_pool_subnets(addrpools, pools_by_type)

    local_sw_ver = _get_sw_version(local_hostname())
    if local_sw_ver is None:
        log("[WARN] could not read local sw_version")

    # Verify multicast-related rules in GNPs:
    # If multicast IPv4 pool configured -> IGMP source must be in GNP
    # If multicast IPv6 pool configured -> fe80::/64 (link-local src) must be in GNP
    _check_multicast_rules(cat, gnps, pools_by_type, local_sw_ver)

    _check_gnp_pool_subnets(cat, gnps, pool_subnets_by_gnp, all_pool_subnets)

    if local_sw_ver is None:
        log("[WARN] could not read local sw_version, using iptables-save as default option")
        use_nft = False
    else:
        use_nft = local_sw_ver >= (26, 9, 0)

    all_ipt_out = _fetch_local_ruleset(cat, use_nft)
    if all_ipt_out is None:
        return

    fw_label = "nftables" if use_nft else "iptables"

    _check_local_gnp_firewall(cat, gnps, pool_subnets_by_gnp, all_ipt_out, use_nft, fw_label)

    remote_hosts = [h.get("hostname") for h in state.HOST_LIST
                    if h.get("hostname") and h.get("hostname") != local_hostname()]
    if remote_hosts:
        log("")
        log(f"[INFO] checking GNP {fw_label} rules on remote hosts...")
    for rhost in remote_hosts:
        if rhost in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, rhost, f"GNP {fw_label} validation")
            continue

        r_all_ipt = _fetch_remote_ruleset(cat, rhost, use_nft)
        if r_all_ipt is None:
            continue

        _check_remote_gnp_firewall(cat, rhost, gnps, pool_subnets_by_gnp, r_all_ipt, use_nft, fw_label)
