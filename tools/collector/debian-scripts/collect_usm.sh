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

###############################################################################
# gather USM releases and deployments in-progress
###############################################################################
function collect_usm {
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
# list feed content (files, directories, permissions)
###############################################################################
function collect_feed {
    for feed in /var/www/pages/feed/*; do
        delimiter ${LOGFILE} "ls -lhR --ignore __pycache__ --ignore ostree_repo ${feed}"
        ls -lhR --ignore __pycache__ --ignore ostree_repo ${feed} >> ${LOGFILE}
    done
}

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then
    echo    "${hostname}: Unified Software Management ..: ${LOGFILE}"

    # collect usm info
    collect_usm

    # collect feed info
    collect_feed

    # copy /opt/software to extra dir
    rsync -a /opt/software ${extradir}

    # copy /var/www/pages/feed to extra dir, excluding large and temp directories
    rsync -a --exclude __pycache__ --exclude ostree_repo --exclude pxeboot /var/www/pages/feed ${extradir}
fi


exit 0
