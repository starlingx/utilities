# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# ---------------------------------------------------------------------------
# network_platform_audit - Platform Network Diagnostic Tool
# ---------------------------------------------------------------------------
#
# Purpose:
#   Validates the platform network configuration by cross-checking the sysinv
#   database against the live kernel state, Kubernetes cluster, and active
#   platform services.  Each test suite focuses on a specific layer of the
#   platform network stack (interfaces, addresses, routes, DNS, heartbeat,
#   IPsec, Kubernetes networking, and GNP firewall rules).
#
# Requirements:
#   - Must be run as root on the active controller (controller-0 or
#     controller-1).
#   - /etc/platform/openrc must exist and source correctly.
#   - Platform services (sysinv, Keystone) must be running.
#
# Usage:
#   sudo network_platform_audit [options]          # bundled script
#   sudo python3 -m network_platform_audit [opts]  # Python package
#   sudo network_platform_audit --help             # full option list
#
# Options:
#   --ssh-pass PASSWORD        SSH password for remote hosts (sshpass required).
#                              Omit to skip all remote kernel checks.
#                              Use --ssh-pass alone (no value) to be prompted.
#   --test TEST_NAME           Run only the specified test suite (see list below).
#   --verbose                  Mirror log-only output (commands, stdout, stderr)
#                              to the console in addition to the log file.
#   --pause                    Pause between test categories (interactive mode).
#   --log-file PATH            Log file path (default: /var/log/network_diag.log).
#   --subcloud NAME            DC: restrict subcloud tests to a single subcloud.
#   --subcloud-range A B       DC: restrict subcloud tests to a range [A..B].
#   --subcloud-oam-ip IP       DC: OAM IP for SSH into the subcloud controller.
#
# Available tests (--test argument):
#   host_availability    Host availability and operational state
#   if_vs_kernel         Interface type/MTU/VLAN/bond vs kernel (all hosts)
#   sriov                SR-IOV numvfs, VF driver bindings, dpdk-devbind
#   addr_vs_kernel       DB addresses vs kernel ip addr show (all hosts)
#   routes_vs_kernel     Static routes in DB vs kernel routing table
#   ports                PCI addresses and drivers vs lspci/ethtool
#   lldp                 LLDP neighbors in DB vs lldpctl
#   addrpool             Floating IPs, gateways, pool overlaps
#   dns                  Nameservers vs resolv.conf, ICMP+TCP+UDP+resolution
#   dhcp                 dnsmasq sockets, leases vs host-list, TFTP
#   heartbeat            hbsAgent/hbsClient sockets and multicast subnet
#   ipsec                Pxeboot port 64764 and swanctl SAs
#   k8s_nodes            Kubernetes node, pod, and endpoint status
#   coredns              CoreDNS internal, platform, and external resolution
#   cluster_nat          DNAT functional and cross-node connectivity
#   gnp                  GlobalNetworkPolicy vs addrpool subnets and iptables
#   endpoints            OpenStack endpoint ports in LISTEN and accessible
#   mtu_functional       Full-size ping per interface MTU (IPv4+IPv6, DF bit)
#   dc_systemcontroller  DC: subcloud gateway, DNS, routes, GNP, L4 ports
#   dc_subcloud          DC: system controller route, gateway, ping, TCP, IPsec
#
# Output:
#   - Real-time per-check results printed to stdout.
#   - Full log written to /var/log/network_diag.log (overridable with
#     --log-file).  The log includes every command executed, its exit code,
#     stdout, and stderr, in addition to the PASS/FAILED/WARN verdicts.
#   - Final summary table printed at the end showing the overall verdict per
#     test suite.
#
# Generating the on-system script:
#   The tool can be packaged as a single self-contained executable using the
#   bundler script.  Run from the root of the source tree:
#
#     python3 tools/bundle_network_platform_audit.py -o network_platform_audit
#
#   This produces a standalone file that can be copied directly to the target
#   controller and executed without installing the package:
#
#     scp network_platform_audit controller-0:/tmp/
#     ssh controller-0 "sudo /tmp/network_platform_audit --ssh-pass PASSWORD"

