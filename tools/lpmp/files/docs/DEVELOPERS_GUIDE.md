# LPMP Developer's Guide

## Overview

The Log Pattern Matching Profiler (LPMP) is a sophisticated log analysis tool designed for performance analysis, timing validation, and system operation profiling. LPMP transforms complex log analysis tasks into simple YAML model definitions, making it accessible to both developers and system administrators.

### What LPMP Is Useful For

LPMP excels in scenarios where you need:

- **Performance Analysis**: Profile system boot sequences, service startup times, and operation durations
- **Timing Validation**: Verify that operations complete within specified time constraints
- **System Correlation**: Analyze events across multiple log files and hosts in chronological order
- **Bottleneck Identification**: Pinpoint performance bottlenecks across all nodes in a collect bundle
- **Regression Testing**: Automate timing validation in CI/CD pipelines
- **Multi-Host Analysis**: Correlate events across multiple systems in bundle mode

### Key Advantages

- **Model-Driven**: Define analysis patterns in human-readable YAML files
- **Multi-Format Support**: Handles regular and compressed (.gz) log files seamlessly
- **Flexible Pattern Matching**: Supports literal strings, regular expressions, and OR patterns
- **Variable Substitution**: Dynamic pattern customization with hostname and custom variables
- **Bundle Mode**: Analyze multiple hosts simultaneously with automatic correlation
- **Dual Output**: Generate both human-readable and CSV formats for further analysis

## Model File Validation and Error Reporting

LPMP automatically validates model files and reports errors at two levels:
YAML syntax and model structure. This catches problems early, before
processing begins.

### Listing Models with Validation Status

Use `--list-models` to see all discoverable models with their validation
status and detected type:

```
FUNCTIONAL MODELS:
 - collectd_cpu_usage_timeline     ✅ timeline
 - swact_soak_model                ❌ format: unknown settings keys: ['max_delta_time']
 - mixed_models                    ❌ yaml error: line 66: but found another document
```

Models are sorted by type group (timeline, pattern, pair) with errors
last. Files that lack a `blocks:` key are silently excluded as non-LPMP
files.

### Validation Levels

**YAML Syntax** — The file must parse as valid YAML. If parsing fails but
the raw text contains `blocks:`, the model is still listed with the YAML
error detail so the author knows which file needs fixing.

**Model Structure** — Once parsed, the YAML is checked against the LPMP
model format rules:

- Top-level keys must be from: `blocks`, `settings`, `include`
- Settings keys must be from: `max_time_delta`, `block_time_tolerance`,
  `start_date`, `loops`, `max_log_length`,
  `profile`, `optional`, `controller`, `graph`, `timeline_patterns`
- Block-level keys must be from: `label`, `file`, `patterns`, `start`,
  `stop`, `timeline`, `optional`, `present`, `profile`, `controller`,
  `override`, `max_time_delta`
- Every block requires `label` and `file`
- Pair blocks require both `start` and `stop`
- Blocks without `patterns`, `start`/`stop`, or `timeline` are rejected
- Duplicate block labels are flagged

The first structural error found is shown in the `--list-models` output
as `❌ format: <error>`. All errors are available programmatically via
`validate_model_structure(data)` which returns a list of error strings.

### Extensionless Model Names

Model names can be specified without the `.yaml` or `.yml` extension:

```bash
lpmptool -m swact_soak_model -l /var/log
```

The tool tries `.yaml` first, then `.yml`, then the bare name. This
applies to both search-path and explicit-path modes.

## Block Types and Processing Modes

LPMP uses "blocks" as the fundamental unit of analysis. Each block represents a specific event or operation to be timed, with automatic type detection based on field presence.

### 1. Pattern Blocks (Sequential Event Timing)

Pattern blocks search for patterns sequentially, where each pattern must be found after the previous pattern in chronological order.

**Use Cases:**
- System boot sequences
- Service initialization chains
- Shutdown procedures
- Orchestrated procedures like Upgrade and Patching
- Multi-step operations across host bundle with override:{host}
- Graph Resource Usage ; i.e. Platform CPU
- Full single host or multi host bundle timeline analysis
- ... and much more

### Stacked Pattern Blocks

Stacked pattern blocks allow multiple patterns to be defined within a single block, providing simplified model structure. The tool automatically expands stacked patterns into individual blocks during model loading, ensuring consistent behavior.

