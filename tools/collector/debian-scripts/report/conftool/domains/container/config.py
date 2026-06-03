########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Container Domain — Config Loader and Summary Builder

Parses containerization_kube.info, containerization_helm.info,
containerization_host.info, containerization_events.info, and
etc/default/kubelet from a collect bundle host directory.

Entry points (exported via domains/container/__init__.py):
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _note_source(config, path):
    """Record a source file that contributed data."""
    note_source(config, 'container_source_files', path)


def _find_section(sections, *patterns):
    """Find a section whose command contains any of the given substrings.

    Handles 'eval kubectl ...', 'sudo -u root KUBECONFIG=... helm ...',
    and direct commands. Skips empty sections. Returns the first non-empty
    match's output text, or None.
    """
    for pattern in patterns:
        for cmd, output in sections.items():
            if pattern in cmd and output.strip():
                return output
    return None


# ---------------------------------------------------------------------------
# containerization_kube.info parsers
# ---------------------------------------------------------------------------
def _parse_get_nodes(text, config):
    """Parse 'kubectl get nodes -o wide' output.

    Uses header column positions for alignment since fields like
    OS-IMAGE can contain spaces.
    """
    lines = text.strip().splitlines()
    if not lines:
        return
    header = lines[0]
    if not header.startswith('NAME'):
        return

    # Find column start positions from header
    cols = ['NAME', 'STATUS', 'ROLES', 'AGE', 'VERSION',
            'INTERNAL-IP', 'EXTERNAL-IP', 'OS-IMAGE',
            'KERNEL-VERSION', 'CONTAINER-RUNTIME']
    positions = []
    for col in cols:
        idx = header.find(col)
        positions.append(idx if idx >= 0 else None)

    def extract(line, col_idx):
        start = positions[col_idx]
        if start is None:
            return ''
        end = None
        for i in range(col_idx + 1, len(positions)):
            if positions[i] is not None:
                end = positions[i]
                break
        return line[start:end].strip() if end else line[start:].strip()

    nodes = []
    for line in lines[1:]:
        if not line.strip():
            continue
        node = {
            'name': extract(line, 0),
            'status': extract(line, 1),
            'roles': extract(line, 2),
            'age': extract(line, 3),
            'version': extract(line, 4),
        }
        if node['roles'] == '<none>':
            node['roles'] = ''
        ip = extract(line, 5)
        if ip and ip != '<none>':
            node['internal_ip'] = ip
        kernel = extract(line, 8)
        if kernel:
            node['kernel'] = kernel
        runtime = extract(line, 9)
        if runtime:
            node['runtime'] = runtime
        nodes.append(node)
    config['kube_nodes'] = nodes


def _parse_get_pods(text, config):
    """Parse 'kubectl get pods --all-namespaces -o wide'."""
    pods = []
    for line in text.strip().splitlines():
        if line.startswith('NAMESPACE') or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        pod = {
            'namespace': parts[0],
            'name': parts[1],
            'ready': parts[2],
            'status': parts[3],
            'restarts': parts[4],
        }
        if len(parts) > 5:
            pod['age'] = parts[5]
        if len(parts) > 6:
            pod['ip'] = parts[6]
        if len(parts) > 7:
            pod['node'] = parts[7]
        pods.append(pod)
    config['kube_pods'] = pods


def _parse_node_conditions(text, config):
    """Parse node conditions from kubectl describe nodes output."""
    conditions = []
    in_conditions = False
    current_node = ''
    for line in text.splitlines():
        if line.startswith('Name:'):
            current_node = line.split(':', 1)[1].strip()
        elif 'Conditions:' in line:
            in_conditions = True
        elif in_conditions and line.startswith('  ') and '---' not in line:
            parts = line.split()
            if len(parts) >= 2 and parts[0] in (
                    'MemoryPressure', 'DiskPressure',
                    'PIDPressure', 'NetworkUnavailable'):
                status = parts[1]
                if status == 'True':
                    conditions.append({
                        'node': current_node,
                        'condition': parts[0],
                        'status': status,
                    })
        elif in_conditions and not line.startswith(' '):
            in_conditions = False
    if conditions:
        config['node_conditions'] = conditions


