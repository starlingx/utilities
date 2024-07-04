########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the maintenance errors plugin
# algorithm.
#
# The maintenance errors plugin algorithm gathers all maintenance errors
# in the system, as well as other relevant, significant log messages.
#
########################################################################

import os

from plugin_algs.substring import substring


def maintenance_errors(hosts, start, end,
                       exclude_list=None,
                       dropped_logs=None):
    """Maintenance errors algorithm
    Presents maintenance errors and other relevant log messages in system,
    such as "Configuration failure"

    Parameters:
        hosts (dictionary): Paths to folders for each host
        start (string): Start time for analysis
        end (string): End time for analysis
        exclude_list (string list): list of strings to exclude from report
        dropped_logs (string): path/filename to write dropped logs
    """
    data = []
    mtc_files = []

    for _, folder in hosts["controllers"].items():
        agent = os.path.join(folder, "var", "log", "mtcAgent.log")
        mtc_files.append(agent)

    for host_type in hosts.keys():
        for _, folder in hosts[host_type].items():
            client = os.path.join(folder, "var", "log", "mtcClient.log")
            mtc_files.append(client)

    mtc_substrings = ["Error : ",
                      "Configuration failure",
                      "In-Test Failure",
                      "Loss Of Communication",
                      "Graceful Recovery Wait ",
                      "regained MTCALIVE from host that has rebooted",
                      "Connectivity Recovered ; ",
                      "auto recovery disabled",
                      "Graceful Recovery Failed",
                      "MNFA ENTER", "MNFA EXIT", "MNFA POOL"]
    data = substring(start, end, mtc_substrings, mtc_files, exclude_list,
                     dropped_logs=dropped_logs)

    return sorted(data)
