#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Pod Stabilization Time Reporter (Describe-Based)
#
# Parse kubectl describe pods output (plain text)
#
# Extracts pod stabilization times from containerization_pods.info
# which is kubectl describe pods output. Much simpler than JSON/events.
#
# Data: Start Time and first Started timestamp per pod/container
# Stabilization = Started time - Start Time (in seconds)
#
# Also extracts restart counts directly from "Restart Count:" lines.
#
# Output columns:
#   Duration   - Seconds from pod scheduled to container started
#   Start      - Pod start time (full date and time)
#   Started    - Container started time (full date and time)
#   Restarts   - Total restarts (⚠ marker if > 0)
#   Pod Name   - Name of the pod
#
# JSON output saved to /tmp/pod_ready_times.json for soak testing.
#
# Usage:
#   pod_ready_times_describe.py          # Auto-generate via kubectl describe pods
#   pod_ready_times_describe.py [input_file]
#
# Examples:
#   pod_ready_times_describe.py
#   pod_ready_times_describe.py containerization_pods.info
#   pod_ready_times_describe.py var/extra/containerization_pods.info
#   cat pods.info | pod_ready_times_describe.py /dev/stdin
#
########################################################################


from datetime import datetime  # noqa: E402
from datetime import timezone  # noqa: E402
import json                    # noqa: E402
import subprocess              # noqa: E402
import sys                     # noqa: E402

sys.dont_write_bytecode = True


def parse_describe_timestamp(ts_str):
    """Parse kubectl describe timestamp format.

    Format examples:
      Sat, 05 Sep 2026 04:36:22 +0000
      Sat, 05 Sep 2026 04:36:22 +0000
    """
    if not ts_str:
        return None
    try:
        # Remove day of week prefix (e.g., "Sat, ")
        parts = ts_str.strip().split(', ', 1)
        if len(parts) == 2:
            ts_str = parts[1]

        # Parse: "05 Sep 2026 04:36:22 +0000"
        return datetime.strptime(ts_str, "%d %b %Y %H:%M:%S %z")
    except (ValueError, IndexError):
        return None


def format_full_datetime(ts_str):
    """Extract full datetime from describe timestamp (YYYY-MM-DD HH:MM:SS)."""
    if not ts_str:
        return "unknown"
    try:
        dt = parse_describe_timestamp(ts_str)
        if dt:
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return ts_str
    except Exception:
        return ts_str


def extract_pods_from_describe(content):
    """Parse pod data from kubectl describe output.

    Extracts: pod name, start time, first started time, restart count

    Returns: List of tuples
      (pod_name, start_time, started_time, restart_count)
    """
    pods = []
    current_pod = None
    current_start_time = None
    current_started_time = None
    current_restart_count = 0
    has_first_started = False

    for line in content.split('\n'):
        line_stripped = line.strip()

        # Pod name
        if line_stripped.startswith('Name:'):
            # Save previous pod if exists
            if current_pod and current_start_time and current_started_time:
                pods.append((current_pod, current_start_time, current_started_time,
                             current_restart_count))

            # Reset for new pod
            current_pod = line_stripped.split('Name:', 1)[1].strip()
            current_start_time = None
            current_started_time = None
            current_restart_count = 0
            has_first_started = False

        # Pod start time
        elif 'Start Time:' in line and not line.startswith('  '):
            # Top-level Start Time (not indented under container)
            parts = line.split('Start Time:', 1)
            if len(parts) == 2:
                current_start_time = parts[1].strip()

        # Container started time (first occurrence only per pod)
        elif 'Started:' in line and not has_first_started:
            # Container's Started time (has leading whitespace)
            parts = line.split('Started:', 1)
            if len(parts) == 2:
                started_str = parts[1].strip()
                if started_str:  # Not empty
                    current_started_time = started_str
                    has_first_started = True

        # Restart count (cumulative across containers)
        elif 'Restart Count:' in line:
            parts = line.split('Restart Count:', 1)
            if len(parts) == 2:
                try:
                    count = int(parts[1].strip())
                    current_restart_count += count
                except ValueError:
                    pass

    # Save last pod
    if current_pod and current_start_time and current_started_time:
        pods.append((current_pod, current_start_time, current_started_time,
                     current_restart_count))

    return pods


def calculate_stabilization_time(start_time_str, started_time_str):
    """Calculate seconds between start and started times."""
    try:
        start_dt = parse_describe_timestamp(start_time_str)
        started_dt = parse_describe_timestamp(started_time_str)

        if start_dt and started_dt:
            delta = started_dt - start_dt
            return delta.total_seconds()
    except Exception:
        pass

    return 0


