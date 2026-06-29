#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""
LPMP Graph Generator
====================

Creates resource-usage graphs from collectd.log content captured by the
LPMP collectd timeline models. Supports the three collectd profile
models shipped with LPMP:

    - collectd_cpu_usage_timeline.yaml
    - collectd_memory_usage_timeline.yaml
    - collectd_overage_timeline.yaml

Two graph styles are supported:

    --style line  (default) — numeric usage values plotted as a continuous
                  line. Used for CPU/memory percentage timelines.
    --style state — three-level step plot of alarm state transitions
                  (okay / warning / failure) for the overage timeline.

Outputs:
    <prefix>.csv  - CSV of the extracted samples
    <prefix>.png  - Rendered graph image

Dependencies: pandas (CSV/timestamp parsing), matplotlib (graph rendering).
"""

import argparse
from datetime import datetime
import os
import re
import sys

# Match lpmptool's import pattern so the same module loads for both
# in-tree development and the installed package layout.
sys.dont_write_bytecode = True
sys.path.insert(0, '/usr/lib/python3/dist-packages/lpmp')

from lpmp_utils import get_verbose_level    # noqa: E402
from lpmp_utils import set_verbose_level    # noqa: E402
from lpmp_utils import vlog1                # noqa: E402
from lpmp_utils import vlog2                # noqa: E402
from lpmp_utils import vlog3                # noqa: E402

try:
    import pandas as pd
except ImportError:
    print("Error: pandas is required for graph function. Install and retry", file=sys.stderr)
    sys.exit(1)

try:
    import matplotlib.pyplot as plt
except ImportError:
    print("Error: matplotlib is required for graph function. Install and retry", file=sys.stderr)
    sys.exit(1)


def parse_bound_date(raw, kind):
    """Parse a -s/-e bound date string the same way lpmptool does.

    Accepts: YYYY-MM-DD, YYYY-MM-DDTHH, YYYY-MM-DDTHH:MM, YYYY-MM-DDTHH:MM:SS
    (with either 'T' or a space as the date/time separator). Date-only input
    defaults to start-of-day for kind='start' and end-of-day for kind='stop'.
    Returns a naive datetime, or None if raw is falsy.
    """
    if not raw:
        return None
    date_input = raw
    # Normalize separator at position 10 to 'T' (accept space or any char)
    if len(date_input) > 10 and date_input[10] != 'T':
        date_input = date_input[:10] + 'T' + date_input[11:]
    try:
        parsed = datetime.fromisoformat(date_input)
    except ValueError:
        print(
            f"Error: Invalid {kind} date '{raw}'. "
            "Accepted formats: YYYY-MM-DD, YYYY-MM-DDTHH, "
            "YYYY-MM-DDTHH:MM, YYYY-MM-DDTHH:MM:SS",
            file=sys.stderr,
        )
        sys.exit(1)
    # Date-only input: anchor to start/end of day
    if 'T' not in date_input:
        if kind == 'start':
            parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999000)
    return parsed


def parse_timestamp_str(ts_str):
    """Parse the ISO timestamp string captured from the timeline log."""
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def extract_usage_data(input_file, usage_type,
                       start_date=None, stop_date=None):
    """Extract usage data from timeline profile file based on usage type.

    Args:
        input_file: Path to the timeline profile log file.
        usage_type: Substring matched against the block label column.
        start_date: Optional datetime; rows with timestamp < start_date
            are skipped. Inclusive of start_date itself.
        stop_date: Optional datetime; rows with timestamp > stop_date are
            skipped. Inclusive of stop_date itself.

    Debug output uses the shared vlog framework. Use -v / -vv / -vvv on
    the CLI (or call set_verbose_level()) to control verbosity.
    """
    usage_data = []
    line_count = 0
    matched_lines = 0
    skipped_by_bounds = 0

    vlog2(f"Searching for '{usage_type}' in {input_file}")
    if start_date:
        vlog2(f"Applying start-date bound: {start_date}")
    if stop_date:
        vlog2(f"Applying stop-date bound: {stop_date}")

    with open(input_file, 'r') as f:
        for line in f:
            line_count += 1
            line = line.strip()
            if not line or line.startswith('Delta(HH:MM:SS)') or line.startswith('-------------'):
                continue

            # Split timeline format: Delta\tHostname\tBlock Label\tLog File\tData
            parts = line.split('\t')
            if len(parts) < 5:
                continue

            block_label = parts[2].strip()
            log_data = parts[4].strip()

            if usage_type not in block_label:
                continue

            matched_lines += 1
            if matched_lines <= 5:
                vlog3(f"Matched line {line_count}: {line}")

            # Extract timestamp from log data (5th column)
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})', log_data)
            if not timestamp_match:
                vlog3(f"No timestamp found in line {line_count}")
                continue

            timestamp = timestamp_match.group(1)

            # Apply -s/-e bounds (inclusive on both ends). Parse once per
            # candidate row that already passed the block-label match.
            if start_date is not None or stop_date is not None:
                ts_dt = parse_timestamp_str(timestamp)
                if ts_dt is None:
                    # Couldn't parse -> drop the row when bounds are in play
                    skipped_by_bounds += 1
                    continue
                if start_date is not None and ts_dt < start_date:
                    skipped_by_bounds += 1
                    continue
                if stop_date is not None and ts_dt > stop_date:
                    skipped_by_bounds += 1
                    continue

            # Format 1: debounce lines with value in parentheses
            debounce_match = re.search(r'debounce.*?\((\d+\.?\d*)\)', log_data)
            if debounce_match:
                value = float(debounce_match.group(1))
                usage_data.append((timestamp, value))
                vlog3(f"Found debounce value: {value} at {timestamp}")
                continue

            # Format 2: reading lines with "XX.XX % usage"
            reading_match = re.search(r'reading: (\d+\.?\d*) % usage', log_data)
            if reading_match:
                value = float(reading_match.group(1))
                usage_data.append((timestamp, value))
                vlog3(f"Found reading value: {value} at {timestamp}")
                continue

            # Format 3: platform memory usage lines with "Usage: XX.X%"
            # Matches both legacy "platform memory usage: Usage" and current
            # "platform memory dispatch Usage" wording. Case-insensitive on the
            # usage_type gate so callers can pass "Platform Mem" / "Platform MEM".
            if 'platform mem' in usage_type.lower():
                memory_match = re.search(
                    r'platform memory (?:usage:|dispatch) Usage: (\d+\.?\d*)%',
                    log_data,
                )
                if memory_match:
                    value = float(memory_match.group(1))
                    usage_data.append((timestamp, value))
                    vlog3(f"Found platform memory value: {value} at {timestamp}")
                    continue

            # Format 4: platform cpu usage plugin lines with "Usage: XX.X%"
            # Matches both legacy "platform cpu usage plugin Usage" and current
            # "platform cpu dispatch Usage" wording. Case-insensitive on the
            # usage_type gate so callers can pass "Platform CPU" / "Platform Cpu".
            if 'platform cpu' in usage_type.lower():
                cpu_match = re.search(
                    r'platform cpu (?:usage plugin|dispatch) Usage: (\d+\.?\d*)%',
                    log_data,
                )
                if cpu_match:
                    value = float(cpu_match.group(1))
                    usage_data.append((timestamp, value))
                    vlog3(f"Found platform cpu value: {value} at {timestamp}")
                    continue

    vlog2(f"Processed {line_count} lines, {matched_lines} "
          f"contained '{usage_type}', {len(usage_data)} data points extracted")
    if start_date is not None or stop_date is not None:
        vlog2(f"{skipped_by_bounds} matched rows skipped by -s/-e bounds")

    return usage_data


def create_csv(usage_data, output_file, usage_type):
    """Create CSV file from usage data."""
    column_name = usage_type.replace(' ', '_') + '_Usage'

    vlog2(f"Creating CSV with column '{column_name}'")

    with open(output_file, 'w') as f:
        f.write(f"Timestamp,{column_name}\n")
        for timestamp, value in usage_data:
            f.write(f"{timestamp},{value}\n")

    vlog2(f"CSV file written: {output_file}")


def create_graph(csv_file, output_image, usage_type, y_range):
    """Create graph from CSV data."""
    vlog2(f"Reading CSV file: {csv_file}")

    df = pd.read_csv(csv_file)

    vlog2(f"CSV contains {len(df)} rows")
    vlog2(f"CSV columns: {list(df.columns)}")

    df['Timestamp'] = pd.to_datetime(df['Timestamp'])

    column_name = usage_type.replace(' ', '_') + '_Usage'

    vlog2(f"Looking for column: {column_name}")
    vlog2(f"Y-range: {y_range}")

    plt.figure(figsize=(12, 6))
    plt.plot(df['Timestamp'], df[column_name], linewidth=1, color='blue')
    plt.title(f'{usage_type} Usage Over Time')
    plt.xlabel('Time')
    plt.ylabel('Usage (%)')
    plt.ylim(y_range[0], y_range[1])
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    plt.savefig(output_image, dpi=300, bbox_inches='tight')
    plt.close()

    vlog2(f"Graph saved: {output_image}")


# ---------------------------------------------------------------------------
# State-mode graph (collectd overage timeline)
# ---------------------------------------------------------------------------

# Severity mapping used by the state extractor and the step plotter.
# Y axis labels are kept compact for the rendered plot.
STATE_LEVEL = {
    'okay': 0,
    'warning': 1,
    'failure': 2,
}
STATE_LABELS = {
    0: 'okay (no alarm)',
    1: 'warning (major)',
    2: 'failure (critical)',
}


def extract_state_data(input_file, usage_type, start_date=None, stop_date=None):
    """Extract committed alarm state transitions from a timeline profile.

    Looks for collectd alarm-notifier debounce lines of the form:

        ... debounce 'okay -> failure' (95.94) (1:1) True

    Only rows whose committed flag is True are returned, since those are the
    transitions where collectd actually moved between okay/warning/failure.
    Rows whose committed flag is False are ignored to keep the rendered step
    line stable while a debounce window is still in progress.

    Args:
        input_file: Path to the timeline profile log file.
        usage_type: Substring matched against the block label column.
        start_date: Optional datetime; rows whose timestamp is before this
            value are dropped. Inclusive of start_date itself.
        stop_date:  Optional datetime; rows whose timestamp is after this
            value are dropped. Inclusive of stop_date itself.

    Returns:
        List of (timestamp_str, level_int) tuples ordered as encountered.
        level_int is 0/1/2 per STATE_LEVEL.
    """
    state_data = []
    line_count = 0
    matched_lines = 0
    skipped_by_bounds = 0
    # Track the earliest in-window block-label-matching timestamp and the
    # 'from' side of the first committed transition. We use these to
    # prepend a baseline sample so the step plot starts at the correct
    # prior state (e.g. okay) rather than at the level of the first
    # transition's target.
    first_seen_ts = None
    initial_from_state = None

    vlog2(f"Searching for state transitions of '{usage_type}' in {input_file}")
    if start_date:
        vlog2(f"Applying start-date bound: {start_date}")
    if stop_date:
        vlog2(f"Applying stop-date bound: {stop_date}")

    # Matches "debounce 'A -> B' (value) (n:m) True/False"
    state_re = re.compile(
        r"debounce\s+'(?P<from>okay|warning|failure)\s*->\s*"
        r"(?P<to>okay|warning|failure)'\s*"
        r"\([^)]*\)\s*\([^)]*\)\s*(?P<committed>True|False)"
    )

    with open(input_file, 'r') as f:
        for line in f:
            line_count += 1
            line = line.strip()
            if (not line
                    or line.startswith('Delta(HH:MM:SS)')
                    or line.startswith('-------------')):
                continue

            parts = line.split('\t')
            if len(parts) < 5:
                continue

            block_label = parts[2].strip()
            log_data = parts[4].strip()

            if usage_type not in block_label:
                continue

            matched_lines += 1

            timestamp_match = re.search(
                r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})', log_data)
            if not timestamp_match:
                vlog3(f"No timestamp found in line {line_count}")
                continue
            timestamp = timestamp_match.group(1)

            if start_date is not None or stop_date is not None:
                ts_dt = parse_timestamp_str(timestamp)
                if ts_dt is None:
                    skipped_by_bounds += 1
                    continue
                if start_date is not None and ts_dt < start_date:
                    skipped_by_bounds += 1
                    continue
                if stop_date is not None and ts_dt > stop_date:
                    skipped_by_bounds += 1
                    continue

            # First in-window block-label-matching row becomes the baseline
            # anchor timestamp.
            if first_seen_ts is None:
                first_seen_ts = timestamp

            m = state_re.search(log_data)
            if not m:
                continue
            if m.group('committed') != 'True':
                continue

            level = STATE_LEVEL.get(m.group('to'))
            if level is None:
                continue

            # Capture the prior state from the first committed transition so
            # we can prepend a baseline sample.
            if initial_from_state is None:
                initial_from_state = STATE_LEVEL.get(m.group('from'), 0)

            # Collapse consecutive same-state rows: collectd keeps emitting
            # 'failure -> okay' rows even after we've already settled at
            # okay, which would otherwise produce a noisy flat run on the
            # step plot.
            if state_data and state_data[-1][1] == level:
                continue

            state_data.append((timestamp, level))
            vlog3(f"State transition -> {m.group('to')} (level {level}) at {timestamp}")

    # Prepend a baseline sample so the step plot reads from the correct
    # prior state. Anchor the baseline at the earliest in-window
    # block-label-matching timestamp (or start_date if it was earlier).
    if state_data and initial_from_state is not None and first_seen_ts is not None:
        baseline_ts = first_seen_ts
        if start_date is not None:
            sd_str = start_date.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
            if sd_str < baseline_ts:
                baseline_ts = sd_str
        # Only insert the baseline if it is strictly earlier than the first
        # transition (otherwise we'd just duplicate that row).
        if baseline_ts < state_data[0][0]:
            state_data.insert(0, (baseline_ts, initial_from_state))
            vlog3(f"Prepended baseline state {initial_from_state} at {baseline_ts}")

    vlog2(f"Processed {line_count} lines, {matched_lines} contained "
          f"'{usage_type}', {len(state_data)} committed transitions extracted")
    if start_date is not None or stop_date is not None:
        vlog2(f"{skipped_by_bounds} matched rows skipped by -s/-e bounds")

    return state_data


def create_state_csv(state_data, output_file, usage_type):
    """Write a Timestamp,State,Level CSV for a state-mode timeline."""
    column_name = usage_type.replace(' ', '_') + '_State'

    vlog2(f"Creating state CSV with column '{column_name}'")

    with open(output_file, 'w') as f:
        f.write(f"Timestamp,{column_name},Level\n")
        for timestamp, level in state_data:
            f.write(f"{timestamp},{STATE_LABELS[level]},{level}\n")

    vlog2(f"State CSV written: {output_file}")


def create_state_graph(state_data, output_image, usage_type):
    """Render state_data as a three-level step plot.

    The plot has a fixed Y axis with three ticks (okay / warning / failure)
    so multiple runs against the same resource produce visually comparable
    images regardless of which severities the time window actually hit.

    A short virtual 'tail' segment is appended so the final state is visible
    as a flat run all the way to the right edge of the plot rather than
    ending in a vertical jump at the last transition.
    """
    if not state_data:
        vlog2("No state transitions; nothing to plot")
        return False

    timestamps = [pd.to_datetime(ts) for ts, _ in state_data]
    levels = [lvl for _, lvl in state_data]

    # Extend the last state to the right edge so it reads as a sustained
    # condition rather than a tick at the final transition. Pick a tail
    # length that is short relative to the captured window.
    if len(timestamps) >= 2:
        span = (timestamps[-1] - timestamps[0]).total_seconds()
        tail_secs = max(60, span * 0.02)
    else:
        tail_secs = 60
    timestamps.append(timestamps[-1] + pd.Timedelta(seconds=tail_secs))
    levels.append(levels[-1])

    plt.figure(figsize=(12, 4.5))
    plt.step(timestamps, levels, where='post', linewidth=2, color='tab:red')
    plt.title(f'{usage_type} Alarm State Over Time')
    plt.xlabel('Time')
    plt.ylabel('Alarm Severity')
    plt.yticks([0, 1, 2], [STATE_LABELS[0], STATE_LABELS[1], STATE_LABELS[2]])
    plt.ylim(-0.3, 2.3)
    # Light horizontal guides at each severity level.
    for y in (0, 1, 2):
        plt.axhline(y=y, color='lightgray', linewidth=0.7, alpha=0.6)
    plt.grid(True, axis='x', alpha=0.3)
    # Force full YYYY-MM-DD HH:MM:SS x-tick labels so the time origin is
    # always unambiguous regardless of the captured time span.
    import matplotlib.dates as mdates
    ax = plt.gca()
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M:%S'))
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()

    plt.savefig(output_image, dpi=300, bbox_inches='tight')
    plt.close()

    vlog2(f"State graph saved: {output_image}")
    return True


def system_color_cycle(n):
    """Return a list of n perceptually distinct matplotlib colors.

    Uses tab10 for up to 10 hosts and tab20 for up to 20. Beyond 20,
    samples evenly from the hsv colormap so very large systems still
    get distinguishable colors (deterministic per host position).
    """
    try:
        import matplotlib.cm as cm
        if n <= 10:
            base = plt.get_cmap('tab10').colors
            return [base[i] for i in range(n)]
        if n <= 20:
            base = plt.get_cmap('tab20').colors
            return [base[i] for i in range(n)]
        cmap = cm.get_cmap('hsv', n)
        return [cmap(i) for i in range(n)]
    except Exception:
        # Last-ditch fallback so tests with mocked matplotlib still work
        defaults = ['blue', 'orange', 'green', 'red', 'purple',
                    'brown', 'pink', 'gray', 'olive', 'cyan']
        return [defaults[i % len(defaults)] for i in range(n)]


def create_system_graph(host_csvs, output_image, usage_type, y_range):
    """Create a combined multi-host graph from per-host CSVs.

    Args:
        host_csvs: List of (hostname, csv_path) tuples, in display order.
            Hosts whose csv_path is missing are silently skipped so a
            zero-match host does not break the combined output.
        output_image: Full path to the PNG to write.
        usage_type: Same usage type string passed to per-host graphing;
            used to derive the value column name and the title.
        y_range: (y_min, y_max) tuple for the Y axis.

    Each host appears as one line, color-coded via a perceptually
    distinct palette. A legend maps hostname → color.
    """
    column_name = usage_type.replace(' ', '_') + '_Usage'

    # Filter to hosts whose CSV actually exists on disk.
    present = []
    for hostname, csv_path in host_csvs:
        if csv_path and os.path.exists(csv_path):
            present.append((hostname, csv_path))
        else:
            vlog3(f"Skipping {hostname}: no CSV at {csv_path}")

    if not present:
        vlog2("No per-host CSVs found; combined graph not produced")
        return False

    vlog2(f"Combining {len(present)} host CSVs into {output_image}")
    vlog2(f"Value column: {column_name}")
    vlog2(f"Y-range: {y_range}")

    # Sort hosts alphabetically so color assignment is stable across runs
    # for the same set of hosts.
    present.sort(key=lambda hc: hc[0])

    colors = system_color_cycle(len(present))

    # Scale figure height slightly with host count so legends stay readable.
    height = 6 + max(0, len(present) - 6) * 0.15
    plt.figure(figsize=(14, height))

    plotted = 0
    for (hostname, csv_path), color in zip(present, colors):
        try:
            df = pd.read_csv(csv_path)
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            if column_name not in df.columns:
                vlog3(f"{hostname}: column '{column_name}' missing in {csv_path}; skipping")
                continue
            plt.plot(df['Timestamp'], df[column_name],
                     linewidth=1, color=color, label=hostname, alpha=0.85)
            plotted += 1
            vlog3(f"Plotted {hostname} ({len(df)} points)")
        except Exception as e:
            print(f"Warning: Could not plot {hostname} from {csv_path}: {e}",
                  file=sys.stderr)

    if plotted == 0:
        plt.close()
        vlog2("No host series plotted; skipping save")
        return False

    plt.title(f'{usage_type} Usage Over Time - All Hosts')
    plt.xlabel('Time')
    plt.ylabel('Usage (%)')
    plt.ylim(y_range[0], y_range[1])
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.legend(loc='best', framealpha=0.9, title='Host')
    plt.tight_layout()

    plt.savefig(output_image, dpi=300, bbox_inches='tight')
    plt.close()

    vlog2(f"System graph saved: {output_image}")
    return True


def main():
    parser = argparse.ArgumentParser(description='Extract usage data and create graph')
    parser.add_argument('-i', '--input', help='Input log file (per-host mode)')
    parser.add_argument('-o', '--output', help='Output file prefix (per-host mode) '
                                               'or full output PNG path (--combine mode)')
    parser.add_argument('-n', '--name', default='Platform CPU', help='Usage type to search for (default: Platform CPU)')
    parser.add_argument('-r', '--range', default='0:110', help='Y-axis range (default: 0:110)')
    parser.add_argument('-s', '--start-date',
                        help='Start date filter (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). '
                             'Date-only input is anchored to 00:00:00 of that day.')
    parser.add_argument('-e', '--stop-date',
                        help='Stop date filter (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). '
                             'Date-only input is anchored to 23:59:59 of that day.')
    parser.add_argument('--combine', action='store_true',
                        help='Combine multiple per-host CSVs into a single multi-line graph. '
                             'Requires --output and at least one --host-csv.')
    parser.add_argument('--host-csv', action='append', default=[],
                        metavar='HOST=PATH',
                        help='In --combine mode, a hostname=csv_path mapping. '
                             'May be repeated, one per host.')
    parser.add_argument('--style', choices=['line', 'state'], default='line',
                        help='Graph style. "line" (default) plots numeric usage '
                             'as a continuous line; "state" plots collectd alarm '
                             'state transitions as a three-level step graph '
                             '(okay / warning / failure).')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Increase verbosity level (use -v, -vv, -vvv, -vvvv, or -vvvvv)')

    args = parser.parse_args()

    # Wire CLI verbose count into the shared vlog framework.
    set_verbose_level(args.verbose)

    # Parse range (shared by both modes)
    try:
        y_min, y_max = map(int, args.range.split(':'))
        y_range = (y_min, y_max)
    except ValueError as e:
        print(f"Error: Range must be in format 'min:max' (e.g., '0:100'). Invalid value: {e}")
        return
    except Exception as e:
        print(f"Error: Failed to parse range '{args.range}': {e}")
        return

    if args.combine:
        run_combine_mode(args, y_range)
        return

    # Per-host mode requires --input.
    if not args.input:
        print("Error: --input is required (or use --combine with --host-csv).",
              file=sys.stderr)
        return

    vlog2(f"Input file: {args.input}")
    vlog2(f"Usage name: {args.name}")
    vlog2(f"Range: {args.range}")
    vlog2(f"Output prefix: {args.output}")
    if args.start_date:
        vlog2(f"Start date: {args.start_date}")
    if args.stop_date:
        vlog2(f"Stop date: {args.stop_date}")

    # Parse -s/-e using the same conventions as lpmptool
    start_date = parse_bound_date(args.start_date, 'start')
    stop_date = parse_bound_date(args.stop_date, 'stop')
    if start_date and stop_date and stop_date <= start_date:
        print("Error: Stop date must be after start date", file=sys.stderr)
        return

    # Determine output files
    if args.output:
        base_name = args.output
    else:
        # Replace spaces with underscores for filename
        graph_filename_part = args.name.replace(' ', '_')
        input_base = os.path.splitext(os.path.basename(args.input))[0]
        base_name = f"{input_base}_{graph_filename_part}"

    vlog2(f"Base filename: {base_name}")

    csv_file = f"{base_name}.csv"
    png_file = f"{base_name}.png"

    vlog2(f"CSV file: {csv_file}")
    vlog2(f"PNG file: {png_file}")

    if args.style == 'state':
        # State-mode (collectd overage timeline): committed alarm transitions
        # rendered as a three-level step graph (okay / warning / failure).
        print(f"Extracting {args.name} alarm state from {args.input}...")
        state_data = extract_state_data(args.input, args.name,
                                        start_date=start_date,
                                        stop_date=stop_date)
        if not state_data:
            print(f"No {args.name} alarm state transitions found in the input file")
            return

        create_state_csv(state_data, csv_file, args.name)
        print(f"Created state CSV with {len(state_data)} transitions: {csv_file}")

        create_state_graph(state_data, png_file, args.name)
        print(f"Created state graph: {png_file}")
        return

    # Default: line-style numeric usage extraction
    print(f"Extracting {args.name} usage data from {args.input}...")
    usage_data = extract_usage_data(args.input, args.name,
                                    start_date=start_date,
                                    stop_date=stop_date)

    if not usage_data:
        print(f"No {args.name} usage data found in the input file")
        if get_verbose_level() >= 2:
            vlog2("Checking first 10 lines of input file:")
            try:
                with open(args.input, 'r') as f:
                    for i, line in enumerate(f):
                        if i >= 10:
                            break
                        vlog3(f"  Line {i + 1}: {line.strip()}")
            except Exception as e:
                vlog2(f"Error reading file: {e}")
        return

    # Create CSV
    create_csv(usage_data, csv_file, args.name)
    print(f"Created CSV with {len(usage_data)} data points: {csv_file}")

    # Create graph
    create_graph(csv_file, png_file, args.name, y_range)
    print(f"Created graph: {png_file}")


def run_combine_mode(args, y_range):
    """Driver for the --combine multi-host graph mode."""
    if not args.output:
        print("Error: --combine requires --output <png-or-prefix-path>.",
              file=sys.stderr)
        return
    if not args.host_csv:
        print("Error: --combine requires at least one --host-csv HOST=PATH.",
              file=sys.stderr)
        return

    host_csvs = []
    for entry in args.host_csv:
        if '=' not in entry:
            print(f"Error: --host-csv expects HOST=PATH, got: {entry}",
                  file=sys.stderr)
            return
        hostname, csv_path = entry.split('=', 1)
        hostname = hostname.strip()
        csv_path = csv_path.strip()
        if not hostname or not csv_path:
            print(f"Error: --host-csv missing host or path: {entry}",
                  file=sys.stderr)
            return
        host_csvs.append((hostname, csv_path))

    # Allow --output to be supplied with or without a .png suffix.
    out = args.output
    if not out.lower().endswith('.png'):
        out = out + '.png'

    vlog2(f"--combine output: {out}")
    vlog2(f"Usage name: {args.name}")
    vlog2(f"Range: {args.range}")
    vlog2(f"Host CSVs: {len(host_csvs)} entries")
    for hostname, csv_path in host_csvs:
        vlog3(f"  {hostname} -> {csv_path}")

    # Per-host CSVs were already produced under whatever -s/-e bound applied
    # at extraction time, so no further filtering is required here. We still
    # echo the bound values in verbose mode for traceability.
    if args.start_date or args.stop_date:
        vlog2("-s/-e bounds were applied at per-host extraction time; "
              "no re-filtering in --combine mode.")

    ok = create_system_graph(host_csvs, out, args.name, y_range)
    if ok:
        print(f"Created system graph: {out}")
    else:
        print("No system graph produced (no per-host CSVs available).")


if __name__ == "__main__":
    main()
