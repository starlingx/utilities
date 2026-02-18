# Log Pattern Matching Profiler (LPMP)

A log search and analysis tool that searches log files for specific patterns and analyzes time differences between pattern matches to produce timing profiles. Designed for KPI performance analysis, timing validation, and system operation profiling across multiple domains' log files.

## Git Repository

The LPMP tool is stored in the StarlingX utilities repository:

**Repository**: https://opendev.org/starlingx/utilities/src/branch/master/tools/lpmp

## Cloning the Repository

To clone the LPMP tool from git:

```bash
# Clone the entire utilities repository
git clone https://opendev.org/starlingx/utilities.git

# Navigate to the lpmp tool directory
cd utilities/tools/lpmp
```

## Building the LPMP Package

The LPMP tool is packaged as part of the StarlingX build system. To build the lpmp package:

```bash
# From the StarlingX build environment
build-pkgs -p lpmp
```

This will create the lpmp Debian package that can be installed on StarlingX systems.

## Installation

After building the package, install it using:

```bash
# Install the lpmp package
sudo dpkg -i lpmp_<version>.deb
```

The installation places:
- **Executable**: `/usr/local/bin/lpmptool`
- **Python modules**: `/usr/lib/python3/dist-packages/lpmp/`
- **Model files**: `/var/lib/lpmp_models/`
- **Helper files**: `/var/lib/lpmp_models/helpers/` (include files, tool config)
- **Example models**: `/var/lib/lpmp_models/examples/` (syntax reference only)
- **User models**: `/etc/lpmp.d/` (writable in OSTree, user plugins)

## Basic Help

```bash
$ lpmptool --help
usage: lpmptool [-h] [--block-time-tolerance BLOCK_TIME_TOLERANCE]
                [--bundle BUNDLE] [--exclude HOST [HOST ...]]
                [--file-position-tracking] [--help-model] [--hostname HOSTNAME]
                [--hosts] [--include HOST [HOST ...]] [--lab LAB]
                [--list-models] [--logs-dir LOGS_DIR] [--loops LOOPS]
                [--max-log-length MAX_LOG_LENGTH] [--max-time-delta MAX_TIME_DELTA]
                [--model-file MODEL_FILE] [--output OUTPUT] [--progress {none,dots,classic,circles,modern}]
                [--start-date START_DATE] [--sort] [--stats] [--stop-date STOP_DATE]
                [--var VARIABLES] [--verbose] [--version]

Log Pattern Matching Profiler - Requires YAML model file

optional arguments:
  -h, --help            show this help message and exit
  --block-time-tolerance BLOCK_TIME_TOLERANCE
                        Time tolerance in seconds for out-of-order log entries (default: 5.0)
  --bundle BUNDLE, -b BUNDLE
                        Full path to collect bundle directory (default: / for system)
  --exclude HOST [HOST ...]
                        Exclude specified hosts (space-separated, only with --bundle)
  --file-position-tracking, -fpt
                        [EXPERIMENTAL] Enable file position caching for better performance with expanded stacked patterns
  --force, -f           Force past block failures after the first block by treating them as warnings
  --help-model, -hm     Show detailed model file format and examples
  --hostname HOSTNAME   Hostname for {hostname} variable substitution (default: controller-0)
  --hosts               Interactive host selection for bundle mode (only with --bundle)
  --include HOST [HOST ...]
                        Include only specified hosts (space-separated, only with --bundle)
  --lab LAB             Lab name for identification (default: lab)
  --list-models, -lm    List available functional and example model files
  --logs-dir LOGS_DIR, -l LOGS_DIR
                        Directory containing log files (default: var/log, relative to bundle)
  --loops LOOPS, -n LOOPS
                        Number of times to run through the model (default: 1, 0=until EOF)
  --max-log-length MAX_LOG_LENGTH, -x MAX_LOG_LENGTH
                        Maximum length of log line in output (default: 180)
  --max-time-delta MAX_TIME_DELTA
                        Maximum time in seconds between start and stop patterns for pair blocks (default: 45)
  --model-file MODEL_FILE, -m MODEL_FILE
                        YAML model file with search patterns (default: model.yaml)
  --output OUTPUT, -o OUTPUT
                        Output directory path (default: ./lpmp_<lab_name>/<start_time>_<model_file_name>)
  --progress {none,dots,classic,circles,modern}, -p {none,dots,classic,circles,modern}
                        [EXPERIMENTAL] Progress indicator type for timeline models (default: dots)
  --start-date START_DATE, -s START_DATE
                        Start date for first search (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
  --sort                Sort --list-models output alphabetically by name
  --stats               Enable memory and performance statistics monitoring
  --stop-date STOP_DATE, -e STOP_DATE
                        Stop date for analysis (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
  --var VARIABLES       Additional variable substitution in KEY=VALUE format (can be used multiple times)
  --verbose, -v         Increase verbosity level (use -v, -vv, -vvv, -vvvv, or -vvvvv)
  --version             show program's version number and exit

Use --help-model for detailed model file format and examples with help creating a sample model file.
```

