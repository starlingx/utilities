# LPMP Architecture Documentation

## Overview

LPMP (Log Pattern Matching Profiler) is a sophisticated log analysis tool designed for timing analysis, performance profiling, and event correlation.
On-system analysis is limited to the local host only (no SSH to remote hosts). Multi-host analysis operates on all nodes within a collect bundle.
The tool transforms user-defined YAML models into comprehensive timing profiles through a multi-stage processing pipeline.

## Core Architecture

### Processing Pipeline

```
+------------------------------------------------------------------+
| 1. Model Loading                                                 |
|    Parse YAML, validate, block type detection, error checking    |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 2. Variable Expansion                                            |
|    {hostname}, {peer_controller}, custom --var substitution      |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 3. File Discovery                                                |
|    Wildcard expansion, date-proximity sort, .gz detection        |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 4. Pattern Matching                                              |
|    Regex/literal search, OR patterns, sequential processing      |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 5. Timestamp Parsing                                             |
|    Multi-format extraction, date rollover, millisecond precision |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 6. Timing Analysis                                               |
|    Delta calculation, chronological ordering, tolerance reorder  |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 7. Output Generation                                             |
|    .timing (tab-sep, mirrors console), .csv, profile files       |
+------------------------------------------------------------------+
```

LPMP operates through a structured pipeline that transforms patterns into host and system-level timing profiles:

1. **Model Loading**: Parse YAML model files with pattern definitions and settings
2. **Variable Expansion**: Substitute {hostname} and custom variables in patterns
3. **File Discovery**: Expand wildcards and locate log files with date-proximity sorting
4. **Pattern Matching**: Search logs using regex, literal and variable expansion string matching
5. **Timestamp Parsing**: Extract timestamps in multiple formats (sysinv, ISO)
6. **Timing Analysis**: Calculate deltas and maintain chronological ordering
7. **Output Generation**: Produce tab-separated and CSV format results

### Core Components

#### Command Line Interface
- Argument parsing and configuration management
- Mutually exclusive option validation
- Multi-level verbosity control (-v to -vvvvv)
- Bundle mode host selection (interactive, include, exclude)
- Progress indicator control (--progress: none, dots, classic, circles, modern)
- Memory monitoring support (--stats with psutil)

#### YAML Model Loader
- Pattern definitions and settings validation
- Block type auto-detection (pattern/pair/timeline)
- Stacked pattern expansion (multi-pattern blocks → individual blocks)
- Include directive support for modular models
- Unique label validation and constraint checking

#### Variable Substitution Engine
- Dynamic pattern customization with {hostname}, {peer_controller}
- Custom variable support via --var key=value
- Override hostname feature for cross-host pattern matching
- Scope-aware substitution (model, block, pattern levels)

#### Pattern Matching Engine
- Regex and literal string matching with fallback
- OR pattern support for alternative matches
- Sequential pattern processing with chronological ordering
- File position tracking across regular and compressed files

#### Timestamp Parser
- Multi-format timestamp extraction (sysinv, ISO with/without milliseconds)
- ISO regex matches timestamps anywhere in line (not just at start)
- Custom timestamp format support via `file_ignore_list_and_format_handling.yaml`
- Fallback chain: sysinv → ISO → custom formats
- Date rollover handling with full date preservation
- Millisecond precision support

#### File Ignore List and Custom Timestamp Formats
- Auto-loaded `file_ignore_list_and_format_handling.yaml` from model search paths
- `ignore:` section for files and directories to skip entirely
  - Directory prefixes with trailing `/` prune entire subtrees
  - Glob patterns and exact basenames for individual files
- `timestamp_formats:` section for custom parsing rules
  - Maps filename patterns to regex + strptime format pairs
  - Pattern can be a string or list of strings (glob matching)
  - Tried as fallback after built-in ISO and sysinv parsing
- Cache-aware: retries custom formats even if prior call cached (None, None)
- Virtual EOF for stop-date filtering

#### File Position Tracker
- Chronological ordering maintenance across files
- Compressed file (.gz) support with timestamp-based progression
- Wildcard expansion with date-proximity sorting
- Cross-platform path handling

