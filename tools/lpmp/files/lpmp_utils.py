#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
LPMP Utilities Module

This module contains utility functions for the Log Pattern Matching Profiler.
Provides file handling, model loading, timestamp parsing, and output utilities.
"""

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from enum import Enum
import fnmatch
import glob
from io import StringIO
import os
import re
from shlex import quote as shquote
import subprocess
import sys
import threading
import time
from typing import Optional

import yaml

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True
# cspell:ignore LPMP


# ---------------------------------------------------------------------------
# Console output capture classes
# ---------------------------------------------------------------------------
class ConsoleCapture:
    """Capture console output and write to profile files."""

    def __init__(self, silent_mode=False):
        self.captured_output = []
        self.original_stdout = sys.stdout
        self.capture_buffer = StringIO()
        self.silent_mode = silent_mode
        # Store reference to true original stdout for progress indicators
        ConsoleCapture._true_original_stdout = self.original_stdout

    def start_capture(self):
        """Start capturing console output."""
        if self.silent_mode:
            # Silent mode: capture only, no console display
            sys.stdout = self.capture_buffer
        else:
            # Normal mode: both console display and capture
            sys.stdout = TeeOutput(self.original_stdout, self.capture_buffer)

    def stop_capture(self):
        """Stop capturing and return to normal output."""
        sys.stdout = self.original_stdout

    def is_capturing(self):
        """Return True while capture is redirecting sys.stdout.

        Safe to call from any callsite that only needs to know whether
        a stop_capture() has already been issued. Compares against the
        stored original stdout rather than relying on external state.
        """
        return sys.stdout is not self.original_stdout

    def get_captured_output(self):
        """Get the captured output as a string."""
        return self.capture_buffer.getvalue()

    def write_to_file(self, filepath):
        """Write captured output to a file."""
        with open(filepath, 'w') as f:
            f.write(self.get_captured_output())

    @classmethod
    def get_true_original_stdout(cls):
        """Get the true original stdout for progress indicators."""
        return getattr(cls, '_true_original_stdout', sys.__stdout__)


class TeeOutput:
    """Output to both original stdout and capture buffer."""

    def __init__(self, original, capture):
        self.original = original
        self.capture = capture

    def write(self, text):
        self.original.write(text)
        self.capture.write(text)

    def flush(self):
        self.original.flush()
        self.capture.flush()


# ---------------------------------------------------------------------------
# Progress indicator enum and functions
# ---------------------------------------------------------------------------
class ProgressType(Enum):
    """Enum for progress indicator types."""
    NONE = 'none'
    DOTS = 'dots'
    CLASSIC = 'classic'
    CIRCLES = 'circles'
    MODERN = 'modern'  # Unicode dots


# ---------------------------------------------------------------------------
# Model type enum and structured result types
# ---------------------------------------------------------------------------
class ModelType(Enum):
    """Enum for the three supported LPMP model types."""
    PATTERN = 'pattern'
    PAIR = 'pair'
    TIMELINE = 'timeline'


def detect_model_type(blocks):
    """Detect the model type from the block list.

    Returns ModelType based on block field inspection:
      - Any block has 'timeline'         -> TIMELINE
      - Any block has 'window'           -> TIMELINE
      - All blocks have 'patterns' only  -> PATTERN
      - Any block has 'start'/'stop'     -> PAIR

    This must be called after load_model validation so
    the blocks are known to be structurally valid.
    """
    for block in blocks:
        if 'timeline' in block:
            return ModelType.TIMELINE
    for block in blocks:
        if block.get('window'):
            return ModelType.TIMELINE
    for block in blocks:
        if 'start' in block and 'stop' in block:
            return ModelType.PAIR
    return ModelType.PATTERN


@dataclass
class PatternResult:
    """Structured result for a single pattern block match."""
    timestamp: str
    block_label: str
    log_line: str
    actual_filename: str
    hostname: str
    is_warning: bool = False
    warning_text: Optional[str] = None
    context: Optional[tuple] = None


@dataclass
class PairResult:
    """Structured result for a single pair block match."""
    start_timestamp: str
    stop_timestamp: str
    duration_seconds: float
    block_label: str
    actual_filename: str
    hostname: str
    is_warning: bool = False
    warning_text: Optional[str] = None


@dataclass
class TimelineResult:
    """Structured result for a single timeline block match."""
    timestamp: str
    block_label: str
    log_line: str
    actual_filename: str
    hostname: str
    context: Optional[tuple] = None


# Progress indicator constants
PROGRESS_DOT_INTERVAL = 0.2  # progress rate every 0.2 seconds

# Global verbose level for vlog function
_verbose_level = 0
MAX_VERBOSE_LEVEL = 5  # Maximum supported verbose level


def set_verbose_level(level):
    """Set global verbose level for vlog function."""
    global _verbose_level
    _verbose_level = min(level, MAX_VERBOSE_LEVEL)  # Cap at maximum level


def get_verbose_level():
    """Get current global verbose level."""
    return _verbose_level


def _vlog(level, *args, **kwargs):
    """Private verbose logging function with timestamp."""
    if _verbose_level >= level:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] Debug {level}:", *args, **kwargs)


def vlog1(*args, **kwargs):
    """Verbose logging level 1."""
    _vlog(1, *args, **kwargs)


def vlog2(*args, **kwargs):
    """Verbose logging level 2."""
    _vlog(2, *args, **kwargs)


def vlog3(*args, **kwargs):
    """Verbose logging level 3."""
    _vlog(3, *args, **kwargs)


def vlog4(*args, **kwargs):
    """Verbose logging level 4."""
    _vlog(4, *args, **kwargs)


def vlog5(*args, **kwargs):
    """Verbose logging level 5."""
    _vlog(5, *args, **kwargs)


# cspell:ignore wlog
def wlog(*args, **kwargs):
    """Warning logging with timestamp - always displayed regardless of verbose level."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] Warning:", *args, **kwargs)


def start_progress_indicator(progress_type=ProgressType.DOTS):
    """Start progress indicator based on type selection.

    Args:
        progress_type: ProgressType enum value (NONE, DOTS, CLASSIC, CIRCLES, MODERN)

    Returns:
        progress_active list for stopping indicator, or None for NONE type
    """
    if progress_type == ProgressType.NONE:
        return None

    progress_active = [True]  # Use list for mutable reference
    # Get the true original stdout to ensure progress never goes to capture buffer
    original_stdout = ConsoleCapture.get_true_original_stdout()

    def show_progress():
        if progress_type == ProgressType.DOTS:
            # Simple dots - one dot per second
            while progress_active[0]:
                original_stdout.write('.')
                original_stdout.flush()
                time.sleep(PROGRESS_DOT_INTERVAL*5)

        elif progress_type == ProgressType.CLASSIC:
            # Classic old-school spinner
            spinner = ['|', '/', '-', '\\']
            while progress_active[0]:
                for char in spinner:
                    if not progress_active[0]:
                        return
                    original_stdout.write(char)
                    original_stdout.flush()
                    time.sleep(PROGRESS_DOT_INTERVAL)
                    original_stdout.write('\b')
                    original_stdout.flush()

        elif progress_type == ProgressType.CIRCLES:
            # Circle spinner
            spinner = ['◐', '◓', '◑', '◒']
            while progress_active[0]:
                for char in spinner:
                    if not progress_active[0]:
                        return
                    original_stdout.write(char)
                    original_stdout.flush()
                    time.sleep(PROGRESS_DOT_INTERVAL)
                    original_stdout.write('\b')
                    original_stdout.flush()

        elif progress_type == ProgressType.MODERN:
            # Unicode dots spinner with periodic dots
            spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
            while progress_active[0]:
                # Spin twice (20 characters) then dot
                for _ in range(2):
                    for char in spinner:
                        if not progress_active[0]:
                            return
                        original_stdout.write(char)
                        original_stdout.flush()
                        time.sleep(PROGRESS_DOT_INTERVAL)
                        original_stdout.write('\b')
                        original_stdout.flush()
                if progress_active[0]:
                    original_stdout.write('.')
                    original_stdout.flush()

    progress_thread = threading.Thread(target=show_progress, daemon=True)
    progress_thread.start()
    return progress_active


def stop_progress_indicator(progress_active):
    """Stop progress indicator and clean up cursor position.

    Safe to call with progress_active=None (no-op when progress was
    never started, e.g. ProgressType.NONE).
    """
    if progress_active is None:
        return
    progress_active[0] = False
    time.sleep(0.3)  # Give indicator time to stop
    # Get the true original stdout to ensure newline never goes to capture buffer
    try:
        original_stdout = ConsoleCapture.get_true_original_stdout()
        original_stdout.write('\n')  # New line after progress indicator
        original_stdout.flush()
    except (ValueError, OSError):
        # stdout may be closed in test environments; ignore.
        pass


def _get_search_paths(kind, etc_dir, system_dir, examples=False,
                      verbose=0, label=None):
    """Build the prioritized search path list shared by models, jobs,
    and scripts, so all three "resolve by bare name" features agree on
    where an override lives relative to a built-in or packaged default.

    Search order (highest to lowest priority):
    1. ./                  - current directory. Always highest: lets a
                             user override any built-in or packaged
                             file just by placing a same-named file in
                             wherever they're running the tool from
                             (e.g. to work around a bug without editing
                             the installed copy).
    2. <etc_dir>            - writable user/developer override location
                             (survives OSTree image updates).
    3. <tool_dir>/<kind>/   - built-in, shipped with the tool. Skipped
                             when running from an installed package
                             (dist-packages/site-packages).
    4. <system_dir>         - system-provided packaged defaults
                             (read-only).

    Args:
        kind: subdirectory name under the tool directory, e.g. 'models'
        etc_dir: writable override directory, e.g. '/etc/lpmp.d/jobs/'
        system_dir: read-only system-provided directory
        examples: when True, append an 'examples' subdirectory right
            after both the built-in and system directories (models only)
        verbose: verbosity level; >=1 prints the resolved paths
        label: human-readable label for the verbose banner

    Returns list of search paths.
    """
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    installed = 'dist-packages' in tool_dir or 'site-packages' in tool_dir

    search_paths = ['./', etc_dir]                                  # Priority 1, 2
    if not installed:
        builtin = os.path.join(tool_dir, kind)
        search_paths.append(builtin)                                # Priority 3
        if examples:
            search_paths.append(os.path.join(builtin, 'examples'))
    search_paths.append(system_dir)                                 # Priority 4
    if examples:
        search_paths.append(os.path.join(system_dir, 'examples'))

    if verbose >= 1:
        print(f"Tool: {os.path.abspath(sys.argv[0]) if sys.argv else 'N/A'}")
        print(f"{label or kind.capitalize()} search paths (highest to lowest priority):")
        for i, path in enumerate(search_paths, 1):
            exists = "✓" if os.path.exists(path) else "✗"
            print(f"  {i}. {exists} {path}")

    return search_paths


def get_models_search_paths(verbose=0):
    """Get prioritized search paths for model files.

    See _get_search_paths() for the shared priority order. Models
    additionally get an 'examples/' subdirectory appended after each
    of the built-in and system-provided directories.

    Returns list of search paths.
    """
    return _get_search_paths('models', etc_dir='/etc/lpmp.d/',
                             system_dir='/var/lib/lpmp_models/',
                             examples=True, verbose=verbose, label='Model')


def get_jobs_search_paths(verbose=0):
    """Get prioritized search paths for jobs spec files.

    See _get_search_paths() for the shared priority order. Lets a
    packaged jobs spec be referenced by bare name (e.g. --jobs
    mtce_job) instead of a full path.

    Returns list of search paths.
    """
    return _get_search_paths('jobs', etc_dir='/etc/lpmp.d/jobs/',
                             system_dir='/var/lib/lpmp_jobs/',
                             verbose=verbose, label='Jobs')