## Model Types and Basic Examples

LPMP supports three distinct model types, each optimized for different analysis needs:

### 1. Pattern Block Model (Sequential Event Timing)

Pattern blocks search for patterns sequentially. Each pattern must be found AFTER the previous pattern in chronological order.

**Example: System Boot Timing**

```yaml
# boot_timing.yaml
blocks:
  - label: "Kernel Boot"
    file: "kern.log*"
    patterns:
      - "Kernel command line:"

  - label: "Network Ready"
    file: "daemon.log*"
    patterns:
      - "network interface up"

  - label: "System Ready"
    file: "syslog*"
    patterns:
      - "System initialization complete"
```

**Usage:**
```bash
lpmptool -m boot_timing.yaml -l /var/log
```

### 2. Pair Block Model (Duration Measurement)

Pair blocks measure the time between start and stop patterns. Ideal for timing operations with clear beginning and end events.

**Example: Service Startup Duration**

```yaml
# service_timing.yaml
blocks:
  - label: "Database Service"
    file: "postgres.log*"
    start: "database system is starting up"
    stop: "database system is ready to accept connections"
    max_time_delta: 180

  - label: "Web Service"
    file: "apache.log*"
    start: "Starting web server"
    stop: "Server ready to accept connections"
    max_time_delta: 60
```

**Usage:**
```bash
lpmptool -m service_timing.yaml -l /var/log
```

### 3. Timeline Block Model (Event Collection)

Timeline blocks collect ALL matches for ALL specified patterns and sort them chronologically. No order requirements - patterns can be found in any order.

**Example: Maintenance Event Timeline**

```yaml
# maintenance_timeline.yaml
settings:
  timeline_patterns:
    maintenance:
      - "Host Add Completed"
      - "*** Heartbeat Miss ***"
      - "critical enable failure"

blocks:
  - label: "Maintenance Events"
    file: "mtcAgent.log*"
    timeline: "{maintenance}"
```

**Usage:**
```bash
lpmptool -m maintenance_timeline.yaml -l /var/log
```

### 4. Window Block Model (Time-Range Extraction)

Window blocks collect every timestamped line from all log files within a time window. No pattern matching — ideal for creating a unified timeline across all log sources during a narrow time range.

**Example: 10-Minute System Snapshot**

```yaml
# window_timeline.yaml
blocks:
  - label: "All logs"
    file: "*"
    window: true
```

**Usage:**
```bash
# Narrow window — recommended for manageable output size
lpmptool -m window_timeline -s 2025-12-15T14:40:00 -e 2025-12-15T14:50:00 -b /path/to/bundle
```

> **Note**: Output grows with window size since every timestamped line is collected.
> Use narrow windows (minutes, not hours) for best results.

## Model File Locations and Search Path

LPMP searches for model files in the following priority order:

1. **Tool directory models**: `<tool_directory>/models/` (highest priority)
2. **Local development models**: `./models/`
3. **User/developer models**: `/etc/lpmp.d/` (writable in OSTree)
4. **System-provided models**: `/var/lib/lpmp_models/` (read-only)
5. **Explicit paths**: Absolute or relative paths with separators

Helper files (include files, tool config) are stored in a `helpers/` subdirectory
under each model search path (e.g., `<tool_directory>/models/helpers/`). The include
directive and file ignore list loader automatically search these subdirectories.

When you specify a model file with `-m my_model.yaml`, LPMP searches these locations in order
and uses the first match found. LPMP defaults to search for model.yaml in the current
working directory if --model or -m is omitted from the command line.

