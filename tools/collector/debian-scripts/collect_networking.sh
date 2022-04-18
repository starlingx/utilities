#! /bin/bash
#
# Copyright (c) 2013-2014 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="networking"
LOGFILE="${extradir}/${SERVICE}.info"
echo    "${hostname}: Networking Info ...: ${LOGFILE}"

###############################################################################
# All nodes
###############################################################################
declare -a CMDS=("ip -s link"
"ip -4 -s addr"
"ip -6 -s addr"
"ip -4 -s neigh"
"ip -6 -s neigh"
"ip -4 rule"
"ip -6 rule"
"ip -4 route"
"ip -6 route"
)

for CMD in "${CMDS[@]}" ; do
    delimiter ${LOGFILE} "${CMD}"
    ${CMD} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
done

CMD="iptables-save"
delimiter ${LOGFILE} "${CMD}"
${CMD} > ${extradir}/iptables.dump 2>>${COLLECT_ERROR_LOG}

CMD="ip6tables-save"
delimiter ${LOGFILE} "${CMD}"
${CMD} > ${extradir}/ip6tables.dump 2>>${COLLECT_ERROR_LOG}

###############################################################################
# Only Worker
###############################################################################
if [[ "$nodetype" = "worker" || "$subfunction" == *"worker"* ]] ; then
    NAMESPACES=($(ip netns))
    for NS in ${NAMESPACES[@]}; do
        delimiter ${LOGFILE} "${NS}"
        for CMD in "${CMDS[@]}" ; do
            ip netns exec ${NS} ${CMD}
        done
    done >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
fi

exit 0
