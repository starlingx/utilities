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

#### Permission-Error Collector
LPMP no longer aborts when it encounters an unreadable file or directory.
Unreadable paths are collected, excluded from processing, and reported in a
summary at the end of the run. This allows analysis to continue even when
parts of the log tree are inaccessible (e.g., due to file permissions or SELinux
contexts).

- Non-optional blocks whose only candidate files are unreadable still fail as "not found"
- Performance impact is zero — errors are collected only on actual failures, not via
  pre-flight access checks
- A fully readable log tree produces no extra output

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
- Each source log line produces **at most one row**. The patterns in the
  block's `timeline:` list are tried in declared order and the first one
  that matches a line emits the row; later patterns are not tried for
  that line (first-match-wins).
- Pattern order can therefore be significant — list specific patterns
  **before** generic ones to avoid silent shadowing.
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

### Fail-Guard Modifier (Polarity Reversal)

`fail: true` is a block-level modifier on a **pattern block** that reverses
its success polarity: finding the pattern (within the block's
`max_time_delta` window, searching from the sequential cursor) **fails the
whole run**, while not finding it is a silent pass. It expresses a negative
assertion — "this must NOT appear here" — such as a kernel panic, segfault,
or an error that should never occur between two anchor events.

Architectural properties:
- **Pattern-block only** and **mutually exclusive** with `optional` and
  `present`, and with `start`/`stop`, `timeline`, and `window`. These
  constraints are enforced both at model-structure validation and at parse
  time, so an invalid combination is rejected before any log is read.
- **Non-recording**: a fail-guard never emits a result row and never
  advances the end-of-pass cursor. Whether it triggers or passes, it leaves
  the timing sequence untouched — it is a gate, not a measured event.
