# LPMP Change History

## Introduction

This document tracks the evolution of the Log Pattern Matching Profiler (LPMP) tool, capturing significant changes, bug fixes, architectural improvements, and feature additions. Each entry represents a meaningful change to the codebase, documentation, or functionality.

The history is organized chronologically with the most recent changes at the top, following industry standard practices for change documentation.

---

## Current Code Coverage Summary (2026-06-30):
  ```
============================================================
lpmp_engine.py : 85% coverage
lpmp_output.py : 83% coverage
lpmp_graph.py  : 96% coverage
lpmp_utils.py  : 83% coverage
lpmptool.py    : 67% coverage
Overall        : 80% coverage with 577 of 577 tests passing
============================================================
  ```

## Change History

### 2026-06-30 - Timeline First-Match-Wins and Model Pattern Cleanup
- **Timeline blocks emit at most one row per source log line.** For each
  log line, patterns in the block's `timeline:` list are tried in
  declared order and the first one that matches emits the row; later
  patterns are not tried for that line. OR-list (nested list) entries
  are flattened into the same ordered alternation. Pattern order is now
  semantically significant — list specific patterns before generic
  ones so the more specific tag wins.
- **Substantial speedup as a side benefit.** A single combined
  alternation regex is scanned once per file instead of one scan per
  pattern, reducing file passes from N×F to F. On real bundles this
  produces roughly 4-5× wall-clock speedup on multi-pattern timeline
  models (e.g. `mtce_timeline_model`, `ceph_health`).
- **Invalid patterns no longer disable a block.** Each timeline pattern
  is compiled individually; a single broken regex is logged with a
  warning and dropped, the remaining patterns continue to apply.
- **Model pattern cleanup**: `models/examples/shared_patterns.yaml` had
  `"*** Heartbeat Miss ***"` which is an invalid regex — corrected to
  `'\*\*\* Heartbeat Miss \*\*\*'`. `models/examples/pair_only_example.yaml`
  showed a `\1` backreference between pair-block start and stop
  patterns; the engine compiles those patterns independently and does
  not carry captures across them, so the example was rewritten to use
  literal `\d+` in both halves with a comment noting the limitation.
- **Removed stale duplicate** `models/wrcp_domains_patterns.yaml`. The
  canonical pattern library lives at `models/helpers/wrcp_domains_patterns.yaml`
  and is referenced by every model that uses the shared sets.
- Added 5 new tests in `test_timeline_models.py` covering first-match
  on overlapping patterns, pattern order significance, OR-list
  flattening, invalid-regex skip, and the all-invalid degenerate case.
  Total: 571 tests, 555 passing under default run (16 skipped without
  `--bundle`).
- **Test suite speed**: The bundle-mode timestamp-format tests were
  re-running lpmptool against the whole bundle for each format group,
  which meant reading and decompressing every rotated copy of files
  like `charon.log*.gz` (sometimes hundreds of MB per host) once per
  test. The tests still passed but the class dominated the suite's
  wall-clock time. Each test now extracts a small slice (~200 lines)
  of one matching file from the real bundle into a temporary
  self-contained mini-bundle and runs lpmptool against that. Same
  end-to-end engine path is exercised — file walk, timestamp format
  dispatch, timeline emit — but each test now completes in well under
  a second regardless of source bundle size.
- **Test suite portability across bundles**: The four
  `TestBundleRegression` tests previously hard-coded
  `--include controller-0 controller-1 compute-0`, which made them
  fail outright on any bundle that did not contain a node with the
  exact name `compute-0`. They now discover hostnames from the bundle
  directory layout and pass that exact list to `--include`, so the
  tests adapt to whatever bundle is supplied. A coverage note is
  printed once at the end of the regression class listing the hosts
  detected and flagging if the bundle has fewer than 2 controllers
  or no worker/compute node (in which case multi-host code paths
  receive less coverage). The `test_context_override_block_bundle`
  test now scans both controllers' `mtcAgent.log` (including any
  rotated `.gz` copies) for the `'Daemon Start'` anchor, picks the
  one that has it as the local host, and uses the other as the
  override peer. It skips cleanly only when neither controller has
  the anchor.
- **Test ordering**: `run_tests.py` now reorders the discovered
  suite so any test class whose name contains `Bundle` runs after
  all other tests. Bundle-mode tests are the slowest (they scan a
  real collect bundle) so deferring them keeps fast feedback on
  the rest of the suite when running interactively. A newline is
  emitted on the dot stream the first time a bundle class starts so
  the slow section is visually separated.
