# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Shared helpers for DC firewall port reachability checks.
#
# Port lists mirror exactly what sysinv puppet/platform_firewall.py builds into
# the GNP via _get_subcloud_tcp_ports() and _get_systemcontroller_tcp_ports():
#
#   port_list = list(firewall.SUBCLOUD["tcp"].keys())
#   http_service_port = self._get_http_service_port()   # from service-parameter
#   if http_service_port:
#       port_list.append(http_service_port)
#
# The http_service_port is the HTTPS (or HTTP) port from the service-parameter
# table (service=http, section=config, name=https_port or http_port).  On most
# systems this resolves to 8443 (the default HTTPS port), which is why 8443
# appears in the live GNP even though it is not in platform_firewall.SUBCLOUD.
#
# Verdict logic for nc failures
# ------------------------------
# A failed nc probe is classified by the error type:
#
#   Connection refused  -> the target host rejected the TCP SYN (port closed,
#                         no service listening).  The firewall allowed the
#                         packet through but no process is bound to that port.
#                         Verdict: WARN: optional/conditional service not running.
#
#   Timed out / no reply -> the TCP SYN was silently dropped somewhere in the
#                          path (firewall rule, routing black-hole, or the
#                          target host's kernel dropped it without RST).
#                          Verdict: FAILED: connectivity is blocked.
#
# For test (SC -> subcloud), an additional ss-based check runs over SSH on the
# subcloud when an SSH session is available, so we can distinguish "service
# not listening" from "nc could not even reach the host".

import re
import sys

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.run import run_log_only
from network_platform_audit.run import run_silent
from network_platform_audit.ssh import remote_run


# ---------------------------------------------------------------------------
# platform_firewall loader
# ---------------------------------------------------------------------------

def _load_platform_firewall():
    """Import sysinv.common.platform_firewall from the installed package.

    Returns the module on success, None if not available.
    """
    try:
        if "/usr/lib/python3/dist-packages" not in sys.path:
            sys.path.insert(0, "/usr/lib/python3/dist-packages")
        from sysinv.common import platform_firewall
        return platform_firewall
    except ImportError as exc:
        log(f"  [WARN] could not import sysinv.common.platform_firewall: {exc}")
        return None


# ---------------------------------------------------------------------------
# HTTP/HTTPS service port
# ---------------------------------------------------------------------------

def _get_http_service_port():
    """Return the configured HTTPS (or HTTP) service port from service-parameter.

    Mirrors what puppet's _get_http_service_port() does:
    - if https_enabled  -> read service-parameter http/config/https_port
    - else              -> read service-parameter http/config/http_port

    state.HTTPS_ENABLED is populated by startup_checks() from 'system show'.
    The result is cached in state.HTTP_SERVICE_PORT so the service-parameter
    CLI is queried only once per run regardless of how many subclouds are tested.

    Returns the port as an int, or None if not found / not customised.
    """
    if state.HTTP_SERVICE_PORT is not None:
        # Sentinel 0 means "already checked, not found"
        return state.HTTP_SERVICE_PORT if state.HTTP_SERVICE_PORT > 0 else None

    param_name = "https_port" if state.HTTPS_ENABLED else "http_port"

    rc, out, _ = run_silent(["system", "service-parameter-list", "--nowrap"])
    if rc != 0 or not out:
        rc, out, _ = run_silent("system service-parameter-list")

    if rc == 0 and out:
        for line in out.splitlines():
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 5:
                continue
            svc, sec, name, val = parts[1], parts[2], parts[3], parts[4]
            if svc == "http" and sec == "config" and name == param_name:
                try:
                    port = int(val)
                    state.HTTP_SERVICE_PORT = port
                    return port
                except ValueError:
                    pass

    # Sentinel: checked and not found (0 is not a valid port)
    state.HTTP_SERVICE_PORT = 0
    return None


# ---------------------------------------------------------------------------
# Port list builders
# ---------------------------------------------------------------------------

def _build_ports(fw_module, dict_names, proto="tcp", http_port=None):
    """Return sorted, de-duplicated port list of a given proto ('tcp' or 'udp')
    merged from dict_names.

    dict_names may be a single dict name (str) or a list of dict names;
    ports from all of them are combined. Optionally adds http_port (tcp only).
    """
    if isinstance(dict_names, str):
        dict_names = [dict_names]
    ports = set()
    for dict_name in dict_names:
        raw = getattr(fw_module, dict_name, {})
        entries = raw.get(proto, {})
        if isinstance(entries, dict):
            ports.update(entries.keys())
        elif isinstance(entries, (set, list)):
            ports.update(entries)
    if http_port:
        ports.add(http_port)
    return sorted(ports)


