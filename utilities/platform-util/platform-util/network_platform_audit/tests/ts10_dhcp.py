# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import ipaddress
import os
import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run
from network_platform_audit.run import run_checked
from network_platform_audit.run import run_log_only
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _detect_dnsmasq_file
from network_platform_audit.sysinv import _parse_dhcp_leases
from network_platform_audit.sysinv import _parse_generic_table
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import _run_system_list
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def _get_pxeboot_iface():
    """Detect pxeboot interface name by looking for pxeboot address in ip addr."""
    rc, out, _ = _run_system_list("system addrpool-list")
    pxe_subnet = ""
    if rc == 0 and out:
        for pool in _parse_generic_table(out, key_col="name"):
            if "pxeboot" in pool.get("name", "").lower():
                pxe_subnet = pool.get("network", "")
                break
    if not pxe_subnet:
        return None
    rc, out, _ = run_log_only(["ip", "route", "show", pxe_subnet])
    m = re.search(r"dev (\S+)", out or "")
    return m.group(1) if m else None


def _find_dhcp_ifaces(interfaces_dir):
    dhcp_ifaces = []
    if os.path.isdir(interfaces_dir):
        for fname in os.listdir(interfaces_dir):
            if not fname.startswith("ifcfg-"):
                continue
            try:
                with open(os.path.join(interfaces_dir, fname)) as f:
                    content = f.read()
                m = re.search(r"iface\s+(\S+)\s+inet\s+dhcp", content)
                if m:
                    dhcp_ifaces.append(m.group(1))
            except Exception:
                continue
    return dhcp_ifaces


def _check_dhclient_running(cat, dhcp_ifaces):
    if dhcp_ifaces:
        _, ps_out, _ = run_log_only("ps -ef")
        for iface in dhcp_ifaces:
            if re.search(rf"dhclient.*{re.escape(iface)}", ps_out or ""):
                log_result(f"dhclient running for {iface}", "PASS")
            else:
                log_result(f"dhclient running for {iface}", "FAILED")
                state.category_failures[cat].append(f"dhclient not running for DHCP interface {iface}")
    else:
        log("[INFO] no DHCP-enabled interfaces found")


