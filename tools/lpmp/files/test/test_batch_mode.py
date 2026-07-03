#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""
Tests for lpmp_batch.py (batch mode).

Covers spec loading, block classification, regex build, file grouping,
single-pass reader, output writer, and full run_batch orchestration.
Bundle regression tests run against a real collect bundle when
LPMP_TEST_BUNDLE is set (via run_tests.py --bundle).
"""

import argparse
from datetime import datetime
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

import lpmp_batch                                             # noqa: E402
from lpmp_batch import _build_file_groups                     # noqa: E402
from lpmp_batch import _build_target_regex                    # noqa: E402
from lpmp_batch import _check_duplicate_runs                  # noqa: E402
from lpmp_batch import _classify_all_models                   # noqa: E402
from lpmp_batch import _classify_model_blocks                 # noqa: E402
from lpmp_batch import _load_all_models                       # noqa: E402
from lpmp_batch import _resolve_model_path                    # noqa: E402
from lpmp_batch import _resolve_run_dates                     # noqa: E402
from lpmp_batch import _run_base_dir                          # noqa: E402
from lpmp_batch import _single_pass_read                      # noqa: E402
from lpmp_batch import _write_profile_text                    # noqa: E402
from lpmp_batch import _write_run_output                      # noqa: E402
from lpmp_batch import load_batch_spec                        # noqa: E402
from lpmp_batch import run_batch                              # noqa: E402
from test_base import LPMPTestBase                            # noqa: E402

# Bundle regression opt-in (same convention as test_main_execution.py)
BUNDLE_PATH = os.environ.get('LPMP_TEST_BUNDLE')
BUNDLE_AVAILABLE = os.path.isdir(BUNDLE_PATH) if BUNDLE_PATH else False


def _capture_prints():
    """Return a (captured_list, capture_fn) pair for use with
    patch('builtins.print', side_effect=capture_fn). Mirrors the
    pattern used in test_lpmp_output.py and test_window_model.py.
    Captures both stdout and stderr prints because `print(..., file=...)`
    still routes through builtins.print.
    """
    captured = []

    def capture(*args, **kwargs):
        captured.append(' '.join(str(a) for a in args))

    return captured, capture


def _make_args(**overrides):
    """Build a minimal argparse.Namespace shaped like the real one."""
    ns = argparse.Namespace(
        batch=None,
        bundle='/',
        bundle_name='/',
        lab='lab',
        lab_name='lab',
        output=None,
        logs_dir='var/log',
        max_log_length=180,
        verbose=0,
        include=None,
        exclude=None,
        model_file='model.yaml',
        hostname='controller-0',
        # Disable the per-host progress thread by default in tests
        # so no dots leak to real stdout while other output is
        # captured. Tests can override with progress='dots' if they
        # want to exercise the progress path.
        progress='none',
        start_date=None,
        stop_date=None,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


# =========================================================================
# Phase 2: Pure-function unit tests
# =========================================================================


class TestBatchSpecLoading(LPMPTestBase):
    """load_batch_spec and _resolve_model_path validation branches."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Silence expected stderr writes from the sys.exit error paths.
        # Matches the peer convention used in test_lpmp.py and
        # test_timeline_models.py where `patch('builtins.print')`
        # swallows noise from routine error paths.
        self._print_patcher = patch('builtins.print')
        self._print_patcher.start()

    def tearDown(self):
        self._print_patcher.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_spec(self, obj):
        p = os.path.join(self.tmp, 'spec.json')
        with open(p, 'w') as f:
            json.dump(obj, f)
        return p

    def test_valid_spec_parses(self):
        p = self._write_spec({
            'runs': [
                {'model': 'x.yaml',
                 'start_date': '2026-02-25T13:35:00',
                 'stop_date': '2026-02-25T13:38:00'}
            ]
        })
        runs = load_batch_spec(p)
        self.assertEqual(len(runs), 1)
        self.assertIsInstance(runs[0]['_start'], datetime)
        self.assertIsInstance(runs[0]['_stop'], datetime)

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit) as cm:
            load_batch_spec(os.path.join(self.tmp, 'nonexistent.json'))
        self.assertEqual(cm.exception.code, 1)

    def test_invalid_json_exits(self):
        p = os.path.join(self.tmp, 'bad.json')
        with open(p, 'w') as f:
            f.write('{not valid json')
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_missing_runs_array_exits(self):
        p = self._write_spec({'nothing': True})
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_runs_not_list_exits(self):
        p = self._write_spec({'runs': 'not a list'})
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_missing_model_key_exits(self):
        p = self._write_spec({'runs': [
            {'start_date': '2026-01-01T00:00:00', 'stop_date': '2026-01-01T01:00:00'}
        ]})
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_missing_start_date_is_optional(self):
        """start_date is optional; run loads with _start=None."""
        p = self._write_spec({'runs': [
            {'model': 'x.yaml', 'stop_date': '2026-01-01T01:00:00'}
        ]})
        runs = load_batch_spec(p)
        self.assertIsNone(runs[0]['_start'])
        self.assertIsInstance(runs[0]['_stop'], datetime)

    def test_missing_stop_date_is_optional(self):
        """stop_date is optional; run loads with _stop=None."""
        p = self._write_spec({'runs': [
            {'model': 'x.yaml', 'start_date': '2026-01-01T00:00:00'}
        ]})
        runs = load_batch_spec(p)
        self.assertIsInstance(runs[0]['_start'], datetime)
        self.assertIsNone(runs[0]['_stop'])

    def test_both_dates_optional(self):
        """Both start_date and stop_date omitted; run loads with both None."""
        p = self._write_spec({'runs': [{'model': 'x.yaml'}]})
        runs = load_batch_spec(p)
        self.assertIsNone(runs[0]['_start'])
        self.assertIsNone(runs[0]['_stop'])

    def test_bare_list_of_runs_accepted(self):
        """Top-level list `[{"model": ...}, ...]` is accepted."""
        p = self._write_spec([{'model': 'a.yaml'}, {'model': 'b.yaml'}])
        runs = load_batch_spec(p)
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]['model'], 'a.yaml')
        self.assertEqual(runs[1]['model'], 'b.yaml')

    def test_bad_iso_date_exits(self):
        p = self._write_spec({'runs': [
            {'model': 'x.yaml',
             'start_date': 'not-a-date',
             'stop_date': '2026-01-01T01:00:00'}
        ]})
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_start_date_with_milliseconds_exits(self):
        """Sub-second precision in start_date is rejected: the output
        directory naming only has whole-second resolution, so two
        dates differing only by milliseconds would collide on disk.
        """
        p = self._write_spec({'runs': [
            {'model': 'x.yaml',
             'start_date': '2026-01-01T00:00:00.500',
             'stop_date': '2026-01-01T01:00:00'}
        ]})
        with self.assertRaises(SystemExit) as cm:
            load_batch_spec(p)
        self.assertEqual(cm.exception.code, 1)

    def test_stop_date_with_microseconds_exits(self):
        p = self._write_spec({'runs': [
            {'model': 'x.yaml',
             'start_date': '2026-01-01T00:00:00',
             'stop_date': '2026-01-01T01:00:00.123456'}
        ]})
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_whole_second_date_with_zero_fraction_accepted(self):
        """A date with an explicit '.000' fraction is whole-second
        (microsecond == 0) and must still be accepted.
        """
        p = self._write_spec({'runs': [
            {'model': 'x.yaml',
             'start_date': '2026-01-01T00:00:00.000',
             'stop_date': '2026-01-01T01:00:00'}
        ]})
        runs = load_batch_spec(p)
        self.assertEqual(runs[0]['_start'].microsecond, 0)

    def test_stop_before_start_exits(self):
        p = self._write_spec({'runs': [
            {'model': 'x.yaml',
             'start_date': '2026-01-01T01:00:00',
             'stop_date': '2026-01-01T00:00:00'}
        ]})
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_stop_equal_start_exits(self):
        p = self._write_spec({'runs': [
            {'model': 'x.yaml',
             'start_date': '2026-01-01T00:00:00',
             'stop_date': '2026-01-01T00:00:00'}
        ]})
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_empty_runs_array_exits(self):
        p = self._write_spec({'runs': []})
        with self.assertRaises(SystemExit):
            load_batch_spec(p)

    def test_repeat_model_with_different_windows_loads_fine(self):
        """A model may appear more than once in a batch spec as long
        as each occurrence has a distinct window. `load_batch_spec`
        itself doesn't reject repeats — that's checked later, after
        date resolution, by `_check_duplicate_runs`.
        """
        p = self._write_spec({'runs': [
            {'model': 'x.yaml',
             'start_date': '2026-01-01T00:00:00',
             'stop_date': '2026-01-01T01:00:00'},
            {'model': 'x.yaml',
             'start_date': '2026-01-01T02:00:00',
             'stop_date': '2026-01-01T03:00:00'},
        ]})
        runs = load_batch_spec(p)
        self.assertEqual(len(runs), 2)

    def test_distinct_models_do_not_exit(self):
        p = self._write_spec({'runs': [
            {'model': 'x.yaml'},
            {'model': 'y.yaml'},
        ]})
        runs = load_batch_spec(p)
        self.assertEqual(len(runs), 2)

    def test_check_duplicate_runs_same_model_same_window_exits(self):
        """Exact (model, start, stop) repeat is rejected."""
        runs = [
            {'model': 'x.yaml',
             '_start': datetime(2026, 1, 1, 0, 0, 0),
             '_stop': datetime(2026, 1, 1, 1, 0, 0)},
            {'model': 'x.yaml',
             '_start': datetime(2026, 1, 1, 0, 0, 0),
             '_stop': datetime(2026, 1, 1, 1, 0, 0)},
        ]
        with self.assertRaises(SystemExit) as cm:
            _check_duplicate_runs(runs)
        self.assertEqual(cm.exception.code, 1)

    def test_check_duplicate_runs_same_model_different_window_ok(self):
        """Same model with a different resolved window is fine — this
        is the whole point of encoding the window in the run's output
        directory name.
        """
        runs = [
            {'model': 'x.yaml',
             '_start': datetime(2026, 1, 1, 0, 0, 0),
             '_stop': datetime(2026, 1, 1, 1, 0, 0)},
            {'model': 'x.yaml',
             '_start': datetime(2026, 1, 1, 1, 0, 0),
             '_stop': datetime(2026, 1, 1, 2, 0, 0)},
        ]
        _check_duplicate_runs(runs)  # must not raise

    def test_check_duplicate_runs_same_model_both_unbounded_exits(self):
        """Same model with no start/stop on both occurrences is an
        exact-window duplicate (both unbounded) and must be rejected.
        """
        runs = [
            {'model': 'x.yaml', '_start': None, '_stop': None},
            {'model': 'x.yaml', '_start': None, '_stop': None},
        ]
        with self.assertRaises(SystemExit):
            _check_duplicate_runs(runs)

    def test_check_duplicate_runs_different_models_same_window_ok(self):
        runs = [
            {'model': 'x.yaml',
             '_start': datetime(2026, 1, 1, 0, 0, 0),
             '_stop': datetime(2026, 1, 1, 1, 0, 0)},
            {'model': 'y.yaml',
             '_start': datetime(2026, 1, 1, 0, 0, 0),
             '_stop': datetime(2026, 1, 1, 1, 0, 0)},
        ]
        _check_duplicate_runs(runs)  # must not raise

    def test_resolve_run_dates_cli_milliseconds_exits(self):
        """`--start-date`/`--stop-date` share `_parse_iso` with spec
        dates, so a sub-second CLI date is rejected the same way.
        """
        runs = [{'model': 'x.yaml', '_start': None, '_stop': None}]
        models = {'x.yaml': ([], {}, '/fake/x.yaml')}
        args = _make_args(start_date='2026-01-01T00:00:00.250',
                          stop_date='2026-01-01T01:00:00')
        with self.assertRaises(SystemExit):
            _resolve_run_dates(runs, models, args)

    def test_resolve_run_dates_model_settings_milliseconds_exits(self):
        """A model's own settings.start_date/stop_date go through the
        same `_parse_iso` sub-second check.
        """
        runs = [{'model': 'x.yaml', '_start': None, '_stop': None}]
        models = {'x.yaml': (
            [], {'start_date': '2026-01-01T00:00:00.999'}, '/fake/x.yaml'
        )}
        args = _make_args()
        with self.assertRaises(SystemExit):
            _resolve_run_dates(runs, models, args)

    def test_resolve_model_path_absolute(self):
        p = os.path.join(self.tmp, 'model.yaml')
        with open(p, 'w') as f:
            f.write('description: Test model.\nblocks: []\n')
        self.assertEqual(_resolve_model_path(p), p)

    def test_resolve_model_path_cwd(self):
        original_cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            p = 'model.yaml'
            with open(p, 'w') as f:
                f.write('description: Test model.\nblocks: []\n')
            resolved = _resolve_model_path(p)
            self.assertTrue(os.path.isabs(resolved))
            self.assertTrue(resolved.endswith('model.yaml'))
        finally:
            os.chdir(original_cwd)

    def test_resolve_model_path_search_path(self):
        # Uses a real shipped model resolved via find_model_file
        resolved = _resolve_model_path('mtce_timeline_model.yaml')
        self.assertTrue(os.path.exists(resolved))

    def test_resolve_model_path_not_found_exits(self):
        with self.assertRaises(SystemExit):
            _resolve_model_path('this_model_should_not_exist_xyzzy.yaml')


