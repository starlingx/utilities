#! /bin/bash
#
# Copyright (c) 2013-2019,2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables
source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

# Environment for kubectl
export KUBECONFIG=/etc/kubernetes/admin.conf

SERVICE="openstack"
LOGFILE="${extradir}/${SERVICE}.info"
echo "${hostname}: Openstack Info ....: ${LOGFILE}"

function is_service_active {
    active=$(sm-query service rabbit-fs | grep "enabled-active")
    if [ -z "${active}" ] ; then
        return 0
    else
        return 1
    fi
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

function openstack_credentials {
    # Setup openstack admin tenant credentials using environment variables
    unset OS_SERVICE_TOKEN
    export OS_ENDPOINT_TYPE=internalURL
    export CINDER_ENDPOINT_TYPE=internalURL
    export OS_USERNAME=admin
    export OS_PASSWORD=$(TERM=linux /opt/platform/.keyring/*/.CREDENTIAL 2>/dev/null)
    export OS_AUTH_TYPE=password
    export OS_AUTH_URL=http://keystone.openstack.svc.cluster.local/v3
    export OS_PROJECT_NAME=admin
    export OS_USER_DOMAIN_NAME=Default
    export OS_PROJECT_DOMAIN_NAME=Default
    export OS_IDENTITY_API_VERSION=3
    export OS_REGION_NAME=RegionOne
    export OS_INTERFACE=internal
}

function openstack_commands {
    declare -a CMDS=()
    CMDS+=("openstack project list --long")
    CMDS+=("openstack user list --long")
    CMDS+=("openstack service list --long")
    CMDS+=("openstack router list --long")
    CMDS+=("openstack network list --long")
    CMDS+=("openstack subnet list --long")
    CMDS+=("openstack image list --long")
    CMDS+=("openstack volume list --all-projects --long")
    CMDS+=("openstack availability zone list --long")
    CMDS+=("openstack server group list --all-projects --long")
    CMDS+=('openstack server list --all-projects --long -c ID -c Name -c Status -c "Task State" -c  "Power State" -c Networks -c "Image Name" -c "Image ID" -c "Flavor Name" -c "Flavor ID" -c "Availability Zone" -c Host -c Properties')
    CMDS+=("openstack stack list --long --all-projects")
    CMDS+=("openstack security group list --all-projects")
    CMDS+=("openstack security group rule list --all-projects --long")
    CMDS+=("openstack keypair list")
    CMDS+=("openstack configuration show")
    CMDS+=("openstack quota list --compute")
    CMDS+=("openstack quota list --volume")
    CMDS+=("openstack quota list --network")
    CMDS+=("openstack host list")
    CMDS+=("openstack hypervisor list --long")
    CMDS+=("openstack hypervisor stats show")
    HOSTS=( $(openstack hypervisor list -f value -c "Hypervisor Hostname" 2>/dev/null) )
    for host in "${HOSTS[@]}" ; do
        CMDS+=("openstack hypervisor show -f yaml ${host}")
    done

    # nova commands
    CMDS+=("nova service-list")

    DELAY_THROTTLE=4
    delay_count=0
    for CMD in "${CMDS[@]}" ; do
        delimiter ${LOGFILE} "${CMD}"
        eval ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE}
        echo >>${LOGFILE}

        if [ ! -z ${COLLECT_RUNCMD_DELAY} ] ; then
            ((delay_count = delay_count + 1))
            if [ ${delay_count} -ge ${DELAY_THROTTLE} ] ; then
                sleep ${COLLECT_RUNCMD_DELAY}
                delay_count=0
            fi
        fi
    done
}

function rabbitmq_usage_stats {
    # RabbitMQ usage stats
    MQ_STATUS="rabbitmqctl status"
    delimiter ${LOGFILE} "${MQ_STATUS} | grep -e '{memory' -A30"
    ${MQ_STATUS} 2>/dev/null | grep -e '{memory' -A30 >> ${LOGFILE}
    echo >>${LOGFILE}

    delimiter ${LOGFILE} "RabbitMQ Queue Info"
    num_queues=$(rabbitmqctl list_queues | wc -l); ((num_queues-=2))
    num_bindings=$(rabbitmqctl list_bindings | wc -l); ((num_bindings-=2))
    num_exchanges=$(rabbitmqctl list_exchanges | wc -l); ((num_exchanges-=2))
    num_connections=$(rabbitmqctl list_connections | wc -l); ((num_connections-=2))
    num_channels=$(rabbitmqctl list_channels | wc -l); ((num_channels-=2))
    arr=($(rabbitmqctl list_queues messages consumers memory | \
        awk '/^[0-9]/ {a+=$1; b+=$2; c+=$3} END {print a, b, c}'))
    messages=${arr[0]}; consumers=${arr[1]}; memory=${arr[2]}
    printf "%6s %8s %9s %11s %8s %8s %9s %10s\n" "queues" "bindings" "exchanges" "connections" "channels" "messages" "consumers" "memory" >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
    printf "%6d %8d %9d %11d %8d %8d %9d %10d\n" $num_queues $num_bindings $num_exchanges $num_connections $num_channels $messages $consumers $memory >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}
}

###############################################################################
# Only Controller
###############################################################################
if [ "$nodetype" = "controller" ] ; then

    is_service_active
    if [ "$?" = "0" ] ; then
        exit 0
    fi

    # host rabbitmq usage
    rabbitmq_usage_stats

    sleep ${COLLECT_RUNCMD_DELAY}

    # Check for openstack label on this node
    if ! is_openstack_node; then
        exit 0
    fi

    # Run as subshell so we don't contaminate environment
    (openstack_credentials; openstack_commands)

    sleep ${COLLECT_RUNCMD_DELAY}

    # TODO(jgauld): Should also get containerized rabbitmq usage,
    # need wrapper script rabbitmq-cli
fi

###############################################################################
# collect does not retrieve /etc/keystone dir
# Additional logic included to copy /etc/keystone directory
###############################################################################

mkdir -p  ${extradir}/../../etc/
cp -R /etc/keystone/ ${extradir}/../../etc
chmod -R 755 ${extradir}/../../etc/keystone

exit 0