- **Skip reporting**: `run_tests.py` now lists each skipped test
  with its reason at the end of the run. When `--bundle` is not
  provided, bundle-mode skips are suppressed from the listing since
  they are already summarised by the closing 'N bundle regression
  tests were skipped' line.
- **Coverage uplift to 80%**: Six small targeted tests were added
  to `TestMainExecution` to exercise non-interactive code paths
  that were previously untested: `--max-lines -1` rejection,
  `--file-position-tracking` flag, `--help-model 1` direct topic
  output, `--help-model 999` invalid topic error path,
  `--no-ts-files` in `--logs-dir` mode, and the graph subprocess
  trigger when `--var graph=...` is set on a pattern model. Overall
  coverage moved from 79% to 80%. Updated per-file figures:
  `lpmp_engine.py` 85%, `lpmp_output.py` 83%, `lpmp_graph.py` 96%,
  `lpmp_utils.py` 83%, `lpmptool.py` 67%, with 577 of 577 tests
  passing.

### 2026-06-26 - Collectd Graph Enhancements
- **Collectd CPU/Memory models accept new `dispatch` wording**: The
  `collectd_cpu_usage_timeline` and `collectd_memory_usage_timeline`
  models now match both legacy (`usage plugin` / `usage:`) and now
  (`dispatch`) collectd wording. Bundles with the newer collectd
  wording now produce data in instead of silently writing empty
  per-host output directories with this update to `lpmp_graph.py`.
- **`lpmp_graph.py` usage-type matching is now case-insensitive**:
  The documented `--var graph="Platform CPU"` (capital CPU) and similar
  capitalisations of `Platform Mem` now work where previously the
  internal gates were case-sensitive and could produced empty graphs.
- **Time-bounded graphing (`-s` / `-e`)**: `lpmp_graph.py` accepts the
  same start/stop date arguments as `lpmptool`, with identical parsing
  and inclusive bounds.
- **System-wide multi-host graph**: After per-host graphs are produced,
  `lpmptool` now also writes a single combined PNG overlaying every
  host on one set of axes with a hostname → color legend.
- **Add vlog support to lpmp_graph.py**: Added `vlog` support to the
  graph handling models.
- **Improved Test coverage on `lpmp_graph.py`**: Added 37 new positive
  and negative test cases (17 → 54) covering the graph helpers,
  `extract_usage_data` bounds, `create_system_graph`, and the `main()`
  / `_run_combine_mode` entry points. Verified end-to-end on a
  multi-controller bundle: per-host CSV/PNG output, the new combined
  system PNG, and `-s`/`-e` bound filtering all produce the expected
  results.

### 2026-06-03 - Mixed Models, Bundle Date Mismatch, Window Improvements, and Quoting Convention
- **Mixed pattern + pair models**: Removed the restriction that pattern blocks
  could only appear as the first block in a model containing pair blocks.
  Pattern and pair blocks can now be freely interleaved in any order. Context
  files (`.context` outputs) are also now produced for pattern blocks within
  mixed models. The timeline/non-timeline mixing restriction remains.
- **Bundle date mismatch auto-accept**: Host directories in a bundle
  with different date suffixes are accepted automatically. The tool
  logs a warning listing the mismatched date groups and proceeds using
  the directory with the latest date part for each hostname.
- **Auto-descent into `var/log`**: When `--logs-dir` resolves to a directory
  that contains a `var/log` subdir, the tool now automatically descends into
  it. Prevents accidentally scanning huge non-log subtrees (e.g.
  `var/extra/ostree_repo/objects/` with hundreds of thousands of `.filez`
  files) when the user points at a host directory.
- **Window mode progress indicator**: The pre-scan phase of window models
  now shows the standard progress indicator while walking the logs dir,
  giving feedback during long scans instead of appearing to hang.
- **Window mode display paths**: Output now shows scan paths and per-file
  paths relative to the user-supplied `--logs-dir` instead of the post-
  descent absolute path. Less confusing when the auto-descent kicks in.
- **Cwd-aware `--logs-dir` resolution**: Relative `--logs-dir` values now
  resolve against the current working directory when the path exists there,
  falling back to filesystem root only if it does not. This makes
  `lpmptool -l .` behave intuitively without breaking the default
  `var/log` → `/var/log` system-mode resolution.
