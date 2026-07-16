#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for lpmptool main() execution paths

This test suite covers:
1. System mode execution with pattern/pair blocks
2. Command-line argument handling
3. Bundle mode execution
4. Error handling paths

Focus: Increase lpmptool coverage from 34% to 50%+
Strategy: Test main() with various argument combinations, avoid interactive modes
"""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# Default bundle path for regression tests (skip if not present)
DEFAULT_BUNDLE_PATH = '/localdisk/lpmptool_demo/TIMELINE/ALL_NODES_20260227.190103'
# Bundle tests only run when explicitly enabled via run_tests.py --bundle
BUNDLE_PATH = os.environ.get('LPMP_TEST_BUNDLE')
BUNDLE_AVAILABLE = os.path.isdir(BUNDLE_PATH) if BUNDLE_PATH else False
BUNDLE_SKIPPED_COUNT = 10  # Number of tests that require --bundle

# Import lpmptool main
sys.path.insert(0, str(Path(__file__).parent.parent))
import lpmptool  # noqa: E402
from test_base import LPMPTestBase  # noqa: E402


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestMainExecution(LPMPTestBase):
    """Test main() execution paths for lpmptool"""

    def setUp(self):
        """Setup temp directories and files for testing"""
        import shutil
        self.temp_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.temp_dir, 'var', 'log')
        os.makedirs(self.logs_dir, exist_ok=True)
        self.output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        """Cleanup temp directories"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def create_model_file(self, model_data, filename='test_model.yaml'):
        """Helper: Create a YAML model file"""
        model_path = os.path.join(self.temp_dir, filename)
        with open(model_path, 'w') as f:
            yaml.dump(model_data, f)
        return model_path

    def create_log_file(self, content, filename='test.log'):
        """Helper: Create a log file with timestamps"""
        log_path = os.path.join(self.logs_dir, filename)
        with open(log_path, 'w') as f:
            f.write(content)
        return log_path

    def create_pattern_model(self, label='Test Pattern', pattern='test pattern', filename='test.log'):
        """Helper: Create simple pattern block model"""
        return {
            'description': 'Test pattern model.',
            'blocks': [
                {
                    'label': label,
                    'file': filename,
                    'patterns': [pattern]
                }
            ]
        }

    def create_pair_model(self, label='Test Pair', start='start', stop='stop', filename='test.log'):
        """Helper: Create simple pair block model"""
        return {
            'description': 'Test pair model.',
            'blocks': [
                {
                    'label': label,
                    'file': filename,
                    'start': start,
                    'stop': stop
                }
            ]
        }

    def create_bundle_structure(self, hosts=['controller-0', 'controller-1']):
        """Helper: Create bundle directory structure"""
        bundle_dir = os.path.join(self.temp_dir, 'bundle')
        os.makedirs(bundle_dir, exist_ok=True)

        host_dirs = []
        for host in hosts:
            host_dir = os.path.join(bundle_dir, f'{host}_20260101.120000')
            logs_dir = os.path.join(host_dir, 'var', 'log')
            os.makedirs(logs_dir, exist_ok=True)
            host_dirs.append(host_dir)

        return bundle_dir, host_dirs

    def run_main_with_args(self, args):
        """Helper: Run main() with mocked sys.argv and capture output"""
        with patch('sys.argv', ['lpmptool'] + args):
            with patch('sys.stdout') as mock_stdout:
                with patch('sys.stderr') as mock_stderr:
                    try:
                        lpmptool.main()
                        return True, None
                    except SystemExit as e:
                        return e.code == 0, e.code

    def test_infrastructure_setup(self):
        """Test that test infrastructure is working"""
        self.assertTrue(os.path.exists(self.temp_dir))
        self.assertTrue(os.path.exists(self.logs_dir))
        model = self.create_pattern_model()
        model_path = self.create_model_file(model)
        self.assertTrue(os.path.exists(model_path))
        log_content = "2024-01-06T10:00:00.000 test pattern\n"
        log_path = self.create_log_file(log_content)
        self.assertTrue(os.path.exists(log_path))

    def test_system_mode_pattern_model_creates_output_files(self):
        """Test system mode with pattern model creates timing and CSV files"""
        self.create_log_file(
            "2024-01-06T10:00:00.000 test pattern match\n"
            "2024-01-06T10:00:05.000 second pattern match\n"
        )
        model_path = self.create_model_file({
            'description': 'Test model.', 'blocks': [
                {'label': 'First', 'file': 'test.log', 'patterns': ['test pattern']},
                {'label': 'Second', 'file': 'test.log', 'patterns': ['second pattern']},
            ]
        })
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        # Verify output files exist
        output_files = []
        for root, dirs, files in os.walk(self.output_dir):
            output_files.extend(files)
        self.assertTrue(any('profile.timing' in f for f in output_files))
        self.assertTrue(any('.csv' in f for f in output_files))

    def test_system_mode_pair_model_creates_output_files(self):
        """Test system mode with pair model creates timing, CSV, and summary"""
        self.create_log_file(
            "2024-01-06T10:00:00.000 operation start here\n"
            "2024-01-06T10:00:03.000 operation stop here\n"
        )
        model_path = self.create_model_file({
            'description': 'Test model.', 'blocks': [{
                'label': 'Operation',
                'file': 'test.log',
                'start': 'operation start',
                'stop': 'operation stop'
            }]
        })
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        output_files = []
        for root, dirs, files in os.walk(self.output_dir):
            output_files.extend(files)
        self.assertTrue(any('profile.timing' in f for f in output_files))
        self.assertTrue(any('.csv' in f for f in output_files))
        self.assertTrue(any('summary.timing' in f for f in output_files))

    def test_system_mode_timeline_model_creates_output_files(self):
        """Test system mode with timeline model creates timeline.log and CSV"""
        self.create_log_file(
            "2024-01-06T10:00:00.000 event alpha happened\n"
            "2024-01-06T10:00:01.000 event beta happened\n"
            "2024-01-06T10:00:02.000 event alpha happened again\n"
        )
        model_path = self.create_model_file({
            'description': 'Test model.', 'blocks': [{
                'label': 'Events',
                'file': 'test.log',
                'timeline': ['event alpha', 'event beta']
            }]
        })
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        output_files = []
        for root, dirs, files in os.walk(self.output_dir):
            output_files.extend(files)
        self.assertTrue(any('timeline.log' in f for f in output_files))
        self.assertTrue(any('.csv' in f for f in output_files))

    def test_system_mode_no_matches_reports_error(self):
        """Test system mode with no pattern matches reports failure"""
        self.create_log_file("2024-01-06T10:00:00.000 nothing relevant\n")
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='will not match')
        )
        output = []
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print', side_effect=lambda *a, **kw: output.append(
                ' '.join(str(x) for x in a)
            )):
                with self.assertRaises(SystemExit) as cm:
                    lpmptool.main()
                self.assertEqual(cm.exception.code, 1)
        combined = '\n'.join(output)
        self.assertIn('Error', combined)

    def test_system_mode_csv_has_content(self):
        """Test CSV output file has header and data rows"""
        self.create_log_file(
            "2024-01-06T10:00:00.000 test pattern match\n"
        )
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='test pattern')
        )
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        # Find and read the CSV file
        csv_file = None
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.csv'):
                    csv_file = os.path.join(root, f)
        self.assertIsNotNone(csv_file, "CSV file not created")
        with open(csv_file, 'r') as f:
            lines = f.readlines()
        self.assertGreater(len(lines), 1, "CSV should have header + data")

    def test_model_settings_block_time_tolerance_applied(self):
        """Test block_time_tolerance from model settings is applied to args"""
        self.create_log_file("2024-01-06T10:00:00.000 test pattern\n")
        model_path = self.create_model_file({
            'description': 'Test model.', 'settings': {'block_time_tolerance': 12.5},
            'blocks': [{'label': 'T', 'file': 'test.log', 'patterns': ['test']}]
        })
        captured = {}

        def capture(args, *a, **kw):
            captured['btt'] = args.block_time_tolerance
            return (False, None, None, 0, [], [])

        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir
        ]):
            with patch('lpmptool.process_blocks_auto_detect', side_effect=capture):
                with patch('builtins.print'):
                    try:
                        lpmptool.main()
                    except SystemExit:
                        pass
        self.assertEqual(captured['btt'], 12.5)

    def test_model_settings_controller_applied(self):
        """Test controller setting from model is applied to args"""
        self.create_log_file("2024-01-06T10:00:00.000 test pattern\n")
        model_path = self.create_model_file({
            'description': 'Test model.', 'settings': {'controller': True},
            'blocks': [{'label': 'T', 'file': 'test.log', 'patterns': ['test']}]
        })
        captured = {}

        def capture(args, *a, **kw):
            captured['ctrl'] = getattr(args, 'controller_setting', None)
            return (False, None, None, 0, [], [])

        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir
        ]):
            with patch('lpmptool.process_blocks_auto_detect', side_effect=capture):
                with patch('builtins.print'):
                    try:
                        lpmptool.main()
                    except SystemExit:
                        pass
        self.assertTrue(captured['ctrl'])

    def test_model_settings_optional_applied(self):
        """Test optional setting from model is applied to args"""
        self.create_log_file("2024-01-06T10:00:00.000 test pattern\n")
        model_path = self.create_model_file({
            'description': 'Test model.', 'settings': {'optional': True},
            'blocks': [{'label': 'T', 'file': 'test.log', 'patterns': ['test']}]
        })
        captured = {}

        def capture(args, *a, **kw):
            captured['opt'] = getattr(args, 'optional_setting', None)
            return (False, None, None, 0, [], [])

        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir
        ]):
            with patch('lpmptool.process_blocks_auto_detect', side_effect=capture):
                with patch('builtins.print'):
                    try:
                        lpmptool.main()
                    except SystemExit:
                        pass
        self.assertTrue(captured['opt'])

    def test_model_settings_max_log_length_applied(self):
        """Test max_log_length from model settings overrides default"""
        self.create_log_file("2024-01-06T10:00:00.000 test pattern\n")
        model_path = self.create_model_file({
            'description': 'Test model.', 'settings': {'max_log_length': 300},
            'blocks': [{'label': 'T', 'file': 'test.log', 'patterns': ['test']}]
        })
        captured = {}

        def capture(args, *a, **kw):
            captured['mll'] = args.max_log_length
            return (False, None, None, 0, [], [])

        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir
        ]):
            with patch('lpmptool.process_blocks_auto_detect', side_effect=capture):
                with patch('builtins.print'):
                    try:
                        lpmptool.main()
                    except SystemExit:
                        pass
        self.assertEqual(captured['mll'], 300)

    def test_list_models_displays_models(self):
        """Test --list-models finds and displays model files"""
        models_dir = os.path.join(self.temp_dir, 'models')
        os.makedirs(models_dir)
        for name in ['pattern_model.yaml', 'pair_model.yaml']:
            model = {
                'description': 'Test model.', 'blocks': [{'label': 'T', 'file': 'test.log', 'patterns': ['test']}]
            } if 'pattern' in name else {
                'description': 'Test model.', 'blocks': [{'label': 'T', 'file': 'test.log', 'start': 's', 'stop': 'e'}]
            }
            with open(os.path.join(models_dir, name), 'w') as f:
                yaml.dump(model, f)

        output = []

        def capture(*a, **kw):
            output.append(' '.join(str(x) for x in a))

        with patch('sys.argv', ['lpmptool', '--list-models']):
            with patch('lpmptool.get_models_search_paths', return_value=[models_dir]):
                with patch('builtins.print', side_effect=capture):
                    with self.assertRaises(SystemExit) as cm:
                        lpmptool.main()
                    self.assertEqual(cm.exception.code, 0)
        combined = '\n'.join(output)
        self.assertIn('pattern_model', combined)
        self.assertIn('pair_model', combined)

    def test_list_models_empty_directory(self):
        """Test --list-models with no model files found"""
        empty_dir = os.path.join(self.temp_dir, 'empty_models')
        os.makedirs(empty_dir)

        output = []

        def capture(*a, **kw):
            output.append(' '.join(str(x) for x in a))

        with patch('sys.argv', ['lpmptool', '--list-models']):
            with patch('lpmptool.get_models_search_paths', return_value=[empty_dir]):
                with patch('builtins.print', side_effect=capture):
                    with self.assertRaises(SystemExit) as cm:
                        lpmptool.main()
                    self.assertEqual(cm.exception.code, 0)

    # -----------------------------------------------------------------
    # --list-models: grouped output, dynamic columns, filter argument
    # -----------------------------------------------------------------

    def _make_test_models_dir(self):
        """Create a small tempdir containing one of each model type
        plus an example subdir and a helpers subdir, matching the real
        model tree layout expected by collect_model_files.
        """
        root = os.path.join(self.temp_dir, 'lm_models')
        os.makedirs(root)
        os.makedirs(os.path.join(root, 'examples'))
        os.makedirs(os.path.join(root, 'helpers'))

        # Two timeline models
        for name in ('timeline_alpha.yaml', 'timeline_bravo.yaml'):
            with open(os.path.join(root, name), 'w') as f:
                yaml.dump({
                    'description': 'Test timeline model.',
                    'blocks': [{'label': 'T', 'file': 't.log', 'timeline': ['x']}],
                }, f)

        # One pattern model
        with open(os.path.join(root, 'pattern_alpha.yaml'), 'w') as f:
            yaml.dump({
                'description': 'Test pattern model.',
                'blocks': [{'label': 'P', 'file': 't.log', 'patterns': ['x']}],
            }, f)

        # One pair model
        with open(os.path.join(root, 'pair_alpha.yaml'), 'w') as f:
            yaml.dump({
                'description': 'Test pair model.',
                'blocks': [{'label': 'PP', 'file': 't.log', 'start': 's', 'stop': 'e'}],
            }, f)

        # One example (in the examples subdir)
        with open(os.path.join(root, 'examples', 'example_alpha.yaml'), 'w') as f:
            yaml.dump({
                'description': 'Test example.',
                'blocks': [{'label': 'X', 'file': 't.log', 'patterns': ['x']}],
            }, f)

        # One helper
        with open(os.path.join(root, 'helpers', 'helper_alpha.yaml'), 'w') as f:
            yaml.dump({'timeline_patterns': {'shared': ['x']}}, f)

        return root

    def _run_lm(self, filter_arg=None, extra_argv=None, search_root=None):
        """Run lpmptool with --list-models (optionally with a filter)
        against a synthetic models tree and return the captured
        stdout lines. Raises AssertionError if exit code != 0.
        """
        root = search_root or self._make_test_models_dir()
        argv = ['lpmptool', '--list-models']
        if filter_arg is not None:
            argv.append(filter_arg)
        if extra_argv:
            argv.extend(extra_argv)

        output = []

        def capture(*a, **kw):
            output.append(' '.join(str(x) for x in a))

        with patch('sys.argv', argv):
            with patch('lpmptool.get_models_search_paths', return_value=[root]):
                with patch('builtins.print', side_effect=capture):
                    with self.assertRaises(SystemExit) as cm:
                        lpmptool.main()
        self.assertEqual(cm.exception.code, 0,
                         msg=f"non-zero exit: {'|'.join(output)}")
        return output, root

    def test_list_models_grouped_headers_present(self):
        """--list-models shows TIMELINE, PATTERN, PAIR, EXAMPLE, HELPER sections"""
        output, _ = self._run_lm()
        combined = '\n'.join(output)
        self.assertIn('TIMELINE MODELS', combined)
        self.assertIn('PATTERN MODELS', combined)
        self.assertIn('PAIR MODELS', combined)
        self.assertIn('EXAMPLE MODELS', combined)
        self.assertIn('HELPER FILES', combined)

    def test_list_models_summary_line(self):
        """Unfiltered listing ends with a total summary line"""
        output, _ = self._run_lm()
        combined = '\n'.join(output)
        self.assertRegex(combined, r'Total:\s+\d+\s+timeline')
        self.assertRegex(combined, r'\d+\s+pattern')
        self.assertRegex(combined, r'\d+\s+pair')

    def test_list_models_filter_timeline_only(self):
        """-lm timeline shows only TIMELINE MODELS section"""
        output, _ = self._run_lm(filter_arg='timeline')
        combined = '\n'.join(output)
        self.assertIn('TIMELINE MODELS', combined)
        self.assertNotIn('PATTERN MODELS', combined)
        self.assertNotIn('PAIR MODELS', combined)
        self.assertNotIn('EXAMPLE MODELS', combined)
        self.assertNotIn('HELPER FILES', combined)

    def test_list_models_filter_pattern_only(self):
        """-lm pattern shows only PATTERN MODELS section"""
        output, _ = self._run_lm(filter_arg='pattern')
        combined = '\n'.join(output)
        self.assertIn('PATTERN MODELS', combined)
        self.assertIn('pattern_alpha', combined)
        self.assertNotIn('TIMELINE MODELS', combined)
        self.assertNotIn('PAIR MODELS', combined)

    def test_list_models_filter_pair_only(self):
        """-lm pair shows only PAIR MODELS section"""
        output, _ = self._run_lm(filter_arg='pair')
        combined = '\n'.join(output)
        self.assertIn('PAIR MODELS', combined)
        self.assertIn('pair_alpha', combined)
        self.assertNotIn('TIMELINE MODELS', combined)
        self.assertNotIn('PATTERN MODELS', combined)

    def test_list_models_filter_example_only(self):
        """-lm example shows only EXAMPLE MODELS section"""
        output, _ = self._run_lm(filter_arg='example')
        combined = '\n'.join(output)
        self.assertIn('EXAMPLE MODELS', combined)
        self.assertIn('example_alpha', combined)
        self.assertNotIn('TIMELINE MODELS', combined)

    def test_list_models_invalid_filter_exits_1(self):
        """-lm <unknown> prints a helpful error and exits 1"""
        stderr_out = []

        def capture_err(*a, **kw):
            stderr_out.append(' '.join(str(x) for x in a))

        with patch('sys.argv', ['lpmptool', '--list-models', 'bogus']):
            with patch('lpmptool.get_models_search_paths',
                       return_value=[self._make_test_models_dir()]):
                with patch('builtins.print', side_effect=capture_err):
                    with self.assertRaises(SystemExit) as cm:
                        lpmptool.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertTrue(
            any('not recognized' in line for line in stderr_out),
            msg=f"expected error text not in stderr: {stderr_out}"
        )

    def test_list_models_columned_lines_within_max_width(self):
        """Grouped output rows never exceed DEFAULT_LIST_MODELS_MAX_WIDTH"""
        output, _ = self._run_lm()
        max_width = lpmptool.DEFAULT_LIST_MODELS_MAX_WIDTH
        overflow = [line for line in output if len(line) > max_width]
        self.assertEqual(
            overflow, [],
            msg=f"Lines exceed max width {max_width}: {overflow}"
        )

    def test_list_models_short_names_pack_more_columns(self):
        """Filtered view with only short names packs more columns
        than the unfiltered view whose longest name is longer.
        """
        # Build a dir where the timeline set has short names and
        # the pattern set has a long name.
        root = os.path.join(self.temp_dir, 'lm_cols')
        os.makedirs(root)
        for name in ('a.yaml', 'b.yaml', 'c.yaml', 'd.yaml', 'e.yaml', 'f.yaml'):
            with open(os.path.join(root, name), 'w') as f:
                yaml.dump({
                    'description': 'Test model.',
                    'blocks': [{'label': 'T', 'file': 't.log',
                                'timeline': ['x']}],
                }, f)
        # A pattern model with a very long name (37 chars w/o ext)
        long_pattern = 'this_is_an_extremely_long_pattern_mod.yaml'
        with open(os.path.join(root, long_pattern), 'w') as f:
            yaml.dump({
                'description': 'Test model.',
                'blocks': [{'label': 'P', 'file': 't.log',
                            'patterns': ['x']}],
            }, f)

        # Unfiltered: column width is dictated by the long pattern name.
        out_all, _ = self._run_lm(search_root=root)
        out_tl, _ = self._run_lm(filter_arg='timeline', search_root=root)

        def _cols_from_output(lines, section):
            """Count columns in the first data row of a given section."""
            in_sec = False
            for line in lines:
                if line.startswith(section):
                    in_sec = True
                    continue
                if in_sec and line.strip() and not line.startswith(('=', 'ERRORS')):
                    return len(line.split())
            return 0

        cols_all = _cols_from_output(out_all, 'TIMELINE MODELS')
        cols_tl = _cols_from_output(out_tl, 'TIMELINE MODELS')
        # Short-name-only filtered view packs at least as many columns
        # (usually more) as the unfiltered view constrained by long name.
        self.assertGreaterEqual(cols_tl, cols_all)

    def test_list_models_error_section_surfaces_broken_model(self):
        """A model with a YAML error appears in ERRORS section"""
        root = self._make_test_models_dir()
        # Add a broken model (invalid YAML with 'description: Test model.\nblocks:' text so
        # validate_model_file reports a yaml error).
        with open(os.path.join(root, 'broken.yaml'), 'w') as f:
            f.write('description: Test model.\nblocks:\n  - not valid : : :\n')
        output, _ = self._run_lm(search_root=root)
        combined = '\n'.join(output)
        self.assertIn('ERRORS', combined)
        self.assertIn('broken.yaml', combined)

    def test_list_models_description_key_accepted(self):
        """Models with a description: top-level key are accepted (no error)."""
        # _make_test_models_dir puts description: on every model.
        output, _ = self._run_lm()
        combined = '\n'.join(output)
        self.assertNotIn('ERRORS', combined)
        self.assertIn('timeline_alpha', combined)

    def test_list_models_filter_desc_flat_listing(self):
        """-lm desc produces a flat name:description list (no headers)"""
        output, _ = self._run_lm(filter_arg='desc')
        combined = '\n'.join(output)
        # Flat mode has no per-type headers.
        self.assertNotIn('TIMELINE MODELS', combined)
        self.assertNotIn('PATTERN MODELS', combined)
        self.assertNotIn('PAIR MODELS', combined)
        # But every model shows up with its description.
        self.assertIn('timeline_alpha', combined)
        self.assertIn('Test timeline model.', combined)
        self.assertIn('pattern_alpha', combined)
        self.assertIn('Test pattern model.', combined)
        self.assertIn('pair_alpha', combined)
        self.assertIn('Test pair model.', combined)
        # Header banner and total line still shown.
        self.assertIn('Available Model Descriptions', combined)
        self.assertRegex(combined, r'Total:\s+\d+\s+timeline')

    def test_list_models_filter_description_alias(self):
        """-lm description works as an alias for -lm desc"""
        root = self._make_test_models_dir()
        out_desc, _ = self._run_lm(filter_arg='desc', search_root=root)
        out_full, _ = self._run_lm(filter_arg='description', search_root=root)
        # Same header signals same code path.
        self.assertEqual(
            [ln for ln in out_desc if 'Available Model' in ln],
            [ln for ln in out_full if 'Available Model' in ln],
        )

    def test_list_models_desc_ordered_timeline_pattern_pair(self):
        """desc listing orders items timeline, pattern, pair, example."""
        output, _ = self._run_lm(filter_arg='desc')

        # Find the row index of each representative model
        def _idx(name):
            for i, line in enumerate(output):
                if line.startswith(name):
                    return i
            return -1
        t_idx = _idx('timeline_alpha')
        p_idx = _idx('pattern_alpha')
        pp_idx = _idx('pair_alpha')
        e_idx = _idx('example_alpha')
        # All models must be present.
        self.assertGreater(t_idx, 0)
        self.assertGreater(p_idx, 0)
        self.assertGreater(pp_idx, 0)
        self.assertGreater(e_idx, 0)
        # Ordering: timeline < pattern < pair < example.
        self.assertLess(t_idx, p_idx)
        self.assertLess(p_idx, pp_idx)
        self.assertLess(pp_idx, e_idx)

    def test_system_mode_loops_2_produces_two_passes(self):
        """Test loops=2 produces two pass summaries"""
        self.create_log_file(
            "2024-01-06T10:00:00.000 test pattern first\n"
            "2024-01-06T10:00:05.000 test pattern second\n"
            "2024-01-06T10:00:10.000 test pattern third\n"
        )
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='test pattern')
        )
        output = []

        def capture(*a, **kw):
            output.append(' '.join(str(x) for x in a))

        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '-n', '2', '--lab', 'testlab'
        ]):
            with patch('builtins.print', side_effect=capture):
                lpmptool.main()
        combined = '\n'.join(output)
        self.assertIn('Pass 1', combined)
        self.assertIn('Pass 2', combined)

    def test_system_mode_timeline_single_pass(self):
        """Test timeline model processes all data in one pass regardless of -n"""
        self.create_log_file(
            "2024-01-06T10:00:00.000 event alpha\n"
            "2024-01-06T10:00:01.000 event beta\n"
        )
        model_path = self.create_model_file({
            'description': 'Test model.', 'blocks': [{
                'label': 'Events',
                'file': 'test.log',
                'timeline': ['event alpha', 'event beta']
            }]
        })
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '-n', '5', '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        # Timeline should create output regardless of -n value
        output_files = []
        for root, dirs, files in os.walk(self.output_dir):
            output_files.extend(files)
        self.assertTrue(any('timeline.log' in f for f in output_files))

    def test_system_mode_loops_zero_until_eof(self):
        """Test loops=0 runs until EOF (finds pattern once, then stops)"""
        # Timestamps must be > block_time_tolerance (5s) apart so the tool
        # cannot re-match the same line within tolerance on the next pass
        self.create_log_file(
            "2024-01-06T10:00:00.000 test\n"
            "2024-01-06T10:00:10.000 test\n"
        )
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='test')
        )
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-n', '0', '-o', self.output_dir
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        # Verify output was created (tool ran successfully)
        output_files = []
        for root, dirs, files in os.walk(self.output_dir):
            output_files.extend(files)
        self.assertTrue(len(output_files) > 0)

    def test_system_mode_loops_negative_rejected(self):
        """Test negative loops value is rejected with error"""
        self.create_log_file("2024-01-06T10:00:00.000 test\n")
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='test')
        )
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-n', '-1'
        ]):
            with self.assertRaises(SystemExit) as cm:
                lpmptool.main()
            self.assertEqual(cm.exception.code, 1)

    def test_max_lines_negative_rejected(self):
        """Test negative --max-lines value is rejected with error"""
        self.create_log_file("2024-01-06T10:00:00.000 test\n")
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='test')
        )
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '--max-lines', '-1'
        ]):
            with patch('builtins.print'):
                with self.assertRaises(SystemExit) as cm:
                    lpmptool.main()
            self.assertEqual(cm.exception.code, 1)

    def test_file_position_tracking_enabled(self):
        """Test --file-position-tracking initialises position cache"""
        self.create_log_file("2024-01-06T10:00:00.000 fp_test pattern\n")
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='fp_test')
        )
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'fp_test',
            '--file-position-tracking',
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        # No assertion on internal state; the test exercises the
        # initialisation path. A successful run with output files
        # confirms the flag did not break the pipeline.
        produced = []
        for _root, _dirs, files in os.walk(self.output_dir):
            produced.extend(files)
        self.assertGreater(len(produced), 0)

    def test_help_model_direct_topic_number_prints_and_exits(self):
        """--help-model 1 prints a topic and exits zero (non-interactive)."""
        with patch('sys.argv', ['lpmptool', '--help-model', '1']):
            with patch('builtins.print'):
                with self.assertRaises(SystemExit) as cm:
                    lpmptool.main()
            self.assertEqual(cm.exception.code, 0)

    def test_help_model_direct_topic_invalid_exits_one(self):
        """--help-model with an unknown topic exits non-zero."""
        with patch('sys.argv', ['lpmptool', '--help-model', '999']):
            with patch('builtins.print'):
                with self.assertRaises(SystemExit) as cm:
                    lpmptool.main()
            self.assertEqual(cm.exception.code, 1)

    def test_no_ts_files_logs_dir_mode(self):
        """--no-ts-files in --logs-dir mode lists files and exits."""
        # Plain log with a parseable timestamp
        self.create_log_file(
            "2024-01-06T10:00:00.000 hello\n", filename='good.log')
        # File with no parseable timestamp at all
        self.create_log_file("just text, no date\n", filename='noisy.log')
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='hello'))
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '--no-ts-files',
        ]):
            with patch('builtins.print'):
                with self.assertRaises(SystemExit) as cm:
                    lpmptool.main()
            self.assertEqual(cm.exception.code, 0)

    def test_graph_variable_runs_subprocess_in_system_mode(self):
        """`--var graph=...` triggers lpmp_graph subprocess in system mode."""
        self.create_log_file(
            "2024-01-06T10:00:00.000 graph pattern match\n",
            filename='test.log')
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='graph pattern'))
        # Mock subprocess.run so we don't actually invoke matplotlib.
        with patch('sys.argv', [
            'lpmptool', '-l', self.logs_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'graph_test',
            '--var', 'graph=Test Graph',
        ]):
            with patch('builtins.print'):
                with patch('subprocess.run') as run_mock:
                    lpmptool.main()
        # Verify lpmp_graph was invoked at least once.
        self.assertGreaterEqual(run_mock.call_count, 1)
        invoked = run_mock.call_args_list[0].args[0]
        self.assertTrue(any('lpmp_graph.py' in part for part in invoked),
                        f"lpmp_graph.py not in invoked cmd {invoked}")
        self.assertIn('Test Graph', invoked)

    def test_bundle_mode_creates_per_host_output_dirs(self):
        """Test bundle mode creates output directories for each host"""
        bundle_dir, host_dirs = self.create_bundle_structure()
        for host_dir in host_dirs:
            logs_dir = os.path.join(host_dir, 'var', 'log')
            with open(os.path.join(logs_dir, 'test.log'), 'w') as f:
                f.write("2024-01-06T10:00:00.000 test pattern match\n")
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='test pattern')
        )
        with patch('sys.argv', [
            'lpmptool', '-b', bundle_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        all_dirs = []
        for root, dirs, files in os.walk(self.output_dir):
            all_dirs.extend(dirs)
        self.assertIn('controller-0', all_dirs)
        self.assertIn('controller-1', all_dirs)

    def test_bundle_mode_creates_per_host_output_files(self):
        """Test bundle mode creates timing and CSV files per host"""
        bundle_dir, host_dirs = self.create_bundle_structure()
        for host_dir in host_dirs:
            logs_dir = os.path.join(host_dir, 'var', 'log')
            with open(os.path.join(logs_dir, 'test.log'), 'w') as f:
                f.write("2024-01-06T10:00:00.000 test pattern match\n")
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='test pattern')
        )
        with patch('sys.argv', [
            'lpmptool', '-b', bundle_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        for hostname in ['controller-0', 'controller-1']:
            host_files = []
            for root, dirs, files in os.walk(self.output_dir):
                if hostname in root:
                    host_files.extend(files)
            self.assertTrue(
                any('profile.timing' in f for f in host_files),
                f"No profile.timing for {hostname}"
            )

    def test_bundle_mode_hostname_substitution_per_host(self):
        """Test bundle mode substitutes correct hostname per host"""
        bundle_dir, host_dirs = self.create_bundle_structure()
        for i, host_dir in enumerate(host_dirs):
            hostname = f'controller-{i}'
            logs_dir = os.path.join(host_dir, 'var', 'log')
            with open(os.path.join(logs_dir, 'test.log'), 'w') as f:
                f.write(f"2024-01-06T10:00:00.000 {hostname} started\n")
        model_path = self.create_model_file({
            'description': 'Test model.', 'blocks': [{
                'label': 'Host Start',
                'file': 'test.log',
                'patterns': ['{hostname} started']
            }]
        })
        with patch('sys.argv', [
            'lpmptool', '-b', bundle_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        all_files = []
        for root, dirs, files in os.walk(self.output_dir):
            all_files.extend(files)
        timing_files = [f for f in all_files if 'profile.timing' in f and '.csv' not in f]
        self.assertEqual(len(timing_files), 2, "Expected 2 per-host timing files")

    def test_bundle_mode_skips_host_with_missing_logs_dir(self):
        """Test bundle mode skips hosts with missing logs directory"""
        bundle_dir, host_dirs = self.create_bundle_structure()
        logs_dir_0 = os.path.join(host_dirs[0], 'var', 'log')
        with open(os.path.join(logs_dir_0, 'test.log'), 'w') as f:
            f.write("2024-01-06T10:00:00.000 test pattern match\n")
        import shutil
        shutil.rmtree(os.path.join(host_dirs[1], 'var', 'log'))
        model_path = self.create_model_file(
            self.create_pattern_model(pattern='test pattern')
        )
        with patch('sys.argv', [
            'lpmptool', '-b', bundle_dir, '-m', model_path,
            '-o', self.output_dir, '--lab', 'testlab'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        c0_files = []
        for root, dirs, files in os.walk(self.output_dir):
            if 'controller-0' in root:
                c0_files.extend(files)
        self.assertTrue(any('profile.timing' in f for f in c0_files))


@unittest.skipUnless(BUNDLE_AVAILABLE, f"Requires bundle at {BUNDLE_PATH}")
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestBundleRegression(LPMPTestBase):
    """Regression tests using a real collect bundle.
    Skipped when bundle path is not available.

    Host selection is dynamic: each test discovers the hostnames
    actually present in the bundle and passes that exact list to
    --include. This keeps the suite portable across bundles with
    different node counts and naming.
    """

    # Populated by setUpClass once per run from the bundle directory
    BUNDLE_HOSTS = []
    CONTROLLER_COUNT = 0
    WORKER_COUNT = 0
    STORAGE_COUNT = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.BUNDLE_HOSTS = cls._discover_bundle_hosts()
        cls.CONTROLLER_COUNT = sum(
            1 for h in cls.BUNDLE_HOSTS if h.startswith('controller-'))
        cls.WORKER_COUNT = sum(
            1 for h in cls.BUNDLE_HOSTS
            if h.startswith('worker-') or h.startswith('compute-'))
        cls.STORAGE_COUNT = sum(
            1 for h in cls.BUNDLE_HOSTS if h.startswith('storage-'))

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # Coverage note printed once after the regression class finishes.
        # Writes to real stderr so it bypasses run_tests.py's stdout/stderr
        # redirection to the log file.
        import sys as _sys
        msg = (
            f"\n[bundle regression] detected {len(cls.BUNDLE_HOSTS)} host(s): "
            f"{', '.join(cls.BUNDLE_HOSTS) if cls.BUNDLE_HOSTS else '(none)'}"
            f"  (controllers={cls.CONTROLLER_COUNT}, "
            f"workers={cls.WORKER_COUNT}, storage={cls.STORAGE_COUNT})"
        )
        print(msg, file=_sys.__stderr__)
        if cls.CONTROLLER_COUNT < 2 or cls.WORKER_COUNT < 1:
            print(
                "[bundle regression] coverage note: bundle has fewer than "
                "2 controllers and/or 1 worker. Provide a bundle with "
                "2+ controllers and 1+ worker (or compute) node to "
                "exercise full multi-host code paths.",
                file=_sys.__stderr__)

    @classmethod
    def _discover_bundle_hosts(cls):
        """Return hostnames present in the bundle (without date suffix),
        derived from the `<hostname>_YYYYMMDD.HHMMSS` directory pattern.
        """
        import re as _re
        if not BUNDLE_PATH or not os.path.isdir(BUNDLE_PATH):
            return []
        host_pattern = _re.compile(r'^(.+)_(\d{8}\.\d{6})$')
        latest = {}  # hostname -> (date, dir)
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
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(self.output_dir, exist_ok=True)
        self.models_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'models'
        )

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _build_argv(self, model_path, extra_args=None):
        """Build sys.argv for an lpmptool bundle run, scoped to whatever
        hosts the bundle actually has.
        """
        argv = [
            'lpmptool', '-b', BUNDLE_PATH, '-m', model_path,
            '-o', self.output_dir, '--lab', 'regression',
        ]
        if self.BUNDLE_HOSTS:
            argv.append('--include')
            argv.extend(self.BUNDLE_HOSTS)
        if extra_args:
            argv.extend(extra_args)
        return argv

    def test_bundle_timeline_model_produces_output(self):
        """Test timeline model against real bundle produces per-host output"""
        model_path = os.path.join(self.models_dir, 'mtce_timeline_model.yaml')
        if not os.path.exists(model_path):
            self.skipTest(f"Model not found: {model_path}")
        with patch('sys.argv', self._build_argv(model_path)):
            with patch('builtins.print'):
                lpmptool.main()
        # Verify output was created
        all_files = []
        for root, dirs, files in os.walk(self.output_dir):
            all_files.extend(files)
        self.assertGreater(len(all_files), 0, "No output files created")

    def test_bundle_output_has_per_host_dirs(self):
        """Test real bundle creates output directories for detected hosts"""
        model_path = os.path.join(self.models_dir, 'mtce_timeline_model.yaml')
        if not os.path.exists(model_path):
            self.skipTest(f"Model not found: {model_path}")
        with patch('sys.argv', self._build_argv(model_path)):
            with patch('builtins.print'):
                lpmptool.main()
        # Verify a per-host directory exists for at least one bundle host.
        all_dirs = []
        for root, dirs, files in os.walk(self.output_dir):
            all_dirs.extend(dirs)
        self.assertTrue(
            any(h in d for h in self.BUNDLE_HOSTS for d in all_dirs),
            f"No per-host directory in output for any of {self.BUNDLE_HOSTS}"
        )

    def test_bundle_merged_system_profile_created(self):
        """Test real bundle creates merged system profile or per-host profiles"""
        model_path = os.path.join(self.models_dir, 'mtce_timeline_model.yaml')
        if not os.path.exists(model_path):
            self.skipTest(f"Model not found: {model_path}")
        with patch('sys.argv', self._build_argv(model_path)):
            with patch('builtins.print'):
                lpmptool.main()
        # Verify some profile files were created (system or per-host)
        all_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                all_files.append(f)
        profile_files = [f for f in all_files if 'profile' in f]
        self.assertGreater(len(profile_files), 0, "No profile files created")

    def test_bundle_output_files_listed(self):
        """Test real bundle run lists output files at end"""
        model_path = os.path.join(self.models_dir, 'mtce_timeline_model.yaml')
        if not os.path.exists(model_path):
            self.skipTest(f"Model not found: {model_path}")
        output = []

        def capture(*a, **kw):
            output.append(' '.join(str(x) for x in a))

        with patch('sys.argv', self._build_argv(model_path)):
            with patch('builtins.print', side_effect=capture):
                lpmptool.main()
        combined = '\n'.join(output)
        self.assertIn('Output files:', combined)


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestMemoryMonitorAndMisc(LPMPTestBase):
    """Test MemoryMonitor, progress indicators, and console capture."""

    def test_memory_monitor_disabled_without_psutil(self):
        """Test MemoryMonitor gracefully disabled when psutil not available"""
        with patch.dict('lpmptool.__dict__', {'PSUTIL_AVAILABLE': False}):
            monitor = lpmptool.MemoryMonitor()
            self.assertFalse(monitor.enabled)
            self.assertEqual(monitor.update_peak('test'), 0)
            self.assertIsNone(monitor.get_stats())

    def test_memory_monitor_print_stats_no_duplicate(self):
        """Test print_stats handles disabled monitor gracefully"""
        with patch.dict('lpmptool.__dict__', {'PSUTIL_AVAILABLE': False}):
            monitor = lpmptool.MemoryMonitor()
            output = []
            with patch('builtins.print', side_effect=lambda *a, **kw: output.append(str(a))):
                monitor.print_stats()
            # Disabled monitor should print "not available" message
            self.assertTrue(any('not available' in s for s in output))

    def test_stats_flag_runs_without_error(self):
        """Test --stats flag doesn't crash even without psutil"""
        temp_dir = tempfile.mkdtemp()
        logs_dir = os.path.join(temp_dir, 'var', 'log')
        os.makedirs(logs_dir)
        with open(os.path.join(logs_dir, 'test.log'), 'w') as f:
            f.write("2024-01-06T10:00:00.000 test pattern\n")
        model_data = {
            'description': 'Test model.', 'blocks': [{'label': 'T', 'file': 'test.log', 'patterns': ['test']}]
        }
        model_path = os.path.join(temp_dir, 'model.yaml')
        with open(model_path, 'w') as f:
            yaml.dump(model_data, f)
        output_dir = os.path.join(temp_dir, 'out')
        with patch('sys.argv', [
            'lpmptool', '-l', logs_dir, '-m', model_path,
            '-o', output_dir, '--stats'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        import shutil
        shutil.rmtree(temp_dir)

    def test_console_capture_basic(self):
        """Test ConsoleCapture captures and returns output"""
        from lpmp_utils import ConsoleCapture
        capture = ConsoleCapture(silent_mode=False)
        capture.start_capture()
        print("test output line")
        capture.stop_capture()
        result = capture.get_captured_output()
        self.assertIn('test output line', result)

    def test_console_capture_silent_mode(self):
        """Test ConsoleCapture in silent mode suppresses console output"""
        from lpmp_utils import ConsoleCapture
        capture = ConsoleCapture(silent_mode=True)
        capture.start_capture()
        print("silent output")
        capture.stop_capture()
        result = capture.get_captured_output()
        self.assertIn('silent output', result)


# ---------------------------------------------------------------------------
# Bundle regression: custom timestamp format groups
# ---------------------------------------------------------------------------
# Each test exercises one of the four timestamp_formats groups declared in
# models/helpers/file_ignore_list_and_format_handling.yaml against a real
# collect bundle. A throw-away model is written that targets a single log
# file with a substring guaranteed to appear; if the engine fails to parse
# that file's timestamp format every line is silently dropped and the
# timeline output ends up empty, so a non-empty result proves the format
# is being recognised end-to-end.


@unittest.skipUnless(BUNDLE_AVAILABLE, f"Requires bundle at {BUNDLE_PATH}")
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestBundleCustomTimestampFormats(LPMPTestBase):
    """Verify each YAML-declared timestamp format actually parses in bundle mode.

    Skipped when --bundle is not provided. Each test gracefully skips
    when the target file is not present in any host of the bundle.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _build_mini_bundle(self, file_glob, pattern, max_lines=200):
        """Extract a small slice of one matching log from the real bundle
        into a self-contained temp bundle, and return its root path.

        The slice contains at least one line matching `pattern` and is
        capped at `max_lines` total lines. This keeps the engine's scan
        bounded to a small fixed-size file regardless of how large the
        source bundle's rotated copies are (charon.log* can be hundreds
        of MB; lpmptool reading and decompressing that for each format
        test is what made the suite slow).

        Returns None if no matching file with at least one matching line
        is found in the bundle — the caller skips the test in that case.
        """
        import glob
        import gzip
        if not BUNDLE_PATH or not os.path.isdir(BUNDLE_PATH):
            return None

        bare = file_glob.rstrip('*')
        for host_dir in sorted(os.listdir(BUNDLE_PATH)):
            host_path = os.path.join(BUNDLE_PATH, host_dir, 'var', 'log')
            if not os.path.isdir(host_path):
                continue
            candidates = sorted(
                set(glob.glob(os.path.join(host_path, bare))
                    + glob.glob(os.path.join(host_path, bare + '*'))))

            for src in candidates:
                try:
                    if src.endswith('.gz'):
                        opener = gzip.open
                    else:
                        opener = open
                    lines = []
                    found = False
                    with opener(src, 'rt', encoding='utf-8',
                                errors='ignore') as f:
                        for line in f:
                            lines.append(line)
                            if pattern in line:
                                found = True
                            if found and len(lines) >= max_lines:
                                break
                except (IOError, OSError):
                    continue

                if not found:
                    continue

                # Build a one-host mini bundle in self.temp_dir.
                mini_root = os.path.join(self.temp_dir, 'mini_bundle')
                mini_host_dir = 'controller-0_20260101.000000'
                # Compute the path of src relative to host's var/log so
                # subdirs like 'tuned/' are preserved.
                rel = os.path.relpath(src, host_path)
                if rel.endswith('.gz'):
                    rel = rel[:-3]  # write plain text
                dest = os.path.join(mini_root, mini_host_dir, 'var',
                                    'log', rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                return mini_root

        return None

    def _write_model(self, label, file_glob, pattern):
        """Write a one-off timeline model targeting a single file glob."""
        model_path = os.path.join(self.temp_dir, 'tsfmt_model.yaml')
        with open(model_path, 'w') as f:
            f.write("description: Test model.\nblocks:\n")
            f.write(f"  - label: \"{label}\"\n")
            f.write(f"    file: \"{file_glob}\"\n")
            f.write("    timeline:\n")
            f.write(f"      - '{pattern}'\n")
        return model_path

    def _run_against_bundle(self, bundle_root, model_path):
        """Run lpmptool against `bundle_root` and return the merged
        timeline log contents.

        Tolerates SystemExit since lpmptool may exit non-zero in some
        bundle layouts; the profile files (if any) are written before
        the exit and are what we inspect.
        """
        import io
        import contextlib
        with patch('sys.argv', [
            'lpmptool', '-b', bundle_root, '-m', model_path,
            '-o', self.output_dir, '--lab', 'tsfmt',
        ]):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    lpmptool.main()
                except SystemExit:
                    pass

        found = []
        for root, _dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('_profile.timeline.log'):
                    found.append(os.path.join(root, f))
        if not found:
            return ''
        body = []
        for path in found:
            try:
                with open(path, 'r') as fh:
                    body.append(fh.read())
            except IOError:
                pass
        return '\n'.join(body)

    def _assert_file_matches(self, file_glob, label, pattern, file_substring):
        """Common harness for the format tests.

        Builds a tiny self-contained bundle from one matching file in
        the real bundle (capped at 200 lines, with at least one
        matching line) and runs lpmptool against it. This exercises
        the full engine path (file walk, timestamp parse dispatch,
        timeline emit) while keeping per-test runtime under a second.
        """
        mini_root = self._build_mini_bundle(file_glob, pattern)
        if mini_root is None:
            self.skipTest(
                f"Bundle has no '{file_glob}' file containing '{pattern}'; "
                f"skipping format test")
        model_path = self._write_model(label, file_glob, pattern)
        body = self._run_against_bundle(mini_root, model_path)
        # The engine writes the matching file's basename into the Log File
        # column of every result row. Seeing it there proves the engine
        # successfully parsed timestamps from that file.
        self.assertIn(file_substring, body,
                      f"No timeline rows reference '{file_substring}' — "
                      f"timestamp format dispatch likely broken for "
                      f"{file_glob}.")

    # --- Format 1: "YYYY-MM-DD HH:MM:SS.fff" (dot-millis) ---------------

    def test_format1_ceph_manager_log(self):
        """ceph-manager.log uses 'YYYY-MM-DD HH:MM:SS.fff' (dot-millis)."""
        # 'HEALTH_OK' appears in ceph_client Result lines on healthy
        # systems, which is consistent across collect bundles. It's
        # selective without being so narrow it never matches.
        self._assert_file_matches(
            file_glob='ceph-manager.log*',
            label='ceph-manager timestamp parse',
            pattern='HEALTH_OK',
            file_substring='ceph-manager.log')

    def test_format1_fm_api_log(self):
        """fm-api.log uses 'YYYY-MM-DD HH:MM:SS.fff' (dot-millis)."""
        # 'WARNING' shows up in fm-api when alarms or events are
        # processed, present in typical bundles. Selective enough to
        # avoid the per-line 'INFO' problem.
        self._assert_file_matches(
            file_glob='fm-api.log*',
            label='fm-api timestamp parse',
            pattern='WARNING',
            file_substring='fm-api.log')

    # --- Format 2: "YY-MM-DD HH:MM:SS.fff" (2-digit year) ---------------

    def test_format2_charon_log(self):
        """charon.log uses '\\d{2}-\\d{2}-\\d{2} HH:MM:SS.fff' (2-digit year)."""
        # Use a selective phrase. 'LIB' (module tag) would match nearly every
        # line in a verbose strongSwan charon log and slow the test down a lot
        # without adding coverage. 'IKE_SA' appears in setup/teardown lines
        # only, which is sufficient to prove timestamp dispatch works.
        self._assert_file_matches(
            file_glob='charon.log*',
            label='charon timestamp parse',
            pattern='IKE_SA',
            file_substring='charon.log')

    # --- Format 3: "YYYY-MM-DD HH:MM:SS:" (trailing colon, no millis) ---

    def test_format3_lighttpd_error_log(self):
        """lighttpd-error.log uses 'YYYY-MM-DD HH:MM:SS:' (trailing colon)."""
        # Selective phrase. 'server' (without context) appears in the
        # '(server.c.NNN)' prefix on nearly every line.
        self._assert_file_matches(
            file_glob='lighttpd-error.log*',
            label='lighttpd timestamp parse',
            pattern='server started',
            file_substring='lighttpd-error.log')

    # --- Format 4: "YYYY-MM-DD HH:MM:SS,fff" (comma-millis) -------------

    def test_format4_tuned_log(self):
        """tuned/tuned.log uses 'YYYY-MM-DD HH:MM:SS,fff' (comma-millis)."""
        # Selective phrase. 'INFO' is the level on every line.
        self._assert_file_matches(
            file_glob='tuned/tuned.log*',
            label='tuned timestamp parse',
            pattern='static tuning',
            file_substring='tuned.log')

    def test_format4_mgr_restful_plugin_log(self):
        """mgr-restful-plugin.log uses 'YYYY-MM-DD HH:MM:SS,fff' (comma-millis)."""
        # 'init-wrapper' is the plugin's lifecycle wrapper module,
        # appears in start/stop/status lines and shows up in typical
        # bundles. Selective without being too narrow.
        self._assert_file_matches(
            file_glob='mgr-restful-plugin.log*',
            label='mgr-restful timestamp parse',
            pattern='init-wrapper',
            file_substring='mgr-restful-plugin.log')


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestEmptyOutputDirPruning(LPMPTestBase):
    """End-of-run cleanup: empty per-host / per-model directories that
    came from zero-match runs must not linger under
    <output>/lpmp_<lab>/.

    Batch mode already skips empty dir creation. Mainline used to
    leave the tree behind — this class locks in the bottom-up sweep
    that mirrors the batch behaviour.
    """

    def setUp(self):
        import shutil
        self.temp_dir = tempfile.mkdtemp()
        self.logs_dir = os.path.join(self.temp_dir, 'var', 'log')
        os.makedirs(self.logs_dir, exist_ok=True)
        self.output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_unmatchable_model(self):
        """Timeline model whose pattern will never match any log line
        so the run produces zero rows and would otherwise leave an
        empty output dir behind.
        """
        model = {
            'description': 'Empty-result timeline model.',
            'blocks': [{
                'label': 'Nope',
                'file': 'test.log',
                'timeline': ['UNMATCHABLE_TOKEN_ZZZZZZZ'],
            }],
        }
        path = os.path.join(self.temp_dir, 'nomatch.yaml')
        with open(path, 'w') as f:
            yaml.dump(model, f)
        return path

    def _write_log(self, content='2026-01-01T00:00:00.000 unrelated\n'):
        path = os.path.join(self.logs_dir, 'test.log')
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_zero_match_run_leaves_no_empty_directories(self):
        """Timeline run with no matches must not leave empty per-run
        directories under <output>/lpmp_<lab>/.
        """
        model = self._make_unmatchable_model()
        self._write_log()
        argv = [
            'lpmptool', '-m', model, '-l', self.logs_dir,
            '-o', self.output_dir, '--lab', 'pruning_lab',
        ]
        with patch('sys.argv', argv), \
                patch('sys.stdout'), patch('sys.stderr'):
            try:
                lpmptool.main()
            except SystemExit as e:
                # Timeline zero-match is not an error.
                self.assertIn(e.code, (0, None))

        # The tool-created wrapper 'lpmp_pruning_lab/' may or may not
        # exist depending on whether anything at all was written under
        # it. In this zero-match case the whole subtree must be gone.
        lpmp_root = os.path.join(self.output_dir, 'lpmp_pruning_lab')
        if os.path.exists(lpmp_root):
            # If the wrapper survived, it must contain no empty
            # <time>_<model> subdir left over from the zero-match run.
            for entry in os.listdir(lpmp_root):
                sub = os.path.join(lpmp_root, entry)
                self.assertTrue(
                    any(os.walk(sub)) and any(
                        files for _r, _d, files in os.walk(sub)
                    ),
                    msg=f"Empty subdir survived pruning: {sub}"
                )
        # The user-supplied -o directory itself is never touched.
        self.assertTrue(os.path.isdir(self.output_dir))


if __name__ == '__main__':
    unittest.main()
