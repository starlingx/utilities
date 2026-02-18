#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Automated tests for window model feature.

Tests window block loading, file discovery, auto time range detection,
and end-to-end processing via the existing timeline pipeline.

Run with: python -m pytest test_window_model.py -v
"""

from datetime import datetime
from datetime import timedelta
import gzip
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

from lpmp_engine import extract_context_lines        # noqa: E402
from lpmp_engine import find_pattern_in_files_all_matches  # noqa: E402
from lpmp_output import write_context_files          # noqa: E402
from lpmp_utils import _file_date_range_cache        # noqa: E402
from lpmp_utils import _rotation_prune               # noqa: E402
from lpmp_utils import auto_detect_time_range        # noqa: E402
from lpmp_utils import detect_model_type             # noqa: E402
from lpmp_utils import discover_window_files         # noqa: E402
from lpmp_utils import get_file_date_range           # noqa: E402
from lpmp_utils import load_model                    # noqa: E402
from lpmp_utils import ModelType                     # noqa: E402
from lpmp_utils import PatternResult                 # noqa: E402
from lpmp_utils import TimelineResult                # noqa: E402
from lpmp_utils import validate_model_structure      # noqa: E402
import lpmptool                                      # noqa: E402
from test_base import LPMPTestBase                   # noqa: E402


class TestWindowFileDiscovery(LPMPTestBase):
    """Test file discovery and classification for window models"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_log(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def test_discover_matches_log_files(self):
        """Log files with timestamps are matched"""
        self._create_log('test.log', [
            '2024-01-06T10:00:00.000 first line',
            '2024-01-06T10:00:01.000 second line',
        ])
        matched, skipped = discover_window_files(self.temp_dir, '*.log')
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0][0], 'test.log')

    def test_discover_skips_binary(self):
        """Binary files are skipped"""
        # Create a file with null bytes
        path = os.path.join(self.temp_dir, 'binary.log')
        with open(path, 'wb') as f:
            f.write(b'\x00\x01\x02binary content')
        matched, skipped = discover_window_files(self.temp_dir, '*.log')
        self.assertEqual(len(matched), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn('binary', skipped[0][1])

    def test_discover_skips_known_non_log(self):
        """Known non-log files (wtmp, btmp, etc.) are skipped"""
        path = os.path.join(self.temp_dir, 'wtmp')
        with open(path, 'w') as f:
            f.write('some content')
        matched, skipped = discover_window_files(self.temp_dir, '*')
        self.assertTrue(any('wtmp' in s[0] for s in skipped))

    def test_discover_skips_no_timestamps(self):
        """Files without parseable timestamps are skipped"""
        self._create_log('notime.log', [
            'no timestamp here',
            'still no timestamp',
        ])
        matched, skipped = discover_window_files(self.temp_dir, '*.log')
        self.assertEqual(len(matched), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn('no timestamps', skipped[0][1])

    def test_discover_skips_outside_window(self):
        """Files entirely outside time window are skipped"""
        self._create_log('old.log', [
            '2024-01-01T10:00:00.000 old line',
            '2024-01-01T10:00:01.000 old line 2',
        ])
        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, '*.log', start, stop
        )
        self.assertEqual(len(matched), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn('before time window', skipped[0][1])

    def test_discover_file_list_pattern(self):
        """File list patterns are expanded correctly"""
        self._create_log('app.log', [
            '2024-01-06T10:00:00.000 app line',
        ])
        self._create_log('sys.log', [
            '2024-01-06T10:00:00.000 sys line',
        ])
        matched, skipped = discover_window_files(
            self.temp_dir, ['app.log', 'sys.log']
        )
        self.assertEqual(len(matched), 2)


class TestAutoDetectTimeRange(LPMPTestBase):
    """Test auto-detection of time range from log files"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_log(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def test_auto_detect_returns_default_window(self):
        """Auto-detect returns a window ending at latest timestamp"""
        self._create_log('test.log', [
            '2024-01-06T10:00:00.000 first',
            '2024-01-06T12:00:00.000 last',
        ])
        start, end = auto_detect_time_range(self.temp_dir, '*.log')
        self.assertEqual(end, datetime(2024, 1, 6, 12, 0, 0))
        self.assertIsNotNone(start)
        self.assertLess(start, end)

    def test_auto_detect_custom_minutes(self):
        """Auto-detect respects custom minutes_back parameter"""
        self._create_log('test.log', [
            '2024-01-06T10:00:00.000 first',
            '2024-01-06T12:00:00.000 last',
        ])
        start, end = auto_detect_time_range(
            self.temp_dir, '*.log', minutes_back=30
        )
        self.assertEqual(end - start, timedelta(minutes=30))

    def test_auto_detect_multiple_files(self):
        """Auto-detect finds latest timestamp across multiple files"""
        self._create_log('early.log', [
            '2024-01-06T10:00:00.000 early',
        ])
        self._create_log('late.log', [
            '2024-01-06T14:00:00.000 late',
        ])
        start, end = auto_detect_time_range(self.temp_dir, '*.log')
        self.assertEqual(end, datetime(2024, 1, 6, 14, 0, 0))
        self.assertIsNotNone(start)
        self.assertLess(start, end)

    def test_auto_detect_no_files(self):
        """Auto-detect returns None when no log files found"""
        start, end = auto_detect_time_range(self.temp_dir, '*.log')
        self.assertIsNone(start)
        self.assertIsNone(end)

    def test_auto_detect_skips_binary(self):
        """Auto-detect skips binary files"""
        path = os.path.join(self.temp_dir, 'binary.log')
        with open(path, 'wb') as f:
            f.write(b'\x00\x01\x02binary')
        start, end = auto_detect_time_range(self.temp_dir, '*.log')
        self.assertIsNone(start)
        self.assertIsNone(end)


class TestWindowModelValidation(LPMPTestBase):
    """Test window model structure validation"""

    def test_window_block_valid(self):
        """Window block passes validation"""
        data = {'blocks': [
            {'label': 'All', 'file': '*.log*', 'window': True}
        ]}
        errors = validate_model_structure(data)
        self.assertEqual(errors, [])

    def test_window_detected_as_timeline(self):
        """Window block detected as TIMELINE model type"""
        blocks = [
            {'label': 'All', 'file': '*.log*', 'window': True, 'timeline': '.*'}
        ]
        self.assertEqual(detect_model_type(blocks), ModelType.TIMELINE)

    def test_multiple_window_blocks_valid(self):
        """Multiple window blocks pass validation"""
        data = {'blocks': [
            {'label': 'Mtce', 'file': 'mtcAgent.log*', 'window': True},
            {'label': 'SM', 'file': 'sm.log*', 'window': True},
        ]}
        errors = validate_model_structure(data)
        self.assertEqual(errors, [])

    def test_window_with_settings_valid(self):
        """Window model with start_date/stop_date settings is valid"""
        data = {
            'settings': {
                'start_date': '2024-01-06T10:00:00',
                'stop_date': '2024-01-06T11:00:00',
            },
            'blocks': [
                {'label': 'All', 'file': '*.log*', 'window': True}
            ]
        }
        errors = validate_model_structure(data)
        self.assertEqual(errors, [])


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestWindowModelLoading(LPMPTestBase):
    """Test window model loading via load_model"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, 'window_model.yaml')

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_load_window_model(self):
        """Window model loads with timeline: '.*' injected"""
        model_data = {
            'blocks': [
                {'label': 'All Logs', 'file': '*.log*', 'window': True}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, model_type = load_model(self.model_file)
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].get('window'))
        self.assertEqual(blocks[0]['timeline'], '.*')
        self.assertEqual(model_type, ModelType.TIMELINE)

    def test_load_window_model_with_stop_date(self):
        """Window model with stop_date in settings loads correctly"""
        model_data = {
            'settings': {
                'start_date': '2024-01-06T10:00:00',
                'stop_date': '2024-01-06T11:00:00',
            },
            'blocks': [
                {'label': 'All Logs', 'file': '*.log*', 'window': True}
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, model_type = load_model(self.model_file)
        self.assertEqual(settings['stop_date'], '2024-01-06T11:00:00')

    def test_load_window_model_file_list(self):
        """Window model with file list loads correctly"""
        model_data = {
            'blocks': [
                {
                    'label': 'Selected Logs',
                    'file': ['mtcAgent.log*', 'sm.log*'],
                    'window': True
                }
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        blocks, settings, model_type = load_model(self.model_file)
        self.assertEqual(blocks[0]['file'], ['mtcAgent.log*', 'sm.log*'])
        self.assertTrue(blocks[0].get('window'))


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestContextLabel(LPMPTestBase):
    """Test context label parsing and output"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, 'context_model.yaml')
        self.log_dir = os.path.join(self.temp_dir, 'logs')
        os.makedirs(self.log_dir)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_context_int_parsed_as_symmetric(self):
        """context: 5 parsed as [5, 5]"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'patterns': ['pattern'], 'context': 5
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        blocks, _, _ = load_model(self.model_file)
        self.assertEqual(blocks[0]['context_before'], 5)
        self.assertEqual(blocks[0]['context_after'], 5)

    def test_context_list_parsed_as_asymmetric(self):
        """context: [3, 10] parsed as before=3, after=10"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'patterns': ['pattern'], 'context': [3, 10]
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        blocks, _, _ = load_model(self.model_file)
        self.assertEqual(blocks[0]['context_before'], 3)
        self.assertEqual(blocks[0]['context_after'], 10)

    def test_context_not_set_by_default(self):
        """Blocks without context: have no context_before/after"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'patterns': ['pattern']
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        blocks, _, _ = load_model(self.model_file)
        self.assertNotIn('context_before', blocks[0])
        self.assertNotIn('context_after', blocks[0])

    def test_context_skipped_for_pair_blocks(self):
        """context: on pair blocks is ignored with warning"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'start': 'begin', 'stop': 'end', 'context': 5
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        blocks, _, _ = load_model(self.model_file)
        self.assertNotIn('context_before', blocks[0])

    def test_context_invalid_string_exits(self):
        """context: 'string' triggers sys.exit(1)"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'patterns': ['p'], 'context': 'bad'
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        with self.assertRaises(SystemExit) as cm:
            load_model(self.model_file)
        self.assertEqual(cm.exception.code, 1)

    def test_context_single_element_list_exits(self):
        """context: [5] (single element list) triggers sys.exit(1)"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'patterns': ['p'], 'context': [5]
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        with self.assertRaises(SystemExit) as cm:
            load_model(self.model_file)
        self.assertEqual(cm.exception.code, 1)

    def test_context_three_element_list_exits(self):
        """context: [1,2,3] (three element list) triggers sys.exit(1)"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'patterns': ['p'], 'context': [1, 2, 3]
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        with self.assertRaises(SystemExit) as cm:
            load_model(self.model_file)
        self.assertEqual(cm.exception.code, 1)

    def test_context_zero_value_symmetric(self):
        """context: 0 is valid and sets both to 0"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'patterns': ['p'], 'context': 0
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        blocks, _, _ = load_model(self.model_file)
        self.assertEqual(blocks[0]['context_before'], 0)
        self.assertEqual(blocks[0]['context_after'], 0)

    def test_context_on_timeline_block(self):
        """context: on timeline block is accepted"""
        model_data = {
            'blocks': [{
                'label': 'Test', 'file': 'test.log',
                'timeline': ['event'], 'context': [2, 5]
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)
        blocks, _, _ = load_model(self.model_file)
        self.assertEqual(blocks[0]['context_before'], 2)
        self.assertEqual(blocks[0]['context_after'], 5)

    def test_extract_context_lines(self):
        """extract_context_lines returns correct before/after lines"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('line 1\n')
            f.write('line 2\n')
            f.write('line 3\n')
            f.write('MATCH LINE\n')
            f.write('line 5\n')
            f.write('line 6\n')
            f.write('line 7\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'MATCH LINE', 2, 2
        )
        self.assertEqual(len(before), 2)
        self.assertEqual(len(after), 2)
        self.assertIn('line 2', before[0])
        self.assertIn('line 3', before[1])
        self.assertIn('line 5', after[0])
        self.assertIn('line 6', after[1])

    def test_extract_context_at_file_start(self):
        """Context at start of file returns fewer before lines"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('MATCH LINE\n')
            f.write('after 1\n')
            f.write('after 2\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'MATCH LINE', 5, 2
        )
        self.assertEqual(len(before), 0)
        self.assertEqual(len(after), 2)

    def test_extract_context_at_file_end(self):
        """Context at end of file returns fewer after lines"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('before 1\n')
            f.write('before 2\n')
            f.write('MATCH LINE\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'MATCH LINE', 2, 5
        )
        self.assertEqual(len(before), 2)
        self.assertEqual(len(after), 0)

    def test_extract_context_zero_before(self):
        """context_before=0 returns no before lines"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('line 1\n')
            f.write('MATCH LINE\n')
            f.write('line 3\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'MATCH LINE', 0, 1
        )
        self.assertEqual(len(before), 0)
        self.assertEqual(len(after), 1)
        self.assertIn('line 3', after[0])

    def test_extract_context_zero_after(self):
        """context_after=0 returns no after lines"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('line 1\n')
            f.write('MATCH LINE\n')
            f.write('line 3\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'MATCH LINE', 1, 0
        )
        self.assertEqual(len(before), 1)
        self.assertIn('line 1', before[0])
        self.assertEqual(len(after), 0)

    def test_extract_context_zero_both(self):
        """context_before=0 and context_after=0 returns empty lists"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('line 1\n')
            f.write('MATCH LINE\n')
            f.write('line 3\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'MATCH LINE', 0, 0
        )
        self.assertEqual(before, [])
        self.assertEqual(after, [])

    def test_extract_context_file_not_found(self):
        """Missing file returns empty lists"""
        before, after = extract_context_lines(
            self.log_dir, 'nonexistent.log', 'MATCH', 2, 2
        )
        self.assertEqual(before, [])
        self.assertEqual(after, [])

    def test_extract_context_no_match(self):
        """No matching line returns empty lists"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('line 1\n')
            f.write('line 2\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'NO SUCH LINE', 2, 2
        )
        self.assertEqual(before, [])
        self.assertEqual(after, [])

    def test_extract_context_large_request_small_file(self):
        """Large context request on small file returns available lines"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('only before\n')
            f.write('MATCH LINE\n')
            f.write('only after\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'MATCH LINE', 50, 50
        )
        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)

    def test_extract_context_gzipped_file(self):
        """Context extraction works on gzipped log files"""
        gz_path = os.path.join(self.log_dir, 'test.log.gz')
        with gzip.open(gz_path, 'wt', encoding='utf-8') as f:
            f.write('gz line 1\n')
            f.write('gz line 2\n')
            f.write('GZ MATCH\n')
            f.write('gz line 4\n')
            f.write('gz line 5\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log.gz', 'GZ MATCH', 2, 2
        )
        self.assertEqual(len(before), 2)
        self.assertEqual(len(after), 2)
        self.assertIn('gz line 1', before[0])
        self.assertIn('gz line 2', before[1])
        self.assertIn('gz line 4', after[0])
        self.assertIn('gz line 5', after[1])

    def test_extract_context_matches_first_occurrence(self):
        """Substring match returns context around first occurrence"""
        log_file = os.path.join(self.log_dir, 'test.log')
        with open(log_file, 'w') as f:
            f.write('aaa\n')
            f.write('MATCH LINE\n')
            f.write('bbb\n')
            f.write('ccc\n')
            f.write('MATCH LINE\n')
            f.write('ddd\n')
        before, after = extract_context_lines(
            self.log_dir, 'test.log', 'MATCH LINE', 1, 1
        )
        self.assertEqual(len(before), 1)
        self.assertIn('aaa', before[0])
        self.assertEqual(len(after), 1)
        self.assertIn('bbb', after[0])

    def test_write_context_files(self):
        """write_context_files creates .context file with correct format"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)

        blocks = [{
            'label': 'Test Block',
            'file': 'test.log',
            'patterns': ['MATCH'],
            'context_before': 2,
            'context_after': 2,
        }]
        results = [
            PatternResult(
                timestamp='2024-01-06T10:00:00.000',
                block_label='Test Block',
                log_line='MATCH LINE',
                actual_filename='test.log',
                hostname='controller-0',
                context=(['before 1', 'before 2'], ['after 1', 'after 2'])
            )
        ]
        write_context_files(output_dir, blocks, results)

        context_file = os.path.join(output_dir, 'Test_Block.context')
        self.assertTrue(os.path.exists(context_file))
        with open(context_file, 'r') as f:
            content = f.read()
        self.assertIn('> MATCH LINE', content)
        self.assertIn('before 1', content)
        self.assertIn('after 2', content)
        self.assertIn('Match 1', content)

    def test_write_context_files_multiple_matches(self):
        """write_context_files handles multiple matches in one block"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)

        blocks = [{
            'label': 'Multi', 'file': 'test.log',
            'patterns': ['M'], 'context_before': 1, 'context_after': 1,
        }]
        results = [
            PatternResult(
                timestamp='2024-01-06T10:00:00.000',
                block_label='Multi', log_line='MATCH 1',
                actual_filename='test.log', hostname='c-0',
                context=(['b1'], ['a1'])),
            PatternResult(
                timestamp='2024-01-06T10:00:01.000',
                block_label='Multi', log_line='MATCH 2',
                actual_filename='test.log', hostname='c-0',
                context=(['b2'], ['a2'])),
        ]
        write_context_files(output_dir, blocks, results)
        with open(os.path.join(output_dir, 'Multi.context'), 'r') as f:
            content = f.read()
        self.assertIn('Match 1', content)
        self.assertIn('Match 2', content)
        self.assertIn('Matches: 2', content)
        self.assertIn('> MATCH 1', content)
        self.assertIn('> MATCH 2', content)

    def test_write_context_files_multiple_blocks(self):
        """write_context_files creates separate files per block"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)

        blocks = [
            {'label': 'Block A', 'file': 'a.log',
             'patterns': ['A'], 'context_before': 1, 'context_after': 1},
            {'label': 'Block B', 'file': 'b.log',
             'patterns': ['B'], 'context_before': 2, 'context_after': 2},
        ]
        results = [
            PatternResult(
                timestamp='t1', block_label='Block A', log_line='HIT A',
                actual_filename='a.log', hostname='c-0',
                context=(['ba'], ['aa'])),
            PatternResult(
                timestamp='t2', block_label='Block B', log_line='HIT B',
                actual_filename='b.log', hostname='c-0',
                context=(['bb1', 'bb2'], ['ab1', 'ab2'])),
        ]
        write_context_files(output_dir, blocks, results)
        self.assertTrue(os.path.exists(os.path.join(output_dir, 'Block_A.context')))
        self.assertTrue(os.path.exists(os.path.join(output_dir, 'Block_B.context')))

    def test_write_context_files_no_matching_results(self):
        """Block with context but no matching results produces no file"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)

        blocks = [{
            'label': 'Empty', 'file': 'test.log',
            'patterns': ['X'], 'context_before': 2, 'context_after': 2,
        }]
        write_context_files(output_dir, blocks, [])  # no results
        self.assertFalse(os.path.exists(
            os.path.join(output_dir, 'Empty.context')))

    def test_write_context_files_empty_context_tuples(self):
        """Results with empty context tuples still produce output"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)

        blocks = [{
            'label': 'Edge', 'file': 'test.log',
            'patterns': ['E'], 'context_before': 5, 'context_after': 5,
        }]
        results = [
            PatternResult(
                timestamp='t1', block_label='Edge', log_line='EDGE HIT',
                actual_filename='test.log', hostname='c-0',
                context=([], [])),
        ]
        write_context_files(output_dir, blocks, results)
        with open(os.path.join(output_dir, 'Edge.context'), 'r') as f:
            content = f.read()
        self.assertIn('> EDGE HIT', content)
        self.assertIn('Matches: 1', content)

    def test_write_context_files_timeline_result(self):
        """write_context_files works with TimelineResult objects"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)

        blocks = [{
            'label': 'TL Block', 'file': 'test.log',
            'timeline': ['ev'], 'context_before': 1, 'context_after': 1,
        }]
        results = [
            TimelineResult(
                timestamp='2024-01-06T10:00:00.000',
                block_label='TL Block', log_line='timeline event',
                actual_filename='test.log', hostname='c-0',
                context=(['before tl'], ['after tl'])),
        ]
        write_context_files(output_dir, blocks, results)
        ctx_file = os.path.join(output_dir, 'TL_Block.context')
        self.assertTrue(os.path.exists(ctx_file))
        with open(ctx_file, 'r') as f:
            content = f.read()
        self.assertIn('> timeline event', content)
        self.assertIn('before tl', content)
        self.assertIn('after tl', content)

    def test_write_context_files_skips_blocks_without_context(self):
        """Blocks without context_before produce no context file"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)

        blocks = [{
            'label': 'No Ctx', 'file': 'test.log',
            'patterns': ['p'],
            # no context_before / context_after
        }]
        results = [
            PatternResult(
                timestamp='t1', block_label='No Ctx', log_line='hit',
                actual_filename='test.log', hostname='c-0'),
        ]
        write_context_files(output_dir, blocks, results)
        self.assertFalse(os.path.exists(
            os.path.join(output_dir, 'No_Ctx.context')))

    def test_write_context_files_result_with_none_context_skipped(self):
        """Results where context is None are filtered out"""
        output_dir = os.path.join(self.temp_dir, 'output')
        os.makedirs(output_dir)

        blocks = [{
            'label': 'Mixed', 'file': 'test.log',
            'patterns': ['p'], 'context_before': 1, 'context_after': 1,
        }]
        results = [
            PatternResult(
                timestamp='t1', block_label='Mixed', log_line='no ctx',
                actual_filename='test.log', hostname='c-0',
                context=None),  # explicitly None
            PatternResult(
                timestamp='t2', block_label='Mixed', log_line='has ctx',
                actual_filename='test.log', hostname='c-0',
                context=(['b'], ['a'])),
        ]
        write_context_files(output_dir, blocks, results)
        with open(os.path.join(output_dir, 'Mixed.context'), 'r') as f:
            content = f.read()
        self.assertIn('Matches: 1', content)
        self.assertIn('> has ctx', content)
        self.assertNotIn('no ctx', content)


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestWindowIntegration(LPMPTestBase):
    """Integration tests that run lpmptool main() with window models"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_dir = self.temp_dir
        self.model_file = os.path.join(self.temp_dir, 'model.yaml')
        self.output_dir = os.path.join(self.temp_dir, 'out')
        # Create log files
        with open(os.path.join(self.log_dir, 'app.log'), 'w') as f:
            f.write('2024-01-06T10:00:00.000 app started\n')
            f.write('2024-01-06T10:00:01.000 app running\n')
            f.write('2024-01-06T10:00:02.000 app ready\n')
        with open(os.path.join(self.log_dir, 'sys.log'), 'w') as f:
            f.write('2024-01-06T10:00:00.500 sys event 1\n')
            f.write('2024-01-06T10:00:01.500 sys event 2\n')

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_window_model_produces_timeline_output(self):
        """Window model produces .timeline.log output with all log lines"""
        model_data = {
            'blocks': [{
                'label': 'All Logs',
                'file': '*.log',
                'window': True
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'lpmptool',
            '--logs-dir', self.log_dir,
            '--model-file', self.model_file,
            '--output', self.output_dir,
            '--start-date', '2024-01-06T09:00:00',
            '--stop-date', '2024-01-06T11:00:00',
        ]):
            with open(os.devnull, 'w') as devnull:
                with patch('sys.stdout', devnull):
                    lpmptool.main()

        # Find timeline output file
        timeline_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.timeline.log'):
                    timeline_files.append(os.path.join(root, f))
        self.assertTrue(len(timeline_files) > 0)

        with open(timeline_files[0], 'r') as f:
            content = f.read()
        # Should contain lines from both log files
        self.assertIn('app started', content)
        self.assertIn('sys event', content)

    def test_context_produces_context_file(self):
        """Pattern model with context: produces .context output file"""
        model_data = {
            'blocks': [{
                'label': 'App Ready',
                'file': 'app.log',
                'patterns': ['app ready'],
                'context': [2, 1]
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'lpmptool',
            '--logs-dir', self.log_dir,
            '--model-file', self.model_file,
            '--output', self.output_dir,
        ]):
            with patch('builtins.print'):
                lpmptool.main()

        # Find .context file
        context_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.context'):
                    context_files.append(os.path.join(root, f))
        self.assertTrue(len(context_files) > 0,
                        f"No .context files found under {self.output_dir}")

        with open(context_files[0], 'r') as f:
            content = f.read()
        self.assertIn('> ', content)
        self.assertIn('app ready', content)

    def test_stop_date_from_model_settings(self):
        """stop_date in model settings is used when -e not provided"""
        model_data = {
            'settings': {
                'start_date': '2024-01-06T10:00:00',
                'stop_date': '2024-01-06T10:00:01',
            },
            'blocks': [{
                'label': 'All Logs',
                'file': '*.log',
                'window': True
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'lpmptool',
            '--logs-dir', self.log_dir,
            '--model-file', self.model_file,
            '--output', self.output_dir,
        ]):
            with open(os.devnull, 'w') as devnull:
                with patch('sys.stdout', devnull):
                    lpmptool.main()

        # Find timeline output
        timeline_files = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith('.timeline.log'):
                    timeline_files.append(os.path.join(root, f))
        self.assertTrue(len(timeline_files) > 0)

        with open(timeline_files[0], 'r') as f:
            content = f.read()
        # Should contain lines within the 1-second window
        self.assertIn('sys event 1', content)
        # Lines after stop_date should not be present
        self.assertNotIn('app ready', content)

    def _create_bundle(self, hosts_data):
        """Helper: create a synthetic bundle with per-host log files.

        Args:
            hosts_data: dict of {hostname: {filename: [lines]}}
        Returns:
            bundle_dir path
        """
        bundle_dir = os.path.join(self.temp_dir, 'bundle')
        for hostname, files in hosts_data.items():
            logs_dir = os.path.join(
                bundle_dir, f'{hostname}_20240106.100000', 'var', 'log'
            )
            os.makedirs(logs_dir, exist_ok=True)
            for fname, lines in files.items():
                with open(os.path.join(logs_dir, fname), 'w') as f:
                    f.write('\n'.join(lines) + '\n')
        return bundle_dir

    def test_window_bundle_auto_detect_uses_all_hosts(self):
        """Window auto-detect finds latest timestamp across ALL hosts"""
        bundle_dir = self._create_bundle({
            'controller-0': {
                'app.log': [
                    '2024-01-06T10:00:00.000 c0 early',
                    '2024-01-06T10:05:00.000 c0 late',
                ],
            },
            'controller-1': {
                'app.log': [
                    '2024-01-06T10:00:00.000 c1 early',
                    '2024-01-06T10:10:00.000 c1 latest across bundle',
                ],
            },
        })
        model_data = {
            'blocks': [{'label': 'All', 'file': '*.log', 'window': True}]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        output = []

        def capture(*a, **kw):
            output.append(' '.join(str(x) for x in a))

        with patch('sys.argv', [
            'lpmptool', '-b', bundle_dir,
            '-m', self.model_file, '-o', self.output_dir,
        ]):
            with patch('builtins.print', side_effect=capture):
                lpmptool.main()

        combined = '\n'.join(output)
        # The auto-detected window must include controller-1's latest
        # timestamp (10:10), not stop at controller-0's (10:05)
        self.assertIn('10:10:00', combined,
                      'Window end should reflect latest timestamp '
                      'across all hosts, not just the first')

    def test_window_bundle_prescan_shows_all_hosts(self):
        """Window pre-scan summary lists every host, not just the first"""
        bundle_dir = self._create_bundle({
            'controller-0': {
                'app.log': [
                    '2024-01-06T10:00:00.000 c0 line',
                ],
            },
            'controller-1': {
                'app.log': [
                    '2024-01-06T10:00:00.000 c1 line',
                ],
                'sys.log': [
                    '2024-01-06T10:00:00.000 c1 sys line',
                ],
            },
        })
        model_data = {
            'blocks': [{'label': 'All', 'file': '*.log', 'window': True}]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        output = []

        def capture(*a, **kw):
            output.append(' '.join(str(x) for x in a))

        with patch('sys.argv', [
            'lpmptool', '-b', bundle_dir,
            '-m', self.model_file, '-o', self.output_dir,
        ]):
            with patch('builtins.print', side_effect=capture):
                lpmptool.main()

        combined = '\n'.join(output)
        self.assertIn('controller-0:', combined,
                      'Pre-scan should list controller-0')
        self.assertIn('controller-1:', combined,
                      'Pre-scan should list controller-1')
        # controller-1 has 2 log files, controller-0 has 1
        self.assertIn('controller-1: 2 matched', combined,
                      'controller-1 should show 2 matched files')


BUNDLE_PATH = os.environ.get('LPMP_TEST_BUNDLE')
DEFAULT_LOGS_DIR = 'var/log'


def _bundle_host_dir(bundle, hostname):
    """Find the dated directory for a hostname inside a bundle."""
    if not bundle or not os.path.isdir(bundle):
        return None
    for entry in os.listdir(bundle):
        if entry.startswith(hostname + '_') and os.path.isdir(
                os.path.join(bundle, entry)):
            return os.path.join(bundle, entry)
    return None


def _bundle_logs_dir(bundle, hostname):
    """Return the var/log path for a hostname inside a bundle."""
    host_dir = _bundle_host_dir(bundle, hostname)
    if host_dir:
        return os.path.join(host_dir, DEFAULT_LOGS_DIR)
    return None


@unittest.skipUnless(BUNDLE_PATH, "Set LPMP_TEST_BUNDLE or use run_tests.py -b")
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestContextBundleIntegration(LPMPTestBase):
    """Context feature tests that require a real collect bundle.

    Enable with:
        python run_tests.py --bundle /path/to/bundle
        python run_tests.py -b default
        python run_tests.py -b
    """

    def setUp(self):
        self.bundle = BUNDLE_PATH
        self.c0_logs = _bundle_logs_dir(self.bundle, 'controller-0')
        self.c1_logs = _bundle_logs_dir(self.bundle, 'controller-1')
        self.temp_dir = tempfile.mkdtemp()
        self.model_file = os.path.join(self.temp_dir, 'model.yaml')
        self.output_dir = os.path.join(self.temp_dir, 'out')

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _find_output_files(self, suffix):
        """Walk output_dir and return list of files ending with suffix."""
        found = []
        for root, dirs, files in os.walk(self.output_dir):
            for f in files:
                if f.endswith(suffix):
                    found.append(os.path.join(root, f))
        return found

    # ------------------------------------------------------------------
    # Test 1: Context extraction from a gzipped log in the bundle
    # ------------------------------------------------------------------
    def test_context_from_gzipped_log(self):
        """extract_context_lines reads surrounding lines from a .gz file"""
        if not self.c0_logs:
            self.skipTest('controller-0 logs not found in bundle')
        gz_files = [f for f in os.listdir(self.c0_logs) if f.endswith('.gz')]
        if not gz_files:
            self.skipTest('No .gz log files in controller-0 logs')

        target_file = None
        target_line = None
        for gz in gz_files:
            try:
                with gzip.open(os.path.join(self.c0_logs, gz), 'rt',
                               encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                if len(lines) >= 5:
                    target_file = gz
                    target_line = lines[2].rstrip('\n\r')
                    break
            except Exception:
                continue
        if not target_file:
            self.skipTest('No .gz file with >= 5 lines found')

        before, after = extract_context_lines(
            self.c0_logs, target_file, target_line, 2, 2
        )
        self.assertGreater(len(before), 0, 'Expected before-context lines')
        self.assertGreater(len(after), 0, 'Expected after-context lines')

    # ------------------------------------------------------------------
    # Test 2: Pattern model with context against real sm.log
    # ------------------------------------------------------------------
    def test_context_pattern_model_real_logs(self):
        """Pattern model with context: produces .context file from real logs"""
        if not self.c0_logs:
            self.skipTest('controller-0 logs not found in bundle')
        sm_log = os.path.join(self.c0_logs, 'sm.log')
        if not os.path.exists(sm_log):
            self.skipTest('sm.log not found in controller-0 logs')

        model_data = {
            'blocks': [{
                'label': 'SM Start',
                'file': 'sm.log',
                'patterns': ['Starting'],
                'context': 3,
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'lpmptool',
            '--logs-dir', self.c0_logs,
            '--model-file', self.model_file,
            '--output', self.output_dir,
        ]):
            with patch('builtins.print'):
                lpmptool.main()

        ctx_files = self._find_output_files('.context')
        self.assertTrue(len(ctx_files) > 0, 'No .context file produced')
        with open(ctx_files[0], 'r') as f:
            content = f.read()
        self.assertIn('>', content)

    # ------------------------------------------------------------------
    # Test 3: Timeline model with context against real mtcAgent.log
    # ------------------------------------------------------------------
    def test_context_timeline_model_real_logs(self):
        """Timeline model with context: produces .context file from real logs"""
        if not self.c0_logs:
            self.skipTest('controller-0 logs not found in bundle')
        mtc_log = os.path.join(self.c0_logs, 'mtcAgent.log')
        if not os.path.exists(mtc_log):
            self.skipTest('mtcAgent.log not found in controller-0 logs')

        model_data = {
            'blocks': [{
                'label': 'Mtce Events',
                'file': 'mtcAgent.log',
                'timeline': ['daemon_init', 'Daemon Start'],
                'context': [2, 4],
            }]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'lpmptool',
            '--logs-dir', self.c0_logs,
            '--model-file', self.model_file,
            '--output', self.output_dir,
        ]):
            with patch('builtins.print'):
                lpmptool.main()

        ctx_files = self._find_output_files('.context')
        self.assertTrue(len(ctx_files) > 0, 'No .context file produced')
        with open(ctx_files[0], 'r') as f:
            content = f.read()
        self.assertIn('Context lines: 2 before, 4 after', content)

    # ------------------------------------------------------------------
    # Test 4: Override block context in bundle mode
    # ------------------------------------------------------------------
    def test_context_override_block_bundle(self):
        """Override block reads context from peer controller's logs"""
        if not self.c0_logs or not self.c1_logs:
            self.skipTest('Need both controller-0 and controller-1 in bundle')

        model_data = {
            'blocks': [
                {
                    'label': 'Local Event',
                    'file': 'mtcAgent.log',
                    'patterns': ['Daemon Start'],
                    'context': 2,
                },
                {
                    'label': 'Peer Event',
                    'file': 'mtcAgent.log',
                    'patterns': ['Daemon Start'],
                    'override': 'controller-1',
                    'optional': True,
                    'context': 2,
                    'max_time_delta': 600,
                },
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'lpmptool',
            '-b', self.bundle,
            '--model-file', self.model_file,
            '--output', self.output_dir,
            '--include', 'controller-0',
        ]):
            with patch('builtins.print'):
                try:
                    lpmptool.main()
                except SystemExit:
                    pass

        ctx_files = self._find_output_files('.context')
        self.assertTrue(len(ctx_files) > 0,
                        'Expected at least one .context file from override block')

    # ------------------------------------------------------------------
    # Test 5: Window model + context combined
    # ------------------------------------------------------------------
    def test_window_model_with_context_bundle(self):
        """Window model skips binary/non-log files; context not applicable
        to window blocks but other blocks in same model can have context
        """
        if not self.c0_logs:
            self.skipTest('controller-0 logs not found in bundle')

        model_data = {
            'blocks': [
                {
                    'label': 'SM Window',
                    'file': 'sm.log',
                    'window': True,
                },
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'lpmptool',
            '--logs-dir', self.c0_logs,
            '--model-file', self.model_file,
            '--output', self.output_dir,
        ]):
            with patch('builtins.print'):
                lpmptool.main()

        tl_files = self._find_output_files('.timeline.log')
        self.assertTrue(len(tl_files) > 0,
                        'Window model should produce .timeline.log')

    # ------------------------------------------------------------------
    # Test 6: present: true block not found produces no .context file
    # ------------------------------------------------------------------
    def test_present_block_no_context_file(self):
        """present: true block that is not found produces no .context file"""
        if not self.c0_logs:
            self.skipTest('controller-0 logs not found in bundle')

        model_data = {
            'blocks': [
                {
                    'label': 'Real Event',
                    'file': 'sm.log',
                    'patterns': ['Starting'],
                    'context': 2,
                },
                {
                    'label': 'Ghost Event',
                    'file': 'sm.log',
                    'patterns': ['XYZZY_PATTERN_WILL_NEVER_MATCH_42'],
                    'present': True,
                    'context': 2,
                    'max_time_delta': 600,
                },
            ]
        }
        with open(self.model_file, 'w') as f:
            yaml.dump(model_data, f)

        with patch('sys.argv', [
            'lpmptool',
            '--logs-dir', self.c0_logs,
            '--model-file', self.model_file,
            '--output', self.output_dir,
        ]):
            with patch('builtins.print'):
                lpmptool.main()

        ctx_files = self._find_output_files('.context')
        ctx_names = [os.path.basename(f) for f in ctx_files]
        self.assertIn('Real_Event.context', ctx_names,
                      'Real block should produce .context')
        self.assertNotIn('Ghost_Event.context', ctx_names,
                         'present:true unfound block should NOT produce .context')


# ---------------------------------------------------------------------------
# Tests for performance optimizations (bisect seek, rotation pruning, zcat)
# ---------------------------------------------------------------------------

class TestBisectSeek(LPMPTestBase):
    """Test binary-search seek optimization in find_pattern_in_files_all_matches"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_large_log(self, name, num_lines=500):
        """Create a log file large enough to trigger bisect (>32KB)."""
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            base = datetime(2024, 1, 6, 10, 0, 0)
            for i in range(num_lines):
                ts = base + timedelta(seconds=i)
                # Pad to ensure file exceeds 32KB
                f.write(f"{ts.strftime('%Y-%m-%dT%H:%M:%S.000')} "
                        f"log message line {i} {'x' * 80}\n")
        return path

    def test_bisect_finds_lines_in_window(self):
        """Bisect seek correctly finds lines within the time window"""
        self._create_large_log('big.log', 500)
        after = datetime(2024, 1, 6, 10, 7, 0)  # 420s in

        class FakeArgs:
            stop_date_parsed = datetime(2024, 1, 6, 10, 8, 0)

        matches = find_pattern_in_files_all_matches(
            self.temp_dir, ['big.log'], 'log message', after, FakeArgs()
        )
        self.assertTrue(len(matches) > 0)
        for ts, _, _ in matches:
            self.assertGreater(ts, after)
            self.assertLessEqual(ts, FakeArgs.stop_date_parsed)

    def test_bisect_skipped_for_small_files(self):
        """Small files (<32KB) are scanned linearly without bisect"""
        path = os.path.join(self.temp_dir, 'small.log')
        with open(path, 'w') as f:
            f.write('2024-01-06T10:00:00.000 first\n')
            f.write('2024-01-06T10:00:01.000 second\n')

        after = datetime(2024, 1, 6, 9, 59, 0)

        class FakeArgs:
            stop_date_parsed = None

        matches = find_pattern_in_files_all_matches(
            self.temp_dir, ['small.log'], 'second', after, FakeArgs()
        )
        self.assertEqual(len(matches), 1)
        self.assertIn('second', matches[0][1])

    def test_bisect_no_matches_outside_window(self):
        """Bisect + stop_date correctly returns nothing when window is empty"""
        self._create_large_log('big.log', 500)
        after = datetime(2024, 1, 6, 11, 0, 0)  # past all data

        class FakeArgs:
            stop_date_parsed = datetime(2024, 1, 6, 11, 1, 0)

        matches = find_pattern_in_files_all_matches(
            self.temp_dir, ['big.log'], 'log message', after, FakeArgs()
        )
        self.assertEqual(len(matches), 0)


class TestRotationPrune(LPMPTestBase):
    """Test rotation-aware .gz file pruning"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_gz(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with gzip.open(path, 'wt') as f:
            f.write('\n'.join(lines) + '\n')
        return path

    def _create_log(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        return path

    def test_higher_rotations_skipped(self):
        """Once rotation N is before window, N+1, N+2... are skipped"""
        _file_date_range_cache.clear()

        # rotation 1 is before window
        self._create_gz('app.log.1.gz', [
            '2024-01-01T10:00:00.000 old line',
            '2024-01-01T10:00:01.000 old line 2',
        ])
        # rotation 2 is even older — should be skipped without reading
        self._create_gz('app.log.2.gz', [
            '2023-12-01T10:00:00.000 very old',
        ])
        # rotation 3 — also skipped
        self._create_gz('app.log.3.gz', [
            '2023-11-01T10:00:00.000 ancient',
        ])

        all_files = [
            os.path.join(self.temp_dir, 'app.log.1.gz'),
            os.path.join(self.temp_dir, 'app.log.2.gz'),
            os.path.join(self.temp_dir, 'app.log.3.gz'),
        ]
        start = datetime(2024, 1, 6, 10, 0, 0)
        result = _rotation_prune(all_files, self.temp_dir, start)
        self.assertEqual(len(result), 0)

    def test_non_gz_files_pass_through(self):
        """Plain text files are never pruned by rotation logic"""
        _file_date_range_cache.clear()

        self._create_log('app.log', [
            '2024-01-01T10:00:00.000 old plain file',
        ])
        all_files = [os.path.join(self.temp_dir, 'app.log')]
        start = datetime(2024, 1, 6, 10, 0, 0)
        result = _rotation_prune(all_files, self.temp_dir, start)
        self.assertEqual(len(result), 1)

    def test_rotation_in_window_kept(self):
        """Rotation whose date range overlaps window is kept"""
        _file_date_range_cache.clear()

        self._create_gz('app.log.1.gz', [
            '2024-01-06T09:00:00.000 recent line',
            '2024-01-06T11:00:00.000 recent line 2',
        ])
        all_files = [os.path.join(self.temp_dir, 'app.log.1.gz')]
        start = datetime(2024, 1, 6, 10, 0, 0)
        result = _rotation_prune(all_files, self.temp_dir, start)
        self.assertEqual(len(result), 1)

    def test_mixed_bases_independent(self):
        """Different base names are pruned independently"""
        _file_date_range_cache.clear()

        # app.log.1.gz is before window
        self._create_gz('app.log.1.gz', [
            '2024-01-01T10:00:00.000 old app',
        ])
        # sys.log.1.gz overlaps window — should be kept
        self._create_gz('sys.log.1.gz', [
            '2024-01-06T09:00:00.000 recent sys',
            '2024-01-06T11:00:00.000 recent sys 2',
        ])
        all_files = [
            os.path.join(self.temp_dir, 'app.log.1.gz'),
            os.path.join(self.temp_dir, 'sys.log.1.gz'),
        ]
        start = datetime(2024, 1, 6, 10, 0, 0)
        result = _rotation_prune(all_files, self.temp_dir, start)
        self.assertEqual(len(result), 1)
        self.assertIn('sys.log.1.gz', result[0])


class TestGzDateRange(LPMPTestBase):
    """Test get_file_date_range with .gz files using zcat|tail"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_gz_first_and_last_timestamp(self):
        """get_file_date_range returns correct first/last for .gz files"""
        _file_date_range_cache.clear()

        path = os.path.join(self.temp_dir, 'test.log.1.gz')
        with gzip.open(path, 'wt') as f:
            f.write('2024-01-06T10:00:00.000 first line\n')
            f.write('2024-01-06T10:00:01.000 middle line\n')
            f.write('2024-01-06T10:00:02.000 last line\n')

        first_ts, last_ts = get_file_date_range(path)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 0, 2))

    def test_gz_single_line(self):
        """get_file_date_range handles single-line .gz file"""
        _file_date_range_cache.clear()

        path = os.path.join(self.temp_dir, 'one.log.1.gz')
        with gzip.open(path, 'wt') as f:
            f.write('2024-01-06T10:00:00.000 only line\n')

        first_ts, last_ts = get_file_date_range(path)
        self.assertEqual(first_ts, datetime(2024, 1, 6, 10, 0, 0))
        self.assertEqual(last_ts, datetime(2024, 1, 6, 10, 0, 0))

    def test_gz_cached_on_second_call(self):
        """Second call uses cache, not subprocess"""
        _file_date_range_cache.clear()

        path = os.path.join(self.temp_dir, 'cached.log.1.gz')
        with gzip.open(path, 'wt') as f:
            f.write('2024-01-06T10:00:00.000 line\n')

        first_call = get_file_date_range(path)
        self.assertIn(path, _file_date_range_cache)
        second_call = get_file_date_range(path)
        self.assertEqual(first_call, second_call)


class TestDiscoverWithRotation(LPMPTestBase):
    """Test discover_window_files with rotation-aware pruning"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_log(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def _create_gz(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with gzip.open(path, 'wt') as f:
            f.write('\n'.join(lines) + '\n')

    def test_old_rotations_skipped_in_discover(self):
        """discover_window_files skips old .gz rotations efficiently"""
        _file_date_range_cache.clear()

        # Current log in window
        self._create_log('app.log', [
            '2024-01-06T10:00:00.000 current',
            '2024-01-06T10:30:00.000 current 2',
        ])
        # Rotation 1 before window
        self._create_gz('app.log.1.gz', [
            '2024-01-01T10:00:00.000 old',
            '2024-01-01T11:00:00.000 old 2',
        ])
        # Rotation 2 even older — should be skipped without reading
        self._create_gz('app.log.2.gz', [
            '2023-12-01T10:00:00.000 very old',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start, stop
        )

        matched_names = [m[0] for m in matched]
        skipped_names = [s[0] for s in skipped]
        self.assertIn('app.log', matched_names)
        self.assertIn('app.log.1.gz', skipped_names)
        self.assertIn('app.log.2.gz', skipped_names)

    def test_rotation_2_not_read_when_1_before_window(self):
        """Higher rotations are not in cache — proves they were skipped"""
        _file_date_range_cache.clear()

        self._create_gz('kern.log.1.gz', [
            '2024-01-01T10:00:00.000 old kern',
            '2024-01-01T11:00:00.000 old kern 2',
        ])
        self._create_gz('kern.log.2.gz', [
            '2023-06-01T10:00:00.000 ancient kern',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        discover_window_files(self.temp_dir, ['*'], start, stop)

        # kern.log.1.gz was read (in cache), kern.log.2.gz was not
        gz1 = os.path.join(self.temp_dir, 'kern.log.1.gz')
        gz2 = os.path.join(self.temp_dir, 'kern.log.2.gz')
        self.assertIn(gz1, _file_date_range_cache)
        self.assertNotIn(gz2, _file_date_range_cache)


class TestFailureAndEdgeCases(LPMPTestBase):
    """Failure handling and edge cases for performance optimizations"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_log(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        return path

    def _create_gz(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with gzip.open(path, 'wt') as f:
            f.write('\n'.join(lines) + '\n')
        return path

    def test_bisect_file_with_no_timestamps(self):
        """Bisect handles file with no parseable timestamps gracefully"""
        path = os.path.join(self.temp_dir, 'notime.log')
        with open(path, 'w') as f:
            for i in range(500):
                f.write(f'no timestamp here line {i} {"x" * 80}\n')

        after = datetime(2024, 1, 6, 10, 0, 0)

        class FakeArgs:
            stop_date_parsed = None

        matches = find_pattern_in_files_all_matches(
            self.temp_dir, ['notime.log'], 'line', after, FakeArgs()
        )
        self.assertEqual(len(matches), 0)

    def test_bisect_file_with_sparse_timestamps(self):
        """Bisect handles file where most lines lack timestamps"""
        path = os.path.join(self.temp_dir, 'sparse.log')
        with open(path, 'w') as f:
            f.write('2024-01-06T10:00:00.000 first timestamped\n')
            for i in range(400):
                f.write(f'continuation line {i} no timestamp {"y" * 60}\n')
            f.write('2024-01-06T10:05:00.000 second timestamped\n')
            for i in range(100):
                f.write(f'more continuation {i} {"z" * 60}\n')

        after = datetime(2024, 1, 6, 10, 4, 0)

        class FakeArgs:
            stop_date_parsed = None

        matches = find_pattern_in_files_all_matches(
            self.temp_dir, ['sparse.log'], 'timestamped', after, FakeArgs()
        )
        self.assertEqual(len(matches), 1)
        self.assertIn('second timestamped', matches[0][1])

    def test_gz_corrupt_file_returns_none(self):
        """Corrupt .gz file returns (None, None) without crashing"""
        _file_date_range_cache.clear()

        path = os.path.join(self.temp_dir, 'corrupt.log.1.gz')
        with open(path, 'wb') as f:
            f.write(b'this is not valid gzip data')

        first_ts, last_ts = get_file_date_range(path)
        self.assertIsNone(first_ts)
        self.assertIsNone(last_ts)

    def test_gz_empty_file_returns_none(self):
        """Empty .gz file returns (None, None)"""
        _file_date_range_cache.clear()

        path = os.path.join(self.temp_dir, 'empty.log.1.gz')
        with gzip.open(path, 'wt') as f:
            pass  # empty file

        first_ts, last_ts = get_file_date_range(path)
        self.assertIsNone(first_ts)
        self.assertIsNone(last_ts)

    def test_gz_no_timestamps_returns_none(self):
        """gz file with content but no timestamps returns (None, None)"""
        _file_date_range_cache.clear()

        self._create_gz('nots.log.1.gz', [
            'no timestamp here',
            'also no timestamp',
        ])
        path = os.path.join(self.temp_dir, 'nots.log.1.gz')
        first_ts, last_ts = get_file_date_range(path)
        self.assertIsNone(first_ts)
        self.assertIsNone(last_ts)

    def test_rotation_prune_gz_without_rotation_number(self):
        """gz file without rotation number (e.g. archive.gz) passes through"""
        _file_date_range_cache.clear()

        self._create_gz('archive.gz', [
            '2024-01-01T10:00:00.000 old data',
        ])
        all_files = [os.path.join(self.temp_dir, 'archive.gz')]
        start = datetime(2024, 1, 6, 10, 0, 0)
        result = _rotation_prune(all_files, self.temp_dir, start)
        # No rotation number means it's not grouped — passes through
        self.assertEqual(len(result), 1)

    def test_rotation_prune_empty_list(self):
        """Empty file list returns empty result"""
        result = _rotation_prune([], self.temp_dir, datetime(2024, 1, 6))
        self.assertEqual(result, [])

    def test_rotation_prune_gz_no_timestamps(self):
        """gz rotation with no timestamps is skipped, doesn't block siblings"""
        _file_date_range_cache.clear()

        # rotation 1 has no timestamps
        self._create_gz('app.log.1.gz', ['no timestamp here'])
        # rotation 2 is in window — should still be checked
        self._create_gz('app.log.2.gz', [
            '2024-01-06T10:00:00.000 in window',
            '2024-01-06T11:00:00.000 in window 2',
        ])
        all_files = [
            os.path.join(self.temp_dir, 'app.log.1.gz'),
            os.path.join(self.temp_dir, 'app.log.2.gz'),
        ]
        start = datetime(2024, 1, 6, 9, 0, 0)
        result = _rotation_prune(all_files, self.temp_dir, start)
        self.assertEqual(len(result), 1)
        self.assertIn('app.log.2.gz', result[0])

    def test_discover_no_start_date_skips_rotation_prune(self):
        """Without start_date, rotation pruning is not applied"""
        _file_date_range_cache.clear()

        self._create_log('app.log', ['2024-01-06T10:00:00.000 current'])
        self._create_gz('app.log.1.gz', [
            '2024-01-01T10:00:00.000 old',
        ])

        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start_date=None, stop_date=None
        )
        matched_names = [m[0] for m in matched]
        self.assertIn('app.log', matched_names)
        self.assertIn('app.log.1.gz', matched_names)


class TestWindowGzCoverage(LPMPTestBase):
    """Test .gz log files are correctly classified (matched vs skipped)
    by discover_window_files based on whether their date range overlaps
    the requested time window.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_log(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')

    def _create_gz(self, name, lines):
        path = os.path.join(self.temp_dir, name)
        with gzip.open(path, 'wt') as f:
            f.write('\n'.join(lines) + '\n')

    def test_gz_overlapping_window_is_matched(self):
        """A .gz file whose date range overlaps the window is matched"""
        _file_date_range_cache.clear()

        # rotation 1 spans across the window boundary
        self._create_gz('app.log.1.gz', [
            '2024-01-06T09:00:00.000 before window',
            '2024-01-06T10:30:00.000 in window',
            '2024-01-06T11:30:00.000 after window',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start, stop
        )
        matched_names = [m[0] for m in matched]
        self.assertIn('app.log.1.gz', matched_names)

    def test_gz_entirely_before_window_is_skipped(self):
        """A .gz file entirely before the window is skipped"""
        _file_date_range_cache.clear()

        self._create_gz('app.log.1.gz', [
            '2024-01-01T10:00:00.000 old',
            '2024-01-01T11:00:00.000 old 2',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start, stop
        )
        matched_names = [m[0] for m in matched]
        skipped_names = [s[0] for s in skipped]
        self.assertNotIn('app.log.1.gz', matched_names)
        self.assertIn('app.log.1.gz', skipped_names)

    def test_gz_entirely_after_window_is_skipped(self):
        """A .gz file entirely after the window is skipped"""
        _file_date_range_cache.clear()

        self._create_gz('app.log.1.gz', [
            '2024-01-10T10:00:00.000 future',
            '2024-01-10T11:00:00.000 future 2',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start, stop
        )
        matched_names = [m[0] for m in matched]
        self.assertNotIn('app.log.1.gz', matched_names)

    def test_gz_rotation_1_in_window_rotation_2_before(self):
        """Rotation 1 overlaps window (kept), rotation 2 before (skipped)"""
        _file_date_range_cache.clear()

        self._create_gz('syslog.1.gz', [
            '2024-01-06T09:00:00.000 recent',
            '2024-01-06T10:30:00.000 in window',
        ])
        self._create_gz('syslog.2.gz', [
            '2024-01-01T10:00:00.000 old',
            '2024-01-01T11:00:00.000 old 2',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start, stop
        )
        matched_names = [m[0] for m in matched]
        skipped_names = [s[0] for s in skipped]
        self.assertIn('syslog.1.gz', matched_names)
        self.assertIn('syslog.2.gz', skipped_names)

    def test_gz_window_boundary_exact_match(self):
        """File whose last_ts equals start_date is included (boundary)"""
        _file_date_range_cache.clear()

        self._create_gz('edge.log.1.gz', [
            '2024-01-06T09:00:00.000 before',
            '2024-01-06T10:00:00.000 exactly at start',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start, stop
        )
        matched_names = [m[0] for m in matched]
        self.assertIn('edge.log.1.gz', matched_names)

    def test_gz_window_boundary_just_before(self):
        """File whose last_ts is 1ms before start_date is skipped"""
        _file_date_range_cache.clear()

        self._create_gz('miss.log.1.gz', [
            '2024-01-06T09:00:00.000 before',
            '2024-01-06T09:59:59.999 just before',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start, stop
        )
        matched_names = [m[0] for m in matched]
        self.assertNotIn('miss.log.1.gz', matched_names)

    def test_mixed_plain_and_gz_all_classified_correctly(self):
        """Mix of plain and .gz files: each classified by its date range"""
        _file_date_range_cache.clear()

        # Plain file in window
        self._create_log('app.log', [
            '2024-01-06T10:00:00.000 current',
            '2024-01-06T10:30:00.000 current 2',
        ])
        # gz rotation 1 overlaps window
        self._create_gz('app.log.1.gz', [
            '2024-01-06T09:00:00.000 recent gz',
            '2024-01-06T10:15:00.000 in window gz',
        ])
        # gz rotation 2 before window
        self._create_gz('app.log.2.gz', [
            '2024-01-01T10:00:00.000 old gz',
        ])
        # gz rotation 3 even older — should be skipped by rotation prune
        self._create_gz('app.log.3.gz', [
            '2023-06-01T10:00:00.000 ancient gz',
        ])
        # Different base, in window
        self._create_log('sys.log', [
            '2024-01-06T10:05:00.000 sys event',
        ])

        start = datetime(2024, 1, 6, 10, 0, 0)
        stop = datetime(2024, 1, 6, 11, 0, 0)
        matched, skipped = discover_window_files(
            self.temp_dir, ['*'], start, stop
        )
        matched_names = set(m[0] for m in matched)
        skipped_names = set(s[0] for s in skipped)

        self.assertIn('app.log', matched_names)
        self.assertIn('app.log.1.gz', matched_names)
        self.assertIn('sys.log', matched_names)
        self.assertIn('app.log.2.gz', skipped_names)
        self.assertIn('app.log.3.gz', skipped_names)
        # rotation 3 should NOT be in cache (skipped by rotation prune)
        gz3 = os.path.join(self.temp_dir, 'app.log.3.gz')
        self.assertNotIn(gz3, _file_date_range_cache)


if __name__ == '__main__':
    unittest.main()
