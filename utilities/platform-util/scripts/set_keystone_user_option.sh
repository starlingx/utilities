#!/bin/bash

################################################################################
# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################

#
# This script can be used to set keystone user options such as
# 'ignore_lockout_failure_attempts'.
#
# $1 - admin username
# $2 - admin password
# $3 - identity auth url
# $4 - username to set the option for
# $5 - the user option to set
# $6 - the value of the option to set to
#

if [ $# != 6 ]; then
    echo "The format of the command: $0 admin_username admin_password auth_url user_name option option_value"
    exit 1
fi

admin_username=$1
admin_password=$2
auth_url=$3

user_name=$4
option=$5
option_value=$6

token=$(openstack \
        --os-username ${admin_username} \
        --os-user-domain-name Default \
        --os-project-name admin \
        --os-project-domain-name Default \
        --os-password ${admin_password} \
        --os-auth-url ${auth_url} \
        token issue -c id -f value)
if [ $? -ne 0 ]; then
    echo "Get admin token failed."
    exit 1
fi

user_id=$(openstack \
        --os-auth-type token \
        --os-token ${token} \
        --os-project-name admin \
        --os-project-domain-name Default \
        --os-auth-url ${auth_url} \
        user show ${user_name} -c id -f value)
if [ $? -ne 0 ]; then
    echo "Get user id for user \"${user_name}\" failed."
    exit 1
fi

req_url="${auth_url}/users/${user_id}"
data_json="{\"user\": {\"options\": {\"${option}\": ${option_value}}}}"

/usr/bin/curl -X PATCH -H "X-Auth-Token: ${token}" \
    -H "Content-Type: application/json" -d "${data_json}" "${req_url}"

