#! /bin/bash
#
# Copyright (c) 2013-2021 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="inventory"
LOGFILE="${extradir}/${SERVICE}.info"
RPMLOG="${extradir}/rpm.info"
INVENTORY=${4}

function is_service_active {
    active=`sm-query service management-ip | grep "enabled-active"`
    if [ -z "$active" ] ; then
        return 0
    else
        return 1
    fi
}

function collect_inventory {
    is_service_active
    if [ "$?" = "0" ] ; then
        exit 0
    fi
    echo    "${hostname}: System Inventory ..: ${LOGFILE}"

    HOSTNAMES=$(system host-list --nowrap | grep '[0-9]' | cut -d '|' -f 3 | tr -d ' ')
    if [[ -z ${HOSTNAMES} || ${HOSTNAMES} != *"controller"* ]];  then
        echo "Failed to get system host-list" > $LOGFILE
        exit 0
    fi

    # These go into the SERVICE.info file
    delimiter ${LOGFILE} "system show"
    system show 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "system host-list"
    system host-list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "system datanetwork-list"
    system datanetwork-list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "system service-list"
    system service-list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    # delimiter ${LOGFILE} "vm-topology"
    # timeout 60 vm-topology --show all 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "system network-list"
    system network-list 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    for host in ${HOSTNAMES}; do
        delimiter ${LOGFILE} "system host-show ${host}"
        system host-show 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-port-list ${host}"
        system host-port-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-if-list ${host}"
        system host-if-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system interface-network-list ${host}"
        system interface-network-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-ethernet-port-list ${host}"
        system host-ethernet-port-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-cpu-list ${host}"
        system host-cpu-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-memory-list ${host}"
        system host-memory-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-label-list ${host}"
        system host-label-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-disk-list ${host}"
        system host-disk-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-stor-list ${host}"
        system host-stor-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-lvg-list ${host}"
        system host-lvg-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

        delimiter ${LOGFILE} "system host-pv-list ${host}"
        system host-pv-list ${host} 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}
    done
}

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then

    echo    "${hostname}: Software Config ...: ${RPMLOG}"
    # These go into the SERVICE.info file
    delimiter ${RPMLOG} "rpm -qa"
    rpm -qa >> ${RPMLOG}

    if [ "${INVENTORY}" = true ] ; then
        collect_inventory
    fi

    # copy /opt/platform to extra dir while filtering out the
    # iso and lost+found dirs
    rsync -a --exclude 'iso' --exclude 'lost+found' /opt/platform ${extradir}
fi


exit 0
