#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for LPMP model file operations

Tests model file search, loading, validation, and includes:
- Model file search path precedence
- Host filtering (include/exclude)
- YAML model loading and settings
- Model include/merge functionality
- YAML validation and error handling
"""

from io import StringIO
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_utils import filter_hosts      # noqa: E402
from lpmp_utils import find_model_file   # noqa: E402
from lpmp_utils import load_model        # noqa: E402
from test_base import LPMPTestBase       # noqa: E402


class TestModelFileSearch(LPMPTestBase):
    """Test model file search path precedence"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        os.chdir(self.original_cwd)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_find_model_absolute_path(self):
        """Test finding model with absolute path (highest priority)"""
        model_path = os.path.join(self.temp_dir, 'test_model.yaml')
        with open(model_path, 'w') as f:
            f.write('blocks: []\n')

        result = find_model_file(model_path)
        self.assertEqual(result, model_path)

    def test_find_model_relative_path(self):
        """Test finding model with relative path containing separator"""
        os.makedirs('subdir', exist_ok=True)
        model_path = os.path.join('subdir', 'test_model.yaml')
        with open(model_path, 'w') as f:
            f.write('blocks: []\n')

        result = find_model_file(model_path)
        self.assertIsNotNone(result)
        self.assertTrue(os.path.exists(result))

    def test_find_model_in_models_dir(self):
        """Test finding model in ./models/ directory (priority 1)"""
        os.makedirs('models', exist_ok=True)
        model_path = os.path.join('models', 'test_model.yaml')
        with open(model_path, 'w') as f:
            f.write('blocks: []\n')

        result = find_model_file('test_model.yaml')
        self.assertEqual(result, model_path)

    def test_find_model_precedence_models_over_current(self):
        """Test that ./models/ takes precedence over current directory"""
        os.makedirs('models', exist_ok=True)

        # Create model in both locations
        models_path = os.path.join('models', 'test_model.yaml')
        with open(models_path, 'w') as f:
            f.write('# models dir\n')

        current_path = 'test_model.yaml'
        with open(current_path, 'w') as f:
            f.write('# current dir\n')

        result = find_model_file('test_model.yaml')
        # Should find models/ first (lower priority number = found first)
        self.assertEqual(result, models_path)

    def test_find_model_in_current_dir(self):
        """Test finding model in current directory when not in other locations"""
        model_path = 'test_model.yaml'
        with open(model_path, 'w') as f:
            f.write('blocks: []\n')

        result = find_model_file('test_model.yaml')
        self.assertEqual(result, model_path)

    def test_find_model_not_found(self):
        """Test that None is returned when model file doesn't exist"""
        result = find_model_file('nonexistent.yaml')
        self.assertIsNone(result)

    def test_find_model_without_extension(self):
        """Test finding model without .yaml extension"""
        os.makedirs('models', exist_ok=True)
        model_path = os.path.join('models', 'test_model.yaml')
        with open(model_path, 'w') as f:
            f.write('blocks: []\n')

        result = find_model_file('test_model')
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith('test_model.yaml'))

    def test_find_model_without_extension_matches_with_extension(self):
        """Test extensionless and with-extension resolve to same file"""
        os.makedirs('models', exist_ok=True)
        model_path = os.path.join('models', 'test_model.yaml')
        with open(model_path, 'w') as f:
            f.write('blocks: []\n')

        result_ext = find_model_file('test_model.yaml')
        result_no_ext = find_model_file('test_model')
        self.assertEqual(result_ext, result_no_ext)

    def test_find_model_without_extension_not_found(self):
        """Test extensionless search returns None when no match"""
        result = find_model_file('nonexistent_model')
        self.assertIsNone(result)

    def test_find_model_absolute_not_found(self):
        """Test that None is returned for non-existent absolute path"""
        model_path = os.path.join(self.temp_dir, 'nonexistent.yaml')
        result = find_model_file(model_path)
        self.assertIsNone(result)

    def test_filter_hosts_include_valid(self):
        """Test include mode with valid hosts"""
        hostnames = ['controller-0', 'controller-1', 'worker-0']
        dated_dirs = ['controller-0_20251218.082339', 'controller-1_20251218.082339',
                      'worker-0_20251218.082339']

        filtered_hosts, filtered_dated = filter_hosts(
            hostnames, dated_dirs, ['controller-0', 'worker-0'], mode='include')

        self.assertEqual(filtered_hosts, ['controller-0', 'worker-0'])
        self.assertEqual(filtered_dated, ['controller-0_20251218.082339', 'worker-0_20251218.082339'])

    def test_filter_hosts_exclude_valid(self):
        """Test exclude mode with valid hosts"""
        hostnames = ['controller-0', 'controller-1', 'worker-0']
        dated_dirs = ['controller-0_20251218.082339', 'controller-1_20251218.082339',
                      'worker-0_20251218.082339']

        filtered_hosts, filtered_dated = filter_hosts(
            hostnames, dated_dirs, ['worker-0'], mode='exclude')

        self.assertEqual(filtered_hosts, ['controller-0', 'controller-1'])
        self.assertEqual(filtered_dated, ['controller-0_20251218.082339', 'controller-1_20251218.082339'])

    def test_filter_hosts_invalid_hostname(self):
        """Test error when invalid hostname provided"""
        hostnames = ['controller-0', 'controller-1']
        dated_dirs = ['controller-0_20251218.082339', 'controller-1_20251218.082339']

        with self.assertRaises(SystemExit):
            filter_hosts(hostnames, dated_dirs, ['invalid-host'], mode='include')

    def test_filter_hosts_include_all_excluded(self):
        """Test error when include results in no hosts"""
        hostnames = ['controller-0', 'controller-1']
        dated_dirs = ['controller-0_20251218.082339', 'controller-1_20251218.082339']

        with self.assertRaises(SystemExit):
            filter_hosts(hostnames, dated_dirs, ['worker-0'], mode='include')

    def test_filter_hosts_exclude_all(self):
        """Test error when exclude results in no hosts"""
        hostnames = ['controller-0', 'controller-1']
        dated_dirs = ['controller-0_20251218.082339', 'controller-1_20251218.082339']

        with self.assertRaises(SystemExit):
            filter_hosts(hostnames, dated_dirs, ['controller-0', 'controller-1'],
                         mode='exclude')

    def test_filter_hosts_include_single(self):
        """Test include with single host"""
        hostnames = ['controller-0', 'controller-1', 'worker-0']
        dated_dirs = ['controller-0_20251218.082339', 'controller-1_20251218.082339',
                      'worker-0_20251218.082339']

        filtered_hosts, filtered_dated = filter_hosts(
            hostnames, dated_dirs, ['controller-0'], mode='include')

        self.assertEqual(filtered_hosts, ['controller-0'])
        self.assertEqual(len(filtered_dated), 1)

    def test_filter_hosts_exclude_single(self):
        """Test exclude with single host"""
        hostnames = ['controller-0', 'controller-1', 'worker-0']
        dated_dirs = ['controller-0_20251218.082339', 'controller-1_20251218.082339',
                      'worker-0_20251218.082339']

        filtered_hosts, filtered_dated = filter_hosts(
            hostnames, dated_dirs, ['worker-0'], mode='exclude')

        self.assertEqual(filtered_hosts, ['controller-0', 'controller-1'])
        self.assertEqual(len(filtered_dated), 2)

    def test_filter_hosts_verbose_output(self):
        """Test verbose output shows filtered hosts"""
        hostnames = ['controller-0', 'controller-1']
        dated_dirs = ['controller-0_20251218.082339', 'controller-1_20251218.082339']

        # Set verbose level to enable vlog1 output
        from lpmp_utils import set_verbose_level
        set_verbose_level(1)

        with patch('builtins.print') as mock_print:
            filter_hosts(hostnames, dated_dirs, ['controller-0'], mode='include')
            mock_print.assert_called_once()
            call_str = str(mock_print.call_args)
            self.assertIn('Processing hosts', call_str)
            self.assertIn('include', call_str)

        # Reset verbose level
        set_verbose_level(0)


