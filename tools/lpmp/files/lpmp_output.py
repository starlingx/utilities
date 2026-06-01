#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
LPMP Output Writers Module

Dedicated output formatting and file writing functions for each model type.
Each model type (pattern, pair, timeline) has its own writers that consume
structured result data (PatternResult, PairResult, TimelineResult) instead
of rendered strings.

Phase 5a: Pattern writers
Phase 6a: Pair writers
Phase 7a: Timeline writers
Phase 8a: Merge/system writers
"""

import csv
from datetime import datetime
import os
import sys

sys.dont_write_bytecode = True
# cspell:ignore lpmp

from lpmp_utils import format_duration              # noqa: E402
from lpmp_utils import format_result_line           # noqa: E402
from lpmp_utils import PairResult                   # noqa: E402
from lpmp_utils import parse_duration_to_seconds    # noqa: E402
from lpmp_utils import PatternResult                # noqa: E402
from lpmp_utils import sanitize_label_for_filename  # noqa: E402
from lpmp_utils import TimelineResult               # noqa: E402
from lpmp_utils import vlog2                        # noqa: E402


# Column widths matching lpmptool constants
HOSTNAME_COLUMN_WIDTH = 12
LOG_FILE_COLUMN_WIDTH = 30


def _parse_ts(timestamp):
    """Parse a timestamp that may be a string or datetime."""
    if isinstance(timestamp, str):
        return datetime.fromisoformat(timestamp)
    return timestamp


def write_summary_stats(f, samples, avg_duration, min_duration, max_duration,
                        title="Overall Summary"):
    """Write summary stats block to file.

    Common format used by pattern summaries, pair summaries, and block profiles.
    """
    f.write(f"{title}\n")
    f.write("-" * len(title) + "\n")
    f.write(f"Samples: {samples}\n")
    f.write(f"Average: {format_duration(avg_duration)}\n")
    f.write(f"Maximum: {format_duration(max_duration)}\n")
    f.write(f"Minimum: {format_duration(min_duration)}\n\n")


# ---------------------------------------------------------------------------
# Pattern model output writers
# ---------------------------------------------------------------------------

def write_pattern_csv(output_path, structured_results, pass_summaries):
    """Write pattern model profile.timing.csv from structured results.

    Args:
        output_path: Full path to the CSV output file.
        structured_results: List of PatternResult objects.
        pass_summaries: List of [pass_label, duration, info, '', ''] lists.
    """
    try:
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Cumulative(s)', 'Delta(HH:MM:SS)',
                'Block Label', 'Log File', 'Data',
            ])

            start_ts = None
            prev_ts = None

            for r in structured_results:
                if r.is_warning:
                    delta_fmt = "??:??:??.???"
                    cumulative = (
                        (prev_ts - start_ts).total_seconds()
                        if start_ts and prev_ts else 0.0
                    )
                    data = r.warning_text or ''
                else:
                    ts = _parse_ts(r.timestamp)
                    if start_ts is None:
                        start_ts = ts
                    if prev_ts is None:
                        delta_fmt = format_duration(0.0)
                        cumulative = 0.0
                    else:
                        delta_fmt = format_duration((ts - prev_ts).total_seconds())
                        cumulative = (ts - start_ts).total_seconds()
                    prev_ts = ts
                    data = r.log_line or ''

                writer.writerow([
                    cumulative, delta_fmt,
                    r.block_label, r.actual_filename, data,
                ])

            for ps in pass_summaries:
                writer.writerow(ps)

        vlog2(f"Pattern CSV written: {output_path}")
    except IOError as e:
        print(f"Error writing pattern CSV {output_path}: {e}", file=sys.stderr)


def write_pattern_summary(output_path, structured_results,
                          pass_summaries, optional_warnings=None):
    """Write pattern model summary.timing from structured results.

    Args:
        output_path: Full path to the summary.timing file.
        structured_results: List of PatternResult objects.
        pass_summaries: List of pass summary strings (e.g. "✅ Pass 1 ...").
        optional_warnings: List of warning strings from profile.timing.
    """
    if optional_warnings is None:
        optional_warnings = []

    # Extract durations from successful passes only (exclude ❌ failed passes)
    durations = []
    for line in pass_summaries:
        if '❌' in line:
            continue
        parts = line.split()
        # Format: "✅ Pass 1       HH:MM:SS.fff hostname ..."
        if len(parts) >= 4:
            d = parse_duration_to_seconds(parts[3])
            if d is not None:
                durations.append(d)

    samples = len(durations)
    if samples > 0:
        avg_d = sum(durations) / samples
        min_d = min(durations)
        max_d = max(durations)
    else:
        avg_d = min_d = max_d = 0

    try:
        with open(output_path, 'w') as f:
            write_summary_stats(f, samples, avg_d, min_d, max_d)

            # Write pass summary lines that mention patterns
            for line in pass_summaries:
                if 'patterns' in line:
                    f.write(line + '\n')

            # Write optional warnings
            for warn in optional_warnings:
                if '⚠️ Warn:' in warn or '❌ Error:' in warn:
                    f.write(' ' * 50 + warn + '\n')

        vlog2(f"Pattern summary written: {output_path}")
    except IOError as e:
        print(f"Error writing pattern summary {output_path}: {e}", file=sys.stderr)


def write_pattern_block_profile(output_dir, blocks, structured_results):
    """Write per-block profile files for pattern blocks with profile: true.

    Args:
        output_dir: Directory to write block profile files.
        blocks: List of block dicts from the model.
        structured_results: List of PatternResult objects.
    """
    for block in blocks:
        if not block.get('profile', False):
            continue

        label = block['label']
        filename = sanitize_label_for_filename(label) + '.timing'
        filepath = os.path.join(output_dir, filename)

        # Filter results for this block (non-warning only)
        block_results = [
            r for r in structured_results
            if isinstance(r, PatternResult)
            and r.block_label == label
            and not r.is_warning
        ]

        if not block_results:
            continue

        # Build set of block_results for fast lookup
        block_result_set = set(id(r) for r in block_results)

        # Compute per-pass delta: time from preceding result to this block result
        deltas = []
        for i, r in enumerate(structured_results):
            if id(r) not in block_result_set:
                continue
            # Find preceding non-warning result
            prev_ts = None
            for j in range(i - 1, -1, -1):
                prev_r = structured_results[j]
                if not prev_r.is_warning:
                    prev_ts = _parse_ts(prev_r.timestamp)
                    break
            ts = _parse_ts(r.timestamp)
            if prev_ts is not None:
                deltas.append((ts - prev_ts).total_seconds())

        samples = len(deltas)
        if samples > 0:
            avg_d = sum(deltas) / samples
            min_d = min(deltas)
            max_d = max(deltas)
        else:
            avg_d = min_d = max_d = 0

        try:
            with open(filepath, 'w') as f:
                write_summary_stats(f, samples, avg_d, min_d, max_d,
                                    title="Block Timing Summary")

                f.write(
                    "Delta(HH:MM:SS)\tBlock Label               "
                    "\tLog File  \tData\n"
                )
                f.write(
                    "-------------\t---------------------------"
                    "\t------------\t--------\n"
                )

                for i, r in enumerate(structured_results):
                    if id(r) not in block_result_set:
                        continue
                    ts = _parse_ts(r.timestamp)
                    # Find preceding non-warning result for delta
                    prev_ts = None
                    for j in range(i - 1, -1, -1):
                        prev_r = structured_results[j]
                        if not prev_r.is_warning:
                            prev_ts = _parse_ts(prev_r.timestamp)
                            break
                    delta_secs = (ts - prev_ts).total_seconds() if prev_ts else 0.0
                    delta_fmt = format_duration(delta_secs)

                    line = (
                        f"{delta_fmt:>12}\t"
                        f"{r.block_label:<25}\t"
                        f"{r.actual_filename:<30}\t"
                        f"{r.log_line}"
                    )
                    f.write(line + '\n')

            vlog2(f"Pattern block profile written: {filepath}")
        except IOError as e:
            print(f"Error writing block profile {filepath}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Pair model output writers
# ---------------------------------------------------------------------------

def write_pair_csv(output_path, structured_results, pass_summaries):
    """Write pair model profile.timing.csv from structured results.

    Args:
        output_path: Full path to the CSV output file.
        structured_results: List of PairResult (and possibly PatternResult) objects.
        pass_summaries: List of [pass_label, duration, info, '', ''] lists.
    """
    try:
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Cumulative(s)', 'Delta(HH:MM:SS)',
                'Block Label', 'Log File', 'Data',
            ])

            start_ts = None
            prev_ts = None

            for r in structured_results:
                if r.is_warning:
                    delta_fmt = "??:??:??.???"
                    cumulative = (
                        (prev_ts - start_ts).total_seconds()
                        if start_ts and prev_ts else 0.0
                    )
                    data = r.warning_text or ''
                elif isinstance(r, PairResult):
                    s = _parse_ts(r.start_timestamp)
                    e = _parse_ts(r.stop_timestamp)
                    if start_ts is None:
                        start_ts = s
                    if prev_ts is None:
                        delta_fmt = format_duration(0.0)
                        cumulative = 0.0
                    else:
                        delta_fmt = format_duration((s - prev_ts).total_seconds())
                        cumulative = (s - start_ts).total_seconds()
                    prev_ts = s
                    start_str = s.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    stop_str = e.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    rounded = round(r.duration_seconds, 1)
                    data = f"{start_str}: Start -> Stop: {stop_str}: {rounded:>5.1f}s"
                else:
                    ts = _parse_ts(r.timestamp)
                    if start_ts is None:
                        start_ts = ts
                    if prev_ts is None:
                        delta_fmt = format_duration(0.0)
                        cumulative = 0.0
                    else:
                        delta_fmt = format_duration((ts - prev_ts).total_seconds())
                        cumulative = (ts - start_ts).total_seconds()
                    prev_ts = ts
                    data = r.log_line or ''

                writer.writerow([
                    cumulative, delta_fmt,
                    r.block_label, r.actual_filename, data,
                ])

            for ps in pass_summaries:
                writer.writerow(ps)

        vlog2(f"Pair CSV written: {output_path}")
    except IOError as e:
        print(f"Error writing pair CSV {output_path}: {e}", file=sys.stderr)


def write_pair_summary(output_path, structured_results,
                       pass_summaries, optional_warnings=None):
    """Write pair model summary.timing from structured results.

    Includes:
    - Overall Summary (from pass durations)
    - Per-Block Timing Summary (avg/min/max per service)
    - Per-Pair Block Start/Stop Times grouped by run

    Args:
        output_path: Full path to the summary.timing file.
        structured_results: List of PairResult (and possibly PatternResult) objects.
        pass_summaries: List of pass summary strings.
        optional_warnings: List of warning strings.
    """
    if optional_warnings is None:
        optional_warnings = []

    # Extract profile durations from successful passes only (exclude ❌ failed passes)
    profile_durations = []
    for line in pass_summaries:
        if '❌' in line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            d = parse_duration_to_seconds(parts[1])
            if d is not None:
                profile_durations.append(d)

    # Collect per-service stats from structured results
    service_stats = {}  # label -> list of durations
    for r in structured_results:
        if isinstance(r, PairResult) and not r.is_warning:
            service_stats.setdefault(r.block_label, []).append(r.duration_seconds)

    try:
        with open(output_path, 'w') as f:
            # Overall Summary
            if profile_durations:
                samples = len(profile_durations)
                write_summary_stats(
                    f, samples,
                    sum(profile_durations) / samples,
                    min(profile_durations),
                    max(profile_durations),
                )
            else:
                all_durs = [d for durs in service_stats.values() for d in durs]
                if all_durs:
                    write_summary_stats(
                        f, len(all_durs),
                        sum(all_durs) / len(all_durs),
                        min(all_durs),
                        max(all_durs),
                    )

            # Per-Block Timing Summary
            f.write("Per-Block Timing Summary:\n")
            f.write("Block Label                   Avg:        Min:        Max:\n")
            f.write("-" * 60 + "\n")

            for label in sorted(service_stats.keys()):
                durs = service_stats[label]
                avg_s = f"{round(sum(durs) / len(durs), 1)}s"
                min_s = f"{round(min(durs), 1)}s"
                max_s = f"{round(max(durs), 1)}s"
                f.write(f"{label:<29} {avg_s:>8} {min_s:>8} {max_s:>8}\n")

            # Per-Pair Block Start/Stop Times grouped by pass
            if pass_summaries:
                f.write("\nPer-Pair Block Start/Stop Times:\n")
                f.write(
                    "Delta(HH:MM:SS) Hostname         "
                    "Block Label                   "
                    "Start Time                 "
                    "Stop Time               "
                    "Duration\n"
                )
                f.write("-" * 122 + "\n")

                prev_stop = None
                for r in structured_results:
                    if r.is_warning:
                        delta_pad = f"{'??:??:??.???':<15}"
                        host_pad = f"{r.hostname:<16}"
                        label_pad = f"{r.block_label:<29}"
                        msg = r.warning_text or ''
                        if 'not found' in msg:
                            msg = msg[:msg.index('not found') + 9]
                        f.write(f"{delta_pad} {host_pad} {label_pad} {msg}\n")
                    elif isinstance(r, PairResult):
                        start = _parse_ts(r.start_timestamp)
                        stop = _parse_ts(r.stop_timestamp)
                        delta_fmt = format_duration(
                            0.0 if prev_stop is None else (start - prev_stop).total_seconds()
                        )
                        prev_stop = start
                        delta_pad = f"{delta_fmt:<15}"
                        host_pad = f"{r.hostname:<16}"
                        label_pad = f"{r.block_label:<29}"
                        start_pad = f"{start.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]:<23}"
                        stop_pad = f"{stop.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]:<23}"
                        dur_str = f"{round(r.duration_seconds, 1):.1f}s"
                        f.write(
                            f"{delta_pad} {host_pad} {label_pad} "
                            f"{start_pad} ->{stop_pad} {dur_str:>8}\n"
                        )
                    else:
                        # Trigger pattern result
                        ts = _parse_ts(r.timestamp)
                        delta_fmt = format_duration(
                            0.0 if prev_stop is None else (ts - prev_stop).total_seconds()
                        )
                        prev_stop = ts
                        delta_pad = f"{delta_fmt:<15}"
                        host_pad = f"{r.hostname:<16}"
                        label_pad = f"{r.block_label:<29}"
                        f.write(f"{delta_pad} {host_pad} {label_pad} {r.log_line}\n")

                # Write pass summaries as separators
                for ps in pass_summaries:
                    f.write(f"{ps}\n\n")
                    f.write("-" * 63 + "\n\n")
            else:
                f.write("\nNo timing data found.\n")

        vlog2(f"Pair summary written: {output_path}")
    except IOError as e:
        print(f"Error writing pair summary {output_path}: {e}", file=sys.stderr)


def write_pair_block_profile(output_dir, blocks, structured_results):
    """Write per-block profile files for pair blocks with profile: true.

    Args:
        output_dir: Directory to write block profile files.
        blocks: List of block dicts from the model.
        structured_results: List of PairResult (and possibly PatternResult) objects.
    """
    for block in blocks:
        if not block.get('profile', False):
            continue

        label = block['label']
        filename = sanitize_label_for_filename(label) + '.timing'
        filepath = os.path.join(output_dir, filename)

        # Filter results for this block (non-warning only)
        block_results = [
            r for r in structured_results
            if isinstance(r, PairResult)
            and r.block_label == label
            and not r.is_warning
        ]

        if not block_results:
            continue

        durations = [r.duration_seconds for r in block_results]
        samples = len(durations)
        avg_d = sum(durations) / samples
        min_d = min(durations)
        max_d = max(durations)

        try:
            with open(filepath, 'w') as f:
                write_summary_stats(f, samples, avg_d, min_d, max_d,
                                    title="Block Timing Summary")

                f.write(
                    "Delta(HH:MM:SS)\tBlock Label               "
                    "\tLog File  \tData\n"
                )
                f.write(
                    "-------------\t---------------------------"
                    "\t------------\t--------\n"
                )

                prev_stop = None
                for r in block_results:
                    start = _parse_ts(r.start_timestamp)
                    stop = _parse_ts(r.stop_timestamp)
                    delta_fmt = format_duration(
                        0.0 if prev_stop is None
                        else (start - prev_stop).total_seconds()
                    )
                    prev_stop = start

                    start_str = start.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    stop_str = stop.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    rounded = round(r.duration_seconds, 1)
                    data = f"{start_str}: Start -> Stop: {stop_str}: {rounded:>5.1f}s"

                    line = (
                        f"{delta_fmt:>12}\t"
                        f"{r.block_label:<25}\t"
                        f"{r.actual_filename:<30}\t"
                        f"{data}"
                    )
                    f.write(line + '\n')

            vlog2(f"Pair block profile written: {filepath}")
        except IOError as e:
            print(f"Error writing pair block profile {filepath}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Timeline model output writers
# ---------------------------------------------------------------------------

def write_timeline_csv(output_path, structured_results, pass_summaries):
    """Write timeline model profile.timeline.log.csv from structured results.

    Args:
        output_path: Full path to the CSV output file.
        structured_results: List of TimelineResult objects.
        pass_summaries: List of [pass_label, duration, info, '', ''] lists.
    """
    try:
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Cumulative(s)', 'Delta(HH:MM:SS)',
                'Block Label', 'Log File', 'Data',
            ])

            start_ts = None
            prev_ts = None

            for r in structured_results:
                ts = _parse_ts(r.timestamp)
                if start_ts is None:
                    start_ts = ts
                if prev_ts is None:
                    delta_fmt = format_duration(0.0)
                    cumulative = 0.0
                else:
                    delta_fmt = format_duration((ts - prev_ts).total_seconds())
                    cumulative = (ts - start_ts).total_seconds()
                prev_ts = ts

                writer.writerow([
                    cumulative, delta_fmt,
                    r.block_label, r.actual_filename, r.log_line or '',
                ])

            for ps in pass_summaries:
                writer.writerow(ps)

        vlog2(f"Timeline CSV written: {output_path}")
    except IOError as e:
        print(f"Error writing timeline CSV {output_path}: {e}", file=sys.stderr)


def write_timeline_block_profile(output_dir, blocks, structured_results):
    """Write per-block profile files for timeline blocks with profile: true.

    Args:
        output_dir: Directory to write block profile files.
        blocks: List of block dicts from the model.
        structured_results: List of TimelineResult objects.
    """
    for block in blocks:
        if not block.get('profile', False):
            continue

        label = block['label']
        filename = sanitize_label_for_filename(label) + '.timing'
        filepath = os.path.join(output_dir, filename)

        block_results = [
            r for r in structured_results
            if isinstance(r, TimelineResult) and r.block_label == label
        ]

        if not block_results:
            continue

        deltas = []
        prev_ts = None
        for r in block_results:
            ts = _parse_ts(r.timestamp)
            if prev_ts is not None:
                deltas.append((ts - prev_ts).total_seconds())
            prev_ts = ts

        samples = len(deltas)
        if samples > 0:
            avg_d = sum(deltas) / samples
            min_d = min(deltas)
            max_d = max(deltas)
        else:
            avg_d = min_d = max_d = 0

        try:
            with open(filepath, 'w') as f:
                write_summary_stats(f, samples, avg_d, min_d, max_d,
                                    title="Block Timing Summary")

                f.write(
                    "Delta(HH:MM:SS)\tBlock Label               "
                    "\tLog File  \tData\n"
                )
                f.write(
                    "-------------\t---------------------------"
                    "\t------------\t--------\n"
                )

                prev_ts = None
                for r in block_results:
                    ts = _parse_ts(r.timestamp)
                    delta_fmt = format_duration(
                        0.0 if prev_ts is None
                        else (ts - prev_ts).total_seconds()
                    )
                    prev_ts = ts

                    line = (
                        f"{delta_fmt:>12}\t"
                        f"{r.block_label:<25}\t"
                        f"{r.actual_filename:<30}\t"
                        f"{r.log_line}"
                    )
                    f.write(line + '\n')

            vlog2(f"Timeline block profile written: {filepath}")
        except IOError as e:
            print(f"Error writing timeline block profile {filepath}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# System/merge output writers (bundle mode, multi-host)
# ---------------------------------------------------------------------------

def create_pattern_system_summary(bundle_base_dir, host_list, lab_name, output_path):
    """Create system summary from per-host pattern summary.timing files.

    Reads each host's summary.timing, extracts Samples/Average/Maximum/Minimum
    and per-pass lines, then writes a combined system_summary.timing.

    Args:
        bundle_base_dir: Base directory containing per-host subdirectories.
        host_list: List of all hosts that have data.
        lab_name: Lab name for display.
        output_path: Full path to the system_summary.timing output file.
    """
    host_stats = {}

    for hostname in host_list:
        summary_file = os.path.join(bundle_base_dir, hostname, 'summary.timing')
        if not os.path.exists(summary_file):
            host_stats[hostname] = {'warning': 'No summary.timing file found'}
            continue

        try:
            with open(summary_file, 'r') as f:
                lines = f.readlines()

            samples = avg = max_val = min_val = None
            content_lines = []
            timing_values = []

            for line in lines:
                line = line.strip()
                if line.startswith('Samples'):
                    samples = line.split(':', 1)[1].strip()
                elif line.startswith('Average'):
                    avg = line.split(':', 1)[1].strip()
                elif line.startswith('Maximum'):
                    max_val = line.split(':', 1)[1].strip()
                elif line.startswith('Minimum'):
                    min_val = line.split(':', 1)[1].strip()
                elif line.startswith('\u2705'):
                    content_lines.append(line)
                    parts = line.split()
                    if len(parts) >= 2:
                        d = parse_duration_to_seconds(parts[1])
                        if d is not None:
                            timing_values.append(d)

            if timing_values and (not avg or avg == '00:00:00.000'):
                samples = str(len(timing_values))
                avg = format_duration(sum(timing_values) / len(timing_values))
                min_val = format_duration(min(timing_values))
                max_val = format_duration(max(timing_values))

            host_stats[hostname] = {
                'samples': samples, 'average': avg,
                'maximum': max_val, 'minimum': min_val,
                'content': content_lines,
            }
        except IOError as e:
            host_stats[hostname] = {'warning': f'Error reading file: {e}'}

    _write_system_summary_file(output_path, host_list, host_stats)


def create_pair_system_summary(bundle_base_dir, host_list, lab_name, output_path):
    """Create system summary from per-host pair summary.timing files.

    Reads each host's summary.timing (pair format with Overall Summary line),
    extracts statistics, then writes a combined system_summary.timing.

    Args:
        bundle_base_dir: Base directory containing per-host subdirectories.
        host_list: List of all hosts that have data.
        lab_name: Lab name for display.
        output_path: Full path to the system_summary.timing output file.
    """
    host_stats = {}

    for hostname in host_list:
        summary_file = os.path.join(bundle_base_dir, hostname, 'summary.timing')
        if not os.path.exists(summary_file):
            host_stats[hostname] = {'warning': 'No summary.timing file found'}
            continue

        try:
            with open(summary_file, 'r') as f:
                lines = f.readlines()

            samples = avg = max_val = min_val = None
            content_lines = []

            for line in lines:
                line = line.strip()
                if line.startswith('Samples'):
                    samples = line.split(':', 1)[1].strip()
                elif line.startswith('Average'):
                    avg = line.split(':', 1)[1].strip()
                elif line.startswith('Maximum'):
                    max_val = line.split(':', 1)[1].strip()
                elif line.startswith('Minimum'):
                    min_val = line.split(':', 1)[1].strip()
                elif line.startswith('\u2705'):
                    content_lines.append(line)

            host_stats[hostname] = {
                'samples': samples, 'average': avg,
                'maximum': max_val, 'minimum': min_val,
                'content': content_lines,
            }
        except IOError as e:
            host_stats[hostname] = {'warning': f'Error reading file: {e}'}

    _write_system_summary_file(output_path, host_list, host_stats)


def _write_system_summary_file(output_path, host_list, host_stats):
    """Write system_summary.timing from collected per-host stats."""
    try:
        with open(output_path, 'w') as f:
            f.write("System Timing Summary\n")
            f.write("=" * 80 + "\n")
            f.write(f"Samples: {len(host_list)} hosts\n\n")

            header = "         "
            for hostname in host_list:
                header += f"{hostname:<17}"
            f.write(header + "\n")

            for stat_name in ['Average', 'Maximum', 'Minimum']:
                row = f"{stat_name}: "
                for hostname in host_list:
                    stats = host_stats[hostname]
                    if 'warning' in stats:
                        row += f"{'N/A':<17}"
                    else:
                        val = stats.get(stat_name.lower(), 'N/A')
                        row += f"{(val or 'N/A'):<17}"
                f.write(row + "\n")

            f.write("\n")
            f.write(
                f"{'Loop':<16} {'Delta':<13} {'Hostname':<16} "
                f"Profile     Matches\n"
            )
            f.write(
                f"{'':-<16} {'':-<13} {'':-<16} "
                f"{'':-<32}\n"
            )

            for hostname in host_list:
                stats = host_stats[hostname]
                f.write(f"\n{hostname}\n")
                if 'warning' in stats:
                    f.write(f"\u26a0\ufe0f  Warning: {stats['warning']}\n")
                else:
                    for line in stats.get('content', []):
                        f.write(line + "\n")

        vlog2(f"System summary written: {output_path}")
    except IOError as e:
        print(f"Error writing system summary {output_path}: {e}", file=sys.stderr)


def merge_timeline_profiles(host_files, output_path):
    """Merge per-host timeline profile files into a single system profile.

    Reads each host's profile.timeline.log, parses timestamps from the data
    column, and writes a merged file sorted by timestamp.

    Args:
        host_files: List of (file_path, hostname) tuples.
        output_path: Full path to the merged system_profile.timeline.log.
    """
    all_lines = []
    headers = []

    for file_path, hostname in host_files:
        if not os.path.exists(file_path):
            vlog2(f"File {file_path} not found, skipping")
            continue

        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.rstrip()
                    if not line:
                        continue
                    if line.startswith('Delta(') or line.startswith('---'):
                        if not headers:
                            headers.append(line)
                        continue
                    if line.startswith('\u2705'):
                        continue

                    ts = _extract_timestamp_from_data(line)
                    all_lines.append((ts, line))
        except IOError as e:
            vlog2(f"Error reading {file_path}: {e}")

    if not all_lines:
        vlog2("No timeline data found to merge")
        return

    all_lines.sort(key=lambda x: x[0] if x[0] is not None else datetime.max)

    try:
        with open(output_path, 'w') as f:
            for h in headers:
                f.write(h + '\n')
            for _, line in all_lines:
                f.write(line + '\n')
        vlog2(f"Merged timeline profile written: {output_path}")
    except IOError as e:
        print(f"Error writing merged timeline {output_path}: {e}", file=sys.stderr)


def _extract_timestamp_from_data(line):
    """Extract a timestamp from the data column of a timing line.
    Handles ISO, sysinv, and various custom timestamp formats.
    """
    import re as _re
    # ISO format: YYYY-MM-DDTHH:MM:SS.fff or YYYY-MM-DDTHH:MM:SS
    m = _re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?)', line)
    if m:
        try:
            return datetime.fromisoformat(m.group(1))
        except ValueError:
            pass
    # Space separator with dot millis: YYYY-MM-DD HH:MM:SS.fff
    m = _re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})', line)
    if m:
        try:
            return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            pass
    # Space separator with comma millis: YYYY-MM-DD HH:MM:SS,fff
    m = _re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})', line)
    if m:
        try:
            return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S,%f')
        except ValueError:
            pass
    # 2-digit year with dot millis: YY-MM-DD HH:MM:SS.fff
    m = _re.search(r'(\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})', line)
    if m:
        try:
            return datetime.strptime(m.group(1), '%y-%m-%d %H:%M:%S.%f')
        except ValueError:
            pass
    # Space separator no millis with trailing colon: YYYY-MM-DD HH:MM:SS:
    m = _re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}):', line)
    if m:
        try:
            return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    return None


def write_context_files(output_dir, blocks, structured_results):
    """Write per-block .context files for blocks with context: setting.

    Creates one file per block that has context_before/context_after set.
    Each match gets a section showing the surrounding log lines.
    Deduplicates matches whose log_line already appeared in a previous
    match's after_lines from the same file, avoiding near-duplicate
    context sections when the same pattern fires repeatedly within
    a single context window.

    Args:
        output_dir: Directory to write context files.
        blocks: List of block dicts from the model.
        structured_results: List of PatternResult/TimelineResult objects.
    """
    for block in blocks:
        if block.get('context_before') is None:
            continue

        label = block['label']
        filename = sanitize_label_for_filename(label) + '.context'
        filepath = os.path.join(output_dir, filename)

        # Filter results for this block that have context data
        block_results = [
            r for r in structured_results
            if (isinstance(r, (PatternResult, TimelineResult))
                and r.block_label == label
                and r.context is not None)
        ]

        if not block_results:
            continue

        # Deduplicate: skip matches already covered by a previous
        # match's after_lines in the same file.
        unique_results = []
        # Track after_lines from previously accepted matches per file
        covered_lines = {}  # filename -> set of after_line strings
        for result in block_results:
            file_covered = covered_lines.get(result.actual_filename, set())
            if result.log_line in file_covered:
                vlog2(f"Context dup skip '{result.log_line[:60]}'"
                      f" (covered by prior match in {result.actual_filename})")
                continue
            unique_results.append(result)
            _, after_lines = result.context
            if after_lines:
                covered = covered_lines.setdefault(
                    result.actual_filename, set())
                covered.update(after_lines)

        if not unique_results:
            continue

        with open(filepath, 'w') as f:
            f.write(f"Context for block: {label}\n")
            f.write(f"Context lines: {block['context_before']} before,"
                    f" {block['context_after']} after\n")
            f.write(f"Matches: {len(unique_results)}\n")
            f.write("=" * 70 + "\n\n")

            for i, result in enumerate(unique_results, 1):
                before_lines, after_lines = result.context
                f.write(f"- Match {i} in {result.actual_filename}"
                        f" at {result.timestamp} ----------------------\n")
                for line in before_lines:
                    f.write(f"  {line}\n")
                f.write(f"> {result.log_line}\n")
                for line in after_lines:
                    f.write(f"  {line}\n")
                f.write("\n")

        vlog2(f"Wrote context file: {filepath}")
