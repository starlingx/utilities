# LPMP Development Context - Living Document

**Development workspace:** `/build/emacdona/wrcp-master-jira4/repo/cgcs-root/stx/utilities/tools/lpmp/files`

## Documentation Status

**Complete Documentation Suite:**
- ✅ **README.md** - Comprehensive user guide with examples and quick start
- ✅ **ARCHITECTURE.md** - Detailed technical architecture and design documentation
- ✅ **DEVELOPERS_GUIDE.md** - Complete developer guide with block types and examples
- ✅ **CONTEXT.md** - This living development context document
- ✅ **HISTORY.md** - Comprehensive change history with chronological tracking

**Documentation Quality:** Excellent
- Complete user onboarding with README.md
- Comprehensive architecture documentation
- Detailed developer guide with all block types
- Interactive help system (`--help-model`) with 19 topics
- Model search path and file location documentation
- Bundle mode and multi-host analysis coverage
- Test suite documentation with coverage reporting

## Development Guidelines

- Always favor simplicity over complexity. Offer options to discuss when the choice is not clear.
- Always prompt user asking approval for implementing what feels like an architectural change.
- Always prompt user asking approval for implementing changes that involve more than 20 lines.
- Architectural correctness always trumps hack fixes. Prompt to discuss when a solution does not align with that.
- Never compromise tool extensibility with hack or quick fixes. Offer options to discuss when the choice is not clear.
- Never unstage or checkout files that are under version control.
- Never leave end-of-line whitespace.
- Never make a tool change to fix a test without prompting the user to discuss.
- Never leave orphaned/dead code following a change.
- Always ask at the end if I want a printed summary of what was done.
- Always create diff files for changes after they are made. make that diff file persist in the files or tests dirs
- Not individual diffs, I want a combined one of all the changes from the last request.
- For large changes, like a refactor, create a dated tarball of the entire lpmp package dir tree.
- tarball file name format lpmp_<yyyymmdd_hhmmss>_<description of before change>
- For medium or large changes always create a persistent phased plan in `docs/PLAN_<description>.md` that tracks state = [PENDING|INPROGRESS|DONE]
- For non-trivial changes (>20 lines, multiple files, or critical functionality), always provide an L/M/S assessment of effort, change scope, and risk separately before implementing
- Keep line lengths less than or equal to 120 chars
- Follow PEP 8 style guidelines with max-line-length=120
- Unless otherwise stated I will manually run the lpmptool tests so you don't need to. Does not apply to the automated tests though.

### Code Style Requirements
- **Minimal Implementation:** Write only the absolute minimal code needed
- **No Verbose Code:** Avoid implementations that don't directly contribute to the solution
- **Maintain Consistency:** Follow existing patterns and naming conventions
- **Preserve Functionality:** Never break existing features without explicit approval
- **Test Coverage:** Maintain or improve test coverage for new features added
- **Block Type Checking:** Use explicit block type variables (`block_type == 'pattern'`, `block_type == 'pair'`, `block_type == 'timeline'`) rather than fragile methods like tuple length checking or field presence detection
- **Model Validation Tests:** Any changes to the model format — added or removed labels, keys, or variables — require corresponding updates to `test/test_validate_model.py` to keep validation tests in sync with the current model specification

### Debugging and Problem-Solving Approach
- **Root Cause Analysis**: Always identify the underlying cause before implementing fixes
- **Systematic Investigation**: Use verbose logging and step-by-step debugging to understand issues
- **Pattern Recognition**: Look for patterns in failures (e.g., "32 out of 265 tests failing due to function signature changes")
- **Architectural Understanding**: Understand how changes propagate through the system before making modifications
- **Test-Driven Debugging**: Use individual test execution to isolate and understand specific failures

### Test Suite Management Guidelines
- **Systematic Updates**: Use automated tools (sed, Python scripts) to update function signatures across multiple test files when architectural changes occur
- **Expectation Alignment**: Adjust test expectations to match new architectural realities rather than forcing code to match old tests
- **Failure Pattern Recognition**: Identify common causes of multiple test failures and address them systematically
- **Batch Test Fixes**: When multiple tests fail for the same reason, fix them all at once rather than one by one
- **Architectural Adaptation**: Update tests to match architectural changes (e.g., stacked pattern expansion) rather than preserving old behavior

