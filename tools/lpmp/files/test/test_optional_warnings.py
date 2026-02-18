#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Test script to verify optional pattern block warnings are included in summary.timing
"""

from datetime import datetime
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

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lpmp_engine import process_blocks_auto_detect  # noqa: E402
from lpmp_output import write_pattern_summary       # noqa: E402
from lpmp_utils import expand_wildcards_in_blocks   # noqa: E402
from lpmp_utils import load_model                   # noqa: E402
from test_base import LPMPTestBase                  # noqa: E402


@unittest.skipUnless(YAML_AVAILABLE, "Enable with: pip3 install --user pyyaml")
class TestOptionalWarningsInSummary(LPMPTestBase):
    """Test that optional pattern block warnings appear in summary.timing"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_optional_warnings_in_summary(self):
        """Test that optional pattern block warnings appear in summary.timing"""
        # Create test log file
        log_file = os.path.join(self.temp_dir, "test.log")
        with open(log_file, 'w') as f:
            f.write("2024-01-06T10:00:00.000 found pattern\n")

        # Create test model with optional pattern block
        model_file = os.path.join(self.temp_dir, "model.yaml")
        model_data = {
            'blocks': [
                {
                    'label': 'Found Block',
                    'file': 'test.log',
                    'patterns': ['found pattern']
                },
                {
                    'label': 'SM Service Shutdown',
                    'file': 'test.log',
                    'patterns': ['missing pattern'],
                    'optional': True
                },
                {
                    'label': 'Host Manufacturer',
                    'file': 'test.log',
                    'patterns': ['another missing pattern'],
                    'optional': True
                }
            ]
        }
        with open(model_file, 'w') as f:
            yaml.dump(model_data, f)

        # Create output directory
        output_dir = os.path.join(self.temp_dir, "output")
        os.makedirs(output_dir)

        # Create mock args
        class MockArgs:
            def __init__(self, temp_dir):
                self.logs_dir = temp_dir
                self.verbose = 0
                self.max_log_length = 180
                self.block_time_tolerance = 1.0
                self.model_file = model_file
                self.all_optional_warnings = []

        args = MockArgs(self.temp_dir)

        # Load model and process blocks
        blocks, settings, _ = load_model(model_file)
        expand_wildcards_in_blocks(blocks, self.temp_dir)

        start_date = datetime(2024, 1, 6, 9, 0, 0)

        # Process blocks
        success, start_time, end_time, patterns_found, optional_warnings, _ = process_blocks_auto_detect(
            args, blocks, start_date, 45, {'hostname': 'controller-0'}
        )

        # Collect warnings
        args.all_optional_warnings = optional_warnings or []

        # Create profile.timing file that write_pattern_summary expects
        profile_file = os.path.join(output_dir, "profile.timing")
        with open(profile_file, 'w') as f:
            f.write("✅ Pass 1       00:00:01.000    found 1 patterns\n")
            f.write(
                "??:??:??.???	controller-0	SM Service Shutdown      	test.log  	"
                "⚠️ Warn: Optional block 'SM Service Shutdown': pattern(s) not found\n"
            )
            f.write(
                "??:??:??.???	controller-0	Host Manufacturer        	test.log  	"
                "⚠️ Warn: Optional block 'Host Manufacturer': pattern(s) not found\n"
            )

        # Write summary
        summary_file = os.path.join(output_dir, "summary.timing")
        write_pattern_summary(summary_file, [], [], args.all_optional_warnings)
        self.assertTrue(os.path.exists(summary_file))

        with open(summary_file, 'r') as f:
            content = f.read()

        # Check for warnings
        self.assertIn("SM Service Shutdown", content)
        self.assertIn("Host Manufacturer", content)


if __name__ == '__main__':
    unittest.main()
