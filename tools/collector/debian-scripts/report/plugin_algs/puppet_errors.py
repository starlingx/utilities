########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the puppet errors plugin
# algorithm.
#
# The puppet errors plugin algorithm searches through all the puppet
# logs for any errors.
#
########################################################################

import os

from plugin_algs.substring import _evaluate_substring


def puppet_errors(hosts, start, end):
    """Puppet errors algorithm
    Presents all "Error: " log messages from puppet logs

    Parameters:
        hosts (dictionary): Paths to folders for each host
        start (string): Start time for analysis
        end (string): End time for analysis
    """
    data = []
    for host_type in hosts.keys():
        for _, folder in hosts[host_type].items():
            puppet_folder = os.path.join(folder, "var", "log", "puppet")
            command = (f"""grep -rh "[m ]Error: " {puppet_folder} """
                       f"""2>/dev/null""")
            _evaluate_substring(start, end, data, command)

    return sorted(data)
