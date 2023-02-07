#! /bin/bash
#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SYSADMIN_DIR="${extradir}/sysadmin"
mkdir -p ${SYSADMIN_DIR}

#check files exists and then copy to sysadmin directory

[ -e /home/sysadmin/*.log ] && cp /home/sysadmin/*.log /${SYSADMIN_DIR}/
[ -e /home/sysadmin/*.yml ] && cp /home/sysadmin/*.yml /${SYSADMIN_DIR}/
[ -e /home/sysadmin/*.yaml ] && cp /home/sysadmin/*.yaml /${SYSADMIN_DIR}/

exit 0