class TestBatchClassifyAndRegex(unittest.TestCase):
    """_classify_model_blocks, _classify_all_models, and
    _build_target_regex.
    """

    def test_classify_keeps_timeline(self):
        blocks = [
            {'label': 'A', 'timeline': ['x']},
            {'label': 'B', 'timeline': ['y']},
        ]
        kept = _classify_model_blocks(blocks, 'm.yaml')
        self.assertEqual(len(kept), 2)

    def test_classify_keeps_window(self):
        blocks = [
            {'label': 'W', 'window': True, 'file': '*.log'},
        ]
        kept = _classify_model_blocks(blocks, 'm.yaml')
        self.assertEqual(len(kept), 1)

    def test_classify_keeps_timeline_and_window_mixed(self):
        blocks = [
            {'label': 'T', 'timeline': ['x']},
            {'label': 'W', 'window': True, 'file': '*.log'},
        ]
        kept = _classify_model_blocks(blocks, 'm.yaml')
        self.assertEqual(len(kept), 2)

    def test_classify_warns_once_and_skips_pair_model(self):
        """A pair-only model with multiple pair blocks still prints
        exactly one warning line for the whole model, not one per
        block.
        """
        blocks = [
            {'label': 'P1', 'start': 's1', 'stop': 'e1'},
            {'label': 'P2', 'start': 's2', 'stop': 'e2'},
            {'label': 'P3', 'start': 's3', 'stop': 'e3'},
        ]
        stderr = io.StringIO()
        with patch('sys.stderr', stderr):
            kept = _classify_model_blocks(blocks, 'm.yaml')
        self.assertIsNone(kept)
        output = stderr.getvalue()
        self.assertIn('pair', output)
        self.assertIn("model 'm.yaml'", output)
        # Exactly one warning line for the model, regardless of how
        # many pair blocks it has.
        self.assertEqual(len(output.strip().splitlines()), 1)

    def test_classify_warns_once_and_skips_pattern_model(self):
        blocks = [
            {'label': 'PB1', 'patterns': ['x']},
            {'label': 'PB2', 'patterns': ['y']},
        ]
        stderr = io.StringIO()
        with patch('sys.stderr', stderr):
            kept = _classify_model_blocks(blocks, 'm.yaml')
        self.assertIsNone(kept)
        output = stderr.getvalue()
        self.assertIn('pattern', output)
        self.assertEqual(len(output.strip().splitlines()), 1)

    def test_classify_warns_and_skips_unclassified(self):
        blocks = [{'label': 'U'}]
        stderr = io.StringIO()
        with patch('sys.stderr', stderr):
            kept = _classify_model_blocks(blocks, 'm.yaml')
        self.assertIsNone(kept)
        self.assertIn('unclassified', stderr.getvalue())

    def test_classify_no_warning_for_fully_supported_model(self):
        blocks = [
            {'label': 'T', 'timeline': ['x']},
            {'label': 'W', 'window': True, 'file': '*.log'},
        ]
        stderr = io.StringIO()
        with patch('sys.stderr', stderr):
            kept = _classify_model_blocks(blocks, 'm.yaml')
        self.assertEqual(len(kept), 2)
        self.assertEqual(stderr.getvalue(), '')

    def test_classify_all_models_warns_once_per_unsupported_model(self):
        """_classify_all_models classifies every unique model exactly
        once, so calling it doesn't multiply warnings by host count —
        the caller is expected to reuse its result across hosts.
        """
        models = {
            'good.yaml': ([{'label': 'T', 'timeline': ['x']}], {}, 'p1'),
            'bad.yaml': (
                [{'label': 'P', 'start': 's', 'stop': 'e'}], {}, 'p2'
            ),
        }
        stderr = io.StringIO()
        with patch('sys.stderr', stderr):
            classified = _classify_all_models(models)
        self.assertEqual(len(classified['good.yaml']), 1)
        self.assertIsNone(classified['bad.yaml'])
        output = stderr.getvalue()
        self.assertEqual(len(output.strip().splitlines()), 1)
        self.assertIn("model 'bad.yaml'", output)

    def test_build_regex_single_pattern(self):
        r = _build_target_regex(['abc'], 'lbl')
        self.assertIsNotNone(r)
        self.assertTrue(r.search('xxabcxx'))

    def test_build_regex_or_list_flattened(self):
        # OR list should be flattened into alternation
        r = _build_target_regex([['foo', 'bar'], 'baz'], 'lbl')
        self.assertIsNotNone(r)
        self.assertTrue(r.search('has foo in it'))
        self.assertTrue(r.search('has bar in it'))
        self.assertTrue(r.search('has baz in it'))
        self.assertIsNone(r.search('has nothing'))

    def test_build_regex_invalid_dropped(self):
        stderr = io.StringIO()
        with patch('sys.stderr', stderr):
            # '[unclosed' is invalid regex; 'good' is valid
            r = _build_target_regex(['[unclosed', 'good'], 'lbl')
        self.assertIsNotNone(r)
        self.assertTrue(r.search('is good here'))
        self.assertIn('Invalid regex', stderr.getvalue())

    def test_build_regex_all_invalid_returns_none(self):
        stderr = io.StringIO()
        with patch('sys.stderr', stderr):
            r = _build_target_regex(['[bad1', '(bad2'], 'lbl')
        self.assertIsNone(r)

    def test_build_regex_empty_returns_none(self):
        self.assertIsNone(_build_target_regex([], 'lbl'))


