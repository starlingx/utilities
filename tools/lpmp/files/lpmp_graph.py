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

Given a timeline profile produced by one of those models, this module
extracts the numeric usage values and produces a CSV file and a PNG
line graph image showing the values over time. It is invoked
automatically by lpmptool when one of the supported collectd models is
run, and can also be run standalone from the command line.

Outputs:
    <prefix>.csv  - Two-column CSV (Timestamp, <UsageType>_Usage)
    <prefix>.png  - Line graph image of the values over time

Dependencies: pandas (CSV/timestamp parsing), matplotlib (graph rendering).
"""

import argparse
import os
import re
import sys

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


def extract_usage_data(input_file, usage_type, verbose=False):
    """Extract usage data from timeline profile file based on usage type"""
    usage_data = []
    line_count = 0
    matched_lines = 0

    if verbose:
        print(f"Debug: Searching for '{usage_type}' in {input_file}")

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
            if verbose and matched_lines <= 5:
                print(f"Debug: Matched line {line_count}: {line}")

            # Extract timestamp from log data (5th column)
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})', log_data)
            if not timestamp_match:
                if verbose:
                    print(f"Debug: No timestamp found in line {line_count}")
                continue

            timestamp = timestamp_match.group(1)

            # Format 1: debounce lines with value in parentheses
            debounce_match = re.search(r'debounce.*?\((\d+\.?\d*)\)', log_data)
            if debounce_match:
                value = float(debounce_match.group(1))
                usage_data.append((timestamp, value))
                if verbose:
                    print(f"Debug: Found debounce value: {value} at {timestamp}")
                continue

            # Format 2: reading lines with "XX.XX % usage"
            reading_match = re.search(r'reading: (\d+\.?\d*) % usage', log_data)
            if reading_match:
                value = float(reading_match.group(1))
                usage_data.append((timestamp, value))
                if verbose:
                    print(f"Debug: Found reading value: {value} at {timestamp}")
                continue

            # Format 3: platform memory usage lines with "Usage: XX.X%"
            if 'Platform Mem' in usage_type and 'platform memory usage: Usage' in log_data:
                memory_match = re.search(r'platform memory usage: Usage: (\d+\.?\d*)%', log_data)
                if memory_match:
                    value = float(memory_match.group(1))
                    usage_data.append((timestamp, value))
                    if verbose:
                        print(f"Debug: Found platform memory value: {value} at {timestamp}")
                    continue

            # Format 4: platform cpu usage plugin lines with "Usage: XX.X%"
            if 'Platform Cpu' in usage_type and 'platform cpu usage plugin Usage' in log_data:
                cpu_match = re.search(r'platform cpu usage plugin Usage: (\d+\.?\d*)%', log_data)
                if cpu_match:
                    value = float(cpu_match.group(1))
                    usage_data.append((timestamp, value))
                    if verbose:
                        print(f"Debug: Found platform cpu value: {value} at {timestamp}")
                    continue
    if verbose:
        print(f"Debug: Processed {line_count} lines, {matched_lines} "
              f"contained '{usage_type}', {len(usage_data)} data points extracted")

    return usage_data


def create_csv(usage_data, output_file, usage_type, verbose=False):
    """Create CSV file from usage data"""
    column_name = usage_type.replace(' ', '_') + '_Usage'

    if verbose:
        print(f"Debug: Creating CSV with column '{column_name}'")

    with open(output_file, 'w') as f:
        f.write(f"Timestamp,{column_name}\n")
        for timestamp, value in usage_data:
            f.write(f"{timestamp},{value}\n")

    if verbose:
        print(f"Debug: CSV file written: {output_file}")


def create_graph(csv_file, output_image, usage_type, y_range, verbose=False):
    """Create graph from CSV data"""
    if verbose:
        print(f"Debug: Reading CSV file: {csv_file}")

    df = pd.read_csv(csv_file)

    if verbose:
        print(f"Debug: CSV contains {len(df)} rows")
        print(f"Debug: CSV columns: {list(df.columns)}")

    df['Timestamp'] = pd.to_datetime(df['Timestamp'])

    column_name = usage_type.replace(' ', '_') + '_Usage'

    if verbose:
        print(f"Debug: Looking for column: {column_name}")
        print(f"Debug: Y-range: {y_range}")

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

    if verbose:
        print(f"Debug: Graph saved: {output_image}")


def main():
    parser = argparse.ArgumentParser(description='Extract usage data and create graph')
    parser.add_argument('-i', '--input', required=True, help='Input log file')
    parser.add_argument('-o', '--output', help='Output file prefix (default: input filename in current dir)')
    parser.add_argument('-n', '--name', default='Platform CPU', help='Usage type to search for (default: Platform CPU)')
    parser.add_argument('-r', '--range', default='0:110', help='Y-axis range (default: 0:110)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose debug output')

    args = parser.parse_args()

    if args.verbose:
        print(f"Debug: Input file: {args.input}")
        print(f"Debug: Usage name: {args.name}")
        print(f"Debug: Range: {args.range}")
        print(f"Debug: Output prefix: {args.output}")

    # Parse range
    try:
        y_min, y_max = map(int, args.range.split(':'))
        y_range = (y_min, y_max)
    except ValueError as e:
        print(f"Error: Range must be in format 'min:max' (e.g., '0:100'). Invalid value: {e}")
        return
    except Exception as e:
        print(f"Error: Failed to parse range '{args.range}': {e}")
        return

    # Determine output files
    if args.output:
        base_name = args.output
    else:
        # Replace spaces with underscores for filename
        graph_filename_part = args.name.replace(' ', '_')
        input_base = os.path.splitext(os.path.basename(args.input))[0]
        base_name = f"{input_base}_{graph_filename_part}"

    if args.verbose:
        print(f"Debug: Base filename: {base_name}")

    csv_file = f"{base_name}.csv"
    png_file = f"{base_name}.png"

    if args.verbose:
        print(f"Debug: CSV file: {csv_file}")
        print(f"Debug: PNG file: {png_file}")

    # Extract data
    print(f"Extracting {args.name} usage data from {args.input}...")
    usage_data = extract_usage_data(args.input, args.name, args.verbose)

    if not usage_data:
        print(f"No {args.name} usage data found in the input file")
        if args.verbose:
            print("Debug: Checking first 10 lines of input file:")
            try:
                with open(args.input, 'r') as f:
                    for i, line in enumerate(f):
                        if i >= 10:
                            break
                        print(f"  Line {i + 1}: {line.strip()}")
            except Exception as e:
                print(f"Debug: Error reading file: {e}")
        return

    # Create CSV
    create_csv(usage_data, csv_file, args.name, args.verbose)
    print(f"Created CSV with {len(usage_data)} data points: {csv_file}")

    # Create graph
    create_graph(csv_file, png_file, args.name, y_range, args.verbose)
    print(f"Created graph: {png_file}")


if __name__ == "__main__":
    main()
