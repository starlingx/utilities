#! /bin/bash
#
# Copyright (c) 2013-2014,2024 Wind River Systems, Inc.
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

sleep ${COLLECT_RUNCMD_DELAY}

###############################################################################
# Only Worker
###############################################################################
if [[ "$nodetype" = "worker" || "$subfunction" == *"worker"* ]] ; then
    # Create a list of network namespaces; exclude the (id: #) part
    # Example: cni-56e3136b-2503-fe5f-652f-0998248c1405 (id: 0)
    NAMESPACES=()
    for ns in $(ip netns list | awk '{print $1}'); do
        NAMESPACES+=("$ns")
    done
    for NS in ${NAMESPACES[@]}; do
        delimiter "${LOGFILE}" "Network Namespace: ${NS}"
        for CMD in "${CMDS[@]}" ; do
            run_command "ip netns exec ${NS} ${CMD}" "${LOGFILE}"
        done
        sleep ${COLLECT_RUNCMD_DELAY}
    done
fi
exit 0