- **Faster pre-scan filename filter**: Window mode now skips obvious
  non-log file extensions (`.filez`, `.tar`, `.deb`, `.rpm`, `.iso`,
  `.so`, `.pyc`, etc.) by basename alone instead of opening each file
  for a binary-content check. Major speedup on bundles that contain
  large package or installer trees.
- **Optional-block warning ordering**: Warnings from failed optional blocks
  now sort to the end of the chronological output instead of tying with the
  most recent successful timestamp. Prevents a late-in-the-model warning from
  appearing in the middle of earlier matches.
- **Override-aware warning paths**: Warnings for optional blocks with an
  `override:` clause now show the override target host's logs path, matching
  where the search actually ran.
- **Stop-progress safety**: `stop_progress_indicator` is now safe to call
  with `None` and tolerates a closed stdout, fixing test-suite failures in
  environments that capture/close streams.
- **Quoting convention for pattern fields**: All shipped models now use
  single quotes for `patterns`, `timeline`, `start`, `stop` and entries in
  `timeline_patterns` named sets. Other fields (`label`, `file`, `override`,
  etc.) keep double quotes. Single quotes pass backslashes through to the
  regex engine, so `\w`, `\d`, `\(`, `\)` and friends work without YAML
  double-escaping. The tool itself accepts either style; this is purely a
  documented convention to make regex patterns readable. Developer guide
  updated with rationale, examples, and common pitfalls.
- **System timeline neighbor-relative deltas**: The merged bundle timeline
  output (`<lab>_system_profile.timeline.log`) now recomputes the leading
  Delta column as the difference to the previous merged line across hosts,
  instead of leaving the per-host deltas the original files were written
  with. Reading the merged timeline now answers "how long since the
  previous event anywhere in the system" at a glance, regardless of which
  host produced it. Warning lines (`??:??:??.???`) are preserved unchanged.
- Added 2 new tests in `test_lpmp.py` covering the bundle date-mismatch
  auto-accept and latest-per-host selection, and 2 new tests in
  `test_lpmp_output.py` covering the cross-host delta recomputation in
  the merged system timeline.

### 2026-04-08 - Host Option, List-Models Enhancements, and Loops=0 (496 → 520 tests)
- **`--host` option**: New command line option that sets the `{host}` variable
  for pattern substitution. Shorthand for `--var host=<value>`. Also supported
  as `host:` in the model settings section. Precedence: CLI `--var host=` >
  CLI `--host` > model `settings.host`. In bundle mode without explicit
  `--include`/`--exclude`, `--host` defaults to processing only the
  `--hostname` host's logs.
- **`--sort` option**: New flag for `--list-models` that sorts output
  alphabetically by model name.
- **Helper models in `--list-models`**: The `--list-models` display now
  discovers and lists helper models from `helpers/` subdirectories in model
  search paths.
- **Example model run guard**: Running an example model (from `examples/`
  directory) now prints a note that example models are for syntax reference
  only and exits, preventing confusing failures.
- **`--loops 0` (until EOF)**: Changed `--loops` validation from requiring
  ≥1 to requiring ≥0. Value 0 means "loop until no more patterns found"
  (until EOF). First-loop failure still exits with error; subsequent loops
  ending with no matches exit cleanly.
- **`--max-lines` validation**: Added validation that `--max-lines` must be ≥0.
- Added 11 tests in `test_force_option.py` (new file), 13 tests in
  `test_host_setting.py` (new file), 2 tests in `test_cli_arguments.py`,
  and 1 test in `test_edge_cases.py`.

### 2026-04-07 - Force Mode (--force / -f)
- **Force past non-first block failures**: New `--force` / `-f` command line
  option that treats required block failures as warnings for all blocks after
  the first. The first block must still succeed — it establishes the anchor
  timestamp. Subsequent blocks that fail are downgraded to warnings and
  processing continues, just like `optional: true` but applied from the
  command line without modifying the model. Useful for getting partial
  timing profiles when not all expected events are present in the logs.

### 2026-04-06 - Window Model Performance Optimizations
- **Bisect seek for plain-text files**: Binary search in files >32KB to jump
  near the start timestamp instead of scanning linearly from the beginning.
  Saves ~3s on narrow time windows across large log files.
