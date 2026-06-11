# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Kubernetes / Calico helpers shared across test suites.

import ipaddress
import json
import re
import shlex

from network_platform_audit import state
from network_platform_audit.log import log_to_file_only
from network_platform_audit.run import run_log_only
from network_platform_audit.run import run_silent

# ---------------------------------------------------------------------------
# kubectl wrapper
# ---------------------------------------------------------------------------


def _kubectl(cmd, timeout=None):
    rc, out, err = run_log_only(["kubectl"] + shlex.split(cmd), timeout=timeout)
    return rc, out, err


# ---------------------------------------------------------------------------
# CoreDNS helpers
# ---------------------------------------------------------------------------

def _get_coredns_pid():
    """Return the host-namespace PID of the coredns pod sandbox.

    crictl inspectp output has multiple "pid" fields:
      "pid": 1             <- PID inside the container namespace (always 1)
      "pid": 155325,       <- PID in the host namespace (what we need for nsenter)
    We need the one with a value > 1.
    """
    rc, pods_out, _ = run_log_only("crictl pods --namespace kube-system --name coredns -q")
    if rc != 0 or not pods_out:
        return None
    pod_id = pods_out.splitlines()[0].strip()
    rc, inspect_out, _ = run_silent(["crictl", "inspectp", pod_id])
    if rc != 0 or not inspect_out:
        return None
    pids = re.findall(r'"pid":\s*(\d+)', inspect_out)
    for pid in pids:
        if int(pid) > 1:
            log_to_file_only(f"$ crictl inspectp {pod_id}  -> host-ns pid={pid}")
            return pid
    return None


# ---------------------------------------------------------------------------
# GlobalNetworkPolicy helpers
# ---------------------------------------------------------------------------

# Mapping of GNP name patterns to sysinv pool name keywords
GNP_NETWORK_MAP = {
    "controller-mgmt-if-gnp":          ["management", "mgmt"],
    "controller-oam-if-gnp":           ["oam"],
    "controller-pxeboot-if-gnp":       ["pxeboot"],
    "controller-admin-if-gnp":         ["admin"],
    "controller-storage-if-gnp":       ["storage"],
    "controller-cluster-host-if-gnp":  ["cluster-host"],
}


def _get_globalnetworkset_nets():
    """Return a dict mapping each GlobalNetworkSet label selector expression
    to the list of nets it contains.
    """
    rc, out, _ = run_log_only(
        "kubectl get globalnetworksets.crd.projectcalico.org -o json"
    )
    if rc != 0 or not out:
        return {}
    try:
        data = json.loads(out)
    except Exception:
        return {}

    result = {}
    for item in data.get("items", []):
        labels = item.get("metadata", {}).get("labels", {})
        nets = item.get("spec", {}).get("nets", [])
        if not nets:
            continue
        for k, v in labels.items():
            for quote in ("'", '"'):
                key = f"{k} == {quote}{v}{quote}"
                result.setdefault(key, [])
                result[key] = list(set(result[key]) | set(nets))
            result.setdefault(v, [])
            result[v] = list(set(result[v]) | set(nets))
    return result


def _expand_selector_nets(selector, gns_map):
    """Return the list of nets referenced by a GNP rule selector string."""
    if not selector or not gns_map:
        return []

    if selector in gns_map:
        return gns_map[selector]

    m = re.search(r"""==\s*['"]([^'"]+)['"]""", selector)
    if m:
        label_value = m.group(1)
        if label_value in gns_map:
            return gns_map[label_value]

    return []


def _get_gnp_list():
    """Return parsed list of GlobalNetworkPolicies as dicts with name and source_nets."""
    rc, out, _ = run_log_only(
        "kubectl get globalnetworkpolicies.crd.projectcalico.org -o json"
    )
    if rc != 0 or not out:
        return []
    try:
        data = json.loads(out)
    except Exception:
        return []

    gns_nets_by_selector = _get_globalnetworkset_nets()

    gnps = []
    for item in data.get("items", []):
        name = item.get("metadata", {}).get("name", "")
        spec = item.get("spec", {})
        selector = spec.get("selector", "")
        ingress = spec.get("ingress", [])
        source_nets = set()
        dest_nets = set()
        ports_allow = set()
        systemcontroller_nets = set()
        for rule in ingress:
            rule_annotation = (rule.get("metadata", {})
                               .get("annotations", {})
                               .get("name", ""))
            is_sc_rule = "systemcontroller" in rule_annotation.lower()
            for src in rule.get("source", {}).get("nets", []):
                source_nets.add(src)
                if is_sc_rule:
                    systemcontroller_nets.add(src)
            src_selector = rule.get("source", {}).get("selector", "")
            if src_selector:
                for net in _expand_selector_nets(src_selector, gns_nets_by_selector):
                    source_nets.add(net)
                    if is_sc_rule:
                        systemcontroller_nets.add(net)
            for dst in rule.get("destination", {}).get("nets", []):
                dest_nets.add(dst)
                if is_sc_rule:
                    systemcontroller_nets.add(dst)
            dst_selector = rule.get("destination", {}).get("selector", "")
            if dst_selector:
                for net in _expand_selector_nets(dst_selector, gns_nets_by_selector):
                    dest_nets.add(net)
                    if is_sc_rule:
                        systemcontroller_nets.add(net)
            for port_rule in rule.get("destination", {}).get("ports", []):
                ports_allow.add(str(port_rule))
        gnps.append({
            "name": name,
            "selector": selector,
            "source_nets": list(source_nets),
            "dest_nets": list(dest_nets),
            "ports_allow": list(ports_allow),
            "systemcontroller_nets": list(systemcontroller_nets),
        })
    return gnps