#### Timing Analysis Engine
- Delta calculation with baseline establishment
- Time tolerance reordering for adjacent blocks
- Sequential processing constraints
- Duration measurement for pair blocks

#### Output Generator
- Console output capture system for profile file formatting
- Dedicated output writers per model type (pattern, pair, timeline) in `lpmp_output.py`
- Structured result types (`PatternResult`, `PairResult`, `TimelineResult`) replace rendered strings
- `ModelType` enum (`PATTERN`, `PAIR`, `TIMELINE`) for explicit dispatch — no string-based detection
- Dual format results (human-readable .timing and .csv)
- Per-block profile files with statistical summaries
- Per-block context files (`.context`) showing surrounding log lines around matches
- System-wide merged timelines for bundle mode
- Model-type-aware merge and system summary writers for multi-host bundles
- Hostname-prefixed output for multi-host analysis
- `--max-lines` controls console display of timeline output (default: 20, 0=show all)

## Model Design Philosophy

### Block-Based Architecture

```
                     PATTERN BLOCK PROCESSING
+-------------+   +-------------+   +-------------+   +-------------+
|  Pattern 1  |-->|  Pattern 2  |-->|  Pattern 3  |-->|   Result    |
| (timestamp) |   | (timestamp) |   | (timestamp) |   |  (deltas)   |
+-------------+   +-------------+   +-------------+   +-------------+
    Sequential order required - each builds on previous timestamp


                      PAIR BLOCK PROCESSING
 +-------------+                                     +-------------+
 |    START    |------> Duration Measurement ------->|    STOP     |
 |   Pattern   |        (max_time_delta)             |   Pattern   |
 | (timestamp) |                                     | (timestamp) |
 +-------------+                                     +-------------+
           Precise timing between start and stop events


                    TIMELINE BLOCK PROCESSING
        +-------------+   +-------------+   +-------------+
        |  Pattern A  |   |  Pattern B  |   |  Pattern C  |
        |    (any)    |   |    (any)    |   |    (any)    |
        +------+------+   +------+------+   +------+------+
               |                 |                 |
               +-----------------+-----------------+
                                 |
                                 v
                      +---------------------+
                      | Chronological Sort  |
                      |   (all matches)     |
                      +---------------------+
    Collect ALL matches, sort by timestamp - no order requirements
```

LPMP uses "blocks" as the fundamental unit of analysis. Each block represents a specific event or operation to be timed, with automatic type detection based on field presence:

- **Pattern Blocks**: Sequential event timing using `patterns:` field
- **Pair Blocks**: Duration measurement using `start:`/`stop:` fields
- **Timeline Blocks**: Event collection using `timeline:` field

This design enables flexible modeling approaches from simple event detection to complex multi-host collect bundle analysis.

### Processing Modes

#### 1. Pattern Block Model (Sequential Event Timing)
- Patterns must be found in chronological order
- Each pattern builds upon the previous pattern's timestamp
- Ideal for boot sequences, initialization chains, shutdown procedures
- Supports OR patterns for alternative success indicators

#### 2. Pair Block Model (Duration Measurement)
- Measures precise time between start and stop events
- Enforces max_time_delta constraints to prevent false matches
- Handles date rollover with full timestamp preservation
- Ideal for service startup timing, operation duration analysis

#### 3. Timeline Block Model (Event Collection)
- Collects ALL matches for ALL patterns regardless of order
- Sorts results chronologically by timestamp
- No timing constraints or sequential requirements
- Ideal for event correlation, maintenance timelines, multi-node bundle analysis

#### 4. Window Block Model (Time-Range Log Extraction)
- Timeline variant activated by `window: true` on a block
- Collects ALL timestamped lines from ALL matching files within a time window
- **Recursive subdirectory discovery**: Walks subdirectories of the logs dir
  to find log files (e.g., `ceph/`)
- No pattern matching — every line with a valid timestamp is captured
- Seamlessly spans log rotation boundaries (e.g., `syslog.1.gz` → `syslog`)
- Auto-detects time range (5 minutes before latest log) when no `-s` provided
- Smart file filtering: skips binary, non-log, ignored, and out-of-range files
- Rotation-aware `.gz` pruning: once a rotation is before the window, all
  older rotations of the same base log are skipped without reading them
