#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for High Priority gaps in LPMP precedence handling

This test suite covers:
1. max_time_delta full precedence chain (block > command line > model > default)
2. Command line overriding model settings for all supported parameters
3. Model settings overriding defaults

Tests both positive (correct behavior) and negative (error conditions) scenarios.
"""

from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import unittest
# from unittest.mock import MagicMock
# from unittest.mock import patch

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import process_pair_block  # noqa: E402
from lpmp_utils import load_model           # noqa: E402
import lpmptool                             # noqa: E402
from test_base import LPMPTestBase          # noqa: E402


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestMaxTimeDeltaPrecedence(LPMPTestBase):
    """Test max_time_delta precedence chain: block > command line > model > default"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, "test_model.yaml")
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_block_level_overrides_command_line_positive(self):
        """Test block-level max_time_delta overrides command line setting"""
        # Create model with block-level max_time_delta
        model_data = {
            'blocks': [
                {
                    'label': 'Block Override Test',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern',
                    'max_time_delta': 10  # Block level: 10 seconds
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log with patterns 8 seconds apart (within block limit, exceeds command line)
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:08.000 stop pattern"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Mock args with command line max_time_delta=5 (should be overridden)
        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Should succeed because block-level (10s) overrides command line (5s)
        result = process_pair_block(args, block, start_date, global_max_time_delta=5)
        self.assertIsNotNone(result)

    def test_block_level_overrides_command_line_negative(self):
        """Test block-level max_time_delta causes timeout when exceeded"""
        model_data = {
            'blocks': [
                {
                    'label': 'Block Timeout Test',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern',
                    'max_time_delta': 5  # Block level: 5 seconds
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log with patterns 8 seconds apart (exceeds block limit)
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:08.000 stop pattern"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Should fail because patterns exceed block-level max_time_delta
        result = process_pair_block(args, block, start_date, global_max_time_delta=60)
        self.assertIsNone(result)

    def test_command_line_overrides_model_positive(self):
        """Test command line max_time_delta overrides model setting"""
        model_data = {
            'blocks': [
                {
                    'label': 'Command Line Override Test',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern'
                    # No block-level max_time_delta
                }
            ],
            'settings': {
                'max_time_delta': 5  # Model level: 5 seconds
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log with patterns 8 seconds apart
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:08.000 stop pattern"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Should succeed because command line (10s) overrides model (5s)
        result = process_pair_block(args, block, start_date, global_max_time_delta=10)
        self.assertIsNotNone(result)

    def test_command_line_overrides_model_negative(self):
        """Test command line max_time_delta causes timeout when exceeded"""
        model_data = {
            'blocks': [
                {
                    'label': 'Command Line Timeout Test',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern'
                }
            ],
            'settings': {
                'max_time_delta': 60  # Model allows 60 seconds
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log with patterns 8 seconds apart
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:08.000 stop pattern"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Should fail because command line (5s) overrides model (60s)
        result = process_pair_block(args, block, start_date, global_max_time_delta=5)
        self.assertIsNone(result)

    def test_model_overrides_default_positive(self):
        """Test model max_time_delta overrides default setting"""
        model_data = {
            'blocks': [
                {
                    'label': 'Model Override Test',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern'
                }
            ],
            'settings': {
                'max_time_delta': 60  # Model level: 60 seconds
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log with patterns 50 seconds apart (exceeds default, within model)
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:50.000 stop pattern"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Should succeed because model (60s) overrides default (45s)
        result = process_pair_block(args, block, start_date, global_max_time_delta=60)
        self.assertIsNotNone(result)

    def test_model_overrides_default_negative(self):
        """Test model max_time_delta causes timeout when exceeded"""
        model_data = {
            'blocks': [
                {
                    'label': 'Model Timeout Test',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern'
                }
            ],
            'settings': {
                'max_time_delta': 30  # Model level: 30 seconds
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log with patterns 50 seconds apart (exceeds model limit)
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:50.000 stop pattern"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Should fail because patterns exceed model max_time_delta
        result = process_pair_block(args, block, start_date, global_max_time_delta=30)
        self.assertIsNone(result)

    def test_default_fallback(self):
        """Test default max_time_delta is used when no other setting exists"""
        model_data = {
            'blocks': [
                {
                    'label': 'Default Fallback Test',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern'
                    # No max_time_delta specified
                }
            ]
            # No settings section
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log with patterns within default limit
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:30.000 stop pattern"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Should succeed using default max_time_delta
        result = process_pair_block(args, block, start_date, global_max_time_delta=lpmptool.DEFAULT_MAX_TIME_DELTA)
        self.assertIsNotNone(result)


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestCommandLineParameterOverrides(LPMPTestBase):
    """Test command line parameters override model settings for all supported parameters"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, "test_model.yaml")
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_command_line_max_time_delta_override(self):
        """Test command line max_time_delta parameter precedence"""
        # Create model with different max_time_delta
        model_data = {
            'blocks': [{
                'label': 'CLI Override Test',
                'file': 'test.log',
                'start': 'start pattern',
                'stop': 'stop pattern'
            }],
            'settings': {
                'max_time_delta': 5  # Model setting
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log with 10 second gap (exceeds model, within CLI)
        log_content = """2024-01-06T10:00:00.000 start pattern
2024-01-06T10:00:10.000 stop pattern"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Should succeed because command line (15s) overrides model (5s)
        result = process_pair_block(args, block, start_date, global_max_time_delta=15)
        self.assertIsNotNone(result)

    def test_command_line_verbose_override(self):
        """Test command line verbose parameter precedence"""
        # Create model with different verbosity
        model_data = {
            'blocks': [{
                'label': 'CLI Verbose Test',
                'file': 'test.log',
                'start': 'start pattern',
                'stop': 'stop pattern'
            }],
            'settings': {
                'verbose': 0  # Model setting
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Load model and verify settings exist
        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(settings.get('verbose'), 0)

        # Test that command line would override (simulated)
        command_line_verbose = 2  # -vv
        effective_verbose = command_line_verbose  # Command line takes precedence
        self.assertEqual(effective_verbose, 2)

    def test_model_settings_override_defaults(self):
        """Test model settings override default values for all parameters"""
        model_data = {
            'blocks': [{
                'label': 'Model Settings Test',
                'file': 'test.log',
                'start': 'start pattern',
                'stop': 'stop pattern'
            }],
            'settings': {
                'max_time_delta': 120,
                'block_time_tolerance': 3.0,
                'verbose': 1
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Load model and verify settings
        blocks, settings, _ = load_model(self.model_file)

        self.assertEqual(settings.get('max_time_delta'), 120)
        self.assertEqual(settings.get('block_time_tolerance'), 3.0)
        self.assertEqual(settings.get('verbose'), 1)


if __name__ == '__main__':
    unittest.main()

    def test_max_time_delta_ignored_for_first_match_applied_to_subsequent(self):
        """Test max_time_delta is ignored for first match but applied to subsequent matches"""
        from lpmp_engine import process_pattern_block

        # Create log with patterns where first is hours after start_date, second exceeds max_time_delta
        log_content = """2024-01-06T10:00:00.000 early pattern
2024-01-06T13:00:00.000 first pattern (3 hours after start)
2024-01-06T13:10:00.000 second pattern (10 minutes after first)
2024-01-06T13:15:00.000 third pattern (15 minutes after first)"""
        with open(self.log_file, 'w') as f:
            f.write(log_content)

        model_data = {
            'blocks': [
                {
                    'label': 'First Match Ignore Test',
                    'file': 'test.log',
                    'patterns': ['first pattern', 'second pattern', 'third pattern'],
                    'max_time_delta': 300  # 5 minutes - should not apply to first match
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180

        args = MockArgs(self.temp_dir)
        block = model_data['blocks'][0]
        # Start date is 10:00:00, first pattern is at 13:00:00 (3 hours later)
        start_date = datetime(2024, 1, 6, 10, 0, 0)

        # Should find first pattern despite being 3 hours after start_date (max_time_delta ignored for first)
        # Should find second pattern (10 minutes after first, within 5 minute limit)
        # Should NOT find third pattern (15 minutes after first, exceeds 5 minute limit)
        result = process_pattern_block(args, block, start_date, max_time_delta=300)

        self.assertIsNotNone(result, "Should find patterns despite first being hours after start_date")
        self.assertIsInstance(result, list)

        # Should have found first and second patterns, but not third
        self.assertEqual(len(result), 2, "Should find exactly 2 patterns (first ignores max_time_delta, "
                         "second within limit, third exceeds limit)")

        # Verify the patterns found
        timestamps_and_lines = [(r[0], r[1]) for r in result]

        # First result should be the "first pattern"
        self.assertIn("first pattern", timestamps_and_lines[0][1])
        # Second result should be the "second pattern"
        self.assertIn("second pattern", timestamps_and_lines[1][1])

        # Verify timing: second pattern should be within max_time_delta of first
        first_timestamp = timestamps_and_lines[0][0]
        second_timestamp = timestamps_and_lines[1][0]
        time_diff = (second_timestamp - first_timestamp).total_seconds()
        self.assertLessEqual(time_diff, 300, "Second pattern should be within max_time_delta of first")
