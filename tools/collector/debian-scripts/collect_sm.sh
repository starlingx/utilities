#! /bin/bash
#
# Copyright (c) 2013-2014,2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="sm"
LOGFILE="${extradir}/sm.info"
echo    "${hostname}: Service Management : ${LOGFILE}"

###############################################################################
# Only Controller
###############################################################################

if [ "$nodetype" = "controller" ] ; then
    kill -SIGUSR1 $(</var/run/sm.pid)
    run_command "sm-troubleshoot" "${LOGFILE}"
fi

exit 0
