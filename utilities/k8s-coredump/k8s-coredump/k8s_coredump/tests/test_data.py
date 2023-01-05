################################################################################
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
import mock

# Mocking logging.basicConfig to avoid "path not found" error on constants.py that is imported by config_functions.
with mock.patch('logging.basicConfig') as mock_method:
    from k8s_coredump import config_functions
    from k8s_coredump.common import constants

# Mock for disk usage using values in bytes: Total = 500GB / Used = 250GB / Free = 250GB
DISK_USAGE = {'total_space': 536870912000, 'used_space': 268435456000, 'free_space': 268435456000}

# Dictionary with test input values and expected values for individual test cases.
ANNOTATIONS_EXAMPLES = [
    {
        "starlingx.io/core_pattern": "test.core.%P.%U.%G.%S.%T.%E.%H",  # All Upper Case
        "starlingx.io/core_max_size": "200K",  # Test Kilobytes and Upper case
        "starlingx.io/core_compression": "lz4",  # Test compression.
        "starlingx.io/core_max_used": "20%",  # Test maximum used space
        "starlingx.io/core_min_free": "20%",
        "expected_core_pattern": "test.core.999999.8.7.6.1671181200.process_name_for_k8s_handler.test_host",
        "expected_core_max_size": (200.0, config_functions.file_size_properties['k']),
        "expected_truncate_value": 0,
        # The value here is 0 because the core_max_used is 20% and the test
        # setup the disk space to be 50% used.
        "coredump_file_content": "0123456789012345678901234567890123456789",
        "expected_write_content": "",
    },
    {
        "starlingx.io/core_pattern": "test.core.%p.%u.%g.%s.%t.%e.%h",  # All Lower Case
        "starlingx.io/core_max_size": "20m",  # Test Megabytes and Lower case
        "expected_core_pattern": "test.core.999999.8.7.6.1671181200.process_name_for_k8s_handler.test_host",
        "expected_core_max_size": (20.0, config_functions.file_size_properties['m']),
        "expected_truncate_value": 20971520,  # 20mb in Bytes
        "coredump_file_content": "0123456789012345678901234567890123456789",
        "expected_write_content": "0123456789012345678901234567890123456789",
    },
    {
        "starlingx.io/core_pattern": "test.core.%P.%u.%G.%s.%t.%E.%h",  # Mixed Case
        "starlingx.io/core_max_size": "2G",  # Test Gigabytes
        "starlingx.io/core_min_free": "249G",
        # The test is setup to have 250gb free space, configuring 249gb as
        # the core_min_free will make the file_size_limit to be 1GB.
        "expected_core_pattern": "test.core.999999.8.7.6.1671181200.process_name_for_k8s_handler.test_host",
        "expected_core_max_size": (2.0, config_functions.file_size_properties['g']),
        "expected_truncate_value": 1073741824,
        # 1gb in Bytes, which is the last remaing 1GB free according to the core_min_free annotation.
        "coredump_file_content": "0123456789012345678901234567890123456789",
        "expected_write_content": "0123456789012345678901234567890123456789",
    },
    {
        "starlingx.io/core_pattern": "",  # Empty
        "starlingx.io/core_max_size": "2%",  # Percentage
        "expected_core_pattern": "",
        "expected_core_max_size": (2.0, config_functions.file_size_properties['%']),
        "expected_truncate_value": 10737418240,  # 10gb in Bytes, that is 2% of the 500GB of total disk space
        "coredump_file_content": "0123456789012345678901234567890123456789",
        "expected_write_content": "0123456789012345678901234567890123456789",
    },
    {
        "starlingx.io/core_pattern": "test.core.%p.%u.%g.%s.%t.%e.%h",  # All Lower Case
        "starlingx.io/core_max_size": "10b",  # Test bytes and Lower case
        "expected_core_pattern": "test.core.999999.8.7.6.1671181200.process_name_for_k8s_handler.test_host",
        "expected_core_max_size": (10.0, config_functions.file_size_properties['b']),
        "expected_truncate_value": 10,  # 10 Bytes
        "coredump_file_content": "012345678901234567890123456789",
        "expected_write_content": "0123456789",
    },
    {
        "starlingx.io/core_pattern": "/var/log/coredump/test.core.%P.%u.%G.%s.%t.%E.%h",  # With path
        "expected_core_pattern":
            "/var/log/coredump/test.core.999999.8.7.6.1671181200.process_name_for_k8s_handler.test_host",
        "expected_truncate_value": 0,  # No size limit
        "coredump_file_content": "012345678901234567890123456789",
        "expected_write_content": "012345678901234567890123456789",
    },
]

# Expected values for token file
EXPECTED_TOKEN = "EXPECTED_KUBERNETES_COREDUMP_HANDLER_KUBECTL_TOKEN"
EXPECTED_TOKEN_PATH = constants.K8S_COREDUMP_CONF
EXPECTED_TOKEN_MODE = "r"

# Expected value for the pod UID
MOCKED_UID = "2284e2ba-cdaf-4558-907a-b9364b66f3e9"

# CGROUP file mock for coredump._getPodUID method test
CGROUP_FILE_MOCK = f"""
12:blkio:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
11:pids:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
10:hugetlb:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
9:perf_event:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
8:cpuset:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
7:memory:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
6:cpu,cpuacct:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
5:rdma:/
4:freezer:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
3:net_cls,net_prio:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
2:devices:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
1:name=systemd:/k8s-infra/kubepods/besteffort/pod{MOCKED_UID}/0123456789012345678901234567890123456789012345678901234567890123
0::/system.slice/containerd.service
"""

# Mocked pod information for the coredump._lookupPod method test
MOCKED_POD_INFO = f"""
{{
    "metadata": {{
        "uid": "{MOCKED_UID}",
        "annotations":
            {{
                "starlingx.io/core_pattern": "test.core.%P.%U.%G.%S.%T.%E.%H",
                "starlingx.io/core_max_size": "200K",
                "starlingx.io/core_compression": "lz4",
                "starlingx.io/core_max_used": "20%",
                "starlingx.io/core_min_free": "20%"
            }}
    }}
}}
"""
MOCKED_PODS_REQUEST_RESPONSE = f"""
{{
    "items": [
        {MOCKED_POD_INFO}
    ]
}}
"""
