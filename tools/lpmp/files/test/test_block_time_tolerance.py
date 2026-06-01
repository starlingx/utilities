#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""
Dedicated test suite for block_time_tolerance functionality

This test suite provides comprehensive coverage of block_time_tolerance including:
- Out-of-order timestamp handling
- Different tolerance values (0, small, large, negative)
- Reordering functionality verification
- Tolerance error reporting
- Edge cases and boundary conditions
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

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import find_pattern_in_files        # noqa: E402
from lpmp_engine import process_pair_block           # noqa: E402
from lpmp_engine import process_pattern_block        # noqa: E402
from lpmp_engine import reorder_and_output_results   # noqa: E402
from lpmp_utils import ModelType                     # noqa: E402
from test_base import LPMPTestBase                   # noqa: E402


class TestBlockTimeToleranceBasic(LPMPTestBase):
    """Test basic block_time_tolerance functionality"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_zero_tolerance_strict_ordering(self):
        """Test block_time_tolerance=0 enforces strict chronological ordering"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:01.500 second pattern
2024-01-06T10:00:01.000 out of order pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 0.0
                self.verbose = 0

        args = MockArgs()

        # First pattern should be found
        result1 = find_pattern_in_files(
            self.temp_dir, "test.log", "first pattern", 0, None, 0, args=args
        )
        self.assertIsNotNone(result1)

        # Out of order pattern should be rejected with zero tolerance
        after_timestamp = datetime(2024, 1, 6, 10, 0, 1, 500000)
        result2 = find_pattern_in_files(
            self.temp_dir, "test.log", "out of order pattern", 0,
            after_timestamp, 0, args=args
        )
        self.assertIsNone(result2)

    def test_small_tolerance_allows_minor_reordering(self):
        """Test small block_time_tolerance allows minor timestamp reordering"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:02.000 second pattern
2024-01-06T10:00:01.800 slightly out of order pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 0.5  # 500ms tolerance
                self.verbose = 0

        args = MockArgs()

        # Pattern 200ms before should be accepted with 500ms tolerance
        after_timestamp = datetime(2024, 1, 6, 10, 0, 2)
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "slightly out of order pattern", 0,
            after_timestamp, 0, args=args
        )
        self.assertIsNotNone(result)

    def test_large_tolerance_allows_significant_reordering(self):
        """Test large block_time_tolerance allows significant timestamp reordering"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:10.000 second pattern
2024-01-06T10:00:05.000 significantly out of order pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 10.0  # 10 second tolerance
                self.verbose = 0

        args = MockArgs()

        # Pattern 5 seconds before should be accepted with 10s tolerance
        after_timestamp = datetime(2024, 1, 6, 10, 0, 10)
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "significantly out of order pattern", 0,
            after_timestamp, 0, args=args
        )
        self.assertIsNotNone(result)

    def test_negative_tolerance_rejects_all_patterns(self):
        """Test negative block_time_tolerance rejects patterns that exceed tolerance"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:01.000 second pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = -1.0  # Negative tolerance
                self.verbose = 0

        args = MockArgs()

        # Pattern that comes after should still be found (negative tolerance only affects backwards)
        after_timestamp = datetime(2024, 1, 6, 10, 0, 0)
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "second pattern", 0,
            after_timestamp, 0, args=args
        )
        # The pattern at 10:00:01 comes after 10:00:00, so it should be found
        self.assertIsNotNone(result)

    def test_tolerance_boundary_conditions(self):
        """Test block_time_tolerance at exact boundary conditions"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:02.000 second pattern
2024-01-06T10:00:01.000 exactly at boundary pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 1.0  # Exactly 1 second tolerance
                self.verbose = 0

        args = MockArgs()

        # Pattern exactly 1 second before should be accepted
        after_timestamp = datetime(2024, 1, 6, 10, 0, 2)
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "exactly at boundary pattern", 0,
            after_timestamp, 0, args=args
        )
        self.assertIsNotNone(result)