# Disabled unless PyYAML is installed (pip3 install --user pyyaml)
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestModelLoading(unittest.TestCase):
    """Test YAML model loading functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, "test_model.yaml")

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.model_file):
            os.remove(self.model_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_load_pattern_model(self):
        """Test loading pattern block model"""
        model_data = {
            'blocks': [
                {
                    'label': 'Test Pattern',
                    'file': 'test.log',
                    'patterns': ['test pattern']
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['label'], 'Test Pattern')
        self.assertEqual(blocks[0]['patterns'], ['test pattern'])

    def test_load_pair_model(self):
        """Test loading pair block model"""
        model_data = {
            'blocks': [
                {
                    'label': 'Trigger',
                    'file': 'test.log',
                    'patterns': ['trigger pattern']
                },
                {
                    'label': 'Test Pair',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern'
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[1]['label'], 'Test Pair')
        self.assertEqual(blocks[1]['start'], 'start pattern')
        self.assertEqual(blocks[1]['stop'], 'stop pattern')

    def test_load_model_with_settings(self):
        """Test loading model with global settings"""
        model_data = {
            'blocks': [
                {
                    'label': 'Test',
                    'file': 'test.log',
                    'patterns': ['test']
                }
            ],
            'settings': {
                'max_time_delta': 60,
                'loops': 3
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(settings['max_time_delta'], 60)
        self.assertEqual(settings['loops'], 3)

    def test_load_missing_model(self):
        """Test handling of missing model file"""
        with self.assertRaises(SystemExit):
            load_model("nonexistent.yaml")

    def test_load_invalid_yaml(self):
        """Test handling of invalid YAML syntax"""
        with open(self.model_file, 'w') as f:
            f.write("invalid: yaml: content: [unclosed")

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_load_model_missing_blocks(self):
        """Test handling of model file without blocks section"""
        model_data = {
            'settings': {
                'max_time_delta': 60
            }
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_load_model_invalid_pattern_block(self):
        """Test handling of pattern block missing required fields"""
        model_data = {
            'blocks': [
                {
                    'label': 'Incomplete Block',
                    # Missing 'file' and 'patterns' fields
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_load_model_invalid_pair_block(self):
        """Test handling of pair block missing required fields"""
        model_data = {
            'blocks': [
                {
                    'label': 'Incomplete Pair Block',
                    'file': 'test.log',
                    'start': 'start pattern'
                    # Missing 'stop' field
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_load_empty_model_file(self):
        """Test handling of empty model file"""
        with open(self.model_file, 'w') as f:
            pass  # Create empty file

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_load_model_with_block_level_max_time_delta(self):
        """Test loading model with block-level max_time_delta"""
        model_data = {
            'blocks': [
                {
                    'label': 'Test Block Level Setting',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern',
                    'max_time_delta': 120
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['max_time_delta'], 120)
        self.assertEqual(blocks[0]['label'], 'Test Block Level Setting')

    def test_load_model_mixed_max_time_delta_settings(self):
        """Test loading model with mixed block-level and no max_time_delta"""
        model_data = {
            'blocks': [
                {
                    'label': 'Block Without Setting',
                    'file': 'test.log',
                    'patterns': ['test pattern']
                },
                {
                    'label': 'Block With Setting',
                    'file': 'test.log',
                    'start': 'start pattern',
                    'stop': 'stop pattern',
                    'max_time_delta': 60
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 2)
        # Block without explicit max_time_delta should not have the key
        self.assertNotIn('max_time_delta', blocks[0])
        self.assertEqual(blocks[1]['max_time_delta'], 60)


# Disabled unless PyYAML is installed (pip3 install --user pyyaml)
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestModelIncludes(unittest.TestCase):
    """Test model include handling and settings merge"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, "model.yaml")
        self.include_file = os.path.join(self.temp_dir, "include.yaml")

    def tearDown(self):
        """Clean up test fixtures"""
        for path in [self.model_file, self.include_file]:
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_include_settings_merge(self):
        """Test include merges settings and allows local overrides"""
        include_data = {
            'settings': {
                'loops': 2,
                'timeline_patterns': {
                    'maintenance': ['A', 'B'],
                    'sm': ['S1']
                }
            }
        }
        model_data = {
            'include': 'include.yaml',
            'blocks': [
                {'label': 'Test', 'file': 'test.log', 'patterns': ['test']}
            ],
            'settings': {
                'max_log_length': 200,
                'timeline_patterns': {
                    'maintenance': ['C']
                }
            }
        }

        with open(self.include_file, 'w') as f:
            yaml.dump(include_data, f)
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(settings['loops'], 2)
        self.assertEqual(settings['max_log_length'], 200)
        self.assertEqual(settings['timeline_patterns']['maintenance'], ['C'])
        self.assertEqual(settings['timeline_patterns']['sm'], ['S1'])


