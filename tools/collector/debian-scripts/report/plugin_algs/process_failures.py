########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the process failures plugin
# algorithm.
#
# The process failures plugin algorithm searchs through pmond.log and
# gathers all log errors
#
########################################################################

import os

from plugin_algs.substring import substring


def process_failures(hosts, start, end, dropped_logs=None):
    """Process failures algorithm
        Presents all "Error : " log messages from pmond

    Parameters:
        hosts (dictionary): Paths to folders for each host
        start (string): Start time for analysis
        end (string): End time for analysis
        dropped_logs (string): path/filename to write dropped logs
    """
    data = []
    files = []
    for host_type in hosts.keys():
        for _, folder in hosts[host_type].items():
            pmond = os.path.join(folder, "var", "log", "pmond.log")
            files.append(pmond)

    data = substring(start, end, ["Error :"], files, dropped_logs=dropped_logs)

    return sorted(data)