- **Rotation-aware `.gz` pruning**: Groups `.gz` files by base name and
  rotation number. Once a rotation is entirely before the time window, all
  higher-numbered rotations are skipped without decompression. Reduces
  pre-scan time from ~18s to <1s on typical bundles.
- **`zcat | tail` for `.gz` last-timestamp**: Replaced Python line-by-line
  gzip decompression with `zcat | tail -50` subprocess for reading the last
  timestamp from `.gz` files. Uses `shlex.quote` for safe shell escaping.
- **`.gz` binary classification fix**: Fixed `discover_window_files` rejecting
  `.gz` files as "binary/non-log" because gzip files contain null bytes.
  The `_is_skippable_file` check is now skipped for `.gz` files.
- Added 28 new tests (468 → 496) covering bisect seek, rotation pruning,
  `.gz` date range, failure handling, and window boundary edge cases.

### 2026-04-03 - Subdirectory Log Support, File Ignore List, and Custom Timestamps
- **Subdirectory log file discovery**: Window models now recursively discover
  log files in subdirectories of the logs dir (e.g., `nova/`, `sysinv/`,
  `ceph/`). The `_expand_window_globs` helper walks subdirectories and applies
  glob patterns at each level. Non-window blocks are unaffected — users can
  already specify subdirectory paths explicitly (e.g., `file: "nova/*.log*"`).
- **Directory skip in window discovery**: Directories matched by glob patterns
  are silently skipped instead of causing "Is a directory" errors. Empty
  directories are reported as `(directory empty)` at `-v` verbosity.
- **File ignore list** (`file_ignore_list_and_format_handling.yaml`): Auto-loaded from model search
  paths. Supports directory pruning (trailing `/`), glob patterns, and exact
  basenames. Ignored directories are pruned during recursive walks so their
  contents are never scanned. Ignored files are skipped in window discovery,
  auto-detect, and `--no-ts-files`.
- **Custom timestamp formats**: The file ignore list supports a
  `timestamp_formats` section that maps filename patterns to custom regex/strptime
  rules. `parse_timestamp` falls back to custom formats after built-in ISO and
  sysinv parsing. `get_file_date_range` passes `relpath` through for format
  matching. Cache-miss retry ensures custom formats are tried even if a prior
  call without `relpath` cached `(None, None)`.
- **Relaxed ISO timestamp parsing**: The ISO regex now matches timestamps
  without milliseconds (e.g., `2026-02-27T10:32:06Z`). The ISO regex also
  runs on all lines regardless of first character, fixing files like
  `sm-customer.log` where timestamps appear mid-line after `|` delimiters.
- **`--no-ts-files` option**: New command line option that walks the logs dir
  (or all bundle hosts) and lists files with no parseable timestamps, then
  exits. Respects the file ignore list. Useful for discovering files that need
  custom timestamp format entries or should be added to the ignore list.
- **Bundle host sort order**: Bundle hosts are now processed in priority order:
  controller-0 first, controller-1, other controllers, storage nodes, then
  all others alphabetically.
- **System profile merge fix**: `_extract_timestamp_from_data` in
  `lpmp_output.py` now handles all custom timestamp formats (comma millis,
  2-digit year, no millis with trailing colon) so the merged system profile
  sorts correctly across all log formats.

### 2026-04-02 - Window Model, stop_date, and max-lines Support
- **Window model**: New `window: true` block type that collects ALL log lines
  from ALL specified log files within a time window into a single chronological
  system timeline. No pattern matching — every timestamped line in the window
  is captured and sorted across all files. Auto-detects time range (5 minutes
  before latest log) when no `-s` is provided. Skips binary and non-log files
  automatically. Pre-scan summary shows matched/skipped files and time window.
- **stop_date in model settings**: All model types now support `stop_date` in
  the settings section, with the same precedence as `start_date`: command line
  `-e` overrides model setting, model setting overrides default.
- **Model search path fix**: Fixed `get_models_search_paths` to exclude
  dist-packages/site-packages directories from the model search path when
  installed as a Python package.
- **--max-lines option**: New command line option to control how many lines
  of timeline output are displayed to the console (default: 20, 0=show all).
  Prevents large timeline outputs from flooding the terminal while still
  writing the complete output to profile files.
