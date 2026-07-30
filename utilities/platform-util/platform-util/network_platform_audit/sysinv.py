# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# sysinv/system CLI helpers, table parsers, and startup_checks.

from collections import defaultdict
import ipaddress
import os
import re
import sys

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_exec
from network_platform_audit.log import log_to_file_only
from network_platform_audit.run import run
from network_platform_audit.run import run_log_only
from network_platform_audit.run import run_silent
from network_platform_audit.ssh import open_ssh_session
from network_platform_audit.ssh import remote_run


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _run_system_list(cmd, runner=None):
    """Run a system *-list command with --nowrap, fallback without if unsupported.

    Inserts --nowrap after the subcommand name. If the command fails (rc!=0),
    retries without --nowrap.
    """
    if runner is None:
        runner = run_log_only
    if isinstance(cmd, list):
        nowrap_cmd = cmd[:2] + ["--nowrap"] + cmd[2:]
        fallback_cmd = cmd
    else:
        parts = cmd.split(None, 2)
        nowrap_cmd = parts[0] + " " + parts[1] + " --nowrap" + (" " + parts[2] if len(parts) > 2 else "")
        fallback_cmd = cmd

    rc, out, err = runner(nowrap_cmd)
    if rc == 0:
        return rc, out, err
    # --nowrap not supported, retry without
    return runner(fallback_cmd)


# ---------------------------------------------------------------------------
# Startup checks
# ---------------------------------------------------------------------------

def startup_checks():
    """Verify prerequisites and populate global state. Exit on fatal errors."""
    log("")
    log("=" * 50)
    log("Startup Checks")
    log("=" * 50)

    # 1) openrc must exist
    openrc = "/etc/platform/openrc"
    if not os.path.isfile(openrc):
        sys.exit(f"Error: {openrc} not found. Must run on a platform controller.")
    log(f"[OK] {openrc} found")

    # 2) source openrc (set env vars for subprocess calls)
    rc, out, _ = run_silent(["bash", "-c", f"source {openrc} && env"])
    if rc == 0:
        for line in out.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                os.environ[key.strip()] = val.strip()
    log("[OK] openrc sourced")

    # Set KUBECONFIG for kubectl commands
    os.environ["KUBECONFIG"] = "/etc/kubernetes/admin.conf"

    # 3) Verify we are on a controller
    hostname = os.uname().nodename
    if not re.match(r"^controller-[01]$", hostname):
        sys.exit(f"Error: Must run on controller-0 or controller-1 (current host: {hostname})")
    log(f"[OK] running on {hostname}")

    # 4) Verify this is the active controller
    log("[..] checking active controller (sm-query)...")
    rc, out, _ = run_silent("sm-query service-group controller-services")
    if rc != 0:
        sys.exit(
            "Error: Could not query service-group status (sm-query failed). "
            "Ensure the script is running on a healthy controller."
        )
    if not re.search(r"controller-services\s+active\b", out):
        sys.exit(
            "Error: This controller is not active. "
            "Run network_platform_audit on the active controller."
        )
    log("[OK] this is the active controller")

    # 5) Detect system_mode
    log("[..] querying system show...")
    rc, out, _ = run_log_only("system show")
    if rc != 0:
        sys.exit("Error: 'system show' failed. Keystone/sysinv may not be available. "
                 "Ensure platform services are running before executing this script.")
    m = re.search(r"system_mode\s*\|\s*(\S+)", out)
    if m:
        state.SYSTEM_MODE = m.group(1)

    state.IS_SIMPLEX = (state.SYSTEM_MODE == "simplex")

    # 6) Detect distributed_cloud_role
    m = re.search(r"distributed_cloud_role\s*\|\s*(\S+)", out)
    if m:
        state.DC_ROLE = m.group(1)

    # 7) Detect https_enabled
    m = re.search(r"https_enabled\s*\|\s*(\S+)", out)
    if m:
        state.HTTPS_ENABLED = m.group(1).lower() in ("true", "yes", "1")

    log(f"[OK] system_mode={state.SYSTEM_MODE}  dc_role={state.DC_ROLE}"
        f"  https_enabled={state.HTTPS_ENABLED}")

    # 8) Build host list
    log("[..] querying system host-list...")
    rc, out, _ = _run_system_list("system host-list")
    if rc != 0:
        sys.exit("Error: 'system host-list' failed. Keystone/sysinv may not be available. "
                 "Ensure platform services are running before executing this script.")
    if out:
        state.HOST_LIST = _parse_host_table(out)
    log(f"[OK] {len(state.HOST_LIST)} hosts found")

    # 9) Open persistent SSH sessions to remote hosts
    if not state.IS_SIMPLEX:
        local_host = os.uname().nodename
        remote_hosts = [h.get("hostname") for h in state.HOST_LIST
                        if h.get("hostname") and h.get("hostname") != local_host]
        if not state.SSH_PASSWORD and remote_hosts:
            log("[WARN] --ssh-pass not provided - remote kernel tests will be skipped")
            for rhost in remote_hosts:
                state.SSH_FAILED_HOSTS.add(rhost)
                state.SSH_NO_PASS_HOSTS.add(rhost)
            state.REMOTE_KERNEL_SKIPPED = True
        else:
            for rhost in remote_hosts:
                log(f"[..] opening SSH session to {rhost}...")
                state.ssh_sessions[rhost] = open_ssh_session(rhost)
                if rhost in state.SSH_FAILED_HOSTS:
                    log(f"[WARN] SSH to {rhost} failed - remote kernel tests will be skipped for this host")
                    state.REMOTE_KERNEL_SKIPPED = True
                else:
                    log(f"[OK] SSH to {rhost} established")

    log("")