def _load_kube_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    text = _find_section(sections, 'kubectl get nodes -o wide')
    if text and text.strip():
        _parse_get_nodes(text, config)

    # Parse node conditions from describe nodes
    text = _find_section(sections, 'kubectl describe nodes')
    if text and text.strip():
        _parse_node_conditions(text, config)

    text = _find_section(sections,
                         'kubectl get pods --all-namespaces -o wide',
                         'kubectl get pods -A -o wide',
                         'kubectl get pods --all-namespaces',
                         'kubectl get pods -A')
    if text and text.strip():
        _parse_get_pods(text, config)

    if config.get('kube_nodes') or config.get('kube_pods'):
        _note_source(config, path)


# ---------------------------------------------------------------------------
# containerization_helm.info parsers
# ---------------------------------------------------------------------------
def _parse_helm_list(text, config):
    """Parse helm list output (tab-separated)."""
    releases = []
    for line in text.strip().splitlines():
        if line.startswith('NAME') or not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 7:
            continue
        releases.append({
            'name': parts[0].strip(),
            'namespace': parts[1].strip(),
            'revision': parts[2].strip(),
            'status': parts[4].strip() if len(parts) > 4 else '',
            'chart': parts[5].strip() if len(parts) > 5 else '',
            'app_version': parts[6].strip() if len(parts) > 6 else '',
        })
    if releases:
        config['helm_releases'] = releases


def _load_helm_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    text = _find_section(sections,
                         'helm list --all --all-namespaces',
                         'helm list -a -A',
                         'helm list -A',
                         'helm list --all-namespaces')
    if text and text.strip():
        _parse_helm_list(text, config)

    if 'helm_releases' in config:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# containerization_host.info parsers
# ---------------------------------------------------------------------------
def _parse_cpu_manager_state(text, config):
    """Parse kubelet cpu_manager_state JSON."""
    try:
        data = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return
    entries = data.get('entries', {})
    config['cpu_manager'] = {
        'policy': data.get('policyName', ''),
        'default_cpuset': data.get('defaultCpuSet', ''),
        'pinned_pods': len(entries),
    }


def _parse_crictl_info(text, config):
    """Parse 'crictl info' JSON output."""
    try:
        data = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return
    runtime = {}
    status = data.get('status', {})
    if isinstance(status, dict):
        conditions = status.get('conditions', [])
        for cond in conditions:
            if isinstance(cond, dict):
                runtime[cond.get('type', '')] = cond.get('status', False)
    config['container_runtime'] = runtime


def _load_host_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    found = False

    # CPU manager state (common on all releases that have this file)
    text = _find_section(sections, 'cpu_manager_state')
    if text and text.strip():
        _parse_cpu_manager_state(text, config)
        found = True

    # crictl info (if present)
    text = _find_section(sections, 'crictl info')
    if text and text.strip():
        _parse_crictl_info(text, config)
        found = True

    if found:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# containerization_events.info parsers
# ---------------------------------------------------------------------------
def _parse_kube_events_gotemplate(text, config):
    """Parse go-template events: 'timestamp name\\tKind\\tmessage\\treason\\ttype'."""
    events = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 5:
            continue
        # First field: "2026-01-29T00:30:21Z controller-0-profile"
        first = parts[0].strip()
        space_idx = first.find(' ')
        if space_idx > 0:
            timestamp = first[:space_idx]
            obj_name = first[space_idx + 1:]
        else:
            timestamp = ''
            obj_name = first
        events.append({
            'timestamp': timestamp,
            'object': obj_name,
            'kind': parts[1].strip(),
            'message': parts[2].strip(),
            'reason': parts[3].strip(),
            'type': parts[4].strip(),
        })
    if events:
        config['kube_events'] = events


