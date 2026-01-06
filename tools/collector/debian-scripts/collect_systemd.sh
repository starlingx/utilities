#! /bin/bash
#
# Copyright (c) 2024-2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Loads Up Utilities and Commands Variables

# shellcheck disable=SC1091
source /usr/local/sbin/collect_parms
# shellcheck disable=SC1091
source /usr/local/sbin/collect_utils

# set defaults for shellcheck
: "${extradir:=/tmp}"
: "${hostname:=$(hostname)}"

SERVICE="systemd"
LOGFILE="${extradir}/${SERVICE}.info"
DEPFILE="${extradir}/${SERVICE}_service_dependencies.info"
PLOTFILE="${extradir}/${SERVICE}-startup-plot.svg"
PLOTCMD="timeout 10 systemd-analyze plot > ${PLOTFILE}"

###############################################################################
# Systemd analysis
###############################################################################
echo    "${hostname}: Systemd analyze .........: ${LOGFILE}"
echo    "extra:${extradir} and hostname:${hostname}"

delimiter "${LOGFILE}" "${PLOTCMD}"
eval "${PLOTCMD}"

run_command "timeout 10 systemd-analyze" "${LOGFILE}"
run_command "timeout 10 systemd-analyze blame" "${LOGFILE}"
run_command "timeout 10 systemd-analyze critical-chain" "${LOGFILE}"
run_command "timeout 10 systemd-analyze critical-chain --fuzz=1s" "${LOGFILE}"
{
    echo "$(date): Collecting systemd service dependencies ; declared and inherited"
    echo ""

    # Loop over all installed services (active + inactive)
    while read -r svc _
    do
        echo -e "\n### Dependencies for: ${svc} ###"
        systemctl show "${svc}" --property=After,Before 2>> "${COLLECT_ERROR_LOG}"
    done < <(systemctl list-unit-files --type=service --no-legend 2>> "${COLLECT_ERROR_LOG}")

} > "${DEPFILE}"

exit 0
