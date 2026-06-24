# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import ipaddress
import re

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import log_to_file_only
from network_platform_audit.log import print_category
from network_platform_audit.run import run
from network_platform_audit.run import run_log_only
from network_platform_audit.ssh import remote_run
from network_platform_audit.ssh import ssh_check_remote
from network_platform_audit.sysinv import local_hostname


def _detect_mcast_from_ss(ss_output, port):
    """Extract multicast addresses from ss output for a given port."""
    addrs = []
    for line in ss_output.splitlines():
        for token in line.split():
            idx = token.rfind(":")
            if idx < 0:
                continue
            if token[idx + 1:] != port:
                continue
            candidate = token[:idx].split("%")[0].strip("[]")
            try:
                ip = ipaddress.ip_address(candidate)
                if ip.is_multicast and candidate not in addrs:
                    addrs.append(candidate)
            except ValueError:
                pass
    return addrs


def _find_iface_by_ip(ip):
    family = "-6" if ":" in ip else ""
    rc, out, _ = run_log_only(["ip"] + ([family] if family else []) + ["route", "get", ip])
    if rc != 0 or not out:
        return None
    m = re.search(r"\bdev (\S+)", out)
    return m.group(1).split("@")[0] if m else None


def _capture_heartbeat(cat, iface, port, src_ip, dst_addrs, direction, label):
    """Capture one heartbeat packet on *iface* matching src_ip and dst multicast."""
    log(f"  Testing {direction} on port {port} {label}...")
    if isinstance(dst_addrs, list):
        dst_filter = " or ".join(f"dst {a}" for a in dst_addrs)
        dst_filter = f"({dst_filter})"
    else:
        dst_filter = f"dst {dst_addrs}"
    cmd = [
        "timeout", "10",
        "tcpdump", "-i", iface, "-vvv", "-nne",
        f"udp and {dst_filter} and dst port {port} and src {src_ip}",
        "-c", "1",
    ]
    rc, _, _ = run(cmd, timeout=state.TCPDUMP_TIMEOUT)
    if rc != 0:
        state.category_failures[cat].append(
            f"{direction}: no heartbeat from {src_ip} on {iface} port {port}"
        )
    else:
        log_result(f"  {direction} {label} port {port}", "PASS")


def _run_heartbeat_capture(cat, local_host, ports, iface,
                           local_ip, neighbor_entries, mcast_addrs,
                           rx_only=False):
    """Run RX (and optionally TX) heartbeat captures for *ports* on *iface*."""
    if not mcast_addrs:
        log(f"[INFO] no multicast addresses detected for ports {'/'.join(ports)} - skipping tcpdump")
        return

    log(f"[INFO] multicast addresses: {', '.join(mcast_addrs)}")

    for port in ports:
        for neighbor_name, neighbor_ip in neighbor_entries:
            log(f"  [{port}] testing against neighbor {neighbor_name} ({neighbor_ip})")
            _capture_heartbeat(cat, iface, port, neighbor_ip, mcast_addrs, "RX",
                               f"from {neighbor_name}")
            if not rx_only:
                _capture_heartbeat(cat, iface, port, local_ip, mcast_addrs, "TX",
                                   f"from {local_host}")
        log("")


def _check_hbs_processes(cat, ps_out):
    """Verify hbsAgent and hbsClient processes are running locally."""
    if "hbsAgent" in (ps_out or ""):
        log_result("hbsAgent process running", "PASS")
    else:
        log_result("hbsAgent process running", "FAILED")
        state.category_failures[cat].append("hbsAgent process not found")

    if "hbsClient" in (ps_out or ""):
        log_result("hbsClient process running", "PASS")
    else:
        log_result("hbsClient process running", "FAILED")
        state.category_failures[cat].append("hbsClient process not found")


def _check_mcast_sockets_open(cat, ss_out):
    """Verify multicast UDP sockets are open per `ss -upnOl` output."""
    mcast_re = re.compile(r"22[4-9]\.|23[0-9]\.|ff[0-9a-f]{2}::")
    mcast_found = any(mcast_re.search(line) for line in (ss_out or "").splitlines())

    if mcast_found:
        log_result("multicast UDP sockets open (ss -upnOl)", "PASS")
    else:
        log_result("multicast UDP sockets open (ss -upnOl)", "FAILED")
        state.category_failures[cat].append("no multicast UDP sockets found in ss -upnOl")


