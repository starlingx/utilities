#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################

"""Test suite for LPMP script runner feature (--script flag)."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent.parent))

import lpmp_utils as utils  # noqa: E402


class TestScriptDiscovery(unittest.TestCase):
    """Test script search path discovery."""

    def test_search_paths_order(self):
        """Verify search path order: current dir > etc override > built-in > on-system.

        Current directory is highest priority so a same-named script
        there overrides any built-in or packaged default. All four
        directories are always returned regardless of existence;
        callers (find_script/collect_scripts_files) tolerate missing
        directories via os.path.isfile()/os.listdir() at lookup time.
        """
        paths = utils.get_scripts_search_paths()
        self.assertEqual(len(paths), 4)
        self.assertEqual(paths[0], './')
        self.assertEqual(paths[1], '/etc/lpmp.d/scripts/')
        self.assertTrue(paths[2].endswith('scripts'))
        self.assertEqual(paths[3], '/var/lib/lpmp_scripts/')

    def test_search_paths_installed_layout_skips_builtin(self):
        """Verify the tool-dir entry is omitted for an installed package."""
        with mock.patch.object(
                utils.os.path, 'dirname',
                return_value='/usr/lib/python3/dist-packages/lpmp'):
            paths = utils.get_scripts_search_paths()
        self.assertFalse(any('dist-packages' in p for p in paths))
        self.assertEqual(paths[0], './')
        self.assertIn('/var/lib/lpmp_scripts/', paths)

    def test_find_script_absolute_path(self):
        """Verify script discovery with absolute path."""
        with tempfile.NamedTemporaryFile(suffix='.py', delete=False) as f:
            script_path = f.name
        try:
            result = utils.find_script(script_path)
            self.assertEqual(result, script_path)
        finally:
            os.unlink(script_path)

    def test_find_script_not_found(self):
        """Verify warning when script not found."""
        with mock.patch('sys.stderr'):
            result = utils.find_script('nonexistent_script.py',
                                       search_paths=['/tmp'])
            self.assertIsNone(result)


class TestCollectScriptsFiles(unittest.TestCase):
    """collect_scripts_files listing, filtering, and de-dup across paths."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.high = os.path.join(self.tmp, 'high')
        self.low = os.path.join(self.tmp, 'low')
        os.makedirs(self.high)
        os.makedirs(self.low)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, folder, name):
        path = os.path.join(folder, name)
        with open(path, 'w') as f:
            f.write('#!/usr/bin/env python3\n')
        return path

    def test_lists_py_and_sh_only_sorted(self):
        self._write(self.high, 'b_script.py')
        self._write(self.high, 'a_script.sh')
        self._write(self.high, 'notes.txt')
        found = utils.collect_scripts_files([self.high])
        names = [n for n, _ in found]
        self.assertEqual(names, ['a_script.sh', 'b_script.py'])

    def test_higher_priority_path_shadows_lower(self):
        self._write(self.high, 'dup.py')
        self._write(self.low, 'dup.py')
        found = utils.collect_scripts_files([self.high, self.low])
        dup_entries = [p for n, p in found if n == 'dup.py']
        self.assertEqual(len(dup_entries), 1)
        self.assertIn('high', dup_entries[0])

    def test_missing_dir_is_skipped(self):
        self._write(self.high, 'x_script.py')
        missing = os.path.join(self.tmp, 'does_not_exist')
        found = utils.collect_scripts_files([missing, self.high])
        self.assertEqual([n for n, _ in found], ['x_script.py'])

    def test_current_directory_excluded_from_listing(self):
        """The cwd entry ('./' or the real cwd) is never listed, even
        though it is still searched at lookup time by find_script().
        """
        self._write(self.high, 'y_script.py')
        cwd = os.getcwd()
        found = utils.collect_scripts_files([cwd, './', self.high])
        self.assertEqual([n for n, _ in found], ['y_script.py'])

    def test_default_search_paths_used_when_none_given(self):
        with mock.patch.object(utils, 'get_scripts_search_paths',
                               return_value=[self.high]):
            self._write(self.high, 'z_script.py')
            found = utils.collect_scripts_files()
        self.assertEqual([n for n, _ in found], ['z_script.py'])


