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
    """Stop progress indicator and clean up cursor position"""
    progress_active[0] = False
    time.sleep(0.3)  # Give indicator time to stop
    # Get the true original stdout to ensure newline never goes to capture buffer
    original_stdout = ConsoleCapture.get_true_original_stdout()
    original_stdout.write('\n')  # New line after progress indicator
    original_stdout.flush()


def get_models_search_paths(verbose=0):
    """Get prioritized search paths for model files.

    Args:
        verbose: Verbosity level (default: 0)

    Search order (highest to lowest priority):
    1. <tool_directory>/models/ (relative to where lpmptool resides) - HIGHEST PRIORITY
    2. <tool_directory>/models/examples/ (example models)
    3. ./models/ (relative to current directory) - Local development models
    4. ./models/examples/ (local example models)
    5. /etc/lpmp.d/ - User/developer models (writable in OSTree)
    6. /var/lib/lpmp_models/ - System-provided models (read-only)
    7. ./ (current directory)

    Returns list of search paths.
    """
    # When installed as a package, __file__ resolves to a dist-packages
    # or site-packages directory ; skip tool_dir model paths in that case.
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    installed = 'dist-packages' in tool_dir or 'site-packages' in tool_dir

    search_paths = []
    if not installed:
        search_paths.append(os.path.join(tool_dir, 'models'))              # Priority 1
        search_paths.append(os.path.join(tool_dir, 'models', 'examples'))  # Priority 2
    search_paths += [
        './models/',                                   # Priority 3
        './models/examples/',                          # Priority 4
        '/etc/lpmp.d/',                                # Priority 5
        '/var/lib/lpmp_models/',                       # Priority 6
        '/var/lib/lpmp_models/examples/',              # Priority 7
        './'                                           # Priority 8
    ]

    if verbose >= 1:
        print(f"Tool: {os.path.abspath(sys.argv[0]) if sys.argv else 'N/A'}")
        print("Model search paths (highest to lowest priority):")
        for i, path in enumerate(search_paths, 1):
            exists = "✓" if os.path.exists(path) else "✗"
            print(f"  {i}. {exists} {path}")

    return search_paths


def detect_bundle_hosts(bundle_path):
    """Detect bundle hosts from dated hostname directories.
    Expected format: <hostname>_YYYYMMDD.HHMMSS
    Returns tuple: (bundle_host_list, bundle_host_list_dated)
    - bundle_host_list: sorted list of hostnames (without date suffix)
    - bundle_host_list_dated: sorted list of full directory names (hostname_date)
    Exits if no bundle hosts found or if date parts differ.
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
    hostnames = []
    if len(bundle_hosts) > 1:
        print("Error: Bundle host directories have different date parts", file=sys.stderr)
        for date_part, hosts in bundle_hosts.items():
            hostnames = [h[0] for h in hosts]
            print(f"  {date_part}: {', '.join(hostnames)}", file=sys.stderr)
        print("All bundle hosts must have the same date part", file=sys.stderr)
        sys.exit(1)

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


def parse_timestamp(line, relpath=None):
    """Extract timestamp from log line supporting sysinv and ISO formats.

    Formats supported:
    - sysinv: "sysinv 2024-01-06 12:30:45.123 message"
    - ISO:    "2024-01-06T12:30:45.123 message"

    Returns datetime object or None if no valid timestamp found.
    """
    # cspell:ignore sysinv
    if not line:
        return None

    # Cheap prefix guard for built-in formats: sysinv starts with 's',
    # ISO starts with a digit. Other lines skip to custom format fallback.

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
                first_ts, last_ts = get_file_date_range(filepath)
                file_info.append((relpath, mtime, first_ts, last_ts))
            else:
                file_info.append((relpath, mtime, None, None))
        except OSError:
            continue

    if not file_info:
        return [file_pattern]

    # Sort oldest first (chronological) when start_date is provided so
    # the first block finds the earliest match after start_date rather
    # than the first match in the newest file.  Without start_date,
    # keep newest-first for faster searches targeting recent logs.
    file_info.sort(key=lambda x: x[1], reverse=(start_date is None))

    sorted_files = [f[0] for f in file_info]

    order = 'oldest first' if start_date else 'newest first'
    vlog2(f"Expanded '{file_pattern}' to {len(sorted_files)} files ({order}): {sorted_files}")

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
_VALID_TOP_KEYS = {'blocks', 'settings', 'include'}
_VALID_BLOCK_KEYS = {
    'label', 'file', 'patterns', 'start', 'stop', 'timeline',
    'optional', 'present', 'profile', 'controller', 'override',
    'max_time_delta', 'window', 'context'
}
_VALID_SETTINGS_KEYS = {
    'max_time_delta', 'block_time_tolerance',
    'start_date', 'stop_date', 'loops', 'max_log_length', 'profile',
    'optional', 'controller', 'graph', 'host', 'timeline_patterns'
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
                'present': block_data.get('present', False)
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


def create_output_directory(args, run_start_time, hostname=None):
    if args.output:
        # Detect if output is current directory and skip creation
        if args.output == '.' or os.path.abspath(args.output) == os.getcwd():
            if hostname:
                output_dir = hostname
            else:
                output_dir = '.'
            return ensure_output_dir(output_dir) if output_dir != '.' else '.'

        # Maintain lpmp_<lab>/<timestamp>_<model> structure under -o path (bundle and non-bundle)
        model_name = os.path.splitext(os.path.basename(args.model_file))[0]
        time_str = run_start_time.strftime("%Y%m%d_%H%M%S")
        base_dir = os.path.join(args.output, f"lpmp_{args.lab_name}", f"{time_str}_{model_name}")
        output_dir = base_dir
        if hostname:
            output_dir = os.path.join(base_dir, hostname)
    else:
        model_name = os.path.splitext(os.path.basename(args.model_file))[0]
        time_str = run_start_time.strftime("%Y%m%d_%H%M%S")

        # Use bundle directory as base in bundle mode, otherwise current directory
        if hasattr(args, 'bundle_name') and args.bundle_name != '/':
            base_path = args.bundle_name
        else:
            base_path = os.getcwd()

        base_dir = os.path.join(base_path, f"lpmp_{args.lab_name}", f"{time_str}_{model_name}")
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
                first_ts, last_ts = get_file_date_range(filepath)
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
            # Walk subdirectories with the same pattern
            for root, dirs, files in os.walk(log_dir):
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
            if not os.listdir(filepath):
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
    for root, dirs, files in os.walk(log_dir):
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
