#! /bin/bash
#
# Copyright (c) 2020-2026 Wind River Systems, Inc.
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

delimiter ${LOGFILE} "ip -br link"
ip -br link >> ${LOGFILE}

delimiter ${LOGFILE} "grep . /sys/class/net/*/statistics/*_errors | grep -v ':0$'"
grep . /sys/class/net/*/statistics/*_errors | grep -v ':0$'  >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}


for iface_path in /sys/class/net/*; do
    # Skip virtual interfaces
    if [ ! -L "$iface_path/device" ]; then
        continue
    fi

    iface=$(basename "$iface_path")

    delimiter "${LOGFILE}" "Network interface: ${iface}"

    delimiter ${LOGFILE} "ethtool ${iface}"
    ethtool ${iface} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    delimiter ${LOGFILE} "ethtool -i ${iface}"
    ethtool -i ${iface} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    delimiter ${LOGFILE} "ethtool -k ${iface}"
    ethtool -k ${iface} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    delimiter ${LOGFILE} "ethtool -T ${iface}"
    ethtool -T ${iface} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    delimiter ${LOGFILE} "ethtool -S ${iface} | grep -v ': 0'"
    ethtool -S ${iface} | grep -v ": 0" >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
done

delimiter ${LOGFILE} "dpdk-devbind.py -s"
dpdk-devbind.py -s >> ${LOGFILE}

exit 0
