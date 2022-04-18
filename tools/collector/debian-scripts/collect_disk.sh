#! /bin/bash
#
# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="disk"
LOGFILE="${extradir}/${SERVICE}.info"

###############################################################################
# Disk Info
###############################################################################

echo    "${hostname}: Disk Info .: ${LOGFILE}"

for device in $(lsblk -l -o NAME,TYPE,TRAN | grep -v usb | grep -e disk | cut -d ' ' -f1); do
    delimiter ${LOGFILE} "smartctl -a ${device}"
    smartctl -a "/dev/${device}" >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
done

exit 0
