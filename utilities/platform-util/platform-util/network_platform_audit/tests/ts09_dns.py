# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run
from network_platform_audit.run import run_log_only
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def _get_sysinv_nameservers():
    rc, dns_out, _ = run_log_only("system dns-show")
    sysinv_ns = []
    if rc == 0 and dns_out:
        m = re.search(r"nameservers\s*\|\s*([^\|]+)", dns_out)
        if m:
            sysinv_ns = [ns.strip() for ns in m.group(1).split(",") if ns.strip()]
    return sysinv_ns


def _get_resolv_conf_nameservers():
    resolv_ns = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        resolv_ns.append(parts[1])
    except Exception:
        pass
    return resolv_ns


def _check_sysinv_ns_in_resolv_conf(cat, sysinv_ns, resolv_ns):
    for ns in sysinv_ns:
        if ns in resolv_ns:
            log_result(f"nameserver {ns} in /etc/resolv.conf", "PASS")
        else:
            log_result(f"nameserver {ns} in /etc/resolv.conf", "FAILED")
            state.category_failures[cat].append(f"nameserver {ns} in sysinv but not in /etc/resolv.conf")


def _probe_nameservers(all_ns, resolv_ns):
    """Probe each nameserver and report reachability.

    A nameserver is considered reachable if ping succeeds AND at least one of
    TCP-53 or UDP-53 succeeds.  The overall result is evaluated against the
    set of nameservers that appear in /etc/resolv.conf:

    - All resolv.conf nameservers unreachable  -> FAILED (DNS resolution is
      completely broken).
    - Some (but not all) resolv.conf nameservers unreachable -> WARNING
      (partial availability).
    - All resolv.conf nameservers reachable    -> PASS.

    Nameservers present only in sysinv (not in /etc/resolv.conf) are probed
    for informational purposes but do not affect the overall severity.
    """
    cat = state.current_category
    reachable_resolv = 0
    unreachable_resolv = []

    for ns in all_ns:
        flag = "-6" if ":" in ns else ""
        # Use run() (not run_checked) so individual probe failures do not
        # automatically populate category_failures; we handle severity below.
        rc_ping, _, _ = run(["ping"] + ([flag] if flag else []) + ["-c", "2", "-W", "2", ns])
        rc_tcp, _, _ = run(["nc", "-vz", "-w", "2", ns, "53"])
        rc_udp, _, _ = run(["nc", "-vzu", "-w", "2", ns, "53"])
        log("")

        ns_reachable = rc_ping == 0 and (rc_tcp == 0 or rc_udp == 0)

        if ns in resolv_ns:
            if ns_reachable:
                reachable_resolv += 1
            else:
                unreachable_resolv.append(ns)

    # Determine severity only from resolv.conf nameservers.
    total_resolv = len(resolv_ns)
    if total_resolv == 0:
        # No nameservers in resolv.conf at all — nothing to judge here.
        return

    if unreachable_resolv and reachable_resolv == 0:
        # Every configured nameserver is down — DNS is completely non-functional.
        log_result("DNS server reachability (/etc/resolv.conf)", "FAILED")
        for ns in unreachable_resolv:
            state.category_failures[cat].append(
                f"DNS nameserver {ns} is unreachable (ping, TCP-53, and UDP-53 all failed)"
            )
    elif unreachable_resolv:
        # At least one is reachable — partial availability, report as warning.
        log_result("DNS server reachability (/etc/resolv.conf)", "WARNING")
        for ns in unreachable_resolv:
            state.category_warnings[cat].append(
                f"DNS nameserver {ns} is unreachable (ping, TCP-53, and UDP-53 all failed)"
            )
    else:
        log_result("DNS server reachability (/etc/resolv.conf)", "PASS")


def _check_resolve_platform_hostnames_on_host(cat, hostname):
    for target in ("controller-0", "controller"):
        rc, out, _ = _run_on_host(hostname, ["getent", "hosts", target], silent=False)
        if rc is None:
            ssh_check_remote(cat, hostname, f"resolve {target}")
            continue
        if rc == 0 and out.strip():
            log_result(f"  [{hostname}] resolve {target}", "PASS")
        else:
            log_result(f"  [{hostname}] resolve {target}", "FAILED")
            state.category_failures[cat].append(
                f"{hostname}: hostname {target!r} did not resolve"
            )


def _check_resolve_platform_hostnames(cat):
    for hostname in get_host_names():
        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, hostname, "platform hostname resolution")
            continue
        _check_resolve_platform_hostnames_on_host(cat, hostname)


def test_dns_extended():
    cat = "TestSuite 9 - DNS"
    desc = [
        "1) system dns-show - get configured nameservers",
        "2) Compare vs /etc/resolv.conf",
        "3) Ping each nameserver (ICMP)",
        "4) Test TCP port 53 and UDP port 53",
        "5) Resolve platform hostnames (controller-0, controller) on all "
        "hosts (local + remote via SSH)",
    ]
    print_category(cat, description=desc)

    sysinv_ns = _get_sysinv_nameservers()
    resolv_ns = _get_resolv_conf_nameservers()

    _check_sysinv_ns_in_resolv_conf(cat, sysinv_ns, resolv_ns)

    all_ns = list(dict.fromkeys(sysinv_ns + resolv_ns))
    _probe_nameservers(all_ns, resolv_ns)

    _check_resolve_platform_hostnames(cat)
