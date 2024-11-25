#! /bin/bash
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="systemd"
LOGFILE="${extradir}/${SERVICE}.info"
PLOTFILE="${extradir}/${SERVICE}-startup-plot.svg"

###############################################################################
# Systemd analysis
###############################################################################
echo    "${hostname}: Systemd analyze .........: ${LOGFILE}"

run_command "timeout 10 systemd-analyze plot > ${PLOTFILE}" "${LOGFILE}"

exit 0
