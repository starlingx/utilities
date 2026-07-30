# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import re

from network_platform_audit import state
from network_platform_audit.dc_firewall import _load_platform_firewall
from network_platform_audit.dc_firewall import check_firewall_ports_to_sc
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.run import run_silent
from network_platform_audit.sysinv import _get_if_list
from network_platform_audit.sysinv import _parse_generic_table
from network_platform_audit.sysinv import _resolve_kernel_ifname
from network_platform_audit.sysinv import _run_system_list
from network_platform_audit.sysinv import build_pools_by_network_type
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


def _admin_network_has_interface():
    """Return (kernel_ifname, sysinv_ifname) if admin network has a local interface.

    system interface-network-list columns: hostname | uuid (association) | ifname | network_name
    parts[1] is the association UUID (not the interface UUID); parts[2] is the ifname.
    """
    local_host = local_hostname()
    rc, out, _ = _run_system_list(["system", "interface-network-list", local_host], runner=run_silent)
    if rc != 0 or not out:
        return None, None

    admin_ifname = None
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 4:
            continue
        network_name = parts[-1]
        if "admin" not in network_name.lower():
            continue
        admin_ifname = parts[2]  # ifname column (parts[1] is association UUID, not interface UUID)
        break

    if not admin_ifname:
        return None, None

    ifaces = _get_if_list(local_host)
    matched = next((i for i in ifaces if i.get("name", "") == admin_ifname), None)
    if not matched:
        return None, None

    sysinv_ifname = matched.get("name", admin_ifname)
    kernel_if = _resolve_kernel_ifname(matched, ifaces)
    return kernel_if, sysinv_ifname


def _build_pools_by_type(cat):
    """Return (pools_by_type, should_return_early)."""
    rc, pool_out, _ = _run_system_list("system addrpool-list", runner=run_silent)
    all_pools = _parse_generic_table(pool_out, key_col="name") if rc == 0 and pool_out else []

    rc_na, na_out, na_err = _run_system_list("system network-addrpool-list", runner=run_silent)
    if rc_na == 0 and na_out:
        net_addrpools = _parse_generic_table(na_out, key_col="network_name")
    elif "invalid choice: 'network-addrpool-list'" in na_err:
        net_addrpools = None
    else:
        net_addrpools = []
    pools_by_type = build_pools_by_network_type(net_addrpools, all_pools)
    if net_addrpools is None:
        log_result("system network-addrpool-list: command not available in this platform version", "WARN")
        state.category_warnings[cat].append("system network-addrpool-list not available in this platform version")
        return pools_by_type, True
    return pools_by_type, False


def _pool_gateway(pools_by_type, net_type):
    """Return (gateway_ip, cidr) for the first pool of a given network type."""
    for pool in pools_by_type.get(net_type, []):
        gw = pool.get("gateway", pool.get("gateway_address", ""))
        network = pool.get("network", "")
        prefix = pool.get("prefix", "")
        cidr = f"{network}/{prefix}" if network and prefix else network
        if gw and gw.lower() != "none":
            return gw, cidr
    return None, None


def _get_sc_floating_ips(pools_by_type):
    sc_mgmt_floating = None
    sc_oam_floating = None
    for pool in pools_by_type.get("system-controller", []):
        floating = pool.get("floating_address", "")
        if floating and floating.lower() != "none":
            sc_mgmt_floating = floating
            break
    for pool in pools_by_type.get("system-controller-oam", []):
        floating = pool.get("floating_address", "")
        if floating and floating.lower() != "none":
            sc_oam_floating = floating
            break
    return sc_mgmt_floating, sc_oam_floating


