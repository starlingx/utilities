#!/bin/bash
#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# This script automates deploy plug-in update to
# 1. run ansible playbook to upgrade static images
#    - pull image from configured source
#    - push image to local registry
# 2. run ansible playbook to refresh deploy plug-in
#

export KUBECONFIG=/etc/kubernetes/admin.conf

UPGRADE_STATIC_IMAGE_PLAYBOOK=/usr/share/ansible/stx-ansible/playbooks/upgrade-static-images.yml

DEPLOY_OVERRIDES=$1
DEPLOY_CHART=$2
DEPLOY_PLAYBOOK=$3

# This will log to /var/log/platform.log
function log {
    logger -p local1.info $1
}

# Step-1
log "Run upgrade-static-images playbook to pull image from remote registry & push to local registry"
K8S_VERSION=$(kubectl get nodes|tail -1|awk '{print $5}')
ansible-playbook -e "kubernetes_version=${K8S_VERSION}" $UPGRADE_STATIC_IMAGE_PLAYBOOK
RC=$?
if [ $RC -eq 0 ]; then
    log "The upgrade static image playbook was executed successfully"
else
    log "The upgrade static image playbook failed with error: $RC"
    exit $RC
fi

# Step-2
log "Run ansible playbook to refresh deploy plug-in"
ansible-playbook -e "deployment_manager_overrides=$DEPLOY_OVERRIDES deployment_manager_chart=$DEPLOY_CHART" $DEPLOY_PLAYBOOK
RC=$?
if [ $RC -eq 0 ]; then
    log "The deployment playbook was executed successfully"
else
    log "The deployment playbook failed with error: $RC"
    exit $RC
fi

exit 0
