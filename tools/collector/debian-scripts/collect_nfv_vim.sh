#! /bin/bash
#
# Copyright (c) 2013-2016,2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

LOGFILE="${extradir}/nfv-vim.info"
echo    "${hostname}: NFV-Vim Info ......: ${LOGFILE}"

function is_service_active {
    active=`sm-query service vim | grep "enabled-active"`
    if [ -z "$active" ] ; then
        return 0
    else
        return 1
    fi
}

function get_current_strategy_details {
    snippet=$(cat <<END
import os
import sys

from nfv_client.sw_update._sw_update import _display_strategy
from nfv_client.openstack import openstack
from nfv_client.openstack import sw_update

os_auth_url = os.environ.get('OS_AUTH_URL', None)
os_project_name = os.environ.get('OS_PROJECT_NAME', None)
os_project_domain_name = os.environ.get('OS_PROJECT_DOMAIN_NAME', 'Default')
os_username = os.environ.get('OS_USERNAME', None)
os_password = os.environ.get('OS_PASSWORD', None)
os_user_domain_name = os.environ.get('OS_USER_DOMAIN_NAME', None)
os_region_name = os.environ.get('OS_REGION_NAME', None)
os_interface = os.environ.get('OS_INTERFACE', None)

token = openstack.get_token(os_auth_url, os_project_name,os_project_domain_name, os_username, os_password, os_user_domain_name)
url = token.get_service_url(os_region_name, openstack.SERVICE.VIM,openstack.SERVICE_TYPE.NFV, os_interface)

result = sw_update.get_current_strategy(token.get_id(), url, os_username, os_user_domain_name, os_username)
if not result:
    sys.exit(1)

current = list(result.keys())[0]
details = sw_update.get_strategies(token.get_id(), url, current, os_username, os_user_domain_name, os_username)
_display_strategy(details, details=True, error_details=True)
END
)

    timeout 30 python3 -c "${snippet}"
}

###############################################################################
# Only Controller
###############################################################################

if [ "$nodetype" = "controller" ] ; then
    is_service_active
    if [ "$?" = "0" ] ; then
        exit 0
    fi

    # Assumes that database_dir is unique in /etc/nfv/vim/config.ini
    DATABASE_DIR=$(awk -F "=" '/database_dir/ {print $2}' /etc/nfv/vim/config.ini)

    SQLITE_DUMP="/usr/bin/sqlite3 ${DATABASE_DIR}/vim_db_v1 .dump"

    delimiter ${LOGFILE} "dump database"
    timeout 30 ${SQLITE_DUMP} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

    delimiter ${LOGFILE} "get current strategy details"
    get_current_strategy_details >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
fi

exit 0