# ---------------------------------------------------------------------------
# Table parsers
# ---------------------------------------------------------------------------

def _parse_generic_table(output, key_col=None):
    """Generic sysinv table parser - returns list of dicts.

    With --nowrap, tables have single-line headers and single-line data rows.
    We still handle multi-line cases as a safety fallback.
    """
    rows = []
    lines = output.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "|" in line and line.strip().startswith("|"):
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if parts and key_col and key_col in parts:
                header_idx = i
                break
            elif parts and key_col is None:
                header_idx = i
                break
    if header_idx is None:
        return rows

    def _split_cells(line):
        parts = line.split("|")
        if parts and parts[0].strip() == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        return [c.strip() for c in parts]

    col_names = _split_cells(lines[header_idx])

    # Skip to data: consume any header continuations + separator
    data_start = header_idx + 1
    while data_start < len(lines):
        ln = lines[data_start].strip()
        if ln.startswith("+"):
            data_start += 1
            break
        data_start += 1

    for line in lines[data_start:]:
        if not line.strip() or line.strip().startswith("+"):
            continue
        cells = _split_cells(line)
        if len(cells) < len(col_names):
            continue
        if cells[0] == "" and rows:
            # Data continuation row - merge into previous
            for idx, cell in enumerate(cells):
                if idx < len(col_names) and cell:
                    rows[-1][col_names[idx]] = rows[-1].get(col_names[idx], "") + cell
        else:
            rows.append(dict(zip(col_names, cells[:len(col_names)])))
    return rows


def _parse_host_table(output):
    """Parse the sysinv host-list table output into a list of dicts."""
    return _parse_generic_table(output, key_col="hostname")


def _parse_if_table(output):
    """Parse system host-if-list table into list of dicts with MTU and uses_list."""
    ifaces = _parse_generic_table(output, key_col="name")
    for row in ifaces:
        attrs = row.get("attributes", "")
        mtu_match = re.search(r"MTU=(\d+)", attrs)
        if mtu_match:
            row["mtu"] = mtu_match.group(1)
        uses_raw = row.get("uses i/f", "[]")
        row["uses_list"] = re.findall(r"'([^']+)'", uses_raw)
    return ifaces


# ---------------------------------------------------------------------------
# Host / interface helpers
# ---------------------------------------------------------------------------

def get_host_names():
    """Return list of hostnames from HOST_LIST."""
    return [h.get("hostname", "") for h in state.HOST_LIST if h.get("hostname")]


