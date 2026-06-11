# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# sysinv/system CLI helpers, table parsers, and startup_checks.

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
    log(f"[OK] system_mode={state.SYSTEM_MODE}  dc_role={state.DC_ROLE}")

    # 7) Build host list
    log("[..] querying system host-list...")
    rc, out, _ = run_log_only("system host-list")
    if rc != 0:
        sys.exit("Error: 'system host-list' failed. Keystone/sysinv may not be available. "
                 "Ensure platform services are running before executing this script.")
    if out:
        state.HOST_LIST = _parse_host_table(out)
    log(f"[OK] {len(state.HOST_LIST)} hosts found")

    # 8) Open persistent SSH sessions to remote hosts
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

    Handles multi-line rows: sysinv wraps long field values across lines.
    Continuation lines have the same pipe structure but all non-value columns
    are empty (e.g. uuid column is blank). We detect them by checking that
    the first data column is empty and join them into the previous row.
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

    col_names = [p.strip() for p in lines[header_idx].split("|") if p.strip()]

    raw_rows = []
    for line in lines[header_idx + 2:]:
        if not line.strip() or line.startswith("+"):
            continue
        parts = line.split("|")
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        cells = [c.strip() for c in parts]

        if len(cells) < len(col_names):
            continue

        if cells[0] == "" and raw_rows:
            for idx, cell in enumerate(cells):
                if idx < len(col_names) and cell:
                    prev = raw_rows[-1][idx]
                    raw_rows[-1][idx] = prev + cell
        else:
            raw_rows.append(list(cells[:len(col_names)]))

    for cells in raw_rows:
        rows.append(dict(zip(col_names, cells)))
    return rows


def _parse_host_table(output):
    """Parse the sysinv host-list table output into a list of dicts."""
    return _parse_generic_table(output, key_col="hostname")


def _parse_if_table(output):
    """Parse system host-if-list pipe-delimited table into list of dicts.

    Expected columns: uuid, name, class, type, vlan id, ports, uses i/f,
                      used by i/f, attributes

    The header spans two rows due to column name wrapping, e.g.:
      | vlan | uses i/ | used by |
      | id   | f       | i/f     |
    We merge both header rows before parsing data rows.
    """
    ifaces = []
    lines = output.splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if "| name" in line and "class" in line:
            header_idx = i
            break
    if header_idx is None:
        return ifaces

    def split_pipe(line):
        parts = line.split("|")
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        return parts

    row1 = split_pipe(lines[header_idx])
    col_names = [c.strip() for c in row1]

    if header_idx + 1 < len(lines):
        next_line = lines[header_idx + 1]
        if next_line.strip().startswith("|") and not next_line.startswith("+"):
            row2 = split_pipe(next_line)
            merged = []
            for i, c1 in enumerate(row1):
                c2 = row2[i].strip() if i < len(row2) else ""
                needs_space = bool(c1.strip() and c2 and c1.strip()[-1].isalnum())
                combined = (c1.strip() + (" " if needs_space else "") + c2).strip()
                merged.append(combined)
            col_names = merged
            header_idx += 1

    for line in lines[header_idx + 1:]:
        if not line.strip() or line.startswith("+"):
            continue
        raw_parts = line.split("|")
        if raw_parts and raw_parts[0] == "":
            raw_parts = raw_parts[1:]
        if raw_parts and raw_parts[-1].strip() == "":
            raw_parts = raw_parts[:-1]
        values = [v.strip() for v in raw_parts]
        if len(values) >= len(col_names):
            row = dict(zip(col_names, values))
            attrs = row.get("attributes", "")
            mtu_match = re.search(r"MTU=(\d+)", attrs)
            if mtu_match:
                row["mtu"] = mtu_match.group(1)
            uses_raw = row.get("uses i/f", "[]")
            row["uses_list"] = re.findall(r"'([^']+)'", uses_raw)
            ifaces.append(row)
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
    rc, out, _ = run_log_only(["system", "host-if-list", hostname])
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
# Address helpers
# ---------------------------------------------------------------------------

def _get_addr_list(hostname):
    """Return parsed address list for a host. Always runs locally."""
    rc, out, _ = run_log_only(["system", "host-addr-list", hostname])
    if rc != 0 or not out:
        return []
    return _parse_generic_table(out, key_col="address")


def _get_sw_version(hostname):
    """Read sw_version from /etc/platform/platform.conf on the given host.

    Returns a tuple (major, minor) of ints on success, or None on failure.
    """
    rc, out, _ = _run_on_host(hostname, "cat /etc/platform/platform.conf", silent=True)
    if rc != 0 or not out:
        return None
    m = re.search(r"sw_version\s*=\s*(\d+)\.(\d+)", out)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


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
    """Return parsed addrpool list with full field values.

    system addrpool-list truncates column headers across two header rows, e.g.:
      | floating_ | controller0_ | controller1_addres |
      | address   | address      | s                  |
    We join the two header rows to reconstruct the full column names before
    parsing the data rows.
    """
    rc, out, _ = run_log_only("system addrpool-list")
    if rc != 0 or not out:
        return []

    lines = out.splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        if "| name" in line and "uuid" in line:
            header_idx = i
            break
    if header_idx is None:
        return _parse_generic_table(out, key_col="name")

    def split_pipe(line):
        parts = line.split("|")
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        return parts

    row1 = split_pipe(lines[header_idx])

    col_names = [c.strip() for c in row1]
    if header_idx + 1 < len(lines):
        next_line = lines[header_idx + 1]
        if next_line.strip().startswith("|") and not next_line.startswith("+"):
            row2 = split_pipe(next_line)
            merged = []
            for i, c1 in enumerate(row1):
                c2 = row2[i].strip() if i < len(row2) else ""
                merged.append((c1.strip() + c2).strip())
            col_names = merged

    data_start = header_idx + 1
    while data_start < len(lines) and not lines[data_start].startswith("+"):
        data_start += 1
    data_start += 1

    sep_line = lines[data_start - 1] if data_start > 0 else ""

    merged_header = "| " + " | ".join(col_names) + " |"
    new_lines = lines[:header_idx] + [merged_header, sep_line] + lines[data_start:]
    new_out = "\n".join(new_lines)

    return _parse_generic_table(new_out, key_col="name")


def _get_network_list():
    rc, out, _ = run_log_only("system network-list")
    if rc != 0 or not out:
        return []
    return _parse_generic_table(out, key_col="name")


def _get_network_addrpool_list():
    rc, out, _ = run_log_only("system network-addrpool-list")
    if rc != 0 or not out:
        return []
    return _parse_generic_table(out, key_col="network_name")
