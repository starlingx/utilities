# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

from collections import defaultdict
import ipaddress
import re

from network_platform_audit import state
from network_platform_audit.kube import _get_gnp_list
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
from network_platform_audit.sysinv import _get_sw_version
from network_platform_audit.sysinv import local_hostname


def test_gnp_firewall():
    cat = "TestSuite 16 - Firewall / GlobalNetworkPolicy"
    desc = [
        "1) kubectl get globalnetworkpolicies -o json",
        "2) Verify each sysinv pool subnet is in matching GNP ingress nets",
        "3) Warn on GNP subnets with no matching sysinv pool",
        "4) Verify GNP translated to iptables/ip6tables",
        "5) Verify iptables subnet matches pool subnet",
    ]
    print_category(cat, description=desc)

    if not tool_available("kubectl"):
        log("[FAIL] kubectl not available - required for GNP checks")
        state.category_failures[cat].append("kubectl not installed")
        return

    gnps = _get_gnp_list()
    addrpools = _get_addrpool_list()

    if not gnps:
        log("[INFO] no GlobalNetworkPolicies found")
        return

    pool_subnets_by_gnp = defaultdict(list)
    all_pool_subnets = set()
    for pool in addrpools:
        subnet = _pool_subnet_str(pool)
        if not subnet:
            continue
        all_pool_subnets.add(subnet)
        pool_name = pool.get("name", "").lower()
        for gnp_pattern, keywords in GNP_NETWORK_MAP.items():
            if any(kw in pool_name for kw in keywords):
                pool_subnets_by_gnp[gnp_pattern].append(subnet)

    for gnp in gnps:
        gnp_name = gnp["name"]
        source_nets = gnp["source_nets"]
        dest_nets = gnp.get("dest_nets", [])
        check_nets = list(set(source_nets) | set(dest_nets))
        nets_label = "ingress nets"

        expected_subnets = list(set(pool_subnets_by_gnp.get(gnp_name, [])))
        if not expected_subnets:
            continue

        for subnet in expected_subnets:
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

            if found:
                log_result(f"GNP {gnp_name}: pool subnet {subnet} in {nets_label}", "PASS")
            else:
                log_result(f"GNP {gnp_name}: pool subnet {subnet} in {nets_label}", "FAILED")
                state.category_failures[cat].append(
                    f"GNP {gnp_name}: pool subnet {subnet} missing from {nets_label}"
                )

        all_gnp_nets = set(source_nets) | set(dest_nets)
        sc_nets = set(gnp.get("systemcontroller_nets", []))
        orphans_reported = set()

        for net in all_gnp_nets:
            try:
                net_obj = ipaddress.ip_network(net, strict=False)
                if net_obj.is_link_local or net_obj.is_multicast:
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

    local_sw_ver = _get_sw_version(local_hostname())
    if local_sw_ver is None:
        log("[WARN] could not read local sw_version, using iptables-save as default option")
        use_nft = False
    else:
        use_nft = local_sw_ver >= (26, 9)

    if use_nft:
        log("[INFO] using nft list ruleset for GNP verification")
        rc, nft_out, _ = run_log_only("nft list ruleset")
        if rc != 0 or not nft_out:
            state.category_failures[cat].append("nft list ruleset failed")
            return
        all_ipt_out = nft_out
    else:
        rc, ipt_out, _ = run_log_only("iptables-save | grep -E 'cali-pi-'")
        if rc != 0:
            rc2, _, _ = run_log_only("iptables-save | head -5")
            if rc2 != 0:
                state.category_failures[cat].append("iptables-save failed")
                return
            ipt_out = ""
        rc6, ip6t_out, _ = run_log_only("ip6tables-save | grep -E 'cali-pi-'")
        if rc6 != 0:
            ip6t_out = ""
        all_ipt_out = (ipt_out or "") + "\n" + (ip6t_out or "")

    fw_label = "nftables" if use_nft else "iptables"

    for gnp in gnps:
        gnp_name = gnp["name"]

        local_host = local_hostname()
        gnp_hosts = _hosts_for_gnp(gnp)
        if local_host not in gnp_hosts:
            log(f"  [SKIP] GNP {gnp_name}: selector does not target {local_host} - skipping local check")
            continue

        if use_nft:
            pattern = rf'log prefix "(?:API|APE)\d+\|{re.escape(gnp_name)}'
        else:
            pattern = rf"Policy {re.escape(gnp_name)} ingress"
        if re.search(pattern, all_ipt_out):
            log_result(f"GNP {gnp_name}: present in {fw_label}", "PASS")
        else:
            log_result(f"GNP {gnp_name}: present in {fw_label}", "FAILED")
            state.category_failures[cat].append(f"GNP {gnp_name} not found in {fw_label}")
            continue

        expected_subnets = list(set(pool_subnets_by_gnp.get(gnp_name, [])))
        for subnet in expected_subnets:
            match_type = _gnp_chain_has_subnet(gnp_name, subnet, all_ipt_out, use_nft)
            if match_type == "literal":
                log_result(f"GNP {gnp_name}: {fw_label} has subnet {subnet}", "PASS")
            elif match_type == "ipset":
                log_result(f"GNP {gnp_name}: {fw_label} has subnet {subnet} (via ipset)", "PASS")
            else:
                log(f"  [WARN] GNP {gnp_name}: subnet {subnet} not found in {fw_label}")
                state.category_warnings[cat].append(f"GNP {gnp_name}: subnet {subnet} not in {fw_label}")

    remote_hosts = [h.get("hostname") for h in state.HOST_LIST
                    if h.get("hostname") and h.get("hostname") != local_hostname()]
    if remote_hosts:
        log("")
        log(f"[INFO] checking GNP {fw_label} rules on remote hosts...")
    for rhost in remote_hosts:
        if rhost in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, rhost, f"GNP {fw_label} validation")
            continue

        if use_nft:
            rc4, r_ipt4, _ = remote_run(rhost, "nft list ruleset", use_sudo=True)
            r_all_ipt = r_ipt4 if rc4 == 0 else ""
            if rc4 != 0:
                log_result(f"[{rhost}] nft list ruleset", "FAILED")
                state.category_failures[cat].append(f"{rhost}: nft list ruleset failed")
                continue
        else:
            rc4, r_ipt4, _ = remote_run(rhost, "iptables-save", use_sudo=True)
            rc6, r_ipt6, _ = remote_run(rhost, "ip6tables-save", use_sudo=True)
            if rc4 != 0 and rc6 != 0:
                log_result(f"[{rhost}] iptables-save", "FAILED")
                state.category_failures[cat].append(f"{rhost}: iptables-save failed")
                continue
            r_all_ipt = (r_ipt4 if rc4 == 0 else "") + "\n" + (r_ipt6 if rc6 == 0 else "")

        for gnp in gnps:
            gnp_name = gnp["name"]

            gnp_hosts = _hosts_for_gnp(gnp)
            if rhost not in gnp_hosts:
                log(f"  [SKIP] [{rhost}] GNP {gnp_name}: selector does not target this host - skipping")
                continue

            if use_nft:
                pattern = rf'log prefix "(?:API|APE)\d+\|{re.escape(gnp_name)}'
            else:
                pattern = rf"Policy {re.escape(gnp_name)} ingress"
            if re.search(pattern, r_all_ipt):
                log_result(f"[{rhost}] GNP {gnp_name}: present in {fw_label}", "PASS")
            else:
                log_result(f"[{rhost}] GNP {gnp_name}: present in {fw_label}", "FAILED")
                state.category_failures[cat].append(
                    f"{rhost}: GNP {gnp_name} not found in {fw_label}"
                )
                continue

            expected_subnets = list(set(pool_subnets_by_gnp.get(gnp_name, [])))
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