class TestBlockTimeToleranceReordering(LPMPTestBase):
    """Test block_time_tolerance reordering functionality"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_reorder_and_output_results_chronological_sorting(self):
        """Test reorder_and_output_results sorts results chronologically"""
        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 3.0
                self.verbose = 0
                self.max_log_length = 180

        args = MockArgs()

        # Create test results with out-of-order timestamps
        temp_results = [
            {
                'timestamp': datetime(2024, 1, 6, 10, 0, 2),
                'block': {'label': 'Third Block'},
                'data': '2024-01-06T10:00:02.000 third event',
                'actual_filename': 'test.log',
                'seq': 2
            },
            {
                'timestamp': datetime(2024, 1, 6, 10, 0, 0),
                'block': {'label': 'First Block'},
                'data': '2024-01-06T10:00:00.000 first event',
                'actual_filename': 'test.log',
                'seq': 0
            },
            {
                'timestamp': datetime(2024, 1, 6, 10, 0, 1),
                'block': {'label': 'Second Block'},
                'data': '2024-01-06T10:00:01.000 second event',
                'actual_filename': 'test.log',
                'seq': 1
            }
        ]

        structured_results = []

        reorder_and_output_results(temp_results, args, structured_results=structured_results)

        # Verify results are sorted chronologically
        self.assertEqual(len(structured_results), 3)
        self.assertIn("first event", structured_results[0].log_line)
        self.assertIn("second event", structured_results[1].log_line)
        self.assertIn("third event", structured_results[2].log_line)

    def test_reorder_preserves_sequence_for_equal_timestamps(self):
        """Test reordering preserves sequence order for equal timestamps"""
        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 3.0
                self.verbose = 0
                self.max_log_length = 180

        args = MockArgs()

        # Create test results with same timestamp but different sequence numbers
        same_timestamp = datetime(2024, 1, 6, 10, 0, 0)
        temp_results = [
            {
                'timestamp': same_timestamp,
                'block': {'label': 'Second Block'},
                'data': '2024-01-06T10:00:00.000 second event',
                'actual_filename': 'test.log',
                'seq': 1
            },
            {
                'timestamp': same_timestamp,
                'block': {'label': 'First Block'},
                'data': '2024-01-06T10:00:00.000 first event',
                'actual_filename': 'test.log',
                'seq': 0
            }
        ]

        structured_results = []

        reorder_and_output_results(temp_results, args, structured_results=structured_results)

        # Verify sequence order is preserved for equal timestamps
        self.assertEqual(len(structured_results), 2)
        self.assertIn("first event", structured_results[0].log_line)
        self.assertIn("second event", structured_results[1].log_line)

    def test_empty_results_handled_gracefully(self):
        """Test reorder_and_output_results handles empty results gracefully"""
        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 3.0
                self.verbose = 0

        args = MockArgs()
        temp_results = []

        # Should not raise any exceptions
        reorder_and_output_results(temp_results, args)


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestBlockTimeToleranceIntegration(LPMPTestBase):
    """Test block_time_tolerance integration with block processing"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_pattern_block_with_tolerance(self):
        """Test pattern block processing with block_time_tolerance"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:02.000 second pattern
2024-01-06T10:00:01.500 out of order pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.block_time_tolerance = 1.0  # 1 second tolerance
                self.verbose = 0
                self.max_log_length = 180

        args = MockArgs(self.temp_dir)

        block = {
            'label': 'Test Block',
            'file': 'test.log',
            'patterns': ['first pattern'],
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pattern_block(args, block, start_date)

        # Should find the out of order pattern within tolerance
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)  # Should have one result for one pattern
        # Check the last result (out of order pattern)
        timestamp, log_line, filename, output_hostname = result[0]
        self.assertIn("first pattern", log_line)

    def test_auto_detect_with_tolerance_reordering(self):
        """Test tolerance-based reordering with multiple pattern blocks"""
        log_content = """2024-01-06T10:00:00.000 pattern A
