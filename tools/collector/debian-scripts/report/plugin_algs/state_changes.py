########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the state changes plugin
# algorithm.
#
# The state changes plugin algorithm gathers all log messages in the
# system pertaining to the state of hosts.
#
########################################################################

import os

from plugin_algs.substring import substring


def state_changes(hosts, start, end):
    """State changes algorithm
    Presents all messages in the system regarding the state of hosts, such
    as "is ENABLED"

    Parameters:
        hosts (dictionary): Paths to folders for each host
        start (string): Start time for analysis
        end (string): End time for analysis
    """
    data = []
    sc_files = []

    for _, folder in hosts["controllers"].items():
        sc_path = os.path.join(folder, "var", "log", "mtcAgent.log")
        sc_files.append(sc_path)

    sc_substrings = ["is ENABLED", "allStateChange (.+)locked-disabled"]
    data = substring(start, end, sc_substrings, sc_files)

    return sorted(data)