def _pool_subnet_str(pool):
    """Build CIDR string from pool, handling multi-line network field."""
    network = pool.get("network", pool.get("subnet", ""))
    prefix = pool.get("prefix", pool.get("prefix_length", ""))
    network = re.sub(r"\s+", "", network)
    if network and prefix:
        try:
            net_obj = ipaddress.ip_network(f"{network}/{prefix}", strict=False)
            return str(net_obj)
        except ValueError:
            return None
    return None


def _gnp_selector_nodetypes(selector):
    """Extract nodetype values from a GNP selector string."""
    nodetypes = set()
    for m in re.finditer(r"nodetype\s*==\s*['\"](\w+)['\"]", selector):
        nodetypes.add(m.group(1))
    m = re.search(r"nodetype\s+in\s+\{([^}]+)\}", selector)
    if m:
        for v in re.findall(r"['\"](\w+)['\"]", m.group(1)):
            nodetypes.add(v)
    return nodetypes


def _hosts_for_gnp(gnp):
    """Return list of hostnames from HOST_LIST that match the GNP selector.

    Calico nodetype maps to sysinv personality:
      nodetype == 'controller' -> personality in (controller)
      nodetype == 'worker'     -> personality in (worker, compute)
      nodetype == 'storage'    -> personality == storage
    If no nodetype is specified, all hosts are returned.
    """
    nodetypes = _gnp_selector_nodetypes(gnp.get("selector", ""))
    if not nodetypes:
        return [h.get("hostname", "") for h in state.HOST_LIST if h.get("hostname")]

    personality_map = {
        "controller": {"controller"},
        "worker":     {"worker", "compute"},
        "storage":    {"storage"},
    }
    accepted = set()
    for nt in nodetypes:
        accepted |= personality_map.get(nt, {nt})

    result = []
    for h in state.HOST_LIST:
        hn = h.get("hostname", "")
        pers = h.get("personality", "").lower()
        if hn and pers in accepted:
            result.append(hn)
    return result


def _gnp_chain_has_subnet(gnp_name, subnet, ipt_text, use_nft=False):
    """Check if subnet appears in iptables/nftables for a given GNP.

    Returns "literal" if the subnet appears as explicit match inside the GNP
    chain, "ipset" if encoded via ipset/match-set, or None if not found.
    """
    if use_nft:
        gnp_log_pattern = rf'log prefix "[^"]*{re.escape(gnp_name)}'
        chain_blocks = []
        for m in re.finditer(r'chain (cali-pi-\S+)\s*\{', ipt_text):
            start = m.end()
            depth = 1
            pos = start
            while pos < len(ipt_text) and depth > 0:
                if ipt_text[pos] == '{':
                    depth += 1
                elif ipt_text[pos] == '}':
                    depth -= 1
                pos += 1
            block = ipt_text[start:pos - 1]
            if re.search(gnp_log_pattern, block):
                chain_blocks.append(block)

        if not chain_blocks:
            return None

        for chain_block in chain_blocks:
            if f"ip saddr {subnet}" in chain_block or f"ip6 saddr {subnet}" in chain_block:
                return "literal"
            if f"ip daddr {subnet}" in chain_block or f"ip6 daddr {subnet}" in chain_block:
                return "literal"

        try:
            target_net = ipaddress.ip_network(subnet, strict=False)
            for chain_block in chain_blocks:
                for token in re.findall(r'[\da-fA-F:.]+/\d+', chain_block):
                    try:
                        if ipaddress.ip_network(token, strict=False) == target_net:
                            return "literal"
                    except ValueError:
                        pass
        except ValueError:
            pass

        if any('# match-set' in cb for cb in chain_blocks):
            return "ipset"
        return None
    else:
        if f"-s {subnet}" in ipt_text or f"-d {subnet}" in ipt_text:
            return "literal"
        chain_match = re.search(
            rf'-A (cali-pi-\S+) .*Policy {re.escape(gnp_name)} ingress', ipt_text
        )
        if chain_match:
            chain = chain_match.group(1)
            if re.search(rf'-A {re.escape(chain)} .*--match-set.*MARK', ipt_text):
                return "ipset"
        return None