def _port_label(fw_module, dict_names, port, http_port=None, proto="tcp"):
    """Return 'port (service)' label, e.g. '6386 (sysinv-api)'.

    dict_names may be a single dict name (str) or a list of dict names;
    they are searched in order for a service name matching port.
    """
    if port == http_port:
        return f"{port} (https-service)"
    if isinstance(dict_names, str):
        dict_names = [dict_names]
    for dict_name in dict_names:
        raw = getattr(fw_module, dict_name, {})
        entries = raw.get(proto, {})
        if isinstance(entries, dict) and port in entries:
            svc = entries[port]
            return f"{port} ({svc})" if svc else str(port)
    return str(port)


_LABEL_SVC_RE = re.compile(r"^\d+ \((.+)\)$")


def _group_port_reasons(entries):
    """Group (port, label, detail) entries by (service, detail).

    Many ports can share the identical service name and failure/warning
    detail (e.g. ten Kafka NodePorts all reporting "SC service not listening
    (not being used?)" because Analytics isn't applied) - collapsing these
    into a single summary line avoids one line per port for what is really
    one underlying condition. Returns an ordered list of (ports, service,
    detail) tuples.
    """
    groups = {}
    order = []
    for port, label, detail in entries:
        m = _LABEL_SVC_RE.match(label)
        svc = m.group(1) if m else ""
        key = (svc, detail)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(port)
    return [(groups[key], key[0], key[1]) for key in order]


def _format_grouped_label(ports, svc):
    ports_str = ",".join(str(p) for p in ports)
    return f"{ports_str} ({svc})" if svc else ports_str


# ---------------------------------------------------------------------------
# GNP diagnostic dump (called once when any port fails or warns)
# ---------------------------------------------------------------------------

_GNP_DUMP_DONE = False  # module-level flag: dump once per run


def _reset_gnp_dump_flag():
    """Reset the GNP dump flag (for unit testing across multiple runs)."""
    global _GNP_DUMP_DONE
    _GNP_DUMP_DONE = False


def _dump_dc_gnps():
    """Dump controller-mgmt-if-gnp and controller-admin-if-gnp (if present).

    Runs kubectl get ... -o yaml and writes output to the log file only
    (not stdout) so it does not clutter the console.  Called once per run
    when any firewall port check produces WARN or FAILED.
    """
    global _GNP_DUMP_DONE
    if _GNP_DUMP_DONE:
        return
    _GNP_DUMP_DONE = True

    from network_platform_audit.log import log_to_file_only  # noqa: PLC0415

    for gnp_name in ("controller-mgmt-if-gnp", "controller-admin-if-gnp"):
        rc, out, _ = run_silent(
            ["kubectl", "get",
             "globalnetworkpolicies.crd.projectcalico.org",
             gnp_name, "-o", "yaml"]
        )
        if rc != 0 or not out:
            log_to_file_only(
                f"[GNP-DUMP] {gnp_name}: not found or kubectl failed"
            )
            continue
        log_to_file_only(f"[GNP-DUMP] {gnp_name}:\n{out}")

# Verdict constants
_PASS = "PASS"
_WARN = "WARN"
_FAILED = "FAILED"


def _nc_port_classified(ip, port, protocol="tcp", timeout=3):
    """Probe a TCP or UDP port and return (success, verdict, reason).

    Returns (for TCP):
        (True,  _PASS,   "")           connection succeeded
        (False, _WARN,   "refused")    port closed (no service listening)
        (False, _FAILED, "timeout")    packet dropped (firewall/routing)
        (False, _FAILED, "unknown")    other nc error

    UDP is connectionless: nc only reports "refused" when the target replies
    with ICMP port-unreachable. When no reply comes back at all ("timeout" or
    "unknown", i.e. non-zero rc with no recognizable message), that can mean
    an open-but-firewalled port, a closed port whose ICMP reply was itself
    blocked/rate-limited, or a transient miss (e.g. cold neighbor-discovery
    cache), these are indistinguishable from each other, so for UDP such
    results are downgraded to _WARN (inconclusive) instead of _FAILED.
    """
    flag = ["-6"] if ":" in ip else []
    if protocol == "udp":
        flag = flag + ["-u"]
    rc, _, stderr = run_log_only(
        ["nc"] + flag + ["-vz", "-w", str(timeout), ip, str(port)]
    )
    if rc == 0:
        return True, _PASS, ""
    err = (stderr or "").lower()
    if "refused" in err or "connection refused" in err:
        return False, _WARN, "refused"
    inconclusive_verdict = _WARN if protocol == "udp" else _FAILED
    if "timed out" in err or "timeout" in err or "no route" in err:
        return False, inconclusive_verdict, "timeout"
    return False, inconclusive_verdict, "unknown"