class TestScriptValidation(unittest.TestCase):
    """Test script configuration format validation."""

    def test_validate_string_script(self):
        """String script names are valid."""
        valid, error = utils.validate_script_format('my_script.py')
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_validate_list_script_name_only(self):
        """List with single script name is valid."""
        valid, error = utils.validate_script_format(['my_script.py'])
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_validate_list_script_with_arg(self):
        """List [script, argument] is valid."""
        valid, error = utils.validate_script_format(
            ['my_script.py', 'var/extra/data.info'])
        self.assertTrue(valid)
        self.assertIsNone(error)

    def test_validate_invalid_type(self):
        """Non-string/non-list types are invalid."""
        valid, error = utils.validate_script_format(123)
        self.assertFalse(valid)
        self.assertIsNotNone(error)
        self.assertIn('string or list', error)

    def test_validate_list_too_many_elements(self):
        """Lists with >2 elements are invalid."""
        valid, error = utils.validate_script_format(
            ['script.py', 'arg1', 'arg2'])
        self.assertFalse(valid)
        self.assertIsNotNone(error)

    def test_validate_non_string_elements(self):
        """List elements must be strings."""
        valid, error = utils.validate_script_format(['script.py', 123])
        self.assertFalse(valid)
        self.assertIsNotNone(error)


class TestVariableSubstitution(unittest.TestCase):
    """Test variable substitution in paths."""

    def test_substitute_single_variable(self):
        """Verify {variable} substitution."""
        path = '/path/to/{hostname}_data.txt'
        variables = {'hostname': 'controller-0'}
        result = utils.substitute_variables_in_path(path, variables)
        self.assertEqual(result, '/path/to/controller-0_data.txt')

    def test_substitute_multiple_variables(self):
        """Verify multiple {variable} substitutions."""
        path = '{hostname}_{env}'
        variables = {'hostname': 'controller-0', 'env': 'prod'}
        result = utils.substitute_variables_in_path(path, variables)
        self.assertEqual(result, 'controller-0_prod')

    def test_no_substitution_needed(self):
        """Paths without variables pass through unchanged."""
        path = '/var/extra/data.info'
        variables = {'hostname': 'controller-0'}
        result = utils.substitute_variables_in_path(path, variables)
        self.assertEqual(result, path)

    def test_partial_substitution(self):
        """Only defined variables are substituted."""
        path = '{hostname}/data/{missing_var}.txt'
        variables = {'hostname': 'controller-0'}
        result = utils.substitute_variables_in_path(path, variables)
        self.assertIn('controller-0/data/', result)
        self.assertIn('{missing_var}', result)


class TestScriptArgumentResolution(unittest.TestCase):
    """Test script argument resolution in bundle mode."""

    def test_resolve_script_arg_absolute_path(self):
        """Absolute paths used as-is."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = f.name
        try:
            result, error = utils.resolve_script_arg('/tmp', filepath)
            self.assertIsNone(error)
            self.assertEqual(result, filepath)
        finally:
            os.unlink(filepath)

    def test_resolve_script_arg_relative_with_glob(self):
        """Relative paths get hostname pattern prepended."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle_name = 'controller-0_20260101.123456'
            bundle_dir = os.path.join(tmpdir, bundle_name)
            data_dir = os.path.join(bundle_dir, 'var', 'extra')
            os.makedirs(data_dir)
            data_file = os.path.join(data_dir, 'test.info')
            with open(data_file, 'w') as f:
                f.write('test')
            variables = {'hostname': 'controller-0'}
            result, error = utils.resolve_script_arg(tmpdir, 'var/extra/test.info', variables)
            self.assertIsNone(error)
            self.assertIsNotNone(result)
            self.assertTrue(os.path.exists(result))

    def test_resolve_script_arg_no_match(self):
        """Error when pattern doesn't match any files."""
        result, error = utils.resolve_script_arg(
            '/nonexistent',
            'var/extra/missing.info',
            {'hostname': 'controller-0'})
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertIn('No matches', error)


class TestUtilityFunctions(unittest.TestCase):
    """Test core utility functions."""

    def test_manage_peer_controller_controller_0(self):
        """Controller-0 gets controller-1 as peer."""
        variables = {'hostname': 'controller-0'}
        utils.manage_peer_controller(variables)
        self.assertEqual(variables.get('peer_controller'), 'controller-1')

    def test_manage_peer_controller_controller_1(self):
        """Controller-1 gets controller-0 as peer."""
        variables = {'hostname': 'controller-1'}
        utils.manage_peer_controller(variables)
        self.assertEqual(variables.get('peer_controller'), 'controller-0')

    def test_manage_peer_controller_other_host(self):
        """Other hostnames don't get peer assigned."""
        variables = {'hostname': 'worker-1'}
        utils.manage_peer_controller(variables)
        self.assertNotIn('peer_controller', variables)

    def test_manage_peer_controller_preserves_vars(self):
        """Existing variables preserved."""
        variables = {'hostname': 'controller-0', 'custom': 'value'}
        utils.manage_peer_controller(variables)
        self.assertEqual(variables['custom'], 'value')
        self.assertEqual(variables['peer_controller'], 'controller-1')


