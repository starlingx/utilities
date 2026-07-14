#!/usr/bin/env python3
# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Combine all network_platform_audit modules into one deployable script.
# Also embeds network_diagnostics as the fallback for nodes without CLI access.
#
# Run from the platform-util/ source directory:
#
#   python3 tools/bundle_network_platform_audit.py [-o OUTPUT]
#
# The resulting bundle behaves as follows when executed:
#   - If /etc/platform/openrc exists, platform CLI (system show) succeeds,
#     and the node is the active controller  -> runs network_platform_audit.
#   - Otherwise                              -> runs network_diagnostics.
#

import argparse
import os
import re
import stat
import textwrap

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.join(SCRIPT_DIR, '..', 'network_platform_audit')

# network_diagnostics source path.
# The tool lives at:  platform-util/scripts/network_diagnostics
# This bundler lives: platform-util/platform-util/tools/
# So the relative path from SCRIPT_DIR is: ../../scripts/network_diagnostics
DIAG_SCRIPT = os.path.join(SCRIPT_DIR, '..', '..', 'scripts', 'network_diagnostics')

# Modules in strict dependency order (relative to PKG_DIR, no .py suffix).
# 'dispatcher' is intentionally omitted here: it is appended *after* the
# embedded network_diagnostics section so that both main() (from __main__)
# and _network_diagnostics_main() (from the diagnostics embed) are already
# defined when dispatcher.py code runs.
MODULES = [
    'state',
    'log',
    'run',
    'ssh',
    'sysinv',
    'kube',
    'tests/ts01_availability',
    'tests/ts02_interfaces',
    'tests/ts03_sriov',
    'tests/ts04_addresses',
    'tests/ts05_routes',
    'tests/ts06_ports',
    'tests/ts07_lldp',
    'tests/ts08_addrpools',
    'tests/ts09_dns',
    'tests/ts10_dhcp',
    'tests/ts11_heartbeat',
    'tests/ts12_ipsec',
    'tests/ts13_k8s',
    'tests/ts14_coredns',
    'tests/ts15_cluster_nat',
    'tests/ts16_gnp',
    'tests/ts17_openstack',
    'tests/ts18_mtu',
    'dc_firewall',
    'tests/ts19_dc_systemcontroller',
    'tests/ts20_dc_subcloud',
    '__main__',
]

# Matches any import from the package at any indentation level
_INTERNAL_RE = re.compile(
    r'^[ \t]*(?:'
    r'from\s+network_platform_audit(?:\.\w+)*\s+import\s+.*'
    r'|import\s+network_platform_audit(?:\.\w+)*(?:\s+as\s+\w+)?'
    r')\s*$'
)

_ASSIGN_RE = re.compile(r'^([A-Za-z_]\w*)\s*=')


def _read(rel_path):
    with open(os.path.join(PKG_DIR, rel_path + '.py'), encoding='utf-8') as f:
        return f.read()


def _extract_header(content):
    """Return only the copyright/SPDX lines from the leading #-comment block.

    Stops at the first bare '#' separator line so module-specific doc is excluded.
    """
    lines = []
    for line in content.splitlines():
        if line.rstrip() == '#':
            break
        if line.startswith('#'):
            lines.append(line)
        else:
            break
    return '\n'.join(lines)


def _strip_header(content):
    """Remove the leading #-comment block (copyright/module-doc) and the
    module-level docstring (triple-quoted string) that may follow.
    """
    lines = content.splitlines(keepends=True)
    i = 0
    # Skip leading comment block and blank lines
    while i < len(lines) and (lines[i].startswith('#') or lines[i].rstrip() == ''):
        i += 1
    # Skip optional module docstring
    if i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            # Check if docstring closes on the same line (single-line docstring)
            rest = stripped[3:]
            if rest.rstrip().endswith(quote) and len(rest.rstrip()) > len(quote):
                i += 1
            else:
                i += 1
                while i < len(lines) and quote not in lines[i]:
                    i += 1
                i += 1  # skip closing quote line
    return ''.join(lines[i:])


