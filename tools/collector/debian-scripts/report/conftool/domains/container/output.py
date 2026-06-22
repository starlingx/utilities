########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Container Domain — Output Writers

JSON and human-readable text output for the container domain.

Entry points (exported via domains/container/__init__.py):
    write_json(summary, output_path)
    write_text(summary, lines)
"""

import json
import sys
sys.dont_write_bytecode = True

from host_utils import get_verbose_level  # noqa: E402


def write_json(summary, output_path):
    """Write container summary to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)


def write_text(summary, lines):
    """Append container summary sections to lines list."""
    s = summary
    W = 60

    def section(title):
        lines.append('')
        lines.append('=' * W)
        lines.append(f"  {title}")
        lines.append('=' * W)

    def kv(key, val, indent=2):
        lines.append(f"{' ' * indent}{key:<28s} {val}")

    # --- Cluster & Node Health ---
    cluster = s.get('cluster', {})
    lines.append("Container Config Summary")
    section('Cluster & Node Health')
    kv('Nodes', f"{cluster.get('ready_count', 0)}/{cluster.get('node_count', 0)} Ready")
    for n in cluster.get('nodes', []):
        st = n.get('status', '')
        is_ready = st == 'Ready' or st.startswith('Ready,')
        status_icon = '\u2705' if is_ready else '\u274c'
        detail = f"{n.get('version', '')}  {n.get('runtime', '')}"
        lines.append(f"    {status_icon} {n['name']:<24s} {n['status']:<12s} {detail}")
    cpu_mgr = cluster.get('cpu_manager')
    if cpu_mgr:
        lines.append('')
        kv('CPU manager policy', cpu_mgr.get('policy', ''))
        kv('Default cpuset', cpu_mgr.get('default_cpuset', ''))
        kv('Pinned pods', str(cpu_mgr.get('pinned_pods', 0)))
    images = cluster.get('images')
    if images:
        kv('Container images',
           f"{images['total']} total, {images['active']} active,"
           f" {images['size']} disk")
    if cluster.get('kubelet_args'):
        lines.append('')
        for k, v in cluster['kubelet_args'].items():
            if k == 'KUBELET_EXTRA_ARGS':
                lines.append(f"    {k}")
                for arg in v.split():
                    lines.append(f"      {arg}")
            else:
                kv(k, v, indent=4)

    # --- Pod Health ---
    pods = s.get('pods')
    if pods:
        section('Pod Health')
        kv('Total pods', str(pods['total']))
        kv('Total restarts', str(pods['total_restarts']))
        status_str = ', '.join(f"{st}:{n}" for st, n in
                               sorted(pods['by_status'].items()))
        kv('By status', status_str)
        if get_verbose_level() >= 1:
            ns_str = ', '.join(f"{ns}:{n}" for ns, n in
                               sorted(pods['by_namespace'].items()))
            kv('By namespace', ns_str)
        problem = pods.get('problem_pods', [])
        if problem:
            lines.append('')
            lines.append('  Problem pods:')
            for p in problem:
                restarts = p.get('restarts', '0')
                lines.append(
                    f"    \u274c {p['namespace']}/{p['name']}"
                    f"  {p['status']}  restarts:{restarts}")

    # --- Helm Releases ---
    helm = s.get('helm')
    if helm:
        section('Helm Releases')
        kv('Total releases', str(helm['release_count']))
        status_str = ', '.join(f"{st}:{n}" for st, n in
                               sorted(helm['by_status'].items()))
        kv('By status', status_str)
        failed = helm.get('failed_releases', [])
        if failed:
            lines.append('')
            lines.append('  Non-deployed releases:')
            for r in failed:
                lines.append(
                    f"    \u26a0\ufe0f  {r['name']:<28s} {r['status']:<16s} "
                    f"{r.get('chart', '')}")
        if get_verbose_level() >= 2:
            lines.append('')
            for r in helm.get('releases', []):
                icon = '\u2705' if r['status'] == 'deployed' else '\u26a0\ufe0f '
                lines.append(
                    f"    {icon} {r['name']:<28s} {r['status']:<16s} "
                    f"{r.get('chart', '')}")

    # --- Container Runtime ---
    rt = s.get('runtime')
    if rt:
        section('Container Runtime')
        kv('Images', str(rt.get('image_count', 0)))
        kv('Containers', str(rt.get('container_count', 0)))
        for k, v in rt.items():
            if k not in ('image_count', 'container_count', 'cni_plugin_dirs'):
                kv(k, str(v))

    # --- Events ---
    events = s.get('events')
    if events:
        section('Events')
        kv('Total events', str(events['total']))
        kv('Warnings', str(events['warning_count']))
        if events.get('by_reason'):
            lines.append('')
            lines.append('  Warning reasons:')
            for reason, count in events['by_reason'].items():
                lines.append(f"    {reason:<32s} {count}")
        if get_verbose_level() >= 1 and events.get('recent_warnings'):
            lines.append('')
            lines.append('  Recent warnings:')
            for e in events['recent_warnings']:
                ns = e.get('namespace', '')
                prefix = f"{ns}/" if ns else ''
                lines.append(
                    f"    {e.get('last_seen', ''):<8s} {e['reason']:<20s} "
                    f"{prefix}{e['object']}  {e.get('message', '')}")

    # --- Cross-checks ---
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
