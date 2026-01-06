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
SEED_NETWORK_CFG="network-config"
NETWORK_CFG_FILE="/run/.$SEED_NETWORK_CFG"
CLOUD_INIT_IF_FILE="/etc/network/interfaces.d/50-cloud-init"
readonly EVENT_FACTORY_SETUP_COMPLETE="factory_setup_complete"
readonly EVENT_FACTORY_SETUP_FAILED="factory_setup_failed"
readonly DATA_FACTORY_SETUP_COMPLETE="0x04 0x12 0xCC 0x63 0xCC 0x10 0xE0 # \"Factory Setup Complete\""
readonly DATA_FACTORY_SETUP_FAILED="0x04 0x12 0xCC 0x63 0xCC 0x10 0xE1 # \"Factory Setup Failed\""

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

function send_ipmi_event {
    local event_type="$1"
    local event_data
    case "$event_type" in
        "$EVENT_FACTORY_SETUP_COMPLETE")            event_data="$DATA_FACTORY_SETUP_COMPLETE" ;;
        "$EVENT_FACTORY_SETUP_FAILED")              event_data="$DATA_FACTORY_SETUP_FAILED" ;;
        *)
            log_warn "Unknown IPMI event type: $event_type"
            return 1
            ;;
    esac

    local temp_file=$(mktemp /tmp/ipmi_event_XXXXXX.txt)
    echo "$event_data" > "$temp_file"

    if ipmitool sel add "$temp_file" 2>/dev/null; then
        log_info "IPMI event sent successfully: $event_type"
        rm -f "$temp_file"
        return 0
    else
        log_warn "Failed to send IPMI event: $event_type"
        rm -f "$temp_file"
        return 1
    fi
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
    send_ipmi_event "$EVENT_FACTORY_SETUP_FAILED"
    log_fatal "/var/lib/factory-install/stage/complete does not exist. Ensure factory-install was successful."
fi
send_ipmi_event "$EVENT_FACTORY_SETUP_COMPLETE"

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

# Extracts the network-config file from the seed ISO.
# The network-config file is used to configure the network
# settings for the cloud-init instance.
isoinfo -i $DEVICE -R -x "/$SEED_NETWORK_CFG" > $NETWORK_CFG_FILE
check_rc_die $? "Unable to retrieve network-config from seed ISO. Exiting."

# Checks if the network-config file is empty.
# If it is empty, exit the script.
if [ ! -s $NETWORK_CFG_FILE ]; then
    log_fatal "Invalid network-config file. Exiting."
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

# We separate the cloud-init sequence into two parts:
# First, we run cloud-init initialization mode to set up the network
# configuration using the network-config file extracted from the seed
# ISO.
cloud-init clean &&
cloud-init init &&
cloud-init devel net-convert \
    --network-data $NETWORK_CFG_FILE \
    --kind yaml \
    --output-kind eni \
    -d / \
    -D debian
CLOUD_INIT_RC=$?
if [ $CLOUD_INIT_RC -ne 0 ]; then
    restore_cloud_init_config
    check_rc_die $CLOUD_INIT_RC "cloud-init initialization failed from seed ISO."
fi

# The network configuration is applied using the ifup command.
#
# Background: During enroll init process, if the OAM address is on the same device,
# but assigned a different address, the ifup command is paused silently before
# creating the new address (the return code is still 0). This behavior can cause
# a subsequent new route with the new address creation failure.
#
# The --force option is used here to prevent ifup from pausing in case the new
# OAM address is configured with a different address, but in the same VLAN and
# interface.

# Store initial default routes before any network changes
declare -A INITIAL_ROUTES
INITIAL_ROUTES["ipv4"]=$(ip -4 route show | grep default 2>&1)
INITIAL_ROUTES["ipv6"]=$(ip -6 route show | grep default 2>&1)