import argparse
import getpass
import os
import sys

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_to_file_only
from network_platform_audit.log import print_category
from network_platform_audit.run import tool_available
from network_platform_audit.ssh import close_all_sessions
from network_platform_audit.sysinv import startup_checks
from network_platform_audit.tests.ts01_availability import test_host_availability
from network_platform_audit.tests.ts02_interfaces import test_interfaces_vs_kernel
from network_platform_audit.tests.ts03_sriov import test_sriov
from network_platform_audit.tests.ts04_addresses import test_addresses_vs_kernel
from network_platform_audit.tests.ts05_routes import test_routes_vs_kernel
from network_platform_audit.tests.ts06_ports import test_host_ports
from network_platform_audit.tests.ts07_lldp import test_lldp
from network_platform_audit.tests.ts08_addrpools import test_addrpools
from network_platform_audit.tests.ts09_dns import test_dns_extended
from network_platform_audit.tests.ts10_dhcp import test_dhcp_extended
from network_platform_audit.tests.ts11_heartbeat import test_heartbeat_extended
from network_platform_audit.tests.ts12_ipsec import test_ipsec
from network_platform_audit.tests.ts13_k8s import test_k8s_nodes
from network_platform_audit.tests.ts14_coredns import test_coredns
from network_platform_audit.tests.ts15_cluster_nat import test_cluster_nat
from network_platform_audit.tests.ts16_gnp import test_gnp_firewall
from network_platform_audit.tests.ts17_openstack import test_openstack_endpoints
from network_platform_audit.tests.ts18_mtu import test_mtu_functional
from network_platform_audit.tests.ts19_dc_systemcontroller import test_dc_systemcontroller
from network_platform_audit.tests.ts20_dc_subcloud import test_dc_subcloud


AVAILABLE_TESTS = {
    "host_availability":     (test_host_availability,      "sysinv host availability and operational state"),
    "if_vs_kernel":          (test_interfaces_vs_kernel,   "interface type/MTU/VLAN/bond vs kernel (all hosts)"),
    "sriov":                 (test_sriov,                  "SR-IOV numvfs, VF MACs, driver/firmware info"),
    "addr_vs_kernel":        (test_addresses_vs_kernel,    "DB addresses vs kernel ip addr show (all hosts)"),
    "routes_vs_kernel":      (test_routes_vs_kernel,       "static routes in DB vs kernel routing table"),
    "ports":                 (test_host_ports,             "PCI addresses and drivers vs lspci/ethtool"),
    "lldp":                  (test_lldp,                   "LLDP neighbors in DB vs lldpctl"),
    "addrpool":              (test_addrpools,              "floating IPs, gateways, pool overlaps"),
    "dns":                   (test_dns_extended,           "nameservers vs resolv.conf, ICMP+TCP+UDP+resolution"),
    "dhcp":                  (test_dhcp_extended,          "dnsmasq sockets, leases vs host-list, TFTP"),
    "heartbeat":             (test_heartbeat_extended,     "hbsAgent/hbsClient sockets and multicast subnet"),
    "ipsec":                 (test_ipsec,                  "pxeboot port 64764 and swanctl SAs"),
    "k8s_nodes":             (test_k8s_nodes,              "Kubernetes node, pod, and endpoint status"),
    "coredns":               (test_coredns,                "CoreDNS internal, platform, and external resolution"),
    "cluster_nat":           (test_cluster_nat,            "DNAT functional and cross-node connectivity"),
    "gnp":                   (test_gnp_firewall,           "GlobalNetworkPolicy vs addrpool subnets and iptables"),
    "endpoints":             (test_openstack_endpoints,    "OpenStack endpoint ports in LISTEN and accessible"),
    "mtu_functional":        (test_mtu_functional,         "full-size ping per interface MTU (IPv4+IPv6, DF bit)"),
    "dc_systemcontroller":   (test_dc_systemcontroller,   "subcloud gateway, DNS, routes, GNP, L4 ports"),
    "dc_subcloud":           (test_dc_subcloud,            "system controller route, gateway, ping, TCP, IPsec, DNS"),
}


def write_summary():
    col1, col2 = 51, 10

    log("")
    log("=" * 120)
    log("Final Report")
    log("=" * 120)
    log(f"{'TestCategory':{col1}} | {'Result':{col2}} | FailureReason")
    log("=" * 120)

    all_pass = True
    all_warn = False
    for cat in state.executed_categories:
        fails = list(dict.fromkeys(state.category_failures.get(cat, [])))
        warns = list(dict.fromkeys(state.category_warnings.get(cat, [])))

        if not fails and not warns:
            log(f"{cat:{col1}} | {'PASS':{col2}} | -")
        elif fails:
            all_pass = False
            log(f"{cat:{col1}} | {'FAILED':{col2}} | - {fails[0]}")
            for f in fails[1:]:
                log(f"{'':{col1}} | {'':{col2}} | - {f}")
        else:
            all_warn = True
            log(f"{cat:{col1}} | {'WARN':{col2}} | - {warns[0]}")
            for w in warns[1:]:
                log(f"{'':{col1}} | {'':{col2}} | - {w}")

    log("=" * 120)

    if all_pass and not all_warn:
        log("")
        log("All tests passed.")

    if state.REMOTE_KERNEL_SKIPPED:
        log("")
        log("=" * 120)
        log("[WARN] Remote kernel validations were SKIPPED for one or more hosts.")
        log("[WARN] Provide --ssh-pass to enable kernel checks on remote nodes.")
        log("=" * 120)


