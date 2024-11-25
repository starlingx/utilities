#! /bin/bash
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="alarms"
LOGFILE="${extradir}/${SERVICE}.info"

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then

    is_active_controller
    if [ "$?" = "0" ] ; then
        exit 0
    fi

    echo    "${hostname}: System Alarm List .: ${LOGFILE}"

    # These go into the SERVICE.info file
    delimiter ${LOGFILE} "fm alarm-list"
    fm alarm-list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}
    sleep ${COLLECT_RUNCMD_DELAY}

    delimiter ${LOGFILE} "fm event-list --nopaging"
    fm event-list --nopaging 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}
    sleep ${COLLECT_RUNCMD_DELAY}
fi

exit 0
