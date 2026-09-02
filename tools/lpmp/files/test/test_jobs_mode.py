#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""
Tests for lpmp_jobs.py (jobs mode).

Phase 1 covers pure helpers: spec loader, normalize helpers, argv
builder, and output-directory pre-computation.

Later phases cover the FD pre-flight, resolver helpers, worker pool,
and end-to-end run_jobs orchestration.
"""

import argparse
from datetime import datetime
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_jobs import _build_job_argv            # noqa: E402
from lpmp_jobs import _normalize_job             # noqa: E402
from lpmp_jobs import _normalize_vars            # noqa: E402
from lpmp_jobs import _precompute_job_outputs    # noqa: E402
from lpmp_jobs import _preflight_fd_check        # noqa: E402
from lpmp_jobs import _resolve_fail_fast         # noqa: E402
from lpmp_jobs import _resolve_max_parallel      # noqa: E402
from lpmp_jobs import _validate_job              # noqa: E402
from lpmp_jobs import _WorkerPool                # noqa: E402
from lpmp_jobs import ABSOLUTE_MAX_PARALLEL      # noqa: E402
from lpmp_jobs import DEFAULT_MAX_PARALLEL       # noqa: E402
from lpmp_jobs import load_jobs_spec             # noqa: E402
from lpmp_jobs import run_jobs                   # noqa: E402


def _make_args(**overrides):
    """Build a minimal argparse.Namespace shaped for jobs mode."""
    ns = argparse.Namespace(
        jobs=None,
        bundle='/some/bundle',
        bundle_name='/some/bundle',
        lab='lab',
        output=None,
        logs_dir='var/log',
        start_date=None,
        stop_date=None,
        hostname='controller-0',
        host=None,
        include=None,
        exclude=None,
        max_parallel=None,
        fail_fast=False,
        force_parallel=False,
        variables=None,
        verbose=0,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _write_spec(tmp_dir, payload):
    """Write a JSON spec into tmp_dir and return its path."""
    path = os.path.join(tmp_dir, 'spec.json')
    with open(path, 'w') as f:
        json.dump(payload, f)
    return path


# =========================================================================
# TestJobsSpecLoading — load_jobs_spec + _validate_job
# =========================================================================


class TestJobsSpecLoading(unittest.TestCase):
    """load_jobs_spec accepts both shapes and rejects malformed input."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bare_list_shape(self):
        path = _write_spec(self.tmp, [
            {'model': 'a.yaml'},
            {'model': 'b.yaml'},
        ])
        jobs, top = load_jobs_spec(path)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(top, {})

    def test_dict_with_jobs_and_top_level_keys(self):
        path = _write_spec(self.tmp, {
            'max_parallel': 5,
            'fail_fast': True,
            'jobs': [{'model': 'a.yaml'}],
        })
        jobs, top = load_jobs_spec(path)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(top['max_parallel'], 5)
        self.assertTrue(top['fail_fast'])

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            load_jobs_spec(os.path.join(self.tmp, 'nope.json'))

    def test_invalid_json_exits(self):
        path = os.path.join(self.tmp, 'bad.json')
        with open(path, 'w') as f:
            f.write('{not: json}')
        with self.assertRaises(SystemExit):
            load_jobs_spec(path)

    def test_unknown_top_level_key_exits(self):
        path = _write_spec(self.tmp, {
            'jobs': [{'model': 'a.yaml'}],
            'bogus': True,
        })
        with self.assertRaises(SystemExit):
            load_jobs_spec(path)

    def test_empty_jobs_list_exits(self):
        path = _write_spec(self.tmp, [])
        with self.assertRaises(SystemExit):
            load_jobs_spec(path)

    def test_missing_jobs_key_exits(self):
        path = _write_spec(self.tmp, {'max_parallel': 3})
        with self.assertRaises(SystemExit):
            load_jobs_spec(path)

    def test_max_parallel_wrong_type_exits(self):
        path = _write_spec(self.tmp, {
            'max_parallel': 'three',
            'jobs': [{'model': 'a.yaml'}],
        })
        with self.assertRaises(SystemExit):
            load_jobs_spec(path)

    def test_max_parallel_negative_exits(self):
        path = _write_spec(self.tmp, {
            'max_parallel': 0,
            'jobs': [{'model': 'a.yaml'}],
        })
        with self.assertRaises(SystemExit):
            load_jobs_spec(path)

    def test_fail_fast_wrong_type_exits(self):
        path = _write_spec(self.tmp, {
            'fail_fast': 'yes',
            'jobs': [{'model': 'a.yaml'}],
        })
        with self.assertRaises(SystemExit):
            load_jobs_spec(path)

    def test_scalar_spec_exits(self):
        path = os.path.join(self.tmp, 'scalar.json')
        with open(path, 'w') as f:
            json.dump(42, f)
        with self.assertRaises(SystemExit):
            load_jobs_spec(path)


