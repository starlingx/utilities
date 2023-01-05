################################################################################
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
import collections
import json

import fixtures
from k8s_coredump import coredump
from k8s_coredump.tests.base import BaseTestCase
from k8s_coredump.tests.base import MockedOpen
from k8s_coredump.tests.base import MockedStdin
from k8s_coredump.tests.test_data import ANNOTATIONS_EXAMPLES
from k8s_coredump.tests.test_data import DISK_USAGE
from k8s_coredump.tests.test_data import EXPECTED_TOKEN
from k8s_coredump.tests.test_data import EXPECTED_TOKEN_MODE
from k8s_coredump.tests.test_data import EXPECTED_TOKEN_PATH
from k8s_coredump.tests.test_data import MOCKED_POD_INFO
from k8s_coredump.tests.test_data import MOCKED_PODS_REQUEST_RESPONSE
from k8s_coredump.tests.test_data import MOCKED_UID
import mock


class MockedGetResponse(object):
    def __init__(self, url, headers, timeout, verify, response=MOCKED_PODS_REQUEST_RESPONSE):
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.verify = verify
        self.response = response

    def json(self):
        return json.loads(self.response)


class TestCoredump(BaseTestCase):

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(TestCoredump, self).setUp()

        self.expected_token = EXPECTED_TOKEN
        self.expected_path = EXPECTED_TOKEN_PATH
        self.expected_mode = EXPECTED_TOKEN_MODE

        self.useFixture(
            fixtures.MonkeyPatch('k8s_coredump.coredump.open', MockedOpen))

        self.useFixture(
            fixtures.MonkeyPatch('k8s_coredump.coredump.io.open', MockedOpen))

        def mocked_run(cmd):
            self.run_command = cmd

        self.useFixture(
            fixtures.MonkeyPatch('k8s_coredump.coredump.subprocess.run', mocked_run))

        def mocked_requests_get(url, headers, timeout, verify):
            self.mocked_get = MockedGetResponse(url, headers, timeout, verify)
            return self.mocked_get

        self.useFixture(
            fixtures.MonkeyPatch('k8s_coredump.coredump.requests.get', mocked_requests_get))

        self.annotations_examples = ANNOTATIONS_EXAMPLES

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

    def test_getToken(self):
        """Test for coredump._getToken

        Using some mocked data, the method coredump._getToken is tested to verify if
        the method returns the token as expected, also verifying the path and mode that
        the json file containing the token was opened.
        The setup data for this test is done in MockedFile.read, as this is the way that
        coredump._getToken uses to get the token.
        """
        token = coredump._getToken()
        expected_result = f"{self.expected_token}.{self.expected_path}.{self.expected_mode}"
        self.assertEqual(token, expected_result)

    def test_systemCoreFile(self):
        """Test for coredump._systemCoreFile

        Using a mocked run method, the method coredump._systemCoreFile is tested to verify if
        the method attempts to run the right command when invoking systemd-coredump.
        See the mocked_run in the setup method of this test case class.
        """
        self.run_command = ""
        coredump._systemCoreFile()
        self.assertEqual(self.run_command[0], '/usr/lib/systemd/systemd-coredump')

    def test_getPodUID(self):
        """Test for coredump._getPodUID

        Using a mocked open method, the method coredump._getPodUID is tested to verify if
        the method manages to get the pod UID correctly.
        See the MockedFile.__iter__ and MockedFile.__next__ in the base file for the methods
        that are mocked for this test case.
        """
        pod_uid = coredump._getPodUID("9999999")
        self.assertEqual(pod_uid, MOCKED_UID)

    def test_lookupPod(self):
        """Test for coredump._lookupPod

        Using a mocked requests.get method, the method coredump._lookupPod is tested to verify if
        the method manages to get the pod information correctly.
        See the mocked_requests_get in the setup method of this test case class and
        MockedGetResponse class for the mocks for this test case.
        """
        pod_info = coredump._lookupPod("9999999")
        mocked_pod_info_dict = json.loads(MOCKED_POD_INFO)
        self.assertEqual(pod_info, mocked_pod_info_dict)
        metadata = pod_info.get("metadata")
        pod_uid = metadata.get("uid")
        self.assertEqual(pod_uid, MOCKED_UID)

    def test_CoreDumpHandler(self):
        """Test for coredump.CoreDumpHandler

        Using the annotations_examples from test_data, the method coredump.CoreDumpHandler
        is tested to verify if the method executes the whole process, validating annotations
        configurations and writing the right content to the coredump file.
        See MockedFile write, tell and get_full_content for the methods that are used
        in this test case.
        """
        for annotations in self.annotations_examples:
            self.mocked_response = f"""
                {{
                    "items": [
                        {{
                            "metadata": {{
                                "uid": "{MOCKED_UID}",
                                "namespace": "POD_NAME",
                                "name": "APPLICATION_NAME",
                                "annotations":
                                    {{
                                        "starlingx.io/core_pattern": "{annotations.get(
                                            "starlingx.io/core_pattern", "")}",
                                        "starlingx.io/core_max_size": "{annotations.get(
                                            "starlingx.io/core_max_size", "")}",
                                        "starlingx.io/core_compression": "{annotations.get(
                                            "starlingx.io/core_compression", "")}",
                                        "starlingx.io/core_max_used": "{annotations.get(
                                            "starlingx.io/core_max_used", "")}",
                                        "starlingx.io/core_min_free": "{annotations.get(
                                            "starlingx.io/core_min_free", "")}"
                                    }}
                            }}
                        }}
                    ]
                }}
            """

            def mocked_requests_get(url, headers, timeout, verify):
                self.mocked_get = MockedGetResponse(url, headers, timeout, verify, self.mocked_response)
                return self.mocked_get

            def mocked_open(path, mode):
                self.mocked_open_instance = MockedOpen(path, mode)
                return self.mocked_open_instance

            self.mock_stdin = MockedStdin(annotations['coredump_file_content'])

            with mock.patch('k8s_coredump.coredump.requests.get', mocked_requests_get):
                with mock.patch('k8s_coredump.config_functions.nsenter.Namespace'):
                    with mock.patch('k8s_coredump.config_functions.os.path.dirname'):
                        with mock.patch('k8s_coredump.config_functions.io.open', mocked_open):
                            with mock.patch('k8s_coredump.config_functions.sys.stdin', self.mock_stdin):
                                try:
                                    coredump.CoreDumpHandler(**self.input_kwargs)
                                except SystemExit:
                                    if annotations['expected_write_content'] != "":
                                        raise SystemExit()
                                if annotations['expected_write_content'] != "":
                                    self.assertEqual(annotations['expected_write_content'],
                                        self.mocked_open_instance.opened_file.get_full_content())
