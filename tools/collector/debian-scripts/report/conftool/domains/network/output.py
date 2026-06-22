########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Network Domain — Output Writers

JSON and human-readable text output for the network domain.

Entry points (exported via domains/network/__init__.py):
    write_json(summary, output_path)
    write_text(summary, lines)
"""

import json
import sys

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# Allow imports when run from the conftool directory

from host_utils import get_verbose_level  # noqa: E402
# ===================================================================
# Network domain output
# ===================================================================


def write_json(summary, output_path):
    """Write network summary to JSON file."""
    out = dict(summary)
    if get_verbose_level() < 4:
        out['interfaces'] = [
            i for i in out['interfaces'] if not i.get('verbose_only')]
    for i in out.get('interfaces', []):
        i.pop('verbose_only', None)
    with open(output_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)


def write_text(summary, lines):
    """Append network summary sections to lines list."""
    verbose = get_verbose_level()
    s = summary
    W = 60

    def section(title):
        lines.append('')
        lines.append('=' * W)
        lines.append(f"  {title}")
        lines.append('=' * W)

    def kv(key, val, indent=2):
        lines.append(f"{' ' * indent}{key:<28s} {val}")

    # Host identity
    h = s['host']
    lines.append(f"Network Config Summary: {h['hostname']}")
    lines.append(f"  {h['personality']}/{h['subfunctions']}  "
                 f"{h['system_type']}  {h['system_mode']}  "
                 f"v{h['sw_version']}")
    lines.append(f"  Collected: {h['collected']}")

    # Interfaces — hierarchical tree
    section('Interfaces')
    _write_interface_tree(s, lines, verbose)

    # Address - Domain Name Associations
    hosts = s.get('hosts_file', [])
    nets = s.get('networks', {})
    if hosts or any(n.get('gateway') for n in nets.values()):
        section('Address - Domain Name Associations')
        # Show gateway first
        for role in ['oam', 'mgmt', 'cluster_host']:
            net = nets.get(role)
            if net and net.get('gateway'):
                lines.append(
                    f"  {'gateway':<10s}{net['gateway']:<22s} "
                    f"{role} gateway")
        tags = {
            'local': 'local', 'floating': 'floating',
            'peer': 'peer', 'external': 'external',
        }
        for e in hosts:
            lines.append(
                f"  {tags.get(e['type'], ''):<10s}"
                f"{e['ip']:<22s} "
                f"{', '.join(e['hostnames'])}")
    # Routing
    section('Routing')
    r = s.get('routing', {})
    if r.get('default_gateway'):
        kv('Default gateway', r['default_gateway'])
    for sub in r.get('connected_subnets', []):
        kv('Connected', sub)
    for nh, count in r.get('bgp', {}).items():
        kv(f'BGP via {nh}', count)

    # Pod network
    pod = s.get('pod_network')
    if pod:
        section('Pod Network')
        kv('veth interfaces', str(pod['veth_count']))
        for cidr in pod.get('cidrs', []):
            kv('CIDR', cidr)
    for p in s.get('pod_interfaces', []):
        lines.append(f"    {p['name']:<28s} {p['state']:<6s} "
                     f"rx:{p['rx']:>8s}  tx:{p['tx']:>8s}")

    # Listeners
    listeners = s.get('listeners')
    if listeners:
        section('Listeners')
        for prog, ports in listeners.items():
            lines.append(f"  {prog:<24s} {', '.join(str(p) for p in ports)}")

    # Connections
    conn = s.get('connections')
    sockstat = s.get('sockstat', {})
    if conn or sockstat:
        section('Connections')
        if sockstat:
            sockets_used = sockstat.get('sockets', {}).get('used', '')
            tcp = sockstat.get('TCP', {})
            parts = []
            if sockets_used:
                parts.append(f"sockets:{sockets_used}")
            for k in ['inuse', 'orphan', 'tw', 'alloc']:
                v = tcp.get(k)
                if v is not None:
                    parts.append(f"tcp_{k}:{v}")
            if parts:
                lines.append(f"  {', '.join(parts)}")
        if conn:
            lines.append(
                f"  {', '.join(f'{st}:{n}' for st, n in sorted(conn.items()))}")
    # Cross-check
    checks = s.get('cross_check', [])
    if checks:
        section('Cross-Check')
        icons = {'OK': '\u2705', 'WARN': '\u26a0\ufe0f ', 'FAIL': '\u274c', 'INFO': '\u2139\ufe0f '}
        for c in checks:
            lines.append(f"  {icons.get(c['status'], '  ')} {c['check']}: {c['detail']}")

    # Warnings
    warnings = s.get('warnings', [])
    if warnings:
        section('Warnings')
        for w in warnings:
            lines.append(f"  \u26a0\ufe0f  {w}")

    # Source files
    sources = s.get('source_files', [])
    if sources:
        section('Source Files')
        for src in sources:
            lines.append(f"  {src}")


def _format_traffic(t):
    """Format traffic dict into a compact string."""
    if not t:
        return ''
    traf = f"rx:{t['rx']:>8s} tx:{t['tx']:>8s}"
    if t['rx_errors'] or t['rx_dropped'] or t['tx_errors'] or t['tx_dropped']:
        traf += (f" err:{t['rx_errors']}/{t['tx_errors']}"
                 f" drop:{t['rx_dropped']}/{t['tx_dropped']}")
    return traf


def _write_interface_tree(s, lines, verbose):
    """Render interfaces as a hierarchy grouped by network role.

    Structure: network role -> bond/vlan/physical -> children
    Bonds contain physical slaves; VLANs sit on top of bonds or
    physical interfaces.
    """
    by_name = {i['name']: i for i in s['interfaces']}
    nets = s.get('networks', {})
    shown = set()

    # Column where traffic/speed starts (from left edge of line)
    DETAIL_COL = 60

    def iface_line(indent, iface, label='', slave_tag=''):
        """Format one interface line at the given indent depth."""
        prefix = '  ' + '  ' * indent
        name = iface['name']
        tags = []
        if slave_tag:
            tags.append(slave_tag)
        elif iface.get('bond_mode'):
            tags.append(iface['bond_mode'])
        elif iface.get('type') == 'vlan':
            tags.append('vlan')
        state = iface['state']
        addrs = ', '.join(iface.get('ipv4', []) + iface.get('ipv6', []))
        tag_str = f" ({', '.join(tags)})" if tags else ''
        left = f"{prefix}{name}{tag_str}  {state}"
        if iface.get('link_failures'):
            left += f"  link_failures:{iface['link_failures']}"
        if addrs:
            left += f"  {addrs}"
        # Right side: traffic and speed
        right_parts = []
        traf = _format_traffic(iface.get('traffic'))
        if traf:
            right_parts.append(traf)
        if iface.get('speed'):
            right_parts.append(iface['speed'])
        if right_parts:
            right = '  '.join(right_parts)
            pad = max(DETAIL_COL - len(left), 2)
            left += ' ' * pad + right
        if label:
            lines.append(f"{prefix}{label}")
        lines.append(left)

    def get_slaves(bond_name):
        """Return list of interfaces whose master is bond_name."""
        return [i for i in s['interfaces']
                if i.get('master') == bond_name and not i.get('verbose_only')]

    def render_bond(indent, bond):
        """Render a bond and its physical slaves."""
        iface_line(indent, bond)
        shown.add(bond['name'])
        for slave in get_slaves(bond['name']):
            tag = slave.get('bond_slave_state', '')
            iface_line(indent + 1, slave, slave_tag=tag)
            shown.add(slave['name'])

    for role in ['oam', 'mgmt', 'pxeboot', 'cluster_host', 'data']:
        net = nets.get(role)
        if not net:
            continue
        net_iface = by_name.get(net.get('interface', ''))
        if not net_iface:
            lines.append(f"  {role}: interface not found")
            continue

        lines.append(f"  {role}")

        if net_iface.get('type') == 'vlan':
            iface_line(1, net_iface)
            shown.add(net_iface['name'])
            parent_name = net_iface.get('parent', '')
            parent = by_name.get(parent_name)
            if parent and parent.get('bond_mode'):
                render_bond(2, parent)
            elif parent:
                iface_line(2, parent)
                shown.add(parent['name'])
        elif net_iface.get('bond_mode'):
            render_bond(1, net_iface)
        else:
            iface_line(1, net_iface)
            shown.add(net_iface['name'])

    # Remaining interfaces not part of any network role
    remaining = [i for i in s['interfaces']
                 if i['name'] not in shown and not i.get('verbose_only')]
    if remaining:
        lines.append("  other")
        for i in remaining:
            if i.get('master') and i['master'] in shown:
                continue
            iface_line(1, i)
            shown.add(i['name'])

    hidden = s.get('down_no_role_count', 0)
    if hidden and verbose < 4:
        lines.append(f"  ... {hidden} DOWN with no role (use -vvv)")
