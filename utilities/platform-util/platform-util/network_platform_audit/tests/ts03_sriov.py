# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import json
import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.run import tool_available
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _get_if_list
from network_platform_audit.sysinv import _get_if_show
from network_platform_audit.sysinv import _resolve_kernel_ifname
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def _build_sysinv_vfio_pci_map(hostname, ifaces):
    """Build a map of kernel PF interface name -> set of VF PCI addresses
    that sysinv has configured with sriov_vf_driver=vfio.
    """
    vfio_map = {}

    for iface in ifaces:
        if iface.get("type") != "vf":
            continue
        show_data = _get_if_show(hostname, iface.get("name", ""))
        vf_driver = show_data.get("sriov_vf_driver", "")
        if vf_driver.lower() != "vfio":
            continue

        uses_raw = show_data.get("uses", "")
        if isinstance(uses_raw, str):
            parent_names = re.findall(r"'([^']+)'", uses_raw)
            if not parent_names and uses_raw.strip("[]").strip():
                parent_names = [uses_raw.strip("[]").strip()]
        else:
            parent_names = list(uses_raw)

        for pf_sysinv_name in parent_names:
            pf_iface = next((i for i in ifaces if i.get("name") == pf_sysinv_name), None)
            if not pf_iface:
                continue
            pf_show = pf_iface.get("_show") or _get_if_show(hostname, pf_sysinv_name)
            port_name = pf_show.get("ports", "")
            port_names = re.findall(r"'([^']+)'", port_name) if isinstance(port_name, str) else []
            kernel_pf = port_names[0] if port_names else pf_sysinv_name

            if hostname == local_hostname():
                _, uevent, _ = run_log_only(
                    f"cat /sys/class/net/{kernel_pf}/device/uevent"
                )
            else:
                _, uevent, _ = _run_on_host(
                    hostname,
                    f"cat /sys/class/net/{kernel_pf}/device/uevent",
                    silent=True,
                )
            slot_m = re.search(r"PCI_SLOT_NAME=(.+)", uevent or "")
            if not slot_m:
                continue
            pf_pci = slot_m.group(1).strip()

            if hostname == local_hostname():
                _, vfn_ls, _ = run_log_only(
                    f"ls -la /sys/bus/pci/devices/{pf_pci}/virtfn* 2>/dev/null"
                )
            else:
                _, vfn_ls, _ = _run_on_host(
                    hostname,
                    f"ls -la /sys/bus/pci/devices/{pf_pci}/virtfn* 2>/dev/null",
                    silent=True,
                )

            for vfn_line in (vfn_ls or "").splitlines():
                idx_m = re.search(
                    r"virtfn(\d+)\s*->\s*\S*?([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]+)",
                    vfn_line,
                )
                if not idx_m:
                    continue
                vf_pci_addr = idx_m.group(2)
                if hostname == local_hostname():
                    _, drv_out, _ = run_log_only(
                        f"cat /sys/bus/pci/devices/{vf_pci_addr}/uevent 2>/dev/null"
                    )
                else:
                    _, drv_out, _ = _run_on_host(
                        hostname,
                        f"cat /sys/bus/pci/devices/{vf_pci_addr}/uevent 2>/dev/null",
                        silent=True,
                    )
                drv_m = re.search(r"DRIVER=(.+)", drv_out or "")
                if drv_m and drv_m.group(1).strip().lower() == "vfio-pci":
                    vfio_map.setdefault(kernel_pf, set()).add(vf_pci_addr)

    return vfio_map


def _vf_covered_by_vfio_resource(vf_pci, vf_idx, resources, pf_kernel):
    """Return True if vf_pci/vf_idx is covered by another resource entry that
    expects vfio-pci driver on the same PF.
    """
    for res in resources:
        selectors = res.get("selectors", {})
        exp_drivers = selectors.get("drivers", [])
        exp_drv = exp_drivers[0].lower() if exp_drivers else ""
        if exp_drv != "vfio-pci":
            continue
        for pf_entry in selectors.get("pfNames", []):
            if "#" in pf_entry:
                entry_pf, idx_str = pf_entry.split("#", 1)
            else:
                entry_pf = pf_entry
                idx_str = None
            if entry_pf != pf_kernel:
                continue
            if idx_str is None:
                return True
            for part in idx_str.split(","):
                part = part.strip()
                if "-" in part:
                    try:
                        a, b = part.split("-", 1)
                        if int(a) <= vf_idx <= int(b):
                            return True
                    except ValueError:
                        pass
                elif part.isdigit() and int(part) == vf_idx:
                    return True
    return False


