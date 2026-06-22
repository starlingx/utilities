# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.run import run_silent
from network_platform_audit.sysinv import _get_if_list
from network_platform_audit.sysinv import _parse_generic_table
from network_platform_audit.sysinv import _resolve_kernel_ifname
from network_platform_audit.sysinv import local_hostname


def _get_sc_mgmt_ip():
    """Return the system controller management floating IP."""
    rc, out, _ = run_silent("system show")
    if rc == 0 and out:
        m = re.search(r"central_cloud_url\s*\|\s*https?://([0-9a-fA-F:.]+)", out)
        if not m:
            m2 = re.search(r"central_cloud_url\s*\|\s*https?://([^/:\s]+)", out)
            if m2:
                hostname = m2.group(1)
                rc2, res, _ = run_silent(["getent", "hosts", hostname])
                if rc2 == 0 and res:
                    return res.split()[0]
        if m:
            return m.group(1)

    rc, conf, _ = run_silent("cat /etc/platform/platform.conf")
    if rc == 0 and conf:
        m = re.search(r"central_cloud_url\s*=\s*https?://([0-9a-fA-F:.]+)", conf)
        if m:
            return m.group(1)
        m2 = re.search(r"central_cloud_url\s*=\s*https?://([^/:\s]+)", conf)
        if m2:
            hostname = m2.group(1)
            rc2, res, _ = run_silent(["getent", "hosts", hostname])
            if rc2 == 0 and res:
                return res.split()[0]

    return None


def _get_pool_gateway(keyword):
    """Return (gateway_ip, network_cidr, pool_name) for the first addrpool matching keyword."""
    rc, out, _ = run_silent("system addrpool-list")
    if rc != 0 or not out:
        return None, None, None
    pools = _parse_generic_table(out, key_col="name")
    for pool in pools:
        pool_name = pool.get("name", "")
        if keyword.lower() not in pool_name.lower():
            continue
        gateway = pool.get("gateway", pool.get("gateway_address", ""))
        network = pool.get("network", "")
        prefix = pool.get("prefix", "")
        cidr = f"{network}/{prefix}" if network and prefix else network
        if gateway and gateway.lower() != "none":
            return gateway, cidr, pool_name
        return None, cidr, pool_name
    return None, None, None


def _admin_network_has_interface():
    """Return (kernel_ifname, sysinv_ifname) if admin network has a local interface."""
    local_host = local_hostname()
    rc, out, _ = run_silent(["system", "interface-network-list", local_host])
    if rc != 0 or not out:
        return None, None

    iface_uuid = None
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 4:
            continue
        network_name = parts[-1]
        if "admin" not in network_name.lower():
            continue
        iface_uuid = parts[1]
        break

    if not iface_uuid:
        return None, None

    ifaces = _get_if_list(local_host)
    matched = next((i for i in ifaces if i.get("uuid", "") == iface_uuid), None)
    if not matched:
        rc2, show_out, _ = run_silent(["system", "host-if-show", local_host, iface_uuid])
        if rc2 == 0 and show_out:
            m = re.search(r"^\|\s*name\s*\|\s*(\S+)\s*\|", show_out, re.MULTILINE)
            if m:
                sysinv_ifname = m.group(1)
                matched = next((i for i in ifaces if i.get("name") == sysinv_ifname), None)
            else:
                return None, None
        else:
            return None, None

    sysinv_ifname = matched.get("name", iface_uuid)
    kernel_if = _resolve_kernel_ifname(matched, ifaces)
    return kernel_if, sysinv_ifname


