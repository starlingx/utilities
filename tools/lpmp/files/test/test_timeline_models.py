#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Automated tests for timeline model addition and detection functionality.

This test suite provides comprehensive coverage of timeline model features including:
- Timeline model loading and validation
- Timeline pattern resolution (named references vs direct patterns)
- Timeline block processing and chronological ordering
- Mixed models with timeline and non-timeline blocks
- Timeline model detection and validation
- Variable substitution in timeline patterns
- Error handling for invalid timeline configurations

Run with: python -m pytest test_timeline_models.py -v
"""

from datetime import datetime
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

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# Import directly from lpmp modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import process_blocks_auto_detect           # noqa: E402
from lpmp_engine import process_timeline_block               # noqa: E402
from lpmp_utils import apply_timeline_variable_substitution  # noqa: E402
from lpmp_utils import load_model                            # noqa: E402
from lpmp_utils import resolve_timeline_patterns             # noqa: E402
from test_base import LPMPTestBase                           # noqa: E402


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestTimelineModelLoading(LPMPTestBase):
    """Test timeline model loading and validation"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, "timeline_model.yaml")
        self.include_file = os.path.join(self.temp_dir, "patterns.yaml")

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_load_direct_timeline_model(self):
        """Test loading timeline model with direct pattern list"""
        model_data = {
            'blocks': [
                {
                    'label': 'Direct Timeline',
                    'file': 'test.log',
                    'timeline': ['pattern1', 'pattern2', 'pattern3']
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['label'], 'Direct Timeline')
        self.assertEqual(blocks[0]['timeline'], ['pattern1', 'pattern2', 'pattern3'])
        self.assertFalse(blocks[0]['optional'])

    def test_load_named_reference_timeline_model(self):
        """Test loading timeline model with named pattern reference"""
        model_data = {
            'blocks': [
                {
                    'label': 'Named Timeline',
                    'file': 'test.log',
                    'timeline': '{maintenance}'
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['timeline'], '{maintenance}')

    def test_load_timeline_model_with_includes(self):
        """Test loading timeline model with included pattern definitions"""
        # Create include file with timeline patterns
        include_data = {
            'settings': {
                'timeline_patterns': {
                    'maintenance': ['Host Add Completed', 'Unlock Action'],
                    'network': ['Link Down', 'Link Up']
                }
            }
        }
        with open(self.include_file, 'w') as f:
            yaml.dump(include_data, f)

        # Create main model file
        model_data = {
            'include': 'patterns.yaml',
            'blocks': [
                {
                    'label': 'Maintenance Timeline',
                    'file': 'mtcAgent.log',
                    'timeline': '{maintenance}'
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertIn('timeline_patterns', settings)
        self.assertIn('maintenance', settings['timeline_patterns'])
        self.assertEqual(
            settings['timeline_patterns']['maintenance'],
            ['Host Add Completed', 'Unlock Action']
        )

    def test_timeline_model_validation_all_timeline_blocks(self):
        """Test that timeline models require all blocks to be timeline blocks"""
        model_data = {
            'blocks': [
                {
                    'label': 'Timeline Block',
                    'file': 'test.log',
                    'timeline': ['pattern1']
                },
                {
                    'label': 'Pattern Block',
                    'file': 'test.log',
                    'patterns': ['pattern2']
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_timeline_model_validation_missing_timeline_field(self):
        """Test validation error when timeline field is missing"""
        model_data = {
            'blocks': [
                {
                    'label': 'Invalid Block',
                    'file': 'test.log'
                    # Missing timeline, patterns, or start/stop fields
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_timeline_model_with_optional_blocks(self):
        """Test timeline model with optional blocks"""
        model_data = {
            'blocks': [
                {
                    'label': 'Required Timeline',
                    'file': 'test.log',
                    'timeline': ['pattern1'],
                    'optional': False
                },
                {
                    'label': 'Optional Timeline',
                    'file': 'test.log',
                    'timeline': ['pattern2'],
                    'optional': True
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 2)
        self.assertFalse(blocks[0]['optional'])
        self.assertTrue(blocks[1]['optional'])

    def test_timeline_model_with_controller_flag(self):
        """Test timeline model with controller-only blocks"""
        model_data = {
            'blocks': [
                {
                    'label': 'Controller Timeline',
                    'file': 'test.log',
                    'timeline': ['pattern1'],
                    'controller': True
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0]['controller'])


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestTimelinePatternResolution(LPMPTestBase):
    """Test timeline pattern resolution functionality"""

    def test_resolve_direct_pattern_list(self):
        """Test resolving direct pattern list"""
        timeline_ref = ['pattern1', 'pattern2', 'pattern3']
        settings = {}

        result = resolve_timeline_patterns(timeline_ref, settings)
        self.assertEqual(result, ['pattern1', 'pattern2', 'pattern3'])

    def test_resolve_named_pattern_reference(self):
        """Test resolving named pattern reference"""
        timeline_ref = '{maintenance}'
        settings = {
            'timeline_patterns': {
                'maintenance': ['Host Add Completed', 'Unlock Action']
            }
        }

        result = resolve_timeline_patterns(timeline_ref, settings)
        self.assertEqual(result, ['Host Add Completed', 'Unlock Action'])

    def test_resolve_single_string_pattern(self):
        """Test resolving single string pattern"""
        timeline_ref = 'single_pattern'
        settings = {}

        result = resolve_timeline_patterns(timeline_ref, settings)
        self.assertEqual(result, ['single_pattern'])

    def test_resolve_missing_named_reference(self):
        """Test error when named reference doesn't exist"""
        timeline_ref = '{nonexistent}'
        settings = {
            'timeline_patterns': {
                'maintenance': ['pattern1']
            }
        }

        with self.assertRaises(SystemExit):
            resolve_timeline_patterns(timeline_ref, settings)

    def test_resolve_empty_settings(self):
        """Test resolving named reference with empty settings"""
        timeline_ref = '{maintenance}'
        settings = {}

        with self.assertRaises(SystemExit):
            resolve_timeline_patterns(timeline_ref, settings)


class TestTimelineVariableSubstitution(LPMPTestBase):
    """Test variable substitution in timeline patterns"""

    def test_substitute_variables_in_list(self):
        """Test variable substitution in pattern list"""
        timeline_patterns = ['{hostname} started', 'service {service} ready']
        variables = {'hostname': 'controller-0', 'service': 'nova'}

        result = apply_timeline_variable_substitution(timeline_patterns, variables)
        self.assertEqual(result, ['controller-0 started', 'service nova ready'])

    def test_substitute_variables_in_string(self):
        """Test variable substitution in single string"""
        timeline_patterns = '{hostname} unlock action'
        variables = {'hostname': 'controller-1'}

        result = apply_timeline_variable_substitution(timeline_patterns, variables)
        self.assertEqual(result, 'controller-1 unlock action')

    def test_substitute_missing_variable(self):
        """Test handling of missing variables"""
        timeline_patterns = ['{hostname} {missing} action']
        variables = {'hostname': 'controller-0'}

        with patch('sys.stderr', new_callable=StringIO):
            result = apply_timeline_variable_substitution(timeline_patterns, variables)
        self.assertEqual(result, ['{hostname} {missing} action'])


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestTimelineBlockProcessing(LPMPTestBase):
    """Test timeline block processing functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "timeline.log")
        self.model_file = os.path.join(self.temp_dir, "model.yaml")

        # Create mock args object
        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.hostname = 'controller-0'
                self.variables = None
                self.model_file = os.path.join(temp_dir, "model.yaml")

        self.args = MockArgs(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_process_timeline_block_direct_patterns(self):
        """Test processing timeline block with direct patterns"""
        log_content = """2024-01-06T10:00:02.000 pattern2 event
2024-01-06T10:00:01.000 pattern1 event
2024-01-06T10:00:03.000 pattern3 event"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Timeline Block',
            'file': 'timeline.log',
            'timeline': ['pattern1', 'pattern2', 'pattern3']
        }

        settings = {}
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        result = process_timeline_block(self.args, block, start_date, settings)

        # Should return all matches sorted chronologically
        self.assertEqual(len(result), 3)
        self.assertIn('pattern1', result[0][1])  # First chronologically
        self.assertIn('pattern2', result[1][1])  # Second chronologically
        self.assertIn('pattern3', result[2][1])  # Third chronologically

    def test_process_timeline_block_named_reference(self):
        """Test processing timeline block with named pattern reference"""
        log_content = """2024-01-06T10:00:01.000 Host Add Completed
2024-01-06T10:00:02.000 Unlock Action"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Maintenance Timeline',
            'file': 'timeline.log',
            'timeline': '{maintenance}'
        }

        settings = {
            'timeline_patterns': {
                'maintenance': ['Host Add Completed', 'Unlock Action']
            }
        }
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        result = process_timeline_block(self.args, block, start_date, settings)

        self.assertEqual(len(result), 2)
        self.assertIn('Host Add Completed', result[0][1])
        self.assertIn('Unlock Action', result[1][1])

    def test_process_timeline_block_no_matches(self):
        """Test processing timeline block with no pattern matches"""
        log_content = """2024-01-06T10:00:01.000 unrelated event
2024-01-06T10:00:02.000 another event"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Timeline Block',
            'file': 'timeline.log',
            'timeline': ['missing_pattern1', 'missing_pattern2']
        }

        settings = {}
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        result = process_timeline_block(self.args, block, start_date, settings)

        self.assertEqual(len(result), 0)

    def test_process_timeline_block_with_variable_substitution(self):
        """Test timeline block processing with variable substitution"""
        log_content = """2024-01-06T10:00:01.000 controller-0 started
2024-01-06T10:00:02.000 controller-0 ready"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Variable Timeline',
            'file': 'timeline.log',
            'timeline': ['{hostname} started', '{hostname} ready']
        }

        # Set up args with variables
        self.args.variables = ['service=nova']

        settings = {}
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        result = process_timeline_block(self.args, block, start_date, settings)

        self.assertEqual(len(result), 2)
        self.assertIn('controller-0 started', result[0][1])
        self.assertIn('controller-0 ready', result[1][1])

    def test_process_timeline_block_chronological_ordering(self):
        """Test that timeline block results are chronologically ordered"""
        log_content = """2024-01-06T10:00:05.000 event5
2024-01-06T10:00:01.000 event1
2024-01-06T10:00:03.000 event3
2024-01-06T10:00:02.000 event2
2024-01-06T10:00:04.000 event4"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Chronological Timeline',
            'file': 'timeline.log',
            'timeline': ['event1', 'event2', 'event3', 'event4', 'event5']
        }

        settings = {}
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        result = process_timeline_block(self.args, block, start_date, settings)

        self.assertEqual(len(result), 5)
        # Verify chronological order
        timestamps = [r[0] for r in result]
        self.assertEqual(timestamps, sorted(timestamps))

        # Verify content order matches timestamp order
        self.assertIn('event1', result[0][1])
        self.assertIn('event2', result[1][1])
        self.assertIn('event3', result[2][1])
        self.assertIn('event4', result[3][1])
        self.assertIn('event5', result[4][1])


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestTimelineModelDetection(LPMPTestBase):
    """Test timeline model detection and validation"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, "model.yaml")

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_detect_pure_timeline_model(self):
        """Test detection of pure timeline model (all blocks are timeline)"""
        model_data = {
            'blocks': [
                {
                    'label': 'Timeline 1',
                    'file': 'test1.log',
                    'timeline': ['pattern1']
                },
                {
                    'label': 'Timeline 2',
                    'file': 'test2.log',
                    'timeline': ['pattern2']
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)

        # All blocks should be timeline blocks
        timeline_blocks = [b for b in blocks if 'timeline' in b]
        self.assertEqual(len(timeline_blocks), 2)
        self.assertEqual(len(timeline_blocks), len(blocks))

    def test_detect_mixed_model_error(self):
        """Test error detection for mixed timeline/non-timeline models"""
        model_data = {
            'blocks': [
                {
                    'label': 'Timeline Block',
                    'file': 'test1.log',
                    'timeline': ['pattern1']
                },
                {
                    'label': 'Pattern Block',
                    'file': 'test2.log',
                    'patterns': ['pattern2']
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Should raise SystemExit due to mixed model validation
        with self.assertRaises(SystemExit):
            load_model(self.model_file)

    def test_detect_non_timeline_model(self):
        """Test detection of non-timeline model (no timeline blocks)"""
        model_data = {
            'blocks': [
                {
                    'label': 'Pattern Block',
                    'file': 'test1.log',
                    'patterns': ['pattern1']
                },
                {
                    'label': 'Pair Block',
                    'file': 'test2.log',
                    'start': 'start_pattern',
                    'stop': 'stop_pattern'
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, _ = load_model(self.model_file)

        # No blocks should be timeline blocks
        timeline_blocks = [b for b in blocks if 'timeline' in b]
        self.assertEqual(len(timeline_blocks), 0)


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestTimelineModelIntegration(LPMPTestBase):
    """Integration tests for timeline model processing"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "integration.log")
        self.model_file = os.path.join(self.temp_dir, "integration_model.yaml")
        self.include_file = os.path.join(self.temp_dir, "patterns.yaml")

        # Create mock args object
        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.hostname = 'controller-0'
                self.variables = None
                self.model_file = os.path.join(temp_dir, "integration_model.yaml")

        self.args = MockArgs(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_full_timeline_model_processing(self):
        """Test complete timeline model processing workflow"""
        # Create include file with timeline patterns
        include_data = {
            'settings': {
                'timeline_patterns': {
                    'maintenance': ['Host Add Completed', 'Unlock Action', 'Lock Action'],
                    'network': ['Link Down', 'Link Up']
                }
            }
        }
        with open(self.include_file, 'w') as f:
            yaml.dump(include_data, f)

        # Create timeline model
        model_data = {
            'include': 'patterns.yaml',
            'blocks': [
                {
                    'label': 'Maintenance Events',
                    'file': 'integration.log',
                    'timeline': '{maintenance}',
                    'optional': False
                },
                {
                    'label': 'Network Events',
                    'file': 'integration.log',
                    'timeline': '{network}',
                    'optional': True
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create log file with mixed events
        log_content = """2024-01-06T10:00:01.000 Host Add Completed for controller-1
2024-01-06T10:00:02.000 Link Down on interface eth0
2024-01-06T10:00:03.000 Unlock Action for controller-1
2024-01-06T10:00:04.000 Link Up on interface eth0
2024-01-06T10:00:05.000 Lock Action for controller-1"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Load and process model
        blocks, settings, _ = load_model(self.model_file)

        # Verify model loaded correctly
        self.assertEqual(len(blocks), 2)
        self.assertIn('timeline_patterns', settings)

        # Process blocks
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        with patch('builtins.print'):  # Suppress output
            success, start_time, end_time, patterns_found, optional_warnings, _ = process_blocks_auto_detect(
                self.args, blocks, start_date
            )

        # Verify processing results
        self.assertTrue(success)
        self.assertEqual(patterns_found, 5)  # 3 maintenance + 2 network events
        self.assertIsNotNone(start_time)
        self.assertIsNotNone(end_time)

    def test_timeline_model_with_controller_filtering(self):
        """Test timeline model with controller-only blocks"""
        model_data = {
            'blocks': [
                {
                    'label': 'Controller Events',
                    'file': 'integration.log',
                    'timeline': ['controller event'],
                    'controller': True
                },
                {
                    'label': 'General Events',
                    'file': 'integration.log',
                    'timeline': ['general event'],
                    'controller': False
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        log_content = """2024-01-06T10:00:01.000 controller event occurred
2024-01-06T10:00:02.000 general event occurred"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        blocks, settings, _ = load_model(self.model_file)

        # Test with controller hostname
        self.args.hostname = 'controller-0'
        start_date = datetime(2024, 1, 6, 9, 0, 0)

        with patch('builtins.print'):
            success, start_time, end_time, patterns_found, optional_warnings, _ = process_blocks_auto_detect(
                self.args, blocks, start_date
            )

        # Should process both blocks for controller
        self.assertTrue(success)
        self.assertEqual(patterns_found, 2)

        # Test with non-controller hostname
        self.args.hostname = 'worker-0'

        with patch('builtins.print'):
            success, start_time, end_time, patterns_found, optional_warnings, _ = process_blocks_auto_detect(
                self.args, blocks, start_date
            )

        # Should only process general events block for worker
        self.assertTrue(success)
        self.assertEqual(patterns_found, 1)

    def test_timeline_model_error_handling(self):
        """Test error handling in timeline model processing"""
        model_data = {
            'blocks': [
                {
                    'label': 'Required Timeline',
                    'file': 'integration.log',
                    'timeline': ['missing_pattern'],
                    'optional': False
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        log_content = """2024-01-06T10:00:01.000 unrelated event"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        blocks, settings, _ = load_model(self.model_file)

        start_date = datetime(2024, 1, 6, 9, 0, 0)

        with patch('builtins.print'):
            success, start_time, end_time, patterns_found, optional_warnings, _ = process_blocks_auto_detect(
                self.args, blocks, start_date
            )

        # Should fail for required timeline block with no matches
        self.assertFalse(success)
        self.assertEqual(patterns_found, 0)


class TestTimelineModelEdgeCases(LPMPTestBase):
    """Test edge cases and boundary conditions for timeline models"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_empty_timeline_patterns(self):
        """Test handling of empty timeline pattern lists"""
        timeline_ref = []
        settings = {}

        result = resolve_timeline_patterns(timeline_ref, settings)
        self.assertEqual(result, [])

    def test_timeline_patterns_with_regex(self):
        """Test timeline patterns with regex expressions"""
        timeline_patterns = [r'pattern\d+', r'event.*completed']
        variables = {}

        result = apply_timeline_variable_substitution(timeline_patterns, variables)
        self.assertEqual(result, [r'pattern\d+', r'event.*completed'])

    def test_timeline_patterns_with_special_characters(self):
        """Test timeline patterns with special characters"""
        timeline_patterns = ['pattern [special]', 'event (with) parentheses']
        variables = {}

        result = apply_timeline_variable_substitution(timeline_patterns, variables)
        self.assertEqual(result, ['pattern [special]', 'event (with) parentheses'])

    def test_malformed_named_reference(self):
        """Test handling of malformed named references"""
        timeline_ref = '{malformed'  # Missing closing brace
        settings = {}

        # Should treat as single string pattern
        result = resolve_timeline_patterns(timeline_ref, settings)
        self.assertEqual(result, ['{malformed'])

    def test_nested_variable_substitution(self):
        """Test nested variable substitution scenarios"""
        timeline_patterns = ['{hostname} {action} {service}']
        variables = {'hostname': 'controller-0', 'action': 'restart', 'service': 'nova'}

        result = apply_timeline_variable_substitution(timeline_patterns, variables)
        self.assertEqual(result, ['controller-0 restart nova'])


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