- Directory pruning via `file_ignore_list_and_format_handling.yaml` (e.g., `pods/`)
- Pre-scan summary shows time window and file classification
- **Note**: Output files can get very large with wide windows since every
  timestamped line from every matched log file is collected. This feature
  is intended for narrow time windows (minutes, not hours)
- Ideal for creating unified system timelines across all log sources

## File Handling System

### Multi-File Support
- Search across multiple log files with fallback ordering
- Wildcard expansion with automatic .gz detection
- Date-proximity sorting based on start_date
- Position tracking for chronological ordering

### Compression Support
- Transparent handling of .gz compressed files
- Timestamp-based search progression for compressed files
- Mixed regular and compressed file processing
- Automatic compression detection by file extension
- Smart date-range detection for .gz files (reads through file for last timestamp)
- Optimized to skip .gz files outside target date range

### Model File Search Path
Model files are searched in priority order:
1. `<tool_directory>/models/` (highest priority)
2. `./models/` (local development)
3. `/etc/lpmp.d/` (user/developer models)
4. `/var/lib/lpmp_models/` (system-provided)
5. Explicit paths (absolute or relative with separators)

Helper files (include files, tool config such as `wrcp_domains_patterns.yaml`
and `file_ignore_list_and_format_handling.yaml`) are stored in a `helpers/`
subdirectory under each model search path. The include directive and file
ignore list loader automatically search these subdirectories.

## Variable System

```
Variable Scope Hierarchy (Highest to Lowest Precedence):

+------------------------------------------------------------------+
| 1. Command Line Arguments                                        |
|    --hostname controller-1 --var service=nova                    |
|    Highest Priority - Overrides all other settings               |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 2. Block-Level Settings                                          |
|    override: "controller-1"                                      |
|    Block-specific overrides for cross-host matching              |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 3. Model-Level Settings                                          |
|    settings: { max_time_delta: 60 }                              |
|    Model-wide defaults applied to all blocks                     |
+--------------------------------+---------------------------------+
                                 |
                                 v
+------------------------------------------------------------------+
| 4. Default Values                                                |
|    {hostname} = "controller-0", max_time_delta = 45              |
|    Lowest Priority - Used when no other values specified         |
+------------------------------------------------------------------+

Built-in Variables:
+------------------------------------------------------------------+
| {hostname}        -> "controller-0" (default) or --hostname value|
| {peer_controller} -> Auto-calculated opposite controller         |
| {custom_var}      -> --var custom_var=value                      |
+------------------------------------------------------------------+
```

### Built-in Variables
- `{hostname}`: Default "controller-0", overridable via --hostname
- `{peer_controller}`: Automatically calculated opposite controller

### Custom Variables
- Defined via --var key=value command line options
- Available in all pattern fields, file paths, and labels
- Scope-aware substitution at model, block, and pattern levels

### Override Feature
- Block-level `override: hostname` for cross-host pattern matching
- Variables recalculated using override hostname context
- Enables correlation analysis across multiple hosts in single model

## Bundle Mode Architecture

```
Bundle Directory Structure:
  bundle_dir/
  ├── controller-0_20240106.120000/
  │   └── var/log/*.log*
  ├── controller-1_20240106.120000/
  │   └── var/log/*.log*
  └── worker-0_20240106.120000/
      └── var/log/*.log*

Processing Flow: Multi-Host Timeline Processing
+-------------+   +-------------+   +-------------+
|Controller-0 |   |Controller-1 |   |  Worker-0   |
| Processing  |   | Processing  |   | Processing  |
+------+------+   +------+------+   +------+------+
       |                 |                 |
       v                 v                 v
+-------------+   +-------------+   +-------------+
|   Host-0    |   |   Host-1    |   |   Host-2    |
|   Output    |   |   Output    |   |   Output    |
+------+------+   +------+------+   +------+------+
       |                 |                 |
       +-----------------+-----------------+
                         |
                         v
                  +-------------+
                  |   System    |
                  |   Merge     |
                  +-------------+
```