def _is_ceph_enabled_remote(ssh_target):
    """Return True if the subcloud (reached via ssh_target) has a Ceph
    storage backend configured, mirroring sysinv puppet's _is_ceph_enabled()
    (which gates whether PLATFORM_CEPH_PARAMS_RGW_PORT is opened on the OAM
    GNP: _set_rules_oam() removes that port entirely when Ceph is disabled).

    Returns False (not enabled) when this cannot be determined - no SSH
    target available, or the command fails - so callers default to excluding
    the RGW port rather than risk testing a port that was never opened.
    """
    if not ssh_target:
        return False
    rc, out, _ = remote_run(
        ssh_target,
        "bash -c 'source /etc/platform/openrc && system storage-backend-list --nowrap'",
        use_sudo=False,
    )
    if rc != 0 or not out:
        return False
    return any("ceph" in line.lower() for line in out.splitlines())


def _ss_port_listening(port, ssh_target=None, protocol="tcp"):
    """Return True if a TCP or UDP port is bound/listening.

    If ssh_target is provided, checks remotely via SSH.
    Otherwise checks locally.
    The ss command checks both IPv4 and IPv6 listeners.
    """
    flag = "-tlnp" if protocol == "tcp" else "-ulnp"
    cmd = f"ss {flag} 'sport = :{port}'"
    if ssh_target:
        rc, out, _ = remote_run(ssh_target, cmd, use_sudo=False)
    else:
        rc, out, _ = run_silent(cmd)
    if rc != 0 or not out:
        return False
    # ss output has a header line; a matching line has the port in it.
    # TCP listeners show state LISTEN; UDP listeners show state UNCONN, so
    # for UDP the port match alone (already filtered by -l) is sufficient.
    for line in out.splitlines():
        if f":{port}" not in line:
            continue
        if protocol == "tcp" and "LISTEN" not in line:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# SC -> subcloud: probe SUBCLOUD ports from the System Controller
# ---------------------------------------------------------------------------

def _probe_subcloud_ports(cat, sc_name, ip, ports, fw_module, dict_names,
                          ssh_target, proto="tcp", http_port=None):
    """Probe ports on ip and classify refusals via ss (see verdict logic
    in check_firewall_ports_to_subcloud). Returns (failed_count, warned_count).
    """
    proto_label = proto.upper()
    failed = warned = 0
    failed_entries = []
    warned_entries = []
    for port in ports:
        label = _port_label(fw_module, dict_names, port, http_port, proto)
        ok, verdict, reason = _nc_port_classified(ip, port, protocol=proto)

        if ok:
            log_result(f"  {sc_name}: {proto_label} {ip}:{label}", _PASS)
            continue

        if reason == "refused":
            # Check whether the service is actually listening on the subcloud
            if ssh_target:
                listening = _ss_port_listening(port,
                                              ssh_target=ssh_target,
                                              protocol=proto)
                if listening:
                    # Service is up but connection was refused, unexpected
                    verdict = _FAILED
                    detail = "refused but ss shows LISTEN on subcloud"
                else:
                    verdict = _WARN
                    detail = "service not listening on subcloud"
            else:
                # No SSH available, assume service not running (WARN)
                verdict = _WARN
                detail = "refused (no SSH to verify ss on subcloud)"
        elif proto == "udp":
            # UDP has no reliable signal: no reply could mean port not open
            # on destination OR firewall rule not installed (packet dropped).
            if reason == "timeout":
                detail = ("UDP inconclusive (no reply) - port may not be open "
                          "on destination or firewall rule not installed")
            else:
                detail = ("UDP inconclusive - port may not be open on "
                          "destination or firewall rule not installed")
        else:
            detail = f"nc {reason}"

        log_result(f"  {sc_name}: {proto_label} {ip}:{label} [{detail}]", verdict)
        if verdict == _FAILED:
            failed += 1
            failed_entries.append((port, label, detail))
        else:
            warned += 1
            warned_entries.append((port, label, detail))

    for grouped_ports, svc, detail in _group_port_reasons(failed_entries):
        label = _format_grouped_label(grouped_ports, svc)
        state.category_failures[cat].append(
            f"subcloud {sc_name}: {proto_label} {ip}:{label} {detail}"
        )
    for grouped_ports, svc, detail in _group_port_reasons(warned_entries):
        label = _format_grouped_label(grouped_ports, svc)
        state.category_warnings[cat].append(
            f"subcloud {sc_name}: {proto_label} {ip}:{label} {detail}"
        )
    return failed, warned


