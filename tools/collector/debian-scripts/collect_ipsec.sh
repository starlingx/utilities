#! /bin/bash
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="ipsec"
LOGFILE="${extradir}/${SERVICE}.info"
echo    "${hostname}: IPSec Info ........: ${LOGFILE}"

###############################################################################
# All nodes
###############################################################################
declare -a CMDS=("swanctl --list-conn"
"swanctl --list-sa"
"ip -s xfrm policy"
"ip -s xfrm state"
)

for CMD in "${CMDS[@]}" ; do
    delimiter ${LOGFILE} "${CMD}"
    ${CMD} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
done

exit 0