**Key Characteristics:**
- **Auto-Expansion**: Stacked patterns are automatically expanded into individual blocks with labels `original_label_1`, `original_label_2`, etc.
- **No Performance Impact**: Auto-expansion occurs during model loading with zero runtime performance impact
- **Block-Level Settings Inheritance**: All block-level settings (optional, profile, controller, max_time_delta, etc.) apply to ALL expanded patterns
- **Sequential Processing**: Each expanded pattern is processed independently, avoiding all-or-nothing behavior

**When to Use Stacked Patterns:**
- Multiple related patterns in the same log file that should share the same block settings
- Simplified model structure when all patterns have identical configuration requirements

**When to Use Individual Blocks:**
- Different block-level settings needed for different patterns (optional, profile, max_time_delta, etc.)
- Patterns span different log files
- Different timing constraints or behavior requirements per pattern

**Example - Stacked Patterns (All patterns share same settings):**
```yaml
blocks:
  - label: "System Boot Sequence"
    file: "kern.log*"
    patterns:
      - "Kernel command line:"
      - "Loading kernel modules"
      - "System initialization complete"
    max_time_delta: 120
    optional: true
    profile: true
```

**Auto-Expanded Result:**
```yaml
# Tool automatically expands to:
blocks:
  - label: "System Boot Sequence_1"
    file: "kern.log*"
    patterns: ["Kernel command line:"]
    max_time_delta: 120
    optional: true
    profile: true

  - label: "System Boot Sequence_2"
    file: "kern.log*"
    patterns: ["Loading kernel modules"]
    max_time_delta: 120
    optional: true
    profile: true

  - label: "System Boot Sequence_3"
    file: "kern.log*"
    patterns: ["System initialization complete"]
    max_time_delta: 120
    optional: true
    profile: true
```

**Example - Individual Blocks (Different settings needed):**
```yaml
blocks:
  - label: "Critical Boot Step"
    file: "kern.log*"
    patterns: ["Kernel command line:"]
    max_time_delta: 30
    optional: false  # Must be present
    profile: true

  - label: "Optional Module Load"
    file: "kern.log*"
    patterns: ["Loading kernel modules"]
    max_time_delta: 120
    optional: true   # Different setting
    profile: false   # Different setting

  - label: "System Ready"
    file: "kern.log*"
    patterns: ["System initialization complete"]
    max_time_delta: 60   # Different setting
    optional: false
    profile: true
```

**Mixed Models:**
Pattern and pair blocks can be freely interleaved in any order within a model.
All blocks are processed sequentially — each searches after the previous block's
timestamp. Timeline blocks cannot be mixed with pattern or pair blocks.

**Basic Example:**
```yaml
blocks:
  - label: "System Boot Sequence"
    file: "kern.log*"
    patterns:
      - "Kernel command line:"
      - "Loading kernel modules"
      - "System initialization complete"
    max_time_delta: 120  # Allow up to 2 minutes between patterns
```

**Advanced Example with OR Patterns:**
```yaml
blocks:
  - label: "Service Startup"
    file: ["service.log", "service.log.1.gz"]
    patterns:
      - "Service initializing"
      - ["Service ready", "Service active", "Service online"]  # OR pattern
      - "{hostname} service registered"  # Variable substitution
    optional: true  # Don't fail and stop if missing
```


**Example with Present Field:**
```yaml
blocks:
  - label: "System Boot"
    file: "kern.log*"
    patterns:
      - "Kernel command line:"

  - label: "Debug Checkpoint"
    file: "debug.log*"
    patterns:
      - "Debug checkpoint reached"
    present: true  # Capture if found, silently skip if not found (no warnings)
    max_time_delta: 10

  - label: "System Ready"
    file: "syslog*"
    patterns:
      - "System initialization complete"
```

The `present` field is useful for patterns you want to capture if found
but silently skip if not found, without cluttering output with warnings.

