#! /bin/bash
#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SYSADMIN_DIR="${extradir}/sysadmin"
mkdir -p ${SYSADMIN_DIR}

# Function to copy files based on pattern
copy_files()
{
    local pattern=$1
    for file in /home/sysadmin/${pattern} ; do
        [ -e "${file}" ] && cp "${file}" "${SYSADMIN_DIR}/"
    done
}

# get the log and yaml files from the sysadmin home dir
copy_files "*.log"
copy_files "*.yml"
copy_files "*.yaml"

exit 0
