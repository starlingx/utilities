#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test suite for LPMP block processing functionality

Tests pattern block, pair block, and auto-detect block processing including:
- Pattern matching across single and multiple files
- Pair block start/stop timing
- Block-level max_time_delta overrides
- Optional blocks, out-of-order timestamps
- Error handling for missing patterns
"""

from datetime import datetime
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

from lpmp_engine import process_blocks_auto_detect  # noqa: E402
from lpmp_engine import process_pair_block          # noqa: E402
from lpmp_engine import process_pattern_block       # noqa: E402


# Disabled unless PyYAML is installed (pip3 install --user pyyaml)
@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestProcessBlocks(unittest.TestCase):
    """Test block processing functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

        # Create mock args object
        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.block_time_tolerance = 1.0

        self.args = MockArgs(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_process_pattern_block(self):
        """Test processing pattern blocks"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 target pattern
2024-01-06T10:02:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Block',
            'file': 'test.log',
            'patterns': ['target pattern'],
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pattern_block(self.args, block, start_date)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)  # Should have one result for one pattern
        timestamp, line, filename, output_hostname = result[0]
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 1, 0))
        self.assertIn("target pattern", line)

    def test_process_pair_block(self):
        """Test processing pair blocks"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 start pattern
2024-01-06T10:01:30.000 stop pattern
2024-01-06T10:03:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Pair',
            'file': 'test.log',
            'start': 'start pattern',
            'stop': 'stop pattern'
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pair_block(self.args, block, start_date)

        self.assertIsNotNone(result)
        timestamps, duration_info, filename = result
        start_timestamp, stop_timestamp = timestamps
        self.assertEqual(start_timestamp, datetime(2024, 1, 6, 10, 1, 0))  # Start timestamp
        self.assertIn("2024-01-06 10:01:00.000: Start -> Stop: 2024-01-06 10:01:30.000:  30.0s", duration_info)

    def test_process_pair_block_timeout(self):
        """Test processing pair blocks with timeout (max_time_delta exceeded)"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 start pattern
2024-01-06T10:02:00.000 stop pattern
2024-01-06T10:03:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Pair Timeout',
            'file': 'test.log',
            'start': 'start pattern',
            'stop': 'stop pattern'
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        # Use default max_time_delta=45, but patterns are 60s apart
        result = process_pair_block(self.args, block, start_date)

        # Should return None due to timeout
        self.assertIsNone(result)

    def test_process_pair_block_missing_start(self):
        """Test processing pair blocks when start pattern is missing"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:02:00.000 stop pattern
2024-01-06T10:03:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Missing Start',
            'file': 'test.log',
            'start': 'start pattern',
            'stop': 'stop pattern'
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pair_block(self.args, block, start_date)

        # Should return None when start pattern is missing
        self.assertIsNone(result)

    def test_process_pair_block_missing_stop(self):
        """Test processing pair blocks when stop pattern is missing"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 start pattern
2024-01-06T10:03:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Missing Stop',
            'file': 'test.log',
            'start': 'start pattern',
            'stop': 'stop pattern'
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pair_block(self.args, block, start_date)

        # Should return None when stop pattern is missing
        self.assertIsNone(result)

    def test_process_pair_block_optional(self):
        """Test processing optional pair blocks that fail"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:03:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Optional Pair',
            'file': 'test.log',
            'start': 'start pattern',
            'stop': 'stop pattern',
            'optional': True
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pair_block(self.args, block, start_date)

        # Should return None for optional block with missing patterns
        self.assertIsNone(result)

    def test_process_pattern_block_missing_pattern(self):
        """Test processing pattern blocks when pattern is missing"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:02:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Missing Pattern',
            'file': 'test.log',
            'patterns': ['missing pattern'],
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pattern_block(self.args, block, start_date)

        # Should return None when pattern is missing
        self.assertIsNone(result)

    def test_process_pattern_block_multiple_files(self):
        """Test processing pattern blocks across multiple files"""
        log_file1 = os.path.join(self.temp_dir, "test1.log")
        log_file2 = os.path.join(self.temp_dir, "test2.log")

        log_content1 = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 pattern one"""
        log_content2 = """2024-01-06T10:02:00.000 pattern two
2024-01-06T10:03:00.000 last message"""

        with open(log_file1, 'w') as f:
            f.write(log_content1)
        with open(log_file2, 'w') as f:
            f.write(log_content2)

        block = {
            'label': 'Test Multiple Files',
            'file': ['test1.log', 'test2.log'],
            'patterns': ['pattern one'],
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pattern_block(self.args, block, start_date)

        # Should find both patterns across files
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)  # Should have one result for one pattern
        # Check the result (pattern one)
        timestamp, log_line, filename, output_hostname = result[0]
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 1, 0))
        self.assertIn("pattern one", log_line)

    def test_process_pattern_block_out_of_order_timestamps(self):
        """Test processing pattern blocks with slightly out-of-order timestamps"""
        log_content = """2024-01-06T10:00:00.706 first pattern
2024-01-06T10:00:00.703 second pattern
2024-01-06T10:00:01.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Out of Order',
            'file': 'test.log',
            'patterns': ['first pattern'],
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pattern_block(self.args, block, start_date)

        # Should find second pattern even though timestamp is 3ms earlier
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)  # Should have one result for one pattern
        # Check the result (first pattern)
        timestamp, log_line, filename, output_hostname = result[0]
        self.assertEqual(timestamp, datetime(2024, 1, 6, 10, 0, 0, 706000))
        self.assertIn("first pattern", log_line)

    def test_required_block_error_message_includes_patterns(self):
        """Test that error message includes block label and pattern details when required block fails"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 found pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Test with pattern block
        block = {
            'label': 'Test Missing Required',
            'file': 'test.log',
            'patterns': ['missing pattern'],
            'optional': False,
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pattern_block(self.args, block, start_date)

        # Should return None for missing required pattern
        self.assertIsNone(result)

    def test_block_level_max_time_delta(self):
        """Test block-level max_time_delta overriding global setting"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 start pattern
2024-01-06T10:01:20.000 stop pattern
2024-01-06T10:02:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Block Level Max Time Delta',
            'file': 'test.log',
            'start': 'start pattern',
            'stop': 'stop pattern',
            'max_time_delta': 30  # Block-specific setting
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        # Global max_time_delta is 10 seconds, but block allows 30 seconds
        result = process_pair_block(self.args, block, start_date, global_max_time_delta=10)

        # Should succeed because block-level max_time_delta (30s) is used instead of global (10s)
        self.assertIsNotNone(result)
        timestamps, duration_info, filename = result
        start_timestamp, stop_timestamp = timestamps
        self.assertEqual(start_timestamp, datetime(2024, 1, 6, 10, 1, 0))
        self.assertIn("2024-01-06 10:01:00.000: Start -> Stop: 2024-01-06 10:01:20.000:  20.0s", duration_info)

    def test_block_level_max_time_delta_timeout(self):
        """Test block-level max_time_delta causing timeout"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 start pattern
2024-01-06T10:01:40.000 stop pattern
2024-01-06T10:02:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Block Level Timeout',
            'file': 'test.log',
            'start': 'start pattern',
            'stop': 'stop pattern',
            'max_time_delta': 30  # Block allows only 30 seconds
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        # Block max_time_delta is 30 seconds, but patterns are 40 seconds apart
        result = process_pair_block(self.args, block, start_date, global_max_time_delta=60)

        # Should return None due to block-level timeout (40s > 30s)
        self.assertIsNone(result)

    def test_no_block_level_max_time_delta_uses_global(self):
        """Test that missing block-level max_time_delta uses global setting"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:01:00.000 start pattern
2024-01-06T10:01:20.000 stop pattern
2024-01-06T10:02:00.000 last message"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Global Max Time Delta',
            'file': 'test.log',
            'start': 'start pattern',
            'stop': 'stop pattern'
            # No max_time_delta specified at block level
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        # Global max_time_delta is 30 seconds, patterns are 20 seconds apart
        result = process_pair_block(self.args, block, start_date, global_max_time_delta=30)

        # Should succeed using global setting
        self.assertIsNotNone(result)
        timestamps, duration_info, filename = result
        start_timestamp, stop_timestamp = timestamps
        self.assertEqual(start_timestamp, datetime(2024, 1, 6, 10, 1, 0))
        self.assertIn("2024-01-06 10:01:00.000: Start -> Stop: 2024-01-06 10:01:20.000:  20.0s", duration_info)

    def test_pattern_block_max_time_delta_enforced(self):
        """Test pattern block max_time_delta filters out late matches"""
        log_content = """2024-01-06T10:00:00.000 first message
2024-01-06T10:00:20.000 target pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        block = {
            'label': 'Test Pattern Max Delta',
            'file': 'test.log',
            'patterns': ['target pattern'],
            'max_time_delta': 10,
        }

        start_date = datetime(2024, 1, 6, 10, 0, 0)
        result = process_pattern_block(self.args, block, start_date, max_time_delta=10)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