**Example with Override Field:**
```yaml
blocks:
  - label: "Swact Request"
    file: "mtcAgent.log*"
    patterns:
      - "{hostname} Administrative SWACT Requested"

  - label: "Swact Query Failed"
    file: ["mtcAgent.log*"]
    present: true
    patterns:
      - "{peer_controller} Query Services Failed"

  - label: "Swact Query Failed"
    file: "mtcAgent.log*"
    present: true  # Display failure only if present, silently skip otherwise
    patterns:
      - "{peer_controller} Query Services Failed"

  - label: "Shutdown mtcAgent"
    file: "mtcAgent.log*"
    patterns:
      - "Received SIGINT"

  - label: "Swact Complete"
    file: "mtcAgent.log*"
    max_time_delta: 200
    override: "{peer_controller}"  # Search in the OTHER controller's logs
    patterns:
      - "{peer_controller} Swact: Complete"
```

The `override` field redirects a block's log search to a different host
in bundle mode, allowing cross-host event correlation within a single
model. In this example, the swact is initiated on `{hostname}` but
completes on `{peer_controller}`, so the final block reaches over to
the peer's logs to find the completion event.

The "Swact Query Failed" block uses `present: true` for failure path
highlighting. It captures the failure event only if it occurred, silently skipping otherwise.

### 2. Pair Blocks (Duration Measurement)

Pair blocks measure the precise time between start and stop events, ideal for timing operations with clear beginning and end points.

**Use Cases:**
- Service startup/shutdown timing
- Database transaction duration
- API response times
- Operation performance measurement

**Basic Example:**
```yaml
blocks:
  - label: "Database Startup"
    file: "postgres.log*"
    start: "database system is starting up"
    stop: "database system is ready to accept connections"
    max_time_delta: 60
```

**Advanced Example with Regex:**
```yaml
blocks:
  - label: "Service Enable Duration"
    file: "sm.log*"
    start: r'Started.*service \(critical-service\)'
    stop: r'Action \(enable\) completed.*service \(critical-service\)'
    max_time_delta: 30
    profile: true  # Generate detailed per-block statistics
```

### 3. Timeline Blocks (Event Collection)

Timeline blocks collect ALL matches for ALL specified patterns and sort them chronologically, with no order requirements.

**Use Cases:**
- Event correlation across multiple sources
- Maintenance event sequencing
- Distributed system event analysis
- Chronological event reconstruction

**Example with Named Patterns:**
```yaml
settings:
  timeline_patterns:
    maintenance:
      - "Host Add Completed"
      - "*** Heartbeat Miss ***"
      - "critical enable failure"
      - "Swact.*complete"

blocks:
  - label: "Maintenance Timeline"
    file: "mtcAgent.log*"
    timeline: "{maintenance}"
```

**Direct Pattern Example:**
```yaml
blocks:
  - label: "System Events"
    file: "system.log*"
    timeline:
      - "System started"
      - "Service ready"
      - "Network interface up"
      - "System shutdown"
```

### 4. Window Blocks (Time-Range Log Extraction)

Window blocks are a timeline variant that collects ALL timestamped log lines from
all matching files within a time window. No pattern matching — every line with a
valid timestamp is captured and sorted chronologically.

**Use Cases:**
- Creating unified system timelines across all log sources
- Investigating incidents within a specific time window
- Correlating events across all log files simultaneously

**Basic Example:**
```yaml
blocks:
  - label: "All Logs"
    file: "*.log*"
    window: true
```

**With Time Bounds and Multiple File Patterns:**
```yaml
settings:
  start_date: "2026-01-06T19:00:00"
  stop_date: "2026-01-06T20:00:00"

blocks:
  - label: "Mtce Logs"
    file: ["mtcAgent.log*", "hbsAgent.log*", "pmond.log*"]
    window: true

  - label: "SM Logs"
    file: "sm.log*"
    window: true
```

**Time Bound Precedence:** CLI `-s`/`-e` > model `start_date`/`stop_date` > auto-detect (5min before latest log)

**File Filtering:** Binary files, known non-log files (wtmp, btmp, lastlog, *.db),
and files with no parseable timestamps are automatically skipped.

### Context Label (Surrounding Log Lines)

The `context:` block-level setting captures surrounding log lines around each
pattern match. Creates a `.context` file per block (similar to `profile:` creating
`.timing` files). Available for pattern and timeline blocks only.

**Symmetric (same before and after):**
```yaml
blocks:
  - label: "Error Context"
    file: "daemon.log*"
    patterns:
      - "critical error"
    context: 5          # 5 lines before and after
```