def _check_mcast_in_pool_subnets(cat, ss_out):
    """Cross-check active multicast addresses in ss output against pool multicast subnets."""
    if state._multicast_subnets and ss_out:
        active_mcasts = []
        for line in ss_out.splitlines():
            m = re.search(
                r"((?:22[4-9]|23[0-9])\.\d+\.\d+\.\d+|ff[0-9a-f]{2}::[^\s:]+)", line
            )
            if m:
                active_mcasts.append(m.group(1))
        for mcast_ip in active_mcasts:
            try:
                ip_obj = ipaddress.ip_address(mcast_ip)
                in_pool = any(
                    ip_obj in ipaddress.ip_network(sub, strict=False)
                    for sub in state._multicast_subnets
                )
                if in_pool:
                    log_result(f"multicast {mcast_ip} belongs to pool subnet", "PASS")
                else:
                    log(f"  [WARN] multicast {mcast_ip} not in any pool multicast subnet")
                    state.category_warnings[cat].append(
                        f"multicast {mcast_ip} not in pool multicast subnet"
                    )
            except ValueError:
                pass


def _build_host_ip_maps():
    """Parse /etc/hosts and build hostname -> mgmt IP and hostname -> cluster-host IP maps."""
    try:
        with open("/etc/hosts") as f:
            hosts_lines = [line for line in f if line.strip() and not line.startswith("#")]
    except Exception:
        hosts_lines = []

    host_mgmt_ip = {}
    host_cluster_ip = {}
    for line in hosts_lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        ip = parts[0]
        for name in parts[1:]:
            if re.match(r"^controller-\d+$", name):
                host_mgmt_ip[name] = ip
            elif re.match(r"^controller-\d+-cluster-host$", name):
                base = name.replace("-cluster-host", "")
                host_cluster_ip[base] = ip
            elif re.match(r"^\S+-cluster-host$", name):
                base = name.replace("-cluster-host", "")
                host_cluster_ip[base] = ip

    return host_mgmt_ip, host_cluster_ip


def _build_neighbor_lists(local_host, host_mgmt_ip, host_cluster_ip):
    """Build mgmt/cluster neighbor (name, ip) lists from local controller peers."""
    mgmt_neighbors = []
    cluster_neighbors = []

    controller_peers = [
        h for h in state.HOST_LIST
        if h.get("hostname", "") != local_host
        and re.match(r"^controller-\d+$", h.get("hostname", ""))
    ]
    for peer in controller_peers:
        pname = peer.get("hostname", "")
        if pname in host_mgmt_ip:
            mgmt_neighbors.append((pname, host_mgmt_ip[pname]))
        if pname in host_cluster_ip:
            cluster_neighbors.append((pname, host_cluster_ip[pname]))

    return mgmt_neighbors, cluster_neighbors


def _resolve_local_mgmt_ip(local_host, host_mgmt_ip, mgmt_neighbors):
    """Resolve the local mgmt IP, falling back to interface lookup if not in /etc/hosts."""
    local_mgmt_ip = host_mgmt_ip.get(local_host)

    if not local_mgmt_ip:
        _, ref_mgmt_ip = mgmt_neighbors[0]
        mgmt_iface_ref = _find_iface_by_ip(ref_mgmt_ip) if ref_mgmt_ip else None
        if mgmt_iface_ref:
            rc, addr_out, _ = run_log_only(["ip", "-o", "addr", "show", "dev", mgmt_iface_ref])
            m = re.search(r"inet6?\s+([0-9a-fA-F:.]+)/", addr_out or "")
            local_mgmt_ip = m.group(1) if m else None

    return local_mgmt_ip


def _run_mgmt_heartbeat(cat, local_host, ss_out, mgmt_neighbors, local_mgmt_ip, is_controller):
    """Resolve the mgmt interface and run the port-2106 heartbeat capture."""
    _, n_mgmt_ip = mgmt_neighbors[0]
    mgmt_iface = _find_iface_by_ip(n_mgmt_ip)
    if not mgmt_iface:
        log(f"[INFO] unable to determine mgmt interface for {n_mgmt_ip}")
        return None, None

    log("")
    log(f"[INFO] mgmt interface: {mgmt_iface}  local_mgmt_ip: {local_mgmt_ip}")
    mcast_2106 = _detect_mcast_from_ss(ss_out or "", "2106")
    _run_heartbeat_capture(
        cat, local_host,
        ports=["2106"],
        iface=mgmt_iface,
        local_ip=local_mgmt_ip,
        neighbor_entries=mgmt_neighbors,
        mcast_addrs=mcast_2106,
        rx_only=not is_controller,
    )

    return mgmt_iface, mcast_2106


