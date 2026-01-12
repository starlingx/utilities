#! /bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SYSADMIN_DIR="${extradir}/sysadmin"
mkdir -p ${SYSADMIN_DIR}

LOG_FILE="/home/sysadmin/storage-backend-migration-ansible.log"
CACHE_DIR="/home/sysadmin/.storage-backend-migration-ansible-cache"

# Check and copy storage backend migration files if they exist
if [ -f "$LOG_FILE" ]; then
    cp "$LOG_FILE" "$SYSADMIN_DIR/"
fi

if [ -d "$CACHE_DIR" ]; then
    cp -r "$CACHE_DIR" "$SYSADMIN_DIR/"
fi

exit 0