def _parse_kube_events_table(text, config):
    """Parse standard 'kubectl get events' table output."""
    events = []
    for line in text.strip().splitlines():
        if line.startswith('NAMESPACE') or line.startswith('LAST SEEN') or not line.strip():
            continue
        parts = line.split(None, 5)
        if len(parts) < 5:
            continue
        if re.match(r'\d+[smhd]', parts[0]) or parts[0] in ('<unknown>', '-'):
            event = {
                'last_seen': parts[0],
                'type': parts[1],
                'reason': parts[2],
                'object': parts[3],
                'message': parts[4] if len(parts) > 4 else '',
            }
        else:
            event = {
                'namespace': parts[0],
                'last_seen': parts[1],
                'type': parts[2],
                'reason': parts[3],
                'object': parts[4],
                'message': parts[5] if len(parts) > 5 else '',
            }
        events.append(event)
    if events:
        config['kube_events'] = events


def _load_events_info(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    # Try go-template format first (most common across releases)
    text = _find_section(sections, 'go-template', '-o go-template')
    if text and text.strip():
        _parse_kube_events_gotemplate(text, config)
    else:
        # Fall back to standard table format
        text = _find_section(sections,
                             'kubectl get events')
        if text and text.strip():
            _parse_kube_events_table(text, config)

    if 'kube_events' in config:
        _note_source(config, path)


# ---------------------------------------------------------------------------
# etc/default/kubelet
# ---------------------------------------------------------------------------
def _load_images_info(path, config):
    """Parse containerization_images.info for disk usage."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    with open(path) as f:
        sections = parse_info_sections(f.read())
    if not sections:
        return

    for cmd, output in sections.items():
        if 'docker system df' in cmd and output.strip():
            for line in output.strip().splitlines():
                if line.startswith('Images'):
                    parts = line.split()
                    if len(parts) >= 4:
                        config['container_images'] = {
                            'total': parts[1],
                            'active': parts[2],
                            'size': parts[3],
                        }
                        _note_source(config, path)
            break


def _load_kubelet_config(path, config):
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return
    _note_source(config, path)
    kubelet = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                kubelet[k.strip()] = v.strip().strip('"')
    config['kubelet_config'] = kubelet


# ---------------------------------------------------------------------------
# load_config — top-level loader
# ---------------------------------------------------------------------------
def load_config(host_dir, config):
    """Load all container config from host_dir into config dict."""
    _load_kube_info(
        os.path.join(host_dir, 'var', 'extra', 'containerization_kube.info'),
        config)
    _load_helm_info(
        os.path.join(host_dir, 'var', 'extra', 'containerization_helm.info'),
        config)
    _load_host_info(
        os.path.join(host_dir, 'var', 'extra', 'containerization_host.info'),
        config)
    _load_events_info(
        os.path.join(host_dir, 'var', 'extra', 'containerization_events.info'),
        config)
    _load_images_info(
        os.path.join(host_dir, 'var', 'extra',
                     'containerization_images.info'),
        config)
    _load_kubelet_config(
        os.path.join(host_dir, 'etc', 'default', 'kubelet'),
        config)


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------
def build_summary(config):
    """Distill raw container config into concise summary dict."""
    s = {}

    # --- Cluster & Node Health ---
    nodes = config.get('kube_nodes', [])
    ready = [n for n in nodes if _node_is_ready(n)]
    not_ready = [n for n in nodes if not _node_is_ready(n)]
    cluster = {
        'node_count': len(nodes),
        'ready_count': len(ready),
        'nodes': nodes,
    }
    kubelet = config.get('kubelet_config', {})
    if kubelet:
        cluster['kubelet_args'] = kubelet
    cpu_mgr = config.get('cpu_manager')
    if cpu_mgr:
        cluster['cpu_manager'] = cpu_mgr
    images = config.get('container_images')
    if images:
        cluster['images'] = images
    s['cluster'] = cluster

    # --- Pod Health ---
    pods = config.get('kube_pods', [])
    if pods:
        by_status = {}
        by_ns = {}
        problem_pods = []
        total_restarts = 0
        for p in pods:
            st = p['status']
            by_status[st] = by_status.get(st, 0) + 1
            by_ns[p['namespace']] = by_ns.get(p['namespace'], 0) + 1
            restarts = _parse_restart_count(p.get('restarts', '0'))
            total_restarts += restarts
            if st not in ('Running', 'Succeeded', 'Completed'):
                problem_pods.append(p)
            elif restarts > 5:
                problem_pods.append(p)
        s['pods'] = {
            'total': len(pods),
            'by_status': by_status,
            'by_namespace': by_ns,
            'total_restarts': total_restarts,
            'problem_pods': problem_pods,
        }

    # --- Helm Releases ---
    releases = config.get('helm_releases', [])
    if releases:
        by_status = {}
        failed = []
        for r in releases:
            st = r.get('status', 'unknown')
            by_status[st] = by_status.get(st, 0) + 1
            if st not in ('deployed',):
                failed.append(r)
        s['helm'] = {
            'release_count': len(releases),
            'by_status': by_status,
            'releases': releases,
            'failed_releases': failed,
        }

    # --- Container Runtime ---
    runtime = config.get('container_runtime', {})
    if runtime:
        s['runtime'] = runtime

    # --- Events ---
    events = config.get('kube_events', [])
    if events:
        warnings = [e for e in events if e.get('type') == 'Warning']
        by_reason = {}
        for e in warnings:
            r = e.get('reason', 'Unknown')
            by_reason[r] = by_reason.get(r, 0) + 1
        s['events'] = {
            'total': len(events),
            'warning_count': len(warnings),
            'by_reason': dict(sorted(by_reason.items(),
                                     key=lambda x: x[1], reverse=True)),
            'recent_warnings': warnings[-20:],
        }

    # --- Cross-checks ---
    checks = []
    for n in not_ready:
        checks.append({'check': f"node {n['name']}", 'status': 'FAIL',
                       'detail': f"Status: {n['status']}"})
    for n in ready:
        checks.append({'check': f"node {n['name']}", 'status': 'OK',
                       'detail': f"Ready, {n.get('version', '')}"})
    if s.get('helm', {}).get('failed_releases'):
        for r in s['helm']['failed_releases']:
            checks.append({'check': f"helm {r['name']}", 'status': 'WARN',
                           'detail': f"Status: {r['status']}"})
    problem = s.get('pods', {}).get('problem_pods', [])
    if problem:
        checks.append({'check': 'pod health', 'status': 'WARN',
                       'detail': f"{len(problem)} pods not Running/Succeeded"})
    if not nodes:
        checks.append({'check': 'cluster data', 'status': 'WARN',
                       'detail': 'No node data found'})

    # Node conditions (pressure signals)
    node_conditions = config.get('node_conditions', [])
    if node_conditions:
        s['node_conditions'] = node_conditions
        for nc in node_conditions:
            checks.append({
                'check': f"node {nc['node']}",
                'status': 'FAIL',
                'detail': f"{nc['condition']}=True"})

    s['cross_check'] = checks

    # Warnings
    warnings = []
    if not_ready:
        warnings.append(
            f"{len(not_ready)} node(s) NotReady: "
            f"{', '.join(n['name'] for n in not_ready)}")
    high_restart = [p for p in pods
                    if _parse_restart_count(p.get('restarts', '0')) > 10]
    if high_restart:
        warnings.append(
            f"{len(high_restart)} pod(s) with >10 restarts")
    s['warnings'] = warnings

    s['source_files'] = sorted(set(config.get('container_source_files', [])))

    return s


def _node_is_ready(node):
    """True if node status is Ready (not NotReady, SchedulingDisabled, etc)."""
    s = node.get('status', '')
    return s == 'Ready' or s.startswith('Ready,')


def _parse_restart_count(val):
    """Extract integer restart count from kubectl output (e.g. '5', '3 (2d ago)')."""
    m = re.match(r'(\d+)', str(val))
    return int(m.group(1)) if m else 0
