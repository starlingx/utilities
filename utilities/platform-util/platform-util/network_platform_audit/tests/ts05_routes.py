# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import ipaddress
import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import _get_if_list
from network_platform_audit.sysinv import _get_iface_networks
from network_platform_audit.sysinv import _get_sw_version
from network_platform_audit.sysinv import _parse_generic_table
from network_platform_audit.sysinv import _resolve_kernel_ifname
from network_platform_audit.sysinv import _run_on_host
from network_platform_audit.sysinv import get_host_names
from network_platform_audit.sysinv import local_hostname


def test_routes_vs_kernel():
    cat = "TestSuite 5 - Static Routes"
    desc = [
        "1) system host-route-list per host",
        "2) Verify each DB route is in kernel routing table",
        "3) Warn on kernel routes not in DB",
        "4) verify IPv6 kernel route has 'src' on the",
        "   same network as the egress interface",
        "   For older versions: verify 'src' is NOT present in the route",
    ]
    print_category(cat, description=desc)

    for hostname in get_host_names():
        log(f"[HOST] {hostname}")

        sw_ver = _get_sw_version(hostname)
        if sw_ver is None:
            log(f"  [WARN] could not read sw_version from {hostname} "
                f"- src kernel-route check will be skipped")
            src_expected = None
        else:
            src_expected = sw_ver >= (26, 3)
            log(f"  sw_version={sw_ver[0]:02d}.{sw_ver[1]:02d}  "
                f"src_in_kernel_route={'expected' if src_expected else 'not expected'}")

        rc, out, _ = run_log_only(["system", "host-route-list", hostname])

        if rc != 0 or not out:
            log(f"  [INFO] no routes for {hostname}")
            db_routes = []
        else:
            db_routes = _parse_generic_table(out, key_col="network")
            if not db_routes:
                log(f"  [INFO] no static routes in DB for {hostname}")

        if hostname != local_hostname() and hostname in state.SSH_FAILED_HOSTS:
            ssh_check_remote(cat, hostname, "route kernel validation")
            continue

        _, k4_out, _ = _run_on_host(hostname, "ip -4 route show")
        _, k6_out, _ = _run_on_host(hostname, "ip -6 route show")
        kernel_routes_raw = (k4_out or "") + "\n" + (k6_out or "")

        ifaces = _get_if_list(hostname)

        for route in db_routes:
            network = route.get("network", "").replace(" ", "")
            prefix = route.get("prefix", route.get("prefix_len", "")).replace(" ", "")
            gateway = route.get("gateway", "").replace(" ", "")
            metric = route.get("metric", "").replace(" ", "")
            ifname = route.get("ifname", "").replace(" ", "")
            cidr = f"{network}/{prefix}" if prefix else network

            kernel_if = None
            if ifname:
                matched = next((i for i in ifaces if i.get("name") == ifname), None)
                if matched:
                    resolved = _resolve_kernel_ifname(matched, ifaces)
                    if resolved != ifname:
                        kernel_if = resolved

            route_found = False
            matched_line = None
            mismatch_details = []

            try:
                db_net = ipaddress.ip_network(cidr, strict=False) if prefix else None
            except ValueError:
                db_net = None

            for route_line in kernel_routes_raw.splitlines():
                if db_net is not None:
                    net_m = re.match(r"(\S+)\s", route_line)
                    if net_m:
                        try:
                            line_net = ipaddress.ip_network(net_m.group(1), strict=False)
                            if line_net != db_net:
                                continue
                        except ValueError:
                            if cidr not in route_line and network not in route_line:
                                continue
                    else:
                        if cidr not in route_line and network not in route_line:
                            continue
                else:
                    if cidr not in route_line and network not in route_line:
                        continue
                has_gateway = (not gateway or f"via {gateway}" in route_line)
                if not has_gateway:
                    continue
                route_found = True
                matched_line = route_line
                if metric and metric != "0":
                    if f"metric {metric}" not in route_line:
                        mismatch_details.append(f"metric DB={metric} not in kernel route")
                if kernel_if:
                    if f"dev {kernel_if}" not in route_line:
                        mismatch_details.append(f"interface DB={kernel_if} not in kernel route")
                break

            if not route_found:
                log_result(f"  {hostname}: route {cidr} via {gateway}", "FAILED")
                state.category_failures[cat].append(
                    f"{hostname}: route {cidr} via {gateway} not found in kernel"
                )
                continue

            src_match = re.search(r"\bsrc\s+([0-9a-fA-F:.]+)", matched_line or "")
            src_ip = src_match.group(1) if src_match else None

            is_ipv6_route = ":" in (network or cidr)
            if not is_ipv6_route:
                pass
            elif src_expected is None:
                pass
            elif src_expected:
                if not src_ip:
                    mismatch_details.append(
                        "src missing in kernel route (expected for this version)"
                    )
                else:
                    egress_if = kernel_if or ifname
                    if egress_if:
                        iface_nets = _get_iface_networks(hostname, egress_if)
                        try:
                            src_addr = ipaddress.ip_address(src_ip)
                            if not any(src_addr in net for net in iface_nets):
                                nets_str = ", ".join(str(n) for n in iface_nets)
                                mismatch_details.append(
                                    f"src {src_ip} is not on egress interface "
                                    f"{egress_if} networks ({nets_str or 'none found'})"
                                )
                            else:
                                log_result(
                                    f"  {hostname}: route {cidr} src={src_ip} "
                                    f"on {egress_if}",
                                    "PASS",
                                )
                        except ValueError:
                            mismatch_details.append(
                                f"src {src_ip} is not a valid IP address"
                            )
                    else:
                        log_result(
                            f"  {hostname}: route {cidr} src={src_ip} (iface unknown)",
                            "PASS",
                        )
            else:
                if src_ip:
                    mismatch_details.append(
                        f"src {src_ip} present in kernel route "
                        f"(not expected for this version)"
                    )
                else:
                    log_result(
                        f"  {hostname}: route {cidr} no src (correct for this version)",
                        "PASS",
                    )

            if not mismatch_details:
                log_result(
                    f"  {hostname}: route {cidr} via {gateway} metric {metric} "
                    f"dev {kernel_if or ifname}",
                    "PASS",
                )
            else:
                for detail in mismatch_details:
                    log_result(f"  {hostname}: route {cidr} - {detail}", "FAILED")
                    state.category_failures[cat].append(f"{hostname}: route {cidr} - {detail}")

        db_nets = set()
        for route in db_routes:
            nw = route.get("network", "").replace(" ", "")
            px = route.get("prefix", route.get("prefix_len", "")).replace(" ", "")
            if nw and px:
                try:
                    db_nets.add(ipaddress.ip_network(f"{nw}/{px}", strict=False))
                except ValueError:
                    pass

        for route_line in kernel_routes_raw.splitlines():
            route_line = route_line.strip()
            if not route_line:
                continue
            skip_protos = ("proto kernel", "proto ra", "proto bird",
                           "proto bgp", "proto ospf", "proto 186")
            if any(p in route_line for p in skip_protos):
                continue
            if "via" not in route_line:
                continue
            first_token = route_line.split()[0]
            if first_token in ("default", "::/0"):
                continue
            try:
                k_net = ipaddress.ip_network(first_token, strict=False)
            except ValueError:
                continue
            if not any(k_net == db_net for db_net in db_nets):
                log(f"  [WARN] {hostname}: kernel route {first_token} not in sysinv DB")
                state.category_warnings[cat].append(
                    f"{hostname}: kernel route {first_token} not in sysinv DB"
                )
