#!/bin/bash

# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# This script is wrapper to containerized mariadb-server mysql client.
# This provides access to MariaDB databases.
#
# There are three modes of operation:
# - no command specified gives an interactive mysql shell
# - command specified executes a single mysql command
# - dump option to dump database contents to sql text file
#
set -euo pipefail

# Define minimal path
PATH=/bin:/usr/bin:/usr/local/bin

# Environment for kubectl
export KUBECONFIG=/etc/kubernetes/admin.conf

# Process input options
SCRIPT=$(basename $0)
OPTS=$(getopt -o dh --long debug,help,command:,database:,exclude:,dump -n ${SCRIPT} -- "$@")
if [ $? != 0 ]; then
    echo "Failed parsing options." >&2
    exit 1
fi
eval set -- "$OPTS"

DEBUG=false
HELP=false
DUMP=false
COMMAND=""
DATABASE=""
EXCLUDE=""
while true
do
    case "$1" in
        -d | --debug ) DEBUG=true; shift ;;
        -h | --help )  HELP=true; shift ;;
        --command )
            COMMAND="$2"
            shift 2
            ;;
        --database )
            DATABASE="$2"
            shift 2
            ;;
        --exclude )
            EXCLUDE="$2"
            shift 2
            ;;
        --dump )
            DUMP=true
            shift
            ;;
        -- )
            shift
            break
            ;;
        * )
            break
            ;;
    esac
done

# Treat remaining arguments as commands + options
shift $((OPTIND-1))
OTHERARGS="$@"

if [ ${HELP} == 'true' ]; then
    echo "Usage: ${SCRIPT} [-d|--debug] [-h|--help] [--database <db>] [--exclude <db,...>] [--command <cmd>] [--dump]"
    echo "Options:"
    echo " -d | --debug : display debug information"
    echo " -h | --help  : this help"
    echo " --database <db>     : connect to database db"
    echo " --exclude <db1,...> : list of databases to exclude"
    echo " --command <cmd>     : execute mysql command cmd"
    echo " --dump              : dump database(s) to sql file in current directory"
    echo
    echo "Command option examples:"
    echo
    echo "Interactive mysql shell:"
    echo " mariadb-cli"
    echo " mariadb-cli --database nova"
    echo " mariadb-cli --command 'show_databases'"
    echo " mariadb-cli --database nova --command 'select * from compute_nodes'"
    echo
    echo "Dump MariaDB databases to sql file:"
    echo " mariadb-cli --dump"
    echo " mariadb-cli --dump --database nova"
    echo " mariadb-cli --dump --exclude keystone"
    exit 0
fi


# Logger setup
LOG_FACILITY=user
LOG_PRIORITY=info
function LOG {
    logger -t "${0##*/}[$$]" -p ${LOG_FACILITY}.${LOG_PRIORITY} "$@"
    echo "${0##*/}[$$]" "$@"
}
function ERROR {
    MSG="ERROR"
    LOG "${MSG} $@"
}

function is_openstack_node {
    local PASS=0
    local FAIL=1
    # NOTE: hostname changes during first configuration
    local this_node=$(cat /proc/sys/kernel/hostname)

    labels=$(kubectl get node ${this_node} \
            --no-headers --show-labels 2>/dev/null | awk '{print $NF}')
    if [[ $labels =~ openstack-control-plane=enabled ]]; then
        return ${PASS}
    else
        return ${FAIL}
    fi
}

# Selected options
if [ ${DEBUG} == 'true' ]; then
    LOG "Options: DUMP=${DUMP} OTHERARGS: ${OTHERARGS}"
    if [ ! -z "${DATABASE}" ]; then
        LOG "Options: DATABASE:${DATABASE}"
    fi
    if [ ! -z "${EXCLUDE}" ]; then
        LOG "Options: EXCLUDE:${EXCLUDE}"
    fi
    if [ ! -z "${COMMAND}" ]; then
        LOG "Options: COMMAND:${COMMAND}"
    fi