def _run_cluster_heartbeat(cat, local_host, ss_out, cluster_neighbors, mgmt_neighbors,
                           mgmt_iface, local_cluster_ip, is_controller):
    """Resolve the cluster-host interface and run the port-2116 heartbeat capture."""
    cluster_iface = None
    if cluster_neighbors:
        _, n_cluster_ip = cluster_neighbors[0]
        cluster_iface = _find_iface_by_ip(n_cluster_ip)

    same_iface = (cluster_iface and cluster_iface == mgmt_iface)

    mcast_2116 = []
    if cluster_iface and not same_iface and local_cluster_ip:
        log(f"[INFO] cluster-host interface: {cluster_iface}  local_cluster_ip: {local_cluster_ip}")
        mcast_2116 = _detect_mcast_from_ss(ss_out or "", "2116")
        _run_heartbeat_capture(
            cat, local_host,
            ports=["2116"],
            iface=cluster_iface,
            local_ip=local_cluster_ip,
            neighbor_entries=cluster_neighbors or mgmt_neighbors,
            mcast_addrs=mcast_2116,
            rx_only=not is_controller,
        )
    elif same_iface:
        log(f"[INFO] cluster-host shares interface {mgmt_iface} with mgmt - skipping port 2116")
    elif not cluster_iface:
        log("[INFO] cluster-host interface not detected - skipping port 2116")

    return cluster_iface, same_iface, mcast_2116


def _run_sm_heartbeat(cat, local_host, ss_out, is_controller, cluster_iface, same_iface,
                      local_cluster_ip, local_mgmt_ip, mgmt_neighbors, cluster_neighbors,
                      mgmt_iface):
    """Controller-only: run the SM heartbeat capture on ports 2222/2223."""
    sm_mcast = []
    sm_local_ip = None
    if is_controller:
        mcast_2222 = _detect_mcast_from_ss(ss_out or "", "2222")
        mcast_2223 = _detect_mcast_from_ss(ss_out or "", "2223")
        sm_mcast = list(dict.fromkeys(mcast_2222 + mcast_2223))
        sm_local_ip = (local_cluster_ip or local_mgmt_ip) if (cluster_iface and not same_iface) else local_mgmt_ip

        if cluster_iface and not same_iface:
            # Separate interfaces: SM heartbeat runs on both cluster-host and mgmt
            log(f"[INFO] SM cluster interface: {cluster_iface}  local_ip: {local_cluster_ip}")
            _run_heartbeat_capture(
                cat, local_host,
                ports=["2222", "2223"],
                iface=cluster_iface,
                local_ip=local_cluster_ip,
                neighbor_entries=cluster_neighbors or mgmt_neighbors,
                mcast_addrs=sm_mcast,
                rx_only=False,
            )
            log(f"[INFO] SM mgmt interface: {mgmt_iface}  local_ip: {local_mgmt_ip}")
            _run_heartbeat_capture(
                cat, local_host,
                ports=["2222", "2223"],
                iface=mgmt_iface,
                local_ip=local_mgmt_ip,
                neighbor_entries=mgmt_neighbors,
                mcast_addrs=sm_mcast,
                rx_only=False,
            )
        else:
            # Shared interface: one test covers both
            log(f"[INFO] SM interface: {mgmt_iface}  local_ip: {local_mgmt_ip}")
            _run_heartbeat_capture(
                cat, local_host,
                ports=["2222", "2223"],
                iface=mgmt_iface,
                local_ip=local_mgmt_ip,
                neighbor_entries=mgmt_neighbors,
                mcast_addrs=sm_mcast,
                rx_only=False,
            )

    return sm_mcast, sm_local_ip


