########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the heartbeat loss plugin
# algorithm.
#
# The heartbeat loss plugin algorithm gathers all heartbeat loss error
# messages in the system.
#
########################################################################

import os

from plugin_algs.substring import substring


def heartbeat_loss(hosts, start, end, dropped_logs=None):
    """Heartbeat loss algorithm
    Presents all "Heartbeat Loss" error messages in the system

    Parameters:
        hosts (dictionary): Paths to folders for each host
        start (string): Start time for analysis
        end (string): End time for analysis
        dropped_logs (string): path/filename to write dropped logs
    """
    data = []
    hb_files = []

    for _, folder in hosts["controllers"].items():
        hb_path = os.path.join(folder, "var", "log", "hbsAgent.log")
        hb_files.append(hb_path)

    hb_substrings = ["Heartbeat Loss"]
    data = substring(start, end, hb_substrings, hb_files,
                     dropped_logs=dropped_logs)

    return sorted(data)
