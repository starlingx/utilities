########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the system info plugin algorithm.
#
# The system info plugin algorithm gathers top level system information,
# such at the build type, sw version, and more.
#
########################################################################

import os
import re


def system_info(host_dir):
    """System info algorithm
    Presents basic information about the system, such as the build type

    Parameters:
        host_dir (string): path to the collect host dir
    """
    data = []
    with open(
        os.path.join(host_dir, "etc", "platform", "platform.conf")
    ) as file:
        for line in file:
            if "system_mode" in line:
                data.append(
                    f"System Mode: "
                    f"{re.match('^system_mode=(.*)', line).group(1)}"
                )
            elif "system_type" in line:
                data.append(
                    f"System Type: "
                    f"{re.match('^system_type=(.*)', line).group(1)}"
                )
            elif "distributed_cloud_role" in line:
                role = re.match('^distributed_cloud_role=(.*)',
                                line).group(1)
                data.append(f"Distributed cloud role: {role}")
            elif "sw_version" in line:
                data.append(
                    f"SW Version: "
                    f"{re.match('^sw_version=(.*)', line).group(1)}"
                )
    with open(
        os.path.join(host_dir, "etc", "build.info")
    ) as file:
        for line in file:
            if "BUILD_TYPE" in line:
                data.append(
                    f"Build Type: "
                    f"{re.match('^BUILD_TYPE=(.*)', line).group(1)}"
                )
            elif re.match("^OS=(.*)", line):
                data.append(f"OS: {re.match('^OS=(.*)', line).group(1)}")

    return data