class TestJobsValidateJob(unittest.TestCase):
    """_validate_job is the per-job gatekeeper called by load_jobs_spec."""

    def test_accepts_minimal_job(self):
        _validate_job({'model': 'a.yaml'}, 1)  # must not raise

    def test_rejects_non_dict(self):
        with self.assertRaises(SystemExit):
            _validate_job(['not a dict'], 1)

    def test_rejects_missing_model(self):
        with self.assertRaises(SystemExit):
            _validate_job({}, 1)

    def test_rejects_empty_model(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': ''}, 1)

    def test_rejects_non_string_model(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 123}, 1)

    def test_rejects_unknown_key(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'typo': 'x'}, 1)

    def test_rejects_non_string_start_date(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'start_date': 42}, 1)

    def test_rejects_non_list_include(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'include': 'host'}, 1)

    def test_rejects_list_with_non_string_include(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'include': ['ok', 3]}, 1)

    def test_rejects_negative_loops(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'loops': -1}, 1)

    def test_rejects_non_int_loops(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'loops': '3'}, 1)

    def test_rejects_non_bool_force(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'force': 1}, 1)

    def test_accepts_vars_dict_list_string(self):
        _validate_job({'model': 'a.yaml', 'vars': {'k': 'v'}}, 1)
        _validate_job({'model': 'a.yaml', 'vars': ['k=v']}, 1)
        _validate_job({'model': 'a.yaml', 'vars': 'k=v'}, 1)

    def test_rejects_vars_dict_non_string_value(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'vars': {'k': 42}}, 1)

    def test_rejects_vars_list_non_string(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'vars': ['k=v', 5]}, 1)

    def test_rejects_vars_bad_type(self):
        with self.assertRaises(SystemExit):
            _validate_job({'model': 'a.yaml', 'vars': 42}, 1)


# =========================================================================
# TestJobsNormalize — _normalize_vars, _normalize_job
# =========================================================================


class TestJobsNormalize(unittest.TestCase):
    """_normalize_vars turns any accepted shape into `list[str]`."""

    def test_normalize_vars_from_dict(self):
        got = _normalize_vars({'graph': 'cpu', 'host': 'c-0'})
        self.assertIn('graph=cpu', got)
        self.assertIn('host=c-0', got)
        self.assertEqual(len(got), 2)

    def test_normalize_vars_from_list(self):
        self.assertEqual(_normalize_vars(['k=v', 'x=y']), ['k=v', 'x=y'])

    def test_normalize_vars_from_string(self):
        self.assertEqual(_normalize_vars('k=v'), ['k=v'])

    def test_normalize_vars_none(self):
        self.assertEqual(_normalize_vars(None), [])

    def test_normalize_vars_empty_dict(self):
        self.assertEqual(_normalize_vars({}), [])

    def test_normalize_vars_empty_list(self):
        self.assertEqual(_normalize_vars([]), [])


class TestJobsNormalizeJob(unittest.TestCase):
    """_normalize_job inherits CLI defaults and injects _vars."""

    def test_missing_keys_filled_from_defaults(self):
        defaults = {
            'start_date': '2026-01-01',
            'stop_date': '2026-01-02',
            'hostname': 'controller-0',
        }
        job = _normalize_job({'model': 'a.yaml'}, defaults)
        self.assertEqual(job['start_date'], '2026-01-01')
        self.assertEqual(job['stop_date'], '2026-01-02')
        self.assertEqual(job['hostname'], 'controller-0')

    def test_present_keys_not_clobbered(self):
        defaults = {'hostname': 'controller-0'}
        job = _normalize_job(
            {'model': 'a.yaml', 'hostname': 'worker-3'}, defaults)
        self.assertEqual(job['hostname'], 'worker-3')

    def test_none_defaults_not_injected(self):
        defaults = {'start_date': None, 'stop_date': None}
        job = _normalize_job({'model': 'a.yaml'}, defaults)
        self.assertNotIn('start_date', job)
        self.assertNotIn('stop_date', job)

    def test_vars_normalised_into__vars(self):
        job = _normalize_job(
            {'model': 'a.yaml', 'vars': {'graph': 'cpu'}}, {})
        self.assertEqual(job['_vars'], ['graph=cpu'])

    def test_vars_absent_gives_empty_list(self):
        job = _normalize_job({'model': 'a.yaml'}, {})
        self.assertEqual(job['_vars'], [])

    def test_normalize_job_does_not_mutate_input(self):
        original = {'model': 'a.yaml', 'vars': {'g': 'cpu'}}
        _normalize_job(original, {'hostname': 'c-0'})
        self.assertNotIn('_vars', original)
        self.assertNotIn('hostname', original)


