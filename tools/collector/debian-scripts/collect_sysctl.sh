#! /bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="sysctl"
LOGFILE="${extradir}/${SERVICE}.info"

echo    "${hostname}: Sysctl Info .......: ${LOGFILE}"

###############################################################################
# Sysctl Info:
###############################################################################

run_command "timeout 10 sysctl -a" "${LOGFILE}"

delimiter "${LOGFILE}" "/proc/sys/"
{
    # Use find to iterate over all files (-type f) in /proc/sys
    find "/proc/sys" -type f | while read -r file
    do
        echo "--- File: $file ---"
        # Use cat to print content, redirecting errors to /dev/null
        # to avoid "Permission denied" or I/O error noise
        cat "$file" 2>/dev/null || echo "[Error reading file]"
        echo ""
    done
} >> "${LOGFILE}"

exit 0
