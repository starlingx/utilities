########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Software Domain — Output Writers

JSON and human-readable text output for the software domain.

Entry points (exported via domains/software/__init__.py):
    write_json(summary, output_path)
    write_text(summary, lines)
"""

import json
import sys
sys.dont_write_bytecode = True


def write_json(summary, output_path):
    """Write software summary to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)


def write_text(summary, lines):
    """Append software summary sections to lines list."""
    s = summary
    W = 60

    def section(title):
        lines.append('')
        lines.append('=' * W)
        lines.append(f"  {title}")
        lines.append('=' * W)

    def kv(key, val, indent=2):
        lines.append(f"{' ' * indent}{key:<28s} {val}")

    # Build info
    lines.append("Software Config Summary")
    build = s.get('build', {})
    section('Build')
    kv('SW version', build.get('sw_version', ''))
    kv('Build type', build.get('build_type', ''))
    kv('Build ID', build.get('build_id', ''))
    kv('Build date', build.get('build_date', ''))
    if build.get('job'):
        kv('Job', build['job'])
    if build.get('build_number'):
        kv('Build number', build['build_number'])

    # Host loads
    loads = s.get('host_loads', [])
    if loads:
        section('Host Running Versions')
        for h in loads:
            kv(h.get('hostname', ''), h.get('running_release', ''))

    # Deploy status
    section('Deploy Status')
    status = s.get('deploy_status', 'unknown')
    icon = '\u2705' if status == 'none' else '\u26a0\ufe0f '
    kv('Status', f"{icon} {status}")
    for h in s.get('deploy_hosts', []):
        kv(h['hostname'], h.get('state', ''))

    # Releases
    releases = s.get('releases', [])
    if releases:
        section('Installed Releases')
        for r in releases:
            icon = '\u2705' if r['state'] == 'deployed' else '\u26a0\ufe0f '
            rr = ' (reboot)' if r.get('reboot_required') else ''
            lines.append(f"  {icon} {r['release_id']:<24s} {r['state']}{rr}")

    # Release details
    details = s.get('release_details', [])
    if details:
        section('Release Details')
        for d in details:
            lines.append(f"  {d['release_id']}")
            if d.get('summary'):
                lines.append(f"    {d['summary']}")
            if d.get('requires'):
                lines.append(f"    requires: {d['requires']}")
            fixes = d.get('fixes', [])
            if fixes:
                for fix in fixes:
                    lines.append(f"    - {fix}")
            lines.append('')

    # OSTree
    ostree = s.get('ostree')
    if ostree:
        section('OSTree')
        kv('Active commit', ostree.get('active', ''))
        if ostree.get('rollback'):
            kv('Rollback commit', ostree['rollback'])
        else:
            kv('Rollback', 'not available')

    # Cross-checks
    checks = s.get('cross_check', [])
    if checks:
        section('Cross-Check')
        icons = {
            'OK': '\u2705', 'WARN': '\u26a0\ufe0f ',
            'FAIL': '\u274c', 'INFO': '\u2139\ufe0f ',
        }
        for c in checks:
            lines.append(
                f"  {icons.get(c['status'], '  ')} {c['check']}: {c['detail']}")

    # Packages
    details = s.get('release_details', [])
    has_packages = any(d.get('packages') for d in details)
    if has_packages:
        section('Packages')
        for d in details:
            pkgs = d.get('packages', [])
            if pkgs:
                lines.append(f"  {d['release_id']}")
                for pkg in pkgs:
                    lines.append(f"    {pkg}")
                lines.append('')

    # Source files last
    sources = s.get('source_files', [])
    if sources:
        section('Source Files')
        for src in sources:
            lines.append(f"  {src}")
