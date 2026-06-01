#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""
Base test class for LPMP tests.

Note: lpmptool import uses permanent symlink lpmptool.py -> lpmptool
in the files/ directory (Git-tracked).
"""

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

# Don't produce a __pycache__ dir
sys.dont_write_bytecode = True


class LPMPTestBase(unittest.TestCase):
    """Base test class for LPMP tests."""

    def run_lpmptool(self, model_file, logs_dir, lab_name, output_dir, loops=1,  # noqa: E501
                     hostname='controller-0', real_execution=False):
        """Run lpmptool with given parameters and return result.

        Args:
            real_execution: If True, run actual lpmptool subprocess for integration tests.
                           If False, use mocking for unit tests.
        """
        if real_execution:
            return self._run_lpmptool_subprocess(model_file, logs_dir, lab_name, output_dir, loops, hostname)
        else:
            return self._run_lpmptool_mocked(model_file, logs_dir, lab_name, output_dir, loops, hostname)

    def _run_lpmptool_subprocess(self, model_file, logs_dir, lab_name, output_dir, loops, hostname):
        """Run lpmptool as subprocess for integration tests that need real output files."""
        # Get path to lpmptool script
        lpmptool_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'lpmptool')

        # Build command line arguments
        cmd = [
            'python3', lpmptool_path,
            '--model-file', model_file,
            '--logs-dir', logs_dir,
            '--lab', lab_name,
            '--output', output_dir,
            '--loops', str(loops),
            '--hostname', hostname,
            '--progress', 'none'  # Avoid progress indicators in tests
        ]

        # Run the subprocess
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout for tests
            )
            return result
        except subprocess.TimeoutExpired:
            # Create a mock result for timeout
            class MockResult:
                def __init__(self):
                    self.returncode = 1
                    self.stderr = 'Test timeout after 30 seconds'
                    self.stdout = ''
            return MockResult()
        except Exception as e:
            # Create a mock result for other exceptions
            class MockResult:
                def __init__(self, error):
                    self.returncode = 1
                    self.stderr = str(error)
                    self.stdout = ''
            return MockResult(e)

    def _run_lpmptool_mocked(self, model_file, logs_dir, lab_name, output_dir, loops, hostname):
        """Run lpmptool with mocking for unit tests that don't need real output files."""
        # Import lpmptool here to avoid circular imports
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        import lpmptool

        # Create a simple args object instead of MagicMock to avoid comparison issues
        class MockArgs:
            def __init__(self):
                self.help_model = False
                self.list_models = False
                self.stats = False
                self.hosts = False
                self.include = None
                self.exclude = None
                self.variables = None
                self.bundle_name = '/'
                self.bundle = '/'
                self.logs_dir = logs_dir
                self.model_file = model_file
                self.start_date = None
                self.stop_date = None
                self.verbose = 0
                self.loops = loops
                self.output = output_dir
                self.lab = lab_name
                self.lab_name = lab_name
                self.hostname = hostname
                self.max_time_delta = 45
                self.block_time_tolerance = 5.0
                self.max_log_length = 180
                self.file_position_tracking = False
                self.progress = 'none'
                self.version = False
                self.help = False
                self.quiet = False
                self.debug = False

        mock_args = MockArgs()

        # Mock all the functions that could trigger interactive behavior
        with patch('argparse.ArgumentParser.parse_args', return_value=mock_args), \
             patch('lpmptool.interactive_host_selection') as mock_interactive, \
             patch('lpmptool.get_models_search_paths', return_value=[os.path.dirname(model_file)]), \
             patch('lpmptool.find_model_file', return_value=model_file), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.isdir', return_value=True), \
             patch('builtins.print'), \
             patch('sys.stdout'), \
             patch('sys.stderr'):

            try:
                lpmptool.main()

                # Create a mock successful result
                class MockResult:
                    def __init__(self):
                        self.returncode = 0
                        self.stderr = ''
                        self.stdout = ''
                return MockResult()
            except SystemExit as e:
                # Create a mock result with the exit code
                class MockResult:
                    def __init__(self, returncode):
                        self.returncode = returncode
                        self.stderr = f'SystemExit: {returncode}'
                        self.stdout = ''
                return MockResult(e.code if e.code is not None else 0)
            except Exception as e:
                # Create a mock result for other exceptions
                class MockResult:
                    def __init__(self, error):
                        self.returncode = 1
                        self.stderr = str(error)
                        self.stdout = ''
                return MockResult(e)
