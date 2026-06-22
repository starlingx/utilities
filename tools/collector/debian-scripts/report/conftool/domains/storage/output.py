########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Storage Domain — Output Writers

JSON and human-readable text output for the storage domain.

Entry points (exported via domains/storage/__init__.py):
    write_json(summary, output_path)
    write_text(summary, lines)
"""

import json
import sys
sys.dont_write_bytecode = True


def write_json(summary, output_path):
    """Write storage summary to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)


def write_text(summary, lines):
    """Append storage summary sections to lines list."""
    s = summary
    W = 60

    def section(title):
        lines.append('')
        lines.append('=' * W)
        lines.append(f"  {title}")
        lines.append('=' * W)

    def kv(key, val, indent=2):
        lines.append(f"{' ' * indent}{key:<28s} {val}")

    lines.append("Storage Config Summary")

    # --- Ceph ---
    ceph = s.get('ceph')
    if ceph:
        section('Ceph Cluster')
        health = ceph.get('health', '')
        icon = '\u2705' if 'OK' in health else '\u26a0\ufe0f ' if 'WARN' in health else '\u274c'
        kv('Health', f"{icon} {health}")
        kv('FSID', ceph.get('fsid', ''))
        kv('MON', ceph.get('mon', ''))
        kv('MGR', ceph.get('mgr', ''))
        if ceph.get('mds'):
            kv('MDS', ceph['mds'])
        kv('OSD', ceph.get('osd_summary', ''))
        kv('Usage', ceph.get('usage', ''))
        kv('PG status', ceph.get('pg_status', ''))
        if ceph.get('io'):
            kv('IO', ceph['io'])

        # OSD tree
        osds = ceph.get('osd_tree', [])
        if osds:
            lines.append('')
            lines.append('  OSD Tree:')
            for osd in osds:
                st = osd.get('status', '')
                icon = '\u2705' if st == 'up' else '\u274c'
                lines.append(
                    f"    {icon} {osd['name']:<16s} {st:<6s} "
                    f"host:{osd.get('host', '')} "
                    f"weight:{osd.get('weight', '')} "
                    f"class:{osd.get('class', '')}")

        # Pools
        pools = ceph.get('pools', [])
        if pools:
            lines.append('')
            lines.append('  Pools:')
            for p in pools:
                lines.append(
                    f"    {p['name']:<28s} {p['type']} "
                    f"size:{p['size']} min:{p['min_size']} "
                    f"pgs:{p['pg_num']} "
                    f"app:{p.get('application', '')}")

    # --- DRBD ---
    drbd = s.get('drbd', [])
    if drbd:
        section('DRBD')
        for res in drbd:
            conn = res['connection']
            ds = res['disk_state']
            oos = res.get('out_of_sync_kb', 0)
            ok = conn == 'Connected' and 'UpToDate/UpToDate' in ds
            icon = '\u2705' if ok else '\u274c'
            detail = f"cs:{conn} ds:{ds}"
            if oos > 0:
                detail += f" oos:{oos}KB"
            lines.append(f"  {icon} drbd{res['minor']:<4d} {detail}")

    # --- Filesystems ---
    filesystems = s.get('filesystems', [])
    if filesystems:
        section('Filesystems')
        for fs in filesystems:
            try:
                pct = int(fs['use_pct'])
            except (ValueError, KeyError):
                pct = 0
            icon = '\u274c' if pct >= 95 else '\u26a0\ufe0f ' if pct >= 85 else '  '
            ipct = fs.get('inode_use_pct', '')
            inode_str = f" inodes:{ipct}%" if ipct else ''
            lines.append(
                f"  {icon} {fs['mount']:<36s} {fs['use_pct']:>3s}% "
                f"({fs['used']}/{fs['size']}){inode_str}")

    # --- LVM ---
    lvm = s.get('lvm')
    if lvm:
        section('LVM')
        for vg in lvm.get('vgs', []):
            kv(f"VG {vg['name']}", f"size:{vg['size']} free:{vg['free']}")
        for pv in lvm.get('pvs', []):
            kv(f"PV {pv['device']}", f"size:{pv.get('size', '')} free:{pv.get('free', '')}")

    # --- Physical Disks ---
    block_devs = s.get('block_devices', [])
    if block_devs:
        section('Disks')
        for d in block_devs:
            model = f"  {d['model']}" if d.get('model') else ''
            lines.append(
                f"  {d['name']:<8s} {d.get('size', ''):>8s}{model}")
            for p in d.get('partitions', []):
                mount = f"  {p['mount']}" if p.get('mount') else ''
                lines.append(
                    f"    {p['name']:<10s} {p.get('size', ''):>8s}{mount}")

    # --- Physical Disks (SMART) ---
    disks = s.get('disks', [])
    if disks:
        section('Physical Disks (SMART)')
        for d in disks:
            health = d.get('health', '')
            icon = '\u2705' if 'PASSED' in health else '\u274c'
            lines.append(f"  {icon} {d['device']}")
            kv('Model', d.get('model', ''), indent=4)
            kv('Health', health, indent=4)
            if d.get('capacity'):
                kv('Capacity', d['capacity'], indent=4)
            if d.get('temperature') is not None:
                kv('Temperature', f"{d['temperature']}C", indent=4)
            if d.get('available_spare'):
                kv('Available Spare', d['available_spare'], indent=4)
            if d.get('percentage_used'):
                kv('Percentage Used', d['percentage_used'], indent=4)
            if d.get('power_on_hours') is not None:
                kv('Power On Hours', str(d['power_on_hours']), indent=4)
            if d.get('unsafe_shutdowns') is not None:
                kv('Unsafe Shutdowns', str(d['unsafe_shutdowns']), indent=4)
            if d.get('media_errors') is not None:
                kv('Media Errors', str(d['media_errors']), indent=4)
            lines.append('')

    # --- Cross-checks ---
    checks = s.get('cross_check', [])
    if checks:
        section('Cross-Check')
        icons = {'OK': '\u2705', 'WARN': '\u26a0\ufe0f ', 'FAIL': '\u274c', 'INFO': '\u2139\ufe0f '}
        for c in checks:
            lines.append(
                f"  {icons.get(c['status'], '  ')} {c['check']}: {c['detail']}")

    # --- Warnings ---
    warnings = s.get('warnings', [])
    if warnings:
        section('Warnings')
        for w in warnings:
            lines.append(f"  \u26a0\ufe0f  {w}")

    # --- Source Files ---
    sources = s.get('source_files', [])
    if sources:
        section('Source Files')
        for src in sources:
            lines.append(f"  {src}")
