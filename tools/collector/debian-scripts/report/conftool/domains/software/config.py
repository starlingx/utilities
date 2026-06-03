########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Software Domain — Config Loader and Summary Builder

Parses usm.info, software.json, and /etc/build.info from a collect
bundle host directory.

Entry points (exported via domains/software/__init__.py):
    load_config(host_dir, config)
    build_summary(config) -> summary dict
"""

import json
import os
import re
import sys
sys.dont_write_bytecode = True

from host_utils import note_source          # noqa: E402
from host_utils import parse_info_sections  # noqa: E402


def _note_source(config, path):
    note_source(config, 'software_source_files', path)


# ---------------------------------------------------------------------------
# /etc/build.info
# ---------------------------------------------------------------------------
def _load_build_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    _note_source(config, path)
    info = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                info[k.strip()] = v.strip().strip('"')
    config['build_info'] = info


# ---------------------------------------------------------------------------
# usm.info — software list, deploy show, software show --packages
# ---------------------------------------------------------------------------
def _parse_software_list(text, config):
    """Parse 'software list' table output."""
    releases = []
    for line in text.strip().splitlines():
        if not line.startswith('|'):
            continue
        parts = [p.strip() for p in line.split('|') if p.strip()]
        if len(parts) >= 3 and parts[0] != 'Release':
            releases.append({
                'release_id': parts[0],
                'reboot_required': parts[1] == 'True',
                'state': parts[2],
            })
    config['software_releases'] = releases


def _parse_deploy_show(text, config):
    """Parse 'software deploy show' output."""
    text = text.strip()
    if 'No deploy in progress' in text:
        config['deploy_status'] = 'none'
    else:
        config['deploy_status'] = 'in_progress'
        config['deploy_details'] = text


def _parse_deploy_host_list(text, config):
    """Parse 'software deploy host-list' output."""
    text = text.strip()
    if 'No deploy in progress' in text:
        return
    hosts = []
    for line in text.splitlines():
        if not line.startswith('|'):
            continue
        parts = [p.strip() for p in line.split('|') if p.strip()]
        if len(parts) >= 2 and parts[0] not in ('Hostname', 'hostname'):
            hosts.append({
                'hostname': parts[0],
                'state': parts[1] if len(parts) > 1 else '',
            })
    if hosts:
        config['deploy_hosts'] = hosts


def _parse_software_show(text, release_id, config):
    """Parse 'software show --packages <release>' table output."""
    info = {'release_id': release_id}
    current_key = None
    for line in text.strip().splitlines():
        if not line.startswith('|'):
            continue
        # Split on | but preserve structure
        cells = line.split('|')
        if len(cells) < 3:
            continue
        key = cells[1].strip()
        val = cells[2].strip() if len(cells) > 2 else ''
        if key and key != 'Property':
            current_key = key
            info[key] = val
        elif not key and current_key and val:
            # Continuation line
            info[current_key] = info[current_key] + '\n' + val
    releases_detail = config.setdefault('software_releases_detail', [])
    releases_detail.append(info)


def _load_usm_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    _note_source(config, path)

    for cmd, output in sections.items():
        if 'software deploy show' in cmd:
            _parse_deploy_show(output, config)
        elif 'software deploy host-list' in cmd:
            _parse_deploy_host_list(output, config)
        elif cmd.strip().endswith('software list') or cmd.split()[-2:] == ['software', 'list']:
            _parse_software_list(output, config)
        elif 'software show --packages' in cmd:
            m = re.search(r'software show --packages\s+(\S+)', cmd)
            if m:
                _parse_software_show(output, m.group(1), config)

    # Second pass for software list (command matching can be tricky)
    if not config.get('software_releases'):
        for cmd, output in sections.items():
            if 'software list' in cmd and 'show' not in cmd and 'deploy' not in cmd:
                _parse_software_list(output, config)
                break


# ---------------------------------------------------------------------------
# software.json
# ---------------------------------------------------------------------------
def _load_software_json(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError):
        return
    _note_source(config, path)
    config['software_json'] = data


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------
def _load_ostree_info(path, config):
    """Parse ostree admin status for active/rollback deployments."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    for cmd, output in sections.items():
        if 'admin status' in cmd and output.strip():
            ostree = {'active': '', 'rollback': ''}
            for line in output.splitlines():
                if line.startswith('* '):
                    # Active deployment
                    parts = line[2:].split()
                    if len(parts) >= 2:
                        ostree['active'] = parts[1][:12]
                elif '(rollback)' in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        ostree['rollback'] = parts[1][:12]
            if ostree['active']:
                config['ostree'] = ostree
                _note_source(config, path)
            break