# =========================================================================
# TestJobsArgvBuilder — _build_job_argv
# =========================================================================


class TestJobsArgvBuilder(unittest.TestCase):
    """_build_job_argv translates every documented key to argv."""

    def _build(self, job_spec, **kwargs):
        """Shorthand: normalize then build argv."""
        norm = _normalize_job(job_spec, {})
        return _build_job_argv(
            norm,
            defaults={},
            lpmptool_path=kwargs.get('lpmptool_path', '/x/lpmptool'),
            bundle=kwargs.get('bundle', '/some/bundle'),
            computed_output=kwargs.get('computed_output', '/out/dir'),
        )

    def test_minimal_job_has_model_and_bundle_and_output(self):
        argv = self._build({'model': 'a.yaml'})
        # model
        self.assertIn('-m', argv)
        self.assertEqual(argv[argv.index('-m') + 1], 'a.yaml')
        # bundle
        self.assertIn('-b', argv)
        self.assertEqual(argv[argv.index('-b') + 1], '/some/bundle')
        # computed output always wins
        self.assertIn('-o', argv)
        self.assertEqual(argv[argv.index('-o') + 1], '/out/dir')

    def test_start_and_stop_date(self):
        argv = self._build({
            'model': 'a.yaml',
            'start_date': '2026-01-01T00:00:00',
            'stop_date': '2026-01-02T00:00:00',
        })
        self.assertIn('-s', argv)
        self.assertEqual(argv[argv.index('-s') + 1], '2026-01-01T00:00:00')
        self.assertIn('-e', argv)
        self.assertEqual(argv[argv.index('-e') + 1], '2026-01-02T00:00:00')

    def test_hostname_and_host_flags(self):
        argv = self._build({
            'model': 'a.yaml',
            'hostname': 'controller-1',
            'host': 'worker-2',
        })
        self.assertIn('--hostname', argv)
        self.assertEqual(argv[argv.index('--hostname') + 1], 'controller-1')
        self.assertIn('--host', argv)
        self.assertEqual(argv[argv.index('--host') + 1], 'worker-2')

    def test_include_and_exclude_lists(self):
        argv = self._build({
            'model': 'a.yaml',
            'include': ['a', 'b', 'c'],
        })
        i = argv.index('--include')
        self.assertEqual(argv[i + 1:i + 4], ['a', 'b', 'c'])

        argv = self._build({
            'model': 'a.yaml',
            'exclude': ['x', 'y'],
        })
        i = argv.index('--exclude')
        self.assertEqual(argv[i + 1:i + 3], ['x', 'y'])

    def test_vars_dict_becomes_repeated_var_flags(self):
        argv = self._build({
            'model': 'a.yaml',
            'vars': {'graph': 'cpu', 'host': 'c-0'},
        })
        vars_flag_positions = [
            i for i, a in enumerate(argv) if a == '--var']
        self.assertEqual(len(vars_flag_positions), 2)
        emitted = {argv[i + 1] for i in vars_flag_positions}
        self.assertIn('graph=cpu', emitted)
        self.assertIn('host=c-0', emitted)

    def test_logs_dir_and_lab(self):
        argv = self._build({
            'model': 'a.yaml',
            'logs_dir': 'custom/logs',
            'lab': 'galaxy',
        })
        self.assertIn('-l', argv)
        self.assertEqual(argv[argv.index('-l') + 1], 'custom/logs')
        self.assertIn('--lab', argv)
        self.assertEqual(argv[argv.index('--lab') + 1], 'galaxy')

    def test_loops_and_progress_and_force(self):
        argv = self._build({
            'model': 'a.yaml',
            'loops': 5,
            'progress': 'dots',
            'force': True,
        })
        self.assertIn('-n', argv)
        self.assertEqual(argv[argv.index('-n') + 1], '5')
        self.assertIn('--progress', argv)
        self.assertEqual(argv[argv.index('--progress') + 1], 'dots')
        self.assertIn('--force', argv)

    def test_force_false_not_emitted(self):
        argv = self._build({'model': 'a.yaml', 'force': False})
        self.assertNotIn('--force', argv)

    def test_extra_args_appended_last(self):
        argv = self._build({
            'model': 'a.yaml',
            'extra_args': ['--foo', 'bar', '-x'],
        })
        # Extra args are appended verbatim after -o computed_output.
        self.assertEqual(argv[-3:], ['--foo', 'bar', '-x'])

    def test_no_bundle_omits_b_flag(self):
        argv = self._build({'model': 'a.yaml'}, bundle=None)
        self.assertNotIn('-b', argv)

    def test_computed_output_overrides_job_output(self):
        argv = self._build({
            'model': 'a.yaml',
            'output': '/should/be/ignored',
        }, computed_output='/parent/computed')
        self.assertEqual(argv[argv.index('-o') + 1], '/parent/computed')


