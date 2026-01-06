#! /bin/bash
#
# Copyright (c) 2016-2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="crash"
LOGFILE="${extradir}/${SERVICE}.info"


CRASHDIR="/var/crash"

echo    "${hostname}: Kernel Crash Info .: ${LOGFILE}"
if [ -n "$(ls -A ${CRASHDIR} 2>/dev/null)" ]; then
    COMMAND="find ${CRASHDIR}"
    delimiter ${LOGFILE} "${COMMAND}"
    ${COMMAND} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    COMMAND="rsync -a  --include=*/ --include=*  ${CRASHDIR} ${basedir}/var/"
    delimiter ${LOGFILE} "${COMMAND}"
    ${COMMAND} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    COMMAND="ls -lrtd ${CRASHDIR}/*"
    delimiter ${LOGFILE} "${COMMAND}"
    ${COMMAND} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    COMMAND="md5sum ${CRASHDIR}/*"
    delimiter ${LOGFILE} "${COMMAND}"
    ${COMMAND} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
else
    echo "${CRASHDIR} is empty." >> ${LOGFILE}
fi

exit 0
