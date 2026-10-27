#! /bin/bash
#
# Copyright (c) 2013-2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="inventory"
LOGFILE="${extradir}/${SERVICE}.info"
INVENTORY=${4}

# Inventory queries, as data. Timeout handling lives in run_inventory_cmd.
declare -a SYSTEM_CMDS=(
    "system show"
    "system datanetwork-list"
    "system service-list"
    "system network-list"
    "system network-addrpool-list"
    "system addrpool-list"
    # "vm-topology --show all"
)

# run once per host, with the hostname appended
declare -a SYSTEM_HOST_CMDS=(
    "system host-show"
    "system host-port-list"
    "system host-if-list"
    "system interface-network-list"
    "system host-ethernet-port-list"
    "system host-addr-list"
    "system host-route-list"
    "system host-cpu-list"
    "system host-memory-list"
    "system host-label-list"
    "system host-disk-list"
    "system host-stor-list"
    "system host-lvg-list"
    "system host-pv-list"
)

declare -i INVENTORY_FAILURES=0

###############################################################################
#
# Name:        run_inventory_cmd
#
# Purpose:     Run one inventory query and decide whether to keep going
#
# Description: Keeps whatever inventory the plugin managed to collect rather
#              than running past COLLECT_HOST_TIMEOUT, which would cost the
#              whole host bundle.
#
# Arguments:   $1 - the command to run, including any arguments
#
# Returns:     0 to continue ; 1 once the threshold is reached
#
###############################################################################

function run_inventory_cmd {
    run_platform_cmd "${1}" "${LOGFILE}"
    [ ${?} -ne ${FAIL_PLATFORM_CMD_TIMEOUT} ] && return 0

    INVENTORY_FAILURES=$((INVENTORY_FAILURES+1))
    if [ ${INVENTORY_FAILURES} -ge ${SYSTEM_CMD_FAILURE_THRESHOLD} ] ; then
        wlog "inventory collection stopped after ${INVENTORY_FAILURES} platform command timeouts"
        return 1
    fi
    return 0
}

function collect_inventory {
    echo    "${hostname}: System Inventory ..: ${LOGFILE}"

    local probe_output=""
    local probe_rc=0

    # assign separately from declaring, so that ${?} is the query's status
    # rather than the 'local' builtin's
    probe_output=$(timeout ${PLATFORM_CMD_TIMEOUT} system host-list --nowrap)
    probe_rc=${?}
    HOSTNAMES=$(echo "${probe_output}" | grep '[0-9]' | cut -d '|' -f 3 | tr -d ' ')
    if [ ${probe_rc} -eq ${FAIL_PLATFORM_CMD_TIMEOUT} ] ; then
        echo "Failed to get system host-list ; timed out after ${PLATFORM_CMD_TIMEOUT}s" > $LOGFILE
        wlog "inventory collection skipped ; 'system host-list' timed out after ${PLATFORM_CMD_TIMEOUT}s"
        return
    elif [[ -z "${HOSTNAMES}" || "${HOSTNAMES}" != *"controller"* ]];  then
        echo "No controllers found in the system host-list" > $LOGFILE
        return
    fi

    # the probe already fetched this, so log that copy
    delimiter ${LOGFILE} "system host-list"
    echo "${probe_output}" >> ${LOGFILE}

    # These go into the SERVICE.info file
    for cmd in "${SYSTEM_CMDS[@]}" ; do
        run_inventory_cmd "${cmd}" || return
    done

    for host in ${HOSTNAMES}; do
        for cmd in "${SYSTEM_HOST_CMDS[@]}" ; do
            run_inventory_cmd "${cmd} ${host}" || return
        done
    done
}

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then

    # The inventory queries describe the system rather than this host, so one
    # controller answers for all of them.
    if [ "${INVENTORY}" = true ] ; then
        is_active_controller
        if [ "${?}" = "1" ] ; then
            collect_inventory
        fi
    fi

    # copy /opt/platform to extra dir while filtering out the
    # iso and lost+found dirs
    rsync -a --exclude 'iso' --exclude 'lost+found' /opt/platform ${extradir}
fi


exit 0