def _test_sriov_pcidp_vs_devbind(cat, hostname, sysinv_vfio_pci=None):
    """3.4 - Cross-check /etc/pcidp/config.json vs dpdk-devbind.py --status."""
    if sysinv_vfio_pci is None:
        sysinv_vfio_pci = {}
    config_path = "/etc/pcidp/config.json"
    rc, conf_out, _ = _run_on_host(hostname, ["cat", config_path], silent=True)
    if rc != 0 or not conf_out:
        log(f"  [INFO] {hostname}: {config_path} not found - skipping pcidp/devbind cross-check")
        return

    try:
        config = json.loads(conf_out)
    except Exception as e:
        log(f"  [WARN] {hostname}: failed to parse {config_path}: {e}")
        return

    resources = config.get("resourceList", [])
    log(f"  [config] {hostname}: read {config_path} - {len(resources)} resource(s): "
        f"{', '.join(r.get('resourceName', '?') for r in resources)}")

    rc, devbind_out, _ = _run_on_host(hostname, "dpdk-devbind.py --status")
    if rc != 0 or not devbind_out:
        log(f"  [WARN] dpdk-devbind.py --status failed on {hostname} - skipping cross-check")
        return

    dpdk_pci = {}
    kernel_pci = {}
    section = None
    for line in devbind_out.splitlines():
        if "DPDK-compatible driver" in line:
            section = "dpdk"
        elif "kernel driver" in line:
            section = "kernel"
        elif not line.strip() or line.startswith("=") or line.startswith("No "):
            continue
        else:
            pci_m = re.match(r"(\S+:\S+\.\S+)\s", line)
            if not pci_m:
                continue
            pci = pci_m.group(1)
            drv_m = re.search(r"\bdrv=(\S+)", line)
            if_m = re.search(r"\bif=(\S+)", line)
            drv = drv_m.group(1) if drv_m else ""
            ifname = if_m.group(1) if if_m else ""
            if section == "dpdk":
                dpdk_pci[pci] = drv
            elif section == "kernel":
                kernel_pci[pci] = {"drv": drv, "ifname": ifname}

    for resource in resources:
        res_name = resource.get("resourceName", "?")
        selectors = resource.get("selectors", {})
        pf_names = selectors.get("pfNames", [])
        exp_drivers = selectors.get("drivers", [])
        exp_driver = exp_drivers[0].lower() if exp_drivers else ""

        for pf_entry in pf_names:
            if "#" in pf_entry:
                pf_kernel, idx_str = pf_entry.split("#", 1)
                vf_indices = set()
                for part in idx_str.split(","):
                    part = part.strip()
                    if "-" in part:
                        try:
                            a, b = part.split("-", 1)
                            vf_indices.update(range(int(a), int(b) + 1))
                        except ValueError:
                            log(f"  [WARN] {hostname}/{res_name}: malformed VF range {part!r} in pfNames - skipping")
                    elif part.isdigit():
                        vf_indices.add(int(part))
            else:
                pf_kernel = pf_entry
                vf_indices = None

            prefix = f"  {hostname}/{res_name} (PF={pf_kernel})"

            idx_range = (
                f"VF indices {sorted(vf_indices)[:4]}{'...' if len(vf_indices) > 4 else ''}"
                if vf_indices else "all VFs"
            )

            pf_pci = None
            for pci, info in kernel_pci.items():
                if info.get("ifname") == pf_kernel:
                    pf_pci = pci
                    break

            if pf_pci:
                log_result(
                    f"  {hostname}/{res_name}"
                    f" (PF={pf_kernel}, exp_driver={exp_driver}, {idx_range}):"
                    f" PF in kernel-driver section (not bound to vfio-pci)",
                    "PASS",
                )
            else:
                pf_in_dpdk = any(
                    pci for pci in dpdk_pci
                    if pci in kernel_pci and kernel_pci[pci].get("ifname") == pf_kernel
                ) or pf_kernel in dpdk_pci
                if pf_in_dpdk:
                    log_result(
                        f"  {hostname}/{res_name}"
                        f" (PF={pf_kernel}): PF is bound to vfio-pci - should be in kernel section",
                        "FAILED",
                    )
                    state.category_failures[cat].append(
                        f"{hostname}/{res_name}: PF {pf_kernel} is bound to vfio-pci"
                    )
                else:
                    log(f"  [INFO] {hostname}/{res_name}: PF {pf_kernel} not found in devbind output")

            vf_pci_by_idx = {}
            if pf_pci or pf_kernel:
                if not pf_pci:
                    rc2, if_out, _ = _run_on_host(
                        hostname,
                        f"cat /sys/class/net/{pf_kernel}/device/uevent",
                        silent=True,
                    )
                    slot_m = re.search(r"PCI_SLOT_NAME=(.+)", if_out or "")
                    if slot_m:
                        pf_pci = slot_m.group(1).strip()

                if pf_pci:
                    rc2, vfn_ls, _ = _run_on_host(
                        hostname,
                        f"ls -la /sys/bus/pci/devices/{pf_pci}/virtfn* 2>/dev/null",
                        silent=True,
                    )
                    for vfn_line in (vfn_ls or "").splitlines():
                        idx_m = re.search(
                            r"virtfn(\d+)\s*->\s*\S*?([0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])", vfn_line)
                        if idx_m:
                            vf_pci_by_idx[int(idx_m.group(1))] = idx_m.group(2)

            correct = 0
            wrong = []
            indices_to_check = (
                sorted(vf_indices) if vf_indices is not None
                else sorted(vf_pci_by_idx.keys())
            )
            actual_drv_counts = {}
            for idx in indices_to_check:
                pci = vf_pci_by_idx.get(idx)
                if pci:
                    if pci in dpdk_pci:
                        drv = dpdk_pci[pci]
                    else:
                        drv = kernel_pci.get(pci, {}).get("drv", "unbound")
                    actual_drv_counts[drv] = actual_drv_counts.get(drv, 0) + 1

            for idx in indices_to_check:
                vf_pci = vf_pci_by_idx.get(idx)
                if not vf_pci:
                    wrong.append(f"vf{idx}:not_found_in_sysfs")
                    continue
                if exp_driver == "vfio-pci":
                    if vf_pci in dpdk_pci and dpdk_pci[vf_pci].lower() == "vfio-pci":
                        correct += 1
                    else:
                        actual = dpdk_pci.get(vf_pci) or kernel_pci.get(vf_pci, {}).get("drv", "unbound")
                        wrong.append(f"vf{idx}({vf_pci}):{actual}")
                else:
                    info = kernel_pci.get(vf_pci, {})
                    actual_drv = info.get("drv", "")
                    if actual_drv.lower() == exp_driver:
                        if info.get("ifname"):
                            correct += 1
                        else:
                            correct += 1
                            wrong.append(f"vf{idx}({vf_pci}):iavf-no_if(warn)")
                    else:
                        actual = actual_drv or dpdk_pci.get(vf_pci, "unbound")
                        sysinv_vfio_set = sysinv_vfio_pci.get(pf_kernel, set())
                        if actual == "vfio-pci" and (
                            vf_pci in sysinv_vfio_set
                            or _vf_covered_by_vfio_resource(vf_pci, idx, resources, pf_kernel)
                        ):
                            correct += 1
                            log(f"  [INFO] {hostname}/{res_name}: vf{idx}({vf_pci})"
                                f" is vfio-pci - sysinv vf child or pcidp resource"
                                f" (mixed config, expected)")
                        else:
                            wrong.append(f"vf{idx}({vf_pci}):{actual}")

            total = len(indices_to_check)
            devbind_dist = ", ".join(
                f"{drv}:{cnt}" for drv, cnt in sorted(actual_drv_counts.items())
            ) if actual_drv_counts else "no VFs resolved"

            real_wrong = [w for w in wrong if "iavf-no_if(warn)" not in w]
            warn_no_if = [w for w in wrong if "iavf-no_if(warn)" in w]

            if total == 0:
                log(f"  [INFO] {hostname}/{res_name} (PF={pf_kernel}): no VF indices to check")
            elif len(real_wrong) == 0:
                suffix = f" ({len(warn_no_if)} iavf VFs without netdev if=)" if warn_no_if else ""
                log_result(
                    f"  {hostname}/{res_name}"
                    f" (PF={pf_kernel}, exp_driver={exp_driver}, {idx_range}):"
                    f" {correct}/{total} VFs correct - devbind shows {devbind_dist}{suffix}",
                    "PASS",
                )
            else:
                log_result(
                    f"  {hostname}/{res_name}"
                    f" (PF={pf_kernel}, exp_driver={exp_driver}, {idx_range}):"
                    f" {correct - len(warn_no_if)}/{total} VFs correct - devbind shows {devbind_dist}",
                    "FAILED",
                )
                state.category_failures[cat].append(
                    f"{hostname}/{res_name}: {len(real_wrong)} VF(s) wrong in devbind "
                    f"(expected {exp_driver}): {real_wrong[:8]}"
                )


