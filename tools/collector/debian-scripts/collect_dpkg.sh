#! /bin/bash
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="dpkg"
LOGFILE="${extradir}/${SERVICE}.info"

###############################################################################
# DPKG Info (.deb debian packages)
###############################################################################
echo    "${hostname}: DPKG Info .........: ${LOGFILE}"

delimiter ${LOGFILE} "dpkg -l"
dpkg -l >> ${LOGFILE}  2>>${COLLECT_ERROR_LOG}

exit 0