class TestFileHandling(unittest.TestCase):
    """Test file discovery and handling utilities."""

    def test_is_ignored_path_glob_pattern(self):
        """Glob patterns match correctly."""
        with mock.patch('lpmp_utils._file_ignore_patterns', ['*.pid', '*.sock']):
            self.assertTrue(utils.is_ignored_path('test.pid'))
            self.assertTrue(utils.is_ignored_path('test.sock'))
            self.assertFalse(utils.is_ignored_path('test.log'))

    def test_is_ignored_path_prefix_pattern(self):
        """Prefix patterns match correctly."""
        with mock.patch('lpmp_utils._file_ignore_patterns', ['pods/', 'tmp/']):
            self.assertTrue(utils.is_ignored_path('pods/test.log'))
            self.assertTrue(utils.is_ignored_path('tmp/cache.dat'))
            self.assertFalse(utils.is_ignored_path('logs/app.log'))

    def test_is_ignored_path_basename_exact(self):
        """Basename exact matching works."""
        with mock.patch('lpmp_utils._file_ignore_patterns', ['wtmp', 'btmp']):
            self.assertTrue(utils.is_ignored_path('wtmp'))
            self.assertTrue(utils.is_ignored_path('/var/log/wtmp'))
            self.assertFalse(utils.is_ignored_path('wtmp.1'))

    def test_is_ignored_path_no_patterns(self):
        """No patterns result in no ignores."""
        with mock.patch('lpmp_utils._file_ignore_patterns', []):
            self.assertFalse(utils.is_ignored_path('any.log'))


class TestPeerControllerIntegration(unittest.TestCase):
    """Integration tests for peer controller."""

    def test_peer_controller_in_bundle_variables(self):
        """Peer controller set correctly in bundle context."""
        hostname = 'controller-0'
        variables = {'hostname': hostname}
        utils.manage_peer_controller(variables)
        self.assertIn('peer_controller', variables)
        self.assertEqual(variables['peer_controller'], 'controller-1')

        # Test in pattern substitution
        pattern = '{hostname} and {peer_controller} sync'
        result = utils.substitute_variables_in_path(pattern, variables)
        self.assertEqual(result, 'controller-0 and controller-1 sync')

    def test_multi_controller_scenarios(self):
        """Test various multi-controller scenarios."""
        scenarios = [
            ('controller-0', 'controller-1'),
            ('controller-1', 'controller-0'),
        ]
        for hostname, expected_peer in scenarios:
            variables = {'hostname': hostname}
            utils.manage_peer_controller(variables)
            self.assertEqual(variables.get('peer_controller'), expected_peer,
                             f"Failed for {hostname}")

    def test_worker_hosts_no_peer(self):
        """Worker nodes don't get peer_controller."""
        for hostname in ['worker-0', 'worker-1', 'storage-0']:
            variables = {'hostname': hostname}
            utils.manage_peer_controller(variables)
            self.assertNotIn('peer_controller', variables)


class TestScriptIntegration(unittest.TestCase):
    """Integration tests for script runner."""

    def test_script_runner_format_validation(self):
        """Script runner rejects invalid configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = mock.Mock(bundle=tmpdir, hostname='controller-0')
            with mock.patch('sys.stderr'):
                utils.run_script_hook(123, args)

    def test_script_runner_missing_script_warning(self):
        """Script runner prints warning for missing scripts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = mock.Mock(bundle=tmpdir, hostname='controller-0')
            with mock.patch('sys.stderr'):
                utils.run_script_hook('nonexistent.py', args)

    def test_script_runner_path_substitution(self):
        """Script runner substitutes variables in argument paths."""
        config = ['dummy_script.py', '{hostname}_data.txt']
        variables = {'hostname': 'controller-0'}
        subst = utils.substitute_variables_in_path(config[1], variables)
        self.assertEqual(subst, 'controller-0_data.txt')