def check_firewall_ports_to_subcloud(cat, sc_name, target_ip, fw_module,
                                     ssh_target=None, oam_ip=None):
    """From the System Controller, probe subcloud TCP and UDP ports.

    Mgmt-network ports = platform_firewall.SUBCLOUD["tcp"/"udp"] +
    http_service_port (tcp only), probed against target_ip, mirroring
    _get_subcloud_tcp_ports() in sysinv puppet/platform_firewall.py.
    Docker registry/token ports (9001/9002) are excluded: they may bind to
    either mgmt or admin depending on the subcloud's config, and dcmanager
    doesn't expose which - an admin address silently replaces target_ip
    with no visible trace, so testing these two here is unreliable.

    OAM-network ports = platform_firewall.OAM_COMMON["tcp"/"udp"], probed
    against oam_ip (skipped if not provided). Excluded from this list,
    mirroring _set_rules_oam()'s own exclusions for the subcloud role:
    the fixed HTTPS port (8443, only kept on the system controller's OAM
    GNP), the Ceph RGW port (7480, unless Ceph is confirmed via SSH), and
    the SM heartbeat ports (2222/2223, peer-to-peer between the
    subcloud's own two controllers).

    Verdict logic per port:
      nc PASS                          -> PASS
      nc refused + ss not listening    -> WARN  (service not running on subcloud)
      nc refused + ss listening        -> FAILED (firewall blocked RST but not SYN?)
      nc refused + ss unavailable      -> WARN  (assume service not running)
      nc timeout                       -> FAILED (firewall/routing dropping packets)

    ssh_target: if provided, ss is run remotely on the subcloud to check whether
    the service is actually listening before escalating a refusal to FAILED.
    """
    http_port = _get_http_service_port()
    if http_port and http_port > 0:
        log(f"  [INFO] http_service_port={http_port} "
            f"({'https' if state.HTTPS_ENABLED else 'http'}, from service-parameter)")
    else:
        http_port = None

    mgmt_tcp = _build_ports(fw_module, "SUBCLOUD", "tcp", http_port)
    mgmt_udp = _build_ports(fw_module, "SUBCLOUD", "udp")
    oam_tcp = _build_ports(fw_module, "OAM_COMMON", "tcp")
    oam_udp = _build_ports(fw_module, "OAM_COMMON", "udp")

    constants_mod = getattr(fw_module, "constants", None)
    docker_ports = {
        getattr(constants_mod, "PLATFORM_DOCKER_PARAMS_REGISTRY_PORT", None),
        getattr(constants_mod, "PLATFORM_DOCKER_PARAMS_TOKEN_PORT", None),
    } - {None}
    mgmt_tcp = [p for p in mgmt_tcp if p not in docker_ports]

    https_port = getattr(constants_mod, "PLATFORM_FIREWALL_HTTPS_PORT", None)
    if https_port and https_port in oam_tcp:
        oam_tcp = [p for p in oam_tcp if p != https_port]

    rgw_port = getattr(constants_mod, "PLATFORM_CEPH_PARAMS_RGW_PORT", None)
    if rgw_port and rgw_port in oam_tcp and not _is_ceph_enabled_remote(ssh_target):
        oam_tcp = [p for p in oam_tcp if p != rgw_port]
        log(f"  [INFO] {sc_name}: Ceph backend not detected on subcloud "
            f"(or unverifiable) - excluding RGW port {rgw_port} from OAM TCP test")

    sm_ports = {
        getattr(constants_mod, "PLATFORM_FIREWALL_SM_PORT_1", None),
        getattr(constants_mod, "PLATFORM_FIREWALL_SM_PORT_2", None),
    } - {None}
    oam_udp = [p for p in oam_udp if p not in sm_ports]

    if not any([mgmt_tcp, mgmt_udp, oam_tcp, oam_udp]):
        log(f"  [INFO] {sc_name}: no TCP/UDP ports resolved for "
            f"SUBCLOUD/OAM_COMMON - skipping")
        return

    failed = warned = total = 0
    oam_ip_warned = False

    for proto, mgmt_ports, oam_ports in (("tcp", mgmt_tcp, oam_tcp),
                                         ("udp", mgmt_udp, oam_udp)):
        mgmt_http_port = http_port if proto == "tcp" else None
        if mgmt_ports:
            log(f"  [{sc_name}] firewall port check (mgmt/{proto}) -> {target_ip} "
                f"({len(mgmt_ports)} ports: {', '.join(str(p) for p in mgmt_ports)})")
            f, w = _probe_subcloud_ports(cat, sc_name, target_ip, mgmt_ports,
                                         fw_module, "SUBCLOUD", ssh_target, proto,
                                         mgmt_http_port)
            failed += f
            warned += w
            total += len(mgmt_ports)

        if oam_ports:
            if oam_ip:
                log(f"  [{sc_name}] firewall port check (oam/{proto}) -> {oam_ip} "
                    f"({len(oam_ports)} ports: {', '.join(str(p) for p in oam_ports)})")
                f, w = _probe_subcloud_ports(cat, sc_name, oam_ip, oam_ports,
                                             fw_module, "OAM_COMMON", ssh_target,
                                             proto)
                failed += f
                warned += w
                total += len(oam_ports)
            elif not oam_ip_warned:
                log(f"  [WARN] {sc_name}: OAM_COMMON firewall port check (nc) to "
                    f"subcloud skipped - OAM IP not provided (use --subcloud-oam-ip)")
                state.category_warnings[cat].append(
                    f"subcloud {sc_name}: OAM_COMMON firewall port check skipped - "
                    f"--subcloud-oam-ip not provided"
                )
                oam_ip_warned = True

    if failed:
        log(f"  [{sc_name}] {failed} port(s) FAILED, {warned} WARN out of {total}")
    elif warned:
        log(f"  [{sc_name}] {warned} port(s) WARN (service not running) out of {total}")
    else:
        log(f"  [{sc_name}] all {total} firewall ports reachable")

    if failed or warned:
        _dump_dc_gnps()


