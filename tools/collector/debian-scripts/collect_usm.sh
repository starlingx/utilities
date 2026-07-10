#! /bin/bash
#
# Copyright (c) 2024-2026 Wind River Systems, Inc.
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
# Gather USM releases and deployments in-progress
###############################################################################
function collect_usm {
    RELEASES=$(software list | tail -n +4 | awk '{ print $2; }')

    run_command "software deploy show" "${LOGFILE}"

    run_command "software deploy host-list" "${LOGFILE}"

    run_command "software list" "${LOGFILE}"

    for release in ${RELEASES}; do
        run_command "software show --packages --metapackages --pre-upgrade-deploy ${release}" "${LOGFILE}"
        sleep ${COLLECT_RUNCMD_DELAY}
    done

    run_command "software metapackage list --all" "${LOGFILE}"

    run_command "software metapackage list --pre-upgrade-deploy" "${LOGFILE}"
}

###############################################################################
# List feed content (files, directories, permissions)
###############################################################################
function collect_feed {
    for feed in /var/www/pages/feed/*; do
        run_command "ls -lhR --ignore __pycache__ --ignore ostree_repo ${feed}" "${LOGFILE}"
        sleep ${COLLECT_RUNCMD_DELAY}
    done
}

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then
    echo    "${hostname}: Unified Software Management ..: ${LOGFILE}"

    # Collect usm info
    collect_usm

    # Collect feed info
    collect_feed

    # Copy /opt/software to extra dir, excluding large and temp directories
    run_command "rsync -a /opt/software --exclude __pycache__ --exclude ostree_repo --exclude packages ${extradir}" "${LOGFILE}"
    sleep ${COLLECT_RUNCMD_DELAY}

    # Copy /var/www/pages/feed to extra dir, excluding large and temp directories
    run_command "rsync -a --exclude __pycache__ --exclude ostree_repo --exclude pxeboot /var/www/pages/feed ${extradir}" "${LOGFILE}"
    sleep ${COLLECT_RUNCMD_DELAY}
fi


exit 0
