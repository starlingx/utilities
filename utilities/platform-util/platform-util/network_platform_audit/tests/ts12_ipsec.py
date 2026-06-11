# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import os
import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.run import run_silent
from network_platform_audit.run import tool_available
from network_platform_audit.sysinv import _parse_generic_table
from network_platform_audit.sysinv import local_hostname


def _detect_dnsmasq_file(filename):
    base = "/opt/platform/config"
    if not os.path.isdir(base):
        return None
    version_dirs = [d for d in os.listdir(base) if re.match(r"\d{2}\.\d{2}", d)]
    version_dirs.sort(key=lambda v: [int(x) for x in v.split(".")], reverse=True)
    for ver in version_dirs:
        path = os.path.join(base, ver, filename)
        if os.path.exists(path):
            return path
    return None


def test_ipsec():
    cat = "TestSuite 12 - IPsec"
    desc = [
        "1) Check swanctl is available (skip if not)",
        "2) Verify TCP port 64764 in LISTEN locally (controllers only)",
        "3) Resolve pxeboot-<ID> per controller neighbor and test port 64764",
        "4) Verify system-nodes connection in swanctl --list-conns",
        "5) Verify ESTABLISHED SA per peer in swanctl --list-sas",
        "6) Verify SA count matches expected peers",
    ]
    print_category(cat, description=desc)

    if not tool_available("swanctl"):
        log("[SKIP] swanctl not available - IPsec not enabled, skipping")
        return

    if state.IS_SIMPLEX:
        log("[INFO] simplex - IPsec between nodes not applicable, skipping")
        return

    rc, ss_out, _ = run_log_only("ss -tlnp sport = :64764")
    if ss_out and "64764" in ss_out:
        log_result("TCP port 64764 in LISTEN (IPsec)", "PASS")
    else:
        log_result("TCP port 64764 in LISTEN (IPsec)", "FAILED")
        state.category_failures[cat].append("TCP port 64764 not in LISTEN")

    local_host = local_hostname()
    neighbors = [h for h in state.HOST_LIST
                 if h.get("hostname", "") != local_host]

    controller_neighbors = [h for h in neighbors
                            if h.get("personality", "").lower() == "controller"]

    addn_hosts_path = _detect_dnsmasq_file("dnsmasq.addn_hosts") or "/etc/dnsmasq.addn_hosts"
    pxeboot_ip_to_name = {}
    _, addn_out, _ = run_silent(["cat", addn_hosts_path])
    for line in (addn_out or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            ip = parts[0]
            for name in parts[1:]:
                if re.match(r"^pxeboot-\d+$", name):
                    pxeboot_ip_to_name[ip] = name
    log(f"  [dnsmasq] {addn_hosts_path}: found pxeboot entries: "
        f"{', '.join(f'{n}={ip}' for ip, n in sorted(pxeboot_ip_to_name.items(), key=lambda x: x[1]))}")

    def _resolve_pxeboot_hostname(host_sysinv_name):
        rc2, addr_out, _ = run_silent(["system", "host-addr-list", host_sysinv_name])
        if not addr_out:
            log(f"  [DEBUG] host-addr-list {host_sysinv_name}: no output")
            return None, None
        for ip in pxeboot_ip_to_name:
            if ip in addr_out:
                return pxeboot_ip_to_name[ip], ip
        log(f"  [DEBUG] host-addr-list {host_sysinv_name}: none of "
            f"{list(pxeboot_ip_to_name.keys())} found in output")
        return None, None

    for host in controller_neighbors:
        hostname = host.get("hostname", "?")

        pxeboot_h, _ = _resolve_pxeboot_hostname(hostname)
        if not pxeboot_h:
            host_id = host.get("id", "")
            if not host_id:
                id_match = re.search(r"-(\d+)$", hostname)
                host_id = id_match.group(1) if id_match else hostname
            pxeboot_h = f"pxeboot-{host_id}"
            log(f"  [WARN] could not resolve pxeboot hostname for {hostname} "
                f"from {addn_hosts_path} - falling back to {pxeboot_h}")

        rc, resolv_out, _ = run_log_only(["getent", "hosts", pxeboot_h])
        if rc == 0 and resolv_out:
            neighbor_pxe_ip = resolv_out.split()[0]
            log_result(f"pxeboot hostname {pxeboot_h} resolves to {neighbor_pxe_ip}", "PASS")

            rc2, _, _ = run_log_only(["nc", "-vz", "-w", "3", neighbor_pxe_ip, "64764"])
            if rc2 == 0:
                log_result(f"port 64764 reachable on {pxeboot_h} ({neighbor_pxe_ip})", "PASS")
            else:
                log_result(f"port 64764 reachable on {pxeboot_h} ({neighbor_pxe_ip})", "FAILED")
                state.category_failures[cat].append(f"port 64764 unreachable on {pxeboot_h} ({neighbor_pxe_ip})")
        else:
            log_result(f"pxeboot hostname {pxeboot_h} resolves", "FAILED")
            state.category_failures[cat].append(f"{pxeboot_h} does not resolve")

    rc, conns_out, _ = run_log_only("swanctl --list-conns")
    if "system-nodes" in (conns_out or ""):
        log_result("swanctl: system-nodes connection configured", "PASS")
    else:
        log_result("swanctl: system-nodes connection configured", "FAILED")
        state.category_failures[cat].append("system-nodes connection not found in swanctl --list-conns")

    rc, sas_out, _ = run_log_only("swanctl --list-sas")
    established = re.findall(r"ESTABLISHED", sas_out or "")
    established_count = len(established)
    expected_peer_count = len(neighbors)

    if established_count >= expected_peer_count:
        log_result(f"IPsec SA count: {established_count} ESTABLISHED (expected >={expected_peer_count})", "PASS")
    else:
        log_result(f"IPsec SA count: {established_count} ESTABLISHED (expected >={expected_peer_count})", "FAILED")
        state.category_failures[cat].append(
            f"IPsec SA count mismatch: {established_count} established, expected {expected_peer_count}"
        )

    if state.SYSTEM_MODE in ("duplex", "duplex-direct"):
        if established_count >= expected_peer_count * 2:
            log_result("IPsec: two SAs per neighbor (DX)", "PASS")
        else:
            log(f"  [WARN] IPsec: only {established_count} SAs for {expected_peer_count} peers "
                f"(expected {expected_peer_count * 2} in DX)")
            state.category_warnings[cat].append(
                f"DX: expected {expected_peer_count * 2} SAs, found {established_count}"
            )

    local_sa_ips = re.findall(r"local ([0-9a-fA-F.:]+)", sas_out or "")
    for sa_ip in local_sa_ips:
        _, addr_out, _ = run_log_only(["ip", "addr", "show"])
        if sa_ip in (addr_out or ""):
            log_result(f"IPsec local SA IP {sa_ip} in ip addr show", "PASS")
        else:
            log_result(f"IPsec local SA IP {sa_ip} in ip addr show", "FAILED")
            state.category_failures[cat].append(f"IPsec SA local IP {sa_ip} not found in ip addr show")