def find_jobs_file(jobs_file):
    """Find a jobs spec file using the prioritized jobs search path.

    Accepts a name with or without a .json extension, an absolute path,
    or a relative path. Returns the full path or None if not found.
    Mirrors find_model_file().
    """
    if jobs_file.endswith('.json'):
        candidates = [jobs_file]
    else:
        candidates = [jobs_file + '.json', jobs_file]

    # Absolute path or explicit relative path: use as-is first.
    if os.path.isabs(jobs_file) or os.sep in jobs_file or '/' in jobs_file:
        for candidate in candidates:
            if os.path.exists(candidate):
                vlog2(f"Found jobs spec (explicit path): {candidate}")
                return candidate
        if os.path.isabs(jobs_file):
            return None

    for path in get_jobs_search_paths(0):
        for candidate in candidates:
            full_path = os.path.join(path, candidate)
            if os.path.exists(full_path):
                normalized_path = os.path.normpath(full_path)
                vlog2(f"Found jobs spec: {normalized_path}")
                return normalized_path

    return None


def collect_jobs_files(search_paths=None):
    """Collect available .json jobs specs across the jobs search paths.

    Returns a de-duplicated list of (name, full_path) tuples sorted by
    name. De-dup is by basename so a higher-priority path shadows a
    lower-priority one, matching the resolution order of find_jobs_file().
    Used by --list-jobs.
    """
    if search_paths is None:
        search_paths = get_jobs_search_paths(0)

    seen = set()
    found = []
    for path in search_paths:
        try:
            names = sorted(os.listdir(path))
        except (OSError, IOError):
            continue
        for name in names:
            if not name.endswith('.json'):
                continue
            if name in seen:
                continue
            full_path = os.path.join(path, name)
            if os.path.isfile(full_path):
                seen.add(name)
                found.append((name, os.path.normpath(full_path)))

    found.sort(key=lambda x: x[0].lower())
    return found


def detect_bundle_hosts(bundle_path):
    """Detect bundle hosts from dated hostname directories.
    Expected format: <hostname>_YYYYMMDD.HHMMSS
    Returns tuple: (bundle_host_list, bundle_host_list_dated)
    - bundle_host_list: sorted list of hostnames (without date suffix)
    - bundle_host_list_dated: sorted list of full directory names (hostname_date)

    If host directories have different date parts the mismatch is
    auto-accepted and a warning is logged. Each hostname is represented
    once using the directory with the latest date part.
    """
    if not os.path.isdir(bundle_path) or bundle_path == '/':
        return [], []

    entries = os.listdir(bundle_path)
    host_pattern = re.compile(r'^(.+)_(\d{8}\.\d{6})$')
    bundle_hosts = {}

    for entry in entries:
        entry_path = os.path.join(bundle_path, entry)
        if not os.path.isdir(entry_path):
            continue
        match = host_pattern.match(entry)
        if match:
            hostname, date_part = match.groups()
            bundle_hosts.setdefault(date_part, []).append((hostname, entry))

    if not bundle_hosts:
        print("Error: No bundle hosts found", file=sys.stderr)
        print(f"Expected format: <hostname>_YYYYMMDD.HHMMSS in {bundle_path}", file=sys.stderr)
        sys.exit(1)
    # cspell:ignore hostnames
    if len(bundle_hosts) > 1:
        # Mismatched date parts - log and auto-accept. Each hostname is
        # collapsed to its latest-dated directory below.
        print("Warning: Bundle host directories have different date parts", file=sys.stderr)
        for date_part, hosts in sorted(bundle_hosts.items()):
            host_names = [h[0] for h in hosts]
            print(f"  {date_part}: {', '.join(host_names)}", file=sys.stderr)
        print("Proceeding with the latest directory per host.", file=sys.stderr)

        latest_per_host = {}  # hostname -> (date_part, dir_name)
        for date_part, hosts in bundle_hosts.items():
            for hostname, dir_name in hosts:
                cur = latest_per_host.get(hostname)
                if cur is None or date_part > cur[0]:
                    latest_per_host[hostname] = (date_part, dir_name)

        for date_part, hosts in bundle_hosts.items():
            for hostname, dir_name in hosts:
                kept_dir = latest_per_host[hostname][1]
                if dir_name != kept_dir:
                    print(f"Note: skipping older directory '{dir_name}' "
                          f"(using '{kept_dir}' instead)", file=sys.stderr)

        host_tuples = [(h, latest_per_host[h][1]) for h in latest_per_host]
    else:
        date_part, host_tuples = list(bundle_hosts.items())[0]

    # Sort: controller-0 first, controller-1, other controllers,
    # storage nodes, then all others alphabetically
    def _host_sort_key(hostname):
        if hostname == 'controller-0':
            return (0, hostname)
        if hostname == 'controller-1':
            return (1, hostname)
        if hostname.startswith('controller-'):
            return (2, hostname)
        if hostname.startswith('storage-'):
            return (3, hostname)
        return (4, hostname)

    host_tuples.sort(key=lambda t: _host_sort_key(t[0]))
    hostnames = [h[0] for h in host_tuples]
    dated_dirs = [h[1] for h in host_tuples]

    vlog1(f"bundle_host_list: {hostnames}")
    vlog1(f"bundle_host_list_dated: {dated_dirs}")

    return hostnames, dated_dirs


def filter_hosts(hostnames, dated_dirs, filter_list, mode='include'):
    """Filter hosts based on include or exclude list.
    Validates all hosts in filter_list exist in hostnames.
    Returns filtered (hostnames, dated_dirs) tuple.
    """
    # Validate all hosts in filter_list
    invalid_hosts = [h for h in filter_list if h not in hostnames]
    if invalid_hosts:
        print(f"Error: Invalid host names: {', '.join(invalid_hosts)}", file=sys.stderr)
        print(f"Available hosts: {', '.join(hostnames)}", file=sys.stderr)
        sys.exit(1)

    if mode == 'include':
        filtered_hostnames = [h for h in hostnames if h in filter_list]
        filtered_dated = [d for h, d in zip(hostnames, dated_dirs) if h in filter_list]
    else:  # exclude
        filtered_hostnames = [h for h in hostnames if h not in filter_list]
        filtered_dated = [d for h, d in zip(hostnames, dated_dirs) if h not in filter_list]

    if not filtered_hostnames:
        print("Error: No hosts selected for processing", file=sys.stderr)
        sys.exit(1)

    vlog1(f"Processing hosts ({mode}): {filtered_hostnames}")

    return filtered_hostnames, filtered_dated


def interactive_host_selection(hostnames, dated_dirs):
    """Interactive host selection for bundle mode.
    Displays hosts sorted by type (controllers, storage, others).
    Prompts user for include/exclude list.
    Returns filtered (hostnames, dated_dirs) tuple.
    """
    # Sort hosts by type: controllers first, then storage, then others
    controllers = [h for h in hostnames if h.startswith('controller-')]
    storage = [h for h in hostnames if h.startswith('storage-')]
    others = [h for h in hostnames if not h.startswith('controller-') and not h.startswith('storage-')]

    sorted_hosts = controllers + storage + others

    # Print in cut-and-paste format
    print("\nAvailable hosts:")
    print(' '.join(sorted_hosts))
    print()

    # Prompt for host list
    try:
        user_input = input("Enter space-separated list of hosts (or press Enter for all): ").strip()

        if not user_input:
            # User pressed Enter - use all hosts
            return hostnames, dated_dirs

        selected_hosts = user_input.split()

        # Validate selected hosts
        invalid_hosts = [h for h in selected_hosts if h not in hostnames]
        if invalid_hosts:
            print(f"Error: Invalid host names: {', '.join(invalid_hosts)}", file=sys.stderr)
            sys.exit(1)

        # Ask include or exclude
        mode = input("Is this an include or exclude list? (i/e): ").strip().lower()

        if mode == 'i':
            # Include mode - only process selected hosts
            filtered_hostnames = [h for h in hostnames if h in selected_hosts]
            filtered_dated = [d for h, d in zip(hostnames, dated_dirs) if h in selected_hosts]
        elif mode == 'e':
            # Exclude mode - process all except selected hosts
            filtered_hostnames = [h for h in hostnames if h not in selected_hosts]
            filtered_dated = [d for h, d in zip(hostnames, dated_dirs) if h not in selected_hosts]
        else:
            print("Error: Invalid mode. Enter 'i' for include or 'e' for exclude", file=sys.stderr)
            sys.exit(1)

        if not filtered_hostnames:
            print("Error: No hosts selected for processing", file=sys.stderr)
            sys.exit(1)

        vlog1(f"Processing hosts: {filtered_hostnames}")

        return filtered_hostnames, filtered_dated

    except (KeyboardInterrupt, EOFError):
        print("\n\nOperation cancelled by user", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# File ignore list and custom timestamp format support
# ---------------------------------------------------------------------------
_file_ignore_patterns = []      # list of glob patterns / dir prefixes to skip
_custom_timestamp_formats = []  # list of {'pattern': glob, 'regex': compiled, 'format': strptime}


def load_file_ignore_list(search_paths=None):
    """Auto-load file_ignore_list_and_format_handling.yaml from model search paths.

    Populates the global _file_ignore_patterns and _custom_timestamp_formats.
    Silently does nothing if the file is not found.
    """
    global _file_ignore_patterns, _custom_timestamp_formats

    if search_paths is None:
        search_paths = get_models_search_paths(0)

    for path in search_paths:
        for subdir in ['helpers', '']:
            if subdir:
                candidate = os.path.join(path, subdir, 'file_ignore_list_and_format_handling.yaml')
            else:
                candidate = os.path.join(path, 'file_ignore_list_and_format_handling.yaml')
            if os.path.isfile(candidate):
                try:
                    with open(candidate, 'r') as f:
                        data = yaml.safe_load(f)
                    if not isinstance(data, dict):
                        continue

                    _file_ignore_patterns = data.get('ignore', []) or []

                    for entry in data.get('timestamp_formats', []) or []:
                        try:
                            compiled = re.compile(entry['regex'])
                            _custom_timestamp_formats.append({
                                'pattern': entry['pattern'],
                                'regex': compiled,
                                'format': entry['format'],
                            })
                        except (KeyError, re.error) as e:
                            vlog1(f"Skipping bad timestamp_formats entry: {e}")

                    vlog2(f"Loaded file_ignore_list_and_format_handling.yaml from {candidate}")
                    vlog2(f"  ignore: {_file_ignore_patterns}")
                    vlog2(f"  timestamp_formats: {len(_custom_timestamp_formats)} entries")
                    return
                except (yaml.YAMLError, IOError) as e:
                    vlog1(f"Error loading {candidate}: {e}")
                    continue


def is_ignored_path(relpath):
    """Check if a relative path matches any ignore pattern.

    Supports:
      - Directory prefixes with trailing /  (e.g. 'pods/')
      - Glob patterns                      (e.g. '*.pid')
      - Exact basenames                    (e.g. 'wtmp')
    """
    for pattern in _file_ignore_patterns:
        if pattern.endswith('/'):
            # Directory prefix — match if relpath starts with it
            if relpath.startswith(pattern) or relpath == pattern.rstrip('/'):
                return True
        elif fnmatch.fnmatch(relpath, pattern):
            return True
        elif fnmatch.fnmatch(os.path.basename(relpath), pattern):
            return True
    return False


def _parse_custom_timestamp(line, relpath):
    """Try custom timestamp formats for a file matching relpath.
    Pattern can be a string or list of strings.
    Returns datetime or None.
    """
    for entry in _custom_timestamp_formats:
        patterns = entry['pattern']
        if isinstance(patterns, str):
            patterns = [patterns]
        if any(fnmatch.fnmatch(relpath, p) for p in patterns):
            match = entry['regex'].search(line)
            if match:
                try:
                    return datetime.strptime(match.group(1), entry['format'])
                except (ValueError, IndexError):
                    pass
    return None


# Pre-compiled timestamp regexes (avoids per-line re.compile overhead)
_RE_SYSINV_TS = re.compile(r'sysinv (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})')
_RE_ISO_TS = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?)')
# Space-separated form with dot-millis at the start of the line. Matches
# the common WRCP log layout used by ceph-manager.log, sysinv.log,
# software-api.log, fm-api.log, keystone-all.log, rabbit@localhost.log,
# horizon.log, barbican-api.log, tuned.log, mgr-restful-plugin.log, etc.
# Anchored with `^` so in-message dates inside a log line don't match.
_RE_SPACE_TS = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})')