- **Context label**: New `context:` block-level setting that captures surrounding
  log lines around each pattern match. Writes a `.context` file per block showing
  N lines before and after each match. Supports symmetric (`context: 5`) and
  asymmetric (`context: [3, 10]`) line counts. Available for pattern and timeline
  blocks only (pair blocks ignored with warning).
- Added 30 new tests (435 total) covering window model, context label parsing,
  context extraction, context output, and integration tests.

### 2026-04-02 - Context Label Test Coverage Expansion (435 → 462 tests)
- **extract_context_lines edge cases** (9 tests): Match at EOF, zero before/after,
  both zero, file not found, no match, large context on small file, gzipped file,
  first-occurrence-wins with duplicate lines.
- **load_model context parsing failures** (5 tests): Invalid string/single-element
  list/three-element list trigger sys.exit(1); zero value accepted; timeline block
  with context accepted.
- **write_context_files variations** (7 tests): Multiple matches in one block,
  multiple blocks produce separate files, no matching results produces no file,
  empty context tuples, TimelineResult with context, blocks without context_before
  skipped, results with context=None filtered out.
- **Bundle integration tests** (6 tests, require `--bundle` or `LPMP_TEST_BUNDLE`):
  context from gzipped log, pattern model against real sm.log, timeline model
  against real mtcAgent.log, override block reading peer controller's logs,
  window model with file filtering, present:true unfound block produces no
  .context file.
- Updated run_tests.py skip count message (4 → 10 bundle tests).
- Updated validate_model tests for window and context keys.

### 2026-03-27 - Search Performance Optimizations
- **Time-bounded timeline search**: Timeline models now benefit from the same
  date-range optimizations as pattern and pair models — files outside the search
  window are skipped, lines before the start date are filtered before pattern
  matching, and reading stops early once past the stop date instead of scanning
  to end-of-file
- **Early file pruning**: Log files outside the global start/stop date window are
  now removed from each block's file list before processing begins, avoiding
  repeated per-search filtering of files that can never contain relevant data
- **Regex pre-compilation**: Search patterns are compiled once before scanning
  rather than re-evaluated on every line, also simplifying the match logic by
  eliminating a duplicated fallback code path
- **Timestamp parsing optimization**: Pre-compiled timestamp regexes at module
  level and added a cheap first-character prefix guard to reject lines that
  can't contain timestamps before touching regex at all

### 2026-03-27 - CLI Input Validation Test Coverage (345 → 405 tests)
- **Stop date validation**: Tests for invalid format, stop before start, and
  stop equal to start — all verify exit code 1
- **Mutually exclusive options**: Test for `--include` + `--exclude` conflict
- **Host options without bundle**: Tests for `--include` and `--exclude` used
  without `--bundle` mode
- **Invalid variable format**: Strengthened existing `--var` test with exit code
  check and added stderr message verification
- **Stop date parsing**: Verified date-only input parses to end of day (23:59:59)
  and full ISO format is preserved exactly
- **Model file not found**: Strengthened with exit code check and added search
  path hint verification in stderr
- **Logs dir validation**: Strengthened with exit code check and added "is not a
  directory" stderr verification
- **Bundle path validation**: Added early validation of bundle path before host
  detection, with clear error message for non-existent or invalid paths
- **Settings precedence**: Tests for max-time-delta (CLI > model > default),
  loops (CLI > model > default), and start-date (CLI > model) override order
- **Output directory structure**: Tests verifying the `lpmp_<lab>/<timestamp>_<model>`
  directory layout for both explicit `-o` and default cwd-based output paths

### 2026-03-27 - Usability Improvements (367 → 405 tests)
- **Consistent output file listing**: System mode now lists individual output
  file paths the same way bundle mode does, instead of just showing the directory
- **Flexible date input**: The `-s` and `-e` options now accept all partial ISO
  date formats (date-only, hour, hour:minute, full, with milliseconds) and
  normalize any separator character at the date/time boundary — so spaces,
  colons, or other characters between date and time are accepted gracefully
- **Improved date error messages**: Invalid dates now show all accepted formats
  in the error message to guide the user
- **Non-interactive help-model access**: `--help-model <N>` now accepts an
  optional topic number (1-15) or section name to print content directly without
  paging or interactive prompts, enabling automated testing of help content
- **Removed redundant paging prompt**: The interactive help viewer no longer
  shows "Press Enter to continue..." after the last page — it goes straight
  to the main menu prompt
- **System mode progress indicator**: Timeline models now show progress dots
  during processing in system mode, matching bundle mode behavior
