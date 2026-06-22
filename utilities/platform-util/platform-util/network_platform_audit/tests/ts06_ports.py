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
from network_platform_audit.sysinv import _parse_generic_table
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def test_host_ports():
    cat = "TestSuite 6 - Physical Ports"
    desc = [
        "1) system host-port-list per host",
        "2) Verify PCI address visible in lspci -D",
        "3) Verify driver matches ethtool -i",
    ]
    print_category(cat, description=desc)

    if not tool_available("lspci"):
        log("[FAIL] lspci not available - required for port checks")
        state.category_failures[cat].append("lspci not installed")
        return

    for hostname in get_host_names():
        log(f"[HOST] {hostname}")

        rc, out, _ = run_log_only(["system", "host-port-list", hostname])

        if rc != 0 or not out:
            log(f"  [INFO] no ports or failed to query for {hostname}")
            continue

        ports = _parse_generic_table(out, key_col="name")
        if not ports:
            continue

        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, hostname, "port kernel validation")
            continue

        _, lspci_out, _ = _run_on_host(hostname, "lspci -D")

        for port in ports:
            pname = port.get("name", "?")
            pciaddr = port.get("pciaddr", port.get("pci_address", ""))
            driver = port.get("driver", "")
            prefix = f"  {hostname}/{pname}"

            if pciaddr and pciaddr in lspci_out:
                log_result(f"{prefix}: PCI {pciaddr} in lspci", "PASS")
            elif pciaddr:
                log_result(f"{prefix}: PCI {pciaddr} in lspci", "FAILED")
                state.category_failures[cat].append(f"{hostname}/{pname}: PCI {pciaddr} not found in lspci")

            if driver and pname != "?":
                rc2, ethtool_out, _ = _run_on_host(hostname, ["ethtool", "-i", pname])
                if rc2 == 0:
                    m = re.search(r"driver:\s*(\S+)", ethtool_out)
                    kernel_driver = m.group(1) if m else ""
                    if kernel_driver == driver:
                        log_result(f"{prefix}: driver={driver}", "PASS")
                    else:
                        log_result(f"{prefix}: driver DB={driver} kernel={kernel_driver}", "FAILED")
                        state.category_failures[cat].append(
                            f"{hostname}/{pname}: driver DB={driver} kernel={kernel_driver}"
                        )
