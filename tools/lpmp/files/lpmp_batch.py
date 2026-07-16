#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
LPMP Batch Mode Module

Single-pass file reading across multiple (model, start_date, stop_date)
runs declared in a JSON batch spec. Loads each unique model once,
groups every timeline/window block target by physical log file, opens
each file exactly once and matches against every relevant run in that
single pass.

Usage:
    lpmptool --batch batch_spec.json --bundle /path/to/collect \
        --include host1 host2 [--output DIR] [--verbose]

Timeline and window blocks are supported. A batched model containing
pair or pattern blocks is skipped in full — those block types carry
sequential-ordering and cross-block state that single-pass reading
cannot preserve. `load_model` already requires a model's blocks to
be homogeneous (all timeline-family, or all pair/pattern), so this is
a per-model decision: each unsupported model prints exactly **one**
warning line naming the model and the unsupported block type(s),
regardless of how many hosts the batch scans or how many blocks the
model has. Every run using a supported model still executes normally.

Timeline blocks retain their per-line regex filter with the same
combined-alternation, first-match-wins semantics as the mainline engine.
Window blocks emit every timestamped line whose timestamp falls inside
the run's window — matching the mainline window behaviour.

Output for each run is written into the batch-specific layout
    <output_root>/lpmp_batch_<lab>/<YYYYMMDD_HHMMSS>/[<start_date_time>_]<model_base>[_<end_date_time>][/<host>]

The batch gets its own "tool runtime" directory level named after the
wall-clock time the batch started (matching how mainline `lpmptool -m`
names its dirs), so re-running the same spec never clobbers a previous
run's output. Underneath that single runtime directory, each run gets
its own subdirectory named from its own resolved start/stop dates and
model name — the model's start and stop dates are only included when
the run actually has them (from the spec, CLI, or model settings);
unbounded ends are simply omitted rather than padded out. Examples
(batch started at 2026-07-06 17:03:15):

  - Unbounded run:        20260706_170315/ceph_health
  - Start only:           20260706_170315/20260706_090000_ceph_health
  - Start and stop:       20260706_170315/20260706_090000_ceph_health_20260706_110000

A model may appear more than once in a batch spec as long as each
occurrence has a distinct effective start/stop window — the two runs
naturally land in distinct directories since the window is part of
the directory name. Two runs sharing both the same model AND the
same resolved window are rejected at load time (see
`_check_duplicate_runs`) since they would otherwise collide on disk.

The `batch_` prefix keeps batch output visibly distinct from mainline
`lpmp_<lab>/` runs sharing the same lab name (downstream tooling like
lpmp_graph is unaffected).
"""

from collections import defaultdict
import copy
from datetime import datetime
import gzip
import json
import os
import re
import sys
import time

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True  # noqa: E402
# cspell:ignore lpmp

from lpmp_engine import _bisect_seek_to_timestamp              # noqa: E402
from lpmp_engine import apply_variable_substitution            # noqa: E402
from lpmp_output import merge_timeline_profiles                # noqa: E402
from lpmp_output import write_context_files                    # noqa: E402
from lpmp_output import write_timeline_block_profile           # noqa: E402
from lpmp_output import write_timeline_csv                     # noqa: E402
from lpmp_utils import apply_timeline_variable_substitution    # noqa: E402
from lpmp_utils import create_output_directory                 # noqa: E402
from lpmp_utils import detect_bundle_hosts                     # noqa: E402
from lpmp_utils import expand_wildcards_in_blocks              # noqa: E402
from lpmp_utils import filter_hosts                            # noqa: E402
from lpmp_utils import find_model_file                         # noqa: E402
from lpmp_utils import format_duration                         # noqa: E402
from lpmp_utils import format_log_line_for_output              # noqa: E402
from lpmp_utils import format_long_listing                     # noqa: E402
from lpmp_utils import get_file_date_range                     # noqa: E402
from lpmp_utils import get_verbose_level                       # noqa: E402
from lpmp_utils import load_model                              # noqa: E402
from lpmp_utils import parse_timestamp                         # noqa: E402
from lpmp_utils import ProgressType                            # noqa: E402
from lpmp_utils import resolve_timeline_patterns               # noqa: E402
from lpmp_utils import set_verbose_level                       # noqa: E402
from lpmp_utils import TimelineResult                          # noqa: E402
from lpmp_utils import vlog1                                   # noqa: E402
from lpmp_utils import vlog2                                   # noqa: E402


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

def _parse_iso(value, context):
    """Parse an ISO date string; sys.exit(1) with context on failure.

    Sub-second precision (milliseconds/microseconds) is rejected. The
    batch output directory naming truncates each run's start/stop to
    whole-second granularity (`%Y%m%d_%H%M%S`), so two dates differing
    only in their fractional-second component would parse as distinct
    datetimes — slipping past the exact-duplicate-window check in
    `_check_duplicate_runs` — yet still collide on disk once
    truncated to seconds. Reject sub-second dates outright rather than
    risk that silent collision.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as e:
        print(f"Error: {context}: invalid date {value!r} ({e})",
              file=sys.stderr)
        sys.exit(1)

    if parsed.microsecond != 0:
        print(f"Error: {context}: date {value!r} has sub-second "
              "precision (milliseconds/microseconds), which is not "
              "supported in batch mode — output directory names only "
              "have whole-second resolution. Use a whole-second "
              "timestamp (e.g. 'YYYY-MM-DDTHH:MM:SS').",
              file=sys.stderr)
        sys.exit(1)

    return parsed