# Function to restore default routes
restore_default_routes() {
    log_info "Attempting to restore initial default routes..."

    if [ -n "${INITIAL_ROUTES["ipv4"]}" ]; then

        local initial_v4_gateway
        local initial_v4_dev
        local remove_current_ipv4_default
        local restore_initial_ipv4_default

        initial_v4_gateway=$(echo "${INITIAL_ROUTES["ipv4"]}" | awk '{print $3}')
        initial_v4_dev=$(echo "${INITIAL_ROUTES["ipv4"]}" | awk '{print $5}')
        remove_current_ipv4_default=0
        restore_initial_ipv4_default=0

        # Check if a default IPv4 route already exists (ifup might have added one)
        CURRENT_V4_DEFAULT=$(ip -4 route show | grep default 2>&1)
        if [ -z "$CURRENT_V4_DEFAULT" ]; then
            remove_current_ipv4_default=0
            restore_initial_ipv4_default=1
        elif [ "$CURRENT_V4_DEFAULT" == "${INITIAL_ROUTES["ipv4"]}" ]; then
            remove_current_ipv4_default=0
            restore_initial_ipv4_default=0
        else
            remove_current_ipv4_default=1
            restore_initial_ipv4_default=1
        fi

        if [ "$remove_current_ipv4_default" -eq 1 ]; then
            log_info "IPv4 default route already exists, removing '$CURRENT_V4_DEFAULT' to restore."
            sudo ip -4 route del default
            if [ $? -eq 0 ]; then
                log_info "Default IPv4 route successfully removed."
            else
                log_info "Error: Failed to remove the default IPv4 route. Check permissions or if the route still exists."
            fi
        fi

        if [ "$restore_initial_ipv4_default" -eq 1 ]; then
            log_info "Restoring initial IPv4 default route..."
            if [ -n "$initial_v4_gateway" ] && [ -n "$initial_v4_dev" ]; then
                sudo ip -4 route add default via "$initial_v4_gateway" dev "$initial_v4_dev"
                if [ $? -eq 0 ]; then
                    log_info "IPv4 default route restored successfully: default via $initial_v4_gateway dev $initial_v4_dev"
                else
                    log_info "Error: Failed to restore IPv4 default route."
                fi
            else
                log_info "Warning: Could not parse original IPv4 default gateway/device for restoration. Manual intervention may be needed."
            fi
        fi
    else
        log_info "No initial IPv4 default route to restore."
    fi

    if [ -n "${INITIAL_ROUTES["ipv6"]}" ]; then
        local initial_v6_gateway
        local initial_v6_dev
        local remove_current_ipv6_default
        local restore_initial_ipv6_default

        initial_v6_gateway=$(echo "${INITIAL_ROUTES["ipv6"]}" | awk '{print $3}')
        initial_v6_dev=$(echo "${INITIAL_ROUTES["ipv6"]}" | awk '{print $5}')
        remove_current_ipv6_default=0
        restore_initial_ipv6_default=0

        # Check if a default IPv6 route already exists (ifup might have added one)
        CURRENT_V6_DEFAULT=$(ip -6 route show | grep default 2>&1)
        if [ -z "$CURRENT_V6_DEFAULT" ]; then
            remove_current_ipv6_default=0
            restore_initial_ipv6_default=1
        elif [ "$CURRENT_V6_DEFAULT" == "${INITIAL_ROUTES["ipv6"]}" ]; then
            remove_current_ipv4_default=0
            restore_initial_ipv4_default=0
        else
            remove_current_ipv6_default=1
            restore_initial_ipv6_default=1
        fi

        if [ "$remove_current_ipv6_default" -eq 1 ]; then
            log_info "IPv6 default route already exists, removing '$CURRENT_V6_DEFAULT' to restore."
            sudo ip -6 route del default
            if [ $? -eq 0 ]; then
                log_info "Default IPv6 route successfully removed."
            else
                log_info "Error: Failed to remove the default IPv6 route. Check permissions or if the route still exists."
            fi
        fi

        if [ "$restore_initial_ipv6_default" -eq 1 ]; then
            log_info "Restoring initial IPv6 default route..."
            if [ -n "$initial_v6_gateway" ] && [ -n "$initial_v6_dev" ]; then
                sudo ip -6 route add default via "$initial_v6_gateway" dev "$initial_v6_dev"
                if [ $? -eq 0 ]; then
                    log_info "IPv6 default route restored successfully: default via $initial_v6_gateway dev $initial_v6_dev"
                else
                    log_info "Error: Failed to restore IPv6 default route."
                fi
            else
                log_info "Warning: Could not parse original IPv6 default gateway/device for restoration. Manual intervention may be needed."
            fi
        fi
    else
        log_info "No initial IPv6 default route to restore."
    fi
}

remove_current_default_routes() {
    CURRENT_DEFAULT_IPv4_ROUTE=$(ip -4 route show | grep default 2>&1)
    if [ -n "$CURRENT_DEFAULT_IPv4_ROUTE" ]; then
        if grep -q -E "iface .* inet static" "$CLOUD_INIT_IF_FILE"; then
            log_info "Default IPv4 route found. Removing '${CURRENT_DEFAULT_IPv4_ROUTE}'"
            sudo ip -4 route del default
            if [ $? -eq 0 ]; then
                log_info "Default IPv4 route successfully removed."
            else
                log_info "Error: Failed to remove the default IPv4 route. Check permissions or if the route still exists."
            fi
        else
            log_info "file ${CLOUD_INIT_IF_FILE} isn't inet. do not remove IPv4 default route."
        fi
    else
        log_info "No default IPv4 route found."
    fi

    CURRENT_DEFAULT_IPv6_ROUTE=$(ip -6 route show | grep default 2>&1)
    if [ -n "$CURRENT_DEFAULT_IPv6_ROUTE" ]; then
        if grep -q -E "iface .* inet6 static" "$CLOUD_INIT_IF_FILE"; then
            log_info "Default IPv6 route found. Removing '${CURRENT_DEFAULT_IPv6_ROUTE}'"
            sudo ip -6 route del default
            if [ $? -eq 0 ]; then
                log_info "Default IPv6 route successfully removed."
            else
                log_info "Error: Failed to remove the default IPv6 route. Check permissions or if the route still exists."
            fi
        else
            log_info "file ${CLOUD_INIT_IF_FILE} isn't inet6, do not remove IPv6 default route."
        fi
    else
        log_info "No default IPv6 route found."
    fi
}