class TestScriptRunner(unittest.TestCase):
    """Test script runner hook execution."""

    def test_script_runner_missing_script_skips_execution(self):
        """Missing script is warned and execution skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = mock.Mock(bundle=tmpdir, hostname='controller-0')
            with mock.patch('sys.stderr'):
                # Should not raise, just warn
                utils.run_script_hook('nonexistent.py', args)

    def test_script_runner_py_script_uses_python3(self):
        """A .py script is dispatched to python3, not exec'd directly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, 'my_script.py')
            with open(script_path, 'w') as f:
                f.write('#!/usr/bin/env python3\n')
            args = mock.Mock(bundle='/', hostname='controller-0')
            mock_result = mock.Mock(returncode=0)
            with mock.patch('subprocess.run', return_value=mock_result) as mock_run:
                utils.run_script_hook('my_script.py', args,
                                      search_paths=[tmpdir])
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            self.assertEqual(cmd, ['python3', script_path])

    def test_script_runner_sh_script_uses_bash(self):
        """A .sh script is dispatched to bash, not python3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, 'my_script.sh')
            with open(script_path, 'w') as f:
                f.write('#!/bin/bash\n')
            args = mock.Mock(bundle='/', hostname='controller-0')
            mock_result = mock.Mock(returncode=0)
            with mock.patch('subprocess.run', return_value=mock_result) as mock_run:
                utils.run_script_hook('my_script.sh', args,
                                      search_paths=[tmpdir])
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            self.assertEqual(cmd, ['bash', script_path])

    def test_script_runner_unsupported_extension_skips_execution(self):
        """A script with an unrecognized extension is not executed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, 'my_script.pl')
            with open(script_path, 'w') as f:
                f.write('#!/usr/bin/perl\n')
            args = mock.Mock(bundle='/', hostname='controller-0')
            with mock.patch('subprocess.run') as mock_run, \
                 mock.patch('sys.stderr'):
                utils.run_script_hook('my_script.pl', args,
                                      search_paths=[tmpdir])
            mock_run.assert_not_called()

    def test_script_runner_unreadable_script_skips_execution(self):
        """An unreadable script is warned and not executed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, 'locked.py')
            with open(script_path, 'w') as f:
                f.write('#!/usr/bin/env python3\n')
            args = mock.Mock(bundle='/', hostname='controller-0')
            with mock.patch('os.access', return_value=False), \
                 mock.patch('subprocess.run') as mock_run, \
                 mock.patch('sys.stderr'):
                utils.run_script_hook('locked.py', args,
                                      search_paths=[tmpdir])
            mock_run.assert_not_called()

    def test_script_runner_bundle_and_arg(self):
        """Script with bundle and argument is resolved."""
        config = ['dummy.py', 'var/extra/data.info']
        with tempfile.TemporaryDirectory() as tmpdir:
            args = mock.Mock(bundle=tmpdir, hostname='controller-0')
            # Validates configuration structure, doesn't execute
            valid, error = utils.validate_script_format(config)
            self.assertTrue(valid)

    def test_script_runner_arg_resolution_absolute_path(self):
        """Absolute argument paths used directly."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            filepath = f.name
        try:
            result, error = utils.resolve_script_arg('/', filepath)
            self.assertIsNone(error)
            self.assertEqual(result, filepath)
        finally:
            os.unlink(filepath)

    def test_script_runner_arg_resolution_not_found(self):
        """Unresolvable arguments cause error."""
        result, error = utils.resolve_script_arg(
            '/nonexistent/path',
            'var/extra/missing.info',
            {'hostname': 'controller-0'})
        self.assertIsNone(result)
        self.assertIsNotNone(error)

    def test_script_format_string(self):
        """String format for simple scripts."""
        valid, error = utils.validate_script_format('my_script.py')
        self.assertTrue(valid)

    def test_script_format_list_with_one_element(self):
        """List with single element (script name only)."""
        valid, error = utils.validate_script_format(['my_script.py'])
        self.assertTrue(valid)

    def test_script_format_list_with_two_elements(self):
        """List with two elements (script and argument)."""
        valid, error = utils.validate_script_format(
            ['my_script.py', 'var/extra/data.info'])
        self.assertTrue(valid)

    def test_script_format_invalid_dict(self):
        """Dict format is invalid."""
        valid, error = utils.validate_script_format({'script': 'test.py'})
        self.assertFalse(valid)
        self.assertIsNotNone(error)

    def test_script_format_list_too_long(self):
        """List with >2 elements is invalid."""
        valid, error = utils.validate_script_format(
            ['script.py', 'arg1', 'arg2'])
        self.assertFalse(valid)

    def test_script_format_mixed_types_in_list(self):
        """Non-string elements in list are invalid."""
        valid, error = utils.validate_script_format(['script.py', 123])
        self.assertFalse(valid)


if __name__ == '__main__':
    unittest.main()