class TestLoadAllModels(unittest.TestCase):
    """_load_all_models dedup and load."""

    def test_dedup_by_name(self):
        runs = [
            {'model': 'mtce_timeline_model.yaml',
             '_start': datetime(2026, 1, 1),
             '_stop': datetime(2026, 1, 2),
             'start_date': '2026-01-01T00:00:00',
             'stop_date': '2026-01-02T00:00:00'},
            {'model': 'mtce_timeline_model.yaml',
             '_start': datetime(2026, 1, 3),
             '_stop': datetime(2026, 1, 4),
             'start_date': '2026-01-03T00:00:00',
             'stop_date': '2026-01-04T00:00:00'},
        ]
        models = _load_all_models(runs)
        self.assertEqual(len(models), 1)
        self.assertIn('mtce_timeline_model.yaml', models)

    def test_two_distinct_models(self):
        runs = [
            {'model': 'mtce_timeline_model.yaml',
             '_start': datetime(2026, 1, 1),
             '_stop': datetime(2026, 1, 2),
             'start_date': '2026-01-01T00:00:00',
             'stop_date': '2026-01-02T00:00:00'},
            {'model': 'ceph_health.yaml',
             '_start': datetime(2026, 1, 1),
             '_stop': datetime(2026, 1, 2),
             'start_date': '2026-01-01T00:00:00',
             'stop_date': '2026-01-02T00:00:00'},
        ]
        models = _load_all_models(runs)
        self.assertEqual(len(models), 2)


# =========================================================================
# Phase 3: File-group and reader unit tests
# =========================================================================


def _write_log(path, lines):
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


