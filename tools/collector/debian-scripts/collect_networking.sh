#! /bin/bash
#
# Copyright (c) 2013-2026 Wind River Systems, Inc.
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
declare -a CMDS=("ip -s -d link"
"ip -4 -s -d addr"
"ip -6 -s -d addr"
"ip -4 -s neigh"
"ip -6 -s neigh"
"ip -4 rule"
"ip -6 rule"
"ip -4 route"
"ip -6 route"
"ip -4 maddr"
"ip -6 maddr"
"nstat -a"
"cat /proc/net/sockstat"
"sysctl -ar '^net\.'"
)

for CMD in "${CMDS[@]}" ; do
    delimiter ${LOGFILE} "${CMD}"
    eval "${CMD}" >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
done

run_command "ss -tuSnapeiO --cgroup" "${extradir}/ss.dump"

run_command "eval cat /proc/sys/net/netfilter/nf_conntrack_{count,max}" "${extradir}/conntrack.dump"
run_command "conntrack -L -o extended" "${extradir}/conntrack.dump"
run_command "conntrack -S" "${extradir}/conntrack.dump"

run_command "iptables-save -c" "${extradir}/iptables.dump"

run_command "nft list ruleset ip" "${extradir}/netfilter_list_ruleset.dump"

run_command "ip6tables-save -c" "${extradir}/ip6tables.dump"

run_command "nft list ruleset ip6" "${extradir}/netfilter6_list_ruleset.dump"

run_command "ipset save" "${extradir}/ipset.dump"

run_command "lldpctl" "${extradir}/lldpctl.dump"

bond_status () {
    if [ -d /proc/net/bonding/ ]; then
        for f in /proc/net/bonding/*; do
            echo "===> interface: $f";
            cat "$f";
        done;
    else
        echo "no bonding interfaces found"
    fi
}
CMD="bond_status"
delimiter ${LOGFILE} "cat /proc/net/bonding/*"
${CMD} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

sleep ${COLLECT_RUNCMD_DELAY}


## Commands for network namespaces

declare -a CMDS=("ip -s -d link"
"ip -4 -s -d addr"
"ip -6 -s -d addr"
"ip -4 -s neigh"
"ip -6 -s neigh"
"ip -4 rule"
"ip -6 rule"
"ip -4 route"
"ip -6 route"
"nstat -a"
)

# Create a list of network namespaces; exclude the (id: #) part
# Example: cni-56e3136b-2503-fe5f-652f-0998248c1405 (id: 0)
NAMESPACES=()
for ns in $(ip netns list | awk '{print $1}'); do
    NAMESPACES+=("$ns")
done

for NS in ${NAMESPACES[@]}; do
    delimiter "${LOGFILE}" "Network Namespace: ${NS}"
    delimiter "${extradir}/ss.dump" "Network Namespace: ${NS}"
    for CMD in "${CMDS[@]}" ; do
        run_command "ip netns exec ${NS} ${CMD}" "${LOGFILE}"
        run_command "ip netns exec ${NS} ss -tuSnlpO" "${extradir}/ss.dump"
    done
    sleep ${COLLECT_RUNCMD_DELAY}
done

exit 0