# ---------------------------------------------------------------------------
# subcloud -> SC: probe SYSTEMCONTROLLER ports from the subcloud
# ---------------------------------------------------------------------------

def _probe_sc_ports(cat, ip, ports, fw_module, dict_names, http_port,
                    proto="tcp"):
    """Probe SC ports on ip (see verdict logic in check_firewall_ports_to_sc).

    Returns (failed_count, warned_count).
    """
    proto_label = proto.upper()
    failed = warned = 0
    failed_entries = []
    warned_entries = []
    for port in ports:
        label = _port_label(fw_module, dict_names, port, http_port, proto)
        ok, verdict, reason = _nc_port_classified(ip, port, protocol=proto)

        if ok:
            log_result(f"  SC {ip}: {proto_label} {label}", _PASS)
            continue

        if reason == "refused":
            verdict = _WARN
            detail = "SC service not listening (not being used?)"
        elif proto == "udp":
            # UDP has no reliable signal: no reply could mean port not open
            # on the SC or firewall rule not installed (packet dropped).
            if reason == "timeout":
                detail = ("UDP inconclusive (no reply) - port may not be open "
                          "on SC or firewall rule not installed")
            else:
                detail = ("UDP inconclusive - port may not be open on SC "
                          "or firewall rule not installed")
        else:
            detail = f"nc {reason}"

        log_result(f"  SC {ip}: {proto_label} {label} [{detail}]", verdict)
        if verdict == _FAILED:
            failed += 1
            failed_entries.append((port, label, detail))
        else:
            warned += 1
            warned_entries.append((port, label, detail))

    for grouped_ports, svc, detail in _group_port_reasons(failed_entries):
        label = _format_grouped_label(grouped_ports, svc)
        state.category_failures[cat].append(f"SC {ip}: {proto_label} {label} {detail}")
    for grouped_ports, svc, detail in _group_port_reasons(warned_entries):
        label = _format_grouped_label(grouped_ports, svc)
        state.category_warnings[cat].append(f"SC {ip}: {proto_label} {label} {detail}")
    return failed, warned