def parse_timestamp(line, relpath=None):
    """Extract timestamp from log line supporting sysinv, ISO and space formats.

    Formats supported (in order):
    - sysinv: "sysinv 2024-01-06 12:30:45.123 message"
    - ISO:    "2024-01-06T12:30:45.123 message"
    - space:  "2024-01-06 12:30:45.123 message"   (line-anchored)

    Returns datetime object or None if no valid timestamp found.
    Falls back to file-pattern-driven custom formats when relpath is given.
    """
    # cspell:ignore sysinv
    if not line:
        return None

    # Cheap prefix guard for built-in formats: sysinv starts with 's',
    # ISO/space both start with a digit.

    # Parse sysinv format: "sysinv YYYY-MM-DD HH:MM:SS.fff"
    if line[0] == 's' and line.startswith('sysinv '):
        match = _RE_SYSINV_TS.search(line)
        if match:
            try:
                return datetime.strptime(
                    match.group(1), '%Y-%m-%d %H:%M:%S.%f')
            except (ValueError, AttributeError):
                pass

    # Parse ISO format: "YYYY-MM-DDTHH:MM:SS.fff" — search anywhere in line
    match = _RE_ISO_TS.search(line)
    if match:
        try:
            return datetime.fromisoformat(match.group(1))
        except (ValueError, AttributeError):
            pass

    # Parse space-separated form: "YYYY-MM-DD HH:MM:SS.fff" — only
    # accepted when it leads the line, which avoids matching in-message
    # date strings.
    match = _RE_SPACE_TS.match(line)
    if match:
        try:
            return datetime.strptime(
                match.group(1), '%Y-%m-%d %H:%M:%S.%f')
        except (ValueError, AttributeError):
            pass

    # Fallback: try custom timestamp formats if relpath provided
    if relpath and _custom_timestamp_formats:
        return _parse_custom_timestamp(line, relpath)
    return None


def manage_peer_controller(variables):
    """Manage peer_controller variable for controller hostname pairs.

    Args:
        variables: Dictionary of variables to update
    """
    if 'hostname' in variables:
        hostname = variables['hostname']
        if hostname == 'controller-0':
            variables['peer_controller'] = 'controller-1'
        elif hostname == 'controller-1':
            variables['peer_controller'] = 'controller-0'


def substitute_variables(text, variables):
    """Substitute variables in text using {varname} syntax.
    Returns text with all {varname} replaced by corresponding values.
    """
    try:
        return text.format(**variables)
    except KeyError as e:
        # print(f"⚠️ Warning: Variable {e} not defined, leaving as-is", file=sys.stderr)
        print(f"⚠️ Warning: Variable {e} not defined, leaving as-is")
        return text


def apply_settings_variable_substitution(settings, variables):
    """Apply variable substitution to settings values.
    Modifies settings in-place.
    """
    if not settings or not variables:
        return

    # Apply substitution to graph setting if present
    if 'graph' in settings and isinstance(settings['graph'], str):
        original_graph = settings['graph']
        settings['graph'] = substitute_variables(settings['graph'], variables)
        vlog2(f"Graph setting substituted: '{original_graph}' -> '{settings['graph']}'")


# Global cache for file date ranges to avoid repeated expensive operations
_file_date_range_cache = {}


# ---------------------------------------------------------------------------
# Permission-error collector
#
# Filesystem traversal (window-model directory walks, per-file opens in
# pattern/pair searches) can hit files or directories the invoking user
# cannot read. Rather than aborting the whole run, the offending path is
# recorded here, excluded from processing, and the full list is displayed
# once at the end of the run. Order-preserving and de-duplicated.
# ---------------------------------------------------------------------------
_permission_errors = []       # list of paths (str) that raised permission errors
_permission_errors_seen = set()  # de-dup guard


def record_permission_error(path):
    """Record a path that could not be accessed due to a permission error.

    De-duplicated and order-preserving. Safe to call from any traversal
    or file-open site; callers should exclude the path and continue.
    """
    if path in _permission_errors_seen:
        return
    _permission_errors_seen.add(path)
    _permission_errors.append(path)


def get_permission_errors():
    """Return the list of paths recorded as permission errors (in order)."""
    return list(_permission_errors)


def clear_permission_errors():
    """Reset the permission-error collector (call at the start of a run)."""
    _permission_errors.clear()
    _permission_errors_seen.clear()


def _walk_permission_onerror(err):
    """os.walk onerror callback: record permission errors, ignore others.

    os.walk passes the OSError raised while scanning a directory. We record
    permission errors (EACCES) so they surface in the end-of-run report;
    other errors are left to os.walk's default (skip) behavior.
    """
    filename = getattr(err, 'filename', None)
    if isinstance(err, PermissionError) and filename:
        record_permission_error(filename)


def get_file_date_range(filepath, relpath=None):
    """Get the date range (first and last timestamps) from a log file.
    Returns (first_timestamp, last_timestamp) or (None, None) if unable to parse.
    Reads first 10 and last 50 lines for efficiency.

    Args:
        filepath: Absolute path to the log file
        relpath: Optional relative path for custom timestamp format matching

    Results are cached to avoid repeated expensive operations on .gz files.
    """
    # Check cache first (skip cache if result was None and we now have
    # relpath for custom format retry)
    if filepath in _file_date_range_cache:
        cached = _file_date_range_cache[filepath]
        if cached[0] is not None or not relpath or not _custom_timestamp_formats:
            return cached

    first_ts = None
    last_ts = None

    try:
        # Handle gzipped files
        is_gzipped = filepath.endswith('.gz')
        if is_gzipped:
            import gzip
            open_func = gzip.open
            mode = 'rt'
        else:
            open_func = open
            mode = 'r'

        with open_func(filepath, mode, encoding='utf-8', errors='ignore') as f:
            # Read first 10 lines to find first timestamp
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                ts = parse_timestamp(line, relpath)
                if ts:
                    first_ts = ts
                    break

            # For last timestamp, read last 50 lines
            if not is_gzipped:
                # For regular files, seek to end and read backwards
                try:
                    f.seek(0, 2)  # Seek to end
                    file_size = f.tell()
                    # Read last ~4KB (enough for ~50 lines)
                    seek_pos = max(0, file_size - 4096)
                    f.seek(seek_pos)
                    lines = f.readlines()
                    # Parse timestamps from end backwards
                    for line in reversed(lines[-50:]):
                        ts = parse_timestamp(line, relpath)
                        if ts:
                            last_ts = ts
                            break
                except (OSError, IOError):
                    pass
            else:
                # For gzipped files, use zcat|tail to read last lines
                # instead of decompressing the entire file in Python.
                try:
                    proc = subprocess.run(
                        ['sh', '-c', f'zcat {shquote(filepath)} | tail -50'],
                        capture_output=True, text=True, timeout=30,
                    )
                    if proc.returncode == 0 and proc.stdout:
                        for line in reversed(proc.stdout.splitlines()):
                            ts = parse_timestamp(line, relpath)
                            if ts:
                                last_ts = ts
                                break
                except (subprocess.TimeoutExpired, OSError):
                    pass

    except PermissionError:
        # Unreadable file probed during smart date-range filtering. Record
        # it so the same file that will be skipped at read time is surfaced
        # in the end-of-run permission report, then fall through to caching
        # (None, None) so it is treated as out-of-range and skipped.
        record_permission_error(filepath)
    except (IOError, OSError):
        pass

    # Cache the result
    _file_date_range_cache[filepath] = (first_ts, last_ts)

    return first_ts, last_ts


def expand_and_sort_log_files(log_dir,
                              file_pattern,
                              start_date=None):
    """Expand wildcard patterns and sort files for optimal search performance.

    For patterns with '*', expands to matching files and sorts them:
    - With start_date: oldest to newest (chronological) so the first block
      finds the earliest match after start_date in rotated files
    - Without start_date: newest to oldest for faster searches
    - Files are annotated with date ranges for smart filtering
    - Files outside the date range can be skipped during search

    Returns list of filenames (not full paths).
    """
    if '*' not in file_pattern:
        return [file_pattern]

    # Expand wildcard
    pattern_path = os.path.join(log_dir, file_pattern)
    matched_files = glob.glob(pattern_path)

    if not matched_files:
        vlog2(f"Warning: No files matched pattern '{file_pattern}'")
        return [file_pattern]  # Return original pattern if no matches

    # Get relative paths, mtimes, and date ranges
    # cspell:ignore mtimes
    file_info = []
    for filepath in matched_files:
        try:
            relpath = os.path.relpath(filepath, log_dir)
        except ValueError:
            relpath = os.path.basename(filepath)
        try:
            mtime = os.path.getmtime(filepath)
            # Get date range if start_date is provided for smart filtering
            if start_date:
                first_ts, last_ts = get_file_date_range(filepath, relpath)
                file_info.append((relpath, mtime, first_ts, last_ts))
            else:
                file_info.append((relpath, mtime, None, None))
        except PermissionError:
            # File matched the glob (directory was listable) but is itself
            # unreadable. Record it so it is reported at end-of-run rather
            # than silently dropped from the search list.
            record_permission_error(filepath)
            continue
        except OSError:
            continue

    if not file_info:
        return [file_pattern]

    # Always sort oldest first (chronological) to ensure pattern matching
    # finds the earliest match within the time window. This is critical for
    # multi-pass analysis where subsequent blocks may match in older files.
    file_info.sort(key=lambda x: x[1])

    sorted_files = [f[0] for f in file_info]

    vlog2(f"Expanded '{file_pattern}' to {len(sorted_files)} files (oldest first): {sorted_files}")

    # If start_date provided, log which files contain the target date range
    if start_date and get_verbose_level() >= 3:
        for relpath, mtime, first_ts, last_ts in file_info:
            if first_ts and last_ts:
                if first_ts <= start_date <= last_ts:
                    vlog3(f"  {relpath}: CONTAINS start_date (range: {first_ts} to {last_ts})")
                elif start_date < first_ts:
                    vlog3(f"  {relpath}: AFTER start_date (range: {first_ts} to {last_ts})")
                else:
                    vlog3(f"  {relpath}: BEFORE start_date (range: {first_ts} to {last_ts})")

    return sorted_files


def find_model_file(model_file):
    """Find model file using prioritized search path.

    Accepts model name with or without .yaml/.yml extension.
    Returns: Full path to model file or None if not found
    """
    # Build list of candidate filenames
    if model_file.endswith(('.yaml', '.yml')):
        candidates = [model_file]
    else:
        candidates = [model_file + '.yaml', model_file + '.yml', model_file]

    # Priority check: If absolute path or contains path separator, use as-is
    if os.path.isabs(model_file):
        for candidate in candidates:
            if os.path.exists(candidate):
                vlog2(f"Found model file (explicit path): {candidate}")
                return candidate
        return None

    # If path contains separator (e.g. helpers/file.yaml), search relative to each search path
    if os.sep in model_file or '/' in model_file:
        for candidate in candidates:
            if os.path.exists(candidate):
                vlog2(f"Found model file (relative path): {candidate}")
                return candidate
        search_paths = get_models_search_paths(0)
        for path in search_paths:
            for candidate in candidates:
                full_path = os.path.join(path, candidate)
                if os.path.exists(full_path):
                    normalized_path = os.path.normpath(full_path)
                    vlog2(f"Found model file: {normalized_path}")
                    return normalized_path
        return None

    # Get search paths using global function
    search_paths = get_models_search_paths(0)

    # Search all paths with all candidates
    for path in search_paths:
        for candidate in candidates:
            full_path = os.path.join(path, candidate)
            if os.path.exists(full_path):
                normalized_path = os.path.normpath(full_path)
                vlog2(f"Found model file: {normalized_path}")
                return normalized_path

    return None


