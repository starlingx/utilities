# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import ipaddress
import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _get_addr_list
from network_platform_audit.sysinv import _get_addrpool_list
from network_platform_audit.sysinv import _get_iface_network_count
from network_platform_audit.sysinv import _get_sw_version
from network_platform_audit.sysinv import _parse_dhcp_leases
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def _collect_floating_ips():
    floating_ips = set()
    for pool in _get_addrpool_list():
        for field in ("floating_address", "floating_addr"):
            val = pool.get(field, "")
            if val and val not in ("None", "-", ""):
                floating_ips.add(val)
    return floating_ips


def _collect_dhcp_leased_ips():
    """IPs currently leased out by dnsmasq (e.g. pxeboot addrs picked up via
    dhclient on other hosts) are not expected to appear in the local sysinv DB.
    """
    leases = _parse_dhcp_leases()
    if leases:
        log(f"  dnsmasq.leases: {len(leases)} active lease(s) excluded from DB check")
        for lease in leases:
            log(f"    {lease['ip']}  mac={lease['mac']}  name={lease['hostname']}")
    else:
        log("  [INFO] no dnsmasq.leases entries found")
    return {lease["ip"] for lease in leases}


def _parse_kernel_addrs(kernel_out):
    kernel_ips = set()
    deprecated_ips = set()
    kernel_skip_ifaces = re.compile(r"(tunl|cali|vxlan\.calico|kube-ipvs|docker|flannel|virbr)")
    for line in kernel_out.splitlines():
        # Skip addresses on internal/virtual interfaces
        iface_m = re.match(r"\d+:\s+(\S+)", line)
        if iface_m and kernel_skip_ifaces.search(iface_m.group(1)):
            continue
        m = re.search(r"inet6?\s+([0-9a-fA-F:.]+)/", line)
        if m:
            kernel_ips.add(m.group(1))
        if "deprecated" in line:
            m2 = re.search(r"inet6?\s+([0-9a-fA-F:.]+)/", line)
            if m2:
                deprecated_ips.add(m2.group(1))
    return kernel_ips, deprecated_ips


def _check_db_addr_in_kernel(cat, hostname, ip, kernel_ips):
    if ip in kernel_ips:
        log_result(f"  {hostname}: {ip} in kernel", "PASS")
    else:
        log_result(f"  {hostname}: {ip} in kernel", "FAILED")
        state.category_failures[cat].append(f"{hostname}: address {ip} in DB but not in kernel")


def _check_deprecated(cat, hostname, ip, addr, local_sw_ver, ifname_to_network_count):
    try:
        is_ipv6 = ipaddress.ip_address(ip).version == 6
    except ValueError:
        is_ipv6 = False

    if is_ipv6 and local_sw_ver is not None and local_sw_ver < (26, 3, 0):
        # deprecated is expected for non-preferred network on shared interfaces
        ifname = addr.get("ifname", addr.get("interface", ""))
        net_count = ifname_to_network_count.get(ifname, 1)
        if net_count > 1:
            log_result(f"  {hostname}: {ip} is deprecated in kernel (shared iface)", "PASS")
        else:
            log_result(f"  {hostname}: {ip} is deprecated in kernel", "FAILED")
            state.category_failures[cat].append(
                f"{hostname}: address {ip} is deprecated in kernel")
    else:
        # all IPv6 must be non-deprecated
        log_result(f"  {hostname}: {ip} is deprecated in kernel", "FAILED")
        state.category_failures[cat].append(
            f"{hostname}: address {ip} is deprecated in kernel")


def _warn_kernel_extra_addrs(cat, hostname, kernel_ips, db_ip_set, floating_ips, dhcp_leased_ips):
    for kip in kernel_ips:
        try:
            addr_obj = ipaddress.ip_address(kip)
            if addr_obj.is_link_local or addr_obj.is_loopback:
                continue
        except ValueError:
            continue
        if kip in dhcp_leased_ips:
            continue
        if kip not in db_ip_set and kip not in floating_ips:
            log(f"  [WARN] {hostname}: kernel address {kip} not in sysinv DB")
            state.category_warnings[cat].append(f"{hostname}: kernel address {kip} not in DB")


def test_addresses_vs_kernel():
    cat = "TestSuite 4 - Address Validation"
    desc = [
        "1) system host-addr-list per host",
        "2) Verify each DB address is assigned in kernel (ip -o addr show)",
        "3) Warn on kernel addresses not in DB (floating IPs and DHCP-leased IPs excluded)",
        "4) Deprecated address check",
    ]
    print_category(cat, description=desc)

    floating_ips = _collect_floating_ips()
    dhcp_leased_ips = _collect_dhcp_leased_ips()

    local_sw_ver = _get_sw_version(local_hostname())
    if local_sw_ver is not None:
        log(f"  sw_version={local_sw_ver[0]:02d}.{local_sw_ver[1]:02d}.{local_sw_ver[2]:03d}  "
            f"shared-iface-deprecated={'expected' if local_sw_ver < (26, 3, 0) else 'not expected'}")
    else:
        log("  [WARN] could not read sw_version - deprecated IPv6 check uses strict mode")

    for hostname in get_host_names():
        log(f"[HOST] {hostname}")
        db_addrs = _get_addr_list(hostname)
        if not db_addrs:
            log(f"  [INFO] no addresses found for {hostname}")
            continue

        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, hostname, "address kernel validation")
            continue

        rc, kernel_out, _ = _run_on_host(hostname, "ip -o addr show")
        if rc != 0 or not kernel_out:
            state.category_failures[cat].append(f"{hostname}: failed to run ip -o addr show")
            continue

        kernel_ips, deprecated_ips = _parse_kernel_addrs(kernel_out)

        # Build ifname -> number of network types map for shared-interface check
        ifname_to_network_count = {}
        if local_sw_ver is not None and local_sw_ver < (26, 3, 0):
            ifname_to_network_count = _get_iface_network_count(hostname)

        db_ip_set = set()
        for addr in db_addrs:
            ip = addr.get("address", addr.get("ip_address", ""))
            if not ip:
                continue
            db_ip_set.add(ip)

            _check_db_addr_in_kernel(cat, hostname, ip, kernel_ips)

            if ip in deprecated_ips and ip not in floating_ips:
                _check_deprecated(cat, hostname, ip, addr, local_sw_ver, ifname_to_network_count)

        _warn_kernel_extra_addrs(cat, hostname, kernel_ips, db_ip_set, floating_ips, dhcp_leased_ips)
