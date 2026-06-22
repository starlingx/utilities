########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Network Domain — Config Loader and Summary Builder

Parses networking.info, interface.info, netstat.info, platform.conf,
and /etc/hosts from a collect bundle host directory.

Entry points (exported via domains/network/__init__.py):
    load_config(host_dir, config)
    build_summary(config) -> summary dict
"""

import os
import re
import sys

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# Allow imports when run from the conftool directory

from host_utils import human_bytes          # noqa: E402
from host_utils import note_source          # noqa: E402
from host_utils import parse_info_sections  # noqa: E402


# ---------------------------------------------------------------------------
# networking.info parsers
# ---------------------------------------------------------------------------
def parse_ip_link(text, config):
    interfaces = []
    pods = []
    blocks = re.split(r'\n(?=\d+:\s)', '\n' + text.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        header = re.match(
            r'^(\d+):\s+(\S+?)(?:@(\S+))?:\s+<([^>]*)>\s+mtu\s+(\d+)\s+.*state\s+(\S+)',
            block)
        if not header:
            continue
        name = header.group(2)
        iface = {
            'name': name,
            'index': int(header.group(1)),
            'flags': header.group(4),
            'mtu': int(header.group(5)),
            'state': header.group(6),
        }
        if header.group(3):
            iface['parent'] = header.group(3)
        master_m = re.search(r'master\s+(\S+)', header.group(0))
        if master_m:
            iface['master'] = master_m.group(1)
        mac_m = re.search(r'link/(?:ether|loopback)\s+([0-9a-f:]+)', block)
        if mac_m:
            iface['mac'] = mac_m.group(1)
        alt_m = re.search(r'^\s+altname\s+(\S+)', block, re.MULTILINE)
        if alt_m:
            iface['altname'] = alt_m.group(1)
        bond_mode_m = re.search(r'bond mode (\S+)', block)
        if bond_mode_m:
            iface['bond_mode'] = bond_mode_m.group(1)
        slave_state_m = re.search(r'bond_slave state (\S+)', block)
        if slave_state_m:
            iface['bond_slave_state'] = slave_state_m.group(1)
        if re.search(r'\bvlan\b', block):
            iface['type'] = 'vlan'
        rx_m = re.findall(r'^\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$',
                          block, re.MULTILINE)
        if len(rx_m) >= 2:
            rx, tx = rx_m[0], rx_m[1]
            iface.update({
                'rx_bytes': int(rx[0]), 'rx_packets': int(rx[1]),
                'rx_errors': int(rx[2]), 'rx_dropped': int(rx[3]),
                'tx_bytes': int(tx[0]), 'tx_packets': int(tx[1]),
                'tx_errors': int(tx[2]), 'tx_dropped': int(tx[3]),
            })
        iface['ipv4'] = []
        iface['ipv6'] = []
        if name.startswith('cali') or name.startswith('cni-'):
            pods.append(iface)
        else:
            interfaces.append(iface)
    config['interfaces'] = interfaces
    config['pod_interfaces'] = pods


def parse_ip_addr_v4(text, config):
    _parse_ip_addr(text, config, 'ipv4', r'inet\s+(\S+)')


def parse_ip_addr_v6(text, config):
    _parse_ip_addr(text, config, 'ipv6', r'inet6\s+(\S+)')


def parse_ip_addr_combined(text, config):
    """Parse combined 'ip addr show' output (both inet and inet6)."""
    by_name = {i['name']: i for i in config.get('interfaces', [])}
    by_name.update({i['name']: i for i in config.get('pod_interfaces', [])})
    blocks = re.split(r'\n(?=\d+:\s)', '\n' + text.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        name_m = re.match(r'^\d+:\s+(\S+?)(?:@\S+)?:', block)
        if not name_m:
            continue
        name = name_m.group(1)
        if name in by_name:
            by_name[name]['ipv4'] = re.findall(r'inet\s+(\S+)', block)
            by_name[name]['ipv6'] = re.findall(r'inet6\s+(\S+)', block)


def _parse_ip_addr(text, config, key, addr_re):
    by_name = {i['name']: i for i in config.get('interfaces', [])}
    blocks = re.split(r'\n(?=\d+:\s)', '\n' + text.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        name_m = re.match(r'^\d+:\s+(\S+?)(?:@\S+)?:', block)
        if not name_m:
            continue
        name = name_m.group(1)
        if name in by_name:
            by_name[name][key] = re.findall(addr_re, block)


def parse_ip_route_v4(text, config):
    routing = config.setdefault('routing', {})
    routing.setdefault('default_gateway', None)
    routing.setdefault('connected', [])
    routing.setdefault('bgp_routes', [])
    routing.setdefault('pod_cidrs', [])
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('default'):
            m = re.search(r'via\s+(\S+)\s+dev\s+(\S+)', line)
            if m:
                routing['default_gateway'] = {'ip': m.group(1), 'dev': m.group(2)}
        elif line.startswith('blackhole'):
            m = re.match(r'blackhole\s+(\S+)', line)
            if m:
                routing['pod_cidrs'].append(m.group(1))
        elif 'proto bird' in line:
            m = re.match(r'(\S+)\s+via\s+(\S+)\s+dev\s+(\S+)', line)
            if m:
                routing['bgp_routes'].append({
                    'subnet': m.group(1), 'via': m.group(2), 'dev': m.group(3)})
        elif 'proto kernel' in line:
            m = re.match(r'(\S+)\s+dev\s+(\S+)', line)
            if m:
                routing['connected'].append({'subnet': m.group(1), 'dev': m.group(2)})


def parse_ip_route_v6(text, config):
    routing = config.setdefault('routing', {})
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith('default'):
            m = re.search(r'via\s+(\S+)\s+dev\s+(\S+)', line)
            if m and not routing.get('default_gateway_v6'):
                routing['default_gateway_v6'] = {'ip': m.group(1), 'dev': m.group(2)}


def parse_nstat(text, config):
    """Parse 'nstat -a' output into config['nstat']."""
    counters = {}
    for line in text.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2 and not line.startswith('#'):
            try:
                counters[parts[0]] = int(parts[1])
            except ValueError:
                pass
    config['nstat'] = counters


def parse_sockstat(text, config):
    """Parse 'cat /proc/net/sockstat' into config['sockstat']."""
    ss = {}
    for line in text.strip().splitlines():
        parts = line.split()
        if not parts:
            continue
        category = parts[0].rstrip(':')
        pairs = {}
        i = 1
        while i + 1 < len(parts):
            try:
                pairs[parts[i]] = int(parts[i + 1])
            except ValueError:
                pass
            i += 2
        if pairs:
            ss[category] = pairs
    config['sockstat'] = ss


def parse_proc_bonding(text, config):
    """Parse 'cat /proc/net/bonding/*' output.

    Populates config['proc_bonding'] = {bond_name: {mode, active_slave,
    mii_status, slaves: [{name, mii_status, speed, link_failures}]}}.
    Then merges speed and link_failures into matching interface entries.
    """
    bonds = {}
    current_bond = None
    current_slave = None
    for line in text.splitlines():
        m = re.match(r'^===> interface: /proc/net/bonding/(\S+)', line)
        if m:
            current_bond = {'slaves': []}
            bonds[m.group(1)] = current_bond
            current_slave = None
            continue
        if not current_bond:
            continue
        if line.startswith('Bonding Mode:'):
            current_bond['mode'] = line.split(':', 1)[1].strip()
        elif line.startswith('Currently Active Slave:'):
            current_bond['active_slave'] = line.split(':', 1)[1].strip()
        elif line.startswith('MII Status:') and current_slave is None:
            current_bond['mii_status'] = line.split(':', 1)[1].strip()
        elif line.startswith('Slave Interface:'):
            current_slave = {'name': line.split(':', 1)[1].strip()}
            current_bond['slaves'].append(current_slave)
        elif current_slave is not None:
            if line.startswith('MII Status:'):
                current_slave['mii_status'] = line.split(':', 1)[1].strip()
            elif line.startswith('Speed:'):
                current_slave['speed'] = line.split(':', 1)[1].strip()
            elif line.startswith('Link Failure Count:'):
                try:
                    current_slave['link_failures'] = int(
                        line.split(':', 1)[1].strip())
                except ValueError:
                    pass

    config['proc_bonding'] = bonds

    # Merge into interface entries
    by_name = {i['name']: i for i in config.get('interfaces', [])}
    for bond_name, bond in bonds.items():
        bond_iface = by_name.get(bond_name)
        if bond_iface:
            bond_iface['active_slave'] = bond.get('active_slave', '')
        for slave in bond.get('slaves', []):
            iface = by_name.get(slave['name'])
            if iface:
                if slave.get('speed'):
                    iface['speed'] = slave['speed']
                if slave.get('link_failures', 0) > 0:
                    iface['link_failures'] = slave['link_failures']


def _normalize_ip_cmd(cmd):
    """Normalize ip command strings so variant flags match.

    Strips flags like -d, -o, -r that don't change the fields we parse,
    so 'ip -s -d link' matches the canonical 'ip -s link'.
    """
    parts = cmd.split()
    if not parts or parts[0] != 'ip':
        return cmd
    drop = {'-d', '-o', '-r', '-details', '-oneline', '-resolve'}
    return ' '.join(p for p in parts if p not in drop)


def _dispatch_network_sections(sections, config):
    """Run network parsers against a dict of {command: output} sections.

    Handles both newer (networking.info) and older (sm.info) command
    names, e.g. 'ip -s link' vs 'ip -s link show'.
    """
    # Build a normalized lookup so 'ip -s -d link show' matches 'ip -s link show'
    norm_sections = {}
    for cmd, output in sections.items():
        norm_sections[_normalize_ip_cmd(cmd)] = output

    # ip link — try canonical first, then older variant
    for cmd in ('ip -s link', 'ip -s link show'):
        if cmd in norm_sections:
            parse_ip_link(norm_sections[cmd], config)
            break

    # ip addr — try split v4/v6 first, then combined 'ip addr show'
    if 'ip -4 -s addr' in norm_sections:
        parse_ip_addr_v4(norm_sections['ip -4 -s addr'], config)
    if 'ip -6 -s addr' in norm_sections:
        parse_ip_addr_v6(norm_sections['ip -6 -s addr'], config)
    if not ('ip -4 -s addr' in norm_sections or 'ip -6 -s addr' in norm_sections):
        for cmd in ('ip addr show', 'ip addr'):
            if cmd in norm_sections:
                parse_ip_addr_combined(norm_sections[cmd], config)
                break

    # ip route — try split v4/v6 first, then combined
    for cmd in ('ip -4 route', 'ip route'):
        if cmd in norm_sections:
            parse_ip_route_v4(norm_sections[cmd], config)
            break
    if 'ip -6 route' in norm_sections:
        parse_ip_route_v6(norm_sections['ip -6 route'], config)

    # /proc/net/bonding
    bonding_key = 'cat /proc/net/bonding/*'
    if bonding_key in sections:
        parse_proc_bonding(sections[bonding_key], config)

    # nstat
    if 'nstat -a' in sections:
        parse_nstat(sections['nstat -a'], config)

    # sockstat
    sockstat_key = 'cat /proc/net/sockstat'
    if sockstat_key in sections:
        parse_sockstat(sections[sockstat_key], config)

    # netstat (may appear in sm.info on older releases)
    for cmd in ('netstat -anpo', 'netstat -an'):
        if cmd in sections and not config.get('services'):
            parse_netstat_listeners(sections[cmd], config)
            break

    # /etc/hosts (may appear in sm.info on older releases)
    hosts_key = 'cat /etc/hosts'
    if hosts_key in sections and not config.get('etc_hosts'):
        _parse_etc_hosts_text(sections[hosts_key], config)


def _parse_etc_hosts_text(text, config):
    """Parse /etc/hosts content from a string (e.g. from sm.info section)."""
    entries = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 2:
            entries.append({'ip': parts[0], 'hostnames': parts[1:]})
    config['etc_hosts'] = entries


def _note_source(config, path):
    """Record a source file that contributed data."""
    note_source(config, 'network_source_files', path)


def _load_networking_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if sections:
        _note_source(config, path)
        _dispatch_network_sections(sections, config)


# ---------------------------------------------------------------------------
# interface.info parsers (ethtool)
# ---------------------------------------------------------------------------
def parse_ethtool_base(text, iface_name, config):
    """Parse bare 'ethtool <iface>' output for speed and link state."""
    by_name = {i['name']: i for i in config.get('interfaces', [])}
    iface = by_name.get(iface_name)
    if not iface:
        return
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith('Speed:') and 'Unknown' not in line:
            if not iface.get('speed'):
                iface['speed'] = line.split(':', 1)[1].strip()
        elif line.startswith('Link detected:'):
            iface['link_detected'] = line.split(':', 1)[1].strip()


def parse_ethtool_i(text, iface_name, config):
    by_name = {i['name']: i for i in config.get('interfaces', [])}
    iface = by_name.get(iface_name)
    if not iface:
        return
    fields = {'driver': 'driver', 'version': 'driver_version',
              'firmware-version': 'firmware', 'bus-info': 'bus_info'}
    for line in text.strip().splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            k, v = k.strip(), v.strip()
            if k in fields and v:
                iface[fields[k]] = v


def parse_ethtool_s(text, iface_name, config):
    by_name = {i['name']: i for i in config.get('interfaces', [])}
    iface = by_name.get(iface_name)
    if not iface:
        return
    stats = {}
    for line in text.strip().splitlines():
        m = re.match(r'\s+(\S+):\s+(\d+)', line)
        if m:
            stats[m.group(1)] = int(m.group(2))
    if stats:
        iface['ethtool_stats'] = stats


def _load_interface_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    _note_source(config, path)
    with open(path) as f:
        sections = parse_info_sections(f.read())
    phys_names = {i['name'] for i in config.get('interfaces', [])}
    for cmd, output in sections.items():
        m = re.match(r'ethtool (\S+)$', cmd)
        if m and m.group(1) in phys_names:
            parse_ethtool_base(output, m.group(1), config)
            continue
        m = re.match(r'ethtool -i (\S+)', cmd)
        if m and m.group(1) in phys_names:
            parse_ethtool_i(output, m.group(1), config)
            continue
        m = re.match(r'ethtool -S (\S+)', cmd)
        if m and m.group(1) in phys_names:
            parse_ethtool_s(output, m.group(1), config)


# ---------------------------------------------------------------------------
# platform.conf parser
# ---------------------------------------------------------------------------
def _load_platform_conf(path, config):
    if not os.path.isfile(path):
        config.setdefault('warnings', []).append(f"Missing: {path}")
        return
    _note_source(config, path)
    pconf = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                pconf[k.strip()] = v.strip().strip('"')
    config['platform_conf'] = pconf


# ---------------------------------------------------------------------------
# /etc/hosts parser
# ---------------------------------------------------------------------------
def _load_etc_hosts(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    _note_source(config, path)
    with open(path) as f:
        _parse_etc_hosts_text(f.read(), config)


# ---------------------------------------------------------------------------
# netstat.info parser
# ---------------------------------------------------------------------------
def parse_netstat_listeners(text, config):
    services = []
    conn_states = {}
    for line in text.strip().splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        proto, recv_q, send_q, local, foreign, state = parts[0:6]
        program = parts[6] if len(parts) > 6 else '-'
        if state == 'LISTEN':
            addr, _, port = local.rpartition(':')
            prog_name = program.split('/')[-1] if '/' in program else program
            services.append({
                'proto': proto, 'addr': addr, 'port': int(port),
                'program': prog_name, 'pid_program': program,
            })
        elif state in ('ESTABLISHED', 'TIME_WAIT', 'CLOSE_WAIT'):
            conn_states[state] = conn_states.get(state, 0) + 1
    config['services'] = services
    config['connection_states'] = conn_states


def _load_netstat_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    _note_source(config, path)
    with open(path) as f:
        parse_netstat_listeners(f.read(), config)


# ---------------------------------------------------------------------------
# classify_interfaces
# ---------------------------------------------------------------------------
def _classify_interfaces(config):
    pconf = config.get('platform_conf', {})
    role_keys = {
        'management_interface': 'mgmt',
        'oam_interface': 'oam',
        'cluster_host_interface': 'cluster_host',
    }
    iface_roles = {}
    for key, role in role_keys.items():
        iface_name = pconf.get(key)
        if iface_name:
            iface_roles.setdefault(iface_name, []).append(role)

    networks = {}
    for iface in config.get('interfaces', []):
        name = iface['name']
        roles = iface_roles.get(name, [])
        iface['roles'] = roles
        for role in roles:
            v4_addrs = list(iface.get('ipv4', []))
            v6_addrs = list(iface.get('ipv6', []))
            if role == 'mgmt':
                v4_addrs = [a for a in v4_addrs
                            if not a.startswith('169.254.202.')]
            # Filter out link-local IPv6
            v6_addrs = [a for a in v6_addrs
                        if not a.startswith('fe80:')]
            net = {'interface': name, 'ipv4': v4_addrs, 'ipv6': v6_addrs}
            if role == 'oam':
                gw = config.get('routing', {}).get('default_gateway')
                if gw and gw['dev'] == name:
                    net['gateway'] = gw['ip']
            networks[role] = net
        if 'mgmt' in roles:
            pxe_addrs = [a for a in iface.get('ipv4', []) if a.startswith('169.254.202.')]
            if pxe_addrs:
                networks['pxeboot'] = {'interface': name, 'ipv4': pxe_addrs}

    config['networks'] = networks
    pod_ifaces = config.get('pod_interfaces', [])
    pod_cidrs = config.get('routing', {}).get('pod_cidrs', [])
    config['pod_network'] = {'veth_count': len(pod_ifaces), 'cidrs': pod_cidrs}


# ---------------------------------------------------------------------------
# analyze + cross_check
# ---------------------------------------------------------------------------
def _analyze_warnings(config):
    warnings = config.setdefault('warnings', [])
    anomaly_keys = ['rx_dropped', 'rx_errors', 'tx_errors',
                    'tx_linearize', 'fdir_flush_cnt']
    for iface in config.get('interfaces', []):
        stats = iface.get('ethtool_stats', {})
        for k in anomaly_keys:
            if stats.get(k, 0) > 0:
                warnings.append(f"{iface['name']}: ethtool {k}={stats[k]}")
    # nstat protocol anomalies
    nstat = config.get('nstat', {})
    nstat_anomalies = [
        ('TcpRetransSegs', 'TCP retransmits'),
        ('TcpAttemptFails', 'TCP connection failures'),
        ('TcpEstabResets', 'TCP established resets'),
        ('UdpInErrors', 'UDP input errors'),
        ('UdpRcvbufErrors', 'UDP receive buffer errors'),
        ('IpOutNoRoutes', 'IP no-route drops'),
    ]
    for key, label in nstat_anomalies:
        val = nstat.get(key, 0)
        if val > 0:
            warnings.append(f"nstat: {label} ({key})={val}")


def _cross_check(config):
    checks = []
    pconf = config.get('platform_conf', {})
    by_name = {i['name']: i for i in config.get('interfaces', [])}
    role_keys = {
        'management_interface': 'mgmt',
        'oam_interface': 'oam',
        'cluster_host_interface': 'cluster_host',
    }
    for key, role in role_keys.items():
        iface_name = pconf.get(key)
        if not iface_name:
            continue
        iface = by_name.get(iface_name)
        if not iface:
            checks.append({'check': f'{key} ({iface_name})', 'status': 'FAIL',
                           'detail': 'Interface not found'})
        elif iface['state'] != 'UP':
            checks.append({'check': f'{key} ({iface_name})', 'status': 'WARN',
                           'detail': f"State is {iface['state']}, expected UP"})
        else:
            checks.append({'check': f'{key} ({iface_name})', 'status': 'OK',
                           'detail': f"UP, {len(iface.get('ipv4', []))} IPv4 addrs"})

    all_ips = set()
    for iface in config.get('interfaces', []):
        for addr in iface.get('ipv4', []):
            all_ips.add(addr.split('/')[0])
    hostname = config.get('hostname', '')
    for entry in config.get('etc_hosts', []):
        if any(hostname in h for h in entry['hostnames']):
            ip = entry['ip']
            if ip in all_ips or ip == '127.0.0.1':
                checks.append({
                    'check': f"/etc/hosts {ip} ({', '.join(entry['hostnames'])})",
                    'status': 'OK', 'detail': 'IP found on local interface'})
            else:
                checks.append({
                    'check': f"/etc/hosts {ip} ({', '.join(entry['hostnames'])})",
                    'status': 'INFO', 'detail': 'IP not on local interface (may be floating/peer)'})
    config['cross_check'] = checks


# ---------------------------------------------------------------------------
# network_load_config — top-level loader for network domain
# ---------------------------------------------------------------------------
def _load_sm_info_fallback(path, config):
    """Load network data from sm.info when networking.info is empty.

    Older StarlingX releases collect ip/netstat/hosts data in sm.info
    rather than in dedicated networking.info / netstat.info files.
    """
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if sections:
        _note_source(config, path)
        _dispatch_network_sections(sections, config)


def load_config(host_dir, config):
    """Load all network config from host_dir into config dict."""
    _load_networking_info(
        os.path.join(host_dir, 'var', 'extra', 'networking.info'), config)
    _load_platform_conf(
        os.path.join(host_dir, 'etc', 'platform', 'platform.conf'), config)
    _load_etc_hosts(
        os.path.join(host_dir, 'etc', 'hosts'), config)
    _load_interface_info(
        os.path.join(host_dir, 'var', 'extra', 'interface.info'), config)
    _load_netstat_info(
        os.path.join(host_dir, 'var', 'extra', 'netstat.info'), config)

    # Fallback: if networking.info was empty, try sm.info
    if not config.get('interfaces'):
        _load_sm_info_fallback(
            os.path.join(host_dir, 'var', 'extra', 'sm.info'), config)

    _classify_interfaces(config)
    _analyze_warnings(config)
    _cross_check(config)


# ---------------------------------------------------------------------------
# network_build_summary
# ---------------------------------------------------------------------------
def build_summary(config):
    """Distill raw network config into concise summary dict."""
    s = {}
    pconf = config.get('platform_conf', {})
    s['host'] = {
        'hostname': config.get('hostname', 'unknown'),
        'collected': config.get('collected', ''),
        'personality': pconf.get('nodetype', ''),
        'subfunctions': pconf.get('subfunction', ''),
        'system_type': pconf.get('system_type', ''),
        'system_mode': pconf.get('system_mode', ''),
        'sw_version': pconf.get('sw_version', ''),
    }

    # Determine which interfaces have network roles so lo can be
    # included when it serves as mgmt or cluster_host (simplex).
    pconf = config.get('platform_conf', {})
    role_iface_names = set()
    for key in ('management_interface', 'oam_interface',
                'cluster_host_interface'):
        name = pconf.get(key)
        if name:
            role_iface_names.add(name)

    # Interfaces
    ifaces = []
    down_no_role_count = 0
    for iface in config.get('interfaces', []):
        if iface['name'] == 'lo' and 'lo' not in role_iface_names:
            continue
        entry = {
            'name': iface['name'], 'state': iface['state'],
            'mac': iface.get('mac', ''), 'mtu': iface['mtu'],
            'driver': iface.get('driver', ''),
            'roles': iface.get('roles', []),
            'ipv4': iface.get('ipv4', []),
            'ipv6': [a for a in iface.get('ipv6', [])
                     if not a.startswith('fe80:')],
        }
        if 'altname' in iface:
            entry['altname'] = iface['altname']
        if 'parent' in iface:
            entry['parent'] = iface['parent']
        if 'master' in iface:
            entry['master'] = iface['master']
        if 'bond_mode' in iface:
            entry['bond_mode'] = iface['bond_mode']
        if 'bond_slave_state' in iface:
            entry['bond_slave_state'] = iface['bond_slave_state']
        if 'type' in iface:
            entry['type'] = iface['type']
        if 'speed' in iface:
            entry['speed'] = iface['speed']
        if 'link_failures' in iface:
            entry['link_failures'] = iface['link_failures']
        if 'active_slave' in iface:
            entry['active_slave'] = iface['active_slave']
        if iface['state'] != 'UP' and not iface.get('roles'):
            entry['verbose_only'] = True
            down_no_role_count += 1
        rx, tx = iface.get('rx_bytes', 0), iface.get('tx_bytes', 0)
        if rx or tx:
            entry['traffic'] = {
                'rx': human_bytes(rx), 'tx': human_bytes(tx),
                'rx_errors': iface.get('rx_errors', 0),
                'rx_dropped': iface.get('rx_dropped', 0),
                'tx_errors': iface.get('tx_errors', 0),
                'tx_dropped': iface.get('tx_dropped', 0),
            }
        ifaces.append(entry)
    s['interfaces'] = ifaces
    s['down_no_role_count'] = down_no_role_count

    # Pod interfaces
    pods = config.get('pod_interfaces', [])
    if pods:
        sorted_pods = sorted(
            pods, key=lambda p: p.get('rx_bytes', 0), reverse=True
        )
        s['pod_interfaces'] = [{
            'name': p['name'], 'state': p['state'],
            'rx': human_bytes(p.get('rx_bytes', 0)),
            'tx': human_bytes(p.get('tx_bytes', 0)),
        } for p in sorted_pods]

    s['networks'] = config.get('networks', {})

    # Routing
    routing = config.get('routing', {})
    r = {}
    if routing.get('default_gateway'):
        gw = routing['default_gateway']
        r['default_gateway'] = f"{gw['ip']} dev {gw['dev']}"
    r['connected_subnets'] = [
        f"{x['subnet']} dev {x['dev']}" for x in routing.get('connected', [])]
    bgp = routing.get('bgp_routes', [])
    if bgp:
        nexthops = {}
        for route in bgp:
            nexthops.setdefault(route['via'], []).append(route['subnet'])
        r['bgp'] = {nh: f"{len(subs)} routes" for nh, subs in nexthops.items()}
    s['routing'] = r

    pod = config.get('pod_network', {})
    if pod.get('veth_count'):
        s['pod_network'] = {'veth_count': pod['veth_count'], 'cidrs': pod.get('cidrs', [])}

    # /etc/hosts classification
    hosts = config.get('etc_hosts', [])
    all_local_ips = set()
    for iface in config.get('interfaces', []):
        for addr in iface.get('ipv4', []):
            all_local_ips.add(addr.split('/')[0])
    hostname = config.get('hostname', '')
    floating_names = {'controller', 'pxecontroller', 'oamcontroller',
                      'controller-cluster-host', 'controller-platform-nfs',
                      'registry.local'}
    if hosts:
        host_entries = []
        for e in hosts:
            if e['ip'].startswith('127.'):
                continue
            ip, names = e['ip'], e['hostnames']
            if any(n in floating_names for n in names):
                kind = 'floating'
            elif any(hostname == n or n.startswith(hostname + '-') for n in names):
                kind = 'local'
            elif ip in all_local_ips:
                kind = 'local'
            elif any('controller-' in n for n in names):
                kind = 'peer'
            else:
                kind = 'external'
            host_entries.append({'ip': ip, 'hostnames': names, 'type': kind})
        s['hosts_file'] = host_entries

    # Listeners
    services = config.get('services', [])
    if services:
        by_prog = {}
        for svc in services:
            by_prog.setdefault(svc['program'], set()).add(svc['port'])
        s['listeners'] = {prog: sorted(ports) for prog, ports in sorted(by_prog.items())}

    conn = config.get('connection_states', {})
    if conn:
        s['connections'] = conn
    sockstat = config.get('sockstat', {})
    if sockstat:
        s['sockstat'] = sockstat
    checks = config.get('cross_check', [])
    if checks:
        s['cross_check'] = checks
    warnings = config.get('warnings', [])
    if warnings:
        s['warnings'] = warnings

    s['source_files'] = sorted(set(config.get('network_source_files', [])))

    return s
