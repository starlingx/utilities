########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Platform Domain — Output Writers

JSON and human-readable text output for the platform domain.

Entry points (exported via domains/platform/__init__.py):
    write_json(summary, output_path)
    write_text(summary, lines)
"""

import json
import sys
sys.dont_write_bytecode = True


def write_json(summary, output_path):
    """Write platform summary to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)


def write_text(summary, lines):
    s = summary
    W = 60

    def section(title):
        lines.append('')
        lines.append('=' * W)
        lines.append(f"  {title}")
        lines.append('=' * W)

    def kv(key, val, indent=2):
        lines.append(f"{' ' * indent}{key:<28s} {val}")

    lines.append("Platform Summary")

    # System
    sys_info = s.get('system', {})
    section('System')
    kv('Manufacturer', sys_info.get('manufacturer', ''))
    kv('Product', sys_info.get('product', ''))
    kv('Serial', sys_info.get('serial', ''))
    bios = s.get('bios', {})
    if bios:
        kv('BIOS', f"{bios.get('vendor', '')} {bios.get('version', '')} ({bios.get('date', '')})")

    # CPU
    cpu = s.get('cpu', {})
    if cpu:
        section('CPU')
        kv('Model', cpu.get('model', ''))
        kv('CPUs', cpu.get('cpus', ''))
        kv('Sockets', cpu.get('sockets', ''))
        kv('Cores/socket', cpu.get('cores_per_socket', ''))
        kv('Threads/core', cpu.get('threads_per_core', ''))
        kv('NUMA nodes', cpu.get('numa_nodes', ''))

    # Memory
    mem = s.get('memory', {})
    if mem:
        section('Memory')
        kv('Total', mem.get('total', ''))
        kv('Available', mem.get('available', ''))
        kv('Used', f"{mem.get('used', '')} ({mem.get('used_pct', '')})")
        if mem.get('hugepages_total'):
            kv('Hugepages total', str(mem['hugepages_total']))
            kv('Hugepages free', str(mem['hugepages_free']))
            kv('Hugepage size', mem.get('hugepage_size', ''))
            if mem.get('hugepages_in_use'):
                kv('Hugepages in use', str(mem['hugepages_in_use']))

    # Top processes
    procs = s.get('top_processes', [])
    if procs:
        section('Top Processes (by RSS)')
        for p in procs:
            lines.append(f"    {p['rss']:>8s}  {p['cmd']}")

    # Runtime
    if s.get('uptime') or s.get('load_average') or s.get('kernel'):
        section('Runtime')
        if s.get('uptime'):
            kv('Uptime', s['uptime'])
        if s.get('load_average'):
            kv('Load average', s['load_average'])
        if s.get('kernel'):
            kv('Kernel', s['kernel'])

    # Boot params
    boot = s.get('boot_params', {})
    if boot or s.get('cmdline'):
        section('Boot Parameters')
        if s.get('cmdline'):
            lines.append(f"  {s['cmdline']}")
            lines.append('')
        for k, v in boot.items():
            kv(k, v)

    # PCI
    pci = s.get('pci', {})
    if pci:
        section('PCI Devices')
        for dev, count in pci.get('nics', {}).items():
            kv(dev, f"{count} port(s)")
        if pci.get('sriov_vfs'):
            kv('SR-IOV VFs', str(pci['sriov_vfs']))
        for dev, count in pci.get('accelerators', {}).items():
            kv(dev, f"{count} device(s)")

    # BMC
    bmc = s.get('bmc', {})
    if bmc:
        section('BMC Sensors')
        kv('Total sensors', str(bmc.get('sensor_count', 0)))
        for sensor in bmc.get('critical', []):
            lines.append(f"  \u274c {sensor['name']}: {sensor['value']}")
        for sensor in bmc.get('warning', []):
            lines.append(f"  \u26a0\ufe0f  {sensor['name']}: {sensor['value']}")
        if not bmc.get('critical') and not bmc.get('warning'):
            lines.append("  \u2705 All sensors nominal")

    # SM Service Groups
    sm_services = s.get('sm_services', [])
    if sm_services:
        section('SM Service Groups')
        for sg in sm_services:
            icon = '\u2705' if sg['actual'] == sg['desired'] else '\u274c'
            lines.append(f"  {icon} {sg['name']:<36s} {sg['actual']}")

    # Coredumps
    coredumps = s.get('coredumps', [])
    if coredumps:
        section('Coredumps')
        for dump in coredumps:
            lines.append(f"  \u274c {dump}")
    elif 'coredumps' in s:
        section('Coredumps')
        lines.append("  \u2705 No core dumps")

    # Active Alarms
    active_alarms = s.get('active_alarms', [])
    if active_alarms:
        section('Active Alarms')
        for a in active_alarms:
            lines.append(
                f"  \u26a0\ufe0f  {a['id']:<10s} {a['severity']:<10s}"
                f" {a['reason']}")

    # Cross-checks
    checks = s.get('cross_check', [])
    if checks:
        section('Cross-Check')
        icons = {'OK': '\u2705', 'WARN': '\u26a0\ufe0f ', 'FAIL': '\u274c'}
        for c in checks:
            lines.append(f"  {icons.get(c['status'], '  ')} {c['check']}: {c['detail']}")

    # Source files
    sources = s.get('source_files', [])
    if sources:
        section('Source Files')
        for src in sources:
            lines.append(f"  {src}")
