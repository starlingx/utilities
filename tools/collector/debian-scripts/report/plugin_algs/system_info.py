########################################################################
#
# Copyright (c) 2022 -2023 Wind River Systems, Inc.
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


def system_info(hostname, host_dir, output_dir, hosts, loud=False):
    """System info algorithm
    Presents basic information about the system, such as the build type

    Parameters:
        hostname   (string): make of the host
        host_dir   (string): path to the collect host dir
        output_dir (string): path to the file to store the system info
        hosts      (string): list of host objects
        loud      (boolean): when True print system info to stdout

    Returns: nothing
    """
    data = []

    if host_dir is None:
        raise ValueError("system_info:No specified host dir")

    # from /etc/platform/platform.conf
    platform_conf = os.path.join(host_dir, "etc", "platform", "platform.conf")

    # ... load the following items first
    with open(platform_conf) as file:
        for line in file:
            if "system_mode" in line:
                val = re.match('^system_mode=(.*)', line).group(1)
                data.append(f"System Mode: {val}")
            elif "system_type" in line:
                val = re.match('^system_type=(.*)', line).group(1)
                data.append(f"System Type: {val}")
            elif "distributed_cloud_role" in line:
                role = re.match('^distributed_cloud_role=(.*)',
                                line).group(1)
                data.append(f"DC Role    : {role}")
            elif "sw_version" in line:
                val = re.match('^sw_version=(.*)', line).group(1)
                data.append(f"S/W Version: {val}")
    # ... followed by these items
    with open(platform_conf) as file:
        for line in file:
            if "nodetype" in line:
                val = re.match('^nodetype=(.*)', line).group(1)
                data.append(f"Node Type  : {val}")
            elif "subfunction" in line:
                val = re.match('^subfunction=(.*)', line).group(1)
                data.append(f"subfunction: {val}")
            elif "oam_interface" in line:
                val = re.match('^oam_interface=(.*)', line).group(1)
                data.append(f"OAM Iface  : {val}")
            elif "management_interface" in line:
                val = re.match('^management_interface=(.*)', line).group(1)
                data.append(f"Mgmt Iface : {val}")
            elif "cluster_host_interface" in line:
                val = re.match('^cluster_host_interface=(.*)', line).group(1)
                data.append(f"Clstr Iface: {val}")

    # /etc/os-release info
    with open(
        os.path.join(host_dir, "etc", "os-release")
    ) as file:
        for line in file:
            if "PRETTY_NAME" in line:
                val = (re.match('^PRETTY_NAME=(.*)', line).group(1))
                val = val.strip('\"')
                data.append(f"OS Release : {val}")

    # /etc/build.info
    with open(
        os.path.join(host_dir, "etc", "build.info")
    ) as file:
        for line in file:
            if "BUILD_TYPE" in line:
                val = (re.match('^BUILD_TYPE=(.*)', line).group(1))
                val = val.strip('\"')
                data.append(f"Build Type : {val}")
            elif "BUILD_DATE" in line:
                val = (re.match('^BUILD_DATE=(.*)', line).group(1))
                val = val.strip('\"')
                data.append(f"Build Date : {val}")
            elif "BUILD_DIR" in line:
                val = (re.match('^BUILD_DIR=(.*)', line).group(1))
                val = val.strip('\"')
                data.append(f"Build Dir  : {val}")

    with open(output_dir, "a") as file:
        dashs = "-" * len(hostname)
        file.write("\n" + hostname + "\n" + dashs + "\n")
        for i in data:
            file.write(i + "\n")
            if loud is True:
                print(i)

        if hosts is not None:
            for k, v in hosts.items():
                if not len(v.keys()):
                    continue
                if k == "storages":
                    k += "   "
                if k == "workers":
                    k += "    "
                file.write(f"{k}: {','.join(v.keys())}\n")
                if loud is True:
                    print(f"{k}: {','.join(v.keys())}")

    # create an empty line following the system info dump
    if loud is True:
        print("")

    return