def _remote_iface_for_ip(rhost, target_ip):
    """Resolve the interface used on *rhost* to reach *target_ip* (via SSH route lookup)."""
    if not target_ip:
        return None
    flag = "-6" if ":" in target_ip else ""
    rc_r, rt_out, _ = remote_run(
        rhost, f"ip {flag} route get {target_ip}", use_sudo=False
    )
    if rc_r != 0 or not rt_out:
        return None
    m_dev = re.search(r"\bdev (\S+)", rt_out.splitlines()[0])
    return m_dev.group(1).split("@")[0] if m_dev else None


def _log_remote_tcpdump(out, err):
    """Log remote tcpdump stdout/stderr to the file-only log."""
    if out:
        for line in out.splitlines():
            log_to_file_only(f"  [tcpdump stdout] {line}")
    if err:
        for line in err.splitlines():
            log_to_file_only(f"  [tcpdump stderr] {line}")


def _check_remote_hbs_processes(cat, rhost, ps_out, is_remote_controller):
    """Verify hbsAgent (controllers only) and hbsClient processes on a remote host."""
    if is_remote_controller:
        if "hbsAgent" in (ps_out or ""):
            log_result(f"  {rhost}: hbsAgent process running", "PASS")
        else:
            log_result(f"  {rhost}: hbsAgent process running", "FAILED")
            state.category_failures[cat].append(f"{rhost}: hbsAgent process not found")

    if "hbsClient" in (ps_out or ""):
        log_result(f"  {rhost}: hbsClient process running", "PASS")
    else:
        log_result(f"  {rhost}: hbsClient process running", "FAILED")
        state.category_failures[cat].append(f"{rhost}: hbsClient process not found")


def _check_remote_mcast_sockets(cat, rhost, ss_remote, is_remote_controller, mcast_2116):
    """Verify expected heartbeat multicast socket ports are open on a remote host."""
    ports_found = set()
    for line in (ss_remote or "").splitlines():
        for p in ("2106", "2116", "2222", "2223"):
            if f":{p}" in line:
                ports_found.add(p)

    expected_ports = {"2106"}
    if is_remote_controller:
        expected_ports |= {"2222", "2223"}
    if mcast_2116:
        expected_ports.add("2116")

    for p in sorted(expected_ports):
        if p in ports_found:
            log_result(f"  {rhost}: multicast socket port {p} open", "PASS")
        else:
            log_result(f"  {rhost}: multicast socket port {p} open", "FAILED")
            state.category_failures[cat].append(
                f"{rhost}: heartbeat port {p} not found in ss output"
            )

    return ports_found


def _check_remote_mgmt_tcpdump(cat, rhost, host_mgmt_ip, local_host, local_mgmt_ip, mcast_2106):
    """Capture port-2106 (mgmt) heartbeat RX on a remote host."""
    r_mgmt_iface = _remote_iface_for_ip(rhost, local_mgmt_ip)
    if r_mgmt_iface and mcast_2106:
        ctrl_mgmt_sources = [
            (name, ip) for name, ip in host_mgmt_ip.items()
            if re.match(r"^controller-\d+$", name)
        ]
        if not ctrl_mgmt_sources:
            ctrl_mgmt_sources = [(local_host, local_mgmt_ip)]

        mcast_filter = " or ".join(f"dst {a}" for a in mcast_2106)
        for src_ctrl, src_ip in sorted(ctrl_mgmt_sources):
            if not src_ip:
                continue
            tcpdump_cmd = (
                f"timeout 10 tcpdump -i {r_mgmt_iface} -nn "
                f"'udp and ({mcast_filter}) and dst port 2106 and src {src_ip}' -c 1"
            )
            log(f"  [{rhost}] tcpdump RX port 2106 on {r_mgmt_iface} (src={src_ctrl} {src_ip})...")
            rc_td, td_out, td_err = remote_run(
                rhost, tcpdump_cmd, use_sudo=True, timeout=state.TCPDUMP_TIMEOUT
            )
            _log_remote_tcpdump(td_out, td_err)
            if rc_td == 0:
                log_result(f"  {rhost}: RX heartbeat port 2106 from {src_ctrl}", "PASS")
            else:
                log_result(f"  {rhost}: RX heartbeat port 2106 from {src_ctrl}", "FAILED")
                state.category_failures[cat].append(
                    f"{rhost}: no heartbeat RX on port 2106 from {src_ctrl} ({src_ip})"
                )
    else:
        log(f"  [INFO] {rhost}: skipping tcpdump port 2106 "
            f"(iface={r_mgmt_iface}, mcast_2106={mcast_2106})")


