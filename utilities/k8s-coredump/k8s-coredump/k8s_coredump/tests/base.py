################################################################################
# Copyright (c) 2023,2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
import io
from io import StringIO

import fixtures
from k8s_coredump.tests.test_data import CGROUP_FILE_MOCK
from k8s_coredump.tests.test_data import EXPECTED_TOKEN
from testtools import TestCase


class FakeLog(object):
    def __init__(self):
        self.logs = {"info": [], "error": []}

    def clear_logs(self):
        self.logs = {"info": [], "error": []}

    def info(self, string_log):
        self.logs['info'].append(string_log)

    def debug(self, string_log):
        self.logs['info'].append(string_log)

    def error(self, string_log):
        self.logs['error'].append(string_log)

    def critical(self, string_log):
        self.logs['error'].append(string_log)

    def get_info(self):
        return f"Info:\n{[a for a in self.logs['info']]}"

    def get_error(self):
        return f"Error:\n{[a for a in self.logs['error']]}"

    def get_all(self):
        return f"{self.get_info()}\n{self.get_error()}"


class MockedFile(object):
    def __init__(self, path, mode):
        self.path = path
        self.mode = mode
        self.content = []
        self.bytes_amount = 0

    def write(self, content):
        self.bytes_amount += len(content)
        self.content.append(content)

    def tell(self):
        return self.bytes_amount

    def flush(self):
        pass

    def get_full_content(self):
        content = ""
        for item in self.content:
            content += item
        return content

    def read(self):
        # This method is used on the test for the coredump._getToken method.
        return f"""
            {{
                "k8s_coredump_token": "{EXPECTED_TOKEN}.{self.path}.{self.mode}"
            }}
            """

    def __iter__(self):
        # This method is used on the test for the coredump._getPodUID method.
        self.string_file = io.StringIO(CGROUP_FILE_MOCK)
        return self

    def __next__(self):
        # This method is used on the test for the coredump._getPodUID method.
        line = self.string_file.readline()
        if line != '':
            return line
        else:
            raise StopIteration


class MockedOpen(object):
    def __init__(self, path, mode):
        self.path = path
        self.mode = mode

    def __enter__(self):
        self.opened_file = MockedFile(self.path, self.mode)
        return self.opened_file

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def readline(self):
        raise NotImplementedError(
            "If you're seeing this, something went wrong with the tests, check the logs.")


class MockedStdin(object):
    def __init__(self, coredump_content):
        self.buffer = StringIO(coredump_content)


class BaseTestCase(TestCase):

    def setUp(self):
        """Run before each test method to initialize test environment."""
        super(BaseTestCase, self).setUp()

        self.fake_log = FakeLog()

        self.useFixture(
            fixtures.MonkeyPatch('k8s_coredump.config_functions.LOG', self.fake_log))

        self.useFixture(
            fixtures.MonkeyPatch('k8s_coredump.coredump.LOG', self.fake_log))

        # Values that would come from the invokation of k8s-coredump-handler
        self.input_kwargs = {
            'host_pid': "999999",  # %P
            'uid': "8",  # %u
            'gid': "7",  # %g
            'signal': "6",  # %s
            'timestamp': "1671181200",  # %t
            'hostname': "test_host",  # %h
            'comm': "process_name_for_k8s_handler",  # %e
            'container_pid': "123456",  # %p
        }
