#!/bin/bash
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# cloud-init script to run cloud-init from a seed ISO
#

SCRIPT_PATH=$(realpath "$0")
LOCK_FILE="/run/cloud-init-seediso.lock"
ORIGIN_CLOUD_CFG="/etc/cloud/cloud.cfg"
CUSTOM_CLOUD_CFG="/var/lib/factory-install/cloud.cfg"
FACTORY_INSTALL_COMPLETE_FILE="/var/lib/factory-install/complete"
SEED_UDEV_RULES="/etc/udev/rules.d/99-seediso.rules"
SEED_SERVICE="/etc/systemd/system/cloud-init-seed.service"

function check_rc_die {
    local -i rc=${1}
    msg=${2}
    if [ ${rc} -ne 0 ]; then
        log_fatal "${msg} [rc=${rc}]"
    fi
}

function log_fatal {
    echo "$(date +"%Y-%m-%d %H:%M:%S,%3N - cloud-init-seed -") FATAL: ${*}"
    exit 1
}

function log_warn {
    echo "$(date +"%Y-%m-%d %H:%M:%S,%3N - cloud-init-seed -") WARN: ${*}"
}

function log_info {
    echo "$(date +"%Y-%m-%d %H:%M:%S,%3N - cloud-init-seed -") INFO: $*"
}

function restore_cloud_init_config {
    # Restore the original cloud.cfg file from the backup.
    if [[ -f "$ORIGIN_CLOUD_CFG.bak" ]]; then
        mv -f "$ORIGIN_CLOUD_CFG.bak" "$ORIGIN_CLOUD_CFG"
    else
        log_warn "Original cloud.cfg backup not found. Skipping restore."
    fi
}

# Lock file to prevent multiple instances of the script from running
# simultaneously. The lock file is created in the /run directory.
# The lock file is used to ensure that only one instance of the script
# is running at a time. If another instance of the script is already
# running, the script will exit without doing anything.
exec 200>"$LOCK_FILE"
flock -n 200 || {
    log_warn "Another instance of the script is already running. Exiting."
    exit 0
}

# If clean is passed as an argument, remove the udev rule and service,
# the custom cloud.cfg file, and the script itself.
# This is to ensure that the cloud-init-seed service is not triggered
# again after the script has been run successfully.
if [[ "$1" == "clean" ]]; then
    rm -f $SEED_UDEV_RULES
    rm -f $SEED_SERVICE
    rm -f $CUSTOM_CLOUD_CFG
    rm -f $SCRIPT_PATH
    udevadm control --reload-rules
    systemctl daemon-reexec
    exit 0
fi

log_info "Starting cloud-init using seed ISO..."

# Checks if factory-install has been completed. This is required to be able
# to run cloud-init from a seed ISO.
if [[ ! -f "$FACTORY_INSTALL_COMPLETE_FILE" ]]; then
    log_fatal "Cloud-init from factory-install has not been completed yet. Exiting."
fi

# Finds the first device found with the label CIDATA or cidata.
# If the device is not found, exit the script.
DEVICE=$(blkid -L "cidata" 2>/dev/null || blkid -L "CIDATA" 2>/dev/null | head -1)
if [[ -z "$DEVICE" ]]; then
    log_fatal "No ISO with label 'CIDATA' found. Exiting."
fi

# Checks if the device is cloud-init compatible by checking
# if the user-data and meta-data files exist in the ISO.
# If they do not exist, exit the script.
if ! isoinfo -i "$DEVICE" -l 2>/dev/null | grep -qE "user-data|meta-data"; then
    log_fatal "ISO $DEVICE is not cloud-init compatible: missing user-data or meta-data."
fi

# Check if the custom cloud.cfg file exists.
# If it does not exist, exit the script.
if [[ ! -f "$CUSTOM_CLOUD_CFG" ]]; then
    log_fatal "Custom cloud.cfg file not found. Exiting."
fi

# Backup the original cloud.cfg file to prevent
# network validation during cloud-init init.
# The original cloud.cfg file is backed up to a file with the same name
# and a .bak extension.
if [[ ! -f "$ORIGIN_CLOUD_CFG" ]]; then
    log_fatal "Original cloud.cfg file not found. Exiting."
fi
cp -f "$ORIGIN_CLOUD_CFG" "$ORIGIN_CLOUD_CFG".bak
check_rc_die $? "Unable to backup the cloud.cfg file"

# Replace the original cloud.cfg file with the custom cloud.cfg file.
# The custom cloud.cfg file is used to prevent network validation
# during cloud-init init.
cp -f "$CUSTOM_CLOUD_CFG" "$ORIGIN_CLOUD_CFG"
check_rc_die $? "Unable to copy factory-install cloud.cfg file"

# Runs cloud-init commands to apply seed iso configuration.
# The commands are run in the following order:
# 1. cloud-init clean: Cleans up cloud-init state.
# 2. cloud-init init: Initializes cloud-init.
# 3. cloud-init modules --mode=config: Runs the config modules.
# 4. cloud-init modules --mode=final: Runs the final modules.
cloud-init clean &&
cloud-init init &&
cloud-init modules --mode=config &&
cloud-init modules --mode=final
CLOUD_INIT_RC=$?
restore_cloud_init_config
check_rc_die $CLOUD_INIT_RC "cloud-init failed to run from seed ISO."

log_info "cloud-init from seed ISO completed successfully."
exit 0