def _resolve_sc_ip(sc_mgmt_floating, sc_oam_floating):
    sc_ip = sc_mgmt_floating
    if sc_ip:
        log(f"  SC mgmt floating (system-controller-subnet): {sc_ip}")
    else:
        sc_ip = _get_sc_mgmt_ip()
        if sc_ip:
            log(f"  SC mgmt IP (via system show / platform.conf fallback): {sc_ip}")
        else:
            log("[WARN] system-controller-subnet floating not found "
                "or platform.conf - route/TCP/IPsec checks will be skipped")
    if sc_oam_floating:
        log(f"  SC OAM floating  (system-controller-oam-subnet): {sc_oam_floating}")
    return sc_ip


def _resolve_gateway(pools_by_type):
    admin_kernel_if, admin_sysinv_if = _admin_network_has_interface()
    admin_gw, admin_cidr = _pool_gateway(pools_by_type, "admin")

    if admin_kernel_if:
        log(f"  admin network detected: cidr={admin_cidr} "
            f"gw={admin_gw} iface={admin_kernel_if} (sysinv: {admin_sysinv_if})")
        gateway = admin_gw
        gw_label = f"admin gateway {admin_gw}"
    else:
        log("  no admin network - using management network for SC connectivity")
        mgmt_gw, _ = _pool_gateway(pools_by_type, "mgmt")
        gateway = mgmt_gw
        gw_label = f"management gateway {mgmt_gw}" if mgmt_gw else "management gateway (unknown)"

    return admin_kernel_if, gateway, gw_label


def _check_kernel_route_to_sc(cat, sc_ip, admin_kernel_if):
    if not sc_ip:
        return
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


def _check_gateway_reachable(cat, gateway, gw_label):
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


def _check_sc_floating_reachable(cat, sc_mgmt_floating, sc_oam_floating):
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


def _check_sc_oam_tcp_8443(cat, sc_oam_floating):
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


def _check_central_registry(cat):
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


def test_dc_subcloud():
    cat = "TestSuite 20 - DC / Subcloud"
    desc = [
        "1) Activated only when distributed_cloud_role = subcloud",
        "2) Detect admin network - if present, SC traffic must use admin interface",
        "3) Detect SC IPs from addrpool-list (system-controller-subnet / oam-subnet)",
        "4) Verify kernel route to SC uses admin interface (if admin exists)",
        "5) Ping gateway: admin gateway if admin exists, else mgmt gateway",
        "6) Ping SC mgmt floating and SC OAM floating",
        "7) TCP 8443 on SC OAM floating (firewall-allowed port)",
        "8) Central registry (registry.central:443) reachable",
        "9) Firewall port reachability from platform_firewall.SYSTEMCONTROLLER",
    ]
    print_category(cat, description=desc)

    if state.DC_ROLE != "subcloud":
        log("[SKIP] distributed_cloud_role is not subcloud - skipping subcloud tests")
        return

    pools_by_type, should_return = _build_pools_by_type(cat)
    if should_return:
        return

    sc_mgmt_floating, sc_oam_floating = _get_sc_floating_ips(pools_by_type)
    sc_ip = _resolve_sc_ip(sc_mgmt_floating, sc_oam_floating)

    admin_kernel_if, gateway, gw_label = _resolve_gateway(pools_by_type)

    _check_kernel_route_to_sc(cat, sc_ip, admin_kernel_if)
    _check_gateway_reachable(cat, gateway, gw_label)
    _check_sc_floating_reachable(cat, sc_mgmt_floating, sc_oam_floating)
    _check_sc_oam_tcp_8443(cat, sc_oam_floating)
    _check_central_registry(cat)

    # Firewall port reachability: probe each port that the System Controller
    # is expected to have open (platform_firewall.SYSTEMCONTROLLER dict)
    fw = _load_platform_firewall()
    if fw is None:
        log("  [WARN] platform_firewall unavailable - SC firewall port checks skipped")
        state.category_warnings[cat].append(
            "sysinv.common.platform_firewall not importable - SC firewall port checks skipped"
        )
    elif not sc_ip:
        log("  [INFO] SC IP unknown - firewall port checks skipped")
    else:
        check_firewall_ports_to_sc(cat, sc_ip, fw, oam_ip=sc_oam_floating)