def _check_remote_cluster_tcpdump(cat, rhost, host_cluster_ip, local_mgmt_ip, mcast_2116, ports_found):
    """Capture port-2116 (cluster-host) heartbeat RX on a remote host."""
    ctrl_cluster_sources_2116 = [
        (name, ip) for name, ip in host_cluster_ip.items()
        if re.match(r"^controller-\d+$", name) and ip
    ]
    port_2116_open_remote = "2116" in ports_found
    if ctrl_cluster_sources_2116 and port_2116_open_remote:
        ref_cluster_ip = next(
            (ip for name, ip in ctrl_cluster_sources_2116 if name != rhost),
            ctrl_cluster_sources_2116[0][1],
        )
        r_cluster_iface = _remote_iface_for_ip(rhost, ref_cluster_ip)
        r_mgmt_for_cluster = _remote_iface_for_ip(rhost, local_mgmt_ip)
        same_remote = (r_cluster_iface and r_cluster_iface == r_mgmt_for_cluster)
        log_to_file_only(
            f"  [DEBUG] {rhost} port 2116: ctrl_cluster_sources={ctrl_cluster_sources_2116}"
            f" r_cluster_iface={r_cluster_iface} r_mgmt_for_cluster={r_mgmt_for_cluster}"
            f" same_remote={same_remote}"
        )
        if r_cluster_iface and not same_remote:
            rc_ss2, ss_remote2, _ = remote_run(
                rhost, "ss -upnOl | grep ':2116'", use_sudo=False,
            )
            remote_mcast_2116 = _detect_mcast_from_ss(ss_remote2 or "", "2116")
            if not remote_mcast_2116:
                remote_mcast_2116 = mcast_2116

            if remote_mcast_2116:
                mcast_filter = " or ".join(f"dst {a}" for a in remote_mcast_2116)
                for src_ctrl, src_ip in sorted(ctrl_cluster_sources_2116):
                    tcpdump_cmd = (
                        f"timeout 10 tcpdump -i {r_cluster_iface} -nn "
                        f"'udp and ({mcast_filter}) and dst port 2116 and src {src_ip}' -c 1"
                    )
                    log(f"  [{rhost}] tcpdump RX port 2116 on {r_cluster_iface} (src={src_ctrl} {src_ip})...")
                    rc_td, td_out, td_err = remote_run(
                        rhost, tcpdump_cmd, use_sudo=True, timeout=state.TCPDUMP_TIMEOUT
                    )
                    _log_remote_tcpdump(td_out, td_err)
                    if rc_td == 0:
                        log_result(f"  {rhost}: RX heartbeat port 2116 from {src_ctrl}", "PASS")
                    else:
                        log_result(f"  {rhost}: RX heartbeat port 2116 from {src_ctrl}", "FAILED")
                        state.category_failures[cat].append(
                            f"{rhost}: no heartbeat RX on port 2116 from {src_ctrl} ({src_ip})"
                        )
            else:
                log(f"  [INFO] {rhost}: no multicast address for port 2116 detected - skipping 2116 tcpdump")
        elif same_remote:
            log(f"  [INFO] {rhost}: cluster-host shares interface {r_cluster_iface} with mgmt - skipping port 2116")
        else:
            log(f"  [INFO] {rhost}: could not resolve cluster-host interface - skipping port 2116")
    elif not port_2116_open_remote:
        log(f"  [INFO] {rhost}: port 2116 not open in ss - skipping 2116 tcpdump")
    else:
        log(f"  [INFO] {rhost}: no controller cluster-host IPs found in /etc/hosts - skipping port 2116")


