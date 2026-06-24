# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

from network_platform_audit import state
from network_platform_audit.kube import _get_coredns_pid
from network_platform_audit.log import log
from network_platform_audit.log import print_category
from network_platform_audit.run import run_checked
from network_platform_audit.run import tool_available


def _check_required_tools(cat):
    if not tool_available("crictl"):
        log("[FAIL] crictl not available - required for CoreDNS checks")
        state.category_failures[cat].append("crictl not installed")
        return False
    if not tool_available("nsenter"):
        log("[FAIL] nsenter not available - required for CoreDNS checks")
        state.category_failures[cat].append("nsenter not installed")
        return False
    return True


def _ns_nslookup(pid, hostname):
    return run_checked(["nsenter", "-n", "-t", pid, "--", "nslookup", hostname])


def _check_ns_resolve(cat, pid, hostname, fail_msg):
    rc, out, _ = _ns_nslookup(pid, hostname)
    if rc != 0 or not out or "Address" not in out:
        state.category_failures[cat].append(fail_msg)


def test_coredns():
    cat = "TestSuite 14 - CoreDNS"
    desc = [
        "1) Find coredns pod PID via crictl",
        "2) Use nsenter -n to enter coredns network namespace",
        "3) Resolve kubernetes.default.svc.cluster.local",
        "4) Resolve controller-0 (CoreDNS -> dnsmasq -> platform)",
    ]
    print_category(cat, description=desc)

    if not _check_required_tools(cat):
        return

    pid = _get_coredns_pid()
    if not pid:
        log("[SKIP] could not find coredns pod PID - skipping CoreDNS tests")
        state.category_failures[cat].append("coredns pod PID not found")
        return

    log(f"[INFO] coredns pod sandbox PID: {pid} (used for network namespace)")

    _check_ns_resolve(cat, pid, "kubernetes.default.svc.cluster.local",
                      "CoreDNS: failed to resolve kubernetes.default.svc.cluster.local")

    _check_ns_resolve(cat, pid, "controller-0",
                      "CoreDNS: failed to resolve controller-0 (dnsmasq forward)")
