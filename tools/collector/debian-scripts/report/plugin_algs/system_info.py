########################################################################
#
# Copyright (c) 2022 -2026 Wind River Systems, Inc.
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

import configparser
import logging
import os
import re

logger = logging.getLogger(__name__)


def system_info(hostname, host_dir, output_dir, hosts, loud=False):
    """System info algorithm.

    Presents basic information about the system, such as the build type.

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

    try:
        config = configparser.ConfigParser()
        # platform.conf has no section headers, so read under a dummy section
        with open(platform_conf) as f:
            config.read_string('[platform]\n' + f.read())
        pf = config['platform']

        # Output in specific order — some fields are optional
        field_map = [
            ('system_type', 'System Type'),
            ('sw_version', 'S/W Version'),
            ('system_mode', 'System Mode'),
            ('distributed_cloud_role', 'DC Role    '),
            ('nodetype', 'Node Type  '),
            ('subfunction', 'subfunction'),
            ('management_interface', 'Mgmt Iface '),
            ('cluster_host_interface', 'Clstr Iface'),
            ('oam_interface', 'OAM Iface  '),
        ]
        for key, label in field_map:
            if key in pf:
                data.append(f"{label}: {pf[key]}")
    except FileNotFoundError:
        logger.warning("%s: platform.conf not found", hostname)

    # /etc/os-release info
    try:
        with open(os.path.join(host_dir, "etc", "os-release")) as file:
            for line in file:
                if "PRETTY_NAME" in line:
                    val = (re.match('^PRETTY_NAME=(.*)', line).group(1))
                    val = val.strip('\"')
                    data.append(f"OS Release : {val}")
    except FileNotFoundError:
        logger.warning("%s: os-release not found", hostname)

    # /etc/build.info
    try:
        with open(os.path.join(host_dir, "etc", "build.info")) as file:
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
    except FileNotFoundError:
        logger.warning("%s: build.info not found", hostname)

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
    return
