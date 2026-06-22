# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import re

from network_platform_audit import state
from network_platform_audit.kube import _get_gnp_list
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.run import tool_available
from network_platform_audit.ssh import open_ssh_session
from network_platform_audit.ssh import remote_run
from network_platform_audit.sysinv import local_hostname


def _get_subcloud_list():
    """Return list of subcloud names from dcmanager, filtered by args."""
    rc, out, _ = run_log_only("dcmanager subcloud list")
    if rc != 0 or not out:
        return []

    subclouds = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        name = parts[2].strip()
        if not name or name == "name" or all(c == "-" for c in name):
            continue
        subclouds.append(name)

    if state.SUBCLOUD_NAME:
        found = [s for s in subclouds if s == state.SUBCLOUD_NAME]
        if not found:
            log(f"[WARN] --subcloud: '{state.SUBCLOUD_NAME}' not found in dcmanager subcloud list")
        return found
    if state.SUBCLOUD_RANGE_START and state.SUBCLOUD_RANGE_END:
        start = state.SUBCLOUD_RANGE_START
        end = state.SUBCLOUD_RANGE_END
        if start not in subclouds:
            log(f"[WARN] --subcloud-range: start '{start}' not found in dcmanager subcloud list")
            return []
        if end not in subclouds:
            log(f"[WARN] --subcloud-range: end '{end}' not found in dcmanager subcloud list")
            return []
        i_start = subclouds.index(start)
        i_end = subclouds.index(end)
        if i_start <= i_end:
            return subclouds[i_start:i_end + 1]
        else:
            return subclouds[i_end:i_start + 1]
    return subclouds


def _dcmanager_subcloud_show(name):
    """Return dict of subcloud properties from dcmanager subcloud show."""
    rc, out, _ = run_log_only(["dcmanager", "subcloud", "show", name])
    if rc != 0 or not out:
        return {}
    props = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) == 2:
            props[parts[0]] = parts[1]
    return props


