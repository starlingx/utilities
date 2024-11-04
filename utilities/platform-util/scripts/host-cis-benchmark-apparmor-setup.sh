#!/bin/bash
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# script to enable apparmor on a host
#

# Check if the script argument is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <host-name>"
    exit 1
fi

# Set the host name from the script argument
HOST=$1

# Source the platform environment
source /etc/platform/openrc

# Check the current AppArmor status
apparmor_status=$(system host-show $HOST | grep "apparmor" | awk '{print $4}')
if [ "$apparmor_status" == "enabled" ]; then
    echo "AppArmor is already enabled on $HOST."
    exit 0
else
    echo "AppArmor is not enabled on $HOST. Proceeding with the script execution."
fi

# Lock the host
echo "Locking the host $HOST..."
system host-lock $HOST

# Wait for the host status to change to 'locked' with up to 3 attempts
max_lock_retries=3
lock_attempt=1
while [ $lock_attempt -le $max_lock_retries ]; do
    echo "Attempt $lock_attempt: Checking if the host $HOST is locked..."
    status=$(system host-show $HOST | grep "administrative" | awk '{print $4}')
    if [ "$status" == "locked" ]; then
        echo "Host $HOST is now locked."
        break
    else
        echo "Host $HOST is not yet locked. Retrying..."
        lock_attempt=$((lock_attempt + 1))
        sleep 10
    fi
done

# Check if locking failed after all attempts
if [ $lock_attempt -gt $max_lock_retries ]; then
    echo "Failed to lock the host $HOST after $max_lock_retries attempts. Please check manually."
    exit 1
fi

# Run the host update command
echo "Updating AppArmor status on the host $HOST..."
system host-update $HOST apparmor=enabled

# Verify if AppArmor is enabled after the update
apparmor_status=$(system host-show $HOST | grep "apparmor" | awk '{print $4}')
if [ "$apparmor_status" == "enabled" ]; then
    echo "AppArmor has been successfully enabled on $HOST."
else
    echo "Failed to enable AppArmor on $HOST. Please check manually."
    exit 1
fi

# Unlock the host with up to 3 retry attempts
max_unlock_retries=3
unlock_attempt=1
while [ $unlock_attempt -le $max_unlock_retries ]; do
    echo "Attempt $unlock_attempt: Unlocking the host $HOST..."
    system host-unlock $HOST
    sleep 10

    # Check if the host is unlocked
    status=$(system host-show $HOST | grep "administrative" | awk '{print $4}')
    if [ "$status" == "unlocked" ]; then
        echo "Host $HOST is now unlocked."
        break
    else
        echo "Attempt $unlock_attempt failed. Retrying..."
        unlock_attempt=$((unlock_attempt + 1))
    fi
done

# Check if the host is still locked after all attempts
if [ $unlock_attempt -gt $max_unlock_retries ]; then
    echo "Failed to unlock the host $HOST after $max_unlock_retries attempts. Please check manually."
    exit 1
fi

echo "Script completed. Host may take some time to become available "