**Example:**
```bash
# Searches current directory
lpmptool

# Searches in priority order
lpmptool -m boot_timing.yaml

# Use explicit path to override search
lpmptool -m /path/to/my/custom_model.yaml

# Use relative path
lpmptool -m ./my_models/test_model.yaml
```

## Quick Start Examples

### Basic System Analysis
```bash
# Analyze system logs with default model
lpmptool -m model.yaml -l /var/log

# With custom output directory
lpmptool -m model.yaml -l /var/log -o ./results
```

### Bundle Mode (Multi-Host Analysis)
```bash
# Analyze all hosts in bundle
lpmptool --bundle /path/to/bundle --model model.yaml

# Interactive host selection
lpmptool -b /path/to/bundle -m model.yaml --hosts

# Include specific hosts
lpmptool -b /path/to/bundle -m model.yaml --include controller-0 controller-1

# Exclude specific hosts
lpmptool -b /path/to/bundle -m model.yaml --exclude worker-2 worker-3
```

### Time-Bounded Analysis
```bash
# Start from specific date
lpmptool -m model.yaml --start-date "2024-01-06T10:00:00"

# Analyze specific time window
lpmptool -m model.yaml --start-date "2024-01-06T10:00:00" --stop-date "2024-01-06T12:00:00"
```

### Variable Substitution
```bash
# Use custom hostname
lpmptool -m model.yaml --hostname worker-1

# Custom variables
lpmptool -m model.yaml --var service=nova --var graph="Platform CPU"
```

### Force Mode (Override Non-First Block Failures)
```bash
# Force past failures in blocks after the first (first block must still succeed)
lpmptool -m model.yaml -f

# Useful when the anchor block matches but later blocks may be missing
lpmptool -m unlock_model.yaml -l /var/log --force
```

### Verbose Output
```bash
# Basic progress
lpmptool -m model.yaml -v

# Configuration details
lpmptool -m model.yaml -vv

# Pattern matching details
lpmptool -m model.yaml -vvv

# Full debug output
lpmptool -m model.yaml -vvvvv
```

## Output Files

LPMP generates multiple output files depending on the model type and configuration:

### Standard Output Files
- **`<lab>_profile.timing`**: Main timing results (tab-separated)
- **`<lab>_profile.timing.csv`**: CSV format for analysis tools
- **`summary.timing`**: Statistical summary (non-timeline models)
- **`<block_label>.timing`**: Per-block profiles (when `profile: true`)

### Bundle Mode Output
- **`<hostname>/`**: Per-host subdirectories with individual results
- **`<lab>_system_profile.timing`**: Merged multi-host timeline
- **`<lab>_system_summary.timing`**: System-wide statistics

### Output Directory Structure
```
lpmp_<lab>/
└── <timestamp>_<model>/
    ├── <lab>_profile.timing
    ├── <lab>_profile.timing.csv
    ├── summary.timing
    └── <block_label>.timing (if profile: true)
```

## Common Use Cases

LPMP is designed for:

- **System boot/shutdown timing analysis**: Profile the timing of boot and shutdown sequences
- **Service startup sequence profiling**: Identify performance bottlenecks in service initialization
- **Performance bottleneck identification**: Measure duration of operations with start/stop patterns
- **Log correlation across multiple services**: Correlate events across multiple log files chronologically
- **Timing validation**: Validate timing requirements (e.g., service must start within 30 seconds)
- **Automated timing regression testing**: Track time between specific events across all nodes in a collect bundle
- **Multi-host collect bundle analysis**: Analyze system operations across all nodes in a collect bundle (on-system analysis is single-host only, no SSH)
- **Maintenance or other event filtering**: Track maintenance events and their timing relationships
- **Any Domain profile timing or timeline**: Track log timing of and between one or more domains

## Next Steps

For detailed information about:
- **Architecture and design**:        See [ARCHITECTURE.md](ARCHITECTURE.md)
- **Development and advanced usage**: See [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)
- **Interactive model help**:         Run `lpmptool --help-model`
- **Available models**:               Run `lpmptool --list-models` (add `--sort` for alphabetical)

## Version

Current version: 1.1

## License

Copyright (c) 2026 Wind River Systems, Inc.

SPDX-License-Identifier: Apache-2.0
