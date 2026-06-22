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
from network_platform_audit.sysinv import _parse_generic_table
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
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


def _get_pxeboot_iface():
    """Detect pxeboot interface name by looking for pxeboot address in ip addr."""
    rc, out, _ = run_log_only("system addrpool-list")
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


def test_dhcp_extended():
    cat = "TestSuite 10 - dnsmasq / DHCP"
    desc = [
        "1) Check DHCP client (dhclient) running for DHCP interfaces",
        "2) Resolve hostnames from dnsmasq addn_hosts",
        "3) Ping dnsmasq host-record IPs",
        "4) Verify dnsmasq DHCP socket on pxeboot (UDP 67)",
        "5) Verify TFTP port (UDP 69) in LISTEN",
        "6) Verify dnsmasq.leases file exists",
        "7) Verify /etc/hosts name resolution on all hosts (local + remote via SSH)",
    ]
    print_category(cat, description=desc)

    interfaces_dir = "/etc/network/interfaces.d"
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

    addn_hosts_path = _detect_dnsmasq_file("dnsmasq.addn_hosts")
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
                    ip, entry_hostname = parts[0], parts[1]
                    rc, out, _ = run_log_only(["getent", "hosts", entry_hostname])
                    if rc == 0 and ip in out:
                        log_result(f"dnsmasq host {entry_hostname} resolves to {ip}", "PASS")
                    else:
                        log_result(f"dnsmasq host {entry_hostname} resolves to {ip}", "FAILED")
                        state.category_failures[cat].append(f"dnsmasq host {entry_hostname} does not resolve to {ip}")
                    flag = "-6" if ":" in ip else ""
                    rc2, _, _ = run_log_only(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", ip])
                    if rc2 != 0:
                        log(f"  [WARN] {entry_hostname} ({ip}) not reachable via ping")
                        state.category_warnings[cat].append(f"dnsmasq host {entry_hostname} ({ip}) not reachable")
        except Exception as e:
            state.category_failures[cat].append(f"failed to read dnsmasq.addn_hosts: {e}")
    else:
        log("[INFO] dnsmasq.addn_hosts not found")

    addn_conf_path = _detect_dnsmasq_file("dnsmasq.addn_conf")
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

    leases_file = _detect_dnsmasq_file("dnsmasq.leases")
    if leases_file and os.path.exists(leases_file):
        log_result("dnsmasq.leases file found", "PASS")
    else:
        log("[INFO] dnsmasq.leases not found")

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

    if hosts_entries:
        log("")
        log("[INFO] verifying /etc/hosts name resolution on all hosts...")
        for hostname in get_host_names():
            log(f"  [HOST] {hostname}")
            if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
                ssh_check_remote(cat, hostname, "/etc/hosts resolution")
                continue

            failed = []
            for ip, name in hosts_entries:
                if hostname == local_hostname():
                    rc, out, _ = run(["getent", "hosts", name])
                else:
                    rc, out, _ = _run_on_host(hostname, ["getent", "hosts", name], silent=False)
                if rc is None:
                    log(f"  [SKIP] SSH unavailable for {hostname} - skipping /etc/hosts checks")
                    break
                resolved = out.split()[0] if rc == 0 and out.strip() else ""
                if resolved == ip:
                    log_result(f"  [{hostname}] {name} -> {ip}", "PASS")
                else:
                    got = resolved if resolved else "no result"
                    log_result(f"  [{hostname}] {name} -> {ip} (got: {got})", "FAILED")
                    failed.append(f"{name}: expected {ip}, got {got}")
                    continue

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

            if failed:
                for msg in failed:
                    state.category_failures[cat].append(f"{hostname}: /etc/hosts resolution: {msg}")