# Valid keys for LPMP model structure validation
_VALID_TOP_KEYS = {'blocks', 'settings', 'include', 'description'}
_VALID_BLOCK_KEYS = {
    'label', 'file', 'patterns', 'start', 'stop', 'timeline',
    'optional', 'present', 'profile', 'controller', 'override',
    'max_time_delta', 'window', 'context', 'fail'
}
_VALID_SETTINGS_KEYS = {
    'max_time_delta', 'block_time_tolerance',
    'start_date', 'stop_date', 'loops', 'max_log_length', 'profile',
    'optional', 'controller', 'graph', 'graph_style', 'host', 'timeline_patterns',
    'script'
}


def validate_model_structure(data):
    """Validate parsed YAML dict against LPMP model format rules.

    Returns: list of error strings (empty = valid model)
    """
    errors = []

    if not isinstance(data, dict):
        return ['model must be a YAML mapping']

    # Check top-level keys
    unknown_top = set(data.keys()) - _VALID_TOP_KEYS
    if unknown_top:
        errors.append(f"unknown top-level keys: {sorted(unknown_top)}")

    # Validate settings keys
    settings = data.get('settings')
    if settings is not None:
        if not isinstance(settings, dict):
            errors.append('settings must be a mapping')
        else:
            unknown_settings = set(settings.keys()) - _VALID_SETTINGS_KEYS
            if unknown_settings:
                errors.append(f"unknown settings keys: {sorted(unknown_settings)}")

    # Validate description: required, must be a non-empty string
    description = data.get('description')
    if description is None:
        errors.append('missing description section')
    elif not isinstance(description, str) or not description.strip():
        errors.append('description must be a non-empty string')

    # Validate blocks
    blocks = data.get('blocks')
    if blocks is None:
        return errors + ['missing blocks section']
    if not isinstance(blocks, list):
        return errors + ['blocks must be a list']
    if not blocks:
        return errors + ['blocks list is empty']

    labels = []
    for idx, block in enumerate(blocks, 1):
        prefix = f"block #{idx}"
        if not isinstance(block, dict):
            errors.append(f"{prefix}: must be a mapping")
            continue

        # Check for unknown block keys
        unknown_block = set(block.keys()) - _VALID_BLOCK_KEYS
        if unknown_block:
            lbl = block.get('label', '?')
            errors.append(f"{prefix} '{lbl}': unknown keys: {sorted(unknown_block)}")

        # Required fields
        if 'label' not in block:
            errors.append(f"{prefix}: missing 'label'")
        else:
            labels.append(block['label'])

        if 'file' not in block:
            lbl = block.get('label', '?')
            errors.append(f"{prefix} '{lbl}': missing 'file'")

        # Block type validation
        has_start = 'start' in block
        has_stop = 'stop' in block
        has_patterns = 'patterns' in block
        has_timeline = 'timeline' in block
        has_window = 'window' in block

        if has_window:
            pass  # window block - collects all timestamped lines
        elif has_timeline:
            pass  # timeline block - ok
        elif has_start or has_stop:
            if has_start and not has_stop:
                lbl = block.get('label', '?')
                errors.append(f"{prefix} '{lbl}': has 'start' but missing 'stop'")
            elif has_stop and not has_start:
                lbl = block.get('label', '?')
                errors.append(f"{prefix} '{lbl}': has 'stop' but missing 'start'")
        elif not has_patterns:
            lbl = block.get('label', '?')
            errors.append(
                f"{prefix} '{lbl}': needs 'patterns', 'start'/'stop', 'timeline', or 'window'"
            )

        # fail-guard validation: 'fail' reverses a pattern block's polarity
        # (matching the pattern fails the run). It is pattern-block only and
        # mutually exclusive with the not-found modifiers.
        if block.get('fail'):
            lbl = block.get('label', '?')
            if not has_patterns:
                errors.append(
                    f"{prefix} '{lbl}': 'fail: true' is only valid on a "
                    f"'patterns' block")
            if has_start or has_stop or has_timeline or has_window:
                errors.append(
                    f"{prefix} '{lbl}': 'fail: true' cannot be combined with "
                    f"'start'/'stop', 'timeline', or 'window'")
            if block.get('optional') or block.get('present'):
                errors.append(
                    f"{prefix} '{lbl}': 'fail: true' cannot be combined with "
                    f"'optional' or 'present'")

    # Duplicate labels
    seen = {}
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
    dupes = [label for label, count in seen.items() if count > 1]
    if dupes:
        errors.append(f"duplicate labels: {dupes}")

    return errors


def validate_model_file(filepath):
    """Validate a YAML model file for list-models display.
    Returns: (valid, status) where:
      valid=True,  status=str   - model type e.g. 'pattern', 'pair', 'timeline'
      valid=True,  status=str   - yaml error detail e.g. 'yaml error: line 66: ...'
      valid=False, status=None  - not an LPMP model (no blocks)
    """
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and 'blocks' in data:
            blocks = data['blocks']
            if isinstance(blocks, list) and blocks:
                errors = validate_model_structure(data)
                if errors:
                    return True, f"format: {errors[0]}"
                return True, detect_model_type(blocks).value
            return True, 'pattern'
        return False, None
    except yaml.YAMLError as e:
        try:
            with open(filepath, 'r') as f:
                if 'blocks:' in f.read():
                    detail = "yaml error"
                    if hasattr(e, 'problem') and hasattr(e, 'problem_mark'):
                        line = e.problem_mark.line + 1
                        detail = f"yaml error: line {line}: {e.problem}"
                    return True, detail
        except Exception:
            pass
        return False, None
    except Exception:
        return False, None


def get_model_description(filepath):
    """Read a model's top-level `description:` value without a full load.

    Returns the description string on success, or an empty string when
    the file is missing, malformed, or has no description key. Used by
    the --list-models desc/description filter to build the flat
    name-plus-description view.
    """
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            desc = data.get('description')
            if isinstance(desc, str):
                return desc.strip()
    except (yaml.YAMLError, IOError, OSError):
        pass
    return ''


def expand_stacked_patterns(blocks):
    """Expand stacked patterns into individual blocks during model loading.

    Transforms pattern blocks with multiple patterns into individual blocks,
    each with a single pattern. This architectural change allows the engine
    to treat each pattern as an independent block, avoiding the all-or-nothing
    behavior of stacked patterns.

    Args:
        blocks: List of block dictionaries from model loading

    Returns:
        List of expanded blocks where stacked patterns become individual blocks

    Behavior:
        - Single pattern blocks: unchanged
        - Multi-pattern blocks: expanded to individual blocks with labels "original_label_1", "original_label_2", etc.
        - All block properties preserved except patterns list
        - Non-pattern blocks (pair, timeline): unchanged
        - Mixed model trigger patterns: NEVER expanded (validation will catch this as an error)

    Mixed Model Restriction:
        Mixed models are PAIR models with a single trigger pattern block as the first block.
        The trigger pattern block CANNOT be a stacked pattern block - this is validated
        separately and will cause model loading to fail.
    """
    expanded_blocks = []

    for block in blocks:
        # Only expand pattern blocks with multiple patterns
        if 'patterns' in block and isinstance(block['patterns'], list) and len(block['patterns']) > 1:
            original_label = block['label']
            vlog3(f"Expanding stacked pattern block '{original_label}' with {len(block['patterns'])} patterns")

            # Create individual blocks for each pattern
            for i, pattern in enumerate(block['patterns'], 1):
                # Create new block with single pattern
                expanded_block = block.copy()  # Shallow copy preserves all properties
                expanded_block['label'] = f"{original_label}_{i}"
                expanded_block['patterns'] = [pattern]  # Single pattern list

                expanded_blocks.append(expanded_block)
                vlog3(f"  Created block '{expanded_block['label']}' with pattern: {pattern}")
        else:
            # Single pattern, pair, or timeline block - keep as-is
            expanded_blocks.append(block)

    return expanded_blocks


