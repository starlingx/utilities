# LPMP Test Coverage Catalog

**Last full review: 2026-04-08**

## Summary

**Current State:**
- **520 tests across 19 files**
- **77% overall coverage**
- **Solid coverage:** lpmp_engine.py (85%), lpmp_output.py (82%), lpmp_utils.py (81%)
- **Remaining gap:** lpmptool.py (68%), lpmp_graph.py (62%)

**Next Priorities:**
1. **lpmptool coverage** (68% - bundle merge, window auto-detect, help menu)
2. **Bundle mode merge paths** (system summary dispatch, timeline merge)
3. **Graph coverage** (lpmp_graph.py at 62%)

**Current Coverage:**
```
  lpmp_engine.py : 85% coverage
  lpmp_output.py : 82% coverage
  lpmp_graph.py  : 62% coverage
  lpmp_utils.py  : 81% coverage
  lpmptool.py    : 68% coverage
  Overall        : 77% coverage with 520 of 520 tests passing
```

Run: `cd test && python3 run_tests.py`
Run with bundle: `cd test && python3 run_tests.py -b default`

---

## Command Line Arguments

### test_cli_arguments.py — TestCommandLineArguments (53 tests)

- `test_help_flag` — --help exits cleanly
- `test_version_flag_exit_code` — --version exits with code 0
- `test_short_argument_forms` — Short flags (-l, -m, -o, etc.) parsed correctly
- `test_long_argument_forms` — Long flags (--logs-dir, --model-file, etc.) parsed correctly
- `test_logs_dir_default` — Default logs directory is /var/log
- `test_nonexistent_logs_dir` — Error when logs directory does not exist
- `test_logs_dir_not_directory` — Error when logs-dir is a file (exit code 1)
- `test_logs_dir_not_directory_stderr` — Logs-dir-is-a-file error shows "is not a directory" in stderr
- `test_nonexistent_model_file` — Error when model file does not exist (exit code 1)
- `test_nonexistent_model_file_stderr_shows_search_paths` — Model not found error shows search path hints
- `test_output_dir_argument` — --output sets output directory
- `test_output_dir_structure_with_explicit_output` — -o creates lpmp_<lab>/<timestamp>_<model> structure
- `test_output_dir_default_uses_cwd` — Default output directory created under cwd
- `test_default_output_dir_profile` — Default output dir for profile models
- `test_default_output_dir_timeline` — Default output dir for timeline models
- `test_loops_argument` — --loops sets loop count
- `test_max_log_length_argument` — --max-log-length sets max log line length
- `test_verbose_levels` — -v through -vvvvv set verbose levels 1-5
- `test_hostname_argument` — --hostname sets hostname
- `test_valid_start_date_simple` — Simple date format YYYY-MM-DD accepted
- `test_valid_start_date_iso` — ISO date format YYYY-MM-DDTHH:MM:SS accepted
- `test_invalid_start_date_format` — Invalid date format rejected with error
- `test_start_date_partial_formats` — All partial ISO formats accepted (date, hour, hour:min, full, msec, space)
- `test_invalid_stop_date_format` — Invalid --stop-date format exits with error
- `test_stop_date_before_start_date` — Stop date before start date exits with error
- `test_stop_date_equals_start_date` — Stop date equals start date exits with error
- `test_stop_date_date_only_parses_to_end_of_day` — Date-only --stop-date parses to 23:59:59
- `test_stop_date_iso_preserved` — Full ISO --stop-date preserved exactly
- `test_stop_date_partial_formats` — All partial ISO stop-date formats with correct defaults
- `test_invalid_dates_rejected` — Invalid dates rejected (out-of-range, bad format, garbage)
- `test_invalid_date_error_lists_accepted_formats` — Error message lists all accepted formats
- `test_var_argument_single` — --var key=value sets single variable
- `test_var_argument_multiple` — Multiple --var flags set multiple variables
- `test_var_argument_invalid_format` — --var without = rejected with error (exit code 1)
- `test_var_argument_invalid_format_stderr` — --var invalid format shows "Invalid --var format" in stderr
- `test_include_and_exclude_mutually_exclusive` — --include + --exclude exits with error
- `test_include_without_bundle` — --include without --bundle exits with error
- `test_exclude_without_bundle` — --exclude without --bundle exits with error
- `test_bundle_nonexistent_path` — --bundle with non-existent path exits with error
- `test_bundle_no_host_directories` — --bundle with empty directory exits with error
- `test_max_time_delta_cli_overrides_model` — CLI --max-time-delta overrides model setting
- `test_max_time_delta_model_overrides_default` — Model max_time_delta overrides default (45)
- `test_max_time_delta_default_when_not_specified` — Default max_time_delta is 45
- `test_loops_cli_overrides_model` — CLI -n overrides model loops setting
- `test_loops_model_overrides_default` — Model loops setting overrides default (1)
- `test_start_date_from_model_settings` — Model start_date used when CLI not provided
- `test_start_date_cli_overrides_model` — CLI --start-date overrides model start_date
- `test_help_model_all_topics_produce_output` — --help-model <N> for topics 1-16 all produce non-empty output
- `test_help_model_invalid_topic_rejected` — --help-model with invalid topic exits with error
- `test_help_model_named_topic_accepted` — --help-model ARCHITECTURE works by section name
- `test_help_model_output_matches_get_help_section` — CLI output matches get_help_section for topics 1-5
- `test_example_model_blocked_with_message` — Running example model prints reference-only note and exits
- `test_functional_model_not_blocked` — Running functional model is not blocked by example guard

---

## Model Loading and Validation

### test_model.py — Model file loading (39 tests)

**TestModelLoading** — load_model YAML parsing
- `test_load_pattern_model` — Pattern model loads with correct block structure
- `test_load_pair_model` — Pair model loads with start/stop fields
- `test_load_model_with_settings` — Global settings section parsed
- `test_load_model_with_block_level_max_time_delta` — Block-level max_time_delta preserved
- `test_load_model_mixed_max_time_delta_settings` — Mixed block-level and missing max_time_delta handled
- `test_load_empty_model_file` — Empty file exits with error
- `test_load_invalid_yaml` — Invalid YAML syntax exits with error
- `test_load_missing_model` — Missing file exits with error
- `test_load_model_missing_blocks` — Missing blocks section exits with error
- `test_load_model_invalid_pattern_block` — Pattern block missing required fields exits with error
- `test_load_model_invalid_pair_block` — Pair block missing required fields exits with error

**TestYAMLValidation** — Structural validation in load_model
- `test_missing_blocks_section` — Missing blocks: section detected
- `test_blocks_not_list` — blocks as non-list detected
- `test_empty_blocks_list` — Empty blocks list detected
- `test_block_not_dict` — Block that is not a dict detected
- `test_missing_label_field` — Missing label field detected
- `test_missing_file_field` — Missing file field detected
- `test_missing_patterns_and_start_stop` — Block with no patterns/start/stop/timeline detected
- `test_start_without_stop` — Pair block with start but no stop detected
- `test_stop_without_start` — Pair block with stop but no start detected

