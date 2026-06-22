#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#########################################################################
# Host Utilities Module
#
# Common utilities shared across all host configuration domains.
# Provides verbose control, .info file section parsing, formatting
# helpers, and host directory discovery for collect bundles.
########################################################################

import glob
import os
import re
import sys

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# ---------------------------------------------------------------------------
# Module-level verbose control
# ---------------------------------------------------------------------------

_verbose_level = 0


def set_verbose_level(level):
    """Set the global verbose level for all modules."""
    global _verbose_level
    _verbose_level = level


def get_verbose_level():
    """Return the current global verbose level."""
    return _verbose_level

# ---------------------------------------------------------------------------
# Section parser
# ---------------------------------------------------------------------------


def parse_info_sections(text):
    """Split a ---- delimited .info file into {command_string: output_text}.

    Handles header formats used across StarlingX releases:
        A: "Tue 16 Dec 2025 11:58:55 AM KST :  : ip -s link"
        B: "Tue 20 Jan 2026 08:00:20 AM UTC : controller-0 : ip -s link"
        C: "Fri Apr 24 12:20:08 UTC 2026 : controller-0 : ip -s link"

    The hostname field between the two colons may be empty or contain
    a single word. The command field may contain colons (e.g. grep
    expressions), so the regex uses \\S* for the hostname to avoid
    greedy matching into the command.

    Returns:
        dict mapping command strings to their output text.
    """
    sections = {}
    lines = text.split('\n')
    i = 0
    sep = re.compile(r'^-{4,}$')
    # Match any line containing " : ... : <command>" with a leading
    # date-like prefix (3-letter weekday followed by date tokens).
    cmd_re = re.compile(
        r'^\w{3}\s+.+?\s+:\s+\S*\s*:\s+(.+)$'
    )

    while i < len(lines):
        if sep.match(lines[i].strip()):
            if i + 2 < len(lines) and sep.match(lines[i + 2].strip()):
                m = cmd_re.match(lines[i + 1].strip())
                if m:
                    cmd = m.group(1).strip()
                    i += 3
                    output_lines = []
                    while i < len(lines) and not sep.match(
                            lines[i].strip()):
                        output_lines.append(lines[i])
                        i += 1
                    sections[cmd] = '\n'.join(output_lines)
                    continue
        i += 1

    return sections

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def human_bytes(n):
    """Format a byte count into a compact human-readable string.

    Examples: 1024 -> "1.0K", 1048576 -> "1.0M", 500 -> "500B"
    """
    for unit in ['B', 'K', 'M', 'G', 'T']:
        if abs(n) < 1024:
            if unit == 'B':
                return f"{int(n)}{unit}"
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"

# ---------------------------------------------------------------------------
# Host directory discovery
# ---------------------------------------------------------------------------


def find_host_dir(bundle, hostname):
    """Find the host directory for hostname within a collect bundle.

    Handles both flat and nested bundle layouts:
        flat:   <bundle>/<hostname>_<ts>/var/extra/...
        nested: <bundle>/<hostname>_<ts>/<hostname>_<ts>/var/extra/...

    When multiple timestamp directories match, the most recent (by
    lexicographic sort of the timestamp suffix) is selected.

    Args:
        bundle: Path to the collect bundle directory.
        hostname: Hostname to locate (e.g. "controller-0").

    Returns:
        Absolute path to the host directory containing var/, or None.
    """
    verbose = get_verbose_level()
    pattern = os.path.join(bundle, f"{hostname}_*")
    matches = sorted(
        [m for m in glob.glob(pattern) if os.path.isdir(m)]
    )

    if verbose >= 3:
        print(f"  glob pattern: {pattern}")
        print(f"  matches: {len(matches)}")
        for m in matches:
            has_var = os.path.isdir(os.path.join(m, 'var'))
            print(f"    {m}  (has var/: {has_var})")

    if not matches:
        return None

    candidate = matches[-1]

    if os.path.isdir(os.path.join(candidate, 'var')):
        return candidate

    # Check one level deeper for nested layout
    inner = glob.glob(os.path.join(candidate, f"{hostname}_*"))
    inner_dirs = sorted(
        [d for d in inner if os.path.isdir(d)]
    )

    if verbose >= 3 and inner_dirs:
        print(f"  checking nested dirs in {candidate}:")
        for d in inner_dirs:
            has_var = os.path.isdir(os.path.join(d, 'var'))
            print(f"    {d}  (has var/: {has_var})")

    for d in reversed(inner_dirs):
        if os.path.isdir(os.path.join(d, 'var')):
            return d

    return candidate


def extract_host_identity(host_dir):
    """Extract hostname and collect timestamp from a host directory name.

    Expects the pattern: <hostname>_YYYYMMDD.HHMMSS

    Args:
        host_dir: Path to the host directory.

    Returns:
        Tuple of (hostname, collected_timestamp) strings.
        If the pattern does not match, returns (dirname, '').
    """
    dirname = os.path.basename(host_dir.rstrip('/'))
    m = re.match(r'^(.+?)_(\d{8}\.\d{6})$', dirname)
    if m:
        return m.group(1), m.group(2)
    return dirname, ''

# ---------------------------------------------------------------------------
# Source file tracking
# ---------------------------------------------------------------------------


def note_source(config, key, path):
    """Record a source file that contributed data.

    Args:
        config: The shared config dict.
        key: The config key to store sources under (e.g. 'network_source_files').
        path: Path to the source file.
    """
    config.setdefault(key, []).append(path)