def _parse_numvfs(value):
    """Safely parse sriov_numvfs from sysinv - handles None, 'None', empty."""
    if not value or str(value).strip().lower() in ("none", ""):
        return 0
    try:
        return int(str(value).strip())
    except ValueError:
        return 0


def test_sriov():
    cat = "TestSuite 3 - SR-IOV and DPDK"
    desc = [
        "1) Identify hosts with SR-IOV PF interfaces",
        "2) Verify numvfs DB vs sysfs",
        "3) VF driver binding count: from DB (PF used_by VF children -> per-driver numvfs),",
        "   count sysfs uevent DRIVER= entries and compare per driver group",
        "4) Cross-check /etc/pcidp/config.json vs dpdk-devbind.py --status (all hosts):",
        "   - Each resourceList entry declares a PF, VF index range, and expected driver",
        "   - For each VF index range: verify dpdk-devbind shows the correct driver",
        "   - iavf VFs: must appear in 'kernel driver' section with if= populated",
        "   - vfio-pci VFs: must appear in 'DPDK-compatible driver' section",
        "   - PF itself must remain in 'kernel driver' (not bound to vfio-pci)",
        "5) Log PF driver and firmware info (informational)",
    ]
    print_category(cat, description=desc)

    if not tool_available("lspci"):
        log("[FAIL] lspci not available - required for SR-IOV checks")
        state.category_failures[cat].append("lspci not installed")
        return

    any_sriov_found = False
    for hostname in get_host_names():
        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, hostname, "SR-IOV kernel validation")
            continue

        ifaces = _get_if_list(hostname)
        sriov_ifaces = []
        for i in ifaces:
            if i.get("class") in ("pci-sriov", "sriov"):
                if i.get("type") == "vf":
                    continue
                show_data = _get_if_show(hostname, i.get("name", ""))
                numvfs = _parse_numvfs(show_data.get("sriov_numvfs"))
                if numvfs > 0:
                    i["_show"] = show_data
                    sriov_ifaces.append(i)
            elif i.get("type") == "ethernet":
                show_data = _get_if_show(hostname, i.get("name", ""))
                numvfs = _parse_numvfs(show_data.get("sriov_numvfs"))
                if numvfs > 0:
                    i["_show"] = show_data
                    sriov_ifaces.append(i)

        if not sriov_ifaces:
            log_result(f"host {hostname}: no SR-IOV PF interfaces configured", "PASS")
            continue

        any_sriov_found = True
        log(f"[HOST] {hostname} - SR-IOV interfaces found")

        vf_driver_map = {
            "netdevice": ("iavf", "igbvf", "ixgbevf", "mlx5_core", "virtio_net"),
            "vfio":      ("vfio-pci",),
        }

        for iface in sriov_ifaces:
            ifname = iface.get("name", "?")
            show_data = iface.get("_show") or _get_if_show(hostname, ifname)
            db_numvfs = _parse_numvfs(show_data.get("sriov_numvfs"))
            vf_driver = show_data.get("sriov_vf_driver", "")
            prefix = f"  {hostname}/{ifname}"

            port_name = show_data.get("ports", "")
            if isinstance(port_name, str):
                port_names = re.findall(r"'([^']+)'", port_name)
                kernel_ifname = port_names[0] if port_names else None
            else:
                kernel_ifname = None

            if not kernel_ifname:
                matched = next((i for i in ifaces if i.get("name") == ifname), None)
                kernel_ifname = (
                    _resolve_kernel_ifname(matched, ifaces) if matched else ifname
                )

            log(f"  [PF] {hostname}/{ifname}: kernel interface={kernel_ifname}"
                f"  DB numvfs={db_numvfs}  vf_driver={vf_driver or 'n/a'}"
                f"  used_by={iface.get('used_by', iface.get('used by i/f', '[]'))}")

            _, sysfs_out, _ = _run_on_host(
                hostname,
                f"cat /sys/class/net/{kernel_ifname}/device/sriov_numvfs"
            )
            try:
                kernel_numvfs = int(sysfs_out.strip())
            except ValueError:
                kernel_numvfs = -1

            log_result(
                f"  {hostname}/{ifname} ({kernel_ifname}):"
                f" DB={db_numvfs}, sysfs={kernel_numvfs}",
                "PASS" if kernel_numvfs == db_numvfs else "FAILED",
            )
            if kernel_numvfs != db_numvfs:
                state.category_failures[cat].append(
                    f"{hostname}/{ifname}: sriov_numvfs DB={db_numvfs} sysfs={kernel_numvfs}"
                )

            if not vf_driver:
                log(f"  [INFO] {hostname}/{ifname}: no VF driver info in DB - skipping binding count")
            else:
                accepted = vf_driver_map.get(vf_driver.lower(), (vf_driver.lower(),))
                kernel_drv_str = "/".join(accepted)

                sysfs_path = f"/sys/class/net/{kernel_ifname}/device/virtfn*/uevent"
                log(f"  [sysfs] {hostname}: reading {sysfs_path}")
                _, grep_out, _ = _run_on_host(
                    hostname,
                    f"grep -r '^DRIVER=' {sysfs_path} 2>/dev/null",
                    silent=True,
                )
                actual_by_driver = {}
                for line in (grep_out or "").splitlines():
                    m = re.search(r"DRIVER=(.+)", line)
                    kernel_drv = m.group(1).strip().lower() if m else "unbound"
                    actual_by_driver[kernel_drv] = actual_by_driver.get(kernel_drv, 0) + 1

                actual_count = sum(actual_by_driver.get(k, 0) for k in accepted)
                vfio_count = actual_by_driver.get("vfio-pci", 0)
                is_mixed_ok = (
                    actual_count != db_numvfs
                    and vfio_count > 0
                    and (actual_count + vfio_count) == db_numvfs
                )
                if is_mixed_ok:
                    log_result(
                        f"  {hostname}/{ifname}: sysinv_driver={vf_driver.lower()}"
                        f" (kernel={kernel_drv_str})"
                        f" - DB numvfs={db_numvfs}, sysfs uevent={actual_count} netdevice"
                        f" + {vfio_count} vfio-pci (mixed - expected)",
                        "PASS",
                    )
                else:
                    log_result(
                        f"  {hostname}/{ifname}: sysinv_driver={vf_driver.lower()}"
                        f" (kernel={kernel_drv_str})"
                        f" - DB numvfs={db_numvfs}, sysfs uevent={actual_count}",
                        "PASS" if actual_count == db_numvfs else "FAILED",
                    )
                    if actual_count != db_numvfs:
                        state.category_failures[cat].append(
                            f"{hostname}/{ifname}: DB numvfs={db_numvfs} but sysfs shows "
                            f"{actual_count} VFs with {vf_driver} ({accepted})"
                        )

        sysinv_vfio_pci = _build_sysinv_vfio_pci_map(hostname, ifaces)
        _test_sriov_pcidp_vs_devbind(cat, hostname, sysinv_vfio_pci)

        for iface in sriov_ifaces:
            ifname = iface.get("name", "?")
            show_data = iface.get("_show") or _get_if_show(hostname, ifname)
            port_name = show_data.get("ports", "")
            port_names = re.findall(r"'([^']+)'", port_name) if isinstance(port_name, str) else []
            kernel_ifname = port_names[0] if port_names else ifname
            if hostname == local_hostname():
                rc, ethtool_out, _ = run_log_only(["ethtool", "-i", kernel_ifname])
                if rc == 0:
                    for field in ("driver", "version", "firmware-version"):
                        m = re.search(rf"{field}:\s*(.+)", ethtool_out)
                        if m:
                            log(f"  [INFO] {hostname}/{ifname} PF {field}: {m.group(1).strip()}")

    if not any_sriov_found:
        log_result("no SR-IOV PF interfaces configured on any host", "PASS")
