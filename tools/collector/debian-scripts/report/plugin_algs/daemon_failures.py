########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the daemon failures plugin
# algorithm.
#
# The daemon failures plugin algorithm gathers all failed puppet
# manifest messages in the system.
#
########################################################################

import os

from plugin_algs.substring import substring


def daemon_failures(hosts, start, end):
    """Daemon failures algorithm
    Presents all "Failed to run the puppet manifest" log messages in the system

    Parameters:
        hosts (dictionary): Paths to folders for each host
        start (string): Start time for analysis
        end (string): End time for analysis
    """
    data = []
    daemon_files = []

    for host_type in hosts.keys():
        for _, folder in hosts[host_type].items():
            daemon_path = os.path.join(folder, "var", "log", "daemon.log")
            daemon_files.append(daemon_path)

    daemon_substrings = ["Failed to run the puppet manifest"]
    data = substring(start, end, daemon_substrings, daemon_files)

    return sorted(data)