### Multi-Host Processing
- Detects hosts from `<hostname>_YYYYMMDD.HHMMSS` directory structure
- Validates consistent date parts across all host directories
- **Priority sort order**: controller-0 first, controller-1, other controllers,
  storage nodes, then all others alphabetically
- Supports interactive, include, and exclude host filtering
- Processes each host independently with per-host output

The bundle mode output structure organizes results hierarchically:

```
<bundle_dir>/
├── lpmp_<lab>/
│   └── <timestamp>_<model>/
│       ├── <hostname>/
│       │   ├── <lab>_<hostname>_profile.timing
│       │   ├── <lab>_<hostname>_profile.timing.csv
│       │   └── [per-block profiles if enabled]
│       └── <lab>_system_profile.timing  # Merged timeline
```

### System-Level Analysis
- Merged system profile from controller hosts only
- Chronological ordering across all hosts with multi-format timestamp support
  (ISO, space+dot, space+comma, 2-digit year, no-millis)
- Hostname prefixing for event source identification
- System summary with per-host statistics

## Timing Constraints and Tolerances

### max_time_delta
- Controls timing constraints for pair and pattern blocks
- Prevents false matches with future unrelated events
- Precedence: Block level > Command line > Model level > Default (45s)
- Applied differently by block type

### block_time_tolerance (Model-level only)
- Controls how far backwards in time the engine searches for patterns (default: 5.0s)
- Handles out-of-order log entries from timing variations and buffering delays
- Applies to pattern and pair models
- No block-level override support

### start_date / stop_date
- Time bounds for log analysis
- Precedence: CLI `-s`/`-e` > model settings `start_date`/`stop_date` > default
- Window models auto-detect start_date (5 minutes before latest log) when not provided
- `stop_date` supported in model settings for all model types

### context (Block-level only)
- Captures surrounding log lines around each pattern match
- Syntax: `context: N` (symmetric) or `context: [before, after]` (asymmetric)
- Writes `.context` file per block with before/match/after sections
- Available for pattern and timeline blocks only (pair blocks ignored)

## Advanced Features

### Stacked Pattern Expansion
- Multi-pattern blocks automatically expand into individual blocks during model loading
- Original block "Service Init" with 3 patterns becomes "Service Init_1", "Service Init_2", "Service Init_3"
- Enables independent pattern processing and improved performance
- Preserves all block properties except patterns list

### Console Output Capture
- Profile files mirror console output formatting with proper spacing
- Model start messages, pass separators, and completion messages included
- TeeOutput class captures console output during processing
- Ensures profile files match console display exactly

### Progress Indicators
- Five types available for timeline models: none, dots, classic, circles, modern
- Controlled via --progress/-p command line option
- Different performance impacts: none (zero), dots (minimal), classic/circles (low), modern (medium)
- Automatic for timeline models, disabled for pattern/pair models

### Loop Processing
- Multiple analysis passes with time advancement
- 500ms minimum advancement between iterations
- Timeline models ignore loop settings (single pass)
- Automatic EOF detection for loop=0 mode

### Profile Generation
- Per-block timing files with statistical summaries
- Block-level and model-level profile settings
- Samples, average, minimum, maximum calculations
- Individual block result filtering

### Graph Integration
- Automatic graph generation via lpmp_graph.py
- Triggered by graph variable definition
- CSV and PNG output generation
- Currently supports collectd model profiles

### Error Handling
- Graceful failure with clear error messages
- Optional block support to prevent analysis failure
- Regex fallback to literal string matching
- Comprehensive validation with specific error reporting

## Testing Architecture

LPMP includes a comprehensive automated test suite with 265+ test cases across 22+ test classes:

- **Unit Tests**: Timestamp parsing, variable substitution, duration formatting
- **Integration Tests**: End-to-end workflows, bundle processing
- **Edge Cases**: Boundary conditions, error scenarios, negative tests
- **Validation Tests**: YAML schema, constraint checking, CLI parsing
- **Code Coverage Analysis**: run_tests.py --with-cov ; requires python3-coverage