**TestModelFileSearch** — find_model_file search path precedence
- `test_find_model_absolute_path` — Absolute path found directly
- `test_find_model_absolute_not_found` — Non-existent absolute path returns None
- `test_find_model_in_models_dir` — Model found in ./models/ directory
- `test_find_model_in_current_dir` — Model found in current directory
- `test_find_model_precedence_models_over_current` — ./models/ takes precedence over ./
- `test_find_model_relative_path` — Relative path with separator found directly
- `test_find_model_not_found` — Missing model returns None
- `test_find_model_without_extension` — Model found without .yaml extension
- `test_find_model_without_extension_matches_with_extension` — Extensionless and with-extension resolve to same file
- `test_find_model_without_extension_not_found` — Extensionless search returns None when no match

**TestModelIncludes** — Include file merging
- `test_include_settings_merge` — Included settings merged, local overrides win

### test_model.py — Host filtering (8 tests in TestModelFileSearch)

- `test_filter_hosts_include_valid` — Include mode keeps only listed hosts
- `test_filter_hosts_include_single` — Include with single host
- `test_filter_hosts_exclude_valid` — Exclude mode removes listed hosts
- `test_filter_hosts_exclude_single` — Exclude with single host
- `test_filter_hosts_invalid_hostname` — Invalid hostname exits with error
- `test_filter_hosts_include_all_excluded` — Include resulting in no hosts exits with error
- `test_filter_hosts_exclude_all` — Exclude resulting in no hosts exits with error
- `test_filter_hosts_verbose_output` — Verbose output shows filtered hosts

### test_validate_model.py — validate_model_file and validate_model_structure (40 tests)

**TestValidateModelFile** — File-level validation for --list-models
- `test_valid_pattern_model` — Valid pattern model returns type 'pattern'
- `test_valid_pair_model` — Valid pair model returns type 'pair'
- `test_valid_timeline_model` — Valid timeline model returns type 'timeline'
- `test_valid_model_with_settings` — Model with settings section accepted
- `test_valid_model_with_include` — Model with include key accepted
- `test_valid_empty_blocks_list` — Empty blocks list defaults to type 'pattern'
- `test_empty_file` — Empty file excluded from listing
- `test_nonexistent_file` — Non-existent file excluded
- `test_unreadable_file` — Unreadable file excluded
- `test_plain_yaml_no_blocks` — Plain YAML dict without blocks excluded
- `test_settings_only_no_blocks` — YAML with settings but no blocks excluded
- `test_no_blocks_yaml_excluded_from_listing` — YAML files without blocks not listed
- `test_yaml_error_tab_indentation` — Tab indentation error returns error with line number
- `test_yaml_error_with_blocks_keyword` — YAML parse error with blocks: returns error detail
- `test_yaml_error_without_blocks_keyword` — YAML parse error without blocks: excluded
- `test_yaml_list_not_dict` — YAML that parses as list excluded
- `test_yaml_scalar_not_dict` — YAML that parses as scalar excluded
- `test_format_error_reported_in_status` — Structure error returns format error in status

**TestValidateModelStructure** — Structural validation rules
- `test_valid_pattern_model` — Valid pattern model has no errors
- `test_valid_pair_model` — Valid pair model has no errors
- `test_valid_timeline_model` — Valid timeline model has no errors
- `test_valid_model_with_include` — Model with include key has no errors
- `test_valid_window_model` — Valid window model has no errors
- `test_valid_model_with_all_optional_block_keys` — Block with all valid optional keys has no errors (incl. window, context)
- `test_valid_model_with_all_settings_keys` — Model with all valid settings keys has no errors (incl. stop_date)
- `test_not_a_dict` — Non-dict data detected
- `test_blocks_not_list` — blocks as non-list detected
- `test_empty_blocks` — Empty blocks list detected
- `test_block_not_dict` — Block that is not a dict detected
- `test_missing_label` — Missing label detected
- `test_missing_file` — Missing file detected
- `test_missing_block_type` — Block with no patterns/start/stop/timeline/window detected
- `test_start_without_stop` — Pair block with start but no stop detected
- `test_stop_without_start` — Pair block with stop but no start detected
- `test_duplicate_labels` — Duplicate block labels detected
- `test_unknown_top_level_key` — Unknown top-level key detected
- `test_unknown_block_key` — Unknown block-level key detected
- `test_unknown_settings_key` — Unknown settings key detected (e.g. typo max_delta_time)
- `test_settings_at_block_level_detected` — settings key inside a block flagged as unknown
- `test_settings_not_dict` — settings as non-dict detected
- `test_multiple_errors` — Multiple errors reported in single validation

### test_timeline_models.py — Timeline model processing (31 tests)

**TestTimelineModelDetection** — detect_model_type for timeline blocks
- `test_detect_pure_timeline_model` — All-timeline blocks detected as TIMELINE
- `test_detect_non_timeline_model` — Non-timeline blocks detected as PATTERN
- `test_detect_mixed_model_error` — Mixed timeline/non-timeline blocks rejected

**TestTimelineModelLoading** — load_model for timeline YAML
- `test_load_direct_timeline_model` — Direct pattern list loaded
- `test_load_named_reference_timeline_model` — Named reference {name} resolved from settings
- `test_load_timeline_model_with_includes` — Included pattern definitions merged
- `test_timeline_model_validation_all_timeline_blocks` — All blocks must be timeline
- `test_timeline_model_validation_missing_timeline_field` — Missing timeline field rejected
- `test_timeline_model_with_controller_flag` — Controller-only flag preserved
- `test_timeline_model_with_optional_blocks` — Optional flag preserved

**TestTimelinePatternResolution** — resolve_timeline_patterns
- `test_resolve_direct_pattern_list` — Direct list returned as-is
- `test_resolve_named_pattern_reference` — Named reference resolved from settings
- `test_resolve_single_string_pattern` — Single string wrapped in list
- `test_resolve_empty_settings` — Missing named reference exits with error
- `test_resolve_missing_named_reference` — Non-existent reference exits with error

**TestTimelineVariableSubstitution** — apply_timeline_variable_substitution
- `test_substitute_variables_in_string` — {hostname} replaced in string
- `test_substitute_variables_in_list` — {hostname} replaced in list elements
- `test_substitute_missing_variable` — Missing variable left as-is with warning

**TestTimelineBlockProcessing** — process_timeline_block
- `test_process_timeline_block_direct_patterns` — Direct patterns collected from log
- `test_process_timeline_block_named_reference` — Named reference patterns collected
- `test_process_timeline_block_chronological_ordering` — Results sorted by timestamp
- `test_process_timeline_block_no_matches` — No matches returns empty list
- `test_process_timeline_block_with_variable_substitution` — Variables substituted before search

**TestTimelineModelEdgeCases** — Edge cases
- `test_empty_timeline_patterns` — Empty pattern list returns no matches
- `test_timeline_patterns_with_regex` — Regex patterns matched correctly
- `test_timeline_patterns_with_special_characters` — Special characters in patterns handled
- `test_malformed_named_reference` — Malformed {ref} handled gracefully
- `test_nested_variable_substitution` — Nested variable references substituted

**TestTimelineModelIntegration** — End-to-end
- `test_full_timeline_model_processing` — Complete timeline workflow succeeds
- `test_timeline_model_error_handling` — Error conditions handled gracefully
- `test_timeline_model_with_controller_filtering` — Controller-only blocks skipped for non-controllers

