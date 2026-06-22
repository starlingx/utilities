#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Report tool global test suite with coverage reporting.
#
# Usage:
#     ./run_tests.py              # Run all tests
#     ./run_tests.py --with-cov   # Run with coverage report
#
# Requirements:
#     pip install coverage pytest pytest-cov
#
########################################################################

import os
import subprocess
import sys

REPORT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_FILES = [
    'test_report.py',
    'test_substring.py',
    'test_correlator.py',
    'test_plugin.py',
    'test_alarm.py',
]

SOURCE_MODULES = [
    'report',
    'execution_engine',
    'correlator',
    'plugin',
    'algorithms',
    'plugin_algs.substring',
    'plugin_algs.alarm',
    'plugin_algs.system_info',
    'plugin_algs.swact_activity',
    'plugin_algs.heartbeat_loss',
    'plugin_algs.maintenance_errors',
    'plugin_algs.daemon_failures',
    'plugin_algs.process_failures',
    'plugin_algs.puppet_errors',
    'plugin_algs.state_changes',
]


def main():
    os.chdir(REPORT_DIR)
    with_cov = '--with-cov' in sys.argv

    if with_cov:
        cmd = [
            sys.executable, '-m', 'coverage', 'run',
            '--source=' + ','.join(SOURCE_MODULES),
            '-m', 'unittest', 'discover', '-s', TEST_DIR, '-p', 'test_*.py'
        ]
    else:
        cmd = [
            sys.executable, '-m', 'unittest', 'discover',
            '-s', TEST_DIR, '-p', 'test_*.py', '-v'
        ]

    result = subprocess.run(cmd)

    if with_cov and result.returncode == 0:
        print("\n" + "=" * 60)
        print("CODE COVERAGE REPORT")
        print("=" * 60)
        subprocess.run([sys.executable, '-m', 'coverage', 'report',
                        '--show-missing', '--skip-empty'])
        print("=" * 60)

    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
