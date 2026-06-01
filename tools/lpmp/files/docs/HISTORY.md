# LPMP Change History

## Introduction

This document tracks the evolution of the Log Pattern Matching Profiler (LPMP) tool, capturing significant changes, bug fixes, architectural improvements, and feature additions. Each entry represents a meaningful change to the codebase, documentation, or functionality.

The history is organized chronologically with the most recent changes at the top, following industry standard practices for change documentation.

---

## Current Code Coverage Summary (2026-04-08):
  ```
  Current Automated Test Code Coverage:
  ============================================================
  lpmp_engine.py : 85% coverage
  lpmp_output.py : 82% coverage
  lpmp_graph.py  : 62% coverage
  lpmp_utils.py  : 81% coverage
  lpmptool.py    : 68% coverage
  Overall        : 77% coverage with 520 of 520 tests passing
  ============================================================
  ```

## Change History

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