def load_config(host_dir, config):
    """Load all software config from host_dir into config dict."""
    _load_build_info(
        os.path.join(host_dir, 'etc', 'build.info'), config)
    _load_usm_info(
        os.path.join(host_dir, 'var', 'extra', 'usm.info'), config)
    _load_software_json(
        os.path.join(host_dir, 'var', 'extra', 'software', 'software.json'),
        config)
    _load_ostree_info(
        os.path.join(host_dir, 'var', 'extra', 'ostree.info'), config)


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------
def build_summary(config):
    """Distill raw software config into concise summary dict."""
    s = {}

    # Build info
    build = config.get('build_info', {})
    pconf = config.get('platform_conf', {})
    s['build'] = {
        'sw_version': build.get('SW_VERSION', pconf.get('sw_version', '')),
        'build_type': build.get('BUILD_TYPE', ''),
        'build_id': build.get('BUILD_ID', ''),
        'build_date': build.get('BUILD_DATE', ''),
        'job': build.get('JOB', ''),
        'build_number': build.get('BUILD_NUMBER', ''),
    }

    # Deploy status
    s['deploy_status'] = config.get('deploy_status', 'unknown')
    if 'deploy_hosts' in config:
        s['deploy_hosts'] = config['deploy_hosts']

    # Releases from usm.info
    releases = config.get('software_releases', [])
    if releases:
        s['releases'] = releases

    # Release details (packages, descriptions)
    details = config.get('software_releases_detail', [])
    if details:
        s['release_details'] = []
        for d in details:
            entry = {
                'release_id': d.get('release_id', ''),
                'state': d.get('state', ''),
                'sw_version': d.get('sw_version', ''),
                'reboot_required': d.get('reboot_required', ''),
                'requires': d.get('requires', ''),
                'summary': d.get('summary', ''),
            }
            desc = d.get('description', '')
            if desc:
                entry['fixes'] = [ln.strip() for ln in desc.split('\n')
                                  if ln.strip()]
            pkgs = d.get('packages', '')
            if pkgs:
                entry['packages'] = [ln.strip() for ln in pkgs.split('\n')
                                     if ln.strip()]
            s['release_details'].append(entry)

    # Host running versions from software.json
    sw_json = config.get('software_json', {})
    loads = sw_json.get('current_loads', [])
    if loads:
        s['host_loads'] = loads
    deploy = sw_json.get('deploy', [])
    if deploy:
        s['deploy_records'] = deploy

    # Cross-checks
    checks = []
    deploy_status = config.get('deploy_status', 'unknown')
    if deploy_status == 'none':
        checks.append({'check': 'deploy status', 'status': 'OK',
                       'detail': 'No deploy in progress'})
    elif deploy_status == 'in_progress':
        checks.append({'check': 'deploy status', 'status': 'WARN',
                       'detail': 'Deploy in progress'})

    non_deployed = [r for r in releases if r['state'] != 'deployed']
    if non_deployed:
        for r in non_deployed:
            checks.append({'check': f"release {r['release_id']}",
                           'status': 'WARN',
                           'detail': f"State: {r['state']}"})

    if loads:
        versions = set(h.get('running_release', '') for h in loads)
        if len(versions) > 1:
            checks.append({'check': 'host versions', 'status': 'WARN',
                           'detail': f"Mixed versions: {', '.join(sorted(versions))}"})
        else:
            checks.append({'check': 'host versions', 'status': 'OK',
                           'detail': f"All hosts on {versions.pop()}"})

    # --- OSTree ---
    ostree = config.get('ostree')
    if ostree:
        s['ostree'] = ostree

    s['cross_check'] = checks
    s['warnings'] = []
    s['source_files'] = sorted(set(config.get('software_source_files', [])))

    return s
