# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import log_to_file_only
from network_platform_audit.log import print_category
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _get_if_list
from network_platform_audit.sysinv import _get_if_show
from network_platform_audit.sysinv import _resolve_kernel_ifname
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def test_interfaces_vs_kernel():
    cat = "TestSuite 2 - Interface Validation"
    desc = [
        "1) Fetch all interfaces per host (system host-if-list)",
        "2) Filter platform interfaces (class=platform)",
        "3) Verify admin/oper UP, type, MTU, bond mode, VLAN ID vs kernel",
    ]
    print_category(cat, description=desc)

    for hostname in get_host_names():
        log(f"[HOST] {hostname}")
        ifaces = _get_if_list(hostname)
        if not ifaces:
            log(f"  [WARN] no interfaces found for {hostname}")
            continue

        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, hostname, "kernel interface validation")
            continue

        platform_vlans = []

        for iface in ifaces:
            ifname = iface.get("name", "?")
            iftype = iface.get("type", "?")
            ifclass = iface.get("class", "")
            imtu = iface.get("mtu", "")
            vlan_id = iface.get("vlan id", "")
            uses = iface.get("uses_list", [])

            aemode = ""
            if iftype == "ae":
                show_data = _get_if_show(hostname, ifname)
                aemode = show_data.get("aemode", "")

            if ifclass not in ("platform", ""):
                continue

            kernel_ifname = _resolve_kernel_ifname(iface, ifaces)
            prefix = f"  {hostname}/{ifname} (kernel: {kernel_ifname})"

            rc, link_out, _ = _run_on_host(hostname, ["ip", "link", "show", kernel_ifname])
            if rc is None:
                log_result(f"{prefix}: kernel checks", "SKIP")
                continue
            if rc != 0:
                log_result(f"{prefix}: ip link show", "FAILED")
                state.category_failures[cat].append(f"{hostname}/{ifname}: ip link show failed")
                continue

            flags_m = re.search(r"<([^>]+)>", link_out)
            admin_up = "UP" in flags_m.group(1) if flags_m else False
            oper_up = "state UP" in link_out or "LOWER_UP" in link_out

            if admin_up:
                log_result(f"{prefix}: admin UP", "PASS")
            else:
                log_result(f"{prefix}: admin UP", "FAILED")
                state.category_failures[cat].append(f"{hostname}/{ifname}: not administratively UP")

            if oper_up:
                log_result(f"{prefix}: oper UP", "PASS")
            else:
                log_result(f"{prefix}: oper UP", "FAILED")
                state.category_failures[cat].append(f"{hostname}/{ifname}: not operationally UP (no carrier)")

            if iftype == "ethernet":
                _, bond_out, _ = _run_on_host(
                    hostname, f"test -f /proc/net/bonding/{kernel_ifname} && echo yes || echo no", silent=True)
                _, vlan_out, _ = _run_on_host(
                    hostname, f"test -f /proc/net/vlan/{kernel_ifname} && echo yes || echo no", silent=True)
                bond_exists = 'yes' if 'yes' in bond_out else 'no'
                vlan_exists = 'yes' if 'yes' in vlan_out else 'no'
                log_to_file_only(f"    [detail] /proc/net/bonding/{kernel_ifname} exists: {bond_exists}"
                                 f"  /proc/net/vlan/{kernel_ifname} exists: {vlan_exists}")
                if "yes" in bond_out or "yes" in vlan_out:
                    log_result(f"{prefix}: type ethernet vs kernel", "FAILED")
                    state.category_failures[cat].append(
                        f"{hostname}/{ifname}: DB type=ethernet but kernel shows bond/vlan")
                else:
                    log_result(f"{prefix}: type ethernet vs kernel", "PASS")

            if iftype == "ae":
                rc2, _, _ = _run_on_host(hostname, ["test", "-f", f"/proc/net/bonding/{ifname}"], silent=True)
                log_to_file_only(f"    [detail] /proc/net/bonding/{ifname} exists: {'yes' if rc2 == 0 else 'no'}")
                if rc2 != 0:
                    log_result(f"{prefix}: type ae (bond) vs kernel", "FAILED")
                    state.category_failures[cat].append(
                        f"{hostname}/{ifname}: DB type=ae but /proc/net/bonding/{ifname} missing")
                else:
                    log_result(f"{prefix}: type ae (bond) vs kernel", "PASS")

                if aemode:
                    _, bond_info, _ = _run_on_host(hostname, ["cat", f"/proc/net/bonding/{ifname}"], silent=True)
                    kernel_mode = ""
                    m = re.search(r"Bonding Mode:\s*(.+)", bond_info)
                    if m:
                        kernel_mode = m.group(1).strip()
                    log_to_file_only(
                        f"    [detail] /proc/net/bonding/{ifname}: Bonding Mode={kernel_mode!r}  DB aemode={aemode!r}")
                    mode_map = {
                        "active_standby": "fault-tolerance (active-backup)",
                        "balanced_xor":   "load balancing (xor)",
                        "802.3ad":        "IEEE 802.3ad",
                    }
                    expected = mode_map.get(aemode, aemode)
                    if expected.lower() in kernel_mode.lower() or aemode.lower() in kernel_mode.lower():
                        log_result(f"{prefix}: bond mode ({aemode})", "PASS")
                    else:
                        log_result(f"{prefix}: bond mode ({aemode}) vs kernel ({kernel_mode})", "FAILED")
                        state.category_failures[cat].append(
                            f"{hostname}/{ifname}: DB aemode={aemode} but kernel={kernel_mode}"
                        )

                if uses:
                    _, bond_info, _ = _run_on_host(hostname, ["cat", f"/proc/net/bonding/{ifname}"], silent=True)
                    kernel_slaves = re.findall(r"Slave Interface:\s*(\S+)", bond_info)
                    log_to_file_only(
                        f"    [detail] /proc/net/bonding/{ifname}: Slave Interfaces={kernel_slaves}  DB uses={uses}")
                    missing = [m for m in uses if m not in kernel_slaves]
                    if missing:
                        log_result(f"{prefix}: bond members", "FAILED")
                        state.category_failures[cat].append(
                            f"{hostname}/{ifname}: bond members missing in kernel: {missing}"
                        )
                    else:
                        log_result(f"{prefix}: bond members", "PASS")

            if iftype == "vlan":
                _, vlan_test, _ = _run_on_host(
                    hostname, f"test -f /proc/net/vlan/{kernel_ifname} && echo yes", silent=True)
                log_to_file_only(
                    f"    [detail] /proc/net/vlan/{kernel_ifname} exists: {'yes' if 'yes' in vlan_test else 'no'}")
                if "yes" not in vlan_test:
                    log_result(f"{prefix}: type vlan vs kernel", "FAILED")
                    state.category_failures[cat].append(
                        f"{hostname}/{ifname}: DB type=vlan but /proc/net/vlan/{kernel_ifname} missing")
                else:
                    log_result(f"{prefix}: type vlan vs kernel", "PASS")

                if vlan_id and vlan_id != "None":
                    _, vlan_info, _ = _run_on_host(hostname, ["cat", f"/proc/net/vlan/{kernel_ifname}"], silent=True)
                    m = re.search(r"VID:\s*(\d+)", vlan_info)
                    kernel_vid = m.group(1) if m else ""
                    log_to_file_only(
                        f"    [detail] /proc/net/vlan/{kernel_ifname}: VID={kernel_vid!r}  DB vlan_id={vlan_id!r}")
                    if kernel_vid == str(vlan_id):
                        log_result(f"{prefix}: vlan_id={vlan_id}", "PASS")
                    else:
                        log_result(f"{prefix}: vlan_id DB={vlan_id} kernel={kernel_vid}", "FAILED")
                        state.category_failures[cat].append(
                            f"{hostname}/{ifname}: DB vlan_id={vlan_id} but kernel={kernel_vid}"
                        )
                    platform_vlans.append(str(vlan_id))

            if imtu:
                m = re.search(r"mtu (\d+)", link_out)
                kernel_mtu = m.group(1) if m else ""
                log_to_file_only(f"    [detail] ip link show {kernel_ifname}: mtu={kernel_mtu!r}  DB mtu={imtu!r}")
                if kernel_mtu == str(imtu):
                    log_result(f"{prefix}: mtu={imtu}", "PASS")
                else:
                    log_result(f"{prefix}: mtu DB={imtu} kernel={kernel_mtu}", "FAILED")
                    state.category_failures[cat].append(
                        f"{hostname}/{ifname}: DB mtu={imtu} but kernel mtu={kernel_mtu}"
                    )

        if platform_vlans:
            _, vlan_config, _ = _run_on_host(hostname, "cat /proc/net/vlan/config", silent=True)
            for vid in platform_vlans:
                if vid in vlan_config:
                    log_result(f"  {hostname}: vlan_id={vid} in /proc/net/vlan/config", "PASS")
                else:
                    log_result(f"  {hostname}: vlan_id={vid} in /proc/net/vlan/config", "FAILED")
                    state.category_failures[cat].append(
                        f"{hostname}: VLAN {vid} not found in /proc/net/vlan/config"
                    )
