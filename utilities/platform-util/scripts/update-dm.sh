#!/bin/bash
#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# This script automates deploy plug-in update to
# 1. run ansible playbook to refresh dm images if specified
#    - pull image from configured source
#    - push image to local registry
# 2. run ansible playbook to refresh deploy plug-in

NAME=$(basename $0)
export KUBECONFIG=/etc/kubernetes/admin.conf

UPGRADE_STATIC_IMAGE_PLAYBOOK=/usr/share/ansible/stx-ansible/playbooks/upgrade-static-images.yml

DEPLOY_PLAYBOOK=$1
DEPLOY_CHART=$2
DEPLOY_OVERRIDES=$3
REFRESH_DM_IMAGES=$4

# This will log to /var/log/platform.log
function log {
    logger -p local1.info $1
}

if [[ "${REFRESH_DM_IMAGES}" == "true" ]]; then
    log "Run upgrade-static-images playbook to add the latest version of platform images to the local registry."
    K8S_VERSION=$(kubectl get nodes|tail -1|awk '{print $5}')
    ansible-playbook -e "kubernetes_version=${K8S_VERSION}" ${UPGRADE_STATIC_IMAGE_PLAYBOOK}
    RC=$?
    if [ $RC -eq 0 ]; then
        log "$NAME: The upgrade-static-images playbook was executed successfully"
    else
        log "$NAME: The upgrade-static-images playbook failed with error: $RC"
        exit $RC
    fi
fi

log "Run ansible playbook to refresh deploy plug-in"
ansible-playbook -e "deployment_manager_overrides=${DEPLOY_OVERRIDES} deployment_manager_chart=${DEPLOY_CHART}" ${DEPLOY_PLAYBOOK}
RC=$?
if [ $RC -eq 0 ]; then
    log "$NAME: The deploy plug-in was refreshed successfully."
else
    log "$NAME: The deploy plug-in refresh failed with error: $RC"
    exit $RC
fi

exit 0