### Code Modification Patterns
- **Stacked Pattern Expansion**: Multi-pattern blocks are automatically expanded into individual single-pattern blocks during model loading (affects test expectations)
- **Function Return Simplification**: Modern architecture returns results directly rather than tuples with metadata (affects function signature expectations)
- **Time Constraint Logic**: `max_time_delta` applies only to sequential pattern matching, not initial searches from start dates
- **Bundle Mode Processing**: Support for multi-host analysis with hostname-specific processing

### Error Recovery and Debugging Strategies
- **Graceful Degradation**: Continue processing when non-critical errors occur
- **Validation Early**: Validate inputs and configurations before expensive operations
- **Clear Error Messages**: Provide actionable error messages with suggested fixes
- **Exit Code Standards**: Use appropriate exit codes for different error conditions
- **Test Isolation**: Run individual tests for focused debugging using unittest module directly

### Performance and Architecture Insights
- **Start Date Behavior**: Tool should skip logs until reaching start date, then begin pattern matching (not reject patterns from before start date)
- **Block-Level Overrides**: YAML block settings can override programmatic defaults, causing unexpected behavior
- **Search Path Optimization**: Removal of search path returns that were used for error reporting in favor of direct results
- **File Processing Efficiency**: Smart file ordering and caching to optimize performance

### Automated Test Rules
- **Never Adjust Code for Tests:** If a test is failing and you believe the tool code is incorrect, prompt the user to discuss rather than modifying code to make tests pass
- **Always Update Test Status:** Update the "Test Status" in Current State Summary with current test count and pass rate after any test-related changes
- **Prompt for Test Runs:** After any code change exceeding 10 lines, prompt the user asking whether to run the automated test cases
- **How to Run Tests:** Execute tests from the tool directory using: `cd /build/emacdona/wrcp-master-jira1/repo/cgcs-root/stx/utilities/tools/lpmp/files/test && python3 run_tests.py`
- **Individual Test Debugging:** Use direct unittest execution for focused debugging: `python -c "import unittest; suite = unittest.TestSuite(); suite.addTest(TestClass('test_method')); runner = unittest.TextTestRunner(verbosity=2); runner.run(suite)"`
- **Coverage Analysis:** Use `--with-cov` option for code coverage analysis when available
- **Test Failure Analysis:** When multiple tests fail, look for common patterns (e.g., function signature changes, architectural modifications)
- **Systematic Test Updates:** Use automation tools (sed, Python scripts) to update multiple test files when architectural changes require it
- **Code Coverage Reporting:** Include current code coverage summary in HISTORY.md entries using the format:
  ```
  Current Automated Test Code Coverage:
  ============================================================
  lpmp_engine.py : XX% coverage
  lpmp_utils.py  : XX% coverage
  lpmptool       : XX% coverage
  Overall        : XX% coverage with XXX tests passing
  ============================================================
  ```
- **Replace Test Status with Coverage:** Always REPLACE any "**Test Status**" entries in HISTORY.md with the code coverage summary format above, never include both
- **No New HISTORY.md Sections:** Do not add any new sections to HISTORY.md - the existing structure is complete and adding more sections makes it too verbose
- **HISTORY.md Style:** Keep descriptions in layman's terms — describe *what* changed and *why* it matters, not the specific functions or internal implementation details involved
- **Auto-Update Coverage Stats:** Whenever the tool runs code coverage analysis, automatically update the coverage statistics in both CONTEXT.md Test Coverage Status section and any relevant HISTORY.md entries with the latest results

### Code Review Preparation Rules
- **"Prepare for Review" or "Prepare for Update" Commands:** When user requests preparation for review or update, prompt user with a checklist of actions to be performed:
  1. Run automated test suite with coverage analysis
  2. Execute Python static analysis (PEP8/flake8/pylint) with max-line-length=120
  3. Clean up end-of-line whitespace in all modified files
  4. Verify no orphaned code or dead imports remain
  5. Update documentation if architectural changes were made
  6. Create diff files for all changes since last request
  7. Update CONTEXT.md and HISTORY.md if significant changes occurred
  8. Update TEST_COVERAGE.md if tests were added, removed, or renamed — verify test counts, cross-reference against actual test files, and update the "Last full review" date
