########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the swact activity plugin
# algorithm.
#
# The swact activity plugin algorithm gathers information about all
# swacting activity in the system.
#
########################################################################

from datetime import datetime
import os

from plugin_algs.substring import substring


def swact_activity(hosts, start, end):
    """Swact activity algorithm
    Presents all log messages about swacting activity in the system, such as
    "Uncontrolled swact"

    Parameters:
        hosts (dictionary): Paths to folders for each host
        start (string): Start time for analysis
        end (string): End time for analysis
    Returns:
        data (list): a list of logs that represent evidence of swact activity
    """
    data = []
    sm_files = []
    sm_customer_files = []
    swact_start = None
    swact_in_progress = False
    swact_end = None

    for _, folder in hosts["controllers"].items():
        sm_path = os.path.join(folder, "var", "log", "sm.log")
        sm_files.append(sm_path)
        sm_customer_path = os.path.join(folder, "var", "log",
                                        "sm-customer.log")
        sm_customer_files.append(sm_customer_path)

    sm_substrings = ["Uncontrolled swact", "Swact has started,",
                     "Neighbor (.+) is now in the down",
                     "Service (.+) has reached max failures",
                     "Swact update"]
    data = substring(start, end, sm_substrings, sm_files)

    for i, line in enumerate(data):
        if "Swact has started," in line and not swact_in_progress:
            swact_in_progress = True
            swact_start = datetime.strptime(line[0:19],
                                            "%Y-%m-%dT%H:%M:%S")
        elif "Swact update" in line and swact_in_progress:
            swact_in_progress = False
            swact_end = datetime.strptime(line[0:19], "%Y-%m-%dT%H:%M:%S")
            line += f" SWACT TOOK {swact_end - swact_start} \n"
            data[i] = line

    sm_customer_substrings = [
        "swact", "active-failed\\s+\\| disabling-failed\\s+\\|"
    ]
    data += substring(start, end, sm_customer_substrings,
                      sm_customer_files)

    return sorted(data)
