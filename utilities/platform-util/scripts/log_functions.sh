#!/bin/bash
################################################################################
# Copyright (c) 2013-2015 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################

################################################################################
# Log if debug is enabled via LOG_DEBUG
#
################################################################################
function log_debug {
    if [ ! -z "${LOG_DEBUG}" ]; then
        logger -p debug -t "$0[${PPID}]" -s "$@" 2>&1
    fi
}

################################################################################
# Log unconditionally to STDERR
#
################################################################################
function log_error {
    logger -p error -t "$0[${PPID}]" -s "$@"
}

################################################################################
# Log unconditionally to STDOUT
#
################################################################################
function log {
    logger -p info -t "$0[${PPID}]" -s "$@" 2>&1
}

################################################################################
# Utility function to print the status of a command result
#
################################################################################
function print_status {
    if [ "$1" -eq "0" ]; then
        echo "[  OK  ]"
    else
        echo "[FAILED]"
    fi
}