class TestBatchFileGroups(LPMPTestBase):
    """_build_file_groups behaviour."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.logs = os.path.join(self.tmp, 'var', 'log')
        os.makedirs(self.logs)
        _write_log(os.path.join(self.logs, 'a.log'), [
            '2026-01-01T10:00:00.000 first line here',
            '2026-01-01T10:00:01.000 second line here',
        ])
        _write_log(os.path.join(self.logs, 'b.log'), [
            '2026-01-01T10:00:02.000 different content',
        ])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mock_model(self, blocks, settings=None):
        return (blocks, settings or {}, '/fake/path/model.yaml')

    def test_timeline_block_produces_target(self):
        blocks = [{'label': 'A', 'file': 'a.log',
                   'timeline': ['first']}]
        runs = [{'model': 'x.yaml',
                 '_start': datetime(2026, 1, 1, 9, 0, 0),
                 '_stop': datetime(2026, 1, 1, 11, 0, 0)}]
        models = {'x.yaml': self._mock_model(blocks)}
        classified = _classify_all_models(models)
        groups = _build_file_groups(runs, models, classified, self.logs,
                                    'controller-0')
        self.assertEqual(len(groups), 1)
        filepath, targets = next(iter(groups.items()))
        self.assertTrue(filepath.endswith('a.log'))
        self.assertEqual(len(targets), 1)
        self.assertIsNotNone(targets[0]['regex'])

    def test_window_block_produces_target_with_no_regex(self):
        blocks = [{'label': 'W', 'file': '*.log', 'window': True}]
        runs = [{'model': 'x.yaml',
                 '_start': datetime(2026, 1, 1, 9, 0, 0),
                 '_stop': datetime(2026, 1, 1, 11, 0, 0)}]
        models = {'x.yaml': self._mock_model(blocks)}
        classified = _classify_all_models(models)
        groups = _build_file_groups(runs, models, classified, self.logs,
                                    'controller-0')
        self.assertGreater(len(groups), 0)
        for _, targets in groups.items():
            for t in targets:
                self.assertIsNone(t['regex'])

    def test_two_runs_share_file(self):
        blocks = [{'label': 'A', 'file': 'a.log',
                   'timeline': ['first']}]
        runs = [
            {'model': 'x.yaml',
             '_start': datetime(2026, 1, 1, 9, 0, 0),
             '_stop': datetime(2026, 1, 1, 10, 30, 0)},
            {'model': 'x.yaml',
             '_start': datetime(2026, 1, 1, 10, 30, 0),
             '_stop': datetime(2026, 1, 1, 11, 0, 0)},
        ]
        models = {'x.yaml': self._mock_model(blocks)}
        classified = _classify_all_models(models)
        groups = _build_file_groups(runs, models, classified, self.logs,
                                    'controller-0')
        # Same file, two run targets → one filepath key, two targets
        filepath, targets = next(iter(groups.items()))
        run_indices = sorted({t['run_idx'] for t in targets})
        self.assertEqual(run_indices, [0, 1])

    def test_controller_only_block_skipped_for_worker(self):
        blocks = [{'label': 'A', 'file': 'a.log',
                   'timeline': ['first'], 'controller': True}]
        runs = [{'model': 'x.yaml',
                 '_start': datetime(2026, 1, 1, 9, 0, 0),
                 '_stop': datetime(2026, 1, 1, 11, 0, 0)}]
        models = {'x.yaml': self._mock_model(blocks)}
        classified = _classify_all_models(models)
        groups = _build_file_groups(runs, models, classified, self.logs,
                                    'worker-0')
        self.assertEqual(len(groups), 0)

    def test_invalid_regex_only_skips_target(self):
        stderr = io.StringIO()
        blocks = [{'label': 'BadOnly', 'file': 'a.log',
                   'timeline': ['[unclosed']}]
        runs = [{'model': 'x.yaml',
                 '_start': datetime(2026, 1, 1, 9, 0, 0),
                 '_stop': datetime(2026, 1, 1, 11, 0, 0)}]
        models = {'x.yaml': self._mock_model(blocks)}
        with patch('sys.stderr', stderr):
            classified = _classify_all_models(models)
            groups = _build_file_groups(runs, models, classified,
                                        self.logs, 'controller-0')
        self.assertEqual(len(groups), 0)

    def test_missing_file_skipped(self):
        blocks = [{'label': 'A', 'file': 'notthere.log',
                   'timeline': ['first']}]
        runs = [{'model': 'x.yaml',
                 '_start': datetime(2026, 1, 1, 9, 0, 0),
                 '_stop': datetime(2026, 1, 1, 11, 0, 0)}]
        models = {'x.yaml': self._mock_model(blocks)}
        classified = _classify_all_models(models)
        groups = _build_file_groups(runs, models, classified, self.logs,
                                    'controller-0')
        self.assertEqual(len(groups), 0)


class TestBatchSinglePassRead(LPMPTestBase):
    """_single_pass_read behaviour."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_target(self, start, stop, regex=None):
        return {
            'run_idx': 0,
            'block_label': 'lbl',
            'filename': 'sample.log',
            'start': start,
            'stop': stop,
            'regex': regex,
        }

    def test_timeline_match_emits_row(self):
        path = os.path.join(self.tmp, 'sample.log')
        _write_log(path, [
            '2026-01-01T10:00:00.000 hello world',
            '2026-01-01T10:00:01.000 goodbye there',
        ])
        target = self._make_target(
            datetime(2026, 1, 1, 9, 0, 0),
            datetime(2026, 1, 1, 11, 0, 0),
            re.compile('hello'),
        )
        results = _single_pass_read(path, [target])
        self.assertIn(0, results)
        self.assertEqual(len(results[0]), 1)
        self.assertIn('hello world', results[0][0][1])

    def test_window_target_emits_every_line(self):
        path = os.path.join(self.tmp, 'sample.log')
        _write_log(path, [
            '2026-01-01T10:00:00.000 line one',
            '2026-01-01T10:00:01.000 line two',
            '2026-01-01T10:00:02.000 line three',
        ])
        target = self._make_target(
            datetime(2026, 1, 1, 9, 0, 0),
            datetime(2026, 1, 1, 11, 0, 0),
            None,  # window: no regex
        )
        results = _single_pass_read(path, [target])
        self.assertEqual(len(results[0]), 3)

    def test_whole_file_prune_when_before_window(self):
        path = os.path.join(self.tmp, 'sample.log')
        _write_log(path, [
            '2026-01-01T00:00:00.000 old line one',
            '2026-01-01T00:01:00.000 old line two',
        ])
        target = self._make_target(
            datetime(2026, 6, 1, 0, 0, 0),  # window is way after file end
            datetime(2026, 6, 2, 0, 0, 0),
            None,
        )
        results = _single_pass_read(path, [target])
        self.assertEqual(len(results), 0)

    def test_whole_file_prune_when_after_window(self):
        path = os.path.join(self.tmp, 'sample.log')
        _write_log(path, [
            '2026-06-01T00:00:00.000 new line one',
            '2026-06-01T00:01:00.000 new line two',
        ])
        target = self._make_target(
            datetime(2026, 1, 1, 0, 0, 0),  # window is way before file start
            datetime(2026, 1, 2, 0, 0, 0),
            None,
        )
        results = _single_pass_read(path, [target])
        self.assertEqual(len(results), 0)

    def test_virtual_eof_breaks_reading(self):
        path = os.path.join(self.tmp, 'sample.log')
        _write_log(path, [
            '2026-01-01T10:00:00.000 in window one',
            '2026-01-01T10:00:01.000 in window two',
            '2026-01-01T10:05:00.000 out of window three',
        ])
        target = self._make_target(
            datetime(2026, 1, 1, 9, 59, 0),
            datetime(2026, 1, 1, 10, 0, 30),  # ends before line 3
            None,
        )
        results = _single_pass_read(path, [target])
        self.assertEqual(len(results[0]), 2)

    def test_empty_targets_returns_empty(self):
        path = os.path.join(self.tmp, 'sample.log')
        _write_log(path, ['2026-01-01T10:00:00.000 x'])
        results = _single_pass_read(path, [])
        self.assertEqual(len(results), 0)

    def test_gzipped_file_read(self):
        path = os.path.join(self.tmp, 'sample.log.gz')
        with gzip.open(path, 'wt') as f:
            f.write('2026-01-01T10:00:00.000 gz line one\n')
            f.write('2026-01-01T10:00:01.000 gz line two\n')
        target = self._make_target(
            datetime(2026, 1, 1, 9, 0, 0),
            datetime(2026, 1, 1, 11, 0, 0),
            re.compile('gz line'),
        )
        # Gzipped filename gets .log.gz basename passed as relpath
        target['filename'] = 'sample.log.gz'
        results = _single_pass_read(path, [target])
        self.assertEqual(len(results[0]), 2)

    def test_nonexistent_file_prints_error(self):
        stderr = io.StringIO()
        target = self._make_target(
            datetime(2026, 1, 1, 9, 0, 0),
            datetime(2026, 1, 1, 11, 0, 0),
            None,
        )
        with patch('sys.stderr', stderr):
            results = _single_pass_read(os.path.join(self.tmp, 'nope.log'),
                                        [target])
        # Reader tries to open; get_file_date_range returns None, None so
        # prune doesn't fire; open fails with IOError which is caught.
        self.assertEqual(len(results), 0)