- **On trigger**: results collected so far are flushed in chronological
  order, a `❌ FAIL: ...` line is emitted, and the pass returns
  `success=False`, mirroring the required-block failure path.

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
1. `./` (current directory, highest priority — overrides built-in/packaged models)
2. `/etc/lpmp.d/` (user/developer models, writable in OSTree)
3. `<tool_directory>/models/` (built-in, skipped when running from an installed package)
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
│       │   ├── <lab>_<hostname>_profile.timeline_<graph>.csv  # collectd
│       │   ├── <lab>_<hostname>_profile.timeline_<graph>.png  # collectd
│       │   └── [per-block profiles if enabled]
│       ├── <lab>_system_profile.timing                # Merged timeline
│       └── <lab>_system_profile.timeline_<graph>.png  # Combined hosts graph
```

### System-Level Analysis
- Merged system profile from controller hosts only
- Chronological ordering across all hosts with multi-format timestamp support
  (ISO, space+dot, space+comma, 2-digit year, no-millis)
- Hostname prefixing for event source identification
- System summary with per-host statistics
- **System-level CPU/Memory graph**: when a collectd timeline model is run
  in bundle mode with two or more hosts producing data, lpmp_graph.py
  emits a single combined PNG overlaying every host on one set of axes
  with a hostname-to-color legend. Color assignment is stable across
  runs for the same host set. Palette scales from `tab10` (up to 10
  hosts) to `tab20` (up to 20) to a sampled `hsv` colormap beyond that.
  Honors the bundle host filter (`--hosts`, `--include`, `--exclude`,
  or the single-host `--host` default) so the combined graph contains
  exactly the host set the user selected.

## Model Discovery and Listing

Every model file carries a mandatory top-level `description:` key —
a single-line string that summarises what the model does. The engine
does not read it; it exists solely to power the model catalogue.

`--list-models` (or `-lm`) enumerates all discoverable models, grouped
by detected type in a compact multi-column layout. Column count is
computed live from `max(len(name) for name in visible_names)` and a
target line width of `DEFAULT_LIST_MODELS_MAX_WIDTH` (default 120).
A short-name-only filter (e.g. `-lm pair`) packs more columns into
the same width budget than the unfiltered view whose column width is
constrained by the longest name.

Filter values:
- `timeline`, `pattern`, `pair`, `example` — show one section only
- `desc` (alias `description`) — flat name-plus-description listing
  ordered timeline → pattern → pair → example, one row per line, for
  manual grep

Errors always surface in a dedicated `ERRORS` section regardless of
filter, so a broken model is never silently hidden. Models missing
`description:` are rejected at load time with a symmetric error to
the missing-blocks check.

## Batch Mode

Batch mode executes multiple model/window combinations against the
same bundle in a single invocation, with one read pass per physical
log file. The `--batch <spec.json>` argument dispatches to
`lpmp_batch.run_batch(args)`, bypassing the normal model-file
resolution.

### Input Spec

The batch spec is a JSON file. It may wrap runs in a `runs` array or
be a bare top-level list of runs. Only `model` is required per run;
`start_date` and `stop_date` are optional:

```json
[
  {"model": "ceph_health.yaml",
   "start_date": "2026-02-25T13:35:00",
   "stop_date":  "2026-02-25T13:38:00"},
  {"model": "host_lifecycle.yaml"}
]
```

For each run, the effective time window follows precedence
run entry → CLI `--start-date`/`--stop-date` → model's own
`settings.start_date`/`settings.stop_date` → unbounded. An unbounded
run reads the full file with no time filter, matching mainline
behaviour when neither CLI nor model settings supply dates.

Model names are resolved via the standard search paths, so bare
filenames, relative paths and absolute paths all work. All runs share
the CLI-supplied `--bundle`, `--include`/`--exclude`, `--logs-dir`,
`--lab`, `--output`, `--max-log-length`, and `--verbose`.

### Processing Pipeline

Structurally the batch is three stages arranged around a single
host-outer / file-inner loop nest:

- **Stage 1 (setup, once):** load the spec, load each unique model
  once, resolve per-run `_start`/`_stop` from the precedence chain,
  detect and filter hosts, and precompute each run's output directory
  identity.
- **Stage 2 (scan, one pass per host per file):** for each host,
  fan every run's timeline and window blocks out into a `filepath ->
  [target, ...]` map, then open each grouped file exactly once and
  match every relevant target on each line. This host-outer,
  file-inner loop with runs fanned out as targets is what turns
  `M models x N windows` invocations into one read pass per file per
  host.
- **Stage 3 (merge, one pass per run):** for each run, merge the
  per-host `profile.timeline.log` files it accumulated into a single
  system profile. This is where the per-run streaming summary is
  printed as each merge completes, followed by a final `Output:
  <path>` line naming the batch's tool-runtime directory
  (`_batch_runtime_root`).

Each unique model is loaded once even if several runs share it. Per
host, every run's timeline/window blocks are fanned out into a
`filepath -> [target, ...]` map (pair/pattern blocks are warned about
and skipped), each grouped file is opened exactly once, and every
relevant target is matched against each line in that single pass —
timeline targets via one combined-alternation regex (first-match-wins),
window targets unconditionally within their time window. Once every
host is processed, per-host results are merged into a system profile
per run.

### Output Directory Layout

Batch output gets one extra directory level compared to a mainline
run: a tool-runtime directory shared by the whole batch invocation
(named after the batch's wall-clock start time, `YYYYMMDD_HHMMSS`, so
re-running the same spec never clobbers previous output), under which
each run gets its own subdirectory named from its resolved start/stop
dates and model name. A repeated model name in the spec is rejected
at load time, which guarantees each run's directory name is unique
without needing a disambiguating suffix.

### Constraints

- Timeline and window blocks only. Any pair or pattern block in a
  batched model is warned about (one warning per block) and skipped
  because it carries cross-line ordering state that single-pass
  reading cannot preserve. A run with zero supported blocks after
  filtering is warned about and skipped entirely.
- Each model may appear at most once per batch spec. `load_batch_spec`
  rejects a spec with a repeated model name at load time.
- All runs share a single bundle and host filter. Different bundles or
  disjoint host sets require separate batch invocations.
- Batch mode does not currently drive per-run graph generation. Run
  `lpmp_graph` against the individual run directories to graph batch
  output.

## Jobs Mode

Jobs mode dispatches a JSON-declared list of arbitrary lpmptool
invocations under a bounded worker pool. Unlike batch mode — which is
single-process and timeline/window only — every job is a full mainline
subprocess so any model type is supported: timeline, window, pattern,
pair, mixed, plus graphing side effects. The parent runner never
touches log files itself; it composes argv lists, launches children,
and reaps their exit codes.

### Loop structure

Three stages, all in `lpmp_jobs.py`:

1. **Setup**: load and validate the JSON spec, resolve the effective
   `max_parallel` (CLI > spec > default 3) and `fail_fast`, apply the
   `RLIMIT_NOFILE` pre-flight (raising the soft limit if needed, else
   clamping `max_parallel`), pre-compute a unique output directory per
   job, and build each child's argv list.

2. **Dispatch loop**: `_WorkerPool.run()` alternates between two
   invariant-preserving steps at a 100 ms cadence:

   - **Dispatch step**: while the pending queue is non-empty and
     `running < max_parallel` and no abort has been requested, start
     the next job. Starting a job opens a per-job console log,
     `Popen` runs the child with stdout/stderr redirected to that fd,
     and the parent immediately closes its copy so the child owns
     the descriptor for the rest of its life.

   - **Reap step**: `poll()` each running child. Any child whose exit
     code is available transitions to `passed` (rc == 0), `failed`
     (rc != 0), or `killed` (during an abort). Emit a completion line
     with elapsed time. When `fail_fast` is on and a `failed`
     transition just happened, request pool shutdown.

3. **Merge / summary**: after both the pending queue and the running
   set are empty, print the pass/fail/total summary, list every
   failed or killed job with its console log path, and exit with a
   code derived from the worst child rc (or 130/143 for SIGINT /
   SIGTERM aborts).

### Design guarantees

- **Concurrency invariant**: the number of running jobs never exceeds
  `max_parallel`; a single-threaded poll loop dispatches and reaps, so
  there's no lock discipline to reason about.
- **FD safety**: each child owns its console-log file descriptor
  (the parent closes its copy right after launch), no stdout/stderr
  pipes are held open, `RLIMIT_NOFILE` is pre-flighted at startup and
  raised or `max_parallel` clamped if it's too small, and an absolute
  safety cap of 32 catches typo'd `--max-parallel` values.
- **Collision-free output**: each job's output directory is
  pre-computed before dispatch, with a `_run<N>` suffix when two jobs
  share the same model and wall-clock second, so parallel dispatches
  never stomp each other's files. Console logs for every child land
  under one well-known root for easy post-mortem.
- **Clean shutdown**: SIGINT/SIGTERM at the parent forwards to every
  running child, waits 5s, then escalates to SIGKILL for survivors.
  Exit code is 130 (SIGINT), 143 (SIGTERM), or the worst child rc.
- **Composes with batch mode**: only one of `--batch`/`--jobs` can be
  set per invocation, but a job can itself invoke `--batch` as one of
  its subprocess commands for layered parallelism — no special code
  path needed, since jobs mode is subprocess-based.

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
- Advances by `block_time_tolerance` + 1ms between iterations (not a
  fixed value; default ~5.0s), or 20 minutes if a pass found nothing
- Timeline models ignore loop settings (single pass)
- Automatic EOF detection for loop=0 mode

#### End-of-Pass Cursor Semantics (Declaration Order)

Each pass returns an end-of-pass cursor (`end_time`) that becomes the search
start for the next pass. The cursor reflects the **last block matched in
declared order** — for a pair block, its stop time; for a pattern block, its
match time — set by unconditional overwrite as each block matches. It is
**not** a running maximum across all blocks.

This distinction matters because sequential search, `block_time_tolerance`,
and long-running pair durations can all make a later-declared block resolve
to an *earlier* timestamp than an earlier block. A running-maximum cursor
would let that earlier block's later timestamp hijack the next pass start,
pushing it past legitimate events and silently skipping an entire iteration.
Anchoring the cursor to the last declared block keeps each pass starting
exactly where the previous pass's final event landed. (This is the
kpi-unlock-skipped-iteration fix; fail-guard blocks, being non-recording,
never touch the cursor.)

### Profile Generation
- Per-block timing files with statistical summaries
- Block-level and model-level profile settings
- Samples, average, minimum, maximum calculations
- Individual block result filtering

### Graph Integration
- Automatic graph generation via lpmp_graph.py
- Triggered by `graph` variable definition (`--var graph="<name>"`)
- Per-host CSV and PNG output for collectd CPU and memory timelines
- Bundle mode also produces a system-level combined PNG when two or
  more hosts have data, with a hostname-to-color legend
- Time-bounded graphing via `-s`/`-e` (forwarded from lpmptool)
- Accepts both legacy and current collectd wording (`usage plugin` /
  `usage:` and `dispatch`)
- **Graph style selection**: models may declare `graph_style:` in
  `settings` to choose how the captured timeline is rendered.
  Two styles are supported:
  - `line` (default) — numeric usage values plotted as a continuous
    line. Used by the CPU and memory usage timeline models.
  - `state` — three-level step plot of alarm state transitions
    (okay / warning / failure) for the collectd overage timeline.
    Only committed debounce transitions count; consecutive same-state
    rows are collapsed; a synthetic baseline sample anchored at the
    earliest in-window matched row (or `-s` if earlier) renders the
    prior state before the first transition.
  - System level combined graphs created for usage graphs.
  - No combined system level graph produced for state-style models

### Error Handling
- Graceful failure with clear error messages
- Optional block support to prevent analysis failure
- Regex fallback to literal string matching
- Comprehensive validation with specific error reporting
- Permission errors are collected and excluded rather than fatal (see the
  Permission-Error Collector component), with an end-of-run summary of
  excluded paths

## Testing Architecture

LPMP includes a comprehensive automated test suite with 265+ test cases across 22+ test classes:

- **Unit Tests**: Timestamp parsing, variable substitution, duration formatting
- **Integration Tests**: End-to-end workflows, bundle processing
- **Edge Cases**: Boundary conditions, error scenarios, negative tests
- **Validation Tests**: YAML schema, constraint checking, CLI parsing
- **Code Coverage Analysis**: run_tests.py --with-cov ; requires python3-coverage

## Performance Considerations

### Stacked vs Chained Blocks

Stacked blocks (multiple patterns in one block, see
[Stacked Pattern Blocks](DEVELOPERS_GUIDE.md#stacked-pattern-blocks))
open and read each log file once for all its patterns, so they're
measurably faster than the equivalent chained (one-pattern-per-block)
form when patterns share a file and settings — at the cost of losing
per-pattern setting overrides. `block_time_tolerance` (default 5.0s)
applies within a stacked block the same way it applies across blocks,
letting patterns be found slightly out of chronological order.

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

LPMP minimizes file I/O with a few complementary strategies:

- **Date-aware file ordering**: files are searched oldest-first when
  `start_date` is given (so the earliest match after it isn't skipped
  in rotated files), newest-first otherwise (faster for recent logs).
- **Smart date-range detection**: each file's first/last timestamp is
  sampled cheaply (a few lines at each end; `zcat | tail` for `.gz`)
  during wildcard expansion and cached, so files entirely outside the
  target window are skipped without a full read.
- **Rotation-aware `.gz` pruning**: once one rotation is before the
  window, all older rotations of the same base log are skipped
  without decompression.
- **Chronological progression**: after the first pattern match, file
  position is tracked (regular files only) so later blocks never
  re-read already-processed lines.

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


## Script Runner Extension

Optional post-analysis automation: a model's `settings.script` names a
script to run after the analysis completes, gated behind the opt-in
`--script` flag so a plain run never triggers a side-effecting
subprocess unintentionally. See the Developer Guide's
[Script Runner Feature](DEVELOPERS_GUIDE.md#script-runner-feature)
for configuration, discovery paths, and usage.