def _read_addn_hosts_entries(cat, addn_hosts_path):
    entries = []
    if addn_hosts_path and os.path.exists(addn_hosts_path):
        log(f"  Analyzing file: {addn_hosts_path}")
        try:
            with open(addn_hosts_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    entries.append((parts[0], parts[1]))
        except Exception as e:
            state.category_failures[cat].append(f"failed to read dnsmasq.addn_hosts: {e}")
    else:
        log("[INFO] dnsmasq.addn_hosts not found")
    return entries


def _check_addn_hosts_on_host(cat, hostname, entries):
    log(f"  [HOST] {hostname}")
    if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
        ssh_check_remote(cat, hostname, "dnsmasq.addn_hosts resolution")
        return

    failed = []
    for ip, entry_hostname in entries:
        entry_failed, stop = _check_host_entry_resolution(hostname, ip, entry_hostname)
        failed.extend(entry_failed)
        if stop:
            break

    if failed:
        for msg in failed:
            state.category_failures[cat].append(f"{hostname}: dnsmasq.addn_hosts resolution: {msg}")


def _check_addn_hosts_all_hosts(cat, entries):
    if entries:
        log("")
        log("[INFO] verifying dnsmasq.addn_hosts name resolution on all hosts...")
        for hostname in get_host_names():
            _check_addn_hosts_on_host(cat, hostname, entries)


def _check_addn_conf(cat, addn_conf_path):
    if addn_conf_path and os.path.exists(addn_conf_path):
        try:
            with open(addn_conf_path) as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("host-record="):
                        continue
                    parts = line.split("=", 1)[1].split(",")
                    for token in parts[1:]:
                        token = token.strip()
                        try:
                            ipaddress.ip_address(token)
                        except ValueError:
                            continue
                        flag = "-6" if ":" in token else ""
                        rc, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", token])
                        if rc == 0:
                            log_result(f"host-record {parts[0]} ({token}) reachable", "PASS")
                        else:
                            log_result(f"host-record {parts[0]} ({token}) reachable", "FAILED")
                            state.category_failures[cat].append(f"host-record {parts[0]} ({token}) unreachable")
        except Exception as e:
            state.category_failures[cat].append(f"failed to read dnsmasq.addn_conf: {e}")


def _check_dhcp_tftp_ports(cat):
    pxe_iface = _get_pxeboot_iface()
    rc, ss_out, _ = run_log_only("ss -ulnp sport = :67 or sport = :69")
    if pxe_iface and ss_out:
        if ":67 " in ss_out or ":67\t" in ss_out:
            log_result(f"dnsmasq DHCP port 67 listening (pxeboot iface: {pxe_iface})", "PASS")
        else:
            log_result(f"dnsmasq DHCP port 67 listening (pxeboot iface: {pxe_iface})", "FAILED")
            state.category_failures[cat].append("dnsmasq not listening on UDP port 67 (DHCP)")
    else:
        run_checked("ss -ulnp | grep ':67 '")

    if ss_out and ":69 " in ss_out:
        log_result("TFTP port 69 in LISTEN", "PASS")
    else:
        log_result("TFTP port 69 in LISTEN", "FAILED")
        state.category_failures[cat].append("UDP port 69 (TFTP) not listening")


def _check_leases_file():
    leases_file = _detect_dnsmasq_file("dnsmasq.leases")
    if leases_file and os.path.exists(leases_file):
        log_result("dnsmasq.leases file found", "PASS")
    else:
        log("[INFO] dnsmasq.leases not found")


def _read_hosts_entries(cat):
    hosts_entries = []
    try:
        with open("/etc/hosts") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                ip = parts[0]
                for name in parts[1:]:
                    hosts_entries.append((ip, name))
    except Exception as e:
        state.category_failures[cat].append(f"failed to read /etc/hosts: {e}")
        hosts_entries = []
    return hosts_entries


def _check_host_entry_resolution(hostname, ip, name):
    failed = []
    if hostname == local_hostname():
        rc, out, _ = run(["getent", "hosts", name])
    else:
        rc, out, _ = _run_on_host(hostname, ["getent", "hosts", name], silent=False)
    if rc is None:
        log(f"  [SKIP] SSH unavailable for {hostname} - skipping /etc/hosts checks")
        return failed, True

    resolved = out.split()[0] if rc == 0 and out.strip() else ""
    if resolved == ip:
        log_result(f"  [{hostname}] {name} -> {ip}", "PASS")
    else:
        got = resolved if resolved else "no result"
        log_result(f"  [{hostname}] {name} -> {ip} (got: {got})", "FAILED")
        failed.append(f"{name}: expected {ip}, got {got}")
        return failed, False

    if ip in ("127.0.0.1", "::1"):
        return failed, False

    flag = "-6" if ":" in ip else ""
    if hostname == local_hostname():
        rc2, _, _ = run(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", ip])
    else:
        ping_cmd = ["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", ip]
        rc2, _, _ = _run_on_host(hostname, ping_cmd, silent=False)
    if rc2 == 0:
        log_result(f"  [{hostname}] ping {name} ({ip})", "PASS")
    else:
        log_result(f"  [{hostname}] ping {name} ({ip})", "FAILED")
        failed.append(f"{name} ({ip}): unreachable via ping")

    return failed, False


def _check_hosts_resolution_on_host(cat, hostname, hosts_entries):
    log(f"  [HOST] {hostname}")
    if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
        ssh_check_remote(cat, hostname, "/etc/hosts resolution")
        return

    failed = []
    for ip, name in hosts_entries:
        entry_failed, stop = _check_host_entry_resolution(hostname, ip, name)
        failed.extend(entry_failed)
        if stop:
            break

    if failed:
        for msg in failed:
            state.category_failures[cat].append(f"{hostname}: /etc/hosts resolution: {msg}")


def _get_host_mac_to_iface(hostname):
    """Return {mac: ifname} for a host's kernel interfaces via `ip -o link show`."""
    mac_to_iface = {}
    rc, out, _ = _run_on_host(hostname, "ip -o link show", silent=True)
    if rc != 0 or not out:
        return mac_to_iface
    for line in out.splitlines():
        m = re.match(r"\d+:\s+(\S+?)(?:@\S+)?:.*link/ether\s+([0-9a-fA-F:]+)", line)
        if m:
            mac_to_iface[m.group(2).lower()] = m.group(1)
    return mac_to_iface


def _get_host_kernel_ips(hostname):
    """Return the set of IPs currently assigned in a host's kernel."""
    ips = set()
    rc, out, _ = _run_on_host(hostname, "ip -o addr show", silent=True)
    if rc != 0 or not out:
        return ips
    for line in out.splitlines():
        m = re.search(r"inet6?\s+([0-9a-fA-F:.]+)/", line)
        if m:
            ips.add(m.group(1))
    return ips


def _check_dhcp_leases_assigned(cat):
    """Verify each active dnsmasq lease is actually assigned on the host owning
    the leased MAC address (e.g. a pxeboot IP handed to compute-0 must show up
    in compute-0's kernel, not just in the lease file).
    """
    leases = _parse_dhcp_leases()
    if not leases:
        log("[INFO] no dnsmasq.leases entries found")
        return

    log("")
    log("[INFO] verifying dnsmasq leases are assigned to the correct host...")

    host_macs = {}
    host_ips = {}
    for hostname in get_host_names():
        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            log(f"  [INFO] {hostname}: SSH unavailable - skipping DHCP lease verification")
            continue
        host_macs[hostname] = _get_host_mac_to_iface(hostname)
        host_ips[hostname] = _get_host_kernel_ips(hostname)

    for lease in leases:
        mac = lease["mac"]
        ip = lease["ip"]
        lease_name = lease["hostname"]

        owner, iface = None, None
        for hostname, macs in host_macs.items():
            if mac in macs:
                owner, iface = hostname, macs[mac]
                break

        if owner is None:
            log(f"  [INFO] lease {ip} ({lease_name}, mac {mac}): "
                f"no matching host interface found (stale lease?)")
            continue

        if ip in host_ips.get(owner, set()):
            log_result(f"  DHCP lease {ip} ({lease_name}) assigned on {owner}/{iface}", "PASS")
        else:
            log_result(f"  DHCP lease {ip} ({lease_name}) assigned on {owner}/{iface}", "FAILED")
            state.category_failures[cat].append(
                f"DHCP lease {ip} (mac {mac}) matched to {owner} but not assigned in kernel")


def _check_hosts_resolution_all_hosts(cat, hosts_entries):
    if hosts_entries:
        log("")
        log("[INFO] verifying /etc/hosts name resolution on all hosts...")
        for hostname in get_host_names():
            _check_hosts_resolution_on_host(cat, hostname, hosts_entries)


def test_dhcp_extended():
    cat = "TestSuite 10 - dnsmasq / DHCP"
    desc = [
        "1) Check DHCP client (dhclient) running for DHCP interfaces",
        "2) Resolve hostnames from dnsmasq addn_hosts on all hosts (local + remote via SSH)",
        "3) Ping dnsmasq host-record IPs",
        "4) Verify dnsmasq DHCP socket on pxeboot (UDP 67)",
        "5) Verify TFTP port (UDP 69) in LISTEN",
        "6) Verify dnsmasq.leases file exists",
        "7) Verify /etc/hosts name resolution on all hosts (local + remote via SSH)",
        "8) Verify dnsmasq leases are assigned to the correct host in kernel",
    ]
    print_category(cat, description=desc)

    interfaces_dir = "/etc/network/interfaces.d"
    dhcp_ifaces = _find_dhcp_ifaces(interfaces_dir)
    _check_dhclient_running(cat, dhcp_ifaces)

    addn_hosts_path = _detect_dnsmasq_file("dnsmasq.addn_hosts")
    addn_hosts_entries = _read_addn_hosts_entries(cat, addn_hosts_path)
    _check_addn_hosts_all_hosts(cat, addn_hosts_entries)

    addn_conf_path = _detect_dnsmasq_file("dnsmasq.addn_conf")
    _check_addn_conf(cat, addn_conf_path)

    _check_dhcp_tftp_ports(cat)

    _check_leases_file()

    hosts_entries = _read_hosts_entries(cat)

    _check_hosts_resolution_all_hosts(cat, hosts_entries)

    _check_dhcp_leases_assigned(cat)