---

## Parameter Precedence

### test_precedence_gaps.py (11 tests)

**TestMaxTimeDeltaPrecedence** — block > command line > model > default
- `test_default_fallback` — Default max_time_delta used when no other setting exists
- `test_model_overrides_default_positive` — Model setting overrides default
- `test_model_overrides_default_negative` — Model setting causes timeout when exceeded
- `test_command_line_overrides_model_positive` — Command line overrides model setting
- `test_command_line_overrides_model_negative` — Command line causes timeout when exceeded
- `test_block_level_overrides_command_line_positive` — Block-level overrides command line
- `test_block_level_overrides_command_line_negative` — Block-level causes timeout when exceeded

**TestCommandLineParameterOverrides** — CLI overrides model settings
- `test_model_settings_override_defaults` — Model settings override default values
- `test_command_line_max_time_delta_override` — CLI max_time_delta overrides model
- `test_command_line_verbose_override` — CLI verbose overrides model
- `test_max_time_delta_ignored_for_first_match_applied_to_subsequent` — First match ignores max_time_delta, subsequent matches enforce it

---

## File Handling and I/O

### test_get_file_date_range.py — get_file_date_range function (19 tests)

**TestGetFileDateRange** — File date range extraction and caching
- `test_regular_file_with_timestamps` — Regular file timestamp extraction
- `test_gzipped_file_with_timestamps` — Gzipped file timestamp extraction
- `test_empty_file` — Empty file handling
- `test_file_with_no_timestamps` — File without valid timestamps
- `test_nonexistent_file` — Non-existent file handling
- `test_permission_denied_file` — Permission denied file handling
- `test_single_line_file` — Single line file handling
- `test_timestamps_only_at_beginning` — Timestamps only at file beginning
- `test_timestamps_only_at_end` — Timestamps only at file end
- `test_mixed_timestamp_formats` — Mixed timestamp format handling
- `test_malformed_timestamps` — Malformed timestamp handling
- `test_sysinv_format_timestamps` — sysinv format timestamp parsing
- `test_unicode_content` — Unicode content handling
- `test_large_file_efficiency` — Large file efficiency testing
- `test_regular_file_seek_behavior` — Regular file seek behavior
- `test_gzipped_file_seek_behavior` — Gzipped file seek behavior
- `test_gzipped_file_error_handling` — Gzipped file error handling
- `test_caching_behavior` — Caching mechanism testing
- `test_cache_hit_path` — Cache hit path verification

### test_lpmp.py — TestFileHandling (7 tests)

- `test_find_pattern_in_regular_file` — Pattern found in regular log file
- `test_find_pattern_in_gzipped_file` — Pattern found in .gz log file
- `test_empty_file` — Empty log file returns None
- `test_file_not_found` — Missing file returns None
- `test_file_without_timestamps` — File with no valid timestamps returns None
- `test_pattern_not_found` — Non-matching pattern returns None
- `test_corrupted_gzip_file` — Corrupted .gz file handled gracefully

### test_edge_cases.py — TestFileProcessingFunctions (3 tests)

- `test_expand_wildcards_single_block` — Wildcard expanded to matching files in single block
- `test_expand_wildcards_multiple_blocks` — Wildcards expanded in multiple blocks
- `test_expand_wildcards_no_wildcards` — Non-wildcard file spec left unchanged

### test_edge_cases.py — TestUtilityFunctions (10 tests)

- `test_get_models_search_paths_basic` — Search paths include ./models/ and ./
- `test_detect_model_type_window` — Window block detected as TIMELINE model type
- `test_detect_model_type_window_raw` — Raw window dict (without load_model) detected as TIMELINE
- `test_sanitize_label_remove_invalid_chars` — Path separators replaced with underscores
- `test_sanitize_label_replace_spaces` — Spaces replaced with underscores
- `test_sanitize_label_special_characters` — Non-path special characters preserved
- `test_ensure_output_dir_create` — Directory created if not exists
- `test_parse_duration_to_seconds_hms` — HH:MM:SS.xxx parsed to seconds
- `test_parse_duration_to_seconds_invalid` — Invalid format returns None
- `test_format_result_line_basic` — Tab-separated timing line formatted correctly

### test_lpmp.py — TestWildcardExpansion (4 tests)

- `test_expand_wildcard_pattern` — Wildcard pattern expanded to matching files
- `test_no_wildcard_pattern` — Non-wildcard pattern returned as-is
- `test_wildcard_no_matches` — Wildcard matching no files returns original pattern
- `test_wildcard_nonexistent_directory` — Wildcard in non-existent directory handled

---

## Time Tolerance

One tolerance parameter controls how far backwards (in time) the engine
will look when searching for the next pattern.

| Parameter | Default | Used by | Scope |
|---|---|---|---|
| `block_time_tolerance` | 5.0 s | All model types | How far before `after_timestamp` a pattern may appear |

Both the file-level smart filter and the line-level filter use
`block_time_tolerance` consistently.

### test_block_time_tolerance.py — block_time_tolerance (27 tests)

**TestBlockTimeToleranceBasic** — Core value-range tests against find_pattern_in_files
- `test_zero_tolerance_strict_ordering` — block_time_tolerance=0 rejects out-of-order patterns
- `test_small_tolerance_allows_minor_reordering` — 500 ms tolerance accepts 200 ms backwards
- `test_large_tolerance_allows_significant_reordering` — 10 s tolerance accepts 5 s backwards
- `test_negative_tolerance_rejects_all_patterns` — Negative tolerance rejects backwards but not forwards
- `test_tolerance_boundary_conditions` — Pattern exactly at boundary (time_diff == tolerance) is accepted

**TestBlockTimeToleranceReordering** — reorder_and_output_results sorting
- `test_reorder_and_output_results_chronological_sorting` — Out-of-order temp_results sorted by timestamp
- `test_reorder_preserves_sequence_for_equal_timestamps` — Equal timestamps preserve sequence number order
- `test_empty_results_handled_gracefully` — Empty temp_results does not raise

**TestBlockTimeToleranceIntegration** — End-to-end through process_pattern_block
- `test_pattern_block_with_tolerance` — Out-of-order pattern found within tolerance
- `test_auto_detect_with_tolerance_reordering` — Three blocks with out-of-order timestamps all found
- `test_tolerance_with_multiple_files` — Tolerance works across multiple log files

**TestBlockTimeToleranceErrorHandling** — Defaults and edge values
- `test_missing_block_time_tolerance_uses_default` — Missing attribute defaults to 5.0 (accept backwards)
- `test_none_args_uses_default_tolerance` — args=None defaults to 5.0
- `test_very_large_tolerance_value` — 1-hour tolerance accepts 1-minute-old pattern
- `test_fractional_tolerance_values` — 300 ms tolerance accepts 250 ms backwards
- `test_tolerance_with_verbose_logging` — High verbosity does not change filtering behavior

**TestBlockTimeTolerancePerformance** — Large-file behavior
- `test_tolerance_with_large_log_file` — 1000-line file searched efficiently
- `test_tolerance_with_many_out_of_order_entries` — Many out-of-order entries handled