def test_dc_systemcontroller():
    cat = "TestSuite 19 - Distributed Cloud / System Controller"
    desc = [
        "1) Activated only when distributed_cloud_role = systemcontroller",
        "2) Requires --subcloud or --subcloud-range argument",
        "3) Per subcloud: availability, gateway reachability, mgmt IP reachability",
        "4) DNS resolution, subnet in GNP, kernel route, L4 TCP ports",
    ]
    print_category(cat, description=desc)

    if state.DC_ROLE != "systemcontroller":
        log("[SKIP] distributed_cloud_role is not systemcontroller - skipping DC tests")
        return

    if not state.SUBCLOUD_NAME and not state.SUBCLOUD_RANGE_START:
        log("[WARN] DC system controller tests require --subcloud or --subcloud-range")
        state.category_warnings[cat].append("DC tests skipped: --subcloud or --subcloud-range not provided")
        return

    if not tool_available("dcmanager"):
        log("[SKIP] dcmanager not available - skipping DC tests")
        return

    subclouds = _get_subcloud_list()
    if not subclouds:
        if state.SUBCLOUD_NAME or state.SUBCLOUD_RANGE_START:
            log("[WARN] no subclouds matched the provided filter - check subcloud names")
            state.category_warnings[cat].append("no subclouds matched --subcloud / --subcloud-range filter")
        else:
            log("[INFO] no subclouds found")
        return

    gnps = _get_gnp_list()

    for sc_name in subclouds:
        log(f"\n[SUBCLOUD] {sc_name}")
        props = _dcmanager_subcloud_show(sc_name)

        availability = props.get("availability", "")
        deploy_status = props.get("deploy_status", props.get("deploy-status", ""))
        gateway_ip = props.get("external_oam_gateway_address",
                               props.get("external-oam-gateway-address",
                                         props.get("gateway_ip", "")))
        mgmt_gateway_ip = props.get("management_gateway_ip",
                                    props.get("management-gateway-ip",
                                              props.get("management_gateway_address",
                                                        props.get("management-gateway-address", ""))))
        mgmt_start_ip = props.get("management_start_ip",
                                  props.get("management-start-ip", ""))
        mgmt_subnet = props.get("management_subnet",
                                props.get("management-subnet", ""))
        sc_gw_ip = props.get("systemcontroller_gateway_ip",
                             props.get("systemcontroller-gateway-ip", ""))

        if availability == "offline":
            log_result(f"  {sc_name}: availability={availability}", "FAILED")
            state.category_failures[cat].append(f"subcloud {sc_name} is offline")
        else:
            log_result(f"  {sc_name}: availability={availability}", "PASS")

        if deploy_status == "failed":
            log_result(f"  {sc_name}: deploy_status={deploy_status}", "FAILED")
            state.category_failures[cat].append(f"subcloud {sc_name} deploy_status=failed")
        else:
            log_result(f"  {sc_name}: deploy_status={deploy_status}", "PASS")

        if sc_gw_ip:
            flag = "-6" if ":" in sc_gw_ip else ""
            rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", sc_gw_ip])
            if rc == 0:
                log_result(f"  {sc_name}: systemcontroller gateway {sc_gw_ip} reachable", "PASS")
            else:
                log_result(f"  {sc_name}: systemcontroller gateway {sc_gw_ip} reachable", "FAILED")
                state.category_failures[cat].append(
                    f"subcloud {sc_name}: systemcontroller gateway {sc_gw_ip} unreachable"
                )

        if gateway_ip:
            flag = "-6" if ":" in gateway_ip else ""
            rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", gateway_ip])
            if rc == 0:
                log_result(f"  {sc_name}: OAM gateway {gateway_ip} reachable", "PASS")
            else:
                log_result(f"  {sc_name}: OAM gateway {gateway_ip} reachable", "FAILED")
                state.category_failures[cat].append(f"subcloud {sc_name}: OAM gateway {gateway_ip} unreachable")

        if mgmt_gateway_ip:
            flag = "-6" if ":" in mgmt_gateway_ip else ""
            rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", mgmt_gateway_ip])
            if rc == 0:
                log_result(f"  {sc_name}: mgmt gateway {mgmt_gateway_ip} reachable", "PASS")
            else:
                log_result(f"  {sc_name}: mgmt gateway {mgmt_gateway_ip} reachable", "FAILED")
                state.category_failures[cat].append(f"subcloud {sc_name}: mgmt gateway {mgmt_gateway_ip} unreachable")

        if mgmt_start_ip:
            flag = "-6" if ":" in mgmt_start_ip else ""
            rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", mgmt_start_ip])
            if rc == 0:
                log_result(f"  {sc_name}: mgmt start IP {mgmt_start_ip} reachable", "PASS")
            else:
                log_result(f"  {sc_name}: mgmt start IP {mgmt_start_ip} reachable", "FAILED")
                state.category_failures[cat].append(f"subcloud {sc_name}: mgmt start IP {mgmt_start_ip} unreachable")

        rc, getent_out, _ = run_log_only(["getent", "hosts", sc_name])
        if rc == 0 and getent_out:
            resolved_ip = getent_out.split()[0]
            if mgmt_start_ip and resolved_ip == mgmt_start_ip:
                log_result(f"  {sc_name}: resolves to {mgmt_start_ip}", "PASS")
            else:
                log_result(f"  {sc_name}: resolves to {resolved_ip} (expected {mgmt_start_ip})", "FAILED")
                state.category_failures[cat].append(
                    f"subcloud {sc_name}: resolved to {resolved_ip}, expected {mgmt_start_ip}"
                )
        else:
            log_result(f"  {sc_name}: name resolution failed", "FAILED")
            state.category_failures[cat].append(f"subcloud {sc_name}: name resolution failed")

        if mgmt_subnet:
            found_in_gnp = any(
                mgmt_subnet in g.get("systemcontroller_nets", [])
                for g in gnps
            )
            if found_in_gnp:
                log_result(f"  {sc_name}: subnet {mgmt_subnet} in GNP systemcontroller rule", "PASS")
            else:
                log_result(f"  {sc_name}: subnet {mgmt_subnet} in GNP systemcontroller rule", "FAILED")
                state.category_failures[cat].append(
                    f"subcloud {sc_name}: subnet {mgmt_subnet} not in GNP systemcontroller rule"
                )

        if mgmt_subnet:
            is_v6 = ":" in mgmt_subnet
            ip_cmd = ["ip"] + (["-6"] if is_v6 else []) + ["route", "show", mgmt_subnet]
            rc, route_out, _ = run_log_only(ip_cmd)
            if rc == 0 and route_out and route_out.strip():
                log_result(f"  {sc_name}: route {mgmt_subnet} in kernel", "PASS")
            else:
                log_result(f"  {sc_name}: route {mgmt_subnet} in kernel", "FAILED")
                state.category_failures[cat].append(f"subcloud {sc_name}: no kernel route for {mgmt_subnet}")

        if mgmt_start_ip:
            all_ports = []
            for gnp in gnps:
                if "systemcontroller" in gnp["name"] or "admin" in gnp["name"]:
                    all_ports.extend(gnp.get("ports_allow", []))
            all_ports = list(set(all_ports))
            for port in all_ports[:10]:
                if not str(port).isdigit():
                    continue
                rc2, _, _ = run_log_only(["nc", "-vz", "-w", "3", mgmt_start_ip, str(port)])
                if rc2 == 0:
                    log_result(f"  {sc_name}: TCP {mgmt_start_ip}:{port} accessible", "PASS")
                else:
                    log_result(f"  {sc_name}: TCP {mgmt_start_ip}:{port} accessible", "FAILED")
                    state.category_failures[cat].append(f"subcloud {sc_name}: TCP {mgmt_start_ip}:{port} unreachable")

        if state.SUBCLOUD_OAM_IP:
            ssh_target = state.SUBCLOUD_OAM_IP
            ssh_target_lbl = f"OAM IP {ssh_target}"
        elif mgmt_start_ip and state.SSH_PASSWORD:
            ssh_target = mgmt_start_ip
            ssh_target_lbl = f"mgmt IP {ssh_target}"
        else:
            ssh_target = None

        if not ssh_target:
            if not state.SSH_PASSWORD:
                log(f"  [INFO] {sc_name}: --ssh-pass not provided - skipping remote SSH checks")
            else:
                log(f"  [INFO] {sc_name}: no SSH target available - skipping remote SSH checks")
        else:
            log(f"  [SSH] opening session to {sc_name} {ssh_target_lbl}")
            sock = open_ssh_session(ssh_target)
            state.ssh_sessions[ssh_target] = sock
            if sock is None or ssh_target in state.SSH_FAILED_HOSTS:
                if state.SUBCLOUD_OAM_IP:
                    log_result(f"  {sc_name}: SSH to {ssh_target_lbl}", "FAILED")
                    state.category_failures[cat].append(
                        f"subcloud {sc_name}: SSH to {ssh_target_lbl} failed"
                    )
                else:
                    log(f"  [INFO] {sc_name}: SSH to {ssh_target_lbl} failed"
                        f" (mgmt IP may not be directly reachable - use"
                        f" --subcloud-oam-ip for remote checks)")
            else:
                log_result(f"  {sc_name}: SSH to {ssh_target_lbl}", "PASS")

                rc_h, h_out, _ = remote_run(ssh_target, "hostname")
                if rc_h == 0:
                    log(f"  [{sc_name}] remote hostname: {h_out.strip()}")

                rc_sys, sys_out, _ = remote_run(
                    ssh_target,
                    "bash -c 'source /etc/platform/openrc && system host-list'",
                    use_sudo=False,
                )
                if rc_sys == 0 and sys_out:
                    bad_hosts = []
                    for line in sys_out.splitlines():
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) < 3:
                            continue
                        hostname_col = parts[1] if len(parts) > 1 else ""
                        avail_col = ""
                        oper_col = ""
                        for p in parts:
                            if p in ("available", "degraded", "failed", "offline", "intest"):
                                avail_col = p
                            if p in ("enabled", "disabled"):
                                oper_col = p
                        if hostname_col and hostname_col not in ("hostname", "-" * len(hostname_col)):
                            if avail_col not in ("available", "") or oper_col not in ("enabled", ""):
                                bad_hosts.append(f"{hostname_col}(avail={avail_col},oper={oper_col})")
                    if bad_hosts:
                        log_result(f"  {sc_name}: all hosts available/enabled", "FAILED")
                        state.category_failures[cat].append(
                            f"subcloud {sc_name}: hosts not healthy: {bad_hosts}"
                        )
                    else:
                        log_result(f"  {sc_name}: all hosts available/enabled", "PASS")
                else:
                    log(f"  [WARN] {sc_name}: could not run system host-list on {ssh_target_lbl}")

                rc_rt4, rt_out4, _ = remote_run(ssh_target, "ip -4 route show default")
                rc_rt6, rt_out6, _ = remote_run(ssh_target, "ip -6 route show default")
                has_default_v4 = rc_rt4 == 0 and rt_out4 and rt_out4.strip()
                has_default_v6 = rc_rt6 == 0 and rt_out6 and rt_out6.strip()
                if has_default_v4 or has_default_v6:
                    families = " + ".join(
                        f for f, ok in [("IPv4", has_default_v4), ("IPv6", has_default_v6)] if ok
                    )
                    log_result(f"  {sc_name}: default route present ({families})", "PASS")
                else:
                    log_result(f"  {sc_name}: default route present", "FAILED")
                    state.category_failures[cat].append(
                        f"subcloud {sc_name}: no default route (IPv4 or IPv6) on {ssh_target_lbl}"
                    )

                rc_kc, kc_out, _ = remote_run(
                    ssh_target,
                    "kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes --no-headers",
                    use_sudo=True,
                )
                if rc_kc == 0 and kc_out:
                    not_ready = [line for line in kc_out.splitlines() if "NotReady" in line]
                    if not_ready:
                        for line in not_ready:
                            node = line.split()[0]
                            log_result(f"  {sc_name}: k8s node {node} Ready", "FAILED")
                            state.category_failures[cat].append(
                                f"subcloud {sc_name}: k8s node {node} is NotReady"
                            )
                    else:
                        log_result(f"  {sc_name}: all k8s nodes Ready", "PASS")
                else:
                    log(f"  [INFO] {sc_name}: kubectl not available or failed"
                        f" on {ssh_target_lbl} - skipping")
