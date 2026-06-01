#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
LPMP Engine Module

This module contains core processing functions for the Log Pattern Matching Profiler.
Provides pattern matching, block processing workflows, and orchestration logic.
"""

from datetime import datetime
from datetime import timedelta
import gzip
import os
import re
import sys

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True  # noqa: E402

# Import utilities

from lpmp_utils import apply_timeline_variable_substitution  # noqa: E402
from lpmp_utils import discover_window_files                 # noqa: E402
from lpmp_utils import format_duration                       # noqa: E402
from lpmp_utils import format_log_line_for_output            # noqa: E402
from lpmp_utils import format_result_line                    # noqa: E402
from lpmp_utils import get_verbose_level                     # noqa: E402
from lpmp_utils import load_model                            # noqa: E402
from lpmp_utils import manage_peer_controller                # noqa: E402
from lpmp_utils import ModelType                             # noqa: E402
from lpmp_utils import PairResult                            # noqa: E402
from lpmp_utils import parse_timestamp                       # noqa: E402
from lpmp_utils import PatternResult                         # noqa: E402
from lpmp_utils import resolve_timeline_patterns             # noqa: E402
from lpmp_utils import substitute_variables                  # noqa: E402
from lpmp_utils import TimelineResult                        # noqa: E402
from lpmp_utils import vlog1                                 # noqa: E402
from lpmp_utils import vlog2                                 # noqa: E402
from lpmp_utils import vlog3                                 # noqa: E402
from lpmp_utils import vlog4                                 # noqa: E402
from lpmp_utils import vlog5                                 # noqa: E402


def find_pattern_in_files(log_dir,
                          filenames,
                          pattern,
                          start_pos=0,
                          after_timestamp=None,
                          suppress_error=False,
                          block_label=None,
                          max_time_delta=None,
                          logs_dir=None,
                          args=None):
    """Search for pattern in a list of log files in order, starting from given position.
    Supports both regular and gzipped (.gz) log files.

    Note: For .gz files, position tracking is unreliable due to compression.
    Use timestamp filtering (after_timestamp) for chronological ordering with .gz files.

    Searches files in the order provided (newest first) until pattern is found.
    Uses smart date-range filtering to skip files outside the target date range.
    Returns (timestamp, new_position, log_line, actual_filename) or None if not found.

    max_time_delta: If provided, limits search to patterns within this many seconds of after_timestamp
    """
    # Use logs_dir if specified, otherwise use regular log_dir
    search_log_dir = logs_dir if logs_dir else log_dir
    # Handle single filename (convert to list for uniform processing)
    if isinstance(filenames, str):
        filenames = [filenames]

    # Check if any files exist before searching
    files_exist = False
    for filename in filenames:
        filepath = os.path.join(search_log_dir, filename)
        if os.path.exists(filepath):
            files_exist = True
            break

    if not files_exist and not suppress_error:
        file_list = ', '.join(filenames)
        print(f"Error: no files matching {file_list} found in {search_log_dir}", file=sys.stderr)
        return None

    # Import get_file_date_range from lpmp_utils for smart filtering
    from lpmp_utils import get_file_date_range

    # Pre-compile regex for hot loop performance
    try:
        compiled_pattern = re.compile(pattern)
        use_compiled = True
    except re.error:
        compiled_pattern = None
        use_compiled = False

    for filename in filenames:
        filepath = os.path.join(search_log_dir, filename)
        vlog3(f"Checking file: {filepath}")
        if not os.path.exists(filepath):
            vlog2(f"File {filepath} not found, trying next...")
            continue

        # Smart date-range filtering: Skip files where after_timestamp is after the file's end
        # This optimization skips old rotated files that end before our search timestamp
        # The tolerance (block_time_tolerance) handles timing variations between patterns
        if after_timestamp:
            first_ts, last_ts = get_file_date_range(filepath)
            if first_ts and last_ts:
                # Calculate tolerance: use max_time_delta if provided, otherwise use block_time_tolerance
                if max_time_delta:
                    tolerance = timedelta(seconds=max_time_delta)
                else:
                    # Add block_time_tolerance to allow searching backwards for out-of-order patterns
                    block_time_tolerance = getattr(args, 'block_time_tolerance', 5.0) if args else 5.0
                    tolerance = timedelta(seconds=block_time_tolerance)

                # Skip file if after_timestamp is after the file's date range (plus tolerance)
                if after_timestamp > last_ts + tolerance:
                    vlog3(f"Skipping {filename}: after_timestamp {after_timestamp} "
                          f"is after file range ({first_ts} to {last_ts}) + tolerance {tolerance.total_seconds()}s")
                    continue
                vlog3(f"Searching {filename}: file range ({first_ts} to {last_ts}) "
                      f"may contain patterns after {after_timestamp}")

        vlog2(f"Searching for '{pattern}' in {filename} from position {start_pos}")
        vlog3(f"Opening file: {filepath}")

        # Open file based on extension (.gz or regular)
        is_gzipped = filename.endswith('.gz')
        if is_gzipped:
            open_func = gzip.open
            mode = 'rt'  # text mode for gzip
        else:
            open_func = open
            mode = 'r'

            # File position caching optimization (only for non-compressed files)
            if hasattr(args, '_file_position_cache'):
                cache_key = f"{search_log_dir}/{filename}"
                cached_pos = args._file_position_cache.get(cache_key, start_pos)
                if cached_pos > start_pos:
                    start_pos = cached_pos
                    vlog3(f"Using cached position {start_pos} for {filename}")

        try:
            with open_func(filepath, mode, encoding='utf-8', errors='ignore') as f:
                # For gzipped files, seeking is unreliable, so start from beginning
                # and rely on timestamp filtering
                if not is_gzipped:
                    f.seek(start_pos)
                elif start_pos > 0:
                    vlog4("Warning: Position tracking not reliable for .gz files, using timestamp filtering")

                # Search line by line for pattern
                line_count = 0
                while True:
                    line = f.readline()
                    if not line:  # EOF reached
                        break

                    line_count += 1
                    if line_count <= 5:
                        vlog5(f"Sample line {line_count}: {line.strip()[:100]}")

                    # Parse timestamp FIRST to skip lines before start_date
                    timestamp = parse_timestamp(line)
                    if timestamp:
                        # Skip lines before after_timestamp (start_date) to avoid unnecessary pattern matching
                        if after_timestamp:
                            tolerance = getattr(args, 'block_time_tolerance', 5.0) if args else 5.0
                            time_diff = (after_timestamp - timestamp).total_seconds()

                            # Skip lines that are before after_timestamp minus tolerance
                            # but allow same-timestamp matches (different blocks/patterns
                            # can legitimately share the same timestamp)
                            if time_diff > tolerance:
                                if line_count <= 5:
                                    vlog3(f"DEBUG: Skipping line due to timestamp filter: "
                                          f"time_diff={time_diff:.1f}s > tolerance={tolerance}s")
                                continue
                            # Note: previously had 'elif timestamp == after_timestamp: continue'
                            # which prevented re-finding same timestamp between loops, but
                            # also broke legitimate same-timestamp matches between blocks
                            # (e.g. Pod Drain Complete and Lazy Reboot Start at same time).
                            # Loop advancement is handled by lpmptool's 500ms time advance.

                    # Now try pattern matching only on lines that pass timestamp filter
                    if use_compiled:
                        matched = compiled_pattern.search(line)
                    else:
                        matched = pattern in line

                    if matched:
                        if timestamp:
                            # Virtual EOF: Skip if timestamp exceeds stop_date
                            if (
                                hasattr(args, 'stop_date_parsed')
                                and args.stop_date_parsed
                                and timestamp > args.stop_date_parsed
                            ):
                                vlog4(
                                    f"Virtual EOF reached at {timestamp} "
                                    f"(exceeds stop_date {args.stop_date_parsed})"
                                )
                                return None

                            # Skip if timestamp exceeds max_time_delta from after_timestamp
                            if max_time_delta is not None and after_timestamp:
                                if max_time_delta == 0.0:
                                    if timestamp != after_timestamp:
                                        vlog4(
                                            f"Skipping match at {timestamp} "
                                            f"(zero tolerance, not exact match with {after_timestamp})"
                                        )
                                        continue
                                else:
                                    time_diff = (timestamp - after_timestamp).total_seconds()
                                    if time_diff > max_time_delta:
                                        vlog4(
                                            f"Skipping match at {timestamp} for block '{block_label}' "
                                            f"(time_diff={time_diff:.1f}s > max_time_delta={max_time_delta}s, "
                                            f"after_timestamp={after_timestamp})"
                                        )
                                        continue

                            vlog1(f"Found pattern at {timestamp} in {filename}")
                            formatted_line = format_log_line_for_output(line.strip(), filename)
                            new_position = 0 if is_gzipped else f.tell()

                            # Update file position cache if enabled and not compressed
                            if hasattr(args, '_file_position_cache') and not is_gzipped:
                                cache_key = f"{search_log_dir}/{filename}"
                                args._file_position_cache[cache_key] = new_position
                                vlog4(f"Updated cache position to {new_position} for {filename}")

                            return timestamp, new_position, formatted_line, filename
                        else:
                            # Pattern matched but no valid timestamp - skip this line
                            continue
        except (IOError, OSError, gzip.BadGzipFile) as e:
            vlog3(f"DEBUG: Error reading {filename}: {e}")
            continue

    # Pattern not found in any file
    if not suppress_error:
        file_list = ', '.join(filenames)
        label_info = f" for block '{block_label}'" if block_label else ""
        vlog4(f"⚠️ Error: Pattern '{pattern}' not found in any of: {file_list}{label_info}", file=sys.stderr)
    return None


def _bisect_seek_to_timestamp(f, target_timestamp, file_size):
    """Binary search within a plain-text file to position near target_timestamp.

    Seeks to the approximate file position where lines with timestamps
    >= target_timestamp begin, avoiding a linear scan from the start.
    After return the caller should readline() to consume the partial
    line left by the seek, then continue reading.
    """
    lo, hi = 0, file_size
    best = 0  # best known position that is still before target

    while lo < hi:
        mid = (lo + hi) // 2
        f.seek(mid)
        f.readline()  # skip partial line
        line = f.readline()
        if not line:
            hi = mid
            continue
        ts = parse_timestamp(line)
        if ts is None:
            # No parseable timestamp — try a few more lines
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
                ts = parse_timestamp(line)
                if ts is not None:
                    break
        if ts is None:
            hi = mid
            continue
        if ts < target_timestamp:
            best = f.tell()
            lo = mid + 1
        else:
            hi = mid

    f.seek(best)
    f.readline()  # align to next full line


def find_pattern_in_files_all_matches(log_dir,
                                      filenames, pattern,
                                      after_timestamp=None, args=None):
    """Find ALL matches for a pattern in files (used for --sort mode).
    Returns list of (timestamp, log_line, actual_filename) tuples.
    """
    matches = []
    if isinstance(filenames, str):
        filenames = [filenames]

    # Import get_file_date_range for smart file filtering
    from lpmp_utils import get_file_date_range

    # Pre-compile regex for hot loop performance
    try:
        compiled_pattern = re.compile(pattern)
        use_compiled = True
    except re.error:
        compiled_pattern = None
        use_compiled = False

    for filename in filenames:
        filepath = os.path.join(log_dir, filename)
        if not os.path.exists(filepath):
            continue

        # Smart date-range filtering: skip files that end before after_timestamp
        if after_timestamp:
            first_ts, last_ts = get_file_date_range(filepath)
            if first_ts and last_ts and after_timestamp > last_ts:
                vlog3(f"Skipping {filename}: after_timestamp {after_timestamp} is after file range end {last_ts}")
                continue

        is_gzipped = filename.endswith('.gz')
        open_func = gzip.open if is_gzipped else open
        mode = 'rt' if is_gzipped else 'r'

        try:
            with open_func(filepath, mode, encoding='utf-8', errors='ignore') as f:
                # Binary-search seek for plain-text files when we have a
                # start timestamp, so we skip the bulk of lines before the
                # time window instead of reading them one by one.
                # Only worthwhile on files > 32 KB; tiny files are fast
                # enough to scan linearly and the seek can overshoot.
                if not is_gzipped and after_timestamp:
                    file_size = os.path.getsize(filepath)
                    if file_size > 32768:
                        _bisect_seek_to_timestamp(f, after_timestamp, file_size)

                while True:
                    line = f.readline()
                    if not line:
                        break

                    # Parse timestamp FIRST to skip lines outside date range
                    timestamp = parse_timestamp(line)
                    if timestamp:
                        if after_timestamp and timestamp <= after_timestamp:
                            continue
                        # Virtual EOF: break when past stop_date
                        if (
                            hasattr(args, 'stop_date_parsed')
                            and args.stop_date_parsed
                            and timestamp > args.stop_date_parsed
                        ):
                            break

                    # Pattern matching on lines that pass timestamp filter
                    if use_compiled:
                        matched = compiled_pattern.search(line)
                    else:
                        matched = pattern in line

                    if matched and timestamp:
                        formatted_line = format_log_line_for_output(
                            line.strip(), filename)
                        matches.append((timestamp, formatted_line, filename))
        except (IOError, OSError, gzip.BadGzipFile) as e:
            print(f"Error reading {filename}: {e}")

    return matches


def _substitute_pattern_or_list(pattern, variables):
    """Substitute variables in a pattern that may be a string or list (OR patterns)."""
    if isinstance(pattern, list):
        return [substitute_variables(p, variables) for p in pattern]
    return substitute_variables(pattern, variables)


def _find_pattern_or_list(args, block, pattern, after_timestamp,
                          max_time_delta, override_logs_dir):
    """Search for a pattern that may be a string or list (OR patterns).
    Returns (result, match_index) where match_index is the list index that
    matched (None for non-list patterns).
    """
    if isinstance(pattern, list):
        for idx, alt in enumerate(pattern):
            result = find_pattern_in_files(
                args.logs_dir, block['file'], alt, 0, after_timestamp,
                suppress_error=True, block_label=block['label'],
                max_time_delta=max_time_delta,
                logs_dir=override_logs_dir, args=args
            )
            if result is not None:
                return result, idx
        return None, None
    result = find_pattern_in_files(
        args.logs_dir, block['file'], pattern, 0, after_timestamp,
        suppress_error=True, block_label=block['label'],
        max_time_delta=max_time_delta,
        logs_dir=override_logs_dir, args=args
    )
    return result, None


def apply_variable_substitution(blocks, variables):
    """Apply variable substitution to all patterns in blocks.
    Modifies blocks in-place.

    Override Feature: Blocks with 'override' field will have their patterns
    substituted later during processing to use the correct hostname variables.
    """
    # Calculate peer_controller variable for controller hostname pairs
    manage_peer_controller(variables)

    for block in blocks:
        # Apply variable substitution to label
        if 'label' in block:
            block['label'] = substitute_variables(block['label'], variables)

        # Make resolved label available as {label} variable for pattern substitution
        variables['label'] = block.get('label', '')

        # Override Feature: Apply variable substitution to override field
        # This allows override: "{peer_controller}" syntax
        if 'override' in block:
            block['override'] = substitute_variables(block['override'], variables)

        if 'start' in block and 'stop' in block:
            # Pair block - start/stop format
            # Override Feature: Skip pattern substitution for pair blocks with override
            if not block.get('override'):
                block['start'] = _substitute_pattern_or_list(block['start'], variables)
                block['stop'] = _substitute_pattern_or_list(block['stop'], variables)
            if get_verbose_level() >= 2:
                status = "skipped (has override)" if block.get('override') else "substituted"
                vlog2(f"Block '{block['label']}' start/stop patterns {status}")
        elif 'timeline' in block:
            # Timeline block - timeline patterns handled during resolution
            # Override Feature: Timeline blocks do not support override
            vlog2(
                f"Block '{block['label']}' timeline patterns will be "
                f"resolved during processing: {block['timeline']}"
            )
        elif 'patterns' in block:
            # Pattern block - patterns format
            # Override Feature: Skip pattern substitution for blocks with override
            # They'll be substituted later with correct override hostname variables
            if not block.get('override'):
                for i, pattern in enumerate(block['patterns']):
                    if isinstance(pattern, list):
                        # OR patterns - substitute each alternative
                        block['patterns'][i] = [substitute_variables(p, variables)
                                                for p in pattern]
                    else:
                        # Single pattern
                        block['patterns'][i] = substitute_variables(pattern,
                                                                    variables)
                vlog4(
                    f"Block '{block['label']}' patterns after substitution: "
                    f"{block['patterns']}"
                )
            else:
                vlog2(
                    f"Block '{block['label']}' patterns skipped (has override): "
                    f"{block['patterns']}"
                )


def process_pattern_block(args, block, start_date, max_time_delta=None):
    """Process a single pattern block (uses 'patterns:' field).

    With stacked pattern expansion, this function now only processes single patterns.
    Each pattern block contains exactly one pattern in its 'patterns' list.

    Override Feature: If block has 'override' field, searches patterns in the
    specified hostname's log directory instead of current hostname's logs.

    Returns a list with one tuple: [(timestamp, log_line, actual_filename, output_hostname)]
    or None if the block failed.
    """
    if not block.get('patterns'):
        return None

    # Skip controller-only blocks if hostname doesn't contain 'controller'
    current_hostname = getattr(args, 'current_processing_hostname', getattr(args, 'hostname', 'controller-0'))
    # Check block-level controller setting, fall back to model-level setting
    controller_only = block.get('controller', getattr(args, 'controller_setting', False))
    if controller_only and 'controller' not in current_hostname:
        vlog2(f"Skipping controller-only block '{block['label']}' for non-controller host {current_hostname}")
        return None

    # Override Feature: Check for override hostname in block configuration
    # This allows searching patterns in a different hostname's log directory
    override_logs_dir = None
    if block.get('override') and hasattr(args, 'bundle_name') and args.bundle_name != '/':
        override_hostname = block['override']  # Should already be substituted by apply_variable_substitution
        # Build override logs directory path - check bundle directory for available hosts
        if hasattr(args, 'bundle_host_list_dated'):
            # First try the included hosts list
            for hostname, dated_dir in zip(getattr(args, 'bundle_host_list', []), args.bundle_host_list_dated):
                if hostname == override_hostname:
                    override_logs_dir = os.path.join(
                        args.bundle_name, dated_dir,
                        getattr(args, 'original_logs_dir', 'var/log')
                    )
                    break

        # If not found in included hosts, check all available hosts in bundle directory
        if override_logs_dir is None and hasattr(args, 'bundle_name'):
            try:
                bundle_entries = os.listdir(args.bundle_name)
                for entry in bundle_entries:
                    if (
                        entry.startswith(override_hostname + '_')
                        and os.path.isdir(os.path.join(args.bundle_name, entry))
                    ):
                        override_logs_dir = os.path.join(
                            args.bundle_name, entry,
                            getattr(args, 'original_logs_dir', 'var/log')
                        )
                        break
            except OSError:
                pass

    # Override Feature: Create variables for pattern substitution with override hostname
    current_hostname = getattr(args, 'current_processing_hostname', getattr(args, 'hostname', 'controller-0'))
    pattern_variables = {'hostname': current_hostname, 'label': block.get('label', '')}
    if hasattr(args, 'host') and args.host:
        pattern_variables['host'] = args.host
    if hasattr(args, 'variables') and args.variables:
        for var_pair in args.variables:
            if '=' in var_pair:
                key, value = var_pair.split('=', 1)
                pattern_variables[key] = value

    # Add peer_controller variable
    manage_peer_controller(pattern_variables)

    # Override Feature: If this block has an override, use the override hostname for pattern substitution
    output_hostname = current_hostname  # Default to current hostname
    if block.get('override'):
        pattern_variables['hostname'] = block['override']
        # Recalculate peer_controller based on the override hostname value
        if 'controller' in block['override']:
            if block['override'] == 'controller-0':
                pattern_variables['peer_controller'] = 'controller-1'
            elif block['override'] == 'controller-1':
                pattern_variables['peer_controller'] = 'controller-0'
        output_hostname = block['override']  # Use override hostname for output

    search_path = override_logs_dir if override_logs_dir else args.logs_dir

    # Block-level max_time_delta takes precedence over parameter value
    # BUT: Don't override None (which means "no constraint for first pattern")
    if 'max_time_delta' in block and max_time_delta is not None:
        max_time_delta = block['max_time_delta']
    # If no block-level max_time_delta and we have a parameter value, keep the parameter value
    # (max_time_delta parameter is already set correctly by the caller)

    if get_verbose_level() >= 1:
        vlog1(
            f"Block '{block['label']}': hostname={current_hostname}, "
            f"override={block.get('override', 'None')}, search_path={search_path}, "
            f"max_time_delta={max_time_delta}"
        )

    # Process single pattern (stacked patterns have been expanded into individual blocks)
    pattern = block['patterns'][0]  # Always exactly one pattern after expansion
    after_timestamp = start_date

    # Apply variable substitution to the pattern using local variables
    if isinstance(pattern, list):
        pattern = [substitute_variables(p, pattern_variables) for p in pattern]
    else:
        pattern = substitute_variables(pattern, pattern_variables)

    if isinstance(pattern, list):
        # OR pattern - try each alternative
        result = None
        for alt_pattern in pattern:
            result = find_pattern_in_files(
                args.logs_dir, block['file'], alt_pattern, 0,
                after_timestamp, suppress_error=True,
                block_label=block['label'], max_time_delta=max_time_delta,
                logs_dir=override_logs_dir, args=args
            )
            if result is not None:
                break
    else:
        result = find_pattern_in_files(
            args.logs_dir, block['file'], pattern, 0,
            after_timestamp, suppress_error=True,
            block_label=block['label'], max_time_delta=max_time_delta,
            logs_dir=override_logs_dir, args=args
        )

    if result is None:
        if block.get('present', False):
            return None
        if not block.get('optional', getattr(args, 'optional_setting', False)):
            vlog1(f"Required pattern not found in block '{block['label']}'")
        return None

    timestamp, new_pos, log_line, actual_filename = result
    return [(timestamp, log_line, actual_filename, output_hostname)]


def process_pair_block(args, block, after_timestamp, global_max_time_delta=45):
    """Process a single pair block (uses 'start:'/'stop:' fields).

    Override Feature: If block has 'override' field, searches start/stop patterns in the
    specified hostname's log directory instead of current hostname's logs.

    Returns ((start_timestamp, stop_timestamp), duration_info, actual_filename) or None if not found.

    Uses block-level max_time_delta if present, otherwise falls back to global_max_time_delta.
    The after_timestamp parameter ensures sequential processing by only searching after this time.
    For standalone testing, max_time_delta constraint is only applied between start and stop patterns.

    Date Rollover Handling:
    - Timestamps include full date (YYYY-MM-DD HH:MM:SS.fff)
    - Duration calculation correctly handles day boundaries
    - Output shows date when start and stop are on different days
    - Example: "2024-01-01 23:59:58.000: Start -> Stop: 2024-01-02 00:00:05.000: 7.000s"
    """
    if not (block.get('start') and block.get('stop')):
        return None

    # Skip controller-only blocks if hostname doesn't contain 'controller'
    current_hostname = getattr(args, 'current_processing_hostname', getattr(args, 'hostname', 'controller-0'))
    # Check block-level controller setting, fall back to model-level setting
    controller_only = block.get('controller', getattr(args, 'controller_setting', False))
    if controller_only and 'controller' not in current_hostname:
        vlog2(f"Skipping controller-only block '{block['label']}' for non-controller host {current_hostname}")
        return None

    # Override Feature: Check for override hostname in block configuration
    # This allows searching start/stop patterns in a different hostname's log directory
    override_logs_dir = None
    if block.get('override') and hasattr(args, 'bundle_name') and args.bundle_name != '/':
        override_hostname = block['override']  # Should already be substituted by apply_variable_substitution
        # Build override logs directory path - check bundle directory for available hosts
        if hasattr(args, 'bundle_host_list_dated'):
            # First try the included hosts list
            for hostname, dated_dir in zip(getattr(args, 'bundle_host_list', []), args.bundle_host_list_dated):
                if hostname == override_hostname:
                    override_logs_dir = os.path.join(
                        args.bundle_name, dated_dir,
                        getattr(args, 'original_logs_dir', 'var/log')
                    )
                    break

        # If not found in included hosts, check all available hosts in bundle directory
        if override_logs_dir is None and hasattr(args, 'bundle_name'):
            try:
                bundle_entries = os.listdir(args.bundle_name)
                for entry in bundle_entries:
                    if (
                        entry.startswith(override_hostname + '_')
                        and os.path.isdir(os.path.join(args.bundle_name, entry))
                    ):
                        override_logs_dir = os.path.join(
                            args.bundle_name, entry,
                            getattr(args, 'original_logs_dir', 'var/log')
                        )
                        break
            except OSError:
                pass

    # Override Feature: Create variables for pattern substitution with override hostname
    # When override is specified, recalculate variables based on override hostname
    pattern_variables = {'hostname': current_hostname, 'label': block.get('label', '')}
    if hasattr(args, 'host') and args.host:
        pattern_variables['host'] = args.host
    if hasattr(args, 'variables') and args.variables:
        for var_pair in args.variables:
            if '=' in var_pair:
                key, value = var_pair.split('=', 1)
                pattern_variables[key] = value

    # Add peer_controller variable
    manage_peer_controller(pattern_variables)

    # Override Feature: If this block has an override, use the override hostname for pattern substitution
    # This ensures variables like {hostname} and {peer_controller} are calculated correctly
    if block.get('override'):
        pattern_variables['hostname'] = block['override']
        # Recalculate peer_controller based on the override hostname value
        if 'controller' in block['override']:
            if block['override'] == 'controller-0':
                pattern_variables['peer_controller'] = 'controller-1'
            elif block['override'] == 'controller-1':
                pattern_variables['peer_controller'] = 'controller-0'

    # Override Feature: Apply variable substitution to start/stop patterns if block has override
    # (patterns were skipped during apply_variable_substitution for override blocks)
    start_pattern = block['start']
    stop_pattern = block['stop']
    if block.get('override'):
        start_pattern = _substitute_pattern_or_list(block['start'], pattern_variables)
        stop_pattern = _substitute_pattern_or_list(block['stop'], pattern_variables)

    search_path = override_logs_dir if override_logs_dir else args.logs_dir

    # Use block-level max_time_delta if present, otherwise use global setting
    max_time_delta = block.get('max_time_delta') or global_max_time_delta

    # Find start pattern - apply sequential search constraint if in sequential mode
    # Sequential constraint prevents jumping between different event sequences
    # but allows some flexibility for patterns that occur close in time
    sequential_max_time_delta = None
    if after_timestamp and hasattr(args, '_sequential_mode') and args._sequential_mode:
        # In sequential processing mode, apply constraint to prevent jumping between events
        # But allow patterns that are within time_tolerance of the after_timestamp
        sequential_max_time_delta = max_time_delta

    start_result, _ = _find_pattern_or_list(
        args, block, start_pattern, after_timestamp,
        sequential_max_time_delta, override_logs_dir
    )

    if start_result is None:
        if not block.get('optional', getattr(args, 'optional_setting', False)):
            vlog1(f"Start pattern not found in pair block '{block['label']}'")
        return None

    start_timestamp, _, start_log_line, start_filename = start_result

    # Find stop pattern after start timestamp
    stop_result, stop_match_idx = _find_pattern_or_list(
        args, block, stop_pattern, start_timestamp,
        max_time_delta, override_logs_dir
    )

    if stop_result is None:
        if not block.get('optional', getattr(args, 'optional_setting', False)):
            vlog1(f"Stop pattern not found in pair block '{block['label']}'")
        return None

    stop_timestamp, _, stop_log_line, stop_filename = stop_result

    # Calculate duration and format output
    pair_duration = (stop_timestamp - start_timestamp).total_seconds()
    # Round to nearest 100ms (0.1s) and format with 1 decimal place, right-justified with 5 spaces
    rounded_duration = round(pair_duration, 1)

    # Always include full date and time in output
    start_time_str = start_timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    stop_time_str = stop_timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    duration_info = (
        f"{start_time_str}: Start -> Stop: {stop_time_str}: "
        f"{rounded_duration:>5.1f}s"
    )

    # Annotate with matched stop pattern if it was not the first alternative
    if isinstance(stop_pattern, list) and stop_match_idx and stop_match_idx > 0:
        duration_info += f"  [{stop_pattern[stop_match_idx]}]"

    # Return tuple with both start and stop timestamps for proper timing calculation
    return ((start_timestamp, stop_timestamp), duration_info, start_filename)


def process_timeline_block(args, block, start_date, settings, variables=None):
    """Process a single timeline block (uses 'timeline:' field).

    Timeline blocks collect ALL matches for ALL specified patterns from the target
    log files, then sort them chronologically by timestamp. Unlike pattern blocks
    which search sequentially, timeline blocks search independently for each pattern.

    Args:
        args: Command line arguments containing logs_dir and verbose level
        block: Timeline block dictionary with 'timeline' and 'file' fields
        start_date: Starting timestamp for search (datetime object)
        settings: Model settings containing timeline_patterns for named references

    Returns:
        List of (timestamp, log_line, actual_filename) tuples sorted by timestamp.
        Empty list if no matches found.

    Behavior:
        - Searches for ALL occurrences of ALL patterns in timeline
        - No assumptions about pattern order in timeline definition
        - Results sorted chronologically regardless of pattern order
        - Supports both direct pattern lists and named pattern references
        - All patterns support full regex syntax
    """
    if not block.get('timeline'):
        return []

    # Skip controller-only blocks if hostname doesn't contain 'controller'
    current_hostname = getattr(args, 'current_processing_hostname', getattr(args, 'hostname', 'controller-0'))
    # Check block-level controller setting, fall back to model-level setting
    controller_only = block.get('controller', getattr(args, 'controller_setting', False))
    if controller_only and 'controller' not in current_hostname:
        vlog2(f"Skipping controller-only block '{block['label']}' for non-controller host {current_hostname}")
        return []

    # Resolve timeline patterns (handle named references)
    timeline_patterns = resolve_timeline_patterns(block['timeline'], settings)

    # Apply variable substitution to resolved patterns
    if variables is None:
        variables = {'hostname': getattr(args, 'hostname', 'controller-0')}
        if hasattr(args, 'variables') and args.variables:
            for var_pair in args.variables:
                if '=' in var_pair:
                    key, value = var_pair.split('=', 1)
                    variables[key] = value
    variables['label'] = block.get('label', '')

    timeline_patterns = apply_timeline_variable_substitution(timeline_patterns, variables)

    all_matches = []
    for pattern in timeline_patterns:
        if isinstance(pattern, list):
            # Handle OR patterns - search for each alternative
            for alt_pattern in pattern:
                matches = find_pattern_in_files_all_matches(
                    args.logs_dir, block['file'], alt_pattern, start_date, args
                )
                all_matches.extend(matches)
        else:
            # Handle single pattern
            matches = find_pattern_in_files_all_matches(
                args.logs_dir, block['file'], pattern, start_date, args
            )
            all_matches.extend(matches)

    # Sort by timestamp
    all_matches.sort(key=lambda x: x[0])
    return all_matches


def process_blocks_auto_detect(args,
                               blocks,
                               start_date,
                               max_time_delta=45,
                               variables=None,
                               settings=None):
    """Process blocks SEQUENTIALLY with automatic type detection
    and time tolerance reordering.

    This function processes each block based on its format:
    - Blocks with 'timeline' fields are processed as timeline blocks
    - Blocks with 'start'/'stop' fields are processed as pair blocks
    - Blocks with 'patterns' fields are processed as pattern blocks
    - Blocks are processed IN ORDER - each block must be found AFTER the previous block
    - Maintains unified output format across mixed block types
    - Reorders adjacent blocks if timestamp difference is within time_tolerance
    Returns: (success, start_time, end_time, patterns_found, optional_warnings, structured_results) tuple
    """
    # Set sequential mode flag to enable sequential processing constraints
    args._sequential_mode = True

    start_time = None
    end_time = None  # Track actual end time (for pair blocks, this is the last stop time)
    prev_timestamp = start_date
    patterns_found = 0
    temp_results = []  # Collect results for potential reordering
    seq_counter = 0
    first_non_timeline_block = True  # Track first non-timeline block
    first_pattern_found = False  # Track if we've found the first pattern match
    has_pair_blocks = (getattr(args, 'model_type', None) == ModelType.PAIR)
    optional_warnings = []  # Track optional block warnings for summary
    structured_results = []  # Structured result objects for dedicated writers

    # Load settings for timeline pattern resolution
    if settings is None:
        _, settings, _ = load_model(args.model_file)

    # Get current hostname for controller filtering
    current_hostname = getattr(args, 'current_processing_hostname', getattr(args, 'hostname', 'controller-0'))

    for block in blocks:
        if not block.get('file'):
            continue

        # Skip controller-only blocks if hostname doesn't contain 'controller'
        # Check block-level controller setting, fall back to model-level setting
        controller_only = block.get('controller', getattr(args, 'controller_setting', False))
        if controller_only and 'controller' not in current_hostname:
            vlog2(f"Skipping controller-only block '{block['label']}' for non-controller host {current_hostname}")
            continue

        result = None

        # Auto-detect block type and process accordingly
        if 'timeline' in block:
            # Timeline block - process all matches and merge
            timeline_matches = process_timeline_block(args, block, start_date, settings, variables)
            if timeline_matches:
                patterns_found += len(timeline_matches)
                # Add all timeline matches to temp_results
                for timestamp, log_line, actual_filename in timeline_matches:
                    result_data = {
                        'timestamp': timestamp,
                        'block': block,
                        'data': log_line,
                        'actual_filename': actual_filename,
                        'seq': seq_counter
                    }
                    if block.get('context_before') is not None:
                        before, after = extract_context_lines(
                            args.logs_dir, actual_filename, log_line,
                            block['context_before'], block['context_after']
                        )
                        result_data['context'] = (before, after)
                    temp_results.append(result_data)
                    seq_counter += 1
            # Timeline blocks never fail - they just collect what's available
            # No error handling needed for timeline blocks with no matches
            block_type = 'timeline'
            continue
        elif 'start' in block and 'stop' in block:
            # Pair block - use block-level max_time_delta if present, otherwise global
            # Automatically ignore max_time_delta for the very first pattern match only
            if not first_pattern_found:
                block_max_time_delta = None  # No time constraint for first pattern search
                first_non_timeline_block = False
            else:
                # Use block-level max_time_delta if explicitly set, otherwise use global max_time_delta
                block_max_time_delta = block.get('max_time_delta', max_time_delta)
            result = process_pair_block(
                args,
                block,
                prev_timestamp
                if prev_timestamp
                else start_date, block_max_time_delta)
            block_type = 'pair'
        elif 'patterns' in block:
            # Pattern block - use block-level max_time_delta if present, otherwise global
            # Automatically ignore max_time_delta for the very first pattern match only
            if not first_pattern_found:
                block_max_time_delta = None  # No time constraint for first pattern search
                first_non_timeline_block = False
            else:
                # Use block-level max_time_delta if explicitly set, otherwise use global max_time_delta
                block_max_time_delta = block.get('max_time_delta', max_time_delta)
            result = process_pattern_block(
                args, block, prev_timestamp if prev_timestamp else start_date,
                block_max_time_delta
            )
            block_type = 'pattern'

            # Pattern blocks return a single result (one pattern per block after expansion)
            if result is not None:
                # CRITICAL: Set first_pattern_found BEFORE continue to ensure subsequent blocks
                # get proper max_time_delta constraints instead of None (which bypasses timeout)
                first_pattern_found = True  # Mark that we've found the first pattern
                for timestamp, data, actual_filename, override_hostname in result:
                    patterns_found += 1
                    if end_time is None or timestamp > end_time:
                        end_time = timestamp
                    result_data = {
                        'timestamp': timestamp,
                        'block': block,
                        'data': data,
                        'actual_filename': actual_filename,
                        'seq': seq_counter,
                        'override_hostname': override_hostname
                    }
                    if block.get('context_before') is not None:
                        search_dir = getattr(args, 'logs_dir', '.')
                        before, after = extract_context_lines(
                            search_dir, actual_filename, data,
                            block['context_before'], block['context_after']
                        )
                        result_data['context'] = (before, after)
                    temp_results.append(result_data)
                    seq_counter += 1
                    prev_timestamp = timestamp
                continue

        else:
            vlog1(f"⚠️ Block '{block['label']}' has neither 'timeline', 'patterns' nor 'start'/'stop' fields")
            continue

        if result is not None:
            first_pattern_found = True  # Mark that we've found the first pattern
            # Handle tuple return from pair blocks (start_time, stop_time)
            if isinstance(result[0], tuple):
                timestamp_tuple, data, actual_filename = result
                start_ts, stop_ts = timestamp_tuple
                timestamp = start_ts  # Use start time for sequencing
                # Track the maximum stop time across all pair blocks
                if end_time is None or stop_ts > end_time:
                    end_time = stop_ts
                has_pair_blocks = True  # redundant but kept for clarity
            else:
                timestamp, data, actual_filename = result
                # For non-pair blocks, update end_time if this is later
                if end_time is None or timestamp > end_time:
                    end_time = timestamp

            patterns_found += 1

            # Store result for potential reordering
            result_data = {
                'timestamp': timestamp,
                'block': block,
                'data': data,
                'actual_filename': actual_filename,
                'seq': seq_counter
            }
            # Stash pair timestamps for structured results
            if isinstance(result[0], tuple):
                result_data['start_ts'] = start_ts
                result_data['stop_ts'] = stop_ts
            temp_results.append(result_data)
            seq_counter += 1

            # For pair blocks, advance prev_timestamp to start time so the
            # next block searches from the previous block's start (not stop).
            # The stop time is only used for max_time_delta within the pair.
            if isinstance(result[0], tuple):
                prev_timestamp = start_ts
            else:
                prev_timestamp = timestamp
        elif block.get('present', False):
            # Present block - silently skip if not found, continue from last match timestamp
            # No warning, no error output, just continue processing
            vlog2(f"Present block '{block['label']}' not found, continuing from last timestamp")
            continue
        elif not block.get('optional', getattr(args, 'optional_setting', False)) \
                and not (getattr(args, 'force', False) and first_pattern_found):
            # Required block failed - output collected results first
            if temp_results:
                reorder_and_output_results(
                    temp_results,
                    args,
                    structured_results=structured_results)

                start_time = temp_results[0]['timestamp'] if temp_results else start_time
                prev_timestamp = temp_results[-1]['timestamp'] if temp_results else prev_timestamp
                temp_results = []  # Clear after output

            attempted_file = block['file'][0] if isinstance(block['file'], list) else block['file']
            full_file_path = os.path.join(args.logs_dir, attempted_file)

            if 'patterns' in block:
                pattern = block['patterns'][0] if block['patterns'] else 'unknown pattern'
                print(f"❌ Error: block '{block['label']}' pattern '{pattern}' not found in '{full_file_path}'")
            elif 'start' in block and 'stop' in block:
                start_pattern = block.get('start', 'unknown start pattern')
                stop_pattern = block.get('stop', 'unknown stop pattern')
                print(f"❌ Error: block '{block['label']}' start/stop patterns "
                      f"start='{start_pattern}', stop='{stop_pattern}' not found in '{full_file_path}'")
            elif 'timeline' in block:
                timeline_pattern = block.get('timeline', 'unknown timeline pattern')
                print(f"❌ Error: block '{block['label']}' timeline pattern "
                      f"'{timeline_pattern}' not found in '{full_file_path}'")
            else:
                print(f"❌ Error: block '{block['label']}' pattern not found in '{full_file_path}'")
            return False, start_time, prev_timestamp, patterns_found, optional_warnings, structured_results
        else:
            # Optional block - skip silently or with message
            attempted_file = block['file'][0] if isinstance(block['file'], list) else block['file']
            # Get full file path for warning message
            full_file_path = os.path.join(args.logs_dir, attempted_file)

            if 'timeline' in block:
                timeline_pattern = block.get('timeline', 'unknown timeline pattern')
                truncated_data = (f"⚠️ Warn: block '{block['label']}' timeline pattern "
                                  f"'{timeline_pattern}' not found in '{full_file_path}'")
            elif 'patterns' in block:
                # Get the pattern for warning message
                pattern = block['patterns'][0] if block['patterns'] else 'unknown pattern'
                truncated_data = (f"⚠️ Warn: block '{block['label']}' pattern "
                                  f"'{pattern}' not found in '{full_file_path}'")
            elif 'start' in block and 'stop' in block:
                start_pattern = block.get('start', 'unknown start pattern')
                stop_pattern = block.get('stop', 'unknown stop pattern')
                truncated_data = (f"⚠️ Warn: block '{block['label']}' start/stop patterns "
                                  f"start='{start_pattern}', stop='{stop_pattern}' not found in '{full_file_path}'")
            else:
                truncated_data = f"⚠️ Warn: block '{block['label']}' pattern not found in '{full_file_path}'"
            warning_msg = truncated_data

            # Store warning for summary
            optional_warnings.append(warning_msg)

            warning_timestamp = prev_timestamp or start_date or datetime.min
            # Use override hostname for output if block has override
            warning_hostname = block.get('override', current_hostname) if block.get('override') else current_hostname
            temp_results.append({
                'timestamp': warning_timestamp,
                'block': block,
                'data': truncated_data,
                'actual_filename': attempted_file,
                'seq': seq_counter,
                'is_warning': True,
                'override_hostname': warning_hostname
            })
            seq_counter += 1

    # Process collected results with reordering
    if temp_results:
        reorder_and_output_results(
            temp_results,
            args,
            structured_results=structured_results)

        # Set start_time from first result if not already set
        if start_time is None:
            start_time = temp_results[0]['timestamp'] if temp_results else start_time
        # Don't overwrite end_time if we're tracking pair block stop times
        if not has_pair_blocks:
            prev_timestamp = temp_results[-1]['timestamp'] if temp_results else prev_timestamp
            end_time = prev_timestamp

    # For pair block models, use end_time (maximum stop time); otherwise use prev_timestamp
    final_end_time = end_time if end_time else prev_timestamp

    return patterns_found > 0, start_time, final_end_time, patterns_found, optional_warnings, structured_results


def reorder_and_output_results(temp_results, args,
                               structured_results=None):
    """Sort results chronologically by timestamp and output them.
    This ensures final output is ordered strictly by log time.
    """
    if not temp_results:
        return

    # Full chronological sort (stable for equal timestamps)
    sorted_results = sorted(temp_results, key=lambda x: (x['timestamp'], x.get('seq', 0)))
    _output_collected_results(sorted_results, None, args,
                              structured_results=structured_results)


def _output_collected_results(temp_results, start_time_override, args,
                              structured_results=None):
    """Build structured results and print console output.
    """
    if not temp_results:
        return

    # Check if this is a timeline model to suppress console output
    is_timeline_model = (getattr(args, 'model_type', None) == ModelType.TIMELINE)

    first_real_timestamp = None
    for entry in temp_results:
        if not entry.get('is_warning'):
            first_real_timestamp = entry['timestamp']
            break

    start_time = start_time_override or first_real_timestamp
    prev_timestamp = None

    # Get current hostname being processed (updated for each host in bundle mode)
    current_hostname = getattr(args, 'current_processing_hostname', getattr(args, 'hostname', None))
    # Don't add hostname prefix for system profile files
    use_hostname = current_hostname if not getattr(args, '_is_system_profile', False) else None

    for i, result_data in enumerate(temp_results):
        timestamp = result_data['timestamp']
        block = result_data['block']
        data = result_data['data']
        actual_filename = result_data['actual_filename']

        # Use override hostname if present, otherwise use current hostname
        display_hostname = result_data.get('override_hostname', use_hostname)

        if result_data.get('is_warning'):
            delta_formatted = "??:??:??.???"
        else:
            if prev_timestamp is None:
                delta = 0.0
            else:
                delta = (timestamp - prev_timestamp).total_seconds()

            delta_formatted = format_duration(delta)
            prev_timestamp = timestamp

        # Build structured result
        if structured_results is not None:
            hostname = display_hostname or ''
            is_warn = bool(result_data.get('is_warning'))
            warn_text = data if is_warn else None
            if 'start_ts' in result_data:
                dur = (result_data['stop_ts'] - result_data['start_ts']).total_seconds()
                structured_results.append(PairResult(
                    start_timestamp=str(result_data['start_ts']),
                    stop_timestamp=str(result_data['stop_ts']),
                    duration_seconds=dur,
                    block_label=block['label'],
                    actual_filename=actual_filename,
                    hostname=hostname,
                    is_warning=is_warn,
                    warning_text=warn_text))
            elif 'timeline' in block:
                structured_results.append(TimelineResult(
                    timestamp=str(timestamp),
                    block_label=block['label'],
                    log_line=data,
                    actual_filename=actual_filename,
                    hostname=hostname,
                    context=result_data.get('context')))
            else:
                structured_results.append(PatternResult(
                    timestamp=str(timestamp),
                    block_label=block['label'],
                    log_line=data,
                    actual_filename=actual_filename,
                    hostname=hostname,
                    is_warning=is_warn,
                    warning_text=warn_text,
                    context=result_data.get('context')))

        # Console output for all models (timeline models need this for .timeline.log file)
        filename_padded = f"{actual_filename:<10}"
        label_padded = f"{block['label']:<25}"
        truncated_data = data[:args.max_log_length]
        result_line = format_result_line(
            delta_formatted, label_padded, filename_padded, truncated_data, display_hostname
        )
        print(result_line)


def extract_context_lines(log_dir, filename, matched_line,
                          context_before, context_after):
    """Extract surrounding lines around a matched line in a log file.

    Reads the file, finds the matched line, and returns the N lines
    before and M lines after it.

    Args:
        log_dir: Directory containing the log file
        filename: Log filename (relative to log_dir)
        matched_line: The matched log line text (stripped)
        context_before: Number of lines to capture before the match
        context_after: Number of lines to capture after the match

    Returns:
        (before_lines, after_lines) tuple of string lists,
        or ([], []) if the matched line cannot be found.
    """
    from collections import deque

    filepath = os.path.join(log_dir, filename)
    if not os.path.exists(filepath):
        return [], []

    is_gzipped = filename.endswith('.gz')
    if is_gzipped:
        open_func = gzip.open
        mode = 'rt'
    else:
        open_func = open
        mode = 'r'

    try:
        with open_func(filepath, mode, encoding='utf-8', errors='ignore') as f:
            ring = deque(maxlen=context_before)
            for line in f:
                stripped = line.rstrip('\n\r')
                if matched_line in stripped:
                    before = list(ring)
                    after = []
                    for _ in range(context_after):
                        nxt = f.readline()
                        if not nxt:
                            break
                        after.append(nxt.rstrip('\n\r'))
                    return before, after
                ring.append(stripped)
    except (IOError, OSError, gzip.BadGzipFile):
        pass

    return [], []