def _strip_internal_imports(content):
    """Drop statements that import from network_platform_audit.*, including multi-line ones."""
    result = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _INTERNAL_RE.match(line):
            # Track open parens to skip continuation lines
            depth = line.count('(') - line.count(')')
            i += 1
            while depth > 0 and i < len(lines):
                depth += lines[i].count('(') - lines[i].count(')')
                i += 1
        else:
            result.append(line)
            i += 1
    return '\n'.join(result)


def _strip_name_guard(content):
    """Remove the `if __name__ == '__main__':` block from module content.

    Used when bundling __main__.py so its guard does not fire before the
    dispatcher's guard at the very end of the bundle.
    """
    lines = content.splitlines()
    result = []
    skip = False
    for line in lines:
        if re.match(r'^if\s+__name__\s*==\s*["\']__main__["\']\s*:', line):
            skip = True
            continue
        if skip:
            # Lines that are indented (part of the if-block) are skipped
            if line == '' or line[0] in (' ', '\t'):
                continue
            else:
                skip = False
        result.append(line)
    return '\n'.join(result)


def _transform_state(content):
    """Wrap state.py globals into a SimpleNamespace so all modules can do
    `state.VARIABLE` after their internal imports are stripped.
    Top-level assignments become `state.VAR = value`; other lines are kept.
    """
    preamble = [
        'import types as _npa_types',
        'state = _npa_types.SimpleNamespace()',
        '',
    ]
    body = []
    for line in content.splitlines():
        if _ASSIGN_RE.match(line):
            body.append('state.' + line)
        else:
            body.append(line)
    return '\n'.join(preamble + body)


def _build_diagnostics_section(diag_path):
    """Read network_diagnostics and wrap its body inside _network_diagnostics_main().

    The function replaces the ``if __name__ == "__main__":`` block at the end
    with a regular call so it integrates cleanly into the bundle without
    conflicting with the platform-audit argument parser or the top-level
    __name__ guard.

    Returns the section string ready to be appended to the bundle.
    """
    with open(diag_path, encoding='utf-8') as f:
        source = f.read()

    # Strip shebang, copyright header and module docstring
    source = _strip_header(source)

    lines = source.splitlines()

    # Locate the `if __name__ == "__main__":` block
    main_guard_idx = None
    for idx, line in enumerate(lines):
        if re.match(r'^if\s+__name__\s*==\s*["\']__main__["\']\s*:', line):
            main_guard_idx = idx
            break

    if main_guard_idx is None:
        raise RuntimeError(
            "network_diagnostics: could not find 'if __name__ == \"__main__\":' block"
        )

    # Everything before the guard is the module body; indent it into the function.
    body_lines = lines[:main_guard_idx]

    # The block under the guard becomes the function body after the module body.
    # While de-indenting, replace `parse_args()` with `parse_known_args()[0]`
    # so that arguments exclusive to network_platform_audit (e.g. --verbose,
    # --ssh-pass, --subcloud*) are silently ignored when running in fallback mode.
    guard_body = []
    for line in lines[main_guard_idx + 1:]:
        # De-indent one level (4 spaces) that was under the if-guard
        if line.startswith('    '):
            de = line[4:]
        elif line == '':
            guard_body.append('')
            continue
        else:
            # Non-indented line after guard = end of block (shouldn't happen)
            de = line
        # Replace bare parse_args() call so unknown args are tolerated
        de = re.sub(r'\bparser\.parse_args\(\)', 'parser.parse_known_args()[0]', de)
        guard_body.append(de)

    # Build the wrapper function
    # All original top-level code goes into _network_diagnostics_main()
    # indented by 4 spaces so it becomes function-local.
    indented_body = ['    ' + ln if ln.strip() else '' for ln in body_lines]
    indented_guard = ['    ' + ln if ln.strip() else '' for ln in guard_body]

    func_lines = (
        ['def _network_diagnostics_main():',
         '    """Self-contained node-local network diagnostics (no CLI/DB required)."""',
         '']
        + indented_body
        + ['']
        + indented_guard
    )

    bar = '-' * 70
    section = (
        f'# {bar}\n'
        f'# network_diagnostics (embedded fallback)\n'
        f'# {bar}\n\n'
        + '\n'.join(func_lines)
    )
    return section