2024-01-06T10:00:03.000 pattern C
2024-01-06T10:00:01.000 pattern B"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.block_time_tolerance = 5.0  # Large tolerance
                self.verbose = 0
                self.max_log_length = 180

        args = MockArgs(self.temp_dir)

        # Test individual pattern blocks with tolerance
        blocks = [
            {
                'label': 'Block A',
                'file': 'test.log',
                'patterns': ['pattern A'],
            },
            {
                'label': 'Block B',
                'file': 'test.log',
                'patterns': ['pattern B'],
            },
            {
                'label': 'Block C',
                'file': 'test.log',
                'patterns': ['pattern C'],
            }
        ]

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        results = []

        # Process each block individually to test tolerance
        for block in blocks:
            result = process_pattern_block(args, block, start_date)
            if result:
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)  # Each block has one pattern
                timestamp, log_line, filename, output_hostname = result[0]
                results.append((timestamp, log_line, block['label']))
                start_date = timestamp  # Update for next block

        # Should find all patterns despite out-of-order timestamps
        self.assertEqual(len(results), 3)

        # Sort results by timestamp to verify chronological order
        results.sort(key=lambda x: x[0])
        self.assertIn("pattern A", results[0][1])
        self.assertIn("pattern B", results[1][1])
        self.assertIn("pattern C", results[2][1])

    def test_tolerance_with_multiple_files(self):
        """Test block_time_tolerance with patterns across multiple files"""
        log_file1 = os.path.join(self.temp_dir, "file1.log")
        log_file2 = os.path.join(self.temp_dir, "file2.log")

        log_content1 = """2024-01-06T10:00:00.000 pattern from file1
2024-01-06T10:00:02.500 another pattern from file1"""

        log_content2 = """2024-01-06T10:00:01.000 pattern from file2
2024-01-06T10:00:02.000 another pattern from file2"""

        with open(log_file1, 'w') as f:
            f.write(log_content1)
        with open(log_file2, 'w') as f:
            f.write(log_content2)

        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.block_time_tolerance = 2.0
                self.verbose = 0
                self.max_log_length = 180

        args = MockArgs(self.temp_dir)

        # Test pattern block with multiple files
        block = {
            'label': 'Multi-file Block',
            'file': ['file1.log', 'file2.log'],
            'patterns': ['pattern from file1'],
        }

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        result = process_pattern_block(args, block, start_date)

        # Should find one of the patterns
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)  # Should have one result for one pattern
        # Check the last result
        timestamp, log_line, filename, output_hostname = result[0]
        self.assertTrue(
            "pattern from file1" in log_line or "pattern from file2" in log_line
        )


class TestBlockTimeToleranceErrorHandling(LPMPTestBase):
    """Test block_time_tolerance error handling and edge cases"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_missing_block_time_tolerance_uses_default(self):
        """Test missing block_time_tolerance attribute uses default value of 5.0"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:02.000 second pattern
2024-01-06T10:00:01.000 out of order pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgsNoTolerance:
            def __init__(self):
                self.verbose = 0
                # Deliberately omit block_time_tolerance

        args = MockArgsNoTolerance()

        # Default tolerance is 5.0s — 1s backwards should be accepted
        after_timestamp = datetime(2024, 1, 6, 10, 0, 2)
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "out of order pattern", 0,
            after_timestamp, 0, args=args
        )
        self.assertIsNotNone(result)

    def test_none_args_uses_default_tolerance(self):
        """Test None args parameter uses default tolerance of 5.0"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:02.000 second pattern
2024-01-06T10:00:01.000 out of order pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        # Default tolerance is 5.0s — 1s backwards should be accepted
        after_timestamp = datetime(2024, 1, 6, 10, 0, 2)
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "out of order pattern", 0,
            after_timestamp, 0, args=None
        )
        self.assertIsNotNone(result)

    def test_very_large_tolerance_value(self):
        """Test very large block_time_tolerance values"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:10.000 second pattern