# =========================================================================
# Phase 4: Output-writer and orchestration unit tests
# =========================================================================


class TestBatchOutputWriters(LPMPTestBase):
    """_write_profile_text and _write_run_output and _run_base_dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_profile_text_header_and_delta(self):
        out = os.path.join(self.tmp, 'p.timeline.log')
        matches = [
            (datetime(2026, 1, 1, 10, 0, 0), 'line one', 'a.log', 'Blk'),
            (datetime(2026, 1, 1, 10, 0, 5), 'line two', 'a.log', 'Blk'),
        ]
        _write_profile_text(out, 'controller-0', matches, 180)
        with open(out) as f:
            content = f.read()
        self.assertIn('Delta(HH:MM:SS)', content)
        self.assertIn('Hostname', content)
        self.assertIn('line one', content)
        self.assertIn('line two', content)
        # first row delta is zero
        self.assertIn('00:00:00.000', content)
        # second row delta reflects 5 seconds
        self.assertIn('00:00:05.000', content)

    def test_write_profile_text_truncates(self):
        out = os.path.join(self.tmp, 'p.timeline.log')
        long_line = 'x' * 500
        matches = [
            (datetime(2026, 1, 1, 10, 0, 0), long_line, 'a.log', 'Blk'),
        ]
        _write_profile_text(out, 'controller-0', matches, 50)
        with open(out) as f:
            content = f.read()
        # 'x' repeated exactly 50 times should appear, not 500 times
        self.assertIn('x' * 50, content)
        self.assertNotIn('x' * 51, content)

    def test_write_run_output_creates_dir_and_files(self):
        blocks = [{'label': 'Blk', 'file': 'a.log',
                   'timeline': ['x']}]
        run = {'model': 'model.yaml',
               '_start': datetime(2026, 1, 1, 10, 0, 0),
               '_stop': datetime(2026, 1, 1, 10, 30, 0),
               'start_date': '2026-01-01T10:00:00',
               'stop_date': '2026-01-01T10:30:00'}
        args = _make_args(output=self.tmp)
        matches = [(datetime(2026, 1, 1, 10, 0, 5), 'x hit', 'a.log', 'Blk')]
        profile = _write_run_output(
            args, run, 'model.yaml', 'controller-0', matches,
            blocks, datetime(2026, 7, 1, 12, 0, 0),
        )
        self.assertIsNotNone(profile)
        self.assertTrue(os.path.exists(profile))
        self.assertTrue(os.path.exists(profile + '.csv'))

    def test_write_run_output_empty_matches_returns_none(self):
        args = _make_args(output=self.tmp)
        run = {'model': 'model.yaml',
               '_start': datetime(2026, 1, 1),
               '_stop': datetime(2026, 1, 2)}
        result = _write_run_output(args, run, 'model.yaml', 'controller-0',
                                   [], [], datetime(2026, 7, 1))
        self.assertIsNone(result)

    def test_run_base_dir_matches_layout(self):
        args = _make_args(output=self.tmp, lab='mylab', lab_name='mylab')
        ts = datetime(2026, 7, 1, 12, 34, 56)
        base = _run_base_dir(args, ts, 'foo.yaml')
        self.assertIn('lpmp_mylab', base)
        self.assertIn('20260701_123456_foo', base)

    def test_run_base_dir_honours_batch_dir_prefix(self):
        """When lpmptool sets args._dir_prefix = 'lpmp_batch_<lab>' the
        directory factory routes batch output under that prefix instead
        of the mainline 'lpmp_<lab>'.
        """
        args = _make_args(output=self.tmp, lab='mylab', lab_name='mylab')
        args._dir_prefix = 'lpmp_batch_mylab'
        ts = datetime(2026, 7, 1, 12, 34, 56)
        base = _run_base_dir(args, ts, 'foo.yaml')
        self.assertIn('lpmp_batch_mylab', base)
        # Mainline prefix must NOT appear as a separate directory
        # segment: 'lpmp_batch_mylab' contains 'lpmp_' as a substring
        # but should never sit next to a plain 'lpmp_mylab' segment.
        parts = base.split(os.sep)
        self.assertNotIn('lpmp_mylab', parts)

    def test_precompute_run_dirs_uses_wall_clock_start(self):
        """All runs in a batch share one tool-runtime directory named
        after the batch's wall-clock start time.

        This locks in that batch mode uses the batch wall-clock start
        for the runtime directory (matching mainline `lpmptool -m`)
        rather than any run's window start, so re-running the same
        spec never clobbers a previous run's output.
        """
        from lpmp_batch import _precompute_run_dirs
        runs = [
            {'model': 'ceph_health.yaml',
             '_start': datetime(2026, 2, 25, 13, 35, 0),
             '_stop': datetime(2026, 2, 25, 13, 38, 0)},
            {'model': 'host_lifecycle.yaml',
             '_start': datetime(2026, 2, 25, 13, 35, 0),
             '_stop': datetime(2026, 2, 25, 13, 38, 0)},
        ]
        args = _make_args(output=self.tmp, lab='mylab', lab_name='mylab')
        wall = datetime(2026, 7, 6, 13, 52, 24)
        _precompute_run_dirs(runs, args, wall)

        # Every run's _dir_time equals the batch wall-clock start,
        # not the run's own window start, and both runs share the
        # same _runtime_dir.
        for run in runs:
            self.assertEqual(run['_dir_time'], wall)
        self.assertEqual(runs[0]['_runtime_dir'], runs[1]['_runtime_dir'])
        self.assertEqual(runs[0]['_runtime_dir'], '20260706_135224')

        # Path reflects the shared runtime dir plus each run's own
        # start/model/stop directory name.
        base1 = _run_base_dir(args, wall, runs[0]['model'], runs[0])
        base2 = _run_base_dir(args, wall, runs[1]['model'], runs[1])
        self.assertIn(
            os.path.join('20260706_135224',
                         '20260225_133500_ceph_health_20260225_133800'),
            base1)
        self.assertIn(
            os.path.join('20260706_135224',
                         '20260225_133500_host_lifecycle_20260225_133800'),
            base2)


class TestBatchRunBatchIntegration(LPMPTestBase):
    """End-to-end run_batch using a mini synthetic bundle."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Build mini bundle: <bundle>/<host>_YYYYMMDD.HHMMSS/var/log/*.log
        self.bundle = os.path.join(self.tmp, 'bundle')
        self.hosts = ['controller-0', 'controller-1']
        for h in self.hosts:
            host_dir = os.path.join(self.bundle, f'{h}_20260701.100000')
            logs = os.path.join(host_dir, 'var', 'log')
            os.makedirs(logs)
            _write_log(os.path.join(logs, 'a.log'), [
                '2026-07-01T10:00:00.000 anchor line for ' + h,
                '2026-07-01T10:00:05.000 something else',
                '2026-07-01T10:00:10.000 another anchor here',
            ])
            _write_log(os.path.join(logs, 'b.log'), [
                '2026-07-01T10:00:02.000 second file line one',
                '2026-07-01T10:00:07.000 second file line two',
            ])

        # Batch spec: one timeline run, one window run
        self.spec_path = os.path.join(self.tmp, 'spec.json')
        # Use bare filename that batch will resolve via _resolve_model_path.
        # Write a small model on the fly under a temp models dir accessible
        # via the model_file's absolute path, which _resolve_model_path
        # accepts.
        self.model_a = os.path.join(self.tmp, 'model_a.yaml')
        with open(self.model_a, 'w') as f:
            f.write(
                "description: Test model.\nblocks:\n"
                "  - label: 'Anchor'\n"
                "    file: 'a.log'\n"
                "    timeline:\n"
                "      - 'anchor'\n"
            )
        self.model_w = os.path.join(self.tmp, 'model_w.yaml')
        with open(self.model_w, 'w') as f:
            f.write(
                "description: Test model.\nblocks:\n"
                "  - label: 'All Logs'\n"
                "    file: '*.log'\n"
                "    window: true\n"
            )

        with open(self.spec_path, 'w') as f:
            json.dump({'runs': [
                {'model': self.model_a,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
                {'model': self.model_w,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
            ]}, f)

        self.out = os.path.join(self.tmp, 'out')
        os.makedirs(self.out)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_end_to_end_produces_expected_output(self):
        args = _make_args(
            batch=self.spec_path,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        # Suppress "Batch complete: ..." console output
        with patch('builtins.print'):
            run_batch(args)

        # Per-run output dirs should exist
        found_dirs = []
        for root, dirs, files in os.walk(self.out):
            for d in dirs:
                if 'model_a' in d or 'model_w' in d:
                    found_dirs.append(os.path.join(root, d))
        self.assertGreater(len(found_dirs), 0, 'No per-run dirs')

        # Both hosts should have profile output for the timeline run
        timeline_files = []
        window_files = []
        for root, dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith('profile.timeline.log'):
                    p = os.path.join(root, name)
                    if 'model_a' in p:
                        timeline_files.append(p)
                    if 'model_w' in p:
                        window_files.append(p)

        self.assertGreater(len(timeline_files), 0,
                           'No timeline profile files')
        self.assertGreater(len(window_files), 0,
                           'No window profile files')

        # System-level merged file should exist per run
        systems = []
        for root, dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith('_system_profile.timeline.log'):
                    systems.append(os.path.join(root, name))
        self.assertGreaterEqual(len(systems), 1,
                                'No system merged file(s)')

    def test_run_batch_warns_and_skips_pair_and_pattern_models(self):
        """Pattern and pair models in a batch spec are each rejected
        with a single one-line warning (not one per block), and the
        rest of the batch — the timeline model — still runs and
        produces output normally.
        """
        pair_model = os.path.join(self.tmp, 'pair_model.yaml')
        with open(pair_model, 'w') as f:
            f.write(
                "description: Test model.\nblocks:\n"
                "  - label: 'Duration'\n"
                "    file: 'a.log'\n"
                "    start: 'anchor'\n"
                "    stop: 'else'\n"
                "  - label: 'Duration2'\n"
                "    file: 'a.log'\n"
                "    start: 'anchor'\n"
                "    stop: 'else2'\n"
            )
        pattern_model = os.path.join(self.tmp, 'pattern_model.yaml')
        with open(pattern_model, 'w') as f:
            f.write(
                "description: Test model.\nblocks:\n"
                "  - label: 'Hit'\n"
                "    file: 'a.log'\n"
                "    patterns:\n"
                "      - 'anchor'\n"
            )
        spec = os.path.join(self.tmp, 'mixed_spec.json')
        with open(spec, 'w') as f:
            json.dump({'runs': [
                {'model': pair_model,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
                {'model': pattern_model,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
                {'model': self.model_a,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
            ]}, f)

        args = _make_args(
            batch=spec,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        captured, capture = _capture_prints()
        with patch('builtins.print', side_effect=capture):
            run_batch(args)
        joined = '\n'.join(captured)

        pair_warnings = [line for line in captured
                         if line.startswith('⚠️ Warning:')
                         and 'pair_model.yaml' in line]
        pattern_warnings = [line for line in captured
                            if line.startswith('⚠️ Warning:')
                            and 'pattern_model.yaml' in line]
        self.assertEqual(len(pair_warnings), 1,
                         f'Expected exactly one pair warning, got: '
                         f'{pair_warnings}')
        self.assertEqual(len(pattern_warnings), 1,
                         f'Expected exactly one pattern warning, got: '
                         f'{pattern_warnings}')
        self.assertIn('pair', pair_warnings[0])
        self.assertIn('pattern', pattern_warnings[0])

        # The timeline model in the same batch still runs successfully.
        timeline_files = []
        for root, dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith('profile.timeline.log') \
                        and 'model_a' in root:
                    timeline_files.append(os.path.join(root, name))
        self.assertGreater(len(timeline_files), 0,
                           f'Timeline model produced no output. '
                           f'Console output: {joined}')

    def test_run_batch_include_filter(self):
        args = _make_args(
            batch=self.spec_path,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
            include=['controller-0'],
        )
        with patch('builtins.print'):
            run_batch(args)
        # Only controller-0 dir should exist
        host_dirs = set()
        for root, dirs, files in os.walk(self.out):
            for d in dirs:
                if d in ('controller-0', 'controller-1'):
                    host_dirs.add(d)
        self.assertIn('controller-0', host_dirs)
        self.assertNotIn('controller-1', host_dirs)

    def test_run_batch_dateless_spec_uses_cli_dates(self):
        """Spec with no dates picks up --start-date / --stop-date from CLI."""
        # Build a spec with only 'model' — no dates.
        spec = os.path.join(self.tmp, 'dateless.json')
        with open(spec, 'w') as f:
            json.dump([{'model': self.model_a}], f)

        args = _make_args(
            batch=spec,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
            start_date='2026-07-01T09:00:00',
            stop_date='2026-07-01T11:00:00',
        )
        with patch('builtins.print'):
            run_batch(args)
        # Confirm a per-run profile was produced (matches only happen
        # when the CLI window is applied).
        found = []
        for root, dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith('profile.timeline.log'):
                    found.append(os.path.join(root, name))
        self.assertGreater(len(found), 0,
                           'CLI-date fallback produced no output')

    def test_run_batch_dateless_spec_unbounded(self):
        """Spec with no dates and no CLI dates runs unbounded."""
        spec = os.path.join(self.tmp, 'unbounded.json')
        with open(spec, 'w') as f:
            json.dump([{'model': self.model_w}], f)  # window model

        args = _make_args(
            batch=spec,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        with patch('builtins.print'):
            run_batch(args)
        # Window model with no time filter should emit every
        # timestamped line in the mini-bundle's logs.
        found = []
        for root, dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith('profile.timeline.log'):
                    found.append(os.path.join(root, name))
        self.assertGreater(len(found), 0)

    def test_repeat_model_with_different_windows_produces_distinct_dirs(self):
        """The same model listed twice with different windows is
        allowed and produces two distinct output directories, each
        named from its own resolved start/stop dates.
        """
        spec = os.path.join(self.tmp, 'repeat.json')
        with open(spec, 'w') as f:
            json.dump([
                {'model': self.model_a,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
                {'model': self.model_a,
                 'start_date': '2026-07-01T09:30:00',
                 'stop_date': '2026-07-01T11:30:00'},
            ], f)
        args = _make_args(
            batch=spec,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        with patch('builtins.print'):
            run_batch(args)
        run_dirs = set()
        for root, dirs, files in os.walk(self.out):
            for d in dirs:
                if 'model_a' in d:
                    run_dirs.add(os.path.join(root, d))
        self.assertGreaterEqual(len(run_dirs), 2,
                                f'Expected distinct dirs, got: {run_dirs}')
        dir_strs = [str(d) for d in run_dirs]
        self.assertTrue(
            any('20260701_090000_model_a_20260701_110000' in d
                for d in dir_strs),
            f'Expected first window dir name in {dir_strs}')
        self.assertTrue(
            any('20260701_093000_model_a_20260701_113000' in d
                for d in dir_strs),
            f'Expected second window dir name in {dir_strs}')

    def test_repeat_model_with_same_window_is_rejected(self):
        """The same model listed twice with the exact same resolved
        window is rejected — it would otherwise collide on disk.
        """
        spec = os.path.join(self.tmp, 'exact_repeat.json')
        with open(spec, 'w') as f:
            json.dump([
                {'model': self.model_a,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
                {'model': self.model_a,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
            ], f)
        args = _make_args(
            batch=spec,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        captured, capture = _capture_prints()
        with patch('builtins.print', side_effect=capture), \
                self.assertRaises(SystemExit) as cm:
            run_batch(args)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn('duplicates run #1', '\n'.join(captured))

    def test_run_batch_distinct_models_get_distinct_run_dirs(self):
        """Two different models in one batch each get their own
        subdirectory under the shared tool-runtime directory, with
        their resolved start/stop dates encoded in the directory name.
        """
        spec = os.path.join(self.tmp, 'two_models.json')
        with open(spec, 'w') as f:
            json.dump([
                {'model': self.model_a,
                 'start_date': '2026-07-01T09:00:00',
                 'stop_date': '2026-07-01T11:00:00'},
                {'model': self.model_w,
                 'start_date': '2026-07-01T09:30:00',
                 'stop_date': '2026-07-01T11:30:00'},
            ], f)
        args = _make_args(
            batch=spec,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        with patch('builtins.print'):
            run_batch(args)
        run_dirs = set()
        for root, dirs, files in os.walk(self.out):
            for d in dirs:
                if 'model_a' in d or 'model_w' in d:
                    run_dirs.add(os.path.join(root, d))
        self.assertGreaterEqual(len(run_dirs), 2,
                                f'Expected distinct dirs, got: {run_dirs}')
        dir_strs = [str(d) for d in run_dirs]
        self.assertTrue(
            any('20260701_090000_model_a_20260701_110000' in d
                for d in dir_strs),
            f'Expected full start/stop dir name in {dir_strs}')
        self.assertTrue(
            any('20260701_093000_model_w_20260701_113000' in d
                for d in dir_strs),
            f'Expected full start/stop dir name in {dir_strs}')
        # Both runs must share the same tool-runtime directory level
        # (the parent segment before the run's own dir name).
        runtime_dirs = {os.path.basename(os.path.dirname(d))
                        for d in dir_strs}
        self.assertEqual(len(runtime_dirs), 1,
                         f'Expected one shared runtime dir, got {runtime_dirs}')

    def test_run_batch_prints_output_path(self):
        """The final console output includes the path to the batch's
        tool-runtime directory so users can find their results
        without hunting through the bundle tree.
        """
        args = _make_args(
            batch=self.spec_path,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        captured, capture = _capture_prints()
        with patch('builtins.print', side_effect=capture):
            run_batch(args)
        output_lines = [line for line in captured
                        if line.startswith('Output: ')]
        self.assertEqual(len(output_lines), 1,
                         f'Expected one Output: line, got: {captured}')
        printed_path = output_lines[0][len('Output: '):]
        self.assertTrue(os.path.isdir(printed_path),
                        f'Printed path does not exist: {printed_path}')
        # Note: _make_args doesn't set args._dir_prefix (that override
        # is applied by lpmptool's main() before dispatch), so the
        # prefix here is the plain 'lpmp_<lab>' default.
        self.assertIn(os.path.join(self.out, 'lpmp_lab'), printed_path)

    def test_run_batch_output_listing_shows_run_dirs(self):
        """After the 'Output: <path>' line, a long-listing (ls -lrt
        style) of the runtime directory's immediate contents is
        printed so the run directories are visible without a
        separate manual `ls`.
        """
        args = _make_args(
            batch=self.spec_path,
            bundle=self.bundle,
            bundle_name=self.bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        captured, capture = _capture_prints()
        with patch('builtins.print', side_effect=capture):
            run_batch(args)
        joined = '\n'.join(captured)
        self.assertIn('total ', joined)
        self.assertIn('model_a', joined)
        self.assertIn('model_w', joined)

    def test_run_batch_missing_host_logsdir_warns(self):
        # Create a bundle host dir without var/log
        bad_bundle = os.path.join(self.tmp, 'bad_bundle')
        os.makedirs(os.path.join(bad_bundle, 'controller-0_20260701.100000'))
        args = _make_args(
            batch=self.spec_path,
            bundle=bad_bundle,
            bundle_name=bad_bundle,
            output=self.out,
            lab='lab',
            lab_name='lab',
        )
        captured, capture = _capture_prints()
        with patch('builtins.print', side_effect=capture):
            run_batch(args)
        self.assertIn('not found', '\n'.join(captured))


# =========================================================================
# Phase 5: Bundle regression tests (opt-in via LPMP_TEST_BUNDLE)
# =========================================================================


@unittest.skipUnless(BUNDLE_AVAILABLE, f"Requires bundle at {BUNDLE_PATH}")
class TestBatchBundleRegression(LPMPTestBase):
    """Regression tests running batch mode against a real bundle.

    Discovers hostnames from bundle layout, then runs batch against
    them so tests adapt to whatever bundle is supplied.
    """

    BUNDLE_HOSTS = []

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.BUNDLE_HOSTS = cls._discover_bundle_hosts()

    @classmethod
    def _discover_bundle_hosts(cls):
        if not BUNDLE_PATH or not os.path.isdir(BUNDLE_PATH):
            return []
        host_pattern = re.compile(r'^(.+)_(\d{8}\.\d{6})$')
        latest = {}
        for entry in os.listdir(BUNDLE_PATH):
            full = os.path.join(BUNDLE_PATH, entry)
            if not os.path.isdir(full):
                continue
            m = host_pattern.match(entry)
            if not m:
                continue
            hostname, date_part = m.groups()
            cur = latest.get(hostname)
            if cur is None or date_part > cur[0]:
                latest[hostname] = (date_part, entry)
        return sorted(latest.keys())

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, 'out')
        os.makedirs(self.out)
        self.models_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'models',
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_batch(self, spec_path, include=None):
        args = _make_args(
            batch=spec_path,
            bundle=BUNDLE_PATH,
            bundle_name=BUNDLE_PATH,
            output=self.out,
            lab='regression',
            lab_name='regression',
            include=include or self.BUNDLE_HOSTS,
        )
        with patch('builtins.print'):
            run_batch(args)

    def _time_window(self):
        """Return a wide-enough window that some matches exist. Uses
        detect_bundle_hosts + one host's earliest and latest to pick
        a sensible range.
        """
        # Fall back to a broad window
        return ('2020-01-01T00:00:00', '2030-12-31T23:59:59')

    def test_bundle_batch_produces_timeline_output(self):
        """Batch mode against a real bundle produces per-run output."""
        model = os.path.join(self.models_dir, 'mtce_timeline_model.yaml')
        if not os.path.exists(model):
            self.skipTest(f"Model not found: {model}")
        start, stop = self._time_window()
        spec_path = os.path.join(self.tmp, 'spec.json')
        with open(spec_path, 'w') as f:
            json.dump({'runs': [
                {'model': model, 'start_date': start, 'stop_date': stop},
            ]}, f)
        self._run_batch(spec_path)
        # Confirm at least one profile file produced
        found = []
        for root, dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith('profile.timeline.log'):
                    found.append(os.path.join(root, name))
        self.assertGreater(len(found), 0,
                           'Batch produced no timeline output')

    def test_bundle_batch_multi_run(self):
        """Two runs of two different timeline models on the real bundle."""
        m1 = os.path.join(self.models_dir, 'mtce_timeline_model.yaml')
        m2 = os.path.join(self.models_dir, 'ceph_health.yaml')
        for m in (m1, m2):
            if not os.path.exists(m):
                self.skipTest(f"Model not found: {m}")
        start, stop = self._time_window()
        spec_path = os.path.join(self.tmp, 'spec.json')
        with open(spec_path, 'w') as f:
            json.dump({'runs': [
                {'model': m1, 'start_date': start, 'stop_date': stop},
                {'model': m2, 'start_date': start, 'stop_date': stop},
            ]}, f)
        self._run_batch(spec_path)
        # Look for at least one output dir per model
        m1_base = os.path.splitext(os.path.basename(m1))[0]
        m2_base = os.path.splitext(os.path.basename(m2))[0]
        found_m1 = False
        found_m2 = False
        for root, dirs, files in os.walk(self.out):
            for d in dirs:
                if m1_base in d:
                    found_m1 = True
                if m2_base in d:
                    found_m2 = True
        # Only assert if at least one had matches (bundle may not exercise both)
        self.assertTrue(found_m1 or found_m2,
                        'Neither batched model produced output')

    def test_bundle_batch_warn_and_skip_pair_model(self):
        """Pair model in batch spec is rejected with exactly one
        warning line — not one per block, and not one per host, even
        though this batch scans every host in the real bundle.
        """
        # Find any pair model shipped
        pair_candidates = [
            'sm_service_shutdown_pair_model.yaml',
            'kpi_unlock_pairing_model.yaml',
        ]
        pair_model = None
        for candidate in pair_candidates:
            p = os.path.join(self.models_dir, candidate)
            if os.path.exists(p):
                pair_model = p
                break
        if not pair_model:
            self.skipTest('No pair model available for skip-warn test')
        start, stop = self._time_window()
        spec_path = os.path.join(self.tmp, 'spec.json')
        with open(spec_path, 'w') as f:
            json.dump({'runs': [
                {'model': pair_model,
                 'start_date': start, 'stop_date': stop},
            ]}, f)
        args = _make_args(
            batch=spec_path,
            bundle=BUNDLE_PATH,
            bundle_name=BUNDLE_PATH,
            output=self.out,
            lab='regression',
            lab_name='regression',
            include=self.BUNDLE_HOSTS,
        )
        captured, capture = _capture_prints()
        with patch('builtins.print', side_effect=capture):
            run_batch(args)
        pair_warnings = [line for line in captured
                         if line.startswith('⚠️ Warning:') and 'pair' in line]
        self.assertEqual(len(pair_warnings), 1,
                         f'Expected exactly one pair warning regardless '
                         f'of host count, got: {pair_warnings}')


if __name__ == '__main__':
    unittest.main()