**TestBlockToleranceWithPairBlocks** — process_pair_block with varying tolerances
- `test_stop_after_start` — Basic start/stop found, duration calculated
- `test_stop_slightly_before_start_accepted` — Stop 0.5 s before start accepted with tolerance=2
- `test_stop_too_far_before_start_rejected` — Stop 10 s before start rejected with tolerance=1
- `test_sequential_with_tolerance` — Second pair block's start overlaps first pair's range
- `test_zero_tolerance_finds_forward_stop` — Zero tolerance still finds forward stop

**TestBlockTolerancePairIntegration** — End-to-end through process_blocks_auto_detect for pair models
- `test_basic_pair_block` — Single pair block found, success=True
- `test_tolerance_accepts_overlapping_blocks` — Two overlapping pairs both found
- `test_tight_tolerance_rejects_backwards_stop` — Tight tolerance causes pair failure
- `test_optional_block_not_found` — Optional pair block missing does not fail model

### test_edge_cases.py — TestTimeToleranceEdgeCases (5 tests)

General max_time_delta tests via find_pattern_in_files (not model-type-specific).

- `test_timestamp_exactly_at_tolerance_boundary` — Pattern at 1 s found with max_time_delta=1
- `test_multiple_blocks_within_tolerance_window` — Three patterns within 1 s window all found
- `test_tolerance_larger_than_time_range` — 10 s tolerance for 5 s gap finds pattern
- `test_zero_tolerance_value` — max_time_delta=0 rejects pattern 1 ms later
- `test_negative_tolerance_value` — Negative max_time_delta rejects all patterns

---

## Block Processing Engine

### test_process_blocks.py — TestProcessBlocks (14 tests)

**Pattern Block Processing (5 tests):**
- `test_process_pattern_block` — Single pattern block found in log file
- `test_process_pattern_block_missing_pattern` — Missing pattern returns None
- `test_process_pattern_block_multiple_files` — Pattern found across multiple log files
- `test_process_pattern_block_out_of_order_timestamps` — Out-of-order timestamps handled with tolerance
- `test_required_block_error_message_includes_patterns` — Error message includes block label and pattern details

**Pair Block Processing (5 tests):**
- `test_process_pair_block` — Start/stop pair found, duration calculated
- `test_process_pair_block_missing_start` — Missing start pattern returns None
- `test_process_pair_block_missing_stop` — Missing stop pattern returns None
- `test_process_pair_block_optional` — Optional pair block missing does not fail
- `test_process_pair_block_timeout` — max_time_delta exceeded returns None

**Max Time Delta Processing (4 tests):**
- `test_block_level_max_time_delta` — Block-level max_time_delta overrides global
- `test_block_level_max_time_delta_timeout` — Block-level max_time_delta causes timeout
- `test_no_block_level_max_time_delta_uses_global` — Missing block-level falls back to global
- `test_pattern_block_max_time_delta_enforced` — Pattern block max_time_delta filters late matches

### test_edge_cases.py — TestPatternMatchingEdgeCases (4 tests)

- `test_pattern_at_start_of_file` — Pattern on first line found with correct timestamp
- `test_pattern_at_end_of_file` — Pattern on last line found with correct timestamp
- `test_pattern_spanning_multiple_lines` — Multiline content: first-line pattern found
- `test_overlapping_patterns` — Second occurrence found after first via position advancement

---

## Variable Substitution and Utilities

### test_lpmp.py — TestVariableSubstitution (4 tests)

- `test_substitute_hostname` — {hostname} replaced in pattern text
- `test_substitute_multiple_variables` — Multiple {var} placeholders replaced
- `test_substitute_missing_variable` — Missing variable left as-is with warning
- `test_bundle_mode_hostname_substitution` — Hostname variable substituted in bundle mode

### test_lpmp.py — TestTimestampParsing (4 tests)

- `test_parse_iso_timestamp` — ISO format 2024-01-06T10:00:00.000 parsed
- `test_parse_sysinv_timestamp` — sysinv format parsed
- `test_parse_invalid_timestamp` — Invalid timestamp returns None
- `test_parse_malformed_sysinv` — Malformed sysinv timestamp returns None

### test_lpmp.py — TestLogLineFormatting (2 tests)

- `test_format_regular_log_line` — Regular log line passed through unchanged
- `test_format_sysinv_log_line` — sysinv prefix stripped from sysinv.log lines

### test_lpmp.py — TestFormatDuration (3 tests)

- `test_format_seconds` — Seconds formatted as 00:00:SS.sss
- `test_format_minutes` — Minutes formatted as 00:MM:SS.sss
- `test_format_hours` — Hours formatted as HH:MM:SS.sss

- `test_get_models_search_paths_basic` — Search paths include ./models/ and ./
- `test_detect_model_type_window` — Window block detected as TIMELINE model type
- `test_detect_model_type_window_raw` — Raw window dict (without load_model) detected as TIMELINE
- `test_sanitize_label_remove_invalid_chars` — Path separators replaced with underscores
- `test_sanitize_label_replace_spaces` — Spaces replaced with underscores
- `test_sanitize_label_special_characters` — Non-path special characters preserved
- `test_ensure_output_dir_create` — Directory created if not exists
- `test_parse_duration_to_seconds_hms` — HH:MM:SS.xxx parsed to seconds
- `test_parse_duration_to_seconds_invalid` — Invalid format returns None
- `test_format_result_line_basic` — Tab-separated timing line formatted correctly

### test_edge_cases.py — TestOutputGenerationFunctions (7 tests)

- `test_create_output_directory_default_naming` — Default name includes lab name and timestamp
- `test_create_output_directory_custom_path` — Custom -o path used directly
- `test_create_output_directory_with_hostname` — Hostname subdirectory created in bundle mode
- `test_create_output_directory_permission_denied` — PermissionError raised for restricted path
- `test_create_output_directory_invalid_characters` — ValueError/OSError raised for null bytes in path
- `test_create_output_directory_disk_full` — OSError raised when disk is full
- `test_create_output_directory_readonly_filesystem` — PermissionError raised for read-only filesystem

---

## Bundle Host Detection

### test_lpmp.py — TestBundleHostDetection (6 tests)

- `test_detect_valid_bundle_hosts` — Valid hostname_YYYYMMDD.HHMMSS directories detected
- `test_detect_multiple_hosts_same_date` — Multiple hosts with same date detected
- `test_detect_no_bundle_hosts_error` — No bundle hosts exits with error
- `test_detect_mixed_date_parts_error` — Different date parts across hosts exits with error
- `test_detect_system_root_returns_empty` — System root (/) returns empty lists
- `test_detect_bundle_hosts_verbose` — Verbose output shows detected hosts

---

## Output Generation Functions

### test_lpmp_output.py — lpmp_output.py functions (46 tests)

**TestLpmpOutputFunctions** — Comprehensive output file generation

**Helper Functions (11 tests):**
- `test_parse_ts_string_timestamp` — ISO format string parsing to datetime
- `test_parse_ts_datetime_passthrough` — Datetime objects returned unchanged
- `test_parse_ts_invalid_string` — Invalid string format raises ValueError
- `test_parse_ts_none_input` — None input returns None
- `test_parse_ts_empty_string` — Empty string raises ValueError
- `test_parse_ts_integration_with_patterns` — Integration with existing timestamp patterns
- `test_write_summary_stats_standard_output` — Standard summary with samples/average/min/max
- `test_write_summary_stats_custom_title` — Custom title formatting
- `test_write_summary_stats_zero_samples` — Zero samples handling
- `test_write_summary_stats_file_error` — File write error handling
- `test_write_summary_stats_integration` — Integration with existing format expectations