def _check_remote_sm_tcpdump(cat, rhost, is_remote_controller, sm_mcast, cluster_iface, same_iface,
                             local_cluster_ip, local_mgmt_ip, host_cluster_ip, host_mgmt_ip,
                             sm_local_ip, local_host):
    """Capture SM ports 2222/2223 heartbeat RX on a remote host (controllers only)."""
    if is_remote_controller and sm_mcast:
        r_sm_separate = (cluster_iface and not same_iface
                         and local_cluster_ip and local_mgmt_ip)
        sm_iface_sources = []
        if r_sm_separate:
            r_sm_cluster_iface = _remote_iface_for_ip(rhost, local_cluster_ip)
            if r_sm_cluster_iface:
                ctrl_cluster_sm = [
                    (name, host_cluster_ip.get(name))
                    for name in host_cluster_ip
                    if re.match(r"^controller-\d+$", name) and name != rhost
                ] or [(local_host, local_cluster_ip)]
                sm_iface_sources.append((r_sm_cluster_iface, ctrl_cluster_sm))
            r_sm_mgmt_iface = _remote_iface_for_ip(rhost, local_mgmt_ip)
            if r_sm_mgmt_iface and r_sm_mgmt_iface != r_sm_cluster_iface:
                ctrl_mgmt_sm = [
                    (name, host_mgmt_ip.get(name))
                    for name in host_mgmt_ip
                    if re.match(r"^controller-\d+$", name) and name != rhost
                ] or [(local_host, local_mgmt_ip)]
                sm_iface_sources.append((r_sm_mgmt_iface, ctrl_mgmt_sm))
        else:
            r_sm_iface = _remote_iface_for_ip(rhost, sm_local_ip) if sm_local_ip else None
            if r_sm_iface:
                ctrl_sm = [
                    (name, host_cluster_ip.get(name) or host_mgmt_ip.get(name))
                    for name in host_mgmt_ip
                    if re.match(r"^controller-\d+$", name) and name != rhost
                ] or [(local_host, sm_local_ip)]
                sm_iface_sources.append((r_sm_iface, ctrl_sm))

        mcast_filter = " or ".join(f"dst {a}" for a in sm_mcast)
        for r_iface, ctrl_sources in sm_iface_sources:
            for src_ctrl, src_ip in sorted(ctrl_sources):
                if not src_ip:
                    continue
                for sm_port in ("2222", "2223"):
                    tcpdump_cmd = (
                        f"timeout 10 tcpdump -i {r_iface} -nn "
                        f"'udp and ({mcast_filter}) and dst port {sm_port} and src {src_ip}' -c 1"
                    )
                    log(f"  [{rhost}] tcpdump RX port {sm_port} on {r_iface} "
                        f"(src={src_ctrl} {src_ip})...")
                    rc_td, td_out, td_err = remote_run(
                        rhost, tcpdump_cmd, use_sudo=True, timeout=state.TCPDUMP_TIMEOUT
                    )
                    _log_remote_tcpdump(td_out, td_err)
                    if rc_td == 0:
                        log_result(f"  {rhost}: RX SM port {sm_port} from {src_ctrl}", "PASS")
                    else:
                        log_result(f"  {rhost}: RX SM port {sm_port} from {src_ctrl}", "FAILED")
                        state.category_failures[cat].append(
                            f"{rhost}: no SM RX on port {sm_port} from {src_ctrl} ({src_ip})"
                        )


def _process_remote_heartbeat_host(cat, rhost_entry, local_host, host_mgmt_ip, host_cluster_ip,
                                   local_mgmt_ip, local_cluster_ip, mcast_2106, mcast_2116,
                                   cluster_iface, same_iface, sm_mcast, sm_local_ip):
    """Run all heartbeat checks (process/socket/tcpdump) for one remote host via SSH."""
    rhost = rhost_entry.get("hostname", "")
    personality = rhost_entry.get("personality", "").lower()
    is_remote_controller = bool(re.match(r"^controller-\d+$", rhost))

    if rhost in state.SSH_FAILED_HOSTS:
        ssh_check_remote(cat, rhost, "heartbeat process/socket/tcpdump validation")
        return

    log(f"  [HOST] {rhost} (personality={personality})")

    rc_ps, ps_out, _ = remote_run(rhost, "ps aux", use_sudo=False)
    if rc_ps != 0:
        log(f"  [WARN] {rhost}: could not run ps aux via SSH")
        state.category_failures[cat].append(f"{rhost}: could not check heartbeat processes via SSH")
        return

    _check_remote_hbs_processes(cat, rhost, ps_out, is_remote_controller)

    rc_ss, ss_remote, _ = remote_run(
        rhost,
        "ss -upnOl | grep -E ':2106|:2116|:2222|:2223'",
        use_sudo=False,
    )
    ports_found = _check_remote_mcast_sockets(cat, rhost, ss_remote, is_remote_controller, mcast_2116)

    _check_remote_mgmt_tcpdump(cat, rhost, host_mgmt_ip, local_host, local_mgmt_ip, mcast_2106)

    _check_remote_cluster_tcpdump(cat, rhost, host_cluster_ip, local_mgmt_ip, mcast_2116, ports_found)

    _check_remote_sm_tcpdump(cat, rhost, is_remote_controller, sm_mcast, cluster_iface, same_iface,
                             local_cluster_ip, local_mgmt_ip, host_cluster_ip, host_mgmt_ip,
                             sm_local_ip, local_host)


