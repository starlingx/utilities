#! /bin/bash
#
# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="interface"
LOGFILE="${extradir}/${SERVICE}.info"

###############################################################################
# Interface Info
###############################################################################

echo    "${hostname}: Interface Info .: ${LOGFILE}"

delimiter ${LOGFILE} "ip link"
ip link >> ${LOGFILE}

for i in $(ls /sys/class/net/); do
    delimiter ${LOGFILE} "ethtool -i ${i}"
    ethtool -i ${i} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    delimiter ${LOGFILE} "ethtool -S ${i} | grep -v ': 0'"
    ethtool -S ${i} | grep -v ": 0" >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
done

exit 0