**Pattern Model Writers (19 tests):**
- `test_write_pattern_csv_valid_results` — Valid PatternResult objects to CSV
- `test_write_pattern_csv_empty_results` — Empty results handling
- `test_write_pattern_csv_warning_results` — Warning results processing
- `test_write_pattern_csv_pass_summaries` — Pass summaries inclusion
- `test_write_pattern_csv_file_error` — File I/O error handling
- `test_write_pattern_csv_format_validation` — CSV format validation
- `test_write_pattern_csv_integration` — Integration with existing pattern model tests
- `test_write_pattern_csv_large_dataset` — Large dataset handling (1000 results)
- `test_write_pattern_summary_extend_existing` — Extending existing test coverage
- `test_write_pattern_summary_missing_edge_cases` — Edge cases not covered by existing tests
- `test_write_pattern_summary_error_conditions` — Error condition handling
- `test_write_pattern_summary_integration_validation` — Integration with existing warning format tests
- `test_write_pattern_block_profile_enabled_blocks` — Profile-enabled blocks only
- `test_write_pattern_block_profile_result_filtering` — Block result filtering
- `test_write_pattern_block_profile_filename_sanitization` — Filename sanitization
- `test_write_pattern_block_profile_directory_creation` — Directory creation handling
- `test_write_pattern_block_profile_empty_results` — Empty results handling
- `test_write_pattern_block_profile_statistics_accuracy` — Statistics accuracy validation
- `test_write_pattern_block_profile_integration` — Integration with existing profile expectations

**Pair Model Writers (4 tests):**
- `test_write_pair_csv_pair_results` — PairResult objects to CSV
- `test_write_pair_csv_mixed_results` — Mixed PairResult and PatternResult handling
- `test_write_pair_summary_overall_summary` — Overall summary generation
- `test_write_pair_block_profile_duration_stats` — Duration statistics calculation

**Timeline Model Writers (2 tests):**
- `test_write_timeline_csv_timeline_results` — TimelineResult objects to CSV
- `test_write_timeline_block_profile_delta_calculations` — Delta calculations

**System/Bundle Writers (8 tests):**
- `test_create_pattern_system_summary_multi_host` — Multi-host summary aggregation
- `test_create_pattern_system_summary_missing_files` — Missing files handling
- `test_write_system_summary_file_host_statistics` — Host statistics display
- `test_merge_timeline_profiles_chronological_sorting` — Chronological sorting
- `test_extract_timestamp_from_data_iso_format` — ISO timestamp extraction
- `test_extract_timestamp_from_data_space_separated` — Space-separated timestamp extraction
- `test_extract_timestamp_from_data_invalid_data` — Invalid data handling
- `test_extract_timestamp_from_data_edge_cases` — Edge case data handling
- `test_print_output_files_lists_all_files` — print_output_files lists individual file paths
- `test_print_output_files_nonexistent_dir` — print_output_files handles non-existent directory gracefully

### test_summary_timing_format.py (2 tests)

- `test_summary_timing_two_runs_format` — summary.timing format correct with 2 runs of pair model
- `test_summary_timing_with_warnings` — Warning lines truncated after 'not found' in summary

### test_optional_warnings.py (1 test)

- `test_optional_warnings_in_summary` — Optional block warnings written to summary.timing

### test_warning_format.py (1 test)

- `test_warning_format` — Warning format in summary.timing matches expected layout

---

## Graph Generation Functions

### test_lpmp_graph.py — lpmp_graph.py functions (17 tests)

**TestLpmpGraphFunctions** — Graph generation functionality

**Data Extraction (8 tests):**
- `test_extract_usage_data_platform_cpu_debounce` — Platform CPU debounce format parsing
- `test_extract_usage_data_platform_cpu_reading` — Platform CPU reading format parsing
- `test_extract_usage_data_platform_memory` — Platform Memory usage format parsing
- `test_extract_usage_data_platform_cpu_plugin` — Platform CPU plugin format parsing
- `test_extract_usage_data_no_matches` — No matching usage type handling
- `test_extract_usage_data_malformed_lines` — Malformed lines graceful handling
- `test_extract_usage_data_verbose_mode` — Verbose mode functionality
- `test_extract_usage_data_mixed_formats` — Mixed data formats processing

**CSV Creation (4 tests):**
- `test_create_csv_basic_functionality` — Basic CSV file creation
- `test_create_csv_column_name_formatting` — Column name formatting (spaces → underscores)
- `test_create_csv_empty_data` — Empty data handling
- `test_create_csv_verbose_mode` — Verbose mode functionality

**Graph Generation (3 tests):**
- `test_create_graph_basic_functionality` — Basic graph creation (mocked matplotlib)
- `test_create_graph_verbose_mode` — Verbose mode functionality
- `test_create_graph_custom_y_range` — Custom Y-axis range handling

**Integration & Error Handling (2 tests):**
- `test_end_to_end_workflow` — Complete workflow (extract → CSV → graph)
- `test_file_error_handling` — File operation error handling

---

## Error Handling and Edge Cases

### test_lpmp.py — TestErrorHandling (4 tests)

- `test_invalid_regex_pattern` — Invalid regex handled gracefully
- `test_regex_fallback_to_literal` — Regex failure falls back to literal match
- `test_permission_denied_file` — Permission-denied file handled gracefully
- `test_very_long_log_lines` — Very long log lines do not crash

### test_edge_cases.py — TestNegativeTests (4 tests)

- `test_invalid_format_file` — File without timestamps returns None
- `test_permission_denied_file` — Unreadable file returns None
- `test_empty_label_sanitization` — Empty label sanitized to "block"
- `test_label_with_only_invalid_characters` — All-invalid-char label sanitized to underscores

### test_lpmp.py — TestEdgeCases (8 tests)

- `test_model_with_empty_string_pattern` — Empty string pattern handled
- `test_model_with_special_characters_in_patterns` — Regex special characters in patterns handled
- `test_model_with_unicode_characters` — Unicode characters in model handled
- `test_model_with_numeric_values` — Numeric values in unexpected places handled
- `test_model_with_very_long_label` — Very long label handled
- `test_load_model_with_block_level_max_time_delta` — Block-level max_time_delta loaded
- `test_load_model_mixed_max_time_delta_settings` — Mixed max_time_delta settings loaded
- `test_zero_loops` — loops=0 (until EOF) handled

---

## Force Option

### test_force_option.py — TestForceOption (11 tests)

- `test_force_flag_short` — -f flag sets force=True
- `test_force_flag_long` — --force flag sets force=True
- `test_force_default_false` — Default force is False
- `test_first_block_fails_even_with_force` — First block failure not bypassed by --force
- `test_second_block_forced` — Second block failure downgraded to warning with --force
- `test_middle_block_forced_rest_continues` — Middle block forced, subsequent blocks still processed
- `test_multiple_failures_forced` — Multiple block failures all downgraded with --force
- `test_second_block_fails_without_force` — Without --force, second block failure stops processing
- `test_optional_block_unaffected_by_force` — Optional blocks unaffected by --force
- `test_force_pair_block_after_first` — Pair block failure after first block forced
- `test_getattr_fallback` — getattr fallback for force attribute when not present