def test_dc_subcloud():
    cat = "TestSuite 20 - Distributed Cloud / Subcloud"
    desc = [
        "1) Activated only when distributed_cloud_role = subcloud",
        "2) Detect admin network - if present, SC traffic must use admin interface",
        "3) Detect SC IPs from addrpool-list (system-controller-subnet / oam-subnet)",
        "4) Verify kernel route to SC uses admin interface (if admin exists)",
        "5) Ping gateway: admin gateway if admin exists, else mgmt gateway",
        "6) Ping SC mgmt floating and SC OAM floating",
        "7) TCP 8443 on SC OAM floating (firewall-allowed port)",
        "8) Central registry (registry.central:443) reachable",
    ]
    print_category(cat, description=desc)

    if state.DC_ROLE != "subcloud":
        log("[SKIP] distributed_cloud_role is not subcloud - skipping subcloud tests")
        return

    rc, pool_out, _ = run_silent("system addrpool-list")
    all_pools = _parse_generic_table(pool_out, key_col="name") if rc == 0 and pool_out else []

    sc_mgmt_floating = None
    sc_oam_floating = None
    for pool in all_pools:
        pname = pool.get("name", "").lower()
        floating = pool.get("floating_address", "")
        if not floating or floating.lower() == "none":
            continue
        if "system-controller-subnet" in pname and "oam" not in pname:
            sc_mgmt_floating = floating
        elif "system-controller-oam" in pname:
            sc_oam_floating = floating

    sc_ip = sc_mgmt_floating
    if sc_ip:
        log(f"  SC mgmt floating (system-controller-subnet): {sc_ip}")
    else:
        sc_ip = _get_sc_mgmt_ip()
        if sc_ip:
            log(f"  SC mgmt IP (via system show / platform.conf fallback): {sc_ip}")
        else:
            log("[WARN] system-controller-subnet floating not found in addrpool-list "
                "or platform.conf - route/TCP/IPsec checks will be skipped")
    if sc_oam_floating:
        log(f"  SC OAM floating  (system-controller-oam-subnet): {sc_oam_floating}")

    admin_kernel_if, admin_sysinv_if = _admin_network_has_interface()
    admin_gw, admin_cidr, admin_pool_name = _get_pool_gateway("admin")

    if admin_kernel_if:
        log(f"  admin network detected: pool={admin_pool_name} cidr={admin_cidr} "
            f"gw={admin_gw} iface={admin_kernel_if} (sysinv: {admin_sysinv_if})")
        gateway = admin_gw
        gw_label = f"admin gateway {admin_gw}"
    else:
        log("  no admin network - using management network for SC connectivity")
        mgmt_gw, _, _ = _get_pool_gateway("mgmt")
        if not mgmt_gw:
            mgmt_gw, _, _ = _get_pool_gateway("management")
        gateway = mgmt_gw
        gw_label = f"management gateway {mgmt_gw}" if mgmt_gw else "management gateway (unknown)"

    if sc_ip:
        flag = "-6" if ":" in sc_ip else ""
        rc, route_out, _ = run_log_only(["ip"] + ([flag] if flag else []) + ["route", "get", sc_ip])
        if rc == 0 and route_out:
            first_line = route_out.splitlines()[0]
            log_result(f"kernel route to SC {sc_ip}", "PASS")
            log(f"  route: {first_line}")
            if admin_kernel_if:
                dev_m = re.search(r"\bdev (\S+)", first_line)
                actual_if = dev_m.group(1) if dev_m else None
                if actual_if == admin_kernel_if:
                    log_result(f"route to SC uses admin interface {admin_kernel_if}", "PASS")
                else:
                    log_result(
                        f"route to SC uses admin interface {admin_kernel_if} "
                        f"(actual: {actual_if})", "FAILED"
                    )
                    state.category_failures[cat].append(
                        f"route to SC {sc_ip} uses interface {actual_if}, "
                        f"expected admin interface {admin_kernel_if}"
                    )
        else:
            log_result(f"kernel route to SC {sc_ip}", "FAILED")
            state.category_failures[cat].append(f"no kernel route to SC {sc_ip}")

    if gateway:
        flag = "-6" if ":" in gateway else ""
        rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "3", "-W", "2", gateway])
        if rc == 0:
            log_result(f"{gw_label} reachable", "PASS")
        else:
            log_result(f"{gw_label} reachable", "FAILED")
            state.category_failures[cat].append(f"{gw_label} unreachable")
    else:
        log("[WARN] no gateway detected - gateway ping skipped")

    for label, ip in [("SC mgmt floating", sc_mgmt_floating),
                      ("SC OAM floating",  sc_oam_floating)]:
        if ip:
            flag = "-6" if ":" in ip else ""
            rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "3", "-W", "2", ip])
            if rc == 0:
                log_result(f"{label} {ip} reachable", "PASS")
            else:
                log_result(f"{label} {ip} reachable", "FAILED")
                state.category_failures[cat].append(f"{label} {ip} unreachable")
        else:
            log(f"  [INFO] {label} not found in addrpool-list - ping skipped")

    if sc_oam_floating:
        nc_flag = "-6" if ":" in sc_oam_floating else ""
        rc, _, _ = run_log_only(["nc"] + ([nc_flag] if nc_flag else []) + ["-vz", "-w", "3", sc_oam_floating, "8443"])
        if rc == 0:
            log_result(f"SC OAM {sc_oam_floating}:8443 TCP accessible", "PASS")
        else:
            log_result(f"SC OAM {sc_oam_floating}:8443 TCP accessible", "FAILED")
            state.category_failures[cat].append(f"SC OAM {sc_oam_floating}:8443 TCP unreachable")
    else:
        log("  [INFO] SC OAM floating not found - TCP 8443 test skipped")

    registry_host = "registry.central"
    rc, res, _ = run_silent(["getent", "hosts", registry_host])
    if rc == 0 and res:
        registry_ip = res.split()[0]
        log_result(f"DNS: {registry_host} resolves to {registry_ip}", "PASS")
        nc_flag = "-6" if ":" in registry_ip else ""
        rc2, _, _ = run_log_only(["nc"] + ([nc_flag] if nc_flag else []) + ["-vz", "-w", "3", registry_ip, "8443"])
        if rc2 == 0:
            log_result(
                f"central registry {registry_host} ({registry_ip}):8443 accessible", "PASS"
            )
        else:
            log_result(
                f"central registry {registry_host} ({registry_ip}):8443 accessible", "FAILED"
            )
            state.category_failures[cat].append(
                f"central registry {registry_host} ({registry_ip}):8443 unreachable"
            )
    else:
        log_result(f"DNS: {registry_host} resolution failed", "FAILED")
        state.category_failures[cat].append(
            f"central registry DNS resolution failed for {registry_host}"
        )