**Asymmetric (different before and after):**
```yaml
blocks:
  - label: "Failure Context"
    file: "mtcAgent.log*"
    timeline: "{failures}"
    context: [3, 10]    # 3 lines before, 10 lines after
```

## Control Variables Reference

LPMP provides extensive configuration control through variables that can be set at different scopes with clear precedence rules.

### Variable Scope and Precedence

| Variable Name        | CLI | Model | Block | Pattern | Pair | Timeline | Default/Notes  |
|----------------------|-----|-------|-------|---------|------|----------|----------------|
| **Timing Control**                                                                      |
| max_time_delta       | ✓    | ✓    | ✓    | ✓       | ✓   |          | 45 seconds     |
| block_time_tolerance | ✓    | ✓    |      | ✓       | ✓    |  ✓      | 5.0 seconds    |
| **Processing Control**                                                                  |
| start_date           | ✓    | ✓    |      | ✓       | ✓    | ✓       | None           |
| stop_date            | ✓    | ✓    |      | ✓       | ✓    | ✓       | None           |
| loops                | ✓    | ✓    |      | ✓       | ✓    |          | 1             |
| max_log_length       | ✓    | ✓    |      | ✓       | ✓    | ✓       | 180 chars      |
| max_lines            | ✓    |      |      |         |      | ✓       | 20 (0=all)     |
| **Bundle Host Filtering**                                                               |
| host                 | ✓    | ✓    |      | ✓       | ✓    | ✓       | None           |
| **Block Behavior**                                                                      |
| optional             |       | ✓   | ✓    | ✓       | ✓    | ✓       | false          |
| present              |       |      | ✓    | ✓      |       |         | false          |
| profile              |       | ✓   | ✓     | ✓      | ✓     | ✓      | false          |
| context              |       |      | ✓    | ✓      |       | ✓       | None           |
| controller           |       |      | ✓    | ✓      | ✓     | ✓       | false          |
| override             |       |      | ✓    | ✓      | ✓     |         | None           |
| window               |       |      | ✓    |         |       | ✓      | false          |
| **Variable Substitution**                                                                |
| {hostname}           | ✓     |      | ✓    | ✓      | ✓     | ✓      | controller-0    |
| {peer_controller}    | ✓     |      | ✓    | ✓      | ✓     | ✓      | auto-calculated |
| {custom_var}         | ✓     |      | ✓    | ✓      | ✓     | ✓      | --var key=value |

**Precedence Rules:**
1. Command line arguments (highest)
2. Block-level settings (block-specific only)
3. Model-level settings (model-wide)
4. Default values (lowest)

### Timing Control Variables

**max_time_delta**: Controls the maximum allowed time between related events
- Pair blocks: Maximum time between start and stop patterns
- Pattern blocks: Maximum time between sequential patterns
- Timeline blocks: Not applicable

**block_time_tolerance**: Controls how far backwards in time the engine searches for patterns. Handles out-of-order log entries from timing variations and buffering delays. Applied to all model types.

### Bundle Host Filtering

**host**: Sets the `{host}` variable for pattern substitution. Equivalent to `--var host=<value>` or `--host <value>` on the command line.
- Does NOT filter bundle processing or change `{hostname}`
- CLI `--var host=<name>` or `--host <name>` overrides `settings.host`
- Useful for models that reference `{host}` in patterns (e.g., unlock models targeting a specific host)

```yaml
# Model that targets a specific host via settings
settings:
  host: "worker-1"

# Or use CLI: lpmptool --host worker-1 -m model.yaml
# Or use CLI: lpmptool --var host=worker-1 -m model.yaml
```

## Complete Model Examples

### Mixed Mode System Analysis

This example demonstrates a comprehensive system analysis combining different block types:

```yaml
settings:
  max_time_delta: 120
  block_time_tolerance: 10.0
  max_log_length: 200
  profile: true

blocks:
  # Pattern block: Boot anchor
  - label: "System Boot Trigger"
    file: "kern.log*"
    patterns:
      - "Kernel command line:"

  # Pair block: Critical service timing
  - label: "Critical Service Startup"
    file: "sm.log*"
    start: r'Started.*service \(critical-service\)'
    stop: r'Action \(enable\) completed.*service \(critical-service\)'
    max_time_delta: 60

  # Pattern block: Network readiness
  - label: "Network Interface Ready"
    file: "daemon.log*"
    patterns:
      - ["network interface up", "interface ready", "link established"]
    optional: true

  # Pair block: Database initialization
  - label: "Database Initialization"
    file: "postgres.log*"
    start: "database system is starting up"
    stop: "database system is ready to accept connections"
    max_time_delta: 180
```

