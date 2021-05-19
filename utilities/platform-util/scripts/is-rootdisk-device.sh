#!/bin/bash
#
# Copyright (c) 2021 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Usage:
#   is-rootdisk-device <device>
#
# If no arguments are provided, this shows which disk contains the
# root filesystem. If the optional device parameter is specified,
# output is only generated when the device matches the root disk.

dev=$1

rootdev=$(lsblk --ascii -oPKNAME -n $(findmnt -n -T / -o SOURCE))
if [ $# -eq 0 ]; then
    echo "ROOTDISK_DEVICE=${rootdev}"
else
    if [ "${dev}" == "/dev/${rootdev}" ] || \
        [ "/dev/${dev}" == "/dev/${rootdev}" ]; then
        echo "ROOTDISK_DEVICE=${rootdev}"
    else
        exit 1
    fi
fi

exit 0