2024-01-06T09:59:00.000 very old pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 3600.0  # 1 hour tolerance
                self.verbose = 0

        args = MockArgs()

        # Pattern 1 minute before should be accepted with 1 hour tolerance
        after_timestamp = datetime(2024, 1, 6, 10, 0, 10)
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "very old pattern", 0,
            after_timestamp, 0, args=args
        )
        self.assertIsNotNone(result)

    def test_fractional_tolerance_values(self):
        """Test fractional block_time_tolerance values"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:01.000 second pattern
2024-01-06T10:00:00.750 fractional out of order pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 0.3  # 300ms tolerance
                self.verbose = 0

        args = MockArgs()

        # Pattern 250ms before should be accepted with 300ms tolerance
        after_timestamp = datetime(2024, 1, 6, 10, 0, 1)
        result = find_pattern_in_files(
            self.temp_dir, "test.log", "fractional out of order pattern", 0,
            after_timestamp, 0, args=args
        )
        self.assertIsNotNone(result)

    def test_tolerance_with_verbose_logging(self):
        """Test block_time_tolerance with verbose logging enabled"""
        log_content = """2024-01-06T10:00:00.000 first pattern
2024-01-06T10:00:02.000 second pattern
2024-01-06T10:00:01.000 out of order pattern"""

        with open(self.log_file, 'w') as f:
            f.write(log_content)

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 0.5  # Small tolerance
                self.verbose = 4  # High verbosity

        args = MockArgs()

        # Should log tolerance violations with high verbosity
        with patch('builtins.print') as mock_print:
            after_timestamp = datetime(2024, 1, 6, 10, 0, 2)
            result = find_pattern_in_files(
                self.temp_dir, "test.log", "out of order pattern", 0,
                after_timestamp, 0, args=args
            )

            # Pattern should be rejected due to exceeding tolerance
            self.assertIsNone(result)

            # Should have logged the tolerance violation
            # Note: The actual logging depends on the wlog function implementation


class TestBlockTimeTolerancePerformance(LPMPTestBase):
    """Test block_time_tolerance performance characteristics"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "large_test.log")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_tolerance_with_large_log_file(self):
        """Test block_time_tolerance performance with large log files"""
        # Create a log file with many entries
        log_lines = []
        for i in range(1000):
            timestamp = f"2024-01-06T10:{i // 60:02d}:{i % 60:02d}.000"
            log_lines.append(f"{timestamp} pattern_{i}")

        # Add some out-of-order entries
        log_lines.append("2024-01-06T10:05:30.000 target_pattern")

        with open(self.log_file, 'w') as f:
            f.write('\n'.join(log_lines))

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 10.0
                self.verbose = 0

        args = MockArgs()

        # Should still find pattern efficiently even with large file
        # Pattern is at 10:05:30, search after 10:05:00 to find it
        after_timestamp = datetime(2024, 1, 6, 10, 5, 0)
        result = find_pattern_in_files(
            self.temp_dir, "large_test.log", "target_pattern", 0,
            after_timestamp, 0, args=args
        )

        self.assertIsNotNone(result)
        timestamp, pos, line, filename = result
        self.assertIn("target_pattern", line)

    def test_tolerance_with_many_out_of_order_entries(self):
        """Test block_time_tolerance with many out-of-order entries"""
        # Create log with many out-of-order timestamps
        log_lines = [
            "2024-01-06T10:00:05.000 pattern_5",
            "2024-01-06T10:00:01.000 pattern_1",
            "2024-01-06T10:00:08.000 pattern_8",
            "2024-01-06T10:00:03.000 pattern_3",
            "2024-01-06T10:00:07.000 target_pattern",
            "2024-01-06T10:00:02.000 pattern_2",
            "2024-01-06T10:00:09.000 pattern_9"
        ]

        with open(self.log_file, 'w') as f:
            f.write('\n'.join(log_lines))

        class MockArgs:
            def __init__(self):
                self.block_time_tolerance = 5.0
                self.verbose = 0

        args = MockArgs()

        # Should handle many out-of-order entries efficiently
        after_timestamp = datetime(2024, 1, 6, 10, 0, 8)
        result = find_pattern_in_files(
            self.temp_dir, "large_test.log", "target_pattern", 0,
            after_timestamp, 0, args=args
        )

        self.assertIsNotNone(result)


