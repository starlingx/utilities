#!/bin/bash
#
# Copyright (c) 2021-2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Utility script to reconfigure system private registry
#

#
# It is assumed that the system private registry URLs are in the same level.
# Example: URLs "myregistry.sample.com/docker.io" and "myregistry.sample.com/docker.elastic.co"
# have the same base URL "myregistry.sample.com", so they are in the same level.
# In a distributed cloud environment, this script only needs to be run on the central cloud.
# It can have 2 or 4 parameters, because the pair username and password is optional.
# When the username and password parameters are not given, they are set to empty strings.
# The default value for docker registry is "docker".
#
# $1 - registry base url
# $2 - registry type
# $3 - registry username (optional)
# $4 - registry password (optional)
#
# This script manipulates the parameters 'url', 'type' and 'auth-secret'
# of docker service.Each one of these three parameters may exist inside
# the docker service sections docker-registry, elastic-registry,
# gcr-registry, ghcr-registry, k8s-registry, quay-registry,
# registryk8s-registry and icr.io so 24 parameters are manipulated in
# total.Each section of service docker is referred also as registry in
# this script.

if (( $# != 2 && $# != 4 )); then
    echo "The format of the command: $0 registry_base_url registry_type [registry_username] [registry_password]"
    exit 1
fi

REGISTRY_BASE_URL=$1
REGISTRY_TYPE=$2
if (( $# == 4 )); then
    REGISTRY_USERNAME=$3
    REGISTRY_PASSWORD=$4
else
    REGISTRY_USERNAME=''
    REGISTRY_PASSWORD=''
fi
NEW_REGISTRY_USER_PASSWORD="username:${REGISTRY_USERNAME} password:${REGISTRY_PASSWORD}"

# This is a dictionary between registries (key) and the final part of their URL (value).
declare -A REGISTRY_DICT
REGISTRY_DICT['docker-registry']='docker.io'
REGISTRY_DICT['elastic-registry']='docker.elastic.co'
REGISTRY_DICT['gcr-registry']='gcr.io'
REGISTRY_DICT['ghcr-registry']='ghcr.io'
REGISTRY_DICT['k8s-registry']='k8s.gcr.io'
REGISTRY_DICT['quay-registry']='quay.io'
REGISTRY_DICT['registryk8s-registry']='registry.k8s.io'
REGISTRY_DICT['icr-registry']='icr.io'

source /etc/platform/openrc

# Create or modify url parameter of registries.
for registry in "${!REGISTRY_DICT[@]}"; do

    # Launchpad bug 1948839: the command "system service-parameter-list", when both "--section" and "--name" filters are
    # given, ignores "--section" and uses only "--name". The correct behavior would be to use both. This is why the
    # parameter "--name" is not present below and "grep -w" is used.
    parameter_name_list=`system service-parameter-list  --service docker \
                                                        --section ${registry} \
                                                        --column name \
                                                        --format value`
    parameter_present=`echo ${parameter_name_list} | grep -w url`
    if [[ -z "${parameter_present}" ]]; then
        echo "The url parameter of ${registry} does not exist. Creating parameter..."
        system service-parameter-add docker ${registry} url=${REGISTRY_BASE_URL}/${REGISTRY_DICT[${registry}]}
    else
        echo "The url parameter of ${registry} already exists. Changing its value..."
        system service-parameter-modify docker ${registry} url=${REGISTRY_BASE_URL}/${REGISTRY_DICT[${registry}]}
    fi
    echo ""

done

# Create or modify type parameter of registries.
for registry in "${!REGISTRY_DICT[@]}"; do

    # See the description of Launchpad bug 1948839, it also affects the implementation below.
    parameter_name_list=`system service-parameter-list  --service docker \
                                                        --section ${registry} \
                                                        --column name \
                                                        --format value`
    parameter_present=`echo ${parameter_name_list} | grep -w type`
    if [[ -z "${parameter_present}" ]]; then
        echo "The type parameter of ${registry} does not exist. Creating parameter..."
        system service-parameter-add docker ${registry} type=${REGISTRY_TYPE}
    else
        echo "The type parameter of ${registry} already exists. Changing its value..."
        system service-parameter-modify docker ${registry} type=${REGISTRY_TYPE}
    fi
    echo ""

done

# Change registry credentials: delete and recreate secret in Barbican, then creates or modifies the reference in
# auth-secret parameter.
for registry in "${!REGISTRY_DICT[@]}"; do

    # Note: the command "openstack secret list -n ${registry}-secret -c 'Secret href'", when it doesn't find the
    # secret name "${registry}-secret", prints to stderr an error about not finding the column "Secret href" in the
    # resulting empty table. To avoid informing the user about this error, stderr is redirected to '/dev/null'.
    old_secret_uri=`openstack secret list -n ${registry}-secret -c 'Secret href' -f value 2>/dev/null`
    if [[ -n "${old_secret_uri}" ]]; then
        echo "Deleting secret ref ${old_secret_uri}"
        openstack secret delete ${old_secret_uri}
    fi
    openstack secret store -n ${registry}-secret -p "${NEW_REGISTRY_USER_PASSWORD}"
    new_secret_uri=`openstack secret list -n ${registry}-secret -c 'Secret href' -f value 2>/dev/null`
    new_secret_uuid=`echo ${new_secret_uri} | awk -F '/' '{print $NF}'`

    # See the description of Launchpad bug 1948839, it also affects the implementation below.
    parameter_name_list=`system service-parameter-list  --service docker \
                                                        --section ${registry} \
                                                        --column name \
                                                        --format value`
    parameter_present=`echo ${parameter_name_list} | grep -w auth-secret`
    if [[ -z "${parameter_present}" ]]; then
        echo "The auth-secret parameter of ${registry} does not exist. Creating parameter..."
        system service-parameter-add docker ${registry} auth-secret=${new_secret_uuid}
    else
        echo "The auth-secret parameter of ${registry} already exists. Changing its value..."
        system service-parameter-modify docker ${registry} auth-secret=${new_secret_uuid}
    fi
    echo ""

done

# Apply parameters and return.
system service-parameter-apply docker
echo "Service parameters of docker service were successfully reconfigured."
exit 0
