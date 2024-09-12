#! /bin/bash
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="usm"
LOGFILE="${extradir}/${SERVICE}.info"
USM_DIR="/opt/software"

function collect_usm {
    echo    "${hostname}: Unified Software Management ..: ${LOGFILE}"

    RELEASES=$(software list | tail -n +4 | awk '{ print $2; }')

    delimiter ${LOGFILE} "software deploy show"
    software deploy show 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "software deploy host-list"
    software deploy host-list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "software list"
    software list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    for release in ${RELEASES}; do
        delimiter ${LOGFILE} "software show --packages ${release}"
        software show --packages ${release} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}
    done
}

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then
    # collect usm info
    collect_usm

    # copy /opt/software to extra dir
    rsync -a /opt/software ${extradir}
fi


exit 0