# =========================================================================
# TestJobsPrecomputeOutputs — _precompute_job_outputs
# =========================================================================


class TestJobsPrecomputeOutputs(unittest.TestCase):
    """_precompute_job_outputs assigns a unique -o value per job."""

    def _run(self, jobs, args=None, ts=None):
        norm = [_normalize_job(j, {}) for j in jobs]
        args = args or _make_args()
        ts = ts or datetime(2026, 7, 3, 18, 0, 0)
        root = _precompute_job_outputs(norm, args, ts)
        return norm, root

    def test_distinct_models_do_not_collide(self):
        norm, _ = self._run([
            {'model': 'a.yaml'},
            {'model': 'b.yaml'},
        ])
        self.assertNotEqual(norm[0]['_output_dir'], norm[1]['_output_dir'])
        # Distinct model base names are in the paths.
        self.assertIn('20260703_180000_a', norm[0]['_output_dir'])
        self.assertIn('20260703_180000_b', norm[1]['_output_dir'])

    def test_same_model_gets_run_suffix(self):
        norm, _ = self._run([
            {'model': 'same.yaml'},
            {'model': 'same.yaml'},
            {'model': 'same.yaml'},
        ])
        # First occurrence keeps the natural name.
        self.assertTrue(norm[0]['_output_dir'].endswith('_same'))
        # Subsequent duplicates get _runN suffix.
        self.assertTrue(norm[1]['_output_dir'].endswith('_same_run2'))
        self.assertTrue(norm[2]['_output_dir'].endswith('_same_run3'))

    def test_explicit_output_root_wins(self):
        args = _make_args(output='/custom/root', bundle_name='/')
        norm, root = self._run([{'model': 'a.yaml'}], args=args)
        self.assertEqual(root, '/custom/root')
        self.assertTrue(
            norm[0]['_output_dir'].startswith('/custom/root/lpmp_lab/'))

    def test_bundle_name_used_when_no_output(self):
        args = _make_args(output=None, bundle_name='/bun/dle', lab='xy')
        norm, root = self._run([{'model': 'a.yaml'}], args=args)
        self.assertEqual(root, '/bun/dle')
        self.assertIn('/bun/dle/lpmp_xy/', norm[0]['_output_dir'])

    def test_lab_from_job_overrides_args(self):
        # Job entry provides its own `lab`, which participates in the
        # collision key, so two jobs with different labs never clash.
        norm, _ = self._run([
            {'model': 'a.yaml', 'lab': 'lab-a'},
            {'model': 'a.yaml', 'lab': 'lab-b'},
        ])
        self.assertIn('lpmp_lab-a', norm[0]['_output_dir'])
        self.assertIn('lpmp_lab-b', norm[1]['_output_dir'])
        # Same model, distinct labs -> no _run suffix.
        self.assertFalse(norm[0]['_output_dir'].endswith('_run2'))
        self.assertFalse(norm[1]['_output_dir'].endswith('_run2'))


if __name__ == '__main__':
    unittest.main()


# =========================================================================
# Phase 2: TestJobsMaxParallelResolve, TestJobsFailFastResolve,
#          TestJobsFdPreflight
# =========================================================================