## Performance Considerations

### Stacked vs Chained Blocks

LPMP supports two approaches for organizing multiple sequential patterns:

#### Stacked Blocks (Multiple Patterns in One Block)
```yaml
blocks:
  - label: "Service Initialization"
    file: "service.log*"
    patterns:
      - "Service starting"
      - "Loading configuration"
      - "Connecting to database"
      - "Service ready"
```

#### Chained Blocks (Separate Blocks)
```yaml
blocks:
  - label: "Service Starting"
    file: "service.log*"
    patterns:
      - "Service starting"

  - label: "Loading Configuration"
    file: "service.log*"
    patterns:
      - "Loading configuration"

  - label: "Connecting to Database"
    file: "service.log*"
    patterns:
      - "Connecting to database"

  - label: "Service Ready"
    file: "service.log*"
    patterns:
      - "Service ready"
```

#### Performance Implications

**Stacked Blocks (Recommended for Sequential Patterns):**
- **File I/O Efficiency**: Opens and reads each log file only once for all patterns
- **Position Tracking**: Maintains file position across patterns, avoiding re-reading
- **Performance Gain**: 42% runtime reduction (31s → 18s) measured for 5 patterns in 5 loops
- **Best For**: Patterns in the same log file(s) occurring in chronological sequence

**Chained Blocks (Better for Flexibility):**
- **File I/O Overhead**: Opens and reads log files separately for each block
- **Flexibility**: Each block can have different settings (optional, max_time_delta, etc.)
- **Output Granularity**: Each pattern gets its own labeled output line
- **Best For**: Patterns requiring different settings or from different log files

#### block-time-tolerance Application

**Important**: The `block-time-tolerance` setting applies to patterns within stacked blocks:
- Allows patterns to be found slightly out of chronological order
- Handles logging system timing variations and buffering delays
- Smart date-range filtering uses block_time_tolerance to avoid skipping files
- Default: 3.0 seconds (configurable at model level)

**Example**:
```yaml
settings:
  block_time_tolerance: 5.0  # Allow 5 seconds tolerance

blocks:
  - label: "Service Initialization"
    file: "service.log*"
    patterns:
      - "Service starting"      # Found at 10:00:00
      - "Loading configuration" # Found at 09:59:58 (2s before, within tolerance)
      - "Service ready"         # Found at 10:00:05
```

#### Recommendations

**Use Stacked Blocks When:**
- Patterns are in the same log file(s)
- Patterns occur in chronological sequence
- All patterns share the same settings (file, optional, max_time_delta)
- Performance is critical (high loop counts, large log files)
- You want to minimize file I/O operations

**Use Chained Blocks When:**
- Patterns require different settings per block
- Patterns are in different log files
- You need individual control over optional/present behavior
- Output granularity is more important than performance
- Patterns may not be chronologically sequential

**Performance Measurement**:
- Real-world testing: 5 patterns, 5 loops, survivor_pattern_model.yaml
- Chained blocks: 31 seconds
- Stacked blocks: 18 seconds
- Improvement: 42% reduction in runtime
- Primary benefit: Reduced file I/O and smart filtering overhead

### Memory Usage
- Large log files may consume significant memory
- Bundle mode multiplies memory usage by host count
- Timeline models collect all matches before sorting
- Memory and performance statistics with --stats option (requires psutil)
- Progress indicators for timeline models (5 types: none, dots, classic, circles, modern)

### Regex Performance
- Complex patterns may impact performance on large files
- Automatic fallback to literal matching on regex errors
- Pattern optimization recommendations in documentation

### File I/O Optimization

LPMP implements several optimizations to minimize file I/O and maximize search performance:

#### Date-Aware File Ordering
- **With start_date**: Oldest files first (chronological) so the first block finds the
  earliest match after start_date in rotated files instead of skipping them
- **Without start_date**: Newest files first (reverse chronological) for faster searches
  targeting recent logs
- **Implementation**: `expand_and_sort_log_files()` sorts by mtime — ascending when
  start_date is provided, descending otherwise