def write_report():
    """Close the log file. Content already written in real-time."""
    if state.REPORT_FD:
        try:
            state.REPORT_FD.close()
        except Exception:
            pass
        state.REPORT_FD = None
    log(f"[INFO] Report written to {state.REPORT_FILE}")


def pause_between_categories():
    if not state.PAUSE_ENABLED:
        return
    try:
        input("\n[PAUSE] Press ENTER to continue...\n")
    except KeyboardInterrupt:
        log("\n[INFO] Execution interrupted by user")
        sys.exit(1)


def run_tests(selected=None):
    if selected:
        func, _ = AVAILABLE_TESTS[selected]
        func()
    else:
        for func, _ in AVAILABLE_TESTS.values():
            func()
            pause_between_categories()


def main():
    if os.geteuid() != 0:
        print("ERROR: this script must be run as root", file=sys.stderr)
        sys.exit(1)

    test_list = "\n  ".join(
        f"{name:<24} {desc}" for name, (_, desc) in AVAILABLE_TESTS.items()
    )
    parser = argparse.ArgumentParser(
        description="Platform diagnostics tool (use --help for full option list)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available tests:\n  {test_list}",
    )
    parser.add_argument("--pause", action="store_true",
                        help="Pause between test categories (interactive mode)")
    parser.add_argument("--verbose", action="store_true",
                        help="Mirror log-only output to console (commands, stdout, stderr)")
    parser.add_argument("--log-file", type=str, default=state.REPORT_FILE,
                        help=f"Log file path (default: {state.REPORT_FILE})")
    parser.add_argument("--test", type=str, metavar="TEST_NAME",
                        choices=AVAILABLE_TESTS.keys(),
                        help="Run only the specified test")
    parser.add_argument("--subcloud", type=str, metavar="NAME",
                        help=(
                            "Restrict DC subcloud tests to a single subcloud by exact name. "
                            "Example: --subcloud subcloud1"
                        ))
    parser.add_argument("--subcloud-range", nargs=2, metavar=("A", "B"),
                        help=(
                            "Restrict DC subcloud tests to a range of subclouds. "
                            "A is the first subcloud and B is the last (both inclusive), "
                            "in the order returned by 'dcmanager subcloud list'. "
                            "A and B must be subcloud names "
                            "(e.g. --subcloud-range subcloud1 subcloud5)."
    ))
    parser.add_argument("--subcloud-oam-ip", type=str, metavar="IP",
                        help=(
                            "OAM IP address used to SSH into the subcloud for remote checks. "
                            "When provided, the script opens an SSH session to this IP and "
                            "runs additional validations on the subcloud controller "
                            "(host availability, default route, k8s node status). "
                            "Requires --ssh-pass. "
                            "Example: --subcloud-oam-ip 10.10.10.2"
                        ))
    parser.add_argument("--ssh-pass", type=str, nargs="?", const="__PROMPT__",
                        metavar="PASSWORD",
                        help="SSH password for remote hosts.")
    args = parser.parse_args()

    state.PAUSE_ENABLED = args.pause
    state.REPORT_FILE = args.log_file
    state.VERBOSE = args.verbose

    if args.ssh_pass:
        if args.ssh_pass == "__PROMPT__":
            state.SSH_PASSWORD = getpass.getpass("SSH password for remote hosts: ")
        else:
            state.SSH_PASSWORD = args.ssh_pass
        if not tool_available("sshpass"):
            log("[WARN] --ssh-pass requires 'sshpass' but it is not installed")
            log("[WARN] remote host tests may fail")
    else:
        log("[WARN] --ssh-pass not provided - all validations requiring SSH to remote hosts will be skipped")
        log("[WARN] Use --ssh-pass to enable remote checks (kernel interfaces, iptables, SR-IOV, etc.)")

    if args.subcloud:
        state.SUBCLOUD_NAME = args.subcloud
    if args.subcloud_range:
        state.SUBCLOUD_RANGE_START, state.SUBCLOUD_RANGE_END = args.subcloud_range
    if args.subcloud_oam_ip:
        state.SUBCLOUD_OAM_IP = args.subcloud_oam_ip

    try:
        startup_checks()
        run_tests(selected=args.test)
        write_summary()
    finally:
        close_all_sessions()
        write_report()


if __name__ == "__main__":
    main()
