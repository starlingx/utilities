#!/bin/bash
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# script to apply k8s configs for api-server CIS compiance
#
source /etc/platform/openrc

# Function to check if the kube-apiserver Pod is running and reachable
check_apiserver_status() {
    echo "Checking if kube-apiserver Pod is running and reachable..."
    pod_status=$(kubectl get pod -n kube-system -l component=kube-apiserver -o jsonpath='{.items[0].status.phase}' 2>/dev/null)

    if [[ -z "$pod_status" ]]; then
        return 1
    fi

    if [[ "$pod_status" == "Pending" ]]; then
        return 2
    fi

    if [[ "$pod_status" != "Running" ]]; then
        return 1
    fi
    return 0
}

check_apiserver_status
status=$?
if [[ $status -ne 0 ]]; then
    echo "ERROR: kube-apiserver failed to start or is unreachable!"
    exit 1
fi


EXPECTED_PLUGINS="NodeRestriction,AlwaysPullImages"
MANIFEST_FILE="/etc/kubernetes/manifests/kube-apiserver.yaml"

#CIS-1.2.9 EventRateLimit is not set because of  the bug: https://github.com/kubernetes/kubernetes/issues/62861
#system service-parameter-modify kubernetes kube_apiserver enable-admission-plugins="EventRateLimit"
system service-parameter-modify kubernetes kube_apiserver enable-admission-plugins="$EXPECTED_PLUGINS"
system service-parameter-apply kubernetes

echo "Waiting for sometime for the  changes to take effect ..."
sleep 10
CURRENT_PLUGINS=$(sudo grep -oP -- '--enable-admission-plugins=\K[^"]+' "$MANIFEST_FILE")

if [[ "$CURRENT_PLUGINS" == *"$EXPECTED_PLUGINS"* ]]; then
    echo "Verification successful: The enable-admission-plugins setting includes: $EXPECTED_PLUGINS"
else
    echo "Verification failed: The enable-admission-plugins setting does not include: $EXPECTED_PLUGINS"
    echo "Current setting: $CURRENT_PLUGINS"
fi

run_command() {
    local cmd="$1"
    local success_message="$2"
    local error_message="$3"
    local exists_error_message="$4"
    local modify_cmd="$5"

    # Execute the command
    $cmd
    status=$?

    if [ $status -ne 0 ] && [[ "$(tail -n 1 <<< "$($cmd 2>&1)")" == *"$exists_error_message"* ]]; then
        echo "INFO: $error_message. Attempting to modify instead."
        $modify_cmd
        status=$?

        if [ $status -ne 0 ]; then
            echo "ERROR: Failed to modify the parameter after the add failure."
        else
            echo "Successfully modified the parameter."
        fi
    elif [ $status -ne 0 ]; then
        echo "ERROR: $error_message (Exit Status: $status)"
    else
        echo "$success_message"
    fi

    return $status

}

# Skipped k8s configs are : audit-log-maxbackup=10 and audit-log-maxsize=100. These configs are already set during bootstrap
# Modify the audit-log-maxage parameter
run_command "system service-parameter-modify kubernetes kube_apiserver audit-log-maxage=30" \
    "Successfully modified audit-log-maxage." \
    "Failed to modify audit-log-maxage"

# Add the profiling parameter
run_command "system service-parameter-add kubernetes kube_apiserver profiling=false" \
    "Successfully added profiling parameter." \
    "Failed to add profiling parameter" \
    "Parameter already exists" \
    "system service-parameter-modify kubernetes kube_apiserver profiling=false"

# Modify the audit-policy-file parameter
run_command "system service-parameter-add kubernetes kube_apiserver audit-policy-file=/etc/kubernetes/default-audit-policy.yaml" \
    "Successfully modified audit-policy-file." \
    "Failed to modify audit-policy-file" \
    "Parameter already exists" \
    "system service-parameter-modify kubernetes kube_apiserver audit-policy-file=/etc/kubernetes/default-audit-policy.yaml"

# Apply the service parameters only if the previous commands were successful
if [ $? -eq 0 ]; then
    echo "All service parameters modified successfully. Applying changes..."
    sleep 2

    run_command "system service-parameter-apply kubernetes" \
        "Service parameters applied successfully." \
        "Failed to apply service parameters"
        else
            echo "One or more service parameters failed to modify, skipping apply step."
fi

echo "All commands executed, checking api-server status after 30 secs"
sleep 30

MAX_RETRIES=60
SLEEP_INTERVAL=5
RETRIES=0
while [ $RETRIES -lt $MAX_RETRIES ]; do

    check_apiserver_status
    status=$?
    if [[ $status -eq 0 ]]; then
        echo "Success kube-apiserver is up and running. Exiting loop."
        break
    elif [[ $status -eq 2 ]]; then
        echo "INFO: kube-apiserver Pod is still Pending. Retrying..."
    else
        echo "ERROR: kube-apiserver failed to start or is unreachable!"
    fi

    echo "Waiting for apiserver to come up... (Attempt $((RETRIES + 1))/$MAX_RETRIES)"
    RETRIES=$((RETRIES + 1))
    sleep $SLEEP_INTERVAL
done
exit 0