def load_batch_spec(batch_file):
    """Load and validate a batch specification JSON file.

    Only `model` is required per run. `start_date` and `stop_date` are
    optional; when absent the run falls back to the CLI --start-date /
    --stop-date, then to the model's own settings, and finally to an
    unbounded read (no time filter).

    Returns:
        List of dicts each with keys: model, start_date (str, optional),
        stop_date (str, optional), _start (datetime | None),
        _stop (datetime | None). The datetime fields are populated by
        `_resolve_run_dates` after models are loaded.
    """
    try:
        with open(batch_file) as f:
            spec = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: Cannot load batch spec '{batch_file}': {e}",
              file=sys.stderr)
        sys.exit(1)

    # A bare top-level list of runs is also accepted for the common
    # "just a list of models" case: `[{"model": "a"}, {"model": "b"}]`.
    if isinstance(spec, list):
        runs = spec
    elif isinstance(spec, dict):
        runs = spec.get("runs")
    else:
        runs = None

    if not runs or not isinstance(runs, list):
        print("Error: Batch spec must have a 'runs' array (or be a bare "
              "list of runs)", file=sys.stderr)
        sys.exit(1)

    for i, run in enumerate(runs):
        if not isinstance(run, dict):
            print(f"Error: Run #{i + 1} must be a JSON object", file=sys.stderr)
            sys.exit(1)
        if "model" not in run:
            print(f"Error: Run #{i + 1} missing required key 'model'",
                  file=sys.stderr)
            sys.exit(1)

        # A model may appear more than once in a batch spec as long as
        # each occurrence has a distinct effective time window — the
        # output directory name is built from model + start/stop, so
        # distinct windows naturally land in distinct directories.
        # Exact-duplicate (model, window) pairs are rejected later, in
        # `_check_duplicate_runs`, once CLI/model-setting fallback
        # dates have been resolved.

        # Optional dates — parse now so the spec load surfaces bad
        # strings early. Absent keys leave _start/_stop as None and
        # are resolved later against CLI + model settings.
        run["_start"] = (
            _parse_iso(run["start_date"], f"Run #{i + 1} start_date")
            if run.get("start_date") else None
        )
        run["_stop"] = (
            _parse_iso(run["stop_date"], f"Run #{i + 1} stop_date")
            if run.get("stop_date") else None
        )

        if (run["_start"] is not None and run["_stop"] is not None
                and run["_stop"] <= run["_start"]):
            print(f"Error: Run #{i + 1} stop_date must be after start_date",
                  file=sys.stderr)
            sys.exit(1)

    return runs