fi

# Check for openstack label on this node
if ! is_openstack_node; then
    ERROR "This node not configured for openstack."
    exit 1
fi

# Determine running mariadb pods
MARIADB_PODS=( $(kubectl get pods -n openstack \
                --selector=application=mariadb,component=server \
                --field-selector status.phase=Running \
                --output=jsonpath={.items..metadata.name}) )
if [ ${DEBUG} == 'true' ]; then
    LOG "Found mariadb-server pods: ${MARIADB_PODS[@]}"
fi

# Get first available mariadb pod with container we can exec
DBPOD=""
for POD in "${MARIADB_PODS[@]}"
do
    kubectl exec -it -n openstack ${POD} -c mariadb -- pwd 1>/dev/null 2>/dev/null
    RC=$?
    if [ ${RC} -eq 0 ]; then
        DBPOD=${POD}
        break
    fi
done
if [ -z "${DBPOD}" ]; then
    ERROR "Could not find mariadb-server pod."
    exit 1
fi
if [ ${DEBUG} == 'true' ]; then
    LOG "Found mariadb-server pod: ${DBPOD}"
fi

EVAL='eval env 1>/dev/null'
DBOPTS='--password=$MYSQL_DBADMIN_PASSWORD --user=$MYSQL_DBADMIN_USERNAME'

if [ ${DUMP} == 'true' ]; then
    # Dump database contents to sql text file
    DB_EXT=sql

    DATABASES=()
    if [ ! -z "${DATABASE}" ]; then
        DATABASES+=( $DATABASE )
    else
        # Get list of databases
        MYSQL_CMD="${EVAL}; mysql ${DBOPTS} -e 'show databases' -sN --disable-pager"
        if [ ${DEBUG} == 'true' ]; then
            LOG "MYSQL_CMD: ${MYSQL_CMD}"
        fi

        # Suppress error: line from stdout, eg.,
        # error: Found option without preceding group in config file: /etc/mysql/conf.d/20-override.cnf at line: 1
        # Exclude databases: mysql, information_schema, performance_schema
        # Remove linefeed control character. 
        DATABASES=( $(kubectl exec -it -n openstack ${DBPOD} -c mariadb -- bash -c "${MYSQL_CMD}" | \
                        grep -v -e error: -e mysql -e information_schema -e performance_schema | tr -d '\r') )
    fi

    for dbname in "${DATABASES[@]}"
    do
        re=\\b"${dbname}"\\b
        if [[ "${EXCLUDE}" =~ ${re} ]]; then
            LOG "excluding: ${dbname}"
            continue
        fi

        # NOTE: --skip-opt will show an INSERT for each record
        DUMP_CMD="${EVAL}; mysqldump ${DBOPTS} --skip-opt --skip-comments --skip-set-charset ${dbname}"
        dbfile=${dbname}.${DB_EXT}
        LOG "Dump database: $dbname to file: ${dbfile}"
        if [ ${DEBUG} == 'true' ]; then
            LOG "DUMP_CMD: ${DUMP_CMD}"
        fi
        kubectl exec -it -n openstack ${DBPOD} -c mariadb -- bash -c "${DUMP_CMD}" > ${dbfile}
    done

else
    # Interactive mariadb mysql client
    LOG "Interactive MariaDB mysql shell"
    MYSQL_CMD="${EVAL}; mysql ${DBOPTS} ${DATABASE}"
    if [ ! -z "${COMMAND}" ]; then
        MYSQL_CMD="${MYSQL_CMD} -e '${COMMAND}'"
    fi

    if [ ${DEBUG} == 'true' ]; then
        LOG "MYSQL_CMD: ${MYSQL_CMD}"
    fi
    kubectl exec -it -n openstack ${DBPOD} -c mariadb -- bash -c "${MYSQL_CMD}"
fi

exit 0
