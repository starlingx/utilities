#! /bin/bash
#
# Copyright (c) 2020-2022,2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="distributed_cloud"
LOGFILE="${extradir}/${SERVICE}.info"

function is_distributed_cloud_env {
    distributed_cloud=`sm-query service-group distributed-cloud-services | grep "active"`
    if [ -z "$distributed_cloud" ] ; then
        return 0
    else
        return 1
    fi
}

function is_subcloud {
    subcloud=`cat /etc/platform/platform.conf | grep "distributed_cloud_role" | grep "subcloud"`
    if [ -z "$subcloud" ] ; then
        return 0
    else
        return 1
    fi
}

# Must be a distributed cloud environment
is_distributed_cloud_env
if [ "$?" = "0" ] ; then
    exit 0
fi

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then

    # Must be an active controller
    is_active_controller
    if [ "$?" = "0" ] ; then
        exit 0
    fi

    echo "${hostname}: Distributed Cloud ..: ${LOGFILE}"

    is_subcloud
    if [ "$?" = "1" ] ; then
        # Subcloud
        echo "Distributed Cloud Role: Subcloud" >> ${LOGFILE}

        delimiter ${LOGFILE} "Address Pool of System Controller"
        # Only the system controller's subnet is wanted from this table, so
        # query once into a variable and filter the captured output.
        addrpool=$(timeout ${PLATFORM_CMD_TIMEOUT} system addrpool-list --nowrap 2>>${COLLECT_ERROR_LOG})
        if [ ${?} -eq ${FAIL_PLATFORM_CMD_TIMEOUT} ] ; then
            echo "Command timed out after ${PLATFORM_CMD_TIMEOUT}s: system addrpool-list --nowrap" >> ${LOGFILE}
            wlog "'system addrpool-list' timed out after ${PLATFORM_CMD_TIMEOUT}s"
        else
            # Prints the column names of the table
            echo "${addrpool}" | head -3 >> ${LOGFILE}
            # Prints the System Controller's address pool
            echo "${addrpool}" | grep "system-controller-subnet" >> ${LOGFILE}
        fi

    else
        # System Controller
        echo "Distributed Cloud Role: System Controller" >> ${LOGFILE}

        run_platform_cmd "dcmanager alarm summary" "${LOGFILE}"

        run_platform_cmd "dcmanager subcloud list" "${LOGFILE}"

        run_platform_cmd "dcmanager subcloud-group list" "${LOGFILE}"

        # copy the /opt/dc/ansible dir but exclude any iso files
        rsync -a --exclude '*.iso' /opt/dc/ansible ${extradir}

        delimiter ${LOGFILE} "find /opt/dc-vault -ls"
        find /opt/dc-vault -ls 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    fi

fi

exit 0