def _resolve_run_dates(runs, models, args):
    """Fill in each run's _start / _stop using the precedence chain:
    explicit run keys > CLI --start-date / --stop-date > model
    settings' start_date / stop_date > None (unbounded).

    Called after models have been loaded so per-model settings can
    contribute.
    """
    cli_start = _parse_iso(args.start_date, "--start-date") \
        if getattr(args, "start_date", None) else None
    cli_stop = _parse_iso(args.stop_date, "--stop-date") \
        if getattr(args, "stop_date", None) else None

    for run in runs:
        _blocks, settings, _path = models[run["model"]]
        settings = settings or {}

        if run["_start"] is None:
            if cli_start is not None:
                run["_start"] = cli_start
            elif settings.get("start_date"):
                run["_start"] = _parse_iso(
                    settings["start_date"],
                    f"model '{run['model']}' start_date"
                )
        if run["_stop"] is None:
            if cli_stop is not None:
                run["_stop"] = cli_stop
            elif settings.get("stop_date"):
                run["_stop"] = _parse_iso(
                    settings["stop_date"],
                    f"model '{run['model']}' stop_date"
                )

        if (run["_start"] is not None and run["_stop"] is not None
                and run["_stop"] <= run["_start"]):
            print(f"Error: Run for model '{run['model']}' has "
                  f"resolved stop_date {run['_stop']} <= start_date "
                  f"{run['_start']}", file=sys.stderr)
            sys.exit(1)


def _check_duplicate_runs(runs):
    """Reject runs that share both the same model and the same
    resolved (start, stop) window.

    The output directory name is built from `model + start + stop`
    with no other disambiguator, so two runs with identical model AND
    identical resolved window would collide on disk. Runs sharing a
    model with *different* windows are fine — that's the whole point
    of encoding the window in the directory name — so this check only
    fires on an exact (model, start, stop) match.

    Called after `_resolve_run_dates` so CLI/model-setting fallback
    dates are included in the comparison, not just what was written
    explicitly in the spec.
    """
    seen = {}  # (model, start, stop) -> first run number
    for i, run in enumerate(runs):
        key = (run["model"], run["_start"], run["_stop"])
        if key in seen:
            start_str = run["_start"].isoformat() if run["_start"] else "unbounded"
            stop_str = run["_stop"].isoformat() if run["_stop"] else "unbounded"
            print(f"Error: Run #{i + 1} duplicates run #{seen[key]}: "
                  f"model '{run['model']}' with the same resolved "
                  f"window ({start_str} .. {stop_str}). Give one of "
                  "them a different start_date/stop_date.",
                  file=sys.stderr)
            sys.exit(1)
        seen[key] = i + 1


def _resolve_model_path(model_name):
    """Resolve a model filename to its full path."""
    if os.path.isabs(model_name) and os.path.exists(model_name):
        return model_name
    if os.path.exists(model_name):
        return os.path.abspath(model_name)
    path = find_model_file(model_name)
    if path:
        return path
    print(f"Error: Model file '{model_name}' not found", file=sys.stderr)
    sys.exit(1)


def _load_all_models(runs):
    """Load each unique model once. Returns {name: (blocks, settings, path)}."""
    models = {}
    for run in runs:
        name = run["model"]
        if name not in models:
            path = _resolve_model_path(name)
            blocks, settings, _model_type = load_model(path)
            models[name] = (blocks, settings, path)
    return models


# ---------------------------------------------------------------------------
# Block classification (timeline-only)
# ---------------------------------------------------------------------------

def _classify_model_blocks(blocks, model_name):
    """Classify one model's blocks for batch-mode support.

    Batch mode only supports timeline and window blocks (both are
    timeline-family: chronological output, no cross-line state). Pair
    and pattern blocks carry sequential-ordering / cross-block state
    that single-pass reading cannot preserve.

    `load_model` already rejects a model that mixes timeline-family
    blocks with pair/pattern blocks, so in normal use a model's blocks
    are homogeneous by the time they reach here — the whole model is
    either fully supported or fully unsupported. This function prints
    at most **one** warning line per model regardless of how many
    unsupported blocks (or hosts) are involved, naming the block
    type(s) responsible.

    Returns:
        The list of supported (timeline/window) blocks if any exist,
        or None if the model has zero supported blocks (the caller
        should skip every run using this model).
    """
    unsupported_types = set()
    supported = []
    for block in blocks:
        if "timeline" in block or block.get("window"):
            supported.append(block)
        elif "start" in block and "stop" in block:
            unsupported_types.add("pair")
        elif "patterns" in block:
            unsupported_types.add("pattern")
        else:
            unsupported_types.add("unclassified")

    if unsupported_types:
        kinds = " and ".join(sorted(unsupported_types))
        print(f"⚠️ Warning: Skipping model '{model_name}' "
              f"({kinds} block(s) not supported in Batch runs; timeline "
              f"and window blocks only)", file=sys.stderr)

    return supported if supported else None