def local_hostname():
    return os.uname().nodename


def _get_if_list(hostname):
    """Return parsed interface list for a host (one API call)."""
    rc, out, _ = _run_system_list(["system", "host-if-list", hostname])
    if rc != 0 or not out:
        return []
    return _parse_if_table(out)


def _get_if_show(hostname, ifname):
    """Get detailed interface info via system host-if-show."""
    rc, out, _ = run_log_only(["system", "host-if-show", hostname, ifname])
    if rc != 0 or not out:
        return {}
    props = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) == 2 and parts[0] != "Property":
            props[parts[0]] = parts[1]
    return props


def _resolve_kernel_ifname(iface, all_ifaces, _seen=None):
    """Resolve the kernel interface name for a sysinv interface entry.

    Rules:
    - ethernet with ports: kernel name is the port name (e.g. enp0s3)
    - ethernet without ports: it is a logical interface stacked on another
      interface via uses_list - recurse into the parent to find the physical base
    - ae (bond): kernel name is the sysinv ifname itself (e.g. bond0)
    - vlan: kernel name is vlan<vlan_id>
    """
    if _seen is None:
        _seen = set()

    iftype = iface.get("type", "")
    ifname = iface.get("name", "")
    vlan_id = iface.get("vlan id", "")
    ports = iface.get("ports", "")
    uses = iface.get("uses_list", [])

    if ifname in _seen:
        return ifname

    _seen.add(ifname)

    if iftype == "ethernet":
        port_names = re.findall(r"'([^']+)'", ports) if isinstance(ports, str) else ports
        if port_names:
            return port_names[0]
        if uses:
            parent_name = uses[0]
            parent = next((i for i in all_ifaces if i.get("name") == parent_name), None)
            if parent:
                return _resolve_kernel_ifname(parent, all_ifaces, _seen)
        return ifname

    if iftype == "ae":
        return ifname

    if iftype == "vlan":
        if vlan_id and vlan_id != "None":
            return f"vlan{vlan_id}"
        return ifname

    return ifname


def _run_on_host(hostname, cmd, silent=False):
    """Run a command locally or remotely depending on hostname.

    cmd may be a list (preferred, no shell injection) or a string (shell=True,
    required for commands that use pipes or shell builtins).

    When silent=False (default), logs the command and output using log_exec.
    When silent=True, no logging - used for data gathering only.
    Local: runs directly (script already requires root).
    Remote: uses sudo with SSH_PASSWORD via stdin.

    Returns (rc, stdout, stderr).
    When SSH is unavailable for a remote host, returns (None, "", "SSH_SKIPPED")
    so callers can distinguish a skip from an actual failure.
    """
    from network_platform_audit.run import _cmd_str
    if hostname == local_hostname():
        if silent:
            return run_silent(cmd)
        return run(cmd)

    if hostname in state.SSH_FAILED_HOSTS:
        if not silent:
            log_to_file_only(f"[{hostname}] SKIP: SSH not available - {_cmd_str(cmd)}")
        return None, "", "SSH_SKIPPED"

    rc, out, err = remote_run(hostname, cmd, use_sudo=True)
    if not silent:
        log_exec(f"[{hostname}] {_cmd_str(cmd)}", rc, out, err)
    return rc, out, err


# ---------------------------------------------------------------------------
# dnsmasq / DHCP helpers
# ---------------------------------------------------------------------------

def _detect_dnsmasq_file(filename):
    """Return path to the newest /opt/platform/config/<ver>/<filename>, or None."""
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


def _parse_dhcp_leases():
    """Parse dnsmasq.leases into a list of {mac, ip, hostname} dicts.

    Line format: <expiry> <mac> <ip> <hostname> <client_id>
    """
    leases = []
    leases_file = _detect_dnsmasq_file("dnsmasq.leases")
    if not leases_file:
        return leases
    try:
        with open(leases_file) as f:
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                _, mac, ip, lease_hostname = parts[:4]
                if re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", mac):
                    leases.append({"mac": mac.lower(), "ip": ip, "hostname": lease_hostname})
    except OSError:
        pass
    return leases


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------

