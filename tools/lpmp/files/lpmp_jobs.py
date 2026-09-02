#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
LPMP Jobs Mode Module

Parallel subprocess dispatch of arbitrary lpmptool invocations declared
in a JSON jobs spec. Each job is a full mainline subprocess so any
model type is supported (timeline, window, pattern, pair, mixed) plus
graphing side effects.

Usage:
    lpmptool --jobs jobs_spec.json --bundle /path/to/collect \
        [--max-parallel N] [--fail-fast] [--force-parallel]

Distinct from --batch: batch mode is single-process, single-pass, and
timeline/window only; jobs mode is multi-process, generic, and honours
a bounded parallelism cap. See docs/PLAN_jobs_mode.md for architecture.
"""
from datetime import datetime
from datetime import timedelta
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import time


# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True  # noqa: E402
# cspell:ignore lpmp


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_PARALLEL = 3
ABSOLUTE_MAX_PARALLEL = 32          # governor to catch typos like --max-parallel 500
FD_PER_CHILD_BUDGET = 10            # rough per-child fd estimate
FD_PARENT_BUDGET = 32               # parent bookkeeping
SIGTERM_GRACE_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.1


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

_VALID_JOB_KEYS = frozenset({
    "model",
    "start_date",
    "stop_date",
    "hostname",
    "host",
    "include",
    "exclude",
    "vars",
    "output",
    "logs_dir",
    "lab",
    "loops",
    "progress",
    "force",
    "extra_args",
})

_VALID_TOP_KEYS = frozenset({"max_parallel", "fail_fast", "jobs"})


def load_jobs_spec(jobs_file):
    """Load and validate a jobs specification JSON file.

    Accepts two shapes, matching batch mode:

      * Bare list of jobs:
            [{"model": "a.yaml"}, {"model": "b.yaml"}]

      * Dict with `jobs` list plus optional top-level keys:
            {"max_parallel": 3, "fail_fast": false, "jobs": [...]}

    Only `model` is required per job. All other keys map to lpmptool
    CLI flags at argv-build time.
    """
    # Resolve the spec through the jobs search path so it can be given
    # by bare name (e.g. --jobs mtce_job) like models are with -m.
    from lpmp_utils import find_jobs_file
    from lpmp_utils import get_jobs_search_paths
    resolved = find_jobs_file(jobs_file)
    if resolved is None:
        print(f"Error: Jobs spec '{jobs_file}' not found in search paths:",
              file=sys.stderr)
        for i, path in enumerate(get_jobs_search_paths(0), 1):
            print(f"  {i}. {os.path.join(path, jobs_file)}", file=sys.stderr)
        print("Use --list-jobs to see available job specs.", file=sys.stderr)
        sys.exit(1)
    jobs_file = resolved
    print(f"Jobs spec: {os.path.abspath(jobs_file)}")

    try:
        with open(jobs_file) as f:
            spec = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: Cannot load jobs spec '{jobs_file}': {e}",
              file=sys.stderr)
        sys.exit(1)

    top_level = {}

    if isinstance(spec, list):
        jobs = spec
    elif isinstance(spec, dict):
        bad = set(spec.keys()) - _VALID_TOP_KEYS
        if bad:
            print(f"Error: Jobs spec has unknown top-level key(s): "
                  f"{sorted(bad)}", file=sys.stderr)
            sys.exit(1)
        jobs = spec.get("jobs")
        if "max_parallel" in spec:
            top_level["max_parallel"] = spec["max_parallel"]
        if "fail_fast" in spec:
            top_level["fail_fast"] = spec["fail_fast"]
    else:
        jobs = None

    if not jobs or not isinstance(jobs, list):
        print("Error: Jobs spec must have a 'jobs' array (or be a bare "
              "list of jobs)", file=sys.stderr)
        sys.exit(1)

    if "max_parallel" in top_level:
        mp = top_level["max_parallel"]
        if not isinstance(mp, int) or mp < 1:
            print(f"Error: 'max_parallel' must be a positive integer "
                  f"(got {mp!r})", file=sys.stderr)
            sys.exit(1)
    if "fail_fast" in top_level:
        if not isinstance(top_level["fail_fast"], bool):
            print("Error: 'fail_fast' must be true or false",
                  file=sys.stderr)
            sys.exit(1)

    for i, job in enumerate(jobs):
        _validate_job(job, i + 1)

    return jobs, top_level


def _validate_job(job, position):
    """Validate a single job dict. Exits with a positioned error on failure."""
    if not isinstance(job, dict):
        print(f"Error: Job #{position} must be a JSON object",
              file=sys.stderr)
        sys.exit(1)

    bad = set(job.keys()) - _VALID_JOB_KEYS
    if bad:
        print(f"Error: Job #{position} has unknown key(s): "
              f"{sorted(bad)}", file=sys.stderr)
        sys.exit(1)

    if not job.get("model"):
        print(f"Error: Job #{position} missing required key 'model'",
              file=sys.stderr)
        sys.exit(1)

    if not isinstance(job["model"], str):
        print(f"Error: Job #{position} 'model' must be a string",
              file=sys.stderr)
        sys.exit(1)

    for key in ("start_date", "stop_date", "hostname", "host",
                "output", "logs_dir", "lab", "progress"):
        if key in job and not isinstance(job[key], str):
            print(f"Error: Job #{position} '{key}' must be a string",
                  file=sys.stderr)
            sys.exit(1)

    for key in ("include", "exclude", "extra_args"):
        if key in job:
            val = job[key]
            if not isinstance(val, list) \
                    or not all(isinstance(x, str) for x in val):
                print(f"Error: Job #{position} '{key}' must be a "
                      f"list of strings", file=sys.stderr)
                sys.exit(1)

    if "loops" in job:
        if not isinstance(job["loops"], int) or job["loops"] < 0:
            print(f"Error: Job #{position} 'loops' must be a "
                  f"non-negative integer", file=sys.stderr)
            sys.exit(1)

    if "force" in job and not isinstance(job["force"], bool):
        print(f"Error: Job #{position} 'force' must be true or false",
              file=sys.stderr)
        sys.exit(1)

    if "vars" in job:
        vars_val = job["vars"]
        if isinstance(vars_val, dict):
            for k, v in vars_val.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    print(f"Error: Job #{position} 'vars' entries "
                          f"must be string:string", file=sys.stderr)
                    sys.exit(1)
        elif isinstance(vars_val, list):
            if not all(isinstance(x, str) for x in vars_val):
                print(f"Error: Job #{position} 'vars' list entries "
                      f"must be strings", file=sys.stderr)
                sys.exit(1)
        elif not isinstance(vars_val, str):
            print(f"Error: Job #{position} 'vars' must be a dict, "
                  f"list, or string", file=sys.stderr)
            sys.exit(1)


def _normalize_vars(vars_val):
    """Return the canonical `list[str]` of `K=V` items for argv output."""
    if not vars_val:
        return []
    if isinstance(vars_val, dict):
        return [f"{k}={v}" for k, v in vars_val.items()]
    if isinstance(vars_val, list):
        return list(vars_val)
    return [vars_val]


def _normalize_job(job, defaults):
    """Fill in inherited defaults from the parent invocation."""
    out = dict(job)
    out["_vars"] = _normalize_vars(job.get("vars"))

    for key in ("start_date", "stop_date", "hostname", "host",
                "output", "logs_dir", "lab", "loops", "progress"):
        if key not in out and defaults.get(key) is not None:
            out[key] = defaults[key]

    return out


# ---------------------------------------------------------------------------
# Argv builder — dict → list of strings for Popen
# ---------------------------------------------------------------------------

def _build_job_argv(job, defaults, lpmptool_path, bundle, computed_output):
    """Translate a normalised job dict into a child argv list.

    `computed_output` is the parent-computed unique output directory
    for this job (see `_precompute_job_outputs`). It is always emitted
    to guarantee no two jobs share a directory even when they run the
    same model in the same wall-clock second.

    Uses `-m/-s/-e/-b/-o/-n/-l` short flags where lpmptool exposes
    them; long flags otherwise.
    """
    argv = [sys.executable, lpmptool_path, "-m", job["model"]]

    if bundle:
        argv += ["-b", bundle]

    if job.get("start_date"):
        argv += ["-s", job["start_date"]]
    if job.get("stop_date"):
        argv += ["-e", job["stop_date"]]
    if job.get("hostname"):
        argv += ["--hostname", job["hostname"]]
    if job.get("host"):
        argv += ["--host", job["host"]]
    if job.get("include"):
        argv += ["--include", *job["include"]]
    if job.get("exclude"):
        argv += ["--exclude", *job["exclude"]]
    for kv in job.get("_vars", []):
        argv += ["--var", kv]
    if job.get("logs_dir"):
        argv += ["-l", job["logs_dir"]]
    if job.get("lab"):
        argv += ["--lab", job["lab"]]
    if job.get("loops") is not None:
        argv += ["-n", str(job["loops"])]
    if job.get("progress"):
        argv += ["--progress", job["progress"]]
    if job.get("force"):
        argv += ["--force"]

    # Parent-computed output always wins over the job's own `output`
    # value to keep collision avoidance deterministic. The job spec's
    # `output` was already folded into computed_output upstream.
    argv += ["-o", computed_output]

    if job.get("extra_args"):
        argv += list(job["extra_args"])

    return argv


def _precompute_job_outputs(jobs, args, batch_start_time):
    """Assign each job a unique output directory identity.

    Mirrors batch mode's `_precompute_run_dirs`: when two jobs share
    the same `(model_base, time_str)` key (same model, same second),
    the second and later get a `_run{idx}` suffix. Parent computes
    this up front so each child is handed an unambiguous `-o`.
    """
    # Effective parent output root: an explicit --output wins; else
    # bundle root; else cwd (matches mainline `create_output_directory`).
    if args.output:
        output_root = args.output
    elif getattr(args, "bundle_name", "/") != "/":
        output_root = args.bundle_name
    else:
        output_root = os.getcwd()

    claimed = {}
    time_str = batch_start_time.strftime("%Y%m%d_%H%M%S")

    for idx, job in enumerate(jobs):
        lab = job.get("lab") or getattr(args, "lab", "lab") or "lab"
        model_base = os.path.splitext(os.path.basename(job["model"]))[0]
        key = (lab, model_base, time_str)
        if key in claimed:
            suffix = f"_run{idx + 1}"
        else:
            claimed[key] = idx
            suffix = ""
        base = os.path.join(
            output_root, f"lpmp_{lab}",
            f"{time_str}_{model_base}{suffix}",
        )
        job["_output_dir"] = base

    return output_root


# ---------------------------------------------------------------------------
# FD-limit pre-flight
# ---------------------------------------------------------------------------

def _preflight_fd_check(max_parallel, force_parallel=False,
                        absolute_cap=ABSOLUTE_MAX_PARALLEL):
    """Sanity-check RLIMIT_NOFILE and clamp max_parallel accordingly.

    Returns the resolved max_parallel value. Prints a warning line
    when the effective value is lowered from the requested one.
    """
    # Governor: catch runaway --max-parallel typos.
    if max_parallel > absolute_cap and not force_parallel:
        print(f"Warning: --max-parallel {max_parallel} exceeds safety "
              f"cap {absolute_cap}; clamping. Use --force-parallel to "
              f"override.", file=sys.stderr)
        max_parallel = absolute_cap

    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except (ValueError, OSError, AttributeError):
        return max_parallel

    needed = max_parallel * FD_PER_CHILD_BUDGET + FD_PARENT_BUDGET
    if soft >= needed:
        return max_parallel

    # Try to raise the soft limit up to a comfortable margin.
    target = min(needed * 2, hard)
    if target > soft:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            return max_parallel
        except (ValueError, OSError):
            pass

    # Couldn't raise — clamp max_parallel to fit within the soft limit.
    new_cap = max(1, (soft - FD_PARENT_BUDGET) // FD_PER_CHILD_BUDGET)
    if new_cap < max_parallel:
        print(f"Warning: RLIMIT_NOFILE soft={soft}; lowering "
              f"max_parallel from {max_parallel} to {new_cap}",
              file=sys.stderr)
        max_parallel = new_cap
    return max_parallel


def _get_fd_soft_limit():
    """Return the current RLIMIT_NOFILE soft limit, or None if unknown."""
    try:
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        return soft
    except (ValueError, OSError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------

class _WorkerPool:
    """Bounded FIFO subprocess pool.

    Central invariant: number of jobs in state 'running' never exceeds
    max_parallel. Poll loop runs at POLL_INTERVAL_SECONDS cadence.
    """

    def __init__(self, jobs, max_parallel, fail_fast=False, verbose=False,
                 console_log_dir=None):
        self.jobs = jobs                    # list of dicts (mutated in place)
        self.max_parallel = max_parallel
        self.fail_fast = fail_fast
        self.verbose = verbose
        self.console_log_dir = console_log_dir
        self.pending = list(range(len(jobs)))   # indexes into self.jobs
        self.running = []                       # indexes currently running
        self.abort_flag = False
        self.abort_signal = None
        self.abort_deadline = None

    def _open_console_log(self, job):
        """Open the per-job console log path. Returns (fd, path)."""
        if not self.console_log_dir:
            return None, None
        os.makedirs(self.console_log_dir, exist_ok=True)
        idx = job["_idx"]
        base = os.path.splitext(os.path.basename(job["model"]))[0]
        path = os.path.join(
            self.console_log_dir,
            f"{idx:02d}_{base}.console.log",
        )
        # Line-buffered so tailing works, but the fd is handed to the
        # child which then owns it. Parent closes its copy immediately
        # after Popen returns.
        fd = open(path, "wb", buffering=0)
        return fd, path

    def _dispatch_next(self):
        """Start the next pending job if slots are available."""
        if not self.pending or self.abort_flag:
            return
        job_idx = self.pending.pop(0)
        job = self.jobs[job_idx]

        log_fd, log_path = self._open_console_log(job)
        job["_log_path"] = log_path

        try:
            proc = subprocess.Popen(
                job["_argv"],
                stdout=log_fd if log_fd is not None else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as e:
            if log_fd is not None:
                log_fd.close()
            job["_state"] = "failed"
            job["_exit_code"] = -1
            job["_error"] = f"Popen failed: {e}"
            print(f"  [{job['_idx']}/{len(self.jobs)}] "
                  f"{os.path.basename(job['model']):<32} "
                  f"FAILED to launch: {e}", file=sys.stderr)
            return

        # Parent closes its copy of the log fd immediately — the child
        # holds its own inherited copy for the life of the process.
        if log_fd is not None:
            log_fd.close()

        job["_proc"] = proc
        job["_state"] = "running"
        job["_started_at"] = time.time()
        self.running.append(job_idx)

        if self.verbose:
            print(f"  [{job['_idx']}/{len(self.jobs)}] "
                  f"{os.path.basename(job['model']):<32} start   "
                  f"(running={len(self.running)}/{self.max_parallel})",
                  flush=True)

    def _reap(self):
        """Sweep running jobs and finalise any that exited."""
        still_running = []
        finished = []
        for job_idx in self.running:
            job = self.jobs[job_idx]
            rc = job["_proc"].poll()
            if rc is None:
                still_running.append(job_idx)
                continue
            job["_exit_code"] = rc
            job["_finished_at"] = time.time()
            if rc == 0:
                job["_state"] = "passed"
            else:
                # Distinguish signal-killed from natural failure.
                if self.abort_flag and rc < 0:
                    job["_state"] = "killed"
                else:
                    job["_state"] = "failed"
            finished.append(job_idx)
        self.running = still_running
        return finished

    def request_shutdown(self, signum):
        """Ask the pool to abort. Idempotent."""
        if self.abort_flag:
            return
        self.abort_flag = True
        self.abort_signal = signum
        self.abort_deadline = time.time() + SIGTERM_GRACE_SECONDS
        for job_idx in self.running:
            job = self.jobs[job_idx]
            try:
                job["_proc"].terminate()
            except (ProcessLookupError, OSError):
                pass

    def _escalate_if_deadline_reached(self):
        """SIGKILL survivors once the SIGTERM grace period elapses."""
        if not self.abort_flag or self.abort_deadline is None:
            return
        if time.time() < self.abort_deadline:
            return
        for job_idx in self.running:
            job = self.jobs[job_idx]
            try:
                job["_proc"].kill()
            except (ProcessLookupError, OSError):
                pass

    def run(self):
        """Drive the pool to completion. Returns list of finished job indexes
        in completion order.
        """
        completion_order = []
        # Outer loop exits when either the queue is exhausted (or aborted)
        # and no children remain running. Under abort we stop dispatching
        # but must still drain currently-running children before exiting;
        # anything still in `pending` at exit is reported as skipped by
        # the summary caller.
        while (self.pending and not self.abort_flag) or self.running:
            # Dispatch until either the queue is empty or we hit the cap.
            while (self.pending
                   and len(self.running) < self.max_parallel
                   and not self.abort_flag):
                self._dispatch_next()

            time.sleep(POLL_INTERVAL_SECONDS)

            for job_idx in self._reap():
                completion_order.append(job_idx)
                job = self.jobs[job_idx]
                elapsed = job["_finished_at"] - job["_started_at"]
                model_base = os.path.basename(job["model"])
                state = job["_state"]
                if state == "passed":
                    mark = "pass"
                elif state == "killed":
                    mark = "killed"
                else:
                    mark = f"FAIL rc={job['_exit_code']}"
                print(f"  [{job['_idx']}/{len(self.jobs)}] "
                      f"{model_base:<32} {mark:<10} ({elapsed:.1f}s)",
                      flush=True)

                if state == "failed" and self.fail_fast \
                        and not self.abort_flag:
                    print("  fail_fast: aborting remaining jobs...",
                          file=sys.stderr)
                    self.request_shutdown(signal.SIGTERM)

            self._escalate_if_deadline_reached()

        return completion_order


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _resolve_max_parallel(args, top_level):
    """Precedence: CLI --max-parallel > spec max_parallel > default (3)."""
    if getattr(args, "max_parallel", None) is not None:
        return args.max_parallel
    if "max_parallel" in top_level:
        return top_level["max_parallel"]
    return DEFAULT_MAX_PARALLEL


def _resolve_fail_fast(args, top_level):
    """CLI --fail-fast forces on; spec provides the default when CLI omits."""
    if getattr(args, "fail_fast", False):
        return True
    return bool(top_level.get("fail_fast", False))


def _cli_defaults(args):
    """Build the defaults dict that populates job entries missing keys."""
    return {
        "start_date": getattr(args, "start_date", None),
        "stop_date": getattr(args, "stop_date", None),
        "hostname": getattr(args, "hostname", None),
        "host": getattr(args, "host", None),
        "logs_dir": getattr(args, "logs_dir", None),
        "lab": getattr(args, "lab", None),
        "loops": None,   # do not inherit --loops so jobs default to model behaviour
        "progress": None,
    }


def _resolve_lpmptool_path():
    """Locate the mainline lpmptool executable to hand to the child.

    Tried in order of reliability:
      1. sys.argv[0] — the lpmptool actually invoked by the user. Most
         reliable, and correct on the installed layout where the
         executable (/usr/local/bin/lpmptool) and this module
         (/usr/lib/python3/dist-packages/lpmp/) live in different dirs.
      2. A 'lpmptool' sibling of this module — the source-tree layout
         where everything sits in one directory.
      3. The packaged bin location.
      4. A PATH lookup as a last resort.
    """
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0 and os.path.basename(argv0) == "lpmptool" and os.path.sep in argv0:
        resolved = os.path.abspath(argv0)
        if os.path.exists(resolved):
            return resolved

    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(here, "lpmptool")
    if os.path.exists(candidate):
        return candidate

    installed = "/usr/local/bin/lpmptool"
    if os.path.exists(installed):
        return installed

    found = shutil.which("lpmptool")
    if found:
        return found

    # Last resort: whatever argv[0] was, absolutised.
    return os.path.abspath(argv0) if argv0 else "lpmptool"


def run_jobs(args):
    """Main entry point for jobs mode execution."""
    jobs, top_level = load_jobs_spec(args.jobs)

    max_parallel = _resolve_max_parallel(args, top_level)
    fail_fast = _resolve_fail_fast(args, top_level)
    force_parallel = getattr(args, "force_parallel", False)
    max_parallel = _preflight_fd_check(max_parallel, force_parallel)

    defaults = _cli_defaults(args)
    normalized = [_normalize_job(j, defaults) for j in jobs]

    batch_start = datetime.now()
    output_root = _precompute_job_outputs(normalized, args, batch_start)

    lpmptool_path = _resolve_lpmptool_path()

    # Assign per-job identity + argv before dispatch starts so any
    # build errors surface up front instead of mid-run.
    for i, job in enumerate(normalized):
        job["_idx"] = i + 1
        job["_state"] = "pending"
        job["_argv"] = _build_job_argv(
            job, defaults, lpmptool_path, args.bundle, job["_output_dir"]
        )

    # Per-job console logs live under a dedicated subdirectory so a
    # post-mortem finds them without walking model output trees.
    console_log_dir = os.path.join(
        output_root,
        f"lpmp_{getattr(args, 'lab', 'lab') or 'lab'}",
        f"{batch_start.strftime('%Y%m%d_%H%M%S')}_jobs",
    )

    fd_soft = _get_fd_soft_limit()
    fd_str = f"{fd_soft}" if fd_soft is not None else "unknown"
    print(f"Jobs: {len(normalized)} loaded, max_parallel={max_parallel}, "
          f"fd soft limit={fd_str}"
          f"{'  fail_fast=on' if fail_fast else ''}")
    print(f"Console logs: {console_log_dir}/")

    verbose_level = getattr(args, "verbose", 0) or 0
    pool = _WorkerPool(
        normalized, max_parallel, fail_fast=fail_fast,
        verbose=verbose_level >= 1,
        console_log_dir=console_log_dir,
    )

    # Signal handlers: propagate to running children with a grace period.
    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _shutdown(signum, _frame):
        print(f"\n  received signal {signum}; forwarding to running "
              f"children (grace={SIGTERM_GRACE_SECONDS:.0f}s)...",
              file=sys.stderr)
        pool.request_shutdown(signum)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    t0 = time.time()
    try:
        pool.run()
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)

    _print_summary(normalized, time.time() - t0, batch_start, console_log_dir)
    _exit_with_status(normalized, pool)


def _print_summary(jobs, elapsed, batch_start, console_log_dir):
    """Emit the passed/failed/total block plus a failure detail listing."""
    passed = sum(1 for j in jobs if j["_state"] == "passed")
    failed = sum(1 for j in jobs if j["_state"] == "failed")
    killed = sum(1 for j in jobs if j["_state"] == "killed")
    pending = sum(1 for j in jobs if j["_state"] == "pending")
    total = len(jobs)

    print(f"\nJobs complete: {passed} passed, {failed} failed"
          f"{f', {killed} killed' if killed else ''}"
          f"{f', {pending} skipped' if pending else ''}"
          f", {total} total in {elapsed:.1f}s")

    if failed or killed:
        print("\nFailure detail:")
        for job in jobs:
            if job["_state"] in ("failed", "killed"):
                log = job.get("_log_path") or "<no log>"
                rc = job.get("_exit_code")
                print(f"  {job['_idx']:>3}. {os.path.basename(job['model']):<32} "
                      f"state={job['_state']:<7} rc={rc}  {log}")


def _exit_with_status(jobs, pool):
    """Exit the parent with a code reflecting overall job status."""
    if pool.abort_signal == signal.SIGINT:
        sys.exit(130)
    if pool.abort_signal == signal.SIGTERM:
        sys.exit(143)
    exits = [j.get("_exit_code") for j in jobs
             if j.get("_exit_code") is not None]
    if not exits:
        sys.exit(0)
    worst = max(abs(e) for e in exits)
    sys.exit(worst if worst else 0)


# Silence unused-import warning: timedelta is a public dependency reserved
# for a future job-timeout knob. Remove when introduced.
_ = timedelta
