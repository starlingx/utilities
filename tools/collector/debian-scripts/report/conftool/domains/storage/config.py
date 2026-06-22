########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Storage Domain — Config Loader and Summary Builder

Parses ceph.info, filesystem.info, disk.info, blockdev.info, and
iscsi.info from a collect bundle host directory.

Entry points (exported via domains/storage/__init__.py):
    load_config(host_dir, config)
    build_summary(config) -> summary dict
"""

import os
import re
import sys
sys.dont_write_bytecode = True

from host_utils import note_source          # noqa: E402
from host_utils import parse_info_sections  # noqa: E402


def _note_source(config, path):
    note_source(config, 'storage_source_files', path)


# ---------------------------------------------------------------------------
# ceph.info parsers
# ---------------------------------------------------------------------------
def _parse_ceph_status(text, config):
    """Parse 'ceph status' output."""
    ceph = config.setdefault('ceph', {})
    lines = text.strip().splitlines()

    # Health
    for line in lines:
        line = line.strip()
        if line.startswith('health:'):
            ceph['health'] = line.split(':', 1)[1].strip()
        elif line.startswith('id:'):
            ceph['fsid'] = line.split(':', 1)[1].strip()

    # Services
    for line in lines:
        line = line.strip()
        if line.startswith('mon:'):
            ceph['mon'] = line.split(':', 1)[1].strip()
        elif line.startswith('mgr:'):
            ceph['mgr'] = line.split(':', 1)[1].strip()
        elif line.startswith('mds:'):
            ceph['mds'] = line.split(':', 1)[1].strip()
        elif line.startswith('osd:'):
            ceph['osd_summary'] = line.split(':', 1)[1].strip()

    # Data
    for line in lines:
        line = line.strip()
        if line.startswith('pools:'):
            m = re.match(r'(\d+) pools, (\d+) pgs', line)
            if m:
                ceph['pools'] = int(m.group(1))
                ceph['pgs'] = int(m.group(2))
        elif line.startswith('objects:'):
            ceph['objects'] = line.split(':', 1)[1].strip()
        elif line.startswith('usage:'):
            ceph['usage'] = line.split(':', 1)[1].strip()
        elif line.startswith('pgs:'):
            ceph['pg_status'] = line.split(':', 1)[1].strip()

    # IO
    for line in lines:
        line = line.strip()
        if line.startswith('client:'):
            ceph['io'] = line.split(':', 1)[1].strip()


def _parse_ceph_osd_tree(text, config):
    """Parse 'ceph osd tree' output."""
    osds = []
    current_host = ''
    for line in text.strip().splitlines():
        if line.startswith('ID') or not line.strip():
            continue
        # Host lines: negative ID, type "host", name is hostname
        host_m = re.search(r'host\s+(\S+)', line)
        if host_m:
            current_host = host_m.group(1)
            continue
        # OSD lines: ID CLASS WEIGHT <spaces> osd.N STATUS REWEIGHT PRI
        osd_m = re.match(
            r'\s*(\d+)\s+(\S+)\s+([\d.]+)\s+(osd\.\d+)'
            r'\s+(\S+)\s+([\d.]+)\s+([\d.]+)', line)
        if osd_m:
            osds.append({
                'id': int(osd_m.group(1)),
                'class': osd_m.group(2),
                'weight': osd_m.group(3),
                'name': osd_m.group(4),
                'status': osd_m.group(5),
                'reweight': osd_m.group(6),
                'host': current_host,
            })
    config.setdefault('ceph', {})['osd_tree'] = osds


def _parse_ceph_osd_dump(text, config):
    """Parse 'ceph osd dump' for pool info and OSD state."""
    pools = []
    osd_states = []
    for line in text.strip().splitlines():
        if line.startswith('pool '):
            m = re.match(
                r"pool (\d+) '([^']+)' (\w+) size (\d+) min_size (\d+).*"
                r"pg_num (\d+)",
                line)
            if m:
                pools.append({
                    'id': int(m.group(1)),
                    'name': m.group(2),
                    'type': m.group(3),
                    'size': int(m.group(4)),
                    'min_size': int(m.group(5)),
                    'pg_num': int(m.group(6)),
                })
                # Extract application
                app_m = re.search(r'application (\S+)', line)
                if app_m:
                    pools[-1]['application'] = app_m.group(1)
        elif line.startswith('osd.'):
            m = re.match(r'(osd\.\d+)\s+(\w+)\s+(\w+)\s+weight\s+(\S+)', line)
            if m:
                osd_states.append({
                    'name': m.group(1),
                    'up': m.group(2),
                    'in': m.group(3),
                    'weight': float(m.group(4)),
                })
    ceph = config.setdefault('ceph', {})
    if pools:
        ceph['pools_detail'] = pools
    if osd_states:
        ceph['osd_states'] = osd_states


def _load_ceph_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    found = False
    for cmd, output in sections.items():
        if 'ceph status' in cmd and output.strip():
            _parse_ceph_status(output, config)
            found = True
        elif 'ceph osd tree' in cmd and output.strip():
            _parse_ceph_osd_tree(output, config)
            found = True
        elif 'ceph osd dump' in cmd and output.strip():
            _parse_ceph_osd_dump(output, config)
            found = True

    if found:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# filesystem.info parsers
# ---------------------------------------------------------------------------
def _parse_df(text, config):
    """Parse 'df -h -H -T --local -t ext2 -t ext3 -t ext4 -t xfs --total'."""
    filesystems = []
    for line in text.strip().splitlines():
        if line.startswith('Filesystem') or line.startswith('total') or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 7:
            filesystems.append({
                'device': parts[0],
                'type': parts[1],
                'size': parts[2],
                'used': parts[3],
                'avail': parts[4],
                'use_pct': parts[5].rstrip('%'),
                'mount': parts[6],
            })
    config['filesystems'] = filesystems


def _parse_df_inodes(text, config):
    """Parse 'df -i' output for inode usage."""
    for line in text.strip().splitlines():
        if line.startswith('Filesystem') or line.startswith('total') or not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 7:
            device = parts[0]
            iuse_pct = parts[5].rstrip('%')
            # Merge into existing filesystem entries
            for fs in config.get('filesystems', []):
                if fs['device'] == device:
                    fs['inode_use_pct'] = iuse_pct
                    break


def _parse_drbd(text, config):
    """Parse 'cat /proc/drbd' output."""
    resources = []
    lines = text.strip().splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r'\s*(\d+):\s+cs:(\S+)\s+ro:(\S+)\s+ds:(\S+)', lines[i])
        if m:
            res = {
                'minor': int(m.group(1)),
                'connection': m.group(2),
                'role': m.group(3),
                'disk_state': m.group(4),
            }
            # Next line has stats
            if i + 1 < len(lines):
                stats_line = lines[i + 1]
                oos_m = re.search(r'oos:(\d+)', stats_line)
                if oos_m:
                    res['out_of_sync_kb'] = int(oos_m.group(1))
            resources.append(res)
        i += 1
    config['drbd'] = resources


def _parse_vgs(text, config):
    """Parse 'vgs --all --options all' output."""
    vgs = []
    lines = text.strip().splitlines()
    if not lines:
        return
    for line in lines[1:]:  # skip header
        parts = line.split()
        if len(parts) < 12:
            continue
        # Fields: Fmt VG_UUID VG Attr ... VSize VFree ...
        # Find VG name (3rd field), VSize and VFree
        vg_name = parts[2]
        # Search for size-like values (e.g. 862.66g, <415.85g)
        size_vals = re.findall(r'(?<!\S)<?[\d.]+[gmtpGMTP](?!\S)', line)
        if len(size_vals) >= 2:
            vgs.append({
                'name': vg_name,
                'size': size_vals[0].lstrip('<'),
                'free': size_vals[1].lstrip('<'),
            })
    config['vgs'] = vgs


def _parse_lvs(text, config):
    """Parse 'lvs --all --options all' output."""
    lvs = []
    lines = text.strip().splitlines()
    if not lines:
        return
    for line in lines[1:]:  # skip header
        # Extract LV name and size from the dense output
        # Pattern: UUID LV_NAME VG/LV_NAME PATH ...
        m = re.search(
            r'\S+-\S+-\S+-\S+-\S+-\S+-\S+\s+(\S+)\s+\S+/\S+\s+(\S+)\s+(\S+)',
            line)
        if m:
            lv_name = m.group(1)
            # Find size (pattern like 20.00g, 60.00g)
            size_m = re.search(r'\s(\d+\.\d+[gmtGMT])\s', line)
            lv = {'name': lv_name}
            if size_m:
                lv['size'] = size_m.group(1)
            # Check attributes for state
            attr_m = re.search(r'(-[wW]i-[aA][oO]----)', line)
            if attr_m:
                lv['attr'] = attr_m.group(1)
            lvs.append(lv)
    config['lvs'] = lvs


def _parse_pvs(text, config):
    """Parse 'pvs --all --options all' output."""
    pvs = []
    lines = text.strip().splitlines()
    if not lines:
        return
    for line in lines[1:]:  # skip header
        # Find PV device path
        pv_m = re.search(r'(/dev/\S+)', line)
        if pv_m:
            pv = {'device': pv_m.group(1)}
            size_vals = re.findall(r'(?<!\S)<?[\d.]+[gmtpGMTP](?!\S)', line)
            if len(size_vals) >= 2:
                pv['size'] = size_vals[0].lstrip('<')
                pv['free'] = size_vals[1].lstrip('<')
            pvs.append(pv)
    config['pvs'] = pvs


def _load_filesystem_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    found = False
    for cmd, output in sections.items():
        if not output.strip():
            continue
        if 'df' in cmd and '-t ext' in cmd and '-i' not in cmd:
            _parse_df(output, config)
            found = True
        elif 'df' in cmd and '-i' in cmd and '-t ext' in cmd:
            _parse_df_inodes(output, config)
            found = True
        elif 'cat /proc/drbd' in cmd:
            _parse_drbd(output, config)
            found = True
        elif 'vgs' in cmd and '--all' in cmd:
            _parse_vgs(output, config)
            found = True
        elif 'lvs' in cmd and '--all' in cmd:
            _parse_lvs(output, config)
            found = True
        elif 'pvs' in cmd and '--all' in cmd:
            _parse_pvs(output, config)
            found = True

    if found:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# disk.info parsers (SMART)
# ---------------------------------------------------------------------------
def _parse_smartctl(text, device, config):
    """Parse 'smartctl -a <device>' output."""
    disk = {'device': device}

    # Check if smartctl could read the device
    if 'Unable to detect device type' in text:
        return

    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith('Model Number:') or line.startswith('Device Model:'):
            disk['model'] = line.split(':', 1)[1].strip()
        elif line.startswith('Serial Number:'):
            disk['serial'] = line.split(':', 1)[1].strip()
        elif line.startswith('Firmware Version:'):
            disk['firmware'] = line.split(':', 1)[1].strip()
        elif line.startswith('Total NVM Capacity:'):
            disk['capacity'] = line.split(':', 1)[1].strip()
        elif line.startswith('SMART overall-health'):
            disk['health'] = line.split(':')[-1].strip()
        elif line.startswith('Temperature:'):
            m = re.search(r'(\d+)\s+Celsius', line)
            if m:
                disk['temperature'] = int(m.group(1))
        elif line.startswith('Available Spare:'):
            disk['available_spare'] = line.split(':', 1)[1].strip()
        elif line.startswith('Available Spare Threshold:'):
            disk['spare_threshold'] = line.split(':', 1)[1].strip()
        elif line.startswith('Percentage Used:'):
            disk['percentage_used'] = line.split(':', 1)[1].strip()
        elif line.startswith('Power On Hours:'):
            m = re.search(r'([\d,]+)', line.split(':', 1)[1])
            if m:
                disk['power_on_hours'] = int(m.group(1).replace(',', ''))
        elif line.startswith('Unsafe Shutdowns:'):
            m = re.search(r'([\d,]+)', line.split(':', 1)[1])
            if m:
                disk['unsafe_shutdowns'] = int(m.group(1).replace(',', ''))
        elif line.startswith('Media and Data Integrity Errors:'):
            m = re.search(r'([\d,]+)', line.split(':', 1)[1])
            if m:
                disk['media_errors'] = int(m.group(1).replace(',', ''))
        elif line.startswith('Error Information Log Entries:'):
            m = re.search(r'([\d,]+)', line.split(':', 1)[1])
            if m:
                disk['error_log_entries'] = int(m.group(1).replace(',', ''))
        elif line.startswith('Warning  Comp. Temp. Threshold:'):
            m = re.search(r'(\d+)\s+Celsius', line)
            if m:
                disk['warn_temp_threshold'] = int(m.group(1))
        elif line.startswith('Critical Comp. Temp. Threshold:'):
            m = re.search(r'(\d+)\s+Celsius', line)
            if m:
                disk['crit_temp_threshold'] = int(m.group(1))

    if disk.get('model') or disk.get('health'):
        config.setdefault('smart_disks', []).append(disk)


def _load_disk_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    found = False
    for cmd, output in sections.items():
        m = re.match(r'smartctl -a (\S+)', cmd)
        if m and output.strip():
            _parse_smartctl(output, m.group(1), config)
            found = True

    if found:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# blockdev.info parsers
# ---------------------------------------------------------------------------
def _parse_lsblk(text, config):
    """Parse 'lsblk' output for block device tree."""
    devices = []
    for line in text.strip().splitlines():
        if line.startswith('NAME') or not line.strip():
            continue
        # Determine indent level from tree characters
        indent = len(line) - len(line.lstrip(' │├└─`|'))
        # Strip tree characters
        clean = re.sub(r'^[`|├└─ ]+', '', line)
        parts = clean.split()
        if len(parts) >= 6:
            dev = {
                'name': parts[0],
                'maj_min': parts[1],
                'size': parts[3],
                'type': parts[5],
                'indent': indent,
            }
            if len(parts) >= 7:
                dev['mount'] = parts[6]
            devices.append(dev)
    config['block_devices'] = devices


def _parse_lsblk_scsi(text, config):
    """Parse 'lsblk --scsi' for disk vendor/model info."""
    scsi_info = {}
    for line in text.strip().splitlines():
        if line.startswith('NAME') or not line.strip():
            continue
        parts = line.split()
        # Format: NAME HCTL TYPE VENDOR MODEL ...
        if len(parts) >= 5:
            name = parts[0]
            vendor = parts[3]
            model = parts[4]
            scsi_info[name] = f"{vendor} {model}".strip()
    config['scsi_info'] = scsi_info


def _load_blockdev_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    found = False
    for cmd, output in sections.items():
        if cmd.strip() == 'lsblk' or cmd.endswith(' lsblk'):
            _parse_lsblk(output, config)
            found = True
        elif 'scsi' in cmd:
            _parse_lsblk_scsi(output, config)
            found = True

    if found:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# iscsi.info parsers
# ---------------------------------------------------------------------------
def _load_iscsi_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    for cmd, output in sections.items():
        if 'targetcli ls' in cmd and output.strip():
            # Check if any targets are configured
            targets = re.findall(r'Targets:\s*(\d+)', output)
            has_targets = any(int(t) > 0 for t in targets)
            config['iscsi'] = {
                'configured': has_targets,
                'raw': output.strip() if has_targets else '',
            }
            _note_source(config, path)
            break


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------
def load_config(host_dir, config):
    """Load all storage config from host_dir into config dict."""
    _load_ceph_info(
        os.path.join(host_dir, 'var', 'extra', 'ceph.info'), config)
    _load_filesystem_info(
        os.path.join(host_dir, 'var', 'extra', 'filesystem.info'), config)
    _load_disk_info(
        os.path.join(host_dir, 'var', 'extra', 'disk.info'), config)
    _load_blockdev_info(
        os.path.join(host_dir, 'var', 'extra', 'blockdev.info'), config)
    _load_iscsi_info(
        os.path.join(host_dir, 'var', 'extra', 'iscsi.info'), config)


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------
def build_summary(config):
    """Distill raw storage config into concise summary dict."""
    s = {}

    # --- Ceph ---
    ceph = config.get('ceph', {})
    if ceph:
        s['ceph'] = {
            'health': ceph.get('health', 'unknown'),
            'fsid': ceph.get('fsid', ''),
            'mon': ceph.get('mon', ''),
            'mgr': ceph.get('mgr', ''),
            'mds': ceph.get('mds', ''),
            'osd_summary': ceph.get('osd_summary', ''),
            'usage': ceph.get('usage', ''),
            'pg_status': ceph.get('pg_status', ''),
            'io': ceph.get('io', ''),
        }
        if 'pools_detail' in ceph:
            s['ceph']['pools'] = ceph['pools_detail']
        if 'osd_tree' in ceph:
            s['ceph']['osd_tree'] = ceph['osd_tree']
        if 'osd_states' in ceph:
            s['ceph']['osd_states'] = ceph['osd_states']

    # --- DRBD ---
    drbd = config.get('drbd', [])
    if drbd:
        s['drbd'] = drbd

    # --- Filesystems ---
    filesystems = config.get('filesystems', [])
    if filesystems:
        s['filesystems'] = filesystems

    # --- LVM ---
    vgs = config.get('vgs', [])
    pvs = config.get('pvs', [])
    lvs = config.get('lvs', [])
    if vgs or pvs or lvs:
        lvm = {}
        if vgs:
            lvm['vgs'] = vgs
        if pvs:
            lvm['pvs'] = pvs
        if lvs:
            lvm['lvs'] = lvs
        s['lvm'] = lvm

    # --- Physical Disks (SMART) ---
    disks = config.get('smart_disks', [])
    if disks:
        s['disks'] = disks

    # --- Block Devices (lsblk) ---
    block_devices = config.get('block_devices', [])
    scsi_info = config.get('scsi_info', {})
    if block_devices:
        # Build disk tree: physical disks with their partitions
        disks = []
        current_disk = None
        for dev in block_devices:
            if dev.get('type') == 'disk' and dev.get('indent', 0) == 0:
                current_disk = {
                    'name': dev['name'],
                    'size': dev.get('size', ''),
                    'model': scsi_info.get(dev['name'], ''),
                    'partitions': [],
                }
                disks.append(current_disk)
            elif current_disk and dev.get('type') == 'part':
                current_disk['partitions'].append({
                    'name': dev['name'],
                    'size': dev.get('size', ''),
                    'mount': dev.get('mount', ''),
                })
        if disks:
            s['block_devices'] = disks

    # --- iSCSI ---
    iscsi = config.get('iscsi')
    if iscsi and iscsi.get('configured'):
        s['iscsi'] = iscsi

    # --- Cross-checks ---
    checks = []

    # Ceph health
    if ceph:
        health = ceph.get('health', '')
        if 'HEALTH_OK' in health:
            checks.append({'check': 'ceph health', 'status': 'OK',
                           'detail': health})
        elif 'HEALTH_WARN' in health:
            checks.append({'check': 'ceph health', 'status': 'WARN',
                           'detail': health})
        elif health:
            checks.append({'check': 'ceph health', 'status': 'FAIL',
                           'detail': health})

        # OSD states
        for osd in ceph.get('osd_states', []):
            if osd['up'] != 'up' or osd['in'] != 'in':
                checks.append({'check': f"ceph {osd['name']}", 'status': 'FAIL',
                               'detail': f"up={osd['up']} in={osd['in']}"})

    # DRBD
    for res in drbd:
        minor = res['minor']
        conn = res['connection']
        ds = res['disk_state']
        oos = res.get('out_of_sync_kb', 0)
        if conn != 'Connected' or 'UpToDate/UpToDate' not in ds:
            checks.append({'check': f"drbd{minor}", 'status': 'FAIL',
                           'detail': f"cs:{conn} ds:{ds} oos:{oos}"})
        elif oos > 0:
            checks.append({'check': f"drbd{minor}", 'status': 'WARN',
                           'detail': f"Connected but oos:{oos}KB"})
        else:
            checks.append({'check': f"drbd{minor}", 'status': 'OK',
                           'detail': f"cs:{conn} ds:{ds}"})

    # Filesystem usage
    for fs in filesystems:
        try:
            pct = int(fs['use_pct'])
        except (ValueError, KeyError):
            continue
        if pct >= 95:
            checks.append({'check': f"fs {fs['mount']}", 'status': 'FAIL',
                           'detail': f"{pct}% used ({fs['used']}/{fs['size']})"})
        elif pct >= 85:
            checks.append({'check': f"fs {fs['mount']}", 'status': 'WARN',
                           'detail': f"{pct}% used ({fs['used']}/{fs['size']})"})
        # Inode check
        try:
            ipct = int(fs.get('inode_use_pct', '0'))
        except ValueError:
            ipct = 0
        if ipct >= 90:
            checks.append({'check': f"inodes {fs['mount']}", 'status': 'WARN',
                           'detail': f"{ipct}% inodes used"})

    # SMART health
    for disk in disks:
        health = disk.get('health', '')
        if health and 'PASSED' not in health:
            checks.append({'check': f"disk {disk['device']}", 'status': 'FAIL',
                           'detail': f"SMART: {health}"})
        elif disk.get('media_errors', 0) > 0:
            checks.append({'check': f"disk {disk['device']}", 'status': 'FAIL',
                           'detail': f"Media errors: {disk['media_errors']}"})
        elif health:
            temp = disk.get('temperature', 0)
            warn_t = disk.get('warn_temp_threshold', 70)
            if temp >= warn_t:
                checks.append({'check': f"disk {disk['device']}", 'status': 'WARN',
                               'detail': f"Temp {temp}C >= threshold {warn_t}C"})
            else:
                checks.append({'check': f"disk {disk['device']}", 'status': 'OK',
                               'detail': f"PASSED, {temp}C, "
                                         f"wear:{disk.get('percentage_used', '?')}"})

    s['cross_check'] = checks

    # Warnings
    warnings = []
    for disk in disks:
        if disk.get('unsafe_shutdowns', 0) > 100:
            warnings.append(f"{disk['device']}: {disk['unsafe_shutdowns']} unsafe shutdowns")
        if disk.get('error_log_entries', 0) > 100:
            warnings.append(f"{disk['device']}: {disk['error_log_entries']} error log entries")
    for fs in filesystems:
        try:
            pct = int(fs['use_pct'])
        except (ValueError, KeyError):
            continue
        if pct >= 85:
            warnings.append(f"{fs['mount']}: {pct}% full")

    s['warnings'] = warnings
    s['source_files'] = sorted(set(config.get('storage_source_files', [])))

    return s