cloud_init_iface=''
cloud_init_gateway=''
cloud_init_proto=''

# Check if CLOUD_INIT_IF_FILE exists and contains "gateway"
if [ -f "$CLOUD_INIT_IF_FILE" ] && grep -q "gateway" "$CLOUD_INIT_IF_FILE"; then
    log_info "Cloud-init interface file '$CLOUD_INIT_IF_FILE' contains 'gateway'. Will attempt to remove existing default routes."
    cloud_init_iface=$(awk '/iface.*inet.*static/ {print $2}' $CLOUD_INIT_IF_FILE)
    cloud_init_gateway=$(awk '/gateway/ {print $2}' $CLOUD_INIT_IF_FILE)
    cloud_init_proto=$(awk '/iface.*inet.*static/ {print $3}' $CLOUD_INIT_IF_FILE)
    remove_current_default_routes
else
    log_info "Cloud-init interface file '$CLOUD_INIT_IF_FILE' does not exist or does not contain 'gateway'. Skipping removal of existing default routes."
fi

IFUP_OUTPUT=$(ifup -i $CLOUD_INIT_IF_FILE -a -v --force 2>&1)
CLOUD_INIT_RC=$?
log_info "ifup output: $IFUP_OUTPUT"
if [ $CLOUD_INIT_RC -ne 0 ]; then
    restore_cloud_init_config
    restore_default_routes
    check_rc_die $CLOUD_INIT_RC "ifup failed during cloud-init initialization."
else
    declare -A LATEST_ROUTES
    LATEST_ROUTES["ipv4"]=$(ip -4 route show exact default 2>&1)
    LATEST_ROUTES["ipv6"]=$(ip -6 route show exact default 2>&1)
    log_info "default routes:"
    for key in "${!LATEST_ROUTES[@]}"; do
        log_info "$key routes: ${LATEST_ROUTES[$key]}"
    done
    if [[ -n "${cloud_init_iface}" && -n "${cloud_init_gateway}" ]]; then
        ip_version=""
        if [[ "${cloud_init_proto}" == "inet" ]]; then
            ip_version="-4"
        elif [[ "${cloud_init_proto}" == "inet6" ]]; then
            ip_version="-6"
        fi
        search=$(ip ${ip_version} route show exact default via "${cloud_init_gateway}" dev "${cloud_init_iface}" 2>&1)
        if [[ ! "${search}" =~ ^default ]]; then
            log_info "ifup completed successfully, but no cloud-init default route exists, creating"
            ip ${ip_version} route add default via "${cloud_init_gateway}" dev "${cloud_init_iface}"
            if [ $? -eq 0 ]; then
                log_info "default route restored successfully: default via $cloud_init_gateway dev $cloud_init_iface"
            else
                latest_default=$(ip ${ip_version} route show exact default 2>&1)
                log_info "Error: Failed to restore cloud_init_gateway, output:${latest_default}"
                restore_default_routes
            fi
        else
            log_info "ifup completed successfully. No route restoration needed."
        fi
    else
        if [[ -z "${LATEST_ROUTES["ipv4"]}" || -z "${LATEST_ROUTES["ipv6"]}" ]]; then
            log_info "Still have missing default route, restore to previous value"
            restore_default_routes
        else
            log_info "ifup completed successfully. No route restoration needed."
        fi
    fi
fi

NET_ADDR_STATE=$(echo "======= Addresses post config"; ip -br addr | grep -v -E "cali" 2>&1)
log_info "network address state output post config: $NET_ADDR_STATE"
NET_ROUTE4_STATE=$(echo "======= IPv4 Routes post config"; ip -4 route 2>&1)
log_info "network routes state output post config: $NET_ROUTE4_STATE"
NET_ROUTE6_STATE=$(echo "======= IPv6 Routes post config"; ip -6 route 2>&1)
log_info "network routes state output post config: $NET_ROUTE6_STATE"

# After the network is set up, we run cloud-init config and final
# modes to apply the configuration and finalize the instance.
# This includes running any user-data scripts and applying any
# additional configuration specified in the user-data file.
cloud-init modules --mode=config &&
cloud-init modules --mode=final
CLOUD_INIT_RC=$?
restore_cloud_init_config
check_rc_die $CLOUD_INIT_RC "cloud-init failed to run modules from seed ISO."

log_info "cloud-init from seed ISO completed successfully."
exit 0