def main():
    """Main entry point."""
    data_file = None

    # Parse arguments
    if len(sys.argv) > 1:
        data_file = sys.argv[1]

    # Read input
    try:
        if data_file is None:
            # No argument: auto-generate kubectl describe pods output on-system
            try:
                result = subprocess.run(
                    ['kubectl', 'describe', 'pods', '-A'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode != 0:
                    print(f"Error: kubectl failed: {result.stderr}", file=sys.stderr)
                    sys.exit(1)
                content = result.stdout

                if not content or content.strip() == "":
                    # kubectl succeeded but returned empty (no pods)
                    print("Error: kubectl returned empty output (no pods found)", file=sys.stderr)
                    sys.exit(1)
            except FileNotFoundError:
                print("Error: kubectl not found in PATH", file=sys.stderr)
                sys.exit(1)
            except subprocess.TimeoutExpired:
                print("Error: kubectl describe pods timed out after 30 seconds", file=sys.stderr)
                sys.exit(1)
        elif data_file == "/dev/stdin":
            content = sys.stdin.read()
        else:
            with open(data_file, 'r') as f:
                content = f.read()

        if not content or content.strip() == "":
            print("Error: No data found", file=sys.stderr)
            sys.exit(1)

    except FileNotFoundError:
        print(f"Error: File not found: {data_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading data: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract pod data
    pod_data = extract_pods_from_describe(content)

    if not pod_data:
        msg = "No pods found in describe output"
        print(msg, file=sys.stderr)
        sys.exit(1)

    # Calculate stabilization times
    rows = []
    for (pod_name, start_time, started_time, restart_count) in pod_data:
        stab_seconds = calculate_stabilization_time(start_time, started_time)
        rows.append((stab_seconds, pod_name, start_time, started_time,
                     restart_count))

    # Sort by duration
    rows.sort(key=lambda x: x[0])

    # Print header
    header = (f"{'Duration':>10}  {'Start':>19}  {'Started':>19}  "
              f"{'Restarts':>8}  Pod Name")
    print(header)
    print("-" * 120)

    # Prepare JSON data
    json_data = {
        "metadata": {
            "timestamp": (datetime.now(timezone.utc).isoformat()
                          .replace('+00:00', 'Z')),
            "total_pods": len(rows),
            "mode": "describe-based",
            "source": "containerization_pods.info"
        },
        "pods": []
    }

    # Print results
    total_stab = 0
    for (stab_seconds, pod_name, start_time, started_time,
         restart_count) in rows:
        start_formatted = format_full_datetime(start_time)
        started_formatted = format_full_datetime(started_time)
        duration_str = f"{stab_seconds:6.0f}s"
        pod_display = pod_name[:60] if len(pod_name) > 60 else pod_name

        # Restart marker
        restart_marker = "⚠" if restart_count > 0 else " "
        restart_str = f"{restart_marker} {restart_count}"

        line = (f"{duration_str:>10}  {start_formatted:>19}  "
                f"{started_formatted:>19}  {restart_str:>8}  {pod_display}")
        print(line)
        total_stab += stab_seconds

        # Add to JSON
        json_data["pods"].append({
            "name": pod_name,
            "stabilization_seconds": stab_seconds,
            "start_time": start_formatted,
            "started_time": started_formatted,
            "restart_count": restart_count
        })

    # Summary
    print("-" * 120)
    avg_stab = total_stab / len(rows) if rows else 0
    print(f"Total pods: {len(rows)}")
    print(f"Min stabilization: {min(r[0] for r in rows):6.0f}s")
    print(f"Max stabilization: {max(r[0] for r in rows):6.0f}s")
    print(f"Avg stabilization: {avg_stab:6.0f}s")

    # Flag pods with restarts
    restarted = [r for r in rows if r[4] > 0]
    if restarted:
        print(f"\n⚠️  Found {len(restarted)} pods with restarts:")
        for (stab_seconds, pod_name, _, _, restart_count) in sorted(
                restarted, key=lambda x: -x[4])[:15]:
            line = (f"   • {pod_name:55} restarts={restart_count:2}  "
                    f"stabilization={stab_seconds:6.0f}s")
            print(line)

    # Flag slow pods
    slow = [r for r in rows if r[0] > 60]
    if slow:
        print(f"\n⚠️  Found {len(slow)} pods taking >60 seconds:")
        for (stab_seconds, pod_name, _, _, restart_count) in slow[:15]:
            marker = " (restarted)" if restart_count > 0 else ""
            line = (f"   • {pod_name:55} {stab_seconds:6.0f}s{marker}")
            print(line)

    # Save JSON
    try:
        json_path = "/tmp/pod_ready_times.json"
        with open(json_path, 'w') as f:
            json.dump(json_data, f, indent=2)
        print(f"\n✓ JSON output saved to {json_path}")
    except Exception as e:
        print(f"\n⚠️  Warning: Could not save JSON: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
