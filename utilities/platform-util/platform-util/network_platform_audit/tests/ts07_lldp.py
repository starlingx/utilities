# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.run import tool_available
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _get_if_list
from network_platform_audit.sysinv import _parse_generic_table
from network_platform_audit.sysinv import _resolve_kernel_ifname
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def _get_iface_mac(hostname, kernel_ifname):
    """Return the MAC address of a kernel interface on hostname."""
    rc, out, _ = _run_on_host(hostname, ["ip", "link", "show", kernel_ifname], silent=True)
    if rc != 0 or not out:
        return None
    m = re.search(r"link/ether\s+([0-9a-f:]{17})", out)
    return m.group(1).lower() if m else None


def test_lldp():
    cat = "TestSuite 7 - LLDP Neighbors"
    desc = [
        "1) system host-lldp-neighbor-list per host",
        "2) Compare DB neighbors vs lldpctl output",
        "3) Verify chassis_id (neighbor MAC) matches lldpctl ChassisID",
        "4) Verify local port MAC matches ip link show on the receiving interface",
    ]
    print_category(cat, description=desc)

    if not tool_available("lldpctl"):
        log("[SKIP] lldpctl not available - skipping LLDP tests")
        return

    for hostname in get_host_names():
        log(f"[HOST] {hostname}")

        rc, out, _ = run_log_only(["system", "host-lldp-neighbor-list", hostname])

        if rc != 0 or not out:
            log(f"  [INFO] no LLDP neighbors in DB for {hostname}")
            continue

        db_neighbors = _parse_generic_table(out, key_col="msap")

        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, hostname, "LLDP kernel validation")
            continue

        _, lldpctl_out, _ = _run_on_host(hostname, "lldpctl")

        lldpctl_blocks = {}
        current_if = None
        current_lines = []
        for line in (lldpctl_out or "").splitlines():
            m = re.match(r"\s*Interface:\s*(\S+)", line)
            if m:
                if current_if:
                    lldpctl_blocks[current_if] = "\n".join(current_lines)
                current_if = m.group(1).rstrip(",")
                current_lines = [line]
            elif current_if:
                current_lines.append(line)
        if current_if:
            lldpctl_blocks[current_if] = "\n".join(current_lines)

        ifaces_list = _get_if_list(hostname)

        for neighbor in db_neighbors:
            port_id = neighbor.get("port_identifier", neighbor.get("port_id", ""))
            chassis = neighbor.get("chassis_id", "")
            sysinv_if = neighbor.get("ifname", neighbor.get("name", ""))
            prefix = f"  {hostname}/{sysinv_if}"

            matched_iface = next(
                (i for i in ifaces_list if i.get("name") == sysinv_if), None
            )
            kernel_ifname = (
                _resolve_kernel_ifname(matched_iface, ifaces_list)
                if matched_iface else sysinv_if
            )

            block = lldpctl_blocks.get(kernel_ifname, lldpctl_out or "")

            found = (chassis and chassis in block) or (port_id and port_id in block)
            if found:
                log_result(f"{prefix}: LLDP neighbor present in lldpctl", "PASS")
            else:
                log_result(f"{prefix}: LLDP neighbor present in lldpctl", "FAILED")
                state.category_failures[cat].append(
                    f"{hostname}/{sysinv_if}: LLDP neighbor {chassis}/{port_id} "
                    f"in DB but not in lldpctl"
                )
                continue

            if chassis:
                chassis_norm = chassis.lower()
                m = re.search(
                    r"ChassisID\s*:\s*(?:mac\s+)?([0-9a-f:]{17})", block, re.IGNORECASE
                )
                lldpctl_chassis = m.group(1).lower() if m else None
                if lldpctl_chassis:
                    if chassis_norm == lldpctl_chassis:
                        log_result(
                            f"{prefix}: neighbor chassis MAC {chassis} matches lldpctl",
                            "PASS",
                        )
                    else:
                        log_result(
                            f"{prefix}: neighbor chassis MAC DB={chassis} "
                            f"lldpctl={lldpctl_chassis}",
                            "FAILED",
                        )
                        state.category_failures[cat].append(
                            f"{hostname}/{sysinv_if}: chassis MAC mismatch "
                            f"DB={chassis} lldpctl={lldpctl_chassis}"
                        )
                else:
                    log(f"  [INFO] {prefix}: ChassisID MAC not found in lldpctl block")

            local_mac = _get_iface_mac(hostname, kernel_ifname)
            if local_mac:
                port_id_norm = port_id.lower() if port_id else ""
                if port_id_norm and re.match(r"[0-9a-f:]{17}", port_id_norm):
                    if port_id_norm == local_mac:
                        log_result(
                            f"{prefix}: local port MAC {local_mac} matches DB port_id",
                            "PASS",
                        )
                    else:
                        log_result(
                            f"{prefix}: local port MAC ip_link={local_mac} "
                            f"DB port_id={port_id}",
                            "FAILED",
                        )
                        state.category_failures[cat].append(
                            f"{hostname}/{sysinv_if}: local port MAC mismatch "
                            f"ip link={local_mac} DB port_id={port_id}"
                        )
                else:
                    log(
                        f"  [INFO] {prefix}: port_id={port_id!r} is not a MAC "
                        f"- local MAC is {local_mac}"
                    )
            else:
                log(f"  [INFO] {prefix}: could not read MAC for {kernel_ifname}")