def _classify_all_models(models):
    """Classify every unique model once. Returns {name: blocks|None}.

    Called once per batch invocation (not per host, not per run) so
    a pair or pattern model in the spec produces exactly one warning
    line no matter how many hosts the batch scans.
    """
    return {
        model_name: _classify_model_blocks(
            copy.deepcopy(blocks_orig), model_name)
        for model_name, (blocks_orig, _settings, _path) in models.items()
    }


# ---------------------------------------------------------------------------
# File grouping (build combined-alternation regex per target)
# ---------------------------------------------------------------------------

def _build_target_regex(timeline_patterns, block_label):
    """Build a single combined-alternation regex from a timeline pattern list.

    Mirrors process_timeline_block in lpmp_engine.py so batch mode
    honours the same first-match-wins semantics: at most one row per
    source log line per target.

    Returns None if no patterns compile successfully.
    """
    flat = []
    for pattern in timeline_patterns:
        if isinstance(pattern, list):
            flat.extend(pattern)
        else:
            flat.append(pattern)

    if not flat:
        return None

    valid = []
    for p in flat:
        try:
            re.compile(p)
            valid.append(p)
        except re.error as e:
            print(f"⚠️ Warning: Invalid regex in timeline block "
                  f"'{block_label}': {p!r} ({e})", file=sys.stderr)

    if not valid:
        return None

    combined = "|".join(f"(?:{p})" for p in valid)
    return re.compile(combined)


def _build_file_groups(runs, models, classified, logs_dir, hostname):
    """Group runs by target log file for single-pass reading.

    `classified` is the {model_name: supported_blocks|None} map from
    `_classify_all_models`, computed once per batch invocation so
    unsupported-model warnings are never repeated per host.

    Returns:
        Dict of filepath -> list of target dicts. Each target has keys:
            run_idx, block_label, filename, start, stop, regex.
    """
    groups = defaultdict(list)

    for run_idx, run in enumerate(runs):
        model_name = run["model"]
        _blocks_orig, settings, _model_path = models[model_name]

        supported_blocks = classified.get(model_name)
        if not supported_blocks:
            continue
        # Deep copy per host: variable substitution and wildcard
        # expansion below mutate the block dicts in place.
        blocks = copy.deepcopy(supported_blocks)

        variables = {"hostname": hostname}
        apply_variable_substitution(blocks, variables)
        expand_wildcards_in_blocks(
            blocks, logs_dir, run["_start"], run["_stop"]
        )

        for block in blocks:
            label = block.get("label", "<unlabeled>")

            controller_only = block.get("controller", False)
            if controller_only and "controller" not in hostname:
                vlog2(f"Skipping controller-only block '{label}' "
                      f"for non-controller host {hostname}")
                continue

            # Window blocks: no pattern filter — every timestamped line
            # in the window contributes one row. Signalled by regex=None.
            if block.get("window"):
                regex = None
            else:
                timeline_patterns = resolve_timeline_patterns(
                    block["timeline"], settings
                )
                timeline_patterns = apply_timeline_variable_substitution(
                    timeline_patterns,
                    {**variables, "label": label},
                )
                regex = _build_target_regex(timeline_patterns, label)
                if regex is None:
                    continue

            file_list = block["file"] if isinstance(block["file"], list) \
                else [block["file"]]

            # Substitute None bounds with datetime.min / datetime.max
            # so downstream comparisons in _single_pass_read work
            # without special-casing an "unbounded" flag.
            target_start = run["_start"] if run["_start"] is not None \
                else datetime.min
            target_stop = run["_stop"] if run["_stop"] is not None \
                else datetime.max

            for filename in file_list:
                filepath = os.path.join(logs_dir, filename)
                if not os.path.exists(filepath):
                    continue
                groups[filepath].append({
                    "run_idx": run_idx,
                    "block_label": label,
                    "filename": filename,
                    "start": target_start,
                    "stop": target_stop,
                    "regex": regex,
                })

    return groups