- **Static Analysis Tools:** Use `flake8`, `pylint`, or `pycodestyle` for Python code quality checks with --max-line-length=120
- **Whitespace Cleanup:** Remove trailing whitespace and ensure consistent line endings
- **Pre-Review Validation:** Ensure all tests pass and coverage meets minimum thresholds before declaring ready for review

### Large-Scale Change Process
When a request involves 5 or more discrete items (test additions, refactors, feature sets, etc.):
1. **Create a plan file** in `docs/PLAN_<description>.md` with a markdown table:
   - Columns: `#`, `Item`, `Description`, `Effort (S/M/L)`, `Risk (S/M/L)`, `Status`
   - Status values: `PENDING`, `IN-PROGRESS`, `DONE`
   - One row per discrete item
2. **Work item-by-item sequentially:**
   - Update the plan file to `IN-PROGRESS` before starting each item
   - Implement the item
   - Run the full test suite and verify PEP 8 compliance (120 line length, import ordering, alphabetical imports)
   - Update the plan file to `DONE` after tests pass
   - **Prompt the user to continue** before starting the next item — this is the crash recovery point
3. **Never batch multiple items** into a single step — each item is atomic so progress is never lost
4. **Keep the plan file** after completion as a record of what was done

### Architecture Constraints
- **Python 3.9 Compliance:** All code must be compatible with Python 3.9 (no match/case, no X|Y type unions, no builtin generic subscripts)
- **Single File Design:** Keep main functionality in `lpmptool` executable
- **Symlink Maintenance:** `lpmptool.py` is a symlink to `lpmptool` - never modify `lpmptool.py` directly, always edit `lpmptool`
- **Backward Compatibility:** Maintain existing command-line interface
- **Performance First:** Efficient file processing and memory usage
- **Error Handling:** Graceful failure with clear error messages

## Model Creation Rules

### Regex Escaping in YAML Patterns
Patterns in YAML model files are compiled as Python regular expressions. Characters
that have special meaning in regex **must be escaped** when they appear literally
in log lines. The most common pitfall is **parentheses**.

