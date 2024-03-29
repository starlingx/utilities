#! /bin/bash
#
# Copyright (c) 2013-2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="patching"
LOGFILE="${extradir}/${SERVICE}.info"
echo    "${hostname}: Patching Info .....: ${LOGFILE}"

###############################################################################
# All nodes
###############################################################################

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then

    delimiter ${LOGFILE} "sw-patch query"
    sw-patch query 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "sw-patch query-hosts"
    sw-patch query-hosts 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "sw-patch query-hosts --debug"
    sw-patch query-hosts --debug  2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    delimiter ${LOGFILE} "find /opt/patching"
    find /opt/patching 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}

    # todo(abailey): Verify that we can remove the next 2 lines
    delimiter ${LOGFILE} "find /var/www/pages/updates"
    find /var/www/pages/updates 2>>${COLLECT_ERROR_LOG} >> ${LOGFILE}
fi

exit 0