def load_model(model_file):
    """Load YAML model file containing search patterns and optional settings.

    Returns (blocks, settings) where:
    - blocks: List of search blocks with label, file, and patterns
    - settings: Dict with optional start_date, loops, max_log_length, graph

    Note: Wildcard expansion is deferred until processing time when start_date is known.
    Validates that block labels are unique.
    """
    def _load_yaml_file(path):
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except ImportError:
            print("Error: PyYAML is required. Install with: pip3 install --user pyyaml", file=sys.stderr)
            sys.exit(1)
        except FileNotFoundError:
            print(f"Error: Model file '{path}' not found", file=sys.stderr)
            print("Use --help-model for model file format information", file=sys.stderr)
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"Error: Invalid YAML syntax in '{path}': {e}", file=sys.stderr)
            print("Use --help-model for model file format information", file=sys.stderr)
            sys.exit(1)

    data = _load_yaml_file(model_file)

    # Validate model file has content
    if not data:
        print(f"Error: Model file '{model_file}' is empty", file=sys.stderr)
        print("Use --help-model for model file format information", file=sys.stderr)
        sys.exit(1)

    # Merge settings from included file(s) if present
    include_value = data.get('include')
    if include_value:
        include_files = include_value if isinstance(include_value, list) else [include_value]
        merged_settings = {}
        for include_name in include_files:
            # First try relative to model file directory (for compatibility)
            include_path = None
            if not os.path.isabs(include_name) and os.sep not in include_name:
                # Try relative to model file first
                model_dir_path = os.path.join(os.path.dirname(model_file), include_name)
                if os.path.exists(model_dir_path):
                    include_path = model_dir_path

            # If not found relative to model, use find_model_file to search standard paths
            if include_path is None:
                include_path = find_model_file(include_name)
                if include_path is None:
                    print(f"Error: Include file '{include_name}' not found in search paths", file=sys.stderr)
                    print(
                        "  Searched: <tool_dir>/models/, <tool_dir>/models/helpers/, "
                        "./models/, /etc/lpmp.d/, /var/lib/lpmp_models/, ./",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            include_data = _load_yaml_file(include_path)
            if not include_data:
                continue
            include_settings = include_data.get('settings', {})
            if include_settings:
                timeline_patterns = include_settings.get('timeline_patterns', {})
                if timeline_patterns:
                    merged_tp = merged_settings.get('timeline_patterns', {})
                    merged_tp.update(timeline_patterns)
                    merged_settings['timeline_patterns'] = merged_tp
                for key, value in include_settings.items():
                    if key == 'timeline_patterns':
                        continue
                    merged_settings[key] = value

        local_settings = data.get('settings', {})
        if local_settings:
            local_tp = local_settings.get('timeline_patterns', {})
            if local_tp:
                merged_tp = merged_settings.get('timeline_patterns', {})
                merged_tp.update(local_tp)
                merged_settings['timeline_patterns'] = merged_tp
            for key, value in local_settings.items():
                if key == 'timeline_patterns':
                    continue
                merged_settings[key] = value

        if merged_settings:
            data['settings'] = merged_settings

    # Validate 'description' section exists (required, non-empty string)
    if 'description' not in data:
        print(f"Error: Model file '{model_file}' missing required 'description:' section",
              file=sys.stderr)
        print("Use --help-model for model file format information", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data['description'], str) or not data['description'].strip():
        print(f"Error: 'description' must be a non-empty string in '{model_file}'",
              file=sys.stderr)
        print("Use --help-model for model file format information", file=sys.stderr)
        sys.exit(1)

    # Validate 'blocks' section exists
    if 'blocks' not in data:
        print(f"Error: Model file '{model_file}' missing required 'blocks:' section",
              file=sys.stderr)
        print("Use --help-model for model file format information", file=sys.stderr)
        sys.exit(1)

    # Validate blocks is a list
    if not isinstance(data['blocks'], list):
        print(f"Error: 'blocks' must be a list in '{model_file}'", file=sys.stderr)
        print("Use --help-model for model file format information", file=sys.stderr)
        sys.exit(1)

    # Validate blocks list is not empty
    if len(data['blocks']) == 0:
        print(f"Error: 'blocks' list is empty in '{model_file}'", file=sys.stderr)
        print("Use --help-model for model file format information", file=sys.stderr)
        sys.exit(1)

    blocks = []
    # Load optional settings first to use for profile and optional defaults
    settings = data.get('settings', {})

    for idx, block_data in enumerate(data['blocks'], 1):
        # Validate block is a dictionary
        if not isinstance(block_data, dict):
            print(f"Error: Block #{idx} must be a dictionary in '{model_file}'", file=sys.stderr)
            print("Use --help-model for model file format information", file=sys.stderr)
            sys.exit(1)

        # Check for required 'label' field
        if 'label' not in block_data:
            print(f"Error: Block #{idx} missing required 'label' field in '{model_file}'",
                  file=sys.stderr)
            print("Use --help-model for model file format information", file=sys.stderr)
            sys.exit(1)

        # Check for required 'file' field
        if 'file' not in block_data:
            print(f"Error: Block #{idx} ('{block_data.get('label', 'unknown')}') "
                  f"missing required 'file' field in '{model_file}'", file=sys.stderr)
            print("Use --help-model for model file format information", file=sys.stderr)
            sys.exit(1)

        # Get profile setting (block-level or from settings)
        profile_enabled = block_data.get('profile', settings.get('profile', False))

        # Get optional setting (block-level or from settings)
        optional_enabled = block_data.get('optional', settings.get('optional', False))

        # Get controller setting (block-level or from settings)
        controller_enabled = block_data.get('controller', settings.get('controller', False))

        # Get fail-guard setting (block-level only). 'fail: true' reverses a
        # pattern block's polarity: matching the pattern fails the run. It is
        # pattern-block only and mutually exclusive with optional/present.
        fail_enabled = block_data.get('fail', False)
        if fail_enabled:
            if 'patterns' not in block_data:
                print(f"Error: Block #{idx} ('{block_data['label']}') 'fail: true' "
                      f"is only valid on a 'patterns' block in '{model_file}'",
                      file=sys.stderr)
                print("Use --help-model for model file format information", file=sys.stderr)
                sys.exit(1)
            if block_data.get('optional') or block_data.get('present'):
                print(f"Error: Block #{idx} ('{block_data['label']}') 'fail: true' "
                      f"cannot be combined with 'optional' or 'present' in "
                      f"'{model_file}'", file=sys.stderr)
                print("Use --help-model for model file format information", file=sys.stderr)
                sys.exit(1)

        # Parse context setting: int N -> (N, N), list [B, A] -> (B, A), absent -> None
        context_raw = block_data.get('context')
        context_before = None
        context_after = None
        if context_raw is not None:
            if isinstance(context_raw, int):
                context_before = context_raw
                context_after = context_raw
            elif isinstance(context_raw, list) and len(context_raw) == 2:
                context_before = int(context_raw[0])
                context_after = int(context_raw[1])
            else:
                print(
                    f"Error: Block #{idx} ('{block_data.get('label', '?')}') "
                    f"'context' must be an integer or [before, after] list",
                    file=sys.stderr)
                sys.exit(1)

        # Determine block type and validate accordingly
        has_start = 'start' in block_data
        has_stop = 'stop' in block_data
        has_patterns = 'patterns' in block_data
        has_timeline = 'timeline' in block_data
        has_window = block_data.get('window', False)

        # Validate window block (timeline variant, no patterns)
        if has_window:
            block = {
                'label': block_data['label'],
                'file': block_data['file'],
                'window': True,
                'timeline': '.*',
                'optional': optional_enabled,
                'profile': profile_enabled,
                'controller': controller_enabled,
                'present': block_data.get('present', False)
            }
        # Validate timeline block
        elif has_timeline:
            # Timeline block
            block = {
                'label': block_data['label'],
                'file': block_data['file'],
                'timeline': block_data['timeline'],
                'optional': optional_enabled,
                'profile': profile_enabled,
                'controller': controller_enabled,
                'present': block_data.get('present', False)
            }
            # Add override field if present
            if 'override' in block_data:
                block['override'] = block_data['override']
        # Validate pair block (start/stop)
        elif has_start or has_stop:
            if has_start and not has_stop:
                print(f"Error: Block #{idx} ('{block_data['label']}') has 'start' "
                      f"but missing 'stop' field in '{model_file}'", file=sys.stderr)
                print("Pair blocks require both 'start' and 'stop' fields", file=sys.stderr)
                print("Use --help-model for model file format information", file=sys.stderr)
                sys.exit(1)
            if has_stop and not has_start:
                print(f"Error: Block #{idx} ('{block_data['label']}') has 'stop' "
                      f"but missing 'start' field in '{model_file}'", file=sys.stderr)
                print("Pair blocks require both 'start' and 'stop' fields", file=sys.stderr)
                print("Use --help-model for model file format information", file=sys.stderr)
                sys.exit(1)
            # Valid pair block
            block = {
                'label': block_data['label'],
                'file': block_data['file'],
                'start': block_data['start'],
                'stop': block_data['stop'],
                'optional': optional_enabled,
                'profile': profile_enabled,
                'controller': controller_enabled,
                'present': block_data.get('present', False)
            }
            # Add max_time_delta only if explicitly set in YAML
            if 'max_time_delta' in block_data:
                block['max_time_delta'] = block_data['max_time_delta']
            # Add override field if present
            if 'override' in block_data:
                block['override'] = block_data['override']
        elif has_patterns:
            # Pattern block
            block = {
                'label': block_data['label'],
                'file': block_data['file'],
                'patterns': block_data['patterns'],
                'optional': optional_enabled,
                'profile': profile_enabled,
                'controller': controller_enabled,
                'present': block_data.get('present', False),
                'fail': fail_enabled
            }
            # Add max_time_delta only if explicitly set in YAML
            if 'max_time_delta' in block_data:
                block['max_time_delta'] = block_data['max_time_delta']
            # Add override field if present
            if 'override' in block_data:
                block['override'] = block_data['override']
        else:
            # Neither window, timeline, pair, nor pattern block
            print(
                f"Error: Block #{idx} ('{block_data['label']}') must have "
                f"'window', 'timeline', 'patterns', or 'start'/'stop' in '{model_file}'",
                file=sys.stderr)
            print("Use --help-model for model file format information", file=sys.stderr)
            sys.exit(1)

        # Add context setting if present (timeline and pattern blocks only)
        if context_before is not None:
            if 'start' in block and 'stop' in block:
                print(
                    f"Warning: Block #{idx} ('{block['label']}') "
                    f"'context' is not supported for pair blocks, ignoring")
            else:
                block['context_before'] = context_before
                block['context_after'] = context_after

        vlog3(f"Block Label: {block['label']}")
        vlog3(f"Log File: {block['file']}")
        if has_window:
            vlog3("Window block: collect all timestamped lines")
        elif 'start' in block and 'stop' in block:
            vlog3(f"Start Pattern: {block['start']}")
            vlog3(f"Stop Pattern: {block['stop']}")
        elif 'timeline' in block:
            vlog3(f"Timeline Patterns: {block['timeline']}")
        else:
            vlog3(f"Patterns: {block['patterns']}")

        blocks.append(block)

    # Expand stacked patterns into individual blocks BEFORE validation
    blocks = expand_stacked_patterns(blocks)
    vlog3(f"After expansion: {len(blocks)} total blocks")

    # Show expanded model at vlog2 level
    if get_verbose_level() >= 2:
        vlog2(f"Loaded model with {len(blocks)} blocks:")
        for i, block in enumerate(blocks):
            vlog2(f"  Block {i + 1}: {block.get('label', 'unlabeled')} - {block.get('file', 'no file')}")

    # Validate unique block labels (exact match) - check expanded blocks
    label_map = {}
    for idx, block in enumerate(blocks, 1):
        label = block['label']
        label_map.setdefault(label, []).append(idx)

    # cspell:ignore idxs
    duplicates = {label: idxs for label, idxs in label_map.items() if len(idxs) > 1}
    if duplicates:
        details = []
        for label, idxs in duplicates.items():
            details.append(f"{label!r} at blocks {idxs}")
        print(f"Error: Duplicate block labels found in '{model_file}':", file=sys.stderr)
        for line in details:
            print(f"  - {line}", file=sys.stderr)
        print("Each block must have a unique label (exact match).", file=sys.stderr)
        sys.exit(1)

    # Validate timeline model consistency
    timeline_blocks = []
    non_timeline_blocks = []
    pair_blocks = []
    pattern_blocks = []

    for idx, block in enumerate(blocks, 1):
        if 'timeline' in block:
            timeline_blocks.append(idx)
        elif 'start' in block and 'stop' in block:
            pair_blocks.append(idx)
            non_timeline_blocks.append(idx)
        elif 'patterns' in block:
            pattern_blocks.append(idx)
            non_timeline_blocks.append(idx)
        else:
            non_timeline_blocks.append(idx)

    # If some blocks have timeline but not all, error out
    if timeline_blocks and non_timeline_blocks:
        print("Error: all blocks in a timeline model must have the timeline label.", file=sys.stderr)
        sys.exit(1)

    # Load optional settings (already loaded above for profile defaults)
    if settings:
        vlog2(f"Global settings: {settings}")

    model_type = detect_model_type(blocks)
    return blocks, settings, model_type


def create_output_directory(args, run_start_time, hostname=None,
                            extra_dir=None, dir_name=None):
    """Build (and create) the output directory for a run.

    Args:
        extra_dir: optional extra path segment inserted between the
            top-level prefix and the run directory. Batch mode uses
            this for its 'tool runtime' directory level (see
            lpmp_batch.py), so the layout becomes
            '<prefix>/<extra_dir>/<run_dir>' instead of the mainline
            '<prefix>/<run_dir>'. Ignored (None) for mainline runs.
        dir_name: optional override for the run directory's own name.
            Defaults to '<timestamp>_<model>' when not given.
    """
    # Top-level directory prefix. Callers may set `args._dir_prefix`
    # to override the default 'lpmp_<lab>'; batch mode uses this to
    # emit 'lpmp_batch_<lab>' so the layout is visibly distinct from
    # mainline runs sharing the same lab name.
    dir_prefix = getattr(args, '_dir_prefix', None) or f"lpmp_{args.lab_name}"

    model_name = os.path.splitext(os.path.basename(args.model_file))[0]
    time_str = run_start_time.strftime("%Y%m%d_%H%M%S")
    run_dir_name = dir_name or f"{time_str}_{model_name}"

    if args.output:
        # Detect if output is current directory and skip creation
        if args.output == '.' or os.path.abspath(args.output) == os.getcwd():
            if hostname:
                output_dir = hostname
            else:
                output_dir = '.'
            return ensure_output_dir(output_dir) if output_dir != '.' else '.'

        # Maintain <prefix>[/<extra_dir>]/<run_dir_name> under -o path
        # (bundle and non-bundle).
        path_parts = [args.output, dir_prefix]
        if extra_dir:
            path_parts.append(extra_dir)
        path_parts.append(run_dir_name)
        base_dir = os.path.join(*path_parts)
        output_dir = base_dir
        if hostname:
            output_dir = os.path.join(base_dir, hostname)
    else:
        # Use bundle directory as base in bundle mode, otherwise current directory
        if hasattr(args, 'bundle_name') and args.bundle_name != '/':
            base_path = args.bundle_name
        else:
            base_path = os.getcwd()

        path_parts = [base_path, dir_prefix]
        if extra_dir:
            path_parts.append(extra_dir)
        path_parts.append(run_dir_name)
        base_dir = os.path.join(*path_parts)
        if hostname:
            output_dir = os.path.join(base_dir, hostname)
        else:
            output_dir = base_dir

    return ensure_output_dir(output_dir)


def parse_duration_to_seconds(duration_text):
    """Parse HH:MM:SS.xxx into seconds."""
    try:
        parts = duration_text.strip().split(':')
        if len(parts) != 3:
            return None
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except (ValueError, IndexError):
        return None


def format_duration(seconds):
    """Convert seconds to HH:MM:SS.xxx format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def sanitize_label_for_filename(label):
    """Convert a block label to a safe filename segment."""
    cleaned = re.sub(r'\s+', '_', str(label).strip())
    # Replace path separators and backslashes with underscores
    cleaned = cleaned.replace(os.sep, '_')
    cleaned = cleaned.replace('\\', '_')
    cleaned = cleaned.replace('/', '_')
    if os.altsep:
        cleaned = cleaned.replace(os.altsep, '_')
    return cleaned if cleaned else "block"


def ensure_output_dir(path):
    """Create output directory if it doesn't exist.

    Raises:
        PermissionError: If insufficient permissions to create directory
        OSError: If disk is full or filesystem is read-only
        ValueError: If path contains invalid characters
    """
    try:
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except PermissionError as e:
                print(f"Error: Permission denied creating output directory '{path}': {e}", file=sys.stderr)
                print("Check that you have write permissions to the parent directory", file=sys.stderr)
                raise
            except OSError as e:
                if "No space left on device" in str(e):
                    print(f"Error: Disk full - cannot create output directory '{path}': {e}", file=sys.stderr)
                    print("Free up disk space and try again", file=sys.stderr)
                elif "Read-only file system" in str(e):
                    print(f"Error: Cannot create directory on read-only filesystem '{path}': {e}", file=sys.stderr)
                    print("Choose a different output location with write permissions", file=sys.stderr)
                else:
                    print(f"Error: Cannot create output directory '{path}': {e}", file=sys.stderr)
                raise
            except ValueError as e:
                print(f"Error: Invalid characters in output path '{path}': {e}", file=sys.stderr)
                print("Use a path without null bytes or other invalid characters", file=sys.stderr)
                raise

        return path
    except Exception as e:
        # Catch any other unexpected errors
        print(f"Error: Unexpected error creating output directory '{path}': {e}", file=sys.stderr)
        raise


def prune_empty_output_dirs(root):
    """Walk `root` bottom-up and remove any empty subdirectories.

    `os.rmdir` only succeeds when a directory is empty, so this is a
    safe cleanup: subtrees that produced output are left untouched,
    and only the empty per-host or per-model dirs from zero-match
    runs get removed. Silently ignores directories that are already
    gone, still populated, or unwritable.
    """
    if not root or not os.path.isdir(root):
        return
    for dirpath, _dirs, _files in os.walk(root, topdown=False):
        try:
            os.rmdir(dirpath)
        except OSError:
            # Not empty, or removed under us, or permission issue —
            # any of those are fine: leave the dir alone.
            pass


def format_result_line(
    delta_formatted,
    label_padded,
    filename_padded,
    data,
    hostname=None,
):
    """Format a single output line with optional hostname column."""
    # Import constants from main module
    if hostname:
        return f"{delta_formatted:>12}\t{hostname:<12}\t{label_padded}\t{filename_padded:<30}\t{data}"
    else:
        return f"{delta_formatted:>12}\t{label_padded}\t{filename_padded:<30}\t{data}"


def extract_model_info(log_dir):
    """Extract model information from logs containing "manufacturer is".
    Returns model info string or empty string if not found.
    """
    # Log files that contain manufacturer information
    MANUFACTURER_LOG_FILES = ['mtcAgent.log.1.gz', 'mtcAgent.log']

    for filename in MANUFACTURER_LOG_FILES:
        filepath = os.path.join(log_dir, filename)
        if not os.path.exists(filepath):
            continue

        try:
            with open(filepath, 'r') as f:
                for line in f:
                    if "manufacturer is" in line:
                        # Extract everything after "model:" to end of line
                        match = re.search(r'model:(.+)', line)
                        if match:
                            model_info = match.group(1).strip()
                            vlog4(f"Found model info: {model_info}")
                            return f"model:{model_info}"
        except (IOError, OSError) as e:
            vlog3(f"Error reading {filename}: {e}")
            continue

    return ""


def format_log_line_for_output(log_line, filename):
    """Format log line for output, removing 'sysinv ' prefix from sysinv.log
    files to align timestamps properly while preserving space between
    date and time.
    """
    if filename.startswith('sysinv.log') and \
            log_line.startswith('sysinv '):
        # Remove 'sysinv ' prefix but keep the space between date and time
        return log_line[7:]  # Remove first 7 characters: 'sysinv '
    return log_line


def apply_timeline_variable_substitution(timeline_patterns, variables):
    """Apply variable substitution to timeline patterns.
    Returns new timeline patterns with variables substituted.
    """
    if isinstance(timeline_patterns, list):
        result = []
        for pattern in timeline_patterns:
            if isinstance(pattern, list):
                # Handle nested lists (OR patterns)
                result.append([substitute_variables(p, variables) for p in pattern])
            else:
                # Handle single patterns
                result.append(substitute_variables(pattern, variables))
        return result
    elif isinstance(timeline_patterns, str):
        return substitute_variables(timeline_patterns, variables)
    return timeline_patterns


def resolve_timeline_patterns(timeline_ref, settings):
    """Resolve timeline pattern reference to actual pattern list.

    Timeline patterns can be specified in three ways:
    1. Direct list: ["pattern1", "pattern2", "pattern3"]
    2. Named reference: "{maintenance}" - references settings.timeline_patterns.maintenance
    3. Single string: "single_pattern" - converted to single-item list

    Args:
        timeline_ref: Timeline specification from YAML (list, string, or named reference)
        settings: Model settings dictionary containing timeline_patterns

    Returns:
        List of pattern strings to search for

    Note:
        - Pattern order is irrelevant - all matches are collected and sorted by timestamp
        - Named references must exist in settings.timeline_patterns or tool will exit
        - All patterns support full regex syntax
    """
    if isinstance(timeline_ref, list):
        # Direct list of patterns
        return timeline_ref

    if isinstance(timeline_ref, str) and timeline_ref.startswith('{') and timeline_ref.endswith('}'):
        # Named reference like '{maintenance}'
        pattern_name = timeline_ref[1:-1]  # Remove { }
        timeline_patterns = settings.get('timeline_patterns', {})

        if pattern_name in timeline_patterns:
            vlog2(f"Resolved timeline reference '{timeline_ref}' to {len(timeline_patterns[pattern_name])} patterns")
            return timeline_patterns[pattern_name]
        else:
            print(f"Error: Timeline pattern '{pattern_name}' not found in settings.timeline_patterns", file=sys.stderr)
            sys.exit(1)

    # Single string pattern
    return [timeline_ref]


def expand_wildcards_in_blocks(blocks,
                               log_dir,
                               start_date=None,
                               stop_date=None):
    """Expand wildcard patterns in block file specifications.
    Modifies blocks in-place, replacing wildcards with sorted file lists.
    When start_date or stop_date are provided, prunes files entirely outside
    the global date window to avoid repeated per-call filtering.
    """
    for block in blocks:
        file_spec = block['file']

        # Preserve the original model file spec (globs intact, e.g.
        # 'daemon.log*') before it is overwritten with the expanded
        # concrete file list. Used for not-found error/warning messages so
        # they reference the model's pattern rather than a resolved name.
        # Guard against re-entry so a second expansion pass can't overwrite
        # the original with an already-expanded list.
        if 'file_spec' not in block:
            block['file_spec'] = file_spec

        # Window blocks: use recursive expansion into subdirectories
        if block.get('window'):
            patterns = file_spec if isinstance(file_spec, list) else [file_spec]
            all_paths = _expand_window_globs(log_dir, patterns)
            # Filter out directories, ignored, and binary files; then
            # apply rotation-aware pruning so .gz files that are older
            # than a sibling already outside the window are skipped
            # without the expensive get_file_date_range call.
            candidates = []
            for f in all_paths:
                if os.path.isdir(f):
                    continue
                rel = os.path.relpath(f, log_dir)
                if is_ignored_path(rel) or _is_skippable_file(f):
                    continue
                candidates.append(f)
            if start_date:
                candidates = _rotation_prune(candidates, log_dir, start_date)
            block['file'] = [
                os.path.relpath(f, log_dir) for f in candidates
            ]
        elif isinstance(file_spec, list):
            # List of files - expand each that contains wildcard
            expanded = []
            for f in file_spec:
                if '*' in f:
                    expanded.extend(expand_and_sort_log_files(
                        log_dir, f, start_date))
                else:
                    expanded.append(f)
            block['file'] = expanded
        elif isinstance(file_spec, str) and '*' in file_spec:
            # Single file with wildcard
            block['file'] = expand_and_sort_log_files(
                log_dir, file_spec, start_date)

        # Prune files outside the global date window
        if start_date or stop_date:
            file_list = block['file'] if isinstance(block['file'], list) else [block['file']]
            pruned = []
            for f in file_list:
                filepath = os.path.join(log_dir, f)
                if not os.path.exists(filepath):
                    pruned.append(f)
                    continue
                first_ts, last_ts = get_file_date_range(filepath, f)
                if first_ts and last_ts:
                    if start_date and last_ts < start_date:
                        vlog3(f"Pruning {f}: file ends {last_ts} before start_date {start_date}")
                        continue
                    if stop_date and first_ts > stop_date:
                        vlog3(f"Pruning {f}: file starts {first_ts} after stop_date {stop_date}")
                        continue
                pruned.append(f)
            if isinstance(block['file'], list):
                block['file'] = pruned
            elif pruned:
                block['file'] = pruned

        vlog2(f"Block '{block['label']}' expanded files: {block['file']}")


def print_output_files(bundle_base_dir):
    """Print full paths to all output files."""
    if not os.path.exists(bundle_base_dir):
        return

    print("\nOutput files:")

    def _collect_files(path):
        files = []
        if not os.path.exists(path):
            return files

        try:
            for root, dirs, filenames in os.walk(path):
                for filename in sorted(filenames):
                    file_path = os.path.join(root, filename)
                    files.append(file_path)
        except PermissionError:
            vlog1(f"Permission denied accessing: {path}")

        return files

    all_files = _collect_files(bundle_base_dir)
    for file_path in sorted(all_files):
        print(file_path)


def format_long_listing(path):
    """Return a list of strings mimicking `ls -lrt <path>` for the
    immediate children of `path` (no recursion into subdirectories).

    Entries are sorted oldest-modified-first, matching `ls -lrt`'s
    reverse-of-default time order, so the entries touched most
    recently by the run that just finished sort to the bottom.
    Falls back to a numeric uid/gid when the `pwd`/`grp` modules are
    unavailable or the id has no passwd/group entry (e.g. running as
    an id with no local account).

    Returns an empty list if `path` doesn't exist or isn't a
    directory.
    """
    if not path or not os.path.isdir(path):
        return []

    try:
        with os.scandir(path) as it:
            entries = []
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                entries.append((entry.name, st))
    except OSError:
        return []

    if not entries:
        return ["total 0"]

    entries.sort(key=lambda e: e[1].st_mtime)

    def _owner(uid):
        try:
            import pwd
            return pwd.getpwuid(uid).pw_name
        except (ImportError, KeyError, OSError):
            return str(uid)

    def _group(gid):
        try:
            import grp
            return grp.getgrgid(gid).gr_name
        except (ImportError, KeyError, OSError):
            return str(gid)

    import stat as stat_module

    rows = []
    for name, st in entries:
        mode_str = stat_module.filemode(st.st_mode)
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%b %d %H:%M")
        rows.append((
            mode_str, st.st_nlink, _owner(st.st_uid), _group(st.st_gid),
            st.st_size, mtime, name,
        ))

    nlink_w = max(len(str(r[1])) for r in rows)
    owner_w = max(len(r[2]) for r in rows)
    group_w = max(len(r[3]) for r in rows)
    size_w = max(len(str(r[4])) for r in rows)

    # st_blocks is in 512-byte units; ls reports "total" in 1024-byte
    # blocks, hence the //2. Not available on all platforms.
    total_blocks = sum(getattr(st, 'st_blocks', 0) for _, st in entries) // 2

    lines = [f"total {total_blocks}"]
    for mode_str, nlink, owner, group, size, mtime, name in rows:
        lines.append(
            f"{mode_str} {nlink:>{nlink_w}} {owner:<{owner_w}} "
            f"{group:<{group_w}} {size:>{size_w}} {mtime} {name}"
        )
    return lines


def get_help_section(section_name):
    """Extract help section content from lpmptool script docstring."""
    # Find the lpmptool script
    # cspell:ignore lpmptool
    script_path = sys.argv[0] if sys.argv else None
    if not script_path or not os.path.exists(script_path):
        # Fallback to searching for lpmptool
        for path in ['/usr/local/bin/lpmptool', './lpmptool', 'lpmptool']:
            if os.path.exists(path):
                script_path = path
                break

    if script_path and os.path.exists(script_path):
        try:
            with open(script_path, 'r') as f:
                content = f.read()
            pattern = f"# HELP_SECTION: {section_name}(.*?)# END_HELP_SECTION: {section_name}"
            match = re.search(pattern, content, re.DOTALL)
            if match:
                return match.group(1).strip()
        except IOError:
            pass

    return f"Help section '{section_name}' not found"


def verify_timeline_bounds(timeline_path, start_date=None, stop_date=None):
    """Verify a timeline file contains no log entries outside the time bounds.

    Scans the timeline file for timestamps and checks they fall within
    [start_date, stop_date]. Reports a single pass/fail line with the
    effective time range.

    Args:
        timeline_path: Path to a .timeline.log file
        start_date: Start datetime bound (None = use earliest entry)
        stop_date: Stop datetime bound (None = use latest entry)
    """
    if not os.path.exists(timeline_path):
        return

    ts_re = re.compile(r'\t(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\s')
    earliest = None
    latest = None
    violations = 0

    with open(timeline_path, 'r') as f:
        for line in f:
            m = ts_re.search(line)
            if not m:
                continue
            ts = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S.%f")
            if earliest is None or ts < earliest:
                earliest = ts
            if latest is None or ts > latest:
                latest = ts
            if start_date and ts < start_date:
                violations += 1
            if stop_date and ts > stop_date:
                violations += 1

    if earliest is None:
        return

    fmt = "%Y-%m-%dT%H:%M:%S.%f"
    bound_start = (start_date.strftime(fmt)[:-3] if start_date
                   else earliest.strftime(fmt)[:-3])
    bound_stop = (stop_date.strftime(fmt)[:-3] if stop_date
                  else latest.strftime(fmt)[:-3])
    fname = os.path.basename(timeline_path)

    if violations == 0:
        print(f"\n✅ {fname} adheres to time bounds [{bound_start} .. {bound_stop}]")
    else:
        print(f"\n❌ {fname} has {violations} entries outside [{bound_start} .. {bound_stop}]")


# ---------------------------------------------------------------------------
# Window model helpers
# ---------------------------------------------------------------------------

# Files to skip in window mode (binary, database, non-log)
_WINDOW_SKIP_BASENAMES = {
    'btmp', 'wtmp', 'lastlog', 'faillog', 'tallylog',
    'utmp', 'dmesg', 'boot.log',
}
_WINDOW_SKIP_EXTENSIONS = {
    '.db', '.sqlite', '.journal', '.pid', '.lock',
    '.png', '.jpg', '.gif', '.ico', '.bin', '.dat',
    # Package/installer/archive formats — never log files
    # NOTE: .gz is intentionally excluded — rotated logs use .gz
    '.filez', '.so', '.a', '.o', '.pyc', '.pyo',
    '.tar', '.tgz', '.tbz', '.tbz2', '.txz',
    '.zip', '.bz2', '.xz', '.7z', '.rar',
    '.deb', '.rpm', '.iso', '.img', '.vmdk',
    '.elf', '.exe', '.dll', '.dylib',
    '.jpeg', '.bmp', '.svg', '.tiff',
    '.mp3', '.mp4', '.avi', '.mov',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
}


def _is_skippable_file(filepath):
    """Return True if filepath should be skipped in window mode."""
    basename = os.path.basename(filepath)
    if basename in _WINDOW_SKIP_BASENAMES:
        return True
    _, ext = os.path.splitext(basename)
    if ext in _WINDOW_SKIP_EXTENSIONS:
        return True
    # Skip files that look binary (check first 512 bytes)
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(512)
        if b'\x00' in chunk:
            return True
    except PermissionError:
        # Unreadable file (window mode): record it for the end-of-run
        # report before skipping, so it is surfaced rather than silently
        # dropped as "looks binary".
        record_permission_error(filepath)
        return True
    except (IOError, OSError):
        return True
    return False


def _expand_window_globs(log_dir, file_patterns):
    """Expand glob patterns for window models, including subdirectories.

    For each pattern, first does a normal glob in log_dir, then walks
    all subdirectories and applies the same basename pattern there.
    Prunes directories that match the file ignore list.
    Returns a list of absolute file paths (deduplicated).
    """
    if isinstance(file_patterns, str):
        file_patterns = [file_patterns]

    all_files = set()
    for pattern in file_patterns:
        # Normal top-level glob
        if '*' in pattern:
            for f in glob.glob(os.path.join(log_dir, pattern)):
                all_files.add(f)
            # Walk subdirectories with the same pattern. os.walk swallows
            # directory-access errors by default; the onerror callback lets
            # us record unreadable directories instead of losing them.
            for root, dirs, files in os.walk(log_dir, onerror=_walk_permission_onerror):
                if root == log_dir:
                    continue
                # Prune ignored directories
                relroot = os.path.relpath(root, log_dir)
                if is_ignored_path(relroot + '/'):
                    dirs.clear()
                    continue
                for f in glob.glob(os.path.join(root, pattern)):
                    all_files.add(f)
        else:
            full = os.path.join(log_dir, pattern)
            if os.path.exists(full):
                all_files.add(full)

    return sorted(all_files)


# Regex to extract base name and rotation number from rotated log files.
# Matches patterns like "name.N.gz" or "name.N" where N is the rotation number.
_RE_ROTATION = re.compile(r'^(.+)\.(\d+)(\.gz)?$')


def _rotation_prune(filepaths, log_dir, start_date):
    """Remove .gz files whose rotation siblings are before start_date.

    Groups .gz files by base name, processes lowest rotation first.
    Once a rotation's last_ts < start_date, all higher rotations of
    the same base are dropped without reading them.
    Non-.gz files pass through unchanged.

    Returns filtered list of filepaths.
    """
    gz_by_base = {}   # base -> [(rotation_num, filepath)]
    result = []

    for fp in filepaths:
        rel = os.path.relpath(fp, log_dir)
        if fp.endswith('.gz'):
            m = _RE_ROTATION.match(rel)
            if m:
                base = m.group(1)
                rot_num = int(m.group(2))
                gz_by_base.setdefault(base, []).append((rot_num, fp))
                continue
        result.append(fp)

    for base in gz_by_base:
        gz_by_base[base].sort(key=lambda x: x[0])

    before_window = set()
    for base, rotations in gz_by_base.items():
        for rot_num, fp in rotations:
            if base in before_window:
                continue  # skip — older rotation already before window
            rel = os.path.relpath(fp, log_dir)
            first_ts, last_ts = get_file_date_range(fp, rel)
            if first_ts is None:
                continue
            if last_ts is None:
                last_ts = first_ts
            if last_ts < start_date:
                before_window.add(base)
                continue
            result.append(fp)

    return result


def discover_window_files(log_dir, file_patterns, start_date=None,
                          stop_date=None):
    """Discover and classify files for window model processing.

    Searches log_dir and all subdirectories for matching files.
    Uses rotation-aware skipping for .gz files: once a rotation is
    found to be entirely before the time window, all higher-numbered
    rotations of the same base log are skipped without reading them.

    Returns:
        matched: list of (filename, first_ts, last_ts) tuples for files in range
        skipped: list of (filename, reason) tuples for skipped files
    """
    all_files = _expand_window_globs(log_dir, file_patterns)

    # Pre-filter and apply rotation-aware pruning to avoid expensive
    # get_file_date_range calls on old .gz rotations.
    if start_date:
        candidates = _rotation_prune(all_files, log_dir, start_date)
        pruned_set = set(candidates)
    else:
        pruned_set = set(all_files)

    matched = []
    skipped = []

    for filepath in all_files:
        relname = os.path.relpath(filepath, log_dir)

        if os.path.isdir(filepath):
            try:
                dir_empty = not os.listdir(filepath)
            except (PermissionError, OSError):
                # Unreadable directory: record, exclude, and continue rather
                # than aborting the whole run.
                record_permission_error(filepath)
                skipped.append((relname, 'permission denied'))
                continue
            if dir_empty:
                skipped.append((relname, 'directory empty'))
            continue

        # Rotation-pruned .gz files
        if filepath not in pruned_set:
            skipped.append((relname, 'before time window'))
            continue

        if is_ignored_path(relname):
            skipped.append((relname, 'ignored'))
            continue

        # Skip binary files but not .gz — they contain null bytes by
        # design and are handled via gzip.open in get_file_date_range.
        if not filepath.endswith('.gz') and _is_skippable_file(filepath):
            skipped.append((relname, 'binary/non-log'))
            continue

        first_ts, last_ts = get_file_date_range(filepath, relname)
        if first_ts is None:
            skipped.append((relname, 'no timestamps'))
            continue
        if last_ts is None:
            last_ts = first_ts

        if stop_date and first_ts > stop_date:
            skipped.append((relname, 'after time window'))
            continue
        if start_date and last_ts < start_date:
            skipped.append((relname, 'before time window'))
            continue

        matched.append((relname, first_ts, last_ts))

    matched.sort(key=lambda x: x[1])
    return matched, skipped


def auto_detect_time_range(log_dir, file_patterns, minutes_back=5):
    """Auto-detect time range for window models.

    Scans all matching log files to find the latest timestamp,
    then returns (start, end) where start = latest - minutes_back.

    Args:
        log_dir: Directory containing log files
        file_patterns: File glob pattern(s) from the model
        minutes_back: Minutes before latest timestamp for default start

    Returns:
        (start_datetime, end_datetime) or (None, None) if no timestamps found
    """
    all_files = _expand_window_globs(log_dir, file_patterns)

    latest_ts = None

    for filepath in all_files:
        if os.path.isdir(filepath) or _is_skippable_file(filepath):
            continue
        relname = os.path.relpath(filepath, log_dir)
        _, last_ts = get_file_date_range(filepath, relname)
        if last_ts and (latest_ts is None or last_ts > latest_ts):
            latest_ts = last_ts

    if latest_ts is None:
        return None, None

    start = latest_ts - timedelta(minutes=minutes_back)
    return start, latest_ts


def print_window_summary(matched_files, skipped_files,
                         start_date, stop_date, auto_detected=False,
                         file_hosts=None):
    """Print pre-scan summary for window model.

    Shows the time window and lists matched log files (files whose date
    range overlaps the window).  The per-file date range is intentionally
    omitted to avoid confusion with the search window itself; it is still
    available at verbose level 2.

    Args:
        matched_files: list of (filename, first_ts, last_ts) tuples
        skipped_files: list of (filename, reason) tuples
        start_date: start of time window
        stop_date: end of time window
        auto_detected: whether the time range was auto-detected
        file_hosts: optional dict {filename: [hostname, ...]} for bundle mode
    """
    fmt = "%Y-%m-%dT%H:%M:%S"
    start_str = start_date.strftime(fmt) if start_date else "beginning"
    stop_str = stop_date.strftime(fmt) if stop_date else "end of logs"
    source = " (auto-detected)" if auto_detected else ""

    print(f"  Time window: {start_str} .. {stop_str}{source}")
    print(f"  Log files: {len(matched_files)} matched"
          f", {len(skipped_files)} skipped")

    if file_hosts:
        # Bundle mode: show hosts column (only with -v)
        if get_verbose_level() >= 1:
            print(f"  {'Log Files':<34} Hosts")
            print(f"  {'-' * 34} {'-' * 30}")
            for fname, first_ts, last_ts in matched_files:
                hosts = ' '.join(file_hosts.get(fname, []))
                print(f"    \u2713 {fname:<32} {hosts}")
                vlog2(f"      file range: {first_ts.strftime(fmt)} .. {last_ts.strftime(fmt)}")
        for fname, reason in skipped_files:
            hosts = ' '.join(file_hosts.get(fname, []))
            log_fn = vlog2 if 'time window' in reason else vlog1
            log_fn(f"    \u2717 {fname:<32} ({reason}) {hosts}")
    else:
        if get_verbose_level() >= 1:
            for fname, first_ts, last_ts in matched_files:
                print(f"    \u2713 {fname}")
                vlog2(f"      file range: {first_ts.strftime(fmt)} .. {last_ts.strftime(fmt)}")
        for fname, reason in skipped_files:
            log_fn = vlog2 if 'time window' in reason else vlog1
            log_fn(f"    \u2717 {fname:<32} ({reason})")


def find_no_timestamp_files(log_dir):
    """Walk log_dir recursively and return relative paths of files
    that have no parseable timestamp (skipping binary/non-log and ignored files).
    Respects the file ignore list for directory pruning.
    """
    no_ts = []
    for root, dirs, files in os.walk(log_dir, onerror=_walk_permission_onerror):
        # Prune ignored directories
        relroot = os.path.relpath(root, log_dir)
        if relroot != '.' and is_ignored_path(relroot + '/'):
            dirs.clear()
            continue
        for fname in sorted(files):
            filepath = os.path.join(root, fname)
            relpath = os.path.relpath(filepath, log_dir)
            if is_ignored_path(relpath):
                continue
            if _is_skippable_file(filepath):
                continue
            first_ts, _ = get_file_date_range(filepath, relpath)
            if first_ts is None:
                no_ts.append(relpath)
    return no_ts


# Script runner support for post-analysis hooks
def substitute_variables_in_path(path, variables):
    """Substitute {hostname} and other variables in path string.

    Args:
        path: Path pattern with {hostname}, {peer_controller}, etc.
        variables: Dict with variable values

    Returns: Substituted path string
    """
    result = path
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def resolve_script_arg(bundle_path, arg_pattern, variables=None):
    """Resolve variables and glob patterns in script arguments.

    In bundle mode, automatically prepends {hostname}_????????.?????? to relative paths.

    Args:
        bundle_path: Base bundle directory
        arg_pattern: Path like "var/extra/containerization_api.info"
                     Will be expanded to "{hostname}_????????.??????/var/extra/containerization_api.info"
        variables: Dict with {hostname}, {peer_controller}, etc.

    Returns:
        Tuple (resolved_path: str or None, error: str or None)
    """
    import glob

    if variables is None:
        variables = {}

    # Step 1: Auto-prepend hostname pattern if arg doesn't start with /
    if not arg_pattern.startswith('/'):
        arg_pattern = f"{{hostname}}_????????.??????/{arg_pattern}"
        vlog2(f"Auto-prepended hostname pattern: {arg_pattern}")

    # Step 2: Substitute variables
    substituted = substitute_variables_in_path(arg_pattern, variables)
    vlog2(f"After variable substitution: {substituted}")

    # Step 3: Search in bundle
    search_pattern = os.path.join(bundle_path, substituted)
    vlog2(f"Searching with glob: {search_pattern}")

    matches = sorted(glob.glob(search_pattern))

    if not matches:
        return (None, f"No matches found for pattern: {substituted}")

    # Return first match (most recent if date-based sorting)
    resolved = matches[0]
    vlog2(f"Resolved to: {resolved}")

    return (resolved, None)


def validate_script_format(script_config):
    """Validate script configuration format.

    Returns: (valid: bool, error_message: str or None)
    """
    if isinstance(script_config, str):
        # Single script name - valid
        return (True, None)

    if not isinstance(script_config, list):
        msg = "script must be a string or list [script_name, arg_pattern]"
        return (False, msg)

    if len(script_config) < 1 or len(script_config) > 2:
        msg = "script list must have 1-2 elements [script_name] or [script_name, arg_pattern]"
        return (False, msg)

    if not isinstance(script_config[0], str):
        return (False, "script name (first element) must be a string")

    if len(script_config) == 2 and not isinstance(script_config[1], str):
        return (False, "script argument (second element) must be a string")

    return (True, None)


def get_scripts_search_paths(verbose_level=0):
    """Get list of directories to search for scripts.

    See _get_search_paths() for the shared priority order across
    models, jobs, and scripts. Adds '/etc/lpmp.d/scripts/' as the
    writable override location, matching models and jobs.

    Returns: List of directory paths (existence not pre-filtered;
    callers use os.path.isfile()/os.listdir() and tolerate missing dirs).
    """
    return _get_search_paths('scripts', etc_dir='/etc/lpmp.d/scripts/',
                             system_dir='/var/lib/lpmp_scripts/',
                             verbose=verbose_level, label='Scripts')


def find_script(script_name, search_paths=None):
    """Find and return full path to script.

    Search order:
    1. Absolute path (if starts with /)
    2. Script search paths: built-in, then current dir

    Args:
        script_name: Script name (e.g., "pod_ready_times.py")
        search_paths: List of directories to search

    Returns: Full path to script, or None if not found
    """
    # Absolute path
    if script_name.startswith('/'):
        if os.path.isfile(script_name):
            vlog2(f"Found script at absolute path: {script_name}")
            return script_name
        else:
            vlog1(f"Script not found at absolute path: {script_name}")
            return None

    # Search in script search paths
    if search_paths:
        vlog2(f"Searching for script '{script_name}' in paths: {search_paths}")
        for search_dir in search_paths:
            script_path = os.path.join(search_dir, script_name)
            if os.path.isfile(script_path):
                vlog2(f"Found script: {script_path}")
                return script_path
            else:
                vlog2(f"Not found in {search_dir}: {script_path}")

    # Script not found - print detailed warning
    print(f"\n⚠️ Warning: Script '{script_name}' not found", file=sys.stderr)
    if search_paths:
        print("   Searched in:", file=sys.stderr)
        for search_dir in search_paths:
            exists = "exists" if os.path.isdir(search_dir) else "MISSING"
            print(f"     • {search_dir} ({exists})", file=sys.stderr)
    else:
        print("   No search paths configured", file=sys.stderr)
    print("   Script will not be executed", file=sys.stderr)

    return None


def collect_scripts_files(search_paths=None):
    """Collect available scripts across the scripts search paths.

    Returns a de-duplicated list of (name, full_path) tuples sorted by
    name. De-dup is by basename so a higher-priority path shadows a
    lower-priority one, matching the resolution order of find_script().
    Only executable-style scripts (.py, .sh) are listed. Used by
    --list-scripts.
    """
    if search_paths is None:
        search_paths = get_scripts_search_paths(0)

    # The current-directory entry ('./') is a runtime fallback for
    # ad-hoc user scripts; exclude it from the listing so --list-scripts
    # shows only the dedicated scripts directories rather than whatever
    # files happen to live in the working directory (e.g. the tool's
    # own modules when run from the source tree).
    cwd = os.path.normpath(os.getcwd())
    search_paths = [p for p in search_paths
                    if os.path.normpath(p) not in ('.', cwd)]

    seen = set()
    found = []
    for path in search_paths:
        try:
            names = sorted(os.listdir(path))
        except (OSError, IOError):
            continue
        for name in names:
            if not (name.endswith('.py') or name.endswith('.sh')):
                continue
            if name in seen:
                continue
            full_path = os.path.join(path, name)
            if os.path.isfile(full_path):
                seen.add(name)
                found.append((name, os.path.normpath(full_path)))

    found.sort(key=lambda x: x[0].lower())
    return found


def run_script_hook(script_config, args, variables=None, search_paths=None):
    """Execute script hook at end of lpmptool run.

    Args:
        script_config: String or list [script_name, arg_pattern]
        args: Parsed command-line arguments (bundle, hostname, etc.)
        variables: Dict with variable substitutions {hostname}, {peer_controller}, etc.
        search_paths: Script search paths from get_scripts_search_paths()
    """
    import subprocess

    if not script_config:
        return

    if variables is None:
        variables = {}

    # Add standard variables if not provided
    if 'hostname' not in variables and hasattr(args, 'hostname'):
        variables['hostname'] = args.hostname
    if 'peer_controller' not in variables:
        hostname = variables.get('hostname',
                                 args.hostname if hasattr(args, 'hostname')
                                 else 'controller-0')
        peer = 'controller-1' if hostname == 'controller-0' else 'controller-0'
        variables['peer_controller'] = peer

    # Validate format
    valid, error_msg = validate_script_format(script_config)
    if not valid:
        msg = f"\n⚠️ Warning: Invalid script configuration: {error_msg}\n   Script will not be executed"
        print(msg, file=sys.stderr)
        return

    # Parse script config
    if isinstance(script_config, str):
        script_name = script_config
        script_arg = None
    else:
        script_name = script_config[0]
        script_arg = script_config[1] if len(script_config) > 1 else None

    # Find script
    script_path = find_script(script_name, search_paths=search_paths)
    if not script_path:
        # Detailed warning already printed by find_script()
        return

    # Readable check up front: subprocess.run() would raise a
    # PermissionError once launched, but checking here gives a clearer,
    # earlier message naming the exact path. Execute ('x') permission
    # is not required — the script is never exec'd directly, it's
    # passed as an argument to the interpreter selected below, which
    # only needs to read the file's contents.
    if not os.access(script_path, os.R_OK):
        print(f"\n⚠️ Warning: Script '{script_path}' is not readable",
              file=sys.stderr)
        print("   Script will not be executed", file=sys.stderr)
        return

    print(f"Script: {os.path.abspath(script_path)}")

    # Build command: dispatch on extension so .sh scripts run under
    # bash instead of being (incorrectly) handed to python3.
    ext = os.path.splitext(script_path)[1].lower()
    if ext == '.py':
        cmd = ["python3", script_path]
    elif ext == '.sh':
        cmd = ["bash", script_path]
    else:
        print(f"\n⚠️ Warning: Unsupported script type '{ext}' for "
              f"'{script_path}' (expected .py or .sh)", file=sys.stderr)
        print("   Script will not be executed", file=sys.stderr)
        return

    # Print startup message BEFORE running the script
    print(f"\n🔍 Running script: {script_name} - Please standby...\n")
    sys.stdout.flush()  # Ensure it prints immediately

    # Handle arguments
    if script_arg:
        if args.bundle != '/':  # Bundle mode
            resolved_arg, error = resolve_script_arg(args.bundle,
                                                     script_arg,
                                                     variables)
            if error:
                msg = "\n⚠️ Warning: Script argument resolution failed"
                print(msg, file=sys.stderr)
                print(f"   Pattern: {script_arg}", file=sys.stderr)
                print(f"   Error: {error}", file=sys.stderr)
                print("   Script will not be executed", file=sys.stderr)
                return
            if resolved_arg:
                cmd.append(resolved_arg)

    # Execute with real-time output (don't capture)
    try:
        vlog1(f"Running post-analysis script: {' '.join(cmd)}")
        result = subprocess.run(cmd, timeout=300)

        if result.returncode != 0:
            msg = f"\n⚠️ Warning: Script exited with code {result.returncode}"
            print(msg, file=sys.stderr)
    except subprocess.TimeoutExpired:
        msg = "\n⚠️ Warning: Script timed out after 300 seconds"
        print(msg, file=sys.stderr)
    except Exception as e:
        print(f"\n⚠️ Warning: Failed to run script: {e}", file=sys.stderr)