---

## Host Setting

### test_host_setting.py — TestHostSetting (13 tests)

- `test_host_sets_variable_on_system` — --host sets {host} variable in system mode
- `test_host_does_not_change_hostname` — --host does not alter --hostname value
- `test_host_in_bundle_mode` — --host works in bundle mode
- `test_var_host_overrides_cli_host` — --var host= overrides --host
- `test_host_usable_with_include` — --host works alongside --include
- `test_settings_host_is_valid_key` — host: in settings passes validation
- `test_settings_host_injects_variable` — settings host: injects {host} variable
- `test_cli_var_overrides_settings_host` — --var host= overrides settings host:
- `test_cli_host_overrides_settings_host` — --host overrides settings host:
- `test_examples_path_in_search_paths` — examples/ path included in model search paths
- `test_loops_zero_terminates` — loops=0 terminates cleanly at EOF
- `test_loops_fixed_count_with_sufficient_data` — Fixed loop count with sufficient data
- `test_loops_zero_eof_is_not_failure` — loops=0 EOF exit is not a failure

### test_lpmp.py — TestOptionalWarnings (1 test)

- `test_optional_block_warning_in_results` — Optional missing block emits warning line and continues

### test_lpmp.py — TestTimelineBlocks (1 test)

- `test_timeline_block_collects_matches` — Timeline block collects matches

---

## Integration Tests

### test_lpmp.py — TestIntegration (3 tests)

- `test_version_flag` — --version flag works end-to-end
- `test_mixed_model_processing` — Mixed pattern+pair model processed correctly
- `test_profile_block_file_output` — Per-block profile file created with summary header

### test_main_execution.py — TestMainExecution (17 tests)

**System Mode Processing:**
- `test_infrastructure_setup` — Test infrastructure (imports, paths) working
- `test_system_mode_pattern_model_creates_output_files` — Pattern model creates timing and CSV files
- `test_system_mode_pair_model_creates_output_files` — Pair model creates timing, CSV, and summary
- `test_system_mode_timeline_model_creates_output_files` — Timeline model creates timeline.log and CSV
- `test_system_mode_no_matches_reports_error` — No pattern matches reports failure
- `test_system_mode_csv_has_content` — CSV output has header and data rows
- `test_system_mode_loops_2_produces_two_passes` — loops=2 produces two pass summaries
- `test_system_mode_timeline_single_pass` — Timeline processes all data in one pass
- `test_system_mode_loops_zero_until_eof` — loops=0 runs until EOF (no longer rejected)
- `test_system_mode_loops_negative_rejected` — Negative loops rejected with error

**Settings Application:**
- `test_model_settings_block_time_tolerance_applied` — Model block_time_tolerance applied to args
- `test_model_settings_controller_applied` — Model controller setting applied to args
- `test_model_settings_optional_applied` — Model optional setting applied to args
- `test_model_settings_max_log_length_applied` — Model max_log_length overrides default

**List Models:**
- `test_list_models_displays_models` — --list-models finds and displays model files
- `test_list_models_empty_directory` — --list-models with no models found

**Bundle Mode (synthetic):**
- `test_bundle_mode_creates_per_host_output_dirs` — Per-host output directories created
- `test_bundle_mode_creates_per_host_output_files` — Per-host timing files created
- `test_bundle_mode_hostname_substitution_per_host` — Correct hostname substituted per host
- `test_bundle_mode_skips_host_with_missing_logs_dir` — Missing logs dir skipped gracefully

### test_main_execution.py — TestBundleRegression (4 tests, optional)

Requires `--bundle` flag. Skipped by default.

- `test_bundle_timeline_model_produces_output` — Timeline model against real bundle produces output
- `test_bundle_output_has_per_host_dirs` — Real bundle creates per-host output directories
- `test_bundle_merged_system_profile_created` — Real bundle creates profile files
- `test_bundle_output_files_listed` — Real bundle run lists output files

---

## Window Model and Context Label

### test_window_model.py — Window model and context feature (55 tests)

**TestWindowFileDiscovery** — File discovery and classification (6 tests)
- `test_discover_matches_log_files` — Log files with timestamps are matched
- `test_discover_skips_binary` — Binary files are skipped
- `test_discover_skips_known_non_log` — Known non-log files (wtmp, btmp) are skipped
- `test_discover_skips_no_timestamps` — Files without parseable timestamps are skipped
- `test_discover_skips_outside_window` — Files entirely outside time window are skipped
- `test_discover_file_list_pattern` — File list patterns are expanded correctly

**TestAutoDetectTimeRange** — Auto-detection of time range (5 tests)
- `test_auto_detect_returns_one_hour_window` — Defaults to 1 hour before latest timestamp
- `test_auto_detect_custom_hours` — Respects custom hours_back parameter
- `test_auto_detect_multiple_files` — Finds latest timestamp across multiple files
- `test_auto_detect_no_files` — Returns None when no log files found
- `test_auto_detect_skips_binary` — Skips binary files

**TestWindowModelValidation** — Window model structure validation (4 tests)
- `test_window_block_valid` — Window block passes validation
- `test_window_detected_as_timeline` — Window block detected as TIMELINE model type
- `test_multiple_window_blocks_valid` — Multiple window blocks pass validation
- `test_window_with_settings_valid` — Window model with start_date/stop_date settings is valid

**TestWindowModelLoading** — Window model loading via load_model (3 tests)
- `test_load_window_model` — Window model loads with timeline: '.*' injected
- `test_load_window_model_with_stop_date` — Window model with stop_date in settings loads correctly
- `test_load_window_model_file_list` — Window model with file list loads correctly

**TestContextLabel** — Context label parsing, extraction, and output (28 tests)

*Context parsing (9 tests):*
- `test_context_int_parsed_as_symmetric` — context: 5 parsed as [5, 5]
- `test_context_list_parsed_as_asymmetric` — context: [3, 10] parsed as before=3, after=10
- `test_context_not_set_by_default` — Blocks without context: have no context_before/after
- `test_context_skipped_for_pair_blocks` — context: on pair blocks is ignored with warning
- `test_context_invalid_string_exits` — context: 'string' triggers sys.exit(1)
- `test_context_single_element_list_exits` — context: [5] triggers sys.exit(1)
- `test_context_three_element_list_exits` — context: [1,2,3] triggers sys.exit(1)
- `test_context_zero_value_symmetric` — context: 0 is valid and sets both to 0
- `test_context_on_timeline_block` — context: on timeline block is accepted

*extract_context_lines (11 tests):*
- `test_extract_context_lines` — Returns correct before/after lines
- `test_extract_context_at_file_start` — Fewer before lines when match is at start
- `test_extract_context_at_file_end` — Fewer after lines when match is at end
- `test_extract_context_zero_before` — context_before=0 returns no before lines
- `test_extract_context_zero_after` — context_after=0 returns no after lines
- `test_extract_context_zero_both` — Both zero returns empty lists
- `test_extract_context_file_not_found` — Missing file returns ([], [])
- `test_extract_context_no_match` — No matching line returns ([], [])
- `test_extract_context_large_request_small_file` — Large context on small file returns available lines
- `test_extract_context_gzipped_file` — Context extraction works on .gz files
- `test_extract_context_matches_first_occurrence` — First occurrence matched when duplicates exist