def bundle(output_path, diag_path=None):
    sections = []
    file_header = None

    # --- network_platform_audit modules ---
    for mod in MODULES:
        raw = _read(mod)
        if file_header is None:
            file_header = _extract_header(raw)
        content = _strip_header(raw)
        content = _strip_internal_imports(content)
        # __main__.py has its own `if __name__ == "__main__": main()` guard
        # which must not fire inside the bundle; strip it so only the
        # dispatcher's guard at the very end of the file runs.
        if mod == '__main__':
            content = _strip_name_guard(content)
        content = re.sub(r'\n{3,}', '\n\n', content).strip()

        if mod == 'state':
            content = _transform_state(content)

        label = mod.replace('/', '.')
        bar = '-' * 70
        sections.append(f'# {bar}\n# {label}\n# {bar}\n\n{content}')

    # --- embedded network_diagnostics ---
    if diag_path and os.path.isfile(diag_path):
        diag_section = _build_diagnostics_section(diag_path)
        sections.append(diag_section)
        print(f'Embedded network_diagnostics from: {diag_path}')
    else:
        # Provide a stub so the bundle is still valid even without the file
        stub = (
            'def _network_diagnostics_main():\n'
            '    print("[WARN] network_diagnostics not available in this bundle.")\n'
            '    import sys; sys.exit(1)\n'
        )
        bar = '-' * 70
        sections.append(
            f'# {bar}\n'
            f'# network_diagnostics (stub — source not found at build time)\n'
            f'# {bar}\n\n'
            + stub
        )
        print(f'[WARN] network_diagnostics not found at {diag_path!r}; stub embedded.')

    # --- dispatcher (must come after __main__ and network_diagnostics) ---
    raw = _read('dispatcher')
    content = _strip_header(raw)
    content = _strip_internal_imports(content)
    content = re.sub(r'\n{3,}', '\n\n', content).strip()
    bar = '-' * 70
    sections.append(f'# {bar}\n# dispatcher\n# {bar}\n\n{content}')

    # --- entry point ---
    entry_section = textwrap.dedent("""\
        # ----------------------------------------------------------------------
        # Entry point
        # ----------------------------------------------------------------------

        if __name__ == "__main__":
            dispatch()
    """)
    sections.append(entry_section)

    header = (
        '#!/usr/bin/env python3\n'
        + file_header + '\n'
        '# Generated by tools/bundle_network_platform_audit.py — do not edit.\n'
        '#\n'
        '# Usage: sudo ./network_platform_audit [options]\n'
        '#\n'
        '# The script auto-detects whether platform CLI access is available:\n'
        '#   - Active controller with platform services up -> full platform audit\n'
        '#   - Any other node (worker, storage, standby controller, no CLI) ->\n'
        '#     node-local network_diagnostics (no database access required)\n'
    )
    output = header + '\n' + '\n\n\n'.join(sections) + '\n'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output)

    mode = os.stat(output_path).st_mode
    os.chmod(output_path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    size = os.path.getsize(output_path)
    print(f'Bundle written: {output_path} ({size:,} bytes, {size // 1024} KB)')


def main():
    parser = argparse.ArgumentParser(
        description='Bundle network_platform_audit into a single deployable script'
    )
    parser.add_argument(
        '-o', '--output',
        default='network_platform_audit',
        help='Output file path (default: ./network_platform_audit)',
    )
    parser.add_argument(
        '--diagnostics',
        default=DIAG_SCRIPT,
        metavar='PATH',
        help=(
            'Path to the network_diagnostics script to embed as fallback '
            f'(default: {DIAG_SCRIPT})'
        ),
    )
    args = parser.parse_args()
    bundle(args.output, diag_path=args.diagnostics)


if __name__ == '__main__':
    main()
