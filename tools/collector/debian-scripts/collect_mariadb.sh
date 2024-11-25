#! /bin/bash
#
# Copyright (c) 2020,2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Gather containerized MariaDB information from active controller.

# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="mariadb"
DB_DIR="${extradir}/${SERVICE}"
LOGFILE="${extradir}/${SERVICE}.info"
echo "${hostname}: MariaDB Info .....: ${LOGFILE}"

function is_service_active {
    active=$(sm-query service postgres | grep "enabled-active")
    if [ -z "${active}" ] ; then
        return 0
    else
        return 1
    fi
}

if [ "${nodetype}" = "controller" ] ; then
    is_service_active
    if [ "$?" = "0" ] ; then
        exit 0
    fi

    # MariaDB databases
    delimiter ${LOGFILE} "MariaDB databases:"
    mariadb-cli --command 'show databases' >> ${LOGFILE}

    # MariaDB database sizes
    delimiter ${LOGFILE} "MariaDB database sizes:"
    mariadb-cli --command '
SELECT table_schema AS "database",
    ROUND(SUM(DATA_LENGTH + INDEX_LENGTH)/1024/1024, 3) AS "Size (MiB)",
    SUM(TABLE_ROWS) AS "rowCount"
FROM information_schema.TABLES
GROUP BY table_schema' >> ${LOGFILE}

    delimiter ${LOGFILE} "MariaDB database table sizes:"
    mariadb-cli --command '
SELECT
    table_schema AS "database", TABLE_NAME AS "table",
    ROUND((DATA_LENGTH + INDEX_LENGTH)/1024/1024, 6) AS "Size (MiB)",
    TABLE_ROWS AS "rowCount"
FROM information_schema.TABLES
ORDER BY table_schema, TABLE_NAME' >> ${LOGFILE}

    sleep ${COLLECT_RUNCMD_DELAY}

    # MariaDB dump all databases
    delimiter ${LOGFILE} "Dumping MariaDB databases: ${DB_DIR}"
    mkdir -p ${DB_DIR}
    (cd ${DB_DIR}; mariadb-cli --dump --exclude keystone,ceilometer)

    sleep ${COLLECT_RUNCMD_DELAY}
fi

exit 0