**Rule:** When a pattern contains literal parentheses (or any regex metacharacter
such as `(`, `)`, `[`, `]`, `{`, `}`, `.`, `*`, `+`, `?`, `^`, `$`, `|`, `\`),
you must double-escape them in YAML: use `\\\\(` and `\\\\)` to match literal `(` and `)`.

**Why double-escape?**
- YAML `\\\\(` → Python string `\\(` → regex interprets `\(` as literal `(`
- YAML `\\(` → Python string `\(` → regex sees an **incomplete escape** (may silently compile as a group)
- YAML `(` → Python string `(` → regex treats it as a **capture group** (compiles without error, but won't match the literal paren in the log)

**Example — WRONG (silent failure):**
```yaml
patterns:
  - "Service group (cloud-services) was in the standby state"
```
This compiles as a regex with `cloud-services` in a capture group. It searches
for `Service group cloud-services was in the standby state` (no parens) — which
doesn't exist in the log. No regex error is raised, so there is no fallback to
literal matching. The pattern silently fails to match.

**Example — CORRECT:**
```yaml
patterns:
  - "Service group \\(cloud-services\\) was in the standby state"
```
This matches the literal log text `Service group (cloud-services) was in the standby state`.

**Common metacharacters requiring `\\\\` escaping in YAML:**
| Character | Regex meaning | YAML escape |
|-----------|--------------|-------------|
| `(` `)` | Capture group | `\\\\(` `\\\\)` |
| `[` `]` | Character class | `\\\\[` `\\\\]` |
| `.` | Any character | `\\\\.` |
| `*` `+` `?` | Quantifiers | `\\\\*` `\\\\+` `\\\\?` |
| `{` `}` | Repetition | `\\\\{` `\\\\}` |
| `^` `$` | Anchors | `\\\\^` `\\\\$` |
| `\|` | Alternation | `\\\\\|` |

**Tip:** If your pattern is a plain literal string with no regex intent, check
for any of the above characters. If present, escape them or the pattern will
silently mismatch.

### Block Ordering for Sequential Patterns
Pattern blocks are processed sequentially — each block searches **after** the
previous block's timestamp. When multiple events fire within milliseconds of
each other (e.g., service groups going active during a swact), the log order
may vary between runs. Strategies:
- Use a single generic block to catch the first occurrence, then `optional: true`
  for specific variants
- Or use `present: true` for blocks whose order is unpredictable
- The `block_time_tolerance` setting (default 5.0s) allows searching slightly
  backwards, but only helps when the gap is within tolerance — it does **not**
  help when the pattern itself fails to match due to regex escaping issues

## Block Type Detection Best Practices

### Preferred Method: Explicit Block Type Variables
When processing blocks, always use explicit block type variables for conditional logic:

```python
# Block type detection
if 'timeline' in block:
    block_type = 'timeline'
elif 'start' in block and 'stop' in block:
    block_type = 'pair'
elif 'patterns' in block:
    block_type = 'pattern'

# Conditional logic using block type
if block_type == 'pattern':
    # Pattern-specific logic
elif block_type == 'pair':
    # Pair-specific logic
elif block_type == 'timeline':
    # Timeline-specific logic
```

### Avoid Fragile Methods
- **Don't use tuple length checking:** `len(result) == 4` is fragile and unclear
- **Don't use field presence detection:** Checking for specific fields in results is error-prone
- **Don't use isinstance() on result tuples:** This couples logic to return value structure

### Benefits of Explicit Block Type Checking
- **Clarity:** Code intent is immediately obvious
- **Maintainability:** Changes to return value structure don't break logic
- **Robustness:** Less prone to errors when adding new block types or modifying existing ones
- **Debugging:** Easier to trace block type-specific behavior

## Tool Overview

The Log Pattern Matching Profiler (LPMP) is a sophisticated log analysis tool designed for performance analysis, timing validation, and system operation profiling. LPMP transforms complex log analysis tasks into simple YAML model definitions with three distinct pattern matching modes:

1. **Pattern Blocks** - Sequential event timing analysis where patterns must be found in chronological order
2. **Pair Blocks** - Start/stop duration measurement for precise timing between clear beginning and end events
3. **Timeline Blocks** - Chronological event collection and ordering with no sequence requirements
4. **Window Blocks** - Time-range log extraction collecting all timestamped lines (timeline variant with `window: true`)

### Key Features
- **Model-Driven**: Define analysis patterns in human-readable YAML files
- **Multi-Format Support**: Handles regular and compressed (.gz) log files seamlessly
- **Bundle Mode**: Analyze multiple hosts simultaneously with automatic correlation
- **Variable Substitution**: Dynamic pattern customization with hostname and custom variables
- **Dual Output**: Generate both human-readable and CSV formats for further analysis
- **Interactive Help**: Comprehensive built-in help system with 19 documentation topics

## Key Architecture Components

### Core Files
- `lpmptool` - Main executable (3,000+ lines)

### Test Suite
- `test_lpmp.py` - Main test suite with comprehensive integration tests
- `test_model.py` - Model loading and validation tests
- `test_process_blocks.py` - Block processing engine tests
- `test_timeline_models.py` - Timeline-specific functionality tests
- `test_cli_arguments.py` - Command line interface tests
- `test_edge_cases.py` - Edge cases and boundary condition tests
- `test_block_time_tolerance.py` - Time tolerance and constraint tests
- `test_precedence_gaps.py` - Configuration precedence tests
- `test_validate_model.py` - Model structure validation tests
- `test_main_execution.py` - Main execution workflow tests
- `test_optional_warnings.py` - Optional block warning tests
- `test_summary_timing_format.py` - Output formatting tests
- `test_warning_format.py` - Warning message formatting tests
- `test_window_model.py` - Window model feature tests
- `run_tests.py` - Test runner with coverage analysis
- **Total**: 435 tests across 14 test files with code coverage reporting
- **Current Coverage**: lpmp_engine.py (77%), lpmp_utils.py (74%), lpmptool (36%), Overall (53%)
- **Pass Rate**: 435/435 tests passing (100%)

### Model Examples
- 7 example YAML model files
- `wrcp_domains_patterns.yaml` - Shared timeline patterns
- Mixed mode examples demonstrating all features

## Current Capabilities

### Pattern Matching
- ✅ Full regex support with literal fallback
- ✅ OR patterns: `["option1", "option2"]`
- ✅ Variable substitution: `{hostname}`, custom vars
- ✅ Multi-file search with fallback ordering
- ✅ Compressed file support (.gz)

### Bundle Processing
- ✅ Multi-host bundle detection and processing
- ✅ Interactive, include, exclude host filtering
- ✅ Per-host output with merged system profiles
- ✅ Controller-only filtering

### Timing Analysis
- ✅ Configurable timing constraints
- ✅ Time tolerance for out-of-order events
- ✅ Multiple analysis passes (loops)
- ✅ Chronological reordering
- ✅ Force mode (`--force` / `-f`) to override non-first block failures as warnings

### Output Generation
- ✅ Dual format: .timing (tab-separated) and .csv
- ✅ Per-block profile files with statistics
- ✅ Summary files with timing analysis
- ✅ Merged multi-host timeline files
- ✅ **Dedicated output writers**: `lpmp_output.py` contains model-type-specific output functions
- ✅ **Separate format functions**: Tool maintains distinct output file format functions for each model type (pattern, pair, timeline)
- ✅ **Structured output**: Uses `PatternResult`, `PairResult`, and `TimelineResult` data structures for type-safe output generation
- ⚠️ **Output Format Change Rule**: Always prompt user for confirmation whenever an output file format change is pending to ensure backward compatibility

## Test Coverage Status

**Total Tests:** 425 across 14 test files
- **test_lpmp.py**: Main integration tests with comprehensive workflows
- **test_model.py**: Model loading and validation functionality
- **test_process_blocks.py**: Block processing engine tests
- **test_timeline_models.py**: Timeline-specific functionality tests
- **test_cli_arguments.py**: Command line interface validation
- **test_edge_cases.py**: Edge cases and boundary conditions
- **test_block_time_tolerance.py**: Time tolerance and constraint handling
- **test_precedence_gaps.py**: Configuration precedence validation
- **test_validate_model.py**: Model structure validation
- **test_main_execution.py**: Main execution workflow tests
- **test_optional_warnings.py**: Optional block warning handling
- **test_summary_timing_format.py**: Output formatting validation
- **test_warning_format.py**: Warning message formatting
- **test_window_model.py**: Window model file discovery, auto time range, validation, loading

**Current Test Results:** 435/435 tests passing (100% pass rate)

**Code Coverage Analysis:**
```
Current Automated Test Code Coverage:
============================================================
lpmp_engine.py : 80% coverage
lpmp_output.py : 83% coverage
lpmp_graph.py  : 62% coverage
lpmp_utils.py  : 78% coverage
lpmptool       : 70% coverage
Overall        : 75% coverage with 435 tests passing
============================================================
```

**Test Cases Rules**
- Do not create or run tests that use --help-model nor --hosts as command line options
- Inform the user of any tests that use --help-model or --hosts if found. Ask what to do.

**Coverage Quality:** Good
- Edge cases covered
- Error handling tested
- Integration tests included
- Mock-based testing for dependencies
- Code coverage analysis available with `--with-cov` option

## Known Issues & Technical Debt

### Documentation
- ✅ Complete README.md with user guide and examples
- ✅ Comprehensive docs/ directory with 4 complete files
- ✅ Detailed architecture documentation
- ✅ Developer guide with all block types and examples
- ✅ Comprehensive built-in help (`--help-model`)
- ✅ Text-based visual architecture diagrams in ARCHITECTURE.md

### Code Quality
- ✅ Clean, well-structured code
- ✅ Consistent naming conventions
- ⚠️ Large main() function (could be refactored)
- ⚠️ Limited type hints

### Performance
- ✅ Efficient file position tracking
- ✅ Intelligent wildcard expansion
- ⚠️ No performance benchmarking
- ⚠️ No parallel processing for multi-host

## Development Priorities

### High Priority
1. Performance benchmarking and optimization

### Medium Priority
1. Refactor large functions
2. Add type hints
3. Enhanced error reporting and debugging

### Low Priority
1. GUI/web interface
2. Real-time monitoring mode
3. Plugin architecture
4. Integration with external monitoring systems

---

## Future Updates

This document will be updated as changes are made to track:
- New features added
- Bugs fixed
- Performance improvements
- Test coverage changes
- Architecture modifications
- Documentation updates

Each update should include:
- Date and description of changes
- Impact on existing functionality
- Test coverage updates
- Performance implications
- Breaking changes (if any)