### Bundle Mode Multi-Host Analysis

For analyzing multiple hosts simultaneously:

```yaml
settings:
  timeline_patterns:
    swact_events:
      - "Swact.*initiated"
      - "Swact.*complete"
      - "Active controller changed"
      - "Standby controller ready"

blocks:
  - label: "Controller Swact Timeline"
    file: "mtcAgent.log*"
    timeline: "{swact_events}"
    controller: true  # Only process on controller hosts

  - label: "Service Impact Analysis"
    file: "sm.log*"
    override: "controller-1"  # Search in controller-1 logs
    timeline:
      - "Service.*disabled"
      - "Service.*enabled"
      - "Service.*failed"
```

### Performance Regression Testing

Automated timing validation model:

```yaml
settings:
  max_time_delta: 45
  profile: true

blocks:
  - label: "Boot Performance"
    file: "kern.log*"
    patterns:
      - "Kernel command line:"
      - "System ready"
    max_time_delta: 30  # Strict boot time requirement

  - label: "Service Startup SLA"
    file: "service.log*"
    start: "Service starting"
    stop: "Service ready"
    max_time_delta: 15  # 15-second SLA

  - label: "API Response Time"
    file: "api.log*"
    start: r'Request.*received'
    stop: r'Response.*sent'
    max_time_delta: 5   # 5-second response time limit
```

## Advanced Features

### Variable Substitution

LPMP supports dynamic pattern customization through variable substitution:

```yaml
# Command line: lpmptool --hostname worker-1 --var env=production --var region=us-west

blocks:
  - label: "Host-Specific Events"
    file: "system.log*"
    patterns:
      - "{hostname} started in {env} environment"
      - "{hostname} registered in {region}"
      - r'{hostname} status: (ENABLED|DISABLED)'
```

### Bundle Mode with Host Override

Cross-host pattern matching within bundle mode:

```yaml
blocks:
  - label: "Controller-0 Events"
    file: "mtcAgent.log*"
    patterns:
      - "{hostname} unlock action"

  - label: "Peer Controller Analysis"
    file: "mtcAgent.log*"
    override: "{peer_controller}"  # Search in peer controller logs
    patterns:
      - "{peer_controller} standby ready"
```

### Profile Generation

Enable detailed per-block statistics:

```yaml
settings:
  profile: true  # Enable for all blocks

blocks:
  - label: "Database Performance"
    file: "db.log*"
    start: "Query started"
    stop: "Query completed"
    profile: true  # Block-specific override
```

## Output Formats and Analysis

### Standard Output

LPMP generates multiple output formats for different analysis needs:

**Pattern Block Output:**
```
Delta(HH:MM:SS)  Hostname      Block Label               Log File      Data
---------------  ------------  -------------------------  ------------ --------
00:00:00.000     controller-0  System Boot Trigger       kern.log     2024-01-06T10:15:20.100: Kernel command line: ...
00:00:05.234     controller-0  Network Interface Ready   daemon.log   2024-01-06T10:15:25.334: network interface up
```

**Pair Block Output:**
```
Delta(HH:MM:SS)  Hostname      Block Label               Log File      Data
---------------  ------------  -------------------------  ------------ --------
00:00:01.535     controller-0  Critical Service Startup  sm.log       10:15:20.100: Start -> Stop: 10:15:21.635: 1.535s
00:00:03.247     controller-0  Database Initialization   postgres.log 10:15:21.635: Start -> Stop: 10:15:24.882: 3.247s
```

### Bundle Mode Output Structure

```
<bundle_dir>/
├── lpmp_<lab>/
│   └── <timestamp>_<model>/
│       ├── controller-0/
│       │   ├── <lab>_controller-0_profile.timing
│       │   ├── <lab>_controller-0_profile.timing.csv
│       │   └── [per-block profiles if enabled]
│       ├── controller-1/
│       │   └── [similar structure]
│       └── <lab>_system_profile.timing  # Merged timeline
```