# ---------------------------------------------------------------------------
# Single-pass reader
# ---------------------------------------------------------------------------

def _single_pass_read(filepath, targets):
    """Read a file once, emit at most one row per line per target.

    Returns dict of run_idx -> list of (timestamp, formatted_line,
    filename, block_label) tuples.
    """
    results = defaultdict(list)
    if not targets:
        return results

    relpath = os.path.basename(filepath)

    earliest_start = min(t["start"] for t in targets)
    latest_stop = max(t["stop"] for t in targets)

    # Whole-file prune: if this file's timestamps are entirely outside
    # every target's window, skip the open entirely.
    first_ts, last_ts = get_file_date_range(filepath, relpath)
    if first_ts and last_ts:
        if earliest_start > last_ts:
            return results
        if latest_stop < first_ts:
            return results

    is_gzipped = filepath.endswith(".gz")
    open_func = gzip.open if is_gzipped else open
    mode = "rt" if is_gzipped else "r"

    try:
        with open_func(filepath, mode, encoding="utf-8",
                       errors="ignore") as f:
            if not is_gzipped:
                try:
                    file_size = os.path.getsize(filepath)
                    if file_size > 32768:
                        _bisect_seek_to_timestamp(
                            f, earliest_start, file_size, relpath
                        )
                except OSError:
                    pass

            while True:
                line = f.readline()
                if not line:
                    break
                timestamp = parse_timestamp(line, relpath)
                if not timestamp:
                    continue
                if timestamp > latest_stop:
                    break

                for target in targets:
                    if timestamp <= target["start"] \
                            or timestamp > target["stop"]:
                        continue
                    # Window blocks: regex is None, emit every line in
                    # window. Timeline blocks: regex.search must match.
                    regex = target["regex"]
                    if regex is not None and not regex.search(line):
                        continue
                    # Match mainline (lpmp_engine.process_*): full
                    # strip so trailing spaces and CR bytes from CRLF
                    # log files don't leak into the CSV cells.
                    formatted = format_log_line_for_output(
                        line.strip(), target["filename"]
                    )
                    results[target["run_idx"]].append((
                        timestamp,
                        formatted,
                        target["filename"],
                        target["block_label"],
                    ))
    except (IOError, OSError) as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
    except Exception as e:  # gzip.BadGzipFile, decode errors etc.
        print(f"Error processing {filepath}: {e}", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# Per-run output writer
# ---------------------------------------------------------------------------

def _write_profile_text(profile_path, hostname, matches, max_log_length):
    """Write the human-readable profile.timeline.log for one host+run."""
    prev_ts = None
    with open(profile_path, "w") as f:
        f.write(
            f"{'Delta(HH:MM:SS)':>15}\t{'Hostname':<12}\t"
            f"{'Block Label':<25}\t{'Log File':<30}\tData\n"
        )
        f.write(
            f"{'-' * 15}\t{'-' * 12}\t{'-' * 25}\t"
            f"{'-' * 30}\t{'-' * 8}\n"
        )
        for ts, log_line, filename, block_label in matches:
            if prev_ts is None:
                delta = format_duration(0.0)
            else:
                delta = format_duration((ts - prev_ts).total_seconds())
            prev_ts = ts
            truncated = log_line[:max_log_length] if max_log_length \
                else log_line
            f.write(
                f"{delta:>15}\t{hostname:<12}\t{block_label:<25}\t"
                f"{filename:<30}\t{truncated}\n"
            )


def _write_run_output(args, run, model_name, hostname, matches,
                      blocks, run_start_time):
    """Write per-host outputs for a single run and return the profile path."""
    if not matches:
        return None

    matches.sort(key=lambda x: x[0])

    # `_dir_time` (the batch wall-clock start) and `_dir_name` (this
    # run's own directory name) are set by `_precompute_run_dirs`.
    # `run_start_time` is a defensive fallback for callers that
    # skipped precompute.
    dir_time = run.get("_dir_time") or run_start_time
    dir_name = run.get("_dir_name")

    # Reuse mainline directory factory by temporarily pointing
    # args.model_file at this run's model. The runtime directory
    # (named after the batch's wall-clock start) is injected via
    # `extra_dir`, and this run's own directory name (derived from its
    # start/stop dates + model name) via `dir_name`, so the layout is
    # <output_root>/lpmp_batch_<lab>/<runtime>/<run_dir>[/<host>]
    # (the 'batch_' segment is injected by the parent-set
    # `args._dir_prefix`, see create_output_directory).
    saved_model_file = getattr(args, "model_file", None)
    args.model_file = model_name
    try:
        run_dir = create_output_directory(
            args, dir_time, hostname,
            extra_dir=run.get("_runtime_dir"), dir_name=dir_name,
        )
    finally:
        args.model_file = saved_model_file

    structured = [
        TimelineResult(
            timestamp=ts.isoformat(),
            block_label=block_label,
            log_line=log_line,
            actual_filename=filename,
            hostname=hostname,
        )
        for ts, log_line, filename, block_label in matches
    ]

    lab_name = args.lab_name
    profile_path = os.path.join(
        run_dir, f"{lab_name}_{hostname}_profile.timeline.log"
    )
    csv_path = profile_path + ".csv"

    _write_profile_text(profile_path, hostname, matches, args.max_log_length)
    write_timeline_csv(csv_path, structured, [])
    write_timeline_block_profile(run_dir, blocks, structured)
    write_context_files(run_dir, blocks, structured)

    return profile_path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _run_base_dir(args, run_start_time, model_name, run=None):
    """Return the run's base directory (parent of per-host subdirs).

    If `run` is given, honours its `_dir_time`, `_runtime_dir`, and
    `_dir_name` so the directory matches what `_write_run_output`
    produced per host.
    """
    dir_time = run_start_time
    extra_dir = None
    dir_name = None
    if run is not None:
        # These are set by `_precompute_run_dirs`. Keep the
        # `run_start_time` fallback for tests / callers that construct
        # a run dict manually without precompute.
        dir_time = run.get("_dir_time") or run_start_time
        extra_dir = run.get("_runtime_dir")
        dir_name = run.get("_dir_name")
    saved_model_file = getattr(args, "model_file", None)
    args.model_file = model_name
    try:
        base = create_output_directory(
            args, dir_time, None, extra_dir=extra_dir, dir_name=dir_name,
        )
    finally:
        args.model_file = saved_model_file
    return base


def _precompute_run_dirs(runs, args, run_start_time):
    """Assign each run its output-directory identity.

    The batch gets a single "tool runtime" directory named after the
    batch's wall-clock start time, so re-running the same batch spec
    never clobbers the previous run's output. Every run in the batch
    shares that one runtime directory.

    Underneath the runtime directory, each run gets its own
    subdirectory named from its resolved start/stop dates and model
    name: `[<start_date_time>_]<model_base>[_<end_date_time>]`.
    Unbounded ends (where start or stop is datetime.min / datetime.max,
    i.e. not present) are simply omitted rather than padded out.
    Because `load_batch_spec` rejects a spec that lists the same model
    more than once, each run's directory name is guaranteed unique
    within the batch without any extra suffix.

    Populates per-run fields:
      _dir_time    — datetime used to build the mainline dir path
                     (the batch wall-clock start)
      _runtime_dir — the batch's tool-runtime directory name, shared
                     by every run in this batch
      _dir_name    — this run's own directory name
    """
    runtime_dir = run_start_time.strftime("%Y%m%d_%H%M%S")

    for run in runs:
        run["_dir_time"] = run_start_time
        run["_runtime_dir"] = runtime_dir

        start = run.get("_start")
        stop = run.get("_stop")
        model_base = os.path.splitext(os.path.basename(run["model"]))[0]

        name_parts = []
        if start is not None and start != datetime.min:
            name_parts.append(start.strftime("%Y%m%d_%H%M%S"))
        name_parts.append(model_base)
        if stop is not None and stop != datetime.max:
            name_parts.append(stop.strftime("%Y%m%d_%H%M%S"))

        run["_dir_name"] = "_".join(name_parts)


def _batch_runtime_root(args, run_start_time):
    """Return the batch's shared tool-runtime directory path.

    This is the parent directory of every run's own subdirectory
    (`<prefix>/<runtime>`), mirroring the path-building logic in
    `create_output_directory` without needing a model name or
    hostname. Returns None for the "output is current directory"
    special case, where `create_output_directory` never creates a
    `<prefix>/` wrapper at all.
    """
    if args.output:
        if args.output == '.' or os.path.abspath(args.output) == os.getcwd():
            return None
        base_path = args.output
    elif getattr(args, 'bundle_name', '/') != '/':
        base_path = args.bundle_name
    else:
        base_path = os.getcwd()

    dir_prefix = getattr(args, '_dir_prefix', None) or f"lpmp_{args.lab_name}"
    runtime_dir = run_start_time.strftime("%Y%m%d_%H%M%S")
    return os.path.join(base_path, dir_prefix, runtime_dir)


def _batch_progress_type(args):
    """Resolve the progress indicator for batch mode.

    Batch is opt-in: mainline argparse defaults --progress to 'dots'
    but that pulls a background thread into every batch invocation.
    Batches run for many seconds per host and the thread's stdout
    wake-ups add ~20% overhead under GIL contention with file I/O,
    so batch mode ignores the mainline default and only enables the
    indicator when the user typed --progress / -p explicitly.
    """
    for arg in sys.argv:
        if arg == '--progress' or arg == '-p' or arg.startswith('--progress='):
            try:
                return ProgressType(getattr(args, "progress", "none"))
            except (TypeError, ValueError):
                return ProgressType.NONE
    return ProgressType.NONE


def run_batch(args):
    """Main entry point for batch mode execution."""
    set_verbose_level(getattr(args, "verbose", 0) or 0)

    runs = load_batch_spec(args.batch)
    vlog1(f"Batch mode: {len(runs)} runs from '{args.batch}'")

    models = _load_all_models(runs)
    vlog1(f"Batch mode: {len(models)} unique models loaded "
          f"({', '.join(sorted(models.keys()))})")

    # Classify each unique model's blocks exactly once. A model with
    # any pair/pattern blocks (single-pass reading can't preserve
    # their sequential-ordering state) gets exactly one warning line
    # here, regardless of how many hosts the batch scans.
    classified = _classify_all_models(models)

    # Fill in each run's _start/_stop from CLI + model settings when
    # they were not supplied in the spec. Runs still without bounds
    # after this pass are treated as unbounded (no time filter).
    _resolve_run_dates(runs, models, args)

    # Reject exact (model, resolved window) duplicates now that CLI
    # and model-setting fallback dates are filled in. A model may
    # repeat with a different window — that's expected and produces
    # distinct output directories.
    _check_duplicate_runs(runs)

    bundle_host_list, bundle_host_list_dated = detect_bundle_hosts(args.bundle)
    if getattr(args, "include", None):
        bundle_host_list, bundle_host_list_dated = filter_hosts(
            bundle_host_list, bundle_host_list_dated,
            args.include, mode="include",
        )
    elif getattr(args, "exclude", None):
        bundle_host_list, bundle_host_list_dated = filter_hosts(
            bundle_host_list, bundle_host_list_dated,
            args.exclude, mode="exclude",
        )
    vlog1(f"Batch mode: hosts = {', '.join(bundle_host_list)}")

    run_start_time = datetime.now()

    # Precompute per-run output directory identity so repeat models
    # with equal or unbounded windows never collide.
    _precompute_run_dirs(runs, args, run_start_time)

    logs_dir_rel = getattr(args, "logs_dir", "var/log")

    # per-run map: run_idx -> [(profile_path, hostname), ...]
    run_host_profiles = defaultdict(list)
    # per-run total match count for the summary at the end
    run_totals = defaultdict(int)

    # Output modes for the per-host scan phase:
    #   - -v (verbose): full '[i/N] hostname ... N matches (Ts)' line
    #     per host.
    #   - --progress (any type other than 'none') without -v: streaming
    #     comma-delimited host names on a single line, updated as each
    #     host completes. No background thread — the print is inline,
    #     so no GIL / stdout contention with the file-read loop.
    #   - default: silent scan; results appear in the per-run summary.
    progress_enabled = _batch_progress_type(args) != ProgressType.NONE
    verbose = get_verbose_level() >= 1
    total_hosts = len(bundle_host_list)
    print(f"Batch mode: {len(runs)} runs across {total_hosts} host(s)")

    batch_start = time.time()
    host_names_printed = 0
    for host_idx, (hostname, dated_dir) in enumerate(
            zip(bundle_host_list, bundle_host_list_dated), 1):
        logs_dir = os.path.join(args.bundle, dated_dir, logs_dir_rel)
        if not os.path.isdir(logs_dir):
            print(f"Warning: {logs_dir} not found, skipping {hostname}",
                  file=sys.stderr)
            continue

        if verbose:
            print(f"  [{host_idx}/{total_hosts}] {hostname:<16} ",
                  end='', flush=True)
        elif progress_enabled:
            sep = ', ' if host_names_printed else ''
            print(f"{sep}{hostname}", end='', flush=True)
            host_names_printed += 1
        host_start = time.time()

        file_groups = _build_file_groups(
            runs, models, classified, logs_dir, hostname)
        host_matches = defaultdict(list)
        for filepath, targets in file_groups.items():
            file_results = _single_pass_read(filepath, targets)
            for run_idx, matches in file_results.items():
                host_matches[run_idx].extend(matches)

        host_total = 0
        for run_idx, run in enumerate(runs):
            matches = host_matches.get(run_idx, [])
            if not matches:
                continue
            model_name = run["model"]
            # Reuse the once-per-batch classification result rather
            # than re-classifying (and re-warning) per host.
            blocks_for_writers = classified.get(model_name) or []
            profile_path = _write_run_output(
                args, run, model_name, hostname, matches,
                blocks_for_writers, run_start_time,
            )
            if profile_path:
                run_host_profiles[run_idx].append(
                    (profile_path, hostname))
                run_totals[run_idx] += len(matches)
                host_total += len(matches)
                vlog2(f"    ran '{model_name}' -> "
                      f"{len(matches)} matches")

        if verbose:
            elapsed = time.time() - host_start
            print(f" {host_total:>6} matches ({elapsed:.1f}s)")

    # Close the comma-delimited progress line before the next section
    # so the streaming summary starts on a fresh line.
    if not verbose and progress_enabled and host_names_printed:
        print()

    # Streaming per-run summary during the merge phase — each run's
    # system profile is emitted as it completes so long batches show
    # incremental output instead of a single dump at the end.
    print(f"\nWriting per-run system profiles ({len(runs)} runs):")
    for run_idx, run in enumerate(runs):
        model_name = run["model"]
        total = run_totals.get(run_idx, 0)
        host_files = run_host_profiles.get(run_idx, [])
        if host_files:
            base_dir = _run_base_dir(args, run_start_time, model_name, run)
            system_path = os.path.join(
                base_dir,
                f"{args.lab_name}_system_profile.timeline.log")
            merge_timeline_profiles(host_files, system_path)
            mark = "\u2713"  # check
        else:
            mark = "-"
        start_str = run["_start"].isoformat() if run["_start"] else "-"
        stop_str = run["_stop"].isoformat() if run["_stop"] else "-"
        window_str = f"{start_str} .. {stop_str}"
        print(f"  {mark} Run {run_idx + 1:>3}/{len(runs)}: "
              f"{model_name:<32}  {total:>6} matches  ({window_str})")

    grand_total = sum(run_totals.values())
    total_elapsed = time.time() - batch_start
    print(f"\nBatch complete: {grand_total} total matches across "
          f"{len(runs)} runs, {total_hosts} host(s) in {total_elapsed:.1f}s")

    runtime_root = _batch_runtime_root(args, run_start_time)
    if runtime_root:
        print(f"Output: {runtime_root}")
        for line in format_long_listing(runtime_root):
            print(line)
