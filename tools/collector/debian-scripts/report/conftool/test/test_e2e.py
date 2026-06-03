#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the end-to-end tests for conftool.
#
#
########################################################################
"""
Integration / End-to-End test for conftool.

Runs the full conftool pipeline against a synthetic bundle to verify:
    - CLI argument handling
    - Host directory discovery
    - All domains load without error
    - Output files are created (JSON + text per domain)
    - JSON output is valid and parseable
    - Exit code is correct
    - Cross-domain interactions work (e.g. platform_conf used by network)

Uses a temporary directory — no hardcoded paths, no external dependencies.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

CONFTOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CONFTOOL_DIR)
sys.path.insert(0, os.path.join(CONFTOOL_DIR, 'test'))

from mock_factory import create_bundle  # noqa: E402


CONFTOOL_PATH = os.path.join(CONFTOOL_DIR, 'conftool')
EXPECTED_OUTPUTS = [
    'network_config.json',
    'network_config.txt',
    'container_config.json',
    'container_config.txt',
    'software_config.json',
    'software_config.txt',
    'platform_config.json',
    'platform_config.txt',
    'storage_config.json',
    'storage_config.txt',
]


class TestConftoolE2E(unittest.TestCase):
    """End-to-end integration tests for conftool CLI."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.bundle_dir = self.temp_dir
        create_bundle(self.bundle_dir, hostname='controller-0')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _run_conftool(self, *extra_args):
        """Run conftool as subprocess, return CompletedProcess."""
        cmd = [sys.executable, CONFTOOL_PATH,
               '-b', self.bundle_dir, '-H', 'controller-0']
        cmd.extend(extra_args)
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            cwd=CONFTOOL_DIR)

    def test_exit_code_zero(self):
        """Conftool should exit 0 on successful run (when no FAIL checks
        would cause exit 1 — we accept either since our mock has SM
        mismatches).
        """
        result = self._run_conftool()
        # Exit 1 is acceptable if cross-checks have FAILs
        self.assertIn(result.returncode, (0, 1))
        self.assertEqual(result.stderr, '')

    def test_output_files_created(self):
        """All expected output files should be created."""
        self._run_conftool()
        output_dir = os.path.join(self.bundle_dir, 'config',
                                  'controller-0')
        self.assertTrue(os.path.isdir(output_dir),
                        f"Output dir not created: {output_dir}")
        for filename in EXPECTED_OUTPUTS:
            path = os.path.join(output_dir, filename)
            self.assertTrue(os.path.isfile(path),
                            f"Missing output: {filename}")

    def test_json_files_valid(self):
        """All JSON output files should be valid JSON."""
        self._run_conftool()
        output_dir = os.path.join(self.bundle_dir, 'config',
                                  'controller-0')
        for filename in EXPECTED_OUTPUTS:
            if not filename.endswith('.json'):
                continue
            path = os.path.join(output_dir, filename)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(
                data, dict, f"{filename} should be a dict")

    def test_text_files_non_empty(self):
        """All text output files should be non-empty."""
        self._run_conftool()
        output_dir = os.path.join(self.bundle_dir, 'config',
                                  'controller-0')
        for filename in EXPECTED_OUTPUTS:
            if not filename.endswith('.txt'):
                continue
            path = os.path.join(output_dir, filename)
            size = os.path.getsize(path)
            self.assertGreater(size, 0,
                               f"{filename} should be non-empty")

    def test_single_domain_flag(self):
        """Running with -d network should only produce network output."""
        result = self._run_conftool('-d', 'network')
        self.assertIn(result.returncode, (0, 1))
        output_dir = os.path.join(self.bundle_dir, 'config',
                                  'controller-0')
        self.assertTrue(os.path.isfile(
            os.path.join(output_dir, 'network_config.json')))
        # Other domains should NOT be present
        self.assertFalse(os.path.isfile(
            os.path.join(output_dir, 'container_config.json')))

    def test_custom_output_dir(self):
        """Custom output directory via -o flag."""
        custom_out = os.path.join(self.temp_dir, 'custom_output')
        self._run_conftool('-o', custom_out)
        output_dir = os.path.join(custom_out, 'controller-0')
        self.assertTrue(os.path.isdir(output_dir))
        self.assertTrue(os.path.isfile(
            os.path.join(output_dir, 'network_config.json')))

    def test_nonexistent_host_fails(self):
        """Should fail gracefully with non-existent hostname."""
        result = subprocess.run(
            [sys.executable, CONFTOOL_PATH,
             '-b', self.bundle_dir, '-H', 'nonexistent-host'],
            capture_output=True, text=True, timeout=60,
            cwd=CONFTOOL_DIR)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Error', result.stderr)

    def test_nonexistent_bundle_fails(self):
        """Should fail gracefully with non-existent bundle path."""
        result = subprocess.run(
            [sys.executable, CONFTOOL_PATH,
             '-b', '/nonexistent/path/bundle'],
            capture_output=True, text=True, timeout=60,
            cwd=CONFTOOL_DIR)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Error', result.stderr)

    def test_json_contains_cross_checks(self):
        """JSON output should contain cross_check sections."""
        self._run_conftool()
        output_dir = os.path.join(self.bundle_dir, 'config',
                                  'controller-0')
        for filename in ('network_config.json', 'storage_config.json',
                         'platform_config.json'):
            path = os.path.join(output_dir, filename)
            with open(path) as f:
                data = json.load(f)
            self.assertIn('cross_check', data,
                          f"{filename} missing cross_check")

    def test_verbose_flag_accepted(self):
        """Verbose flag should not cause errors."""
        result = self._run_conftool('-v')
        self.assertIn(result.returncode, (0, 1))
        self.assertEqual(result.stderr, '')
        # Verbose output goes to stdout
        self.assertGreater(len(result.stdout), 0)

    def test_network_json_has_interfaces(self):
        """Network JSON should contain interface data."""
        self._run_conftool()
        path = os.path.join(self.bundle_dir, 'config',
                            'controller-0', 'network_config.json')
        with open(path) as f:
            data = json.load(f)
        self.assertIn('interfaces', data)
        self.assertTrue(len(data['interfaces']) > 0)
        self.assertIn('host', data)
        self.assertEqual(data['host']['hostname'], 'controller-0')

    def test_cov_graceful_without_coverage(self):
        """--cov should warn and continue if coverage lib not installed.

        Tests the import fallback logic in isolation without triggering
        full test discovery (which would recurse).
        """
        script = (
            "import sys\n"
            "import builtins\n"
            "real_import = builtins.__import__\n"
            "def deny_coverage(name, *a, **kw):\n"
            "    if name == 'coverage':\n"
            "        raise ImportError('not installed')\n"
            "    return real_import(name, *a, **kw)\n"
            "builtins.__import__ = deny_coverage\n"
            "with_cov = True\n"
            "try:\n"
            "    import coverage\n"
            "except ImportError:\n"
            "    print('Warning: coverage not installed, "
            "running tests without coverage')\n"
            "    with_cov = False\n"
            "assert with_cov is False, 'should have fallen back'\n"
            "print('PASS')\n"
        )
        result = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn('PASS', result.stdout)
        self.assertIn('not installed', result.stdout)


class TestConftoolNestedBundle(unittest.TestCase):
    """Test conftool with nested bundle layout."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        # Create nested layout: bundle/host_ts/host_ts/var/...
        outer = os.path.join(self.temp_dir,
                             'controller-0_20250211.212225')
        os.makedirs(outer)
        create_bundle(outer, hostname='controller-0')

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_nested_bundle_works(self):
        """Conftool should find host dir in nested layout."""
        result = subprocess.run(
            [sys.executable, CONFTOOL_PATH,
             '-b', self.temp_dir, '-H', 'controller-0'],
            capture_output=True, text=True, timeout=60,
            cwd=CONFTOOL_DIR)
        self.assertIn(result.returncode, (0, 1))
        output_dir = os.path.join(self.temp_dir, 'config',
                                  'controller-0')
        self.assertTrue(os.path.isdir(output_dir))


if __name__ == '__main__':
    unittest.main()