- **Loops validation**: `--loops` now rejects values less than 1 with a clear
  error message
- **Bundle path validation**: Early validation of `--bundle` path before host
  detection, with clear error for non-existent or invalid paths
- **MemoryMonitor bug fix**: Fixed `AttributeError` when `print_stats()` called
  without psutil installed — `stats_printed` flag now initialized before early
  return
- **Test runner improvements**: Progress dots during test execution, `--bundle`
  option for regression tests with real collect bundles, `--model` option for
  model regression tests, post-run message about skipped bundle tests

### 2026-03-23 - Code Quality and Performance Improvements
- **Enhanced datetime parsing**: Improved ISO date handling in `lpmp_utils.py` for better performance
- **Documentation updates**: Minor corrections to ARCHITECTURE.md and README.md
- **Output module refinements**: Code cleanup and optimization in `lpmp_output.py`
- **Main tool enhancements**: Improved functionality and error handling in `lpmptool`

### 2026-03-22 - Test Suite Enhancement and Code Coverage Improvement
- **Comprehensive Test Coverage Expansion**: Improved overall coverage from 53% to 64% with 345 tests (was 265)
- **Output Generation Testing**: Added complete test coverage for `lpmp_output.py` (39% → 82% coverage, 44 tests)
  - All 15 output functions now tested with helper functions, pattern/pair/timeline writers, and system/bundle writers
  - Comprehensive edge case handling, error conditions, and integration testing
- **Graph Generation Testing**: Implemented full test suite for `lpmp_graph.py` (0% → 62% coverage, 17 tests)
  - Data extraction for all 4 usage formats, CSV creation, graph generation with mocked matplotlib
  - End-to-end workflow testing and file operation error handling
- **File I/O Testing**: Added comprehensive `test_get_file_date_range.py` (19 tests)
  - File type handling (regular, gzipped, empty), timestamp extraction, caching mechanism
  - Performance testing and error condition coverage
- **Dead Code Removal**: Cleaned up `lpmp_output.py` by removing unused/obsolete functions and code paths
  - Improved code maintainability and reduced technical debt
  - Streamlined output generation pipeline for better performance
- **Console Capture Module Consolidation**: Moved `console_capture.py` content to `lpmp_utils.py` and updated imports
- **Interactive Mode Test Resolution**: Fixed test execution blocking by avoiding interactive functions in test suite
- **Test Infrastructure Enhancement**: Enhanced `test_base.py` for both mocked unit tests and real subprocess execution
- **PEP8 Compliance**: Fixed module-level import ordering issues in test files

### 2026-03-17 - Dedicated Output Writers Refactor (Phases 0-11)
- **Added ModelType enum** (`PATTERN`, `PAIR`, `TIMELINE`) and `detect_model_type()` to `lpmp_utils.py`
- **Added structured result types**: `PatternResult`, `PairResult`, `TimelineResult` for type safety
- **Created lpmp_output.py** with dedicated writers per model type (15 functions)
- **Restricted mixed models**: Only trigger pattern + pair blocks allowed for better validation
- **Wired model_type through processing pipeline** with explicit enum usage, no string detection
- **Replaced generic output functions** with model-type-specific writers for better maintainability
- **Separated console output from file output** in `lpmp_engine.py` for cleaner architecture
- **Removed 8 dead functions** from `lpmp_utils.py` (738 lines removed) for code cleanup
- **Fixed pair block delta bug**: Delta now calculated from stop time, not start time

### 2026-02-13 - Documentation Suite Completion
- **Created comprehensive README.md** with user guide, examples, and quick start instructions
- **Added detailed ARCHITECTURE.md** with technical design and processing pipeline documentation
- **Completed DEVELOPERS_GUIDE.md** with all block types, examples, and advanced features
- **Updated CONTEXT.md** with current documentation status and development guidelines
- **Documented complete test suite** with coverage information
- **Added model search path documentation** for better user understanding
- **Included bundle mode and multi-host analysis coverage** in documentation
- **Documented interactive help system** with 19 topics for comprehensive user support
- **Added text-based visual architecture diagrams** for better technical understanding

### 2026-02-01 - Initial Submission
- **Basic design** - 3 model types
- **Command Line Interface** - First option, --help --help-model, max-time-delta, etc
- **Model Loading and Running** - Basic ability to load and run any of the 3 models