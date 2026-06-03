########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Platform Domain — Config Loader and Summary Builder

Parses host.info, memory.info, process.info, and bmc.info from a
collect bundle host directory.

Entry points (exported via domains/platform/__init__.py):
    load_config(host_dir, config)
    build_summary(config) -> summary dict
"""

import os
import re
import sys
sys.dont_write_bytecode = True

from host_utils import human_bytes          # noqa: E402
from host_utils import note_source          # noqa: E402
from host_utils import parse_info_sections  # noqa: E402


def _note_source(config, path):
    note_source(config, 'platform_source_files', path)


# ---------------------------------------------------------------------------
# dmidecode
# ---------------------------------------------------------------------------
def _parse_dmidecode(text, config):
    system = {}
    bios = {}
    current = None
    for line in text.splitlines():
        if line.startswith('System Information'):
            current = system
        elif line.startswith('BIOS Information'):
            current = bios
        elif line.startswith('Handle ') or (line and not line.startswith('\t')):
            current = None
        elif current is not None and line.startswith('\t'):
            if ':' in line:
                k, v = line.split(':', 1)
                current[k.strip()] = v.strip()
    config['dmi_system'] = system
    config['dmi_bios'] = bios


# ---------------------------------------------------------------------------
# lscpu
# ---------------------------------------------------------------------------
def _parse_lscpu(text, config):
    cpu = {}
    for line in text.strip().splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            cpu[k.strip()] = v.strip()
    config['lscpu'] = cpu


# ---------------------------------------------------------------------------
# uptime
# ---------------------------------------------------------------------------
def _parse_uptime(text, config):
    line = text.strip()
    config['uptime_raw'] = line
    m = re.search(r'up\s+(.+?),\s+\d+\s+user', line)
    if m:
        config['uptime'] = m.group(1).strip()
    m = re.search(r'load average:\s+(.+)', line)
    if m:
        config['load_average'] = m.group(1).strip()


# ---------------------------------------------------------------------------
# kernel/boot
# --------------------------------------------------------------------------
def _parse_proc_version(text, config):
    config['kernel_version'] = text.strip().split('\n')[0]


def _parse_proc_cmdline(text, config):
    config['boot_cmdline'] = text.strip()


# ---------------------------------------------------------------------------
# lspci
# ---------------------------------------------------------------------------
def _parse_lspci(text, config):
    devices = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        m = re.match(
            r'(\S+)\s+(.+?)\s+\[([0-9a-f]{4})\]:\s+(.+?)\s+\[([0-9a-f:]+)\]'
            r'(?:\s+\(rev\s+(\S+)\))?', line)
        if m:
            devices.append({
                'slot': m.group(1),
                'class': m.group(2),
                'class_id': m.group(3),
                'device': m.group(4),
                'vendor_device_id': m.group(5),
                'rev': m.group(6) or '',
            })
    config['pci_devices'] = devices


# ---------------------------------------------------------------------------
# meminfo
# ---------------------------------------------------------------------------
def _parse_meminfo(text, config):
    mem = {}
    for line in text.strip().splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            v = v.strip()
            m = re.match(r'(\d+)', v)
            if m:
                mem[k.strip()] = int(m.group(1))
    config['meminfo'] = mem


# ---------------------------------------------------------------------------
# top RSS processes
# ---------------------------------------------------------------------------
def _parse_top_rss(text, config):
    """Parse ps sorted by RSS output."""
    procs = []
    for line in text.strip().splitlines():
        if line.startswith('PPID') or line.startswith(' PPID'):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            rss = int(parts[3])
        except ValueError:
            continue
        procs.append({
            'pid': parts[1],
            'rss_kb': rss,
            'cmd': parts[5].split()[0].split('/')[-1],
        })
    config['top_rss_procs'] = procs[:20]


# ---------------------------------------------------------------------------
# hugepages from /proc/*/numa_maps
# ---------------------------------------------------------------------------
def _parse_hugepages_numa(text, config):
    """Parse grep huge /proc/*/numa_maps — count total huge pages in use."""
    total_huge = 0
    for line in text.strip().splitlines():
        m = re.search(r'huge.*?N(\d+)=(\d+)', line)
        if m:
            total_huge += int(m.group(2))
    if total_huge:
        config['hugepages_in_use'] = total_huge


# ---------------------------------------------------------------------------
# bmc.info
# ---------------------------------------------------------------------------
def _parse_sensor_list(text, config):
    sensors = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 4:
            sensors.append({
                'name': parts[0],
                'value': parts[1],
                'unit': parts[2],
                'status': parts[3],
            })
    config['bmc_sensors'] = sensors


def _load_bmc_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return
    for cmd, output in sections.items():
        if 'sensor list' in cmd and output.strip():
            _parse_sensor_list(output, config)
            _note_source(config, path)
            break


# ---------------------------------------------------------------------------
# host.info loader
# ---------------------------------------------------------------------------
def _load_host_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    found = False
    if 'dmidecode' in sections and sections['dmidecode'].strip():
        _parse_dmidecode(sections['dmidecode'], config)
        found = True
    if 'lscpu' in sections and sections['lscpu'].strip():
        _parse_lscpu(sections['lscpu'], config)
        found = True
    if 'uptime' in sections and sections['uptime'].strip():
        _parse_uptime(sections['uptime'], config)
        found = True
    for cmd in ('cat /proc/version', 'cat /proc/version_signature'):
        if cmd in sections and sections[cmd].strip():
            _parse_proc_version(sections[cmd], config)
            found = True
            break
    if 'cat /proc/cmdline' in sections and sections['cat /proc/cmdline'].strip():
        _parse_proc_cmdline(sections['cat /proc/cmdline'], config)
        found = True
    if 'lspci -nn' in sections and sections['lspci -nn'].strip():
        _parse_lspci(sections['lspci -nn'], config)
        found = True
    if found:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# memory.info loader
# ---------------------------------------------------------------------------
def _load_memory_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    found = False
    if 'cat /proc/meminfo' in sections:
        _parse_meminfo(sections['cat /proc/meminfo'], config)
        found = True

    for cmd, output in sections.items():
        if 'ps -e -o' in cmd and 'rss' in cmd and output.strip():
            _parse_top_rss(output, config)
            found = True
            break

    for cmd, output in sections.items():
        if 'huge' in cmd and 'numa_maps' in cmd and output.strip():
            _parse_hugepages_numa(output, config)
            found = True
            break

    if found:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# process.info loader (top RSS from here if not in memory.info)
# ---------------------------------------------------------------------------
def _load_process_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    if 'top_rss_procs' in config:
        return  # already got from memory.info
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    for cmd, output in sections.items():
        if 'ps -e' in cmd and 'rss' in cmd and output.strip():
            _parse_top_rss(output, config)
            _note_source(config, path)
            break


# ---------------------------------------------------------------------------
# sm.info fallback
# ---------------------------------------------------------------------------
def _load_sm_info_fallback(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    found = False
    if 'uname -a' in sections and sections['uname -a'].strip():
        config['kernel_version'] = sections['uname -a'].strip().split('\n')[0]
        found = True
    if 'cat /proc/cpuinfo' in sections and sections['cat /proc/cpuinfo'].strip():
        _parse_cpuinfo_fallback(sections['cat /proc/cpuinfo'], config)
        found = True
    if 'cat /proc/meminfo' in sections and sections['cat /proc/meminfo'].strip():
        _parse_meminfo(sections['cat /proc/meminfo'], config)
        found = True
    if found:
        _note_source(config, path)


def _parse_cpuinfo_fallback(text, config):
    model = ''
    processors = 0
    for line in text.splitlines():
        if line.startswith('model name') and not model:
            model = line.split(':', 1)[1].strip()
        if line.startswith('processor'):
            processors += 1
    if model or processors:
        config.setdefault('lscpu', {})
        if model:
            config['lscpu']['Model name'] = model
        if processors:
            config['lscpu']['CPU(s)'] = str(processors)


def _load_sm_services(path, config):
    """Parse sm-dump from sm.info for service group states."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    for cmd, output in sections.items():
        if 'sm-dump' in cmd and output.strip():
            service_groups = []
            for line in output.strip().splitlines():
                if line.startswith('-') or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    service_groups.append({
                        'name': parts[0],
                        'desired': parts[1],
                        'actual': parts[2],
                    })
            if service_groups:
                config['sm_service_groups'] = service_groups
                _note_source(config, path)
            break


def _load_coredump_info(path, config):
    """Parse coredump.info for crash dump presence."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        content = f.read().strip()

    if 'No core dumps' in content or not content:
        config['coredumps'] = []
    else:
        # Parse core dump file listings
        dumps = []
        for line in content.splitlines():
            if '/var/lib/systemd/coredump/' in line or 'core.' in line:
                dumps.append(line.strip())
        config['coredumps'] = dumps
        if dumps:
            _note_source(config, path)


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------
def _load_alarms_info(path, config):
    """Parse fm alarm-list from alarms.info for active alarms."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    # Only parse fm alarm-list, not fm event-list
    for cmd, content in sections.items():
        if cmd.strip() == 'fm alarm-list':
            alarms = []
            for line in content.splitlines():
                if line.startswith('+') or not line.strip():
                    continue
                if 'Alarm ID' in line or 'Reason Text' in line:
                    continue
                parts = [p.strip() for p in line.split('|')
                         if p.strip()]
                if len(parts) >= 4:
                    alarms.append({
                        'id': parts[0],
                        'reason': parts[1][:80],
                        'entity': parts[2],
                        'severity': parts[3],
                    })
            if alarms:
                config['active_alarms'] = alarms
                _note_source(config, path)
            break


def load_config(host_dir, config):
    _load_host_info(
        os.path.join(host_dir, 'var', 'extra', 'host.info'), config)
    _load_memory_info(
        os.path.join(host_dir, 'var', 'extra', 'memory.info'), config)
    _load_process_info(
        os.path.join(host_dir, 'var', 'extra', 'process.info'), config)
    _load_bmc_info(
        os.path.join(host_dir, 'var', 'extra', 'bmc.info'), config)
    _load_sm_services(
        os.path.join(host_dir, 'var', 'extra', 'sm.info'), config)
    _load_coredump_info(
        os.path.join(host_dir, 'var', 'extra', 'coredump.info'), config)
    _load_alarms_info(
        os.path.join(host_dir, 'var', 'extra', 'alarms.info'), config)

    if not config.get('lscpu') and not config.get('dmi_system'):
        _load_sm_info_fallback(
            os.path.join(host_dir, 'var', 'extra', 'sm.info'), config)


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------
def build_summary(config):
    s = {}

    # System
    dmi = config.get('dmi_system', {})
    s['system'] = {
        'manufacturer': dmi.get('Manufacturer', ''),
        'product': dmi.get('Product Name', ''),
        'serial': dmi.get('Serial Number', ''),
    }

    bios = config.get('dmi_bios', {})
    if bios:
        s['bios'] = {
            'vendor': bios.get('Vendor', ''),
            'version': bios.get('Version', ''),
            'date': bios.get('Release Date', ''),
        }

    # CPU
    lscpu = config.get('lscpu', {})
    if lscpu:
        s['cpu'] = {
            'model': lscpu.get('Model name', ''),
            'cpus': lscpu.get('CPU(s)', ''),
            'cores_per_socket': lscpu.get('Core(s) per socket', ''),
            'sockets': lscpu.get('Socket(s)', ''),
            'threads_per_core': lscpu.get('Thread(s) per core', ''),
            'numa_nodes': lscpu.get('NUMA node(s)', ''),
        }

    # Memory
    mem = config.get('meminfo', {})
    if mem:
        total = mem.get('MemTotal', 0)
        avail = mem.get('MemAvailable', 0)
        used = total - avail if total and avail else 0
        s['memory'] = {
            'total': human_bytes(total * 1024),
            'available': human_bytes(avail * 1024),
            'used': human_bytes(used * 1024),
            'used_pct': f"{100 * used // total}%" if total else '',
            'hugepages_total': mem.get('HugePages_Total', 0),
            'hugepages_free': mem.get('HugePages_Free', 0),
            'hugepage_size': human_bytes(mem.get('Hugepagesize', 0) * 1024),
        }
        if 'hugepages_in_use' in config:
            s['memory']['hugepages_in_use'] = config['hugepages_in_use']

    # Top processes
    procs = config.get('top_rss_procs', [])
    if procs:
        s['top_processes'] = [
            {'cmd': p['cmd'], 'rss': human_bytes(p['rss_kb'] * 1024)}
            for p in procs
        ]

    # Uptime / load
    if 'uptime' in config:
        s['uptime'] = config['uptime']
    if 'load_average' in config:
        s['load_average'] = config['load_average']

    # Kernel
    if 'kernel_version' in config:
        s['kernel'] = config['kernel_version']

    # Boot params
    cmdline = config.get('boot_cmdline', '')
    if cmdline:
        s['cmdline'] = cmdline
        boot = {}
        for param in ('iommu', 'intel_iommu', 'nohz_full', 'isolcpus',
                      'hugepagesz', 'hugepages', 'default_hugepagesz',
                      'console', 'selinux'):
            m = re.search(rf'\b{param}=(\S+)', cmdline)
            if m:
                boot[param] = m.group(1)
        if boot:
            s['boot_params'] = boot

    # PCI
    pci = config.get('pci_devices', [])
    if pci:
        nics = [d for d in pci if d['class_id'] == '0200'
                and 'Virtual Function' not in d['device']]
        vfs = [d for d in pci if d['class_id'] == '0200'
               and 'Virtual Function' in d['device']]
        accels = [d for d in pci if d['class_id'] == '1200']
        pci_summary = {}
        if nics:
            by_device = {}
            for n in nics:
                by_device.setdefault(n['device'], []).append(n['slot'])
            pci_summary['nics'] = {dev: len(slots)
                                   for dev, slots in by_device.items()}
        if vfs:
            pci_summary['sriov_vfs'] = len(vfs)
        if accels:
            by_device = {}
            for a in accels:
                by_device.setdefault(a['device'], []).append(a['slot'])
            pci_summary['accelerators'] = {dev: len(slots)
                                           for dev, slots in by_device.items()}
        s['pci'] = pci_summary

    # BMC
    sensors = config.get('bmc_sensors', [])
    if sensors:
        critical = [x for x in sensors if x['status'] in ('cr', 'nr')]
        warning = [x for x in sensors if x['status'] == 'nc']
        s['bmc'] = {
            'sensor_count': len(sensors),
            'critical': [{'name': x['name'], 'value': x['value']}
                         for x in critical],
            'warning': [{'name': x['name'], 'value': x['value']}
                        for x in warning],
        }

    # Cross-checks
    checks = []
    if dmi.get('Product Name'):
        checks.append({'check': 'system identity', 'status': 'OK',
                       'detail': f"{dmi['Manufacturer']} {dmi['Product Name']}"})
    if mem:
        total = max(mem.get('MemTotal', 1), 1)
        used = mem.get('MemTotal', 0) - mem.get('MemAvailable', 0)
        used_pct = 100 * used // total
        if used_pct > 90:
            checks.append({'check': 'memory', 'status': 'WARN',
                           'detail': f"{used_pct}% used"})
        else:
            checks.append({'check': 'memory', 'status': 'OK',
                           'detail': f"{used_pct}% used"})
    if sensors:
        if critical:
            checks.append({'check': 'BMC sensors', 'status': 'FAIL',
                           'detail': f"{len(critical)} critical"})
        elif warning:
            checks.append({'check': 'BMC sensors', 'status': 'WARN',
                           'detail': f"{len(warning)} warning"})
        else:
            checks.append({'check': 'BMC sensors', 'status': 'OK',
                           'detail': 'All nominal'})

    s['cross_check'] = checks

    # --- SM Service Groups ---
    sm_groups = config.get('sm_service_groups', [])
    if sm_groups:
        s['sm_services'] = sm_groups
        # Check for non-active services
        for sg in sm_groups:
            if sg['actual'] != sg['desired']:
                checks.append({'check': f"SM {sg['name']}",
                               'status': 'FAIL',
                               'detail': f"desired:{sg['desired']} "
                                         f"actual:{sg['actual']}"})

    # --- Coredumps ---
    coredumps = config.get('coredumps', [])
    if coredumps:
        s['coredumps'] = coredumps
        checks.append({'check': 'coredumps', 'status': 'FAIL',
                       'detail': f"{len(coredumps)} crash dump(s) found"})
    else:
        s['coredumps'] = []

    # --- Active Alarms ---
    active_alarms = config.get('active_alarms', [])
    if active_alarms:
        s['active_alarms'] = active_alarms
        checks.append({'check': 'active alarms', 'status': 'WARN',
                       'detail': f"{len(active_alarms)} alarm(s) active"})

    s['warnings'] = []
    s['source_files'] = sorted(set(config.get('platform_source_files', [])))

    return s