## Limitations and Considerations

### Known Limitations

1. **Same-Timestamp Pattern Repetition**: When multiple patterns exist at identical timestamps, the tool may find the same pattern repeatedly across loop iterations. Use single-pass analysis (`-n 1`) for such scenarios.

2. **Compressed File Position Tracking**: File position tracking is not available for compressed (.gz) files. The tool relies on timestamp-based search progression.

3. **Cross-File Pair Block Coordination**: Pair blocks spanning multiple files depend on timestamp synchronization. Clock skew may affect accuracy.

4. **Memory Usage**: Large log files or high loop counts may consume significant memory, especially in bundle mode with multiple hosts.

5. **Loop Time Advancement**: The tool advances search time by 500ms between iterations, which may skip patterns within the same 500ms window.

6. **First-10-Lines Timestamp Detection**: `get_file_date_range` reads only the first 10 lines to find the first timestamp. Log files with extensive preamble (e.g., Python warnings) before the first timestamped line will appear to have no timestamps. Add such files to the ignore list in `file_ignore_list_and_format_handling.yaml`.

### Performance Considerations

- **Regex Complexity**: Complex regular expressions may impact performance on large files
- **File I/O**: Position tracking minimizes re-reading, but large files still require significant I/O
- **Memory Scaling**: Timeline models collect all matches before sorting, increasing memory usage
- **Bundle Mode Scaling**: Memory usage multiplies by host count in bundle mode

### Performance Optimization Guide

When speed is critical, certain configurations significantly impact runtime.
Here are the key factors that slow down processing:

**Configurations That Slow Down Processing:**

1. **Timeline Blocks**: Collect ALL matches for ALL patterns before sorting chronologically, requiring full file scans and memory buffering. Use pattern/pair blocks when you only need specific sequential events.
   - **Why slow**: Must scan entire file(s), store all matches in memory, then sort
   - **When to use**: Event correlation across sources, no order requirements
   - **When to avoid**: Sequential event timing with known order

2. **Complex Regular Expressions**: Regex patterns with backtracking, lookaheads, or nested quantifiers slow down line-by-line matching, especially on large files.
   - **Why slow**: CPU-intensive pattern matching on every log line
   - **Optimization**: Use literal strings when possible, simplify regex patterns

3. **High Loop Counts**: Each loop iteration re-scans files from the last found position. High loop counts multiply processing time linearly.
   - **Why slow**: Repeats file scanning and pattern matching N times
   - **Optimization**: Use `--loops 1` for single-pass analysis when appropriate

4. **Bundle Mode with Many Hosts**: Processing multiplies by host count, with each host requiring separate file I/O and pattern matching.
   - **Why slow**: Linear scaling with host count for I/O and processing
   - **Optimization**: Use `controller: true` or --hosts to limit processing to specific hosts

5. **Compressed Files (.gz)**: Decompression overhead and inability to use file position tracking forces timestamp-based searching.
   - **Why slow**: Decompression CPU overhead, no position tracking optimization
   - **Optimization**: Use uncompressed files when speed is critical

6. **Wide Time Windows (max_time_delta)**: Large max_time_delta values force the engine to search further through files before giving up.
   - **Why slow**: Extended search ranges before timeout
   - **Optimization**: Set tight max_time_delta values based on actual expected timing

**Fastest Configuration Recommendations:**
- Prefer pattern/pair blocks over timeline blocks for sequential events
- Use literal strings instead of regex when possible
- Set `--loops 1` for single-pass analysis
- Use uncompressed log files
- Set tight max_time_delta values
- In bundle mode, use `controller: true` to limit processing to controller hosts only

### Best Practices

1. **Pattern Design**: Keep patterns specific enough to avoid false matches but flexible enough to handle log variations
2. **Timing Constraints**: Set appropriate `max_time_delta` values to prevent false triggers
3. **Optional Blocks**: Use `optional: true` for non-critical components to prevent analysis failure (shows warnings)
4. **Present Blocks**: Use `present: true` for pattern blocks to capture if found, silently skip if not found (no warnings)
4. **Variable Usage**: Leverage variable substitution for reusable models across environments
5. **Profile Generation**: Enable profiling selectively to avoid excessive output file generation