class TestJobsMaxParallelResolve(unittest.TestCase):
    """CLI > spec > default of 3."""

    def test_cli_value_wins(self):
        args = _make_args(max_parallel=7)
        self.assertEqual(_resolve_max_parallel(args, {'max_parallel': 4}), 7)

    def test_spec_wins_when_cli_none(self):
        args = _make_args(max_parallel=None)
        self.assertEqual(_resolve_max_parallel(args, {'max_parallel': 4}), 4)

    def test_default_when_neither_set(self):
        args = _make_args(max_parallel=None)
        self.assertEqual(_resolve_max_parallel(args, {}),
                         DEFAULT_MAX_PARALLEL)


class TestJobsFailFastResolve(unittest.TestCase):
    """CLI truthy wins; else spec value; else default off."""

    def test_cli_true_wins(self):
        args = _make_args(fail_fast=True)
        self.assertTrue(_resolve_fail_fast(args, {'fail_fast': False}))

    def test_spec_provides_default_when_cli_false(self):
        args = _make_args(fail_fast=False)
        self.assertTrue(_resolve_fail_fast(args, {'fail_fast': True}))

    def test_off_by_default(self):
        args = _make_args(fail_fast=False)
        self.assertFalse(_resolve_fail_fast(args, {}))


class TestJobsFdPreflight(unittest.TestCase):
    """RLIMIT_NOFILE inspection, raise, clamp, cap."""

    def test_soft_limit_sufficient_returns_unchanged(self):
        with patch('lpmp_jobs.resource.getrlimit',
                   return_value=(4096, 8192)), \
                patch('lpmp_jobs.resource.setrlimit') as mock_set:
            got = _preflight_fd_check(4, force_parallel=False)
        self.assertEqual(got, 4)
        # No raise attempted when soft limit is already generous.
        mock_set.assert_not_called()

    def test_raises_soft_limit_when_below_budget(self):
        with patch('lpmp_jobs.resource.getrlimit',
                   return_value=(64, 4096)), \
                patch('lpmp_jobs.resource.setrlimit') as mock_set:
            got = _preflight_fd_check(8, force_parallel=False)
        self.assertEqual(got, 8)
        mock_set.assert_called_once()

    def test_clamps_when_setrlimit_fails(self):
        with patch('lpmp_jobs.resource.getrlimit',
                   return_value=(64, 64)), \
                patch('lpmp_jobs.resource.setrlimit',
                      side_effect=OSError):
            got = _preflight_fd_check(20, force_parallel=False)
        # Budget: max_parallel*10 + 32 must fit into soft.
        # (64 - 32) // 10 = 3.
        self.assertLessEqual(got, 3)
        self.assertGreaterEqual(got, 1)

    def test_absolute_cap_enforced_without_force(self):
        with patch('lpmp_jobs.resource.getrlimit',
                   return_value=(65536, 65536)):
            got = _preflight_fd_check(500, force_parallel=False)
        self.assertEqual(got, ABSOLUTE_MAX_PARALLEL)

    def test_force_parallel_bypasses_cap(self):
        with patch('lpmp_jobs.resource.getrlimit',
                   return_value=(65536, 65536)):
            got = _preflight_fd_check(500, force_parallel=True)
        self.assertEqual(got, 500)

    def test_resource_module_error_returns_input(self):
        with patch('lpmp_jobs.resource.getrlimit',
                   side_effect=OSError):
            got = _preflight_fd_check(4, force_parallel=False)
        self.assertEqual(got, 4)


# =========================================================================
# Phase 3: TestJobsWorkerPool — _WorkerPool with mocked subprocess.Popen
# =========================================================================

class _FakePopen:
    """Test double for subprocess.Popen.

    Reports a configurable exit code after `poll_calls_until_exit`
    invocations of poll(). Records `terminate()` and `kill()` calls
    so shutdown tests can assert them.
    """
    def __init__(self, argv, exit_code=0, poll_calls_until_exit=1,
                 stdout=None, **_kwargs):
        self.argv = argv
        self.stdout_fd = stdout
        self._exit_code = exit_code
        self._polls_left = poll_calls_until_exit
        self.terminate_calls = 0
        self.kill_calls = 0
        self._terminated = False

    def poll(self):
        if self._polls_left > 0:
            self._polls_left -= 1
            return None
        # If terminate was called and no natural exit yet, emulate a
        # signal-driven negative rc so the pool categorizes it correctly.
        if self._terminated and self._exit_code >= 0:
            return -signal.SIGTERM
        return self._exit_code

    def terminate(self):
        self.terminate_calls += 1
        self._terminated = True
        # A terminated proc exits on the next poll.
        self._polls_left = 0

    def kill(self):
        self.kill_calls += 1
        self._terminated = True
        self._polls_left = 0


