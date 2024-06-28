#! /bin/bash
#
# Copyright (c) 2020-2022 Wind River Systems, Inc.
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
        # Prints the column names of the table
        system addrpool-list --nowrap | head -3 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}
        # Prints the System Controller's address pool
        system addrpool-list --nowrap | grep "system-controller-subnet" 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    else
        # System Controller
        echo "Distributed Cloud Role: System Controller" >> ${LOGFILE}

        delimiter ${LOGFILE} "dcmanager alarm summary"
        dcmanager alarm summary 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "dcmanager subcloud list"
        dcmanager subcloud list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "dcmanager subcloud-group list"
        dcmanager subcloud-group list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        # copy the /opt/dc/ansible dir but exclude any iso files
        rsync -a --exclude '*.iso' /opt/dc/ansible ${extradir}

        delimiter ${LOGFILE} "find /opt/dc-vault -ls"
        find /opt/dc-vault -ls 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    fi

fi

exit 0