# Disabled unless PyYAML is installed (pip3 install --user pyyaml)
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestYAMLValidation(unittest.TestCase):
    """Test YAML model file validation"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, "test_model.yaml")

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.model_file):
            os.remove(self.model_file)
        if os.path.exists(self.temp_dir):
            os.rmdir(self.temp_dir)

    def test_missing_blocks_section(self):
        """Test error when 'blocks' section is missing"""
        model_data = {'settings': {'loops': 1}}
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            with patch('sys.stderr', new_callable=StringIO) as mock_stderr:
                load_model(self.model_file)
                self.assertIn("missing required 'blocks:' section", mock_stderr.getvalue())

    def test_empty_blocks_list(self):
        """Test error when 'blocks' list is empty"""
        model_data = {'blocks': []}
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_missing_label_field(self):
        """Test error when block is missing 'label' field"""
        model_data = {
            'blocks': [
                {'file': 'test.log', 'patterns': ['test']}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_missing_file_field(self):
        """Test error when block is missing 'file' field"""
        model_data = {
            'blocks': [
                {'label': 'Test', 'patterns': ['test']}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_missing_patterns_and_start_stop(self):
        """Test error when block has neither 'patterns' nor 'start'/'stop'"""
        model_data = {
            'blocks': [
                {'label': 'Test', 'file': 'test.log'}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_start_without_stop(self):
        """Test error when block has 'start' but no 'stop'"""
        model_data = {
            'blocks': [
                {'label': 'Test', 'file': 'test.log', 'start': 'start pattern'}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_stop_without_start(self):
        """Test error when block has 'stop' but no 'start'"""
        model_data = {
            'blocks': [
                {'label': 'Test', 'file': 'test.log', 'stop': 'stop pattern'}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_blocks_not_list(self):
        """Test error when 'blocks' is not a list"""
        model_data = {'blocks': 'not a list'}
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_block_not_dict(self):
        """Test error when block is not a dictionary"""
        model_data = {'blocks': ['not a dict']}
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)


if __name__ == '__main__':
    unittest.main()