def _pool_jobs(count, model='m.yaml'):
    """Build a list of job dicts ready for the pool to consume."""
    jobs = []
    for i in range(count):
        jobs.append({
            'model': model,
            '_idx': i + 1,
            '_state': 'pending',
            '_argv': ['python3', 'fake_lpmptool', '-m', model],
        })
    return jobs


class TestJobsWorkerPool(unittest.TestCase):
    """_WorkerPool dispatch order, concurrency cap, and lifecycle."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Neutralise the 100ms poll cadence so tests finish fast.
        self._sleep_patch = patch('lpmp_jobs.time.sleep', lambda _s: None)
        self._sleep_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_returns_all_jobs_in_completion_order(self):
        jobs = _pool_jobs(3)
        pool = _WorkerPool(jobs, max_parallel=2, console_log_dir=self.tmp)
        with patch('lpmp_jobs.subprocess.Popen',
                   side_effect=lambda argv, **kw: _FakePopen(argv, **kw)):
            order = pool.run()
        # All three finish; equal durations keep FIFO order.
        self.assertEqual(order, [0, 1, 2])
        for j in jobs:
            self.assertEqual(j['_state'], 'passed')

    def test_concurrency_cap_never_exceeded(self):
        jobs = _pool_jobs(8)
        pool = _WorkerPool(jobs, max_parallel=3, console_log_dir=self.tmp)
        snapshots = []
        real_dispatch = pool._dispatch_next

        def instrumented_dispatch():
            real_dispatch()
            snapshots.append(len(pool.running))

        pool._dispatch_next = instrumented_dispatch
        with patch('lpmp_jobs.subprocess.Popen',
                   side_effect=lambda argv, **kw: _FakePopen(argv, **kw)):
            pool.run()
        self.assertTrue(all(n <= 3 for n in snapshots),
                        f"cap violated: max seen = {max(snapshots)}")

    def test_fail_fast_aborts_remaining(self):
        jobs = _pool_jobs(4)
        pool = _WorkerPool(jobs, max_parallel=2, fail_fast=True,
                           console_log_dir=self.tmp)
        # Fake: first job fails, others would pass.
        exit_codes = iter([2, 0, 0, 0])

        def factory(argv, **kw):
            return _FakePopen(argv, exit_code=next(exit_codes), **kw)

        with patch('lpmp_jobs.subprocess.Popen', side_effect=factory):
            pool.run()
        self.assertTrue(pool.abort_flag)
        # First job is `failed`; at least one of the trailing jobs
        # should never have transitioned to `passed`.
        self.assertEqual(jobs[0]['_state'], 'failed')
        trailing_passed = sum(1 for j in jobs[1:] if j['_state'] == 'passed')
        self.assertLess(trailing_passed, 3)

    def test_console_log_file_created_and_parent_closed(self):
        jobs = _pool_jobs(1, model='mymodel.yaml')

        captured_fd = {}

        def factory(argv, stdout=None, **kw):
            # Record the fd handed to Popen so we can assert on it.
            captured_fd['fd'] = stdout
            return _FakePopen(argv, stdout=stdout, **kw)

        pool = _WorkerPool(jobs, max_parallel=1,
                           console_log_dir=self.tmp)
        with patch('lpmp_jobs.subprocess.Popen', side_effect=factory):
            pool.run()
        # Log path recorded on the job, file exists on disk.
        self.assertTrue(jobs[0]['_log_path'].endswith(
            '01_mymodel.console.log'))
        self.assertTrue(os.path.exists(jobs[0]['_log_path']))
        # Parent closed its copy of the fd immediately after Popen.
        self.assertTrue(captured_fd['fd'].closed)

    def test_popen_oserror_marks_job_failed(self):
        jobs = _pool_jobs(1)

        def factory(*_a, **_kw):
            raise OSError("simulated ENOENT")

        pool = _WorkerPool(jobs, max_parallel=1,
                           console_log_dir=self.tmp)
        with patch('lpmp_jobs.subprocess.Popen', side_effect=factory):
            pool.run()
        self.assertEqual(jobs[0]['_state'], 'failed')
        self.assertEqual(jobs[0]['_exit_code'], -1)
        self.assertIn('Popen failed', jobs[0].get('_error', ''))

    def test_request_shutdown_terminates_running(self):
        jobs = _pool_jobs(2)
        pool = _WorkerPool(jobs, max_parallel=2, console_log_dir=self.tmp)
        fakes = []

        def factory(argv, **kw):
            f = _FakePopen(argv, poll_calls_until_exit=99, **kw)
            fakes.append(f)
            return f

        with patch('lpmp_jobs.subprocess.Popen', side_effect=factory):
            # Manually drive one cycle: dispatch, then shutdown, then
            # let the pool run out.
            pool._dispatch_next()
            pool._dispatch_next()
            self.assertEqual(len(pool.running), 2)
            pool.request_shutdown(signal.SIGTERM)
            # Terminate was called on both procs.
            self.assertTrue(all(f.terminate_calls == 1 for f in fakes))
            # abort_flag is set, abort_signal recorded.
            self.assertTrue(pool.abort_flag)
            self.assertEqual(pool.abort_signal, signal.SIGTERM)
            # Idempotent — second call is a no-op.
            pool.request_shutdown(signal.SIGTERM)
            self.assertTrue(all(f.terminate_calls == 1 for f in fakes))

    def test_escalate_after_deadline_calls_kill(self):
        jobs = _pool_jobs(1)
        pool = _WorkerPool(jobs, max_parallel=1, console_log_dir=self.tmp)
        fakes = []

        def factory(argv, **kw):
            f = _FakePopen(argv, poll_calls_until_exit=99, **kw)
            fakes.append(f)
            return f

        with patch('lpmp_jobs.subprocess.Popen', side_effect=factory):
            pool._dispatch_next()
            pool.request_shutdown(signal.SIGTERM)
            # Force the deadline into the past.
            pool.abort_deadline = 0
            pool._escalate_if_deadline_reached()
        self.assertEqual(fakes[0].kill_calls, 1)

    def test_escalate_before_deadline_is_noop(self):
        jobs = _pool_jobs(1)
        pool = _WorkerPool(jobs, max_parallel=1, console_log_dir=self.tmp)
        fakes = []

        def factory(argv, **kw):
            f = _FakePopen(argv, poll_calls_until_exit=99, **kw)
            fakes.append(f)
            return f

        with patch('lpmp_jobs.subprocess.Popen', side_effect=factory):
            pool._dispatch_next()
            pool.request_shutdown(signal.SIGTERM)
            # Deadline still in the future -> no kill().
            pool.abort_deadline = 9999999999
            pool._escalate_if_deadline_reached()
        self.assertEqual(fakes[0].kill_calls, 0)

    def test_empty_pool_returns_immediately(self):
        pool = _WorkerPool([], max_parallel=3, console_log_dir=self.tmp)
        with patch('lpmp_jobs.subprocess.Popen',
                   side_effect=RuntimeError('should not be called')):
            order = pool.run()
        self.assertEqual(order, [])

    def test_no_log_dir_uses_devnull(self):
        # When console_log_dir is None, the pool should still run and
        # simply skip log creation. stdout arg to Popen ends up as
        # subprocess.DEVNULL, which is the integer -3 in CPython, but
        # what matters here is that no OSError is raised and jobs pass.
        jobs = _pool_jobs(1)
        pool = _WorkerPool(jobs, max_parallel=1, console_log_dir=None)
        with patch('lpmp_jobs.subprocess.Popen',
                   side_effect=lambda argv, **kw: _FakePopen(argv, **kw)):
            pool.run()
        self.assertEqual(jobs[0]['_state'], 'passed')
        self.assertIsNone(jobs[0]['_log_path'])


# =========================================================================
# Phase 4: TestJobsRunJobsEndToEnd — run_jobs orchestration
# =========================================================================


class TestJobsRunJobsEndToEnd(unittest.TestCase):
    """run_jobs orchestrates spec load, precompute, pool, and exit code."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Neutralise the poll delay.
        self._sleep_patch = patch('lpmp_jobs.time.sleep', lambda _s: None)
        self._sleep_patch.start()
        # Skip the real FD pre-flight (test-machine may have low limits).
        self._preflight_patch = patch(
            'lpmp_jobs._preflight_fd_check',
            side_effect=lambda mp, force_parallel=False: mp)
        self._preflight_patch.start()
        # Signal handlers: swallow them so unittest doesn't inherit our
        # SIGINT redirect between tests.
        self._signal_patch = patch(
            'lpmp_jobs.signal.signal', MagicMock())
        self._signal_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()
        self._preflight_patch.stop()
        self._signal_patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_spec(self, entries, top_level=None):
        payload = {'jobs': entries}
        if top_level:
            payload.update(top_level)
        return _write_spec(self.tmp, payload)

    def _run(self, spec_path, args_overrides, exit_codes):
        """Invoke run_jobs with a mocked Popen returning `exit_codes`."""
        args = _make_args(
            jobs=spec_path,
            output=os.path.join(self.tmp, 'out'),
            bundle=self.tmp,
            bundle_name=self.tmp,
            **args_overrides,
        )
        exit_iter = iter(exit_codes)

        def factory(argv, **kw):
            return _FakePopen(argv, exit_code=next(exit_iter), **kw)

        stdout_buf = StringIO()
        with patch('lpmp_jobs.subprocess.Popen', side_effect=factory), \
                patch('sys.stdout', stdout_buf), \
                self.assertRaises(SystemExit) as cm:
            run_jobs(args)
        return cm.exception.code, stdout_buf.getvalue()

    def test_all_pass_exits_zero(self):
        spec = self._write_spec([
            {'model': 'a.yaml'},
            {'model': 'b.yaml'},
            {'model': 'c.yaml'},
        ])
        code, out = self._run(spec, {'max_parallel': 2}, [0, 0, 0])
        self.assertEqual(code, 0)
        self.assertIn('3 passed', out)

    def test_worst_exit_code_propagates(self):
        spec = self._write_spec([
            {'model': 'a.yaml'},
            {'model': 'b.yaml'},
        ])
        code, out = self._run(spec, {'max_parallel': 2}, [0, 3])
        self.assertEqual(code, 3)
        self.assertIn('1 failed', out)

    def test_failure_detail_lists_console_log(self):
        spec = self._write_spec([{'model': 'boom.yaml'}])
        code, out = self._run(spec, {'max_parallel': 1}, [7])
        self.assertEqual(code, 7)
        self.assertIn('Failure detail', out)
        self.assertIn('boom.yaml', out)
        self.assertIn('.console.log', out)

    def test_fail_fast_from_cli_aborts(self):
        spec = self._write_spec([
            {'model': 'a.yaml'},
            {'model': 'b.yaml'},
            {'model': 'c.yaml'},
            {'model': 'd.yaml'},
        ])
        # Only two exit codes will actually be consumed because
        # fail_fast aborts after the first failure — but we provide
        # extras defensively in case max_parallel > 1 lets an in-flight
        # sibling also record its exit.
        code, out = self._run(
            spec, {'max_parallel': 2, 'fail_fast': True},
            [1, 0, 0, 0])
        self.assertNotEqual(code, 0)
        # Summary lists at least one skipped job (never dispatched).
        self.assertRegex(out, r'\d+ skipped')

    def test_max_parallel_from_spec_honoured_when_cli_absent(self):
        spec = self._write_spec([
            {'model': 'a.yaml'},
            {'model': 'b.yaml'},
            {'model': 'c.yaml'},
        ], top_level={'max_parallel': 1})
        code, out = self._run(
            spec, {'max_parallel': None}, [0, 0, 0])
        self.assertEqual(code, 0)
        # startup line should echo the resolved max_parallel.
        self.assertIn('max_parallel=1', out)

    def test_signal_handlers_installed_and_restored(self):
        spec = self._write_spec([{'model': 'a.yaml'}])
        # signal.signal is already mocked in setUp; unpack and inspect
        # the calls after run_jobs.
        exit_iter = iter([0])

        def factory(argv, **kw):
            return _FakePopen(argv, exit_code=next(exit_iter), **kw)

        args = _make_args(
            jobs=spec,
            output=os.path.join(self.tmp, 'out'),
            bundle=self.tmp,
            bundle_name=self.tmp,
        )
        with patch('lpmp_jobs.subprocess.Popen', side_effect=factory), \
                patch('sys.stdout', new_callable=StringIO), \
                self.assertRaises(SystemExit):
            run_jobs(args)
        # Four signal.signal calls total: install SIGINT+SIGTERM, then
        # restore SIGINT+SIGTERM.
        from lpmp_jobs import signal as jobs_signal
        install_signals = [c.args[0] for c in jobs_signal.signal.call_args_list]
        self.assertIn(signal.SIGINT, install_signals)
        self.assertIn(signal.SIGTERM, install_signals)
        # At least 4 calls (2 install + 2 restore)
        self.assertGreaterEqual(len(install_signals), 4)
