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
BUNDLE_SKIPPED_COUNT = 4  # Number of tests that require --bundle

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
            'blocks': [
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
            'blocks': [{
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
            'blocks': [{
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
            'settings': {'block_time_tolerance': 12.5},
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
            'settings': {'controller': True},
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
            'settings': {'optional': True},
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
            'settings': {'max_log_length': 300},
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
                'blocks': [{'label': 'T', 'file': 'test.log', 'patterns': ['test']}]
            } if 'pattern' in name else {
                'blocks': [{'label': 'T', 'file': 'test.log', 'start': 's', 'stop': 'e'}]
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
            'blocks': [{
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
            'blocks': [{
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
    """

    def setUp(self):
        import shutil
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

    def test_bundle_timeline_model_produces_output(self):
        """Test timeline model against real bundle produces per-host output"""
        model_path = os.path.join(self.models_dir, 'mtce_timeline_model.yaml')
        if not os.path.exists(model_path):
            self.skipTest(f"Model not found: {model_path}")
        with patch('sys.argv', [
            'lpmptool', '-b', BUNDLE_PATH, '-m', model_path,
            '-o', self.output_dir, '--lab', 'regression',
            '--include', 'controller-0', 'controller-1', 'compute-0'
        ]):
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
        with patch('sys.argv', [
            'lpmptool', '-b', BUNDLE_PATH, '-m', model_path,
            '-o', self.output_dir, '--lab', 'regression',
            '--include', 'controller-0', 'controller-1', 'compute-0'
        ]):
            with patch('builtins.print'):
                lpmptool.main()
        # Verify per-host directories exist
        all_dirs = []
        for root, dirs, files in os.walk(self.output_dir):
            all_dirs.extend(dirs)
        self.assertTrue(
            any('controller' in d for d in all_dirs),
            "No controller host directory in output"
        )

    def test_bundle_merged_system_profile_created(self):
        """Test real bundle creates merged system profile or per-host profiles"""
        model_path = os.path.join(self.models_dir, 'mtce_timeline_model.yaml')
        if not os.path.exists(model_path):
            self.skipTest(f"Model not found: {model_path}")
        with patch('sys.argv', [
            'lpmptool', '-b', BUNDLE_PATH, '-m', model_path,
            '-o', self.output_dir, '--lab', 'regression',
            '--include', 'controller-0', 'controller-1', 'compute-0'
        ]):
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

        with patch('sys.argv', [
            'lpmptool', '-b', BUNDLE_PATH, '-m', model_path,
            '-o', self.output_dir, '--lab', 'regression',
            '--include', 'controller-0', 'controller-1', 'compute-0'
        ]):
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
            'blocks': [{'label': 'T', 'file': 'test.log', 'patterns': ['test']}]
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


if __name__ == '__main__':
    unittest.main()