## File Ignore List and Custom Timestamp Formats

LPMP auto-loads `file_ignore_list_and_format_handling.yaml` from the model search paths to control
which files are processed by window models and which custom timestamp formats
are recognized.

### Location

The file is searched in the standard model search paths:
1. `<tool_directory>/models/helpers/file_ignore_list_and_format_handling.yaml`
2. `<tool_directory>/models/file_ignore_list_and_format_handling.yaml`
3. `./models/helpers/file_ignore_list_and_format_handling.yaml`
4. `./models/file_ignore_list_and_format_handling.yaml`
5. `/etc/lpmp.d/helpers/file_ignore_list_and_format_handling.yaml`
6. `/etc/lpmp.d/file_ignore_list_and_format_handling.yaml`
7. `/var/lib/lpmp_models/helpers/file_ignore_list_and_format_handling.yaml`
8. `/var/lib/lpmp_models/file_ignore_list_and_format_handling.yaml`

The default location is `models/helpers/` alongside other helper files
such as `wrcp_domains_patterns.yaml`.

### Ignore Section

Files and directories to skip entirely during window model processing:

```yaml
ignore:
  # Directories to prune (trailing / required)
  - "pods/"
  - "lat/"

  # Glob patterns
  - "ceph/ceph-mon.*.log*"
  - "*.txt"

  # Exact basenames
  - "sudo.log"
  - "haproxy.log"
```

Directory entries with trailing `/` prune the entire subtree — no files within
that directory are scanned at all.

### Custom Timestamp Formats

For log files that don't use the standard ISO (`YYYY-MM-DDTHH:MM:SS.fff`) or
sysinv (`sysinv YYYY-MM-DD HH:MM:SS.fff`) formats:

```yaml
timestamp_formats:
  # "YYYY-MM-DD HH:MM:SS.fff" (space separator, dot milliseconds)
  # e.g. 2026-02-27 10:10:13.703 INFO ...
  - pattern:
      - "ceph/ceph-mgr.*.log*"
      - "barbican/barbican-api.log*"
    regex: "(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d{3})"
    format: "%Y-%m-%d %H:%M:%S.%f"

  # "YY-MM-DD HH:MM:SS.fff" (2-digit year)
  # e.g. 26-02-27 16:27:59.202 05[LIB] reloaded ...
  - pattern:
      - "charon.log*"
    regex: "(\\d{2}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d{3})"
    format: "%y-%m-%d %H:%M:%S.%f"

  # "YYYY-MM-DD HH:MM:SS,fff" (comma milliseconds)
  # e.g. (stevedore.extension): 2026-02-27 10:10:13,703 ERROR ...
  - pattern:
      - "keystone/keystone.log*"
      - "tuned/tuned.log*"
    regex: "(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2},\\d{3})"
    format: "%Y-%m-%d %H:%M:%S,%f"
```

Each entry has:
- `pattern`: Glob pattern or list of patterns matched against the file's relative path
- `regex`: Regex with a capture group for the timestamp string
- `format`: strptime format string to parse the captured group

### Discovering Files That Need Entries

Use `--no-ts-files` to list files with no parseable timestamps:

```bash
# Single host
lpmptool -l /var/log --no-ts-files

# Bundle mode
lpmptool -b /path/to/bundle --no-ts-files
```

This walks all log files (respecting the ignore list), reports those where
no timestamp could be parsed, and exits. Use the output to decide whether
each file needs a custom timestamp format entry or should be added to the
ignore list.

## Integration and Automation

### CI/CD Integration

LPMP can be integrated into continuous integration pipelines for automated usage:

```bash
# Example CI script
lpmptool -l /var/log -m performance_sla.yaml --lab ci-build-${BUILD_NUMBER}
if [ $? -ne 0 ]; then
    echo "Performance SLA violation detected"
    exit 1
fi
```

### Monitoring Integration

Use LPMP output for monitoring system integration:

```bash
# Generate CSV for monitoring tools
lpmptool -m monitoring.yaml -o /monitoring/data/
# Process CSV files with monitoring tools
```

This comprehensive guide provides the foundation for effectively using LPMP in various scenarios, from simple single-host log analysis to complex multi-host collect bundle correlation and performance validation.