#### Smart Date-Range Detection
- **Efficient Sampling**: Reads only first 10 and last 50 lines of each file to extract date range
- **File Skipping**: Files outside the target date range are skipped entirely during pattern search
- **Timestamp Caching**: Date ranges determined during wildcard expansion, cached for search phase
- **Dual Strategy**:
  - Regular files: Seek to end and read backwards for last timestamp
  - Gzipped files: Uses `zcat | tail` for fast last-timestamp detection

#### Intelligent File Filtering
- **Pre-Search Validation**: `find_pattern_in_files()` checks file date ranges before opening
- **Skip Conditions**:
  - File's last timestamp is before `after_timestamp` (search start time)
  - File's first timestamp is after `after_timestamp + max_time_delta`
- **Tolerance Handling**: Respects `max_time_delta` when determining file relevance
- **Verbose Logging**: Level 3 verbosity shows which files are skipped and why

#### Chronological Search Progression
- **Forward Progression**: After first pattern found, subsequent searches progress chronologically
- **Position Tracking**: Maintains file position for regular files to avoid re-reading
- **Timestamp Filtering**: Uses `after_timestamp` to skip already-processed log entries
- **Sequential Optimization**: Each block builds on previous block's timestamp

#### Performance Benefits

**Typical Use Case** (searching recent logs):
- **Before Optimization**: Searches oldest rotated files first (e.g., daemon.log.10.gz → daemon.log.1.gz → daemon.log)
- **After Optimization**: Searches newest file first (daemon.log), finds pattern immediately
- **I/O Reduction**: 90%+ reduction in files opened/read for recent log searches
- **Time Savings**: Proportional to number of rotated log files skipped

**Large Rotation Scenario** (10+ rotated .gz files):
- **Rotation-Aware Pruning**: Once a `.gz` rotation is before the time window, all higher-numbered
  rotations of the same base log are skipped without decompression
- **Fast `.gz` Timestamp Detection**: Uses `zcat | tail` instead of Python line-by-line decompression
- **Binary Search Seek**: For plain-text files > 32 KB, binary search jumps near the start timestamp
  instead of scanning from the beginning of the file
- **Minimal Overhead**: Date-range sampling adds <100ms per file, saves seconds/minutes in search time
- **Scalability**: Performance improvement increases with number of rotated files

**Historical Search** (targeting old logs):
- **Graceful Degradation**: Still searches all files, but in reverse order
- **Date-Range Benefit**: Skips files newer than target date range
- **No Performance Loss**: Optimization doesn't penalize historical searches

#### Implementation Details

**File Ordering Algorithm**:
```python
# Sort oldest first when start_date is provided (find earliest match),
# newest first otherwise (find recent matches faster)
file_info.sort(key=lambda x: x[1], reverse=(start_date is None))
```

**Date-Range Detection**:
```python
# Read first 10 lines for first timestamp
for _ in range(10):
    line = f.readline()
    ts = parse_timestamp(line)
    if ts:
        first_ts = ts
        break

# Seek to end and read last ~4KB for last timestamp
f.seek(0, 2)  # End of file
seek_pos = max(0, file_size - 4096)
f.seek(seek_pos)
lines = f.readlines()
for line in reversed(lines[-50:]):
    ts = parse_timestamp(line)
    if ts:
        last_ts = ts
        break
```

**Smart File Filtering**:
```python
# Skip file if after_timestamp is before file's date range
if after_timestamp < first_ts:
    vlog3(f"Skipping {filename}: before file range")
    continue

# Skip file if after_timestamp is after file's date range
if after_timestamp > last_ts + tolerance:
    vlog3(f"Skipping {filename}: after file range")
    continue
```

## Extensibility

### Model Modularity
- Include directive for shared pattern definitions
- Named timeline pattern sets for reusability
- Block-level setting overrides for customization

### Output Flexibility
- Multiple output formats (timing, CSV, profile)
- Configurable log line truncation
- Hostname column control for different modes

### Integration Points
- Graph tool integration for visualization
- CSV output for external analysis tools
- System summary generation for reporting

This architecture provides a robust foundation for log analysis across diverse environments, from single-host on-system analysis (local host only, no SSH) to multi-host collect bundle correlation.