################################################################################
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
import collections

import fixtures
from k8s_coredump.tests.base import BaseTestCase
from k8s_coredump.tests.base import MockedOpen
from k8s_coredump.tests.base import MockedStdin
from k8s_coredump.tests.test_data import ANNOTATIONS_EXAMPLES
from k8s_coredump.tests.test_data import DISK_USAGE
import mock
from testtools import matchers

# Mocking logging.basicConfig to avoid "path not found" error on constants.py that is imported by config_functions.
with mock.patch('logging.basicConfig') as mock_method:
    from k8s_coredump import config_functions


class TestConfigFunctions(BaseTestCase):

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestConfigFunctions, self).setUp()

        self.space_info = DISK_USAGE

        # Mocking disk usage object to be as close to shutil.disk_usage as possible,
        # using the same method to make the named tuple "usage" that shutil.disk_usage returns.
        def mocked_disk_usage(path):
            test_usage = collections.namedtuple('usage', 'total used free')
            test_usage.total.__doc__ = 'Total space in bytes'
            test_usage.used.__doc__ = 'Used space in bytes'
            test_usage.free.__doc__ = 'Free space in bytes'
            return test_usage(total=self.space_info['total_space'],
                used=self.space_info['used_space'],
                free=self.space_info['free_space'])

        self.useFixture(
            fixtures.MonkeyPatch('k8s_coredump.config_functions.shutil.disk_usage', mocked_disk_usage))

        self.annotations_examples = ANNOTATIONS_EXAMPLES

    def test_parse_core_pattern(self):
        """Test for config_functions.parse_core_pattern

        Using the annotations_examples from test_data, the method config_functions.parse_core_pattern
        is tested to verify if the parsing of core_pattern is working as intended.
        """
        for annotations in self.annotations_examples:
            parsed_core_name = config_functions.parse_core_pattern(annotations["starlingx.io/core_pattern"],
                **self.input_kwargs)
            self.assertEqual(parsed_core_name, annotations["expected_core_pattern"])

    def test_parse_size_config(self):
        """Test for config_functions.parse_size_config

        Using the annotations_examples from test_data, the method config_functions.parse_size_config
        is tested to verify if the parsing of the size config is working as intended.
        """
        for annotations in self.annotations_examples:
            if "starlingx.io/core_max_size" in annotations:
                parsed_size_config = config_functions.parse_size_config(annotations["starlingx.io/core_max_size"])
                self.assertEqual(parsed_size_config, annotations["expected_core_max_size"])

    def test_get_annotations_config(self):
        """Test for config_functions.get_annotations_config

        Using the annotations_examples from test_data, the method config_functions.get_annotations_config
        is tested to verify if the parsing of the annotations is working as intended.
        """
        for annotations in self.annotations_examples:
            # Setup data as is expected in the method get_annotations_config
            raw_annotations = {
                'metadata': {
                    'annotations': annotations
                }
            }
            parsed_annotations = config_functions.get_annotations_config(raw_annotations)

            # Test if parsed annotations has all the keys that it should have.
            self.assertThat(parsed_annotations,
                matchers.KeysEqual('core_pattern', 'file_size_config',
                    'file_compression_config', 'max_use_config', 'keep_free_config'))

            # Test each value
            self.assertEqual(parsed_annotations['core_pattern'],
                annotations.get("starlingx.io/core_pattern"))
            self.assertEqual(parsed_annotations['file_size_config'],
                annotations.get("starlingx.io/core_max_size"))
            self.assertEqual(parsed_annotations['file_compression_config'],
                annotations.get("starlingx.io/core_compression"))
            self.assertEqual(parsed_annotations['max_use_config'],
                annotations.get("starlingx.io/core_max_used"))
            self.assertEqual(parsed_annotations['keep_free_config'],
                annotations.get("starlingx.io/core_min_free"))

    def test_check_available_space(self):
        """Test for config_functions.check_available_space

        Using a mocked disk space, the method config_functions.check_available_space
        is tested to verify if the method is working as intended, returning the
        disk space information.
        """
        avail_space = config_functions.check_available_space('/any/path')
        # Check if returned available space is the same as the mocked in the setup.
        self.assertEqual(avail_space, self.space_info)

    def test_convert_from_bytes(self):
        """Test for config_functions.convert_from_bytes

        Using some test values, the method config_functions.convert_from_bytes
        is tested to verify if the convertion of bytes to other size types
        is working as intended.
        """
        converted_gigabytes = config_functions.convert_from_bytes(536870912000, 'g')
        self.assertEqual(converted_gigabytes, 500)
        converted_kilobytes = config_functions.convert_from_bytes(536870912000, 'k')
        self.assertEqual(converted_kilobytes, 524288000)
        converted_megabytes = config_functions.convert_from_bytes(536870912000, 'm')
        self.assertEqual(converted_megabytes, 512000)

    def test_convert_to_bytes(self):
        """Test for config_functions.convert_to_bytes

        Using some test values, the method config_functions.convert_to_bytes
        is tested to verify if the convertion to bytes from other size types
        is working as intended.
        """
        converted_gigabytes = config_functions.convert_to_bytes(500, 'g')
        self.assertEqual(converted_gigabytes, 536870912000)
        converted_kilobytes = config_functions.convert_to_bytes(524288000, 'k')
        self.assertEqual(converted_kilobytes, 536870912000)
        converted_megabytes = config_functions.convert_to_bytes(512000, 'm')
        self.assertEqual(converted_megabytes, 536870912000)

    def test_get_percentage_byte_value(self):
        """Test for config_functions.get_percentage_byte_value

        Using some test values, the method config_functions.get_percentage_byte_value
        is tested to verify if the convertion from bytes to percentage of total space
        of the disk is working as intended.
        """
        bytes_value = config_functions.get_percentage_byte_value(20, self.space_info)
        self.assertEqual(bytes_value, self.space_info['total_space'] * 0.2)
        bytes_value = config_functions.get_percentage_byte_value(50, self.space_info)
        self.assertEqual(bytes_value, self.space_info['total_space'] * 0.5)
        bytes_value = config_functions.get_percentage_byte_value(2, self.space_info)
        self.assertEqual(bytes_value, self.space_info['total_space'] * 0.02)

    def test_get_file_size_limit(self):
        """Test for config_functions.get_file_size_limit

        Using the annotations_examples from test_data, the method config_functions.get_file_size_limit
        is tested to verify if the method calculates the file size limit as intended, according to
        the annotations configuration and disk space.
        """
        for annotations in self.annotations_examples:
            # Setup data as is expected in the method get_annotations_config
            raw_annotations = {
                'metadata': {
                    'annotations': annotations
                }
            }
            parsed_annotations = config_functions.get_annotations_config(raw_annotations)
            with mock.patch('k8s_coredump.config_functions.nsenter.Namespace'):
                with mock.patch('k8s_coredump.config_functions.os.path.dirname'):
                    try:
                        size_value_to_truncate = config_functions.get_file_size_limit('/core/file/path',
                            parsed_annotations, '9999')
                    except SystemExit:
                        if annotations['expected_truncate_value'] == 0:
                            size_value_to_truncate = 0
                        else:
                            raise SystemExit()
            self.assertEqual(size_value_to_truncate, annotations['expected_truncate_value'])

    def test_write_coredump_file(self):
        """Test for config_functions.write_coredump_file

        Using the annotations_examples from test_data, the method config_functions.write_coredump_file
        is tested to verify if the method calculates the file size limit as intended, according to
        the annotations configuration and disk space and writes the file respecting the file size
        limit with the correct content.
        """
        for annotations in self.annotations_examples:
            # Setup data as is expected in the method get_annotations_config
            raw_annotations = {
                'metadata': {
                    'annotations': annotations
                }
            }
            parsed_annotations = config_functions.get_annotations_config(raw_annotations)

            def mocked_open(path, mode):
                self.mocked_open_instance = MockedOpen(path, mode)
                return self.mocked_open_instance

            self.mock_stdin = MockedStdin(annotations['coredump_file_content'])

            with mock.patch('k8s_coredump.config_functions.nsenter.Namespace'):
                with mock.patch('k8s_coredump.config_functions.os.path.dirname'):
                    with mock.patch('k8s_coredump.config_functions.io.open', mocked_open):
                        with mock.patch('k8s_coredump.config_functions.sys.stdin', self.mock_stdin):
                            try:
                                config_functions.write_coredump_file('9999', '/core/file/path', parsed_annotations)
                                self.assertEqual(self.mocked_open_instance.path, '/core/file/path')
                                self.assertEqual(self.mocked_open_instance.mode, 'wb')
                            except SystemExit:
                                if annotations['expected_write_content'] != "":
                                    raise SystemExit()
                            if annotations['expected_write_content'] != "":
                                self.assertEqual(annotations['expected_write_content'],
                                    self.mocked_open_instance.opened_file.get_full_content())