def test_heartbeat_extended():
    cat = "TestSuite 11 - Heartbeat"
    desc = [
        "1) Verify hbsAgent and hbsClient processes running",
        "2) Verify multicast UDP sockets open (ss -upnOl)",
        "3) Verify multicast addresses belong to pool multicast subnet",
        "4) Controller: capture RX and TX heartbeat on port 2106 (mgmt)",
        "5) Controller: capture RX and TX heartbeat on port 2116 (cluster-host,"
        " only when on a different interface from mgmt)",
        "6) Controller: capture RX and TX SM traffic on ports 2222 and 2223",
        "7) Worker: capture RX-only heartbeat on port 2106 (mgmt)",
        "8) Worker: capture RX-only heartbeat on port 2116 (cluster-host,"
        " only when on a different interface from mgmt)",
        "9) Remote hosts (via SSH): verify hbsAgent/hbsClient processes,"
        " multicast sockets, and RX heartbeat traffic on mgmt/cluster-host ports",
    ]
    print_category(cat, description=desc)

    if state.IS_SIMPLEX:
        log("[INFO] simplex - heartbeat between nodes not applicable, skipping")
        return

    local_host = local_hostname()
    is_controller = bool(re.match(r"^controller-\d+$", local_host))

    rc, ps_out, _ = run_log_only("ps aux | grep -E 'hbsAgent|hbsClient' | grep -v grep")
    _check_hbs_processes(cat, ps_out)

    rc, ss_out, _ = run_log_only(
        "ss -upnOl | grep -E '22[4-9]\\.|23[0-9]\\.|ff[0-9a-f]{2}::|"
        ":2106|:2116|:2222|:2223'"
    )
    _check_mcast_sockets_open(cat, ss_out)

    _check_mcast_in_pool_subnets(cat, ss_out)

    host_mgmt_ip, host_cluster_ip = _build_host_ip_maps()

    mgmt_neighbors, cluster_neighbors = _build_neighbor_lists(local_host, host_mgmt_ip, host_cluster_ip)

    if not mgmt_neighbors:
        log("[INFO] no controller peers found in /etc/hosts - skipping tcpdump captures")
        return

    local_mgmt_ip = _resolve_local_mgmt_ip(local_host, host_mgmt_ip, mgmt_neighbors)
    local_cluster_ip = host_cluster_ip.get(local_host)

    if not local_mgmt_ip:
        log("[INFO] unable to determine local mgmt IP - skipping tcpdump captures")
        return

    mgmt_iface, mcast_2106 = _run_mgmt_heartbeat(
        cat, local_host, ss_out, mgmt_neighbors, local_mgmt_ip, is_controller
    )
    if not mgmt_iface:
        return

    cluster_iface, same_iface, mcast_2116 = _run_cluster_heartbeat(
        cat, local_host, ss_out, cluster_neighbors, mgmt_neighbors,
        mgmt_iface, local_cluster_ip, is_controller
    )

    sm_mcast, sm_local_ip = _run_sm_heartbeat(
        cat, local_host, ss_out, is_controller, cluster_iface, same_iface,
        local_cluster_ip, local_mgmt_ip, mgmt_neighbors, cluster_neighbors, mgmt_iface
    )

    remote_hosts = [
        h for h in state.HOST_LIST
        if h.get("hostname") and h.get("hostname") != local_host
    ]
    if not remote_hosts:
        return

    log("")
    log("[INFO] verifying heartbeat on remote hosts via SSH (processes, sockets, tcpdump RX)...")

    for rhost_entry in remote_hosts:
        _process_remote_heartbeat_host(
            cat, rhost_entry, local_host, host_mgmt_ip, host_cluster_ip,
            local_mgmt_ip, local_cluster_ip, mcast_2106, mcast_2116,
            cluster_iface, same_iface, sm_mcast, sm_local_ip
        )