*write_context_files (8 tests):*
- `test_write_context_files` — Creates .context file with correct format
- `test_write_context_files_multiple_matches` — Handles multiple matches in one block
- `test_write_context_files_multiple_blocks` — Creates separate files per block
- `test_write_context_files_no_matching_results` — No results produces no file
- `test_write_context_files_empty_context_tuples` — Empty context tuples still produce output
- `test_write_context_files_timeline_result` — Works with TimelineResult objects
- `test_write_context_files_skips_blocks_without_context` — Blocks without context_before produce no file
- `test_write_context_files_result_with_none_context_skipped` — Results with context=None filtered out

**TestWindowIntegration** — End-to-end integration (3 tests)
- `test_window_model_produces_timeline_output` — Window model produces .timeline.log with all log lines
- `test_context_produces_context_file` — Pattern model with context: produces .context output file
- `test_stop_date_from_model_settings` — stop_date in model settings used when -e not provided

**TestBisectSeek** — Binary search seek optimization (3 tests)
- `test_bisect_finds_lines_in_window` — Bisect correctly finds lines within the time window
- `test_bisect_skipped_for_small_files` — Small files (<32KB) scanned linearly without bisect
- `test_bisect_no_matches_outside_window` — Bisect returns nothing when window is past all data

**TestRotationPrune** — Rotation-aware .gz file pruning (4 tests)
- `test_higher_rotations_skipped` — Once rotation N is before window, N+1, N+2... are skipped
- `test_non_gz_files_pass_through` — Plain text files are never pruned by rotation logic
- `test_rotation_in_window_kept` — Rotation whose date range overlaps window is kept
- `test_mixed_bases_independent` — Different base names are pruned independently

**TestGzDateRange** — .gz file date range via zcat|tail (3 tests)
- `test_gz_first_and_last_timestamp` — Correct first/last timestamps from .gz file
- `test_gz_single_line` — Single-line .gz file returns same first and last timestamp
- `test_gz_cached_on_second_call` — Second call uses cache, not subprocess

**TestDiscoverWithRotation** — discover_window_files with rotation pruning (2 tests)
- `test_old_rotations_skipped_in_discover` — Old .gz rotations skipped in full discovery
- `test_rotation_2_not_read_when_1_before_window` — Higher rotations not in cache (proves skipped)

**TestFailureAndEdgeCases** — Failure handling for optimizations (9 tests)
- `test_bisect_file_with_no_timestamps` — Bisect handles file with no timestamps gracefully
- `test_bisect_file_with_sparse_timestamps` — Bisect handles file where most lines lack timestamps
- `test_gz_corrupt_file_returns_none` — Corrupt .gz file returns (None, None)
- `test_gz_empty_file_returns_none` — Empty .gz file returns (None, None)
- `test_gz_no_timestamps_returns_none` — .gz file with no timestamps returns (None, None)
- `test_rotation_prune_gz_without_rotation_number` — .gz without rotation number passes through
- `test_rotation_prune_empty_list` — Empty file list returns empty result
- `test_rotation_prune_gz_no_timestamps` — No-timestamp rotation skipped, doesn't block siblings
- `test_discover_no_start_date_skips_rotation_prune` — Without start_date, all files included

**TestWindowGzCoverage** — .gz window coverage verification (7 tests)
- `test_gz_overlapping_window_is_matched` — .gz file overlapping window is matched
- `test_gz_entirely_before_window_is_skipped` — .gz file before window is skipped
- `test_gz_entirely_after_window_is_skipped` — .gz file after window is skipped
- `test_gz_rotation_1_in_window_rotation_2_before` — Rotation 1 kept, rotation 2 skipped
- `test_gz_window_boundary_exact_match` — File with last_ts == start_date is included
- `test_gz_window_boundary_just_before` — File with last_ts 1ms before start_date is skipped
- `test_mixed_plain_and_gz_all_classified_correctly` — Mixed plain and .gz files classified correctly

**TestContextBundleIntegration** — Bundle integration (6 tests, optional)

Requires `--bundle` flag or `LPMP_TEST_BUNDLE` env var. Skipped by default.

- `test_context_from_gzipped_log` — extract_context_lines reads surrounding lines from a real .gz file
- `test_context_pattern_model_real_logs` — Pattern model with context: produces .context from real sm.log
- `test_context_timeline_model_real_logs` — Timeline model with context: produces .context from real mtcAgent.log
- `test_context_override_block_bundle` — Override block reads context from peer controller's logs
- `test_window_model_with_context_bundle` — Window model against real bundle with file filtering
- `test_present_block_no_context_file` — present: true unfound block produces no .context file

---

### test_main_execution.py — TestMemoryMonitorAndMisc (5 tests)

- `test_memory_monitor_disabled_without_psutil` — MemoryMonitor disabled gracefully without psutil
- `test_memory_monitor_print_stats_no_duplicate` — print_stats handles disabled monitor
- `test_stats_flag_runs_without_error` — --stats flag doesn't crash
- `test_console_capture_basic` — ConsoleCapture captures output
- `test_console_capture_silent_mode` — ConsoleCapture silent mode works

---
# Improvement Opportunities

---

## High Priority Gaps

### Main Tool (`lpmptool`) - 67% Coverage
- **Window model auto-detect path** — Time range auto-detection, pre-scan summary
- **stop_date from model settings** — Parsing and precedence in main()
- **--max-lines argument** — Console output limiting for timeline models
- **--no-ts-files option** — File listing with no parseable timestamps, bundle and system mode
- **Help menu renumbering** — Topics 15-18 (window blocks, existing models, example models)
- **Bundle mode window model** — Per-host window processing and merge
- **Bundle host sort order** — controller-0 first, controller-1, storage, others

### Engine Pipeline (`lpmp_engine.py`) - 80%/85% Coverage
- **`process_blocks_auto_detect` structured_results** — Verify PatternResult/PairResult/TimelineResult construction
- **`find_pattern_in_files_all_matches` direct tests** — Multi-line log verification, currently only tested via timeline

### Utilities (`lpmp_utils.py`)
- **`load_file_ignore_list`** — Auto-loading from search paths, YAML parsing, error handling
- **`is_ignored_path`** — Directory prefix, glob pattern, and basename matching
- **`_parse_custom_timestamp`** — Custom format matching with single and list patterns
- **`_expand_window_globs`** — Recursive subdirectory discovery with directory pruning
- **`find_no_timestamp_files`** — Recursive walk with ignore list and custom format support
- **`get_file_date_range` cache retry** — Cache-miss retry when relpath provided
- **`parse_timestamp` relaxed ISO** — Timestamps without milliseconds, mid-line timestamps

### Output (`lpmp_output.py`)
- **`_extract_timestamp_from_data`** — All custom formats (comma millis, 2-digit year, no millis)