def _get_addr_list(hostname):
    """Return parsed address list for a host. Always runs locally."""
    rc, out, _ = _run_system_list(["system", "host-addr-list", hostname])
    if rc != 0 or not out:
        return []
    return _parse_generic_table(out, key_col="address")


def _get_sw_version(hostname):
    """Return the deployed sw_version as (major, minor, patch) ints.

    platform.conf's sw_version only carries major.minor (no patch level), so
    the patch must come from the deployed release in `software list`.
    There can be multiple releases listed; only the
    one with State == deployed is used.

    `software list` doesn't exist on older releases, so fall back to
    platform.conf's major.minor (patch defaults to 0) in that case.

    Returns None on failure or if no deployed release is found.
    """
    rc, out, _ = _run_on_host(hostname, "software list", silent=True)
    if rc == 0 and out:
        for release in _parse_generic_table(out, key_col="Release"):
            if release.get("State", "").strip().lower() != "deployed":
                continue
            m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", release.get("Release", ""))
            if m:
                return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))

    rc, out, _ = _run_on_host(hostname, "cat /etc/platform/platform.conf", silent=True)
    if rc == 0 and out:
        m = re.search(r"^sw_version=(\d+)\.(\d+)", out, re.MULTILINE)
        if m:
            return (int(m.group(1)), int(m.group(2)), 0)
    return None


def _get_iface_networks(hostname, kernel_ifname):
    """Return list of ipaddress.ip_network objects assigned to kernel_ifname."""
    rc, out, _ = _run_on_host(
        hostname, ["ip", "-o", "addr", "show", "dev", kernel_ifname], silent=True
    )
    nets = []
    if rc != 0 or not out:
        return nets
    for line in out.splitlines():
        m = re.search(r"inet6?\s+([0-9a-fA-F:.]+/\d+)", line)
        if m:
            try:
                nets.append(ipaddress.ip_network(m.group(1), strict=False))
            except ValueError:
                pass
    return nets


# ---------------------------------------------------------------------------
# Address pool / network helpers
# ---------------------------------------------------------------------------

def _get_addrpool_list():
    """Return parsed addrpool list with full field values."""
    rc, out, _ = _run_system_list("system addrpool-list")
    if rc != 0 or not out:
        return []
    return _parse_generic_table(out, key_col="name")


def _get_network_list():
    rc, out, _ = _run_system_list("system network-list")
    if rc != 0 or not out:
        return []
    return _parse_generic_table(out, key_col="name")


def _get_iface_network_count(hostname):
    """Return {ifname: network_type_count} from system interface-network-list.

    Returns an empty dict if the command is unavailable.
    """
    rc, out, _ = _run_system_list(["system", "interface-network-list", hostname])
    if rc != 0:
        return {}
    if not out:
        return {}
    rows = _parse_generic_table(out, key_col="ifname")
    result = defaultdict(int)
    for row in rows:
        ifname = row.get("ifname", "")
        if ifname:
            result[ifname] += 1
    return dict(result)


def _get_network_addrpool_list():
    rc, out, err = _run_system_list("system network-addrpool-list")
    if rc != 0:
        if "invalid choice: 'network-addrpool-list'" in err:
            return None
        return []
    if not out:
        return []
    return _parse_generic_table(out, key_col="network_name")


def build_pools_by_network_type(net_addrpools, addrpools):
    """Return {network_name: [pool_dict, ...]} using already-fetched data.

    Uses the canonical network name from network-addrpool-list as the key,
    which is a system constant (not user-customizable like addrpool.name).
    Returns an empty dict when net_addrpools is None (command unavailable).
    """
    if net_addrpools is None:
        return {}
    pool_by_name = {p.get("name", ""): p for p in (addrpools or [])}
    result = defaultdict(list)
    for na in net_addrpools:
        net_name = na.get("network_name", na.get("network", ""))
        pool_name = na.get("addrpool_name", na.get("pool", ""))
        pool = pool_by_name.get(pool_name)
        if pool and net_name:
            result[net_name].append(pool)
    return dict(result)
