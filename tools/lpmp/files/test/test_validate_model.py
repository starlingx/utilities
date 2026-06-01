#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for LPMP model file validation (validate_model_file)

Tests the YAML validation used by --list-models to filter and warn:
- Valid models return (True, model_type) with correct type detection
- YAML parse errors with blocks: text return (True, None) for yaml error
- YAML files without blocks return (False, None) and are excluded
- Non-YAML content, empty files, missing files are excluded
"""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_utils import validate_model_file       # noqa: E402
from lpmp_utils import validate_model_structure   # noqa: E402


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestValidateModelFile(unittest.TestCase):
    """Test validate_model_file used by --list-models"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write(self, filename, content):
        path = os.path.join(self.temp_dir, filename)
        with open(path, 'w') as f:
            f.write(content)
        return path

    # --- Valid models: accepted with model type ---

    def test_valid_pattern_model(self):
        """Valid pattern block model returns type 'pattern'"""
        path = self._write('m.yaml',
                           'blocks:\n  - label: "T"\n    file: "t.log"\n    patterns:\n      - "p"\n')
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertEqual(status, 'pattern')

    def test_valid_pair_model(self):
        """Valid pair block model returns type 'pair'"""
        path = self._write('m.yaml',
                           'blocks:\n  - label: "T"\n    file: "t.log"\n    start: "s"\n    stop: "e"\n')
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertEqual(status, 'pair')

    def test_valid_timeline_model(self):
        """Valid timeline block model returns type 'timeline'"""
        path = self._write('m.yaml',
                           'blocks:\n  - label: "T"\n    file: "t.log"\n    timeline:\n      - "event"\n')
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertEqual(status, 'timeline')

    def test_valid_window_model_returns_timeline_type(self):
        """Valid window block model returns type 'timeline'"""
        path = self._write('m.yaml',
                           'blocks:\n  - label: "T"\n    file: "*.log*"\n    window: true\n')
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertEqual(status, 'timeline')

    def test_valid_model_with_settings(self):
        """Valid model with settings section accepted"""
        path = self._write('m.yaml',
                           'settings:\n  loops: 2\nblocks:\n  - label: "T"\n    file: "t.log"\n    patterns:\n      - "p"\n')  # noqa E501
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertEqual(status, 'pattern')

    def test_valid_empty_blocks_list(self):
        """Model with empty blocks list defaults to 'pattern'"""
        path = self._write('m.yaml', 'blocks: []\n')
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertEqual(status, 'pattern')

    def test_valid_model_with_include(self):
        """Model with include and blocks accepted"""
        path = self._write('m.yaml',
                           'include: shared.yaml\nblocks:\n  - label: "T"\n    file: "t.log"\n    patterns:\n      - "p"\n')  # noqa E501
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertEqual(status, 'pattern')

    # --- YAML errors with blocks: text show yaml error ---

    def test_yaml_error_with_blocks_keyword(self):
        """YAML parse error with blocks: returns error detail"""
        path = self._write('m.yaml',
                           'blocks:\n  - label: "Test\n    file: [unclosed\n')
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertTrue(status.startswith('yaml error'))

    def test_yaml_error_tab_indentation(self):
        """YAML tab error with blocks: returns error with line number"""
        path = self._write('m.yaml',
                           'blocks:\n\t- label: "Test"\n\t  file: "t.log"\n')
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertIn('yaml error', status)
        self.assertIn('line', status)

    # --- Excluded: no blocks key ---

    def test_settings_only_no_blocks(self):
        """YAML with settings but no blocks excluded"""
        path = self._write('m.yaml', 'settings:\n  loops: 2\n')
        valid, status = validate_model_file(path)
        self.assertFalse(valid)
        self.assertIsNone(status)

    def test_plain_yaml_no_blocks(self):
        """Plain YAML dict without blocks excluded"""
        path = self._write('m.yaml', 'name: test\nvalue: 123\n')
        valid, status = validate_model_file(path)
        self.assertFalse(valid)
        self.assertIsNone(status)

    def test_yaml_list_not_dict(self):
        """YAML that parses as a list excluded"""
        path = self._write('m.yaml', '- item1\n- item2\n')
        valid, status = validate_model_file(path)
        self.assertFalse(valid)
        self.assertIsNone(status)

    def test_yaml_scalar_not_dict(self):
        """YAML that parses as a scalar excluded"""
        path = self._write('m.yaml', 'just a string\n')
        valid, status = validate_model_file(path)
        self.assertFalse(valid)
        self.assertIsNone(status)

    def test_empty_file(self):
        """Empty file excluded"""
        path = self._write('m.yaml', '')
        valid, status = validate_model_file(path)
        self.assertFalse(valid)
        self.assertIsNone(status)

    def test_yaml_error_without_blocks_keyword(self):
        """YAML parse error without blocks: text excluded"""
        path = self._write('m.yaml', 'settings:\n  bad: [unclosed\n')
        valid, status = validate_model_file(path)
        self.assertFalse(valid)
        self.assertIsNone(status)

    def test_nonexistent_file(self):
        """Non-existent file excluded"""
        path = os.path.join(self.temp_dir, 'missing.yaml')
        valid, status = validate_model_file(path)
        self.assertFalse(valid)
        self.assertIsNone(status)

    def test_unreadable_file(self):
        """Unreadable file excluded"""
        path = self._write('m.yaml', 'blocks:\n  - label: "T"\n')
        os.chmod(path, 0o000)
        valid, status = validate_model_file(path)
        os.chmod(path, 0o644)
        self.assertFalse(valid)
        self.assertIsNone(status)

    # --- Exclusion from listing: no-blocks YAML not displayed ---

    def test_no_blocks_yaml_excluded_from_listing(self):
        """YAML files without blocks are not included in model listing"""
        models_dir = os.path.join(self.temp_dir, 'models')
        os.makedirs(models_dir)

        # Valid model - should be listed
        with open(os.path.join(models_dir, 'good.yaml'), 'w') as f:
            f.write('blocks:\n  - label: "T"\n    file: "t.log"\n    patterns:\n      - "p"\n')

        # No blocks - should NOT be listed
        with open(os.path.join(models_dir, 'no_blocks.yaml'), 'w') as f:
            f.write('settings:\n  loops: 2\n  max_time_delta: 60\n')

        # Collect only valid models
        listed = []
        for fname in os.listdir(models_dir):
            if fname.endswith('.yaml'):
                fpath = os.path.join(models_dir, fname)
                valid, status = validate_model_file(fpath)
                if valid:
                    listed.append(fname)

        self.assertIn('good.yaml', listed)
        self.assertNotIn('no_blocks.yaml', listed)

    def test_format_error_reported_in_status(self):
        """Model with structure error returns format error in status"""
        path = self._write('m.yaml',
                           'blocks:\n  - label: "T"\n    file: "t.log"\n    patterns:\n      - "p"\n'
                           '    bogus_key: true\n')
        valid, status = validate_model_file(path)
        self.assertTrue(valid)
        self.assertTrue(status.startswith('format'))


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestValidateModelStructure(unittest.TestCase):
    """Test validate_model_structure for LPMP model format rules"""

    # --- Valid models: no errors ---

    def test_valid_pattern_model(self):
        """Valid pattern model has no errors"""
        data = {'blocks': [{'label': 'T', 'file': 't.log', 'patterns': ['p']}]}
        self.assertEqual(validate_model_structure(data), [])

    def test_valid_pair_model(self):
        """Valid pair model has no errors"""
        data = {'blocks': [{'label': 'T', 'file': 't.log', 'start': 's', 'stop': 'e'}]}
        self.assertEqual(validate_model_structure(data), [])

    def test_valid_timeline_model(self):
        """Valid timeline model has no errors"""
        data = {'blocks': [{'label': 'T', 'file': 't.log', 'timeline': ['ev']}]}
        self.assertEqual(validate_model_structure(data), [])

    def test_valid_window_model(self):
        """Valid window model has no errors"""
        data = {'blocks': [{'label': 'T', 'file': '*.log*', 'window': True}]}
        self.assertEqual(validate_model_structure(data), [])

    def test_valid_model_with_all_optional_block_keys(self):
        """Block with all valid optional keys has no errors"""
        data = {'blocks': [{
            'label': 'T', 'file': 't.log', 'patterns': ['p'],
            'optional': True, 'present': False, 'profile': True,
            'controller': False, 'override': 'c-1', 'max_time_delta': 60,
            'window': False, 'context': 5,
        }]}
        self.assertEqual(validate_model_structure(data), [])

    def test_valid_model_with_all_settings_keys(self):
        """Model with all valid settings keys has no errors"""
        data = {
            'settings': {
                'max_time_delta': 60, 'block_time_tolerance': 5.0,
                'start_date': '2024-01-01', 'stop_date': '2024-01-02',
                'loops': 2, 'max_log_length': 200, 'profile': True,
                'optional': False, 'controller': False, 'graph': 'CPU',
                'timeline_patterns': {'maint': ['A']}
            },
            'blocks': [{'label': 'T', 'file': 't.log', 'patterns': ['p']}]
        }
        self.assertEqual(validate_model_structure(data), [])

    def test_valid_model_with_include(self):
        """Model with include key has no errors"""
        data = {
            'include': 'shared.yaml',
            'blocks': [{'label': 'T', 'file': 't.log', 'patterns': ['p']}]
        }
        self.assertEqual(validate_model_structure(data), [])

    # --- Unknown keys detected ---

    def test_unknown_top_level_key(self):
        """Unknown top-level key detected"""
        data = {
            'blocks': [{'label': 'T', 'file': 't.log', 'patterns': ['p']}],
            'bogus': True
        }
        errors = validate_model_structure(data)
        self.assertEqual(len(errors), 1)
        self.assertIn('bogus', errors[0])

    def test_unknown_block_key(self):
        """Unknown block-level key detected"""
        data = {'blocks': [{'label': 'T', 'file': 't.log', 'patterns': ['p'], 'bogus': True}]}
        errors = validate_model_structure(data)
        self.assertEqual(len(errors), 1)
        self.assertIn('bogus', errors[0])

    def test_unknown_settings_key(self):
        """Unknown settings key detected (e.g. typo max_delta_time)"""
        data = {
            'settings': {'max_delta_time': 60},
            'blocks': [{'label': 'T', 'file': 't.log', 'patterns': ['p']}]
        }
        errors = validate_model_structure(data)
        self.assertEqual(len(errors), 1)
        self.assertIn('max_delta_time', errors[0])

    def test_settings_at_block_level_detected(self):
        """settings key inside a block is flagged as unknown"""
        data = {'blocks': [{
            'label': 'T', 'file': 't.log', 'timeline': ['ev'],
            'settings': {'start_date': '2024-01-01'}
        }]}
        errors = validate_model_structure(data)
        self.assertEqual(len(errors), 1)
        self.assertIn('settings', errors[0])

    # --- Missing required fields ---

    def test_missing_label(self):
        """Missing label detected"""
        data = {'blocks': [{'file': 't.log', 'patterns': ['p']}]}
        errors = validate_model_structure(data)
        self.assertTrue(any('label' in e for e in errors))

    def test_missing_file(self):
        """Missing file detected"""
        data = {'blocks': [{'label': 'T', 'patterns': ['p']}]}
        errors = validate_model_structure(data)
        self.assertTrue(any('file' in e for e in errors))

    def test_missing_block_type(self):
        """Block with no patterns/start/stop/timeline/window detected"""
        data = {'blocks': [{'label': 'T', 'file': 't.log'}]}
        errors = validate_model_structure(data)
        self.assertTrue(any('window' in e for e in errors))

    def test_start_without_stop(self):
        """Pair block with start but no stop detected"""
        data = {'blocks': [{'label': 'T', 'file': 't.log', 'start': 's'}]}
        errors = validate_model_structure(data)
        self.assertTrue(any('stop' in e for e in errors))

    def test_stop_without_start(self):
        """Pair block with stop but no start detected"""
        data = {'blocks': [{'label': 'T', 'file': 't.log', 'stop': 'e'}]}
        errors = validate_model_structure(data)
        self.assertTrue(any('start' in e for e in errors))

    # --- Structural issues ---

    def test_duplicate_labels(self):
        """Duplicate block labels detected"""
        data = {'blocks': [
            {'label': 'T', 'file': 't.log', 'patterns': ['p']},
            {'label': 'T', 'file': 't.log', 'patterns': ['q']}
        ]}
        errors = validate_model_structure(data)
        self.assertTrue(any('duplicate' in e for e in errors))

    def test_blocks_not_list(self):
        """blocks as non-list detected"""
        data = {'blocks': 'not a list'}
        errors = validate_model_structure(data)
        self.assertTrue(any('list' in e for e in errors))

    def test_block_not_dict(self):
        """Block that is not a dict detected"""
        data = {'blocks': ['not a dict']}
        errors = validate_model_structure(data)
        self.assertTrue(any('mapping' in e for e in errors))

    def test_settings_not_dict(self):
        """settings as non-dict detected"""
        data = {
            'settings': 'not a dict',
            'blocks': [{'label': 'T', 'file': 't.log', 'patterns': ['p']}]
        }
        errors = validate_model_structure(data)
        self.assertTrue(any('settings' in e for e in errors))

    def test_not_a_dict(self):
        """Non-dict data detected"""
        errors = validate_model_structure(['a list'])
        self.assertTrue(any('mapping' in e for e in errors))

    def test_empty_blocks(self):
        """Empty blocks list detected"""
        data = {'blocks': []}
        errors = validate_model_structure(data)
        self.assertTrue(any('empty' in e for e in errors))

    # --- Multiple errors in one model ---

    def test_multiple_errors(self):
        """Multiple errors reported in single validation"""
        data = {
            'bogus_top': True,
            'settings': {'bad_key': 1},
            'blocks': [
                {'label': 'T', 'file': 't.log', 'patterns': ['p'], 'bad_block': True},
                {'label': 'T', 'file': 't.log', 'patterns': ['q']}
            ]
        }
        errors = validate_model_structure(data)
        self.assertGreaterEqual(len(errors), 3)  # top key + settings key + block key + dupe


if __name__ == '__main__':
    unittest.main()