### Bundle & System Mode (`lpmptool` + `lpmp_utils.py`)
- **System summary merge dispatch** — Verify system summary writers called with correct paths
- **Multi-format system profile merge** — Correct chronological sorting across all timestamp formats

## Medium Priority Gaps

### File I/O Optimization (`lpmp_engine.py` + `lpmp_utils.py`) - 78%/81% Coverage
- **Smart filter skip vs search decision** — Verify files correctly skipped/included based on date ranges
- **File position tracking round-trip** — Sequential block processing, verify start_pos parameter works
- **Reverse-chrono sort order** — Verify newest-first file ordering

### Variable Substitution & Override (`lpmp_engine.py` + `lpmp_utils.py`)
- **`manage_peer_controller` basic mapping** — controller-0→controller-1 and reverse
- **Override feature end-to-end** — ~100 lines, cross-host pattern matching in bundle mode
- **`apply_variable_substitution` override skip** — Blocks with override field defer pattern substitution

### Stacked Blocks & Present Blocks (`lpmp_engine.py`)
- **`present: true` in orchestration** — Present block not found → processing continues
- **OR patterns in stacked blocks** — Pattern list `["alt_A", "alt_B"]` within stacked block

## Low Priority Gaps

### Model Loading Minor Gaps (`lpmp_utils.py`) - 78%/81% Coverage
- **Nested includes** — Include chain A → B → C, settings merge across 3 levels
- **Include file not found error** — load_model with nonexistent include → sys.exit

## Recently Completed

### ✅ Host Option, List-Models Enhancements, Loops=0 (2026-04-08) — 496 → 520 tests
- **`--host` option**: Sets `{host}` variable for pattern substitution (CLI and model settings)
- **`--sort` option**: Alphabetical sort for `--list-models` output
- **Helper models**: `--list-models` discovers helpers/ subdirectory models
- **Example model guard**: Example models blocked from running with informative message
- **`--loops 0`**: Loop until EOF, first-loop failure still exits
- **`--max-lines` validation**: Must be ≥0
- **11 tests** in `test_force_option.py`, **13 tests** in `test_host_setting.py`,
  **2 tests** in `test_cli_arguments.py`, **1 test** in `test_edge_cases.py`

### ✅ Window Model Performance Optimizations (2026-04-06) — 462 → 496 tests
- **Bisect seek**: Binary search in plain-text files (>32KB) to jump near the
  start timestamp, avoiding linear scan of lines before the window
- **Rotation-aware .gz pruning**: Once a `.gz` rotation is before the window,
  all higher-numbered rotations of the same base log are skipped without reading
- **zcat|tail for .gz last-timestamp**: Uses `zcat | tail -50` subprocess instead
  of Python line-by-line decompression for fast last-timestamp detection
- **`.gz` binary classification fix**: `.gz` files no longer rejected as
  "binary/non-log" by `_is_skippable_file` in `discover_window_files`
- **28 new tests**: Bisect seek (3), rotation pruning (4), .gz date range (3),
  discover with rotation (2), failure/edge cases (9), .gz window coverage (7)

### ✅ Subdirectory Discovery, File Ignore List, Custom Timestamps (2026-04-03)
- **Subdirectory log discovery**: Window models recursively find logs in subdirs
- **Directory skip**: Directories silently skipped, empty dirs reported at -v
- **File ignore list**: Auto-loaded file_ignore_list_and_format_handling.yaml with ignore and timestamp_formats
- **Custom timestamp formats**: Fallback parsing chain with per-file pattern matching
- **Relaxed ISO parsing**: Optional milliseconds, mid-line timestamp matching
- **--no-ts-files**: Lists files with no parseable timestamps and exits
- **Bundle host sort**: controller-0 first, controller-1, storage, others
- **System profile merge**: Multi-format timestamp sorting in merged profiles
- **last_ts None guard**: Falls back to first_ts when last_ts is None
- **Time-window skip verbosity**: before/after time window skips at -vv not -v

### ✅ Window Model, Context Label, and Test Coverage (2026-04-02) — 435 → 462 tests
- **extract_context_lines edge cases**: Match at EOF (fewer after lines), zero
  before, zero after, both zero, file not found, no match, large context on
  small file, gzipped file, first-occurrence-wins with duplicate lines
- **load_model context parsing failures**: Invalid string format, single-element
  list, three-element list all trigger sys.exit(1); zero value accepted;
  timeline block with context accepted; pair block context ignored with warning
- **write_context_files variations**: Multiple matches in one block, multiple
  blocks produce separate files, no matching results produces no file, empty
  context tuples still produce output, TimelineResult with context, blocks
  without context_before skipped, results with context=None filtered out
- **Bundle integration tests** (6 tests, require `--bundle` or `LPMP_TEST_BUNDLE`):
  context from gzipped log, pattern model against real sm.log, timeline model
  against real mtcAgent.log, override block reading peer controller's logs,
  window model with file filtering, present:true unfound block produces no
  .context file
- Updated run_tests.py skip count message (4 → 10 bundle tests)

### ✅ lpmptool Coverage 40% → 70% (2026-03-27) — 374 → 405 tests
- **System mode end-to-end** — Pattern/pair/timeline output file creation, CSV content, no-match error
- **Settings application** — block_time_tolerance, controller, optional, max_log_length from model
- **Multi-loop** — loops=2 two passes, timeline single pass, loops<=0 rejected
- **--list-models** — Model discovery and empty directory handling
- **Bundle mode (synthetic)** — Per-host dirs, files, hostname substitution, missing logs skip
- **Bundle regression (optional)** — Real bundle with 3 hosts, output validation
- **Help-model** — Invalid topic, named topic, output matches get_help_section
- **MemoryMonitor** — Disabled path, print_stats, --stats flag
- **ConsoleCapture** — Basic capture and silent mode

### ✅ CLI Input Validation (2026-03-27) — 21 → 51 tests in test_cli_arguments.py
- **Stop date validation** — Invalid format, stop < start, stop == start, partial formats
- **Mutually exclusive options** — --include + --exclude conflict
- **Host options without bundle** — --include/--exclude without --bundle
- **Bundle path validation** — Non-existent path, empty bundle directory
- **Settings precedence** — max-time-delta, loops, start-date (CLI > model > default)
- **Output directory structure** — Explicit -o and default cwd-based paths
- **Date format flexibility** — All partial ISO formats, space separator, milliseconds
- **Help-model topics** — All 16 topics, invalid/named topics, output verification

### ✅ Search Performance Optimizations (2026-03-27)
- **Time-bounded timeline search** — File filtering, timestamp-first, early stop on stop_date
- **Early file pruning** — Files outside date window removed before processing
- **Regex pre-compilation** — Patterns compiled once, duplicated fallback path eliminated
- **Timestamp parsing** — Pre-compiled regexes, cheap prefix guard

### ✅ Output Generation Functions (`lpmp_output.py`) - 83% Coverage
- **Complete function coverage** — 46 tests including print_output_files

### ✅ Graph Generation Functions (`lpmp_graph.py`) - 62% Coverage
- **End-to-end workflow** — Complete extract → CSV → graph pipeline

### ✅ File Date Range Functions (`test_get_file_date_range.py`) - 19 Tests
- **File type handling, caching, error conditions** — Comprehensive coverage