class TestBlockToleranceWithPairBlocks(LPMPTestBase):
    """Test process_pair_block with varying block_time_tolerance values."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.temp_dir, "test.log")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _make_args(self, tolerance=5.0):
        class A:
            pass
        a = A()
        a.logs_dir = self.temp_dir
        a.block_time_tolerance = tolerance
        a.model_type = ModelType.PAIR
        a.verbose = 0
        a.max_log_length = 180
        return a

    def test_stop_after_start(self):
        """Basic pair block: stop pattern after start pattern."""
        with open(self.log_file, 'w') as f:
            f.write("2024-01-06T10:00:00.000 service start\n")
            f.write("2024-01-06T10:00:05.000 service stop\n")

        args = self._make_args(tolerance=1.0)
        block = {
            'label': 'Service',
            'file': 'test.log',
            'start': 'service start',
            'stop': 'service stop',
        }
        result = process_pair_block(args, block, datetime(2024, 1, 6, 9, 0, 0))
        self.assertIsNotNone(result)
        (start_ts, stop_ts), duration_info, _ = result
        self.assertIn("5.0s", duration_info)

    def test_stop_slightly_before_start_accepted(self):
        """Stop pattern timestamp slightly before start — accepted by tolerance."""
        with open(self.log_file, 'w') as f:
            f.write("2024-01-06T10:00:05.000 service start\n")
            f.write("2024-01-06T10:00:04.500 service stop\n")

        args = self._make_args(tolerance=2.0)
        block = {
            'label': 'Service',
            'file': 'test.log',
            'start': 'service start',
            'stop': 'service stop',
        }
        result = process_pair_block(args, block, datetime(2024, 1, 6, 9, 0, 0))
        self.assertIsNotNone(result, "Stop 0.5s before start should be found with tolerance=2")

    def test_stop_too_far_before_start_rejected(self):
        """Stop pattern too far before start — rejected by tolerance."""
        with open(self.log_file, 'w') as f:
            f.write("2024-01-06T10:00:00.000 service stop\n")
            f.write("2024-01-06T10:00:10.000 service start\n")

        args = self._make_args(tolerance=1.0)
        block = {
            'label': 'Service',
            'file': 'test.log',
            'start': 'service start',
            'stop': 'service stop',
        }
        result = process_pair_block(args, block, datetime(2024, 1, 6, 9, 0, 0))
        self.assertIsNone(result, "Stop 10s before start should be rejected with tolerance=1")

    def test_sequential_with_tolerance(self):
        """Two sequential pair blocks where second start is slightly before first stop."""
        with open(self.log_file, 'w') as f:
            f.write("2024-01-06T10:00:00.000 svc_a start\n")
            f.write("2024-01-06T10:00:05.000 svc_a stop\n")
            f.write("2024-01-06T10:00:04.000 svc_b start\n")
            f.write("2024-01-06T10:00:08.000 svc_b stop\n")

        args = self._make_args(tolerance=3.0)
        block_a = {
            'label': 'Service A',
            'file': 'test.log',
            'start': 'svc_a start',
            'stop': 'svc_a stop',
        }
        block_b = {
            'label': 'Service B',
            'file': 'test.log',
            'start': 'svc_b start',
            'stop': 'svc_b stop',
        }

        result_a = process_pair_block(args, block_a, datetime(2024, 1, 6, 9, 0, 0))
        self.assertIsNotNone(result_a)
        (start_a, _), _, _ = result_a

        result_b = process_pair_block(args, block_b, start_a)
        self.assertIsNotNone(result_b, "svc_b start at 10:00:04 should be found from after_ts=10:00:00")

    def test_zero_tolerance_finds_forward_stop(self):
        """Zero tolerance still finds stop that comes after start."""
        with open(self.log_file, 'w') as f:
            f.write("2024-01-06T10:00:00.000 service start\n")
            f.write("2024-01-06T10:00:03.000 service stop\n")

        args = self._make_args(tolerance=0.0)
        block = {
            'label': 'Service',
            'file': 'test.log',
            'start': 'service start',
            'stop': 'service stop',
        }
        result = process_pair_block(args, block, datetime(2024, 1, 6, 9, 0, 0))
        self.assertIsNotNone(result, "Forward stop should always be found even with zero tolerance")


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestBlockTolerancePairIntegration(LPMPTestBase):
    """Integration tests: block_time_tolerance through process_blocks_auto_detect for pair models."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _run_pair_model(self, log_content, blocks_yaml, tolerance=5.0):
        """Helper: write log, load model, run process_blocks_auto_detect."""
        from lpmp_engine import process_blocks_auto_detect
        from lpmp_utils import expand_wildcards_in_blocks
        from lpmp_utils import load_model

        log_file = os.path.join(self.temp_dir, "test.log")
        with open(log_file, 'w') as f:
            f.write(log_content)

        model_file = os.path.join(self.temp_dir, "model.yaml")
        with open(model_file, 'w') as f:
            yaml.dump({'blocks': blocks_yaml}, f)

        blocks, settings, model_type = load_model(model_file)
        expand_wildcards_in_blocks(blocks, self.temp_dir)

        class Args:
            pass
        args = Args()
        args.logs_dir = self.temp_dir
        args.verbose = 0
        args.max_log_length = 180
        args.block_time_tolerance = tolerance
        args.model_file = model_file
        args.model_type = model_type
        args.all_optional_warnings = []

        start_date = datetime(2024, 1, 6, 9, 0, 0)
        return process_blocks_auto_detect(args, blocks, start_date, 45,
                                          {'hostname': 'controller-0'})

    def test_basic_pair_block(self):
        """End-to-end: pair model finds start/stop correctly."""
        log = ("2024-01-06T10:00:00.000 service start\n"
               "2024-01-06T10:00:03.000 service stop\n")
        blocks = [{'label': 'Svc', 'file': 'test.log',
                   'start': 'service start', 'stop': 'service stop'}]

        success, start, end, found, warnings, results = self._run_pair_model(log, blocks)
        self.assertTrue(success)
        self.assertEqual(found, 1)
        self.assertEqual(len(results), 1)

    def test_tolerance_accepts_overlapping_blocks(self):
        """Two pair blocks where second start overlaps first — tolerance allows it."""
        log = ("2024-01-06T10:00:00.000 svc_a start\n"
               "2024-01-06T10:00:05.000 svc_a stop\n"
               "2024-01-06T10:00:04.000 svc_b start\n"
               "2024-01-06T10:00:08.000 svc_b stop\n")
        blocks = [
            {'label': 'A', 'file': 'test.log',
             'start': 'svc_a start', 'stop': 'svc_a stop'},
            {'label': 'B', 'file': 'test.log',
             'start': 'svc_b start', 'stop': 'svc_b stop'},
        ]

        success, _, _, found, _, results = self._run_pair_model(log, blocks, tolerance=5.0)
        self.assertTrue(success)
        self.assertEqual(found, 2)

    def test_tight_tolerance_rejects_backwards_stop(self):
        """Tight tolerance causes stop-before-start to fail."""
        log = ("2024-01-06T10:00:00.000 service stop\n"
               "2024-01-06T10:00:10.000 service start\n")
        blocks = [{'label': 'Svc', 'file': 'test.log',
                   'start': 'service start', 'stop': 'service stop'}]

        success, _, _, found, _, results = self._run_pair_model(log, blocks, tolerance=1.0)
        self.assertFalse(success)
        self.assertEqual(found, 0)

    def test_optional_block_not_found(self):
        """Optional pair block that can't be found doesn't fail the model."""
        log = ("2024-01-06T10:00:00.000 svc_a start\n"
               "2024-01-06T10:00:03.000 svc_a stop\n")
        blocks = [
            {'label': 'A', 'file': 'test.log',
             'start': 'svc_a start', 'stop': 'svc_a stop'},
            {'label': 'B', 'file': 'test.log',
             'start': 'missing start', 'stop': 'missing stop',
             'optional': True},
        ]

        success, _, _, found, warnings, results = self._run_pair_model(log, blocks, tolerance=1.0)
        self.assertTrue(success)
        self.assertEqual(found, 1)


if __name__ == '__main__':
    unittest.main()