def check_firewall_ports_to_sc(cat, sc_ip, fw_module, oam_ip=None):
    """From a subcloud, probe SC TCP and UDP ports.

    Mgmt-network ports = platform_firewall.SYSTEMCONTROLLER["tcp"/"udp"] +
    http_service_port (tcp only), probed against sc_ip, matching
    stx-ingr-*-systemcontroller-tcp* in the SC GNP.
    OAM-network ports = OAM_COMMON["tcp"/"udp"] + OAM_DC["tcp"/"udp"], probed
    against oam_ip (skipped if oam_ip is not provided). SM_PORT_1/SM_PORT_2
    (UDP) are excluded from the OAM ports: those are used for sm heartbeat
    between the two controllers of the System Controller's own HA pair,
    never between a subcloud and the System Controller.

    Verdict logic per port:
      nc PASS                 -> PASS
      nc refused              -> WARN  (SC service not running: e.g. Analytics
                                       NodePorts when app not applied)
      nc timeout              -> FAILED (firewall/routing dropping packets)

    Note: we do not have a persistent SSH session to the SC from the subcloud,
    so we cannot run ss remotely. The nc error type is the sole signal:
    'refused' means the SC kernel sent RST -> firewall passed the packet -> WARN.
    'timeout' means the packet never arrived or was silently dropped -> FAILED.
    """
    http_port = _get_http_service_port()
    if http_port and http_port > 0:
        log(f"  [INFO] http_service_port={http_port} "
            f"({'https' if state.HTTPS_ENABLED else 'http'}, from service-parameter)")
    else:
        http_port = None

    oam_dict_names = ["OAM_COMMON", "OAM_DC"]

    mgmt_tcp = _build_ports(fw_module, "SYSTEMCONTROLLER", "tcp", http_port)
    mgmt_udp = _build_ports(fw_module, "SYSTEMCONTROLLER", "udp")
    oam_tcp = _build_ports(fw_module, oam_dict_names, "tcp")
    oam_udp = _build_ports(fw_module, oam_dict_names, "udp")

    constants_mod = getattr(fw_module, "constants", None)
    sm_ports = {
        getattr(constants_mod, "PLATFORM_FIREWALL_SM_PORT_1", None),
        getattr(constants_mod, "PLATFORM_FIREWALL_SM_PORT_2", None),
    } - {None}
    oam_udp = [p for p in oam_udp if p not in sm_ports]

    if not any([mgmt_tcp, mgmt_udp, oam_tcp, oam_udp]):
        log("  [INFO] no TCP/UDP ports resolved for "
            "SYSTEMCONTROLLER/OAM_COMMON/OAM_DC - skipping")
        return

    failed = warned = total = 0
    oam_ip_warned = False

    for proto, mgmt_ports, oam_ports in (("tcp", mgmt_tcp, oam_tcp),
                                         ("udp", mgmt_udp, oam_udp)):
        mgmt_http_port = http_port if proto == "tcp" else None
        if mgmt_ports:
            log(f"  [SC] firewall port check (mgmt/{proto}) -> {sc_ip} "
                f"({len(mgmt_ports)} ports: {', '.join(str(p) for p in mgmt_ports)})")
            f, w = _probe_sc_ports(cat, sc_ip, mgmt_ports, fw_module,
                                   "SYSTEMCONTROLLER", mgmt_http_port, proto)
            failed += f
            warned += w
            total += len(mgmt_ports)

        if oam_ports:
            if oam_ip:
                log(f"  [SC] firewall port check (oam/{proto}) -> {oam_ip} "
                    f"({len(oam_ports)} ports: {', '.join(str(p) for p in oam_ports)})")
                f, w = _probe_sc_ports(cat, oam_ip, oam_ports, fw_module,
                                       oam_dict_names, None, proto)
                failed += f
                warned += w
                total += len(oam_ports)
            elif not oam_ip_warned:
                log("  [INFO] SC OAM IP not available - OAM_COMMON/OAM_DC port "
                    "checks skipped")
                oam_ip_warned = True

    if failed:
        log(f"  [SC] {failed} port(s) FAILED, {warned} WARN out of {total}")
    elif warned:
        log(f"  [SC] {warned} port(s) WARN (service not running) out of {total}")
    else:
        log(f"  [SC] all {total} firewall ports reachable")

    if failed or warned:
        _dump_dc_gnps()
