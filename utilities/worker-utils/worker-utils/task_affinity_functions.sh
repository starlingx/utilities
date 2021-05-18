#!/bin/bash
################################################################################
# Copyright (c) 2017 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
#
### BEGIN INIT INFO
# Provides:          task_affinity_functions
# Required-Start:
# Required-Stop:
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: task_affinity_functions
### END INIT INFO

# Define minimal path
PATH=/bin:/usr/bin:/usr/local/bin

. /etc/platform/platform.conf
CPUMAP_FUNCTIONS=${CPUMAP_FUNCTIONS:-"/etc/init.d/cpumap_functions.sh"}
[[ -e ${CPUMAP_FUNCTIONS} ]] && source ${CPUMAP_FUNCTIONS}

TASK_AFFINING_INCOMPLETE="/etc/platform/.task_affining_incomplete"

# The following CPULISTs are space separated lists of logical cpus,
# and are used by helper functions.
ISOL_CPULIST=$(/bin/cat /sys/devices/system/cpu/isolated | \
                    perl -pe 's/(\d+)-(\d+)/join(",",$1..$2)/eg'| \
                    sed 's/,/ /g')
PLATFORM_CPUS=$(platform_expanded_cpu_list)
PLATFORM_CPULIST=$(platform_expanded_cpu_list| \
                    perl -pe 's/(\d+)-(\d+)/join(",",$1..$2)/eg'| \
                    sed 's/,/ /g')
VSWITCH_CPULIST=$(get_vswitch_cpu_list| \
                    perl -pe 's/(\d+)-(\d+)/join(",",$1..$2)/eg'| \
                    sed 's/,/ /g')
if [[ $vswitch_type =~ none ]]; then
    VSWITCH_CPULIST=""
fi

PIDFILE=/var/run/affine-tasks.sh.pid

# Idle cpu occupancy threshold; logical cpus with greater idle occupancy
# than this will be included.
IDLEOCC_THRESHOLD=95.0

# Watch timeout to monitor removal of flag file; this is engineered as
# 2x the typical duration of a swact.
WATCH_TIMEOUT_SECONDS=90

# Log info message to /var/log/daemon.log
NAME="task-affine-functions"
LOG_FILE=/tmp/task-affine-functions.log
function LOG {
    logger -p daemon.info -t "${NAME}($$): " "$@"
    if [ ! -z "${LOG_FILE}" ]; then
        local tstamp_H=$( date +"%Y-%0m-%0eT%H:%M:%S" )
        echo -e "${tstamp_H} ${HOSTNAME} $0($$): info $@" >> ${LOG_FILE}
    fi
}

################################################################################
# Check if a given core is one of the platform cores
################################################################################
function is_platform_core {
    local core=$1
    for CPU in ${PLATFORM_CPULIST}; do
        if [ $core -eq $CPU ]; then
            return 1
        fi
    done
    return 0
}

################################################################################
# Check if a given core is one of the vswitch cores
################################################################################
function is_vswitch_core {
    local core=$1
    for CPU in ${VSWITCH_CPULIST}; do
        if [ $core -eq $CPU ]; then
            return 1
        fi
    done
    return 0
}

################################################################################
# Check if a given core is one of the isolcpus cores
################################################################################
function is_isolcpus_core {
    local core=$1
    for CPU in ${ISOL_CPULIST}; do
        if [ $core -eq $CPU ]; then
            return 1
        fi
    done
    return 0
}

# Return list of reaffineable pids. This includes all processes, but excludes
# kernel threads, vSwitch, and anything in the cgroup cpusets: k8s-infra, docker,
# and machine.slice (i.e., qemu-kvm).
function reaffineable_pids {
    local pids_excl
    local pidlist

    pids_excl=$(ps -eL -o pid=,comm= | \
                awk -vORS=',' '/eal-intr-thread|kthreadd/ {print $1}' | \
                sed 's/,$/\n/')
    pidlist=$(ps --ppid ${pids_excl} -p ${pids_excl} --deselect \
                -o pid=,cgroup= | \
                awk '!/k8s-infra|docker|machine.slice/ {print $1; }')
    echo "${pidlist[@]}"
}

################################################################################
# The following function can be called by any platform service that needs to
# temporarily make use of idle VM cores to run a short-duration, service
# critical and cpu intensive operation in AIO. For instance, sm can levearage
# the idle cores to speed up swact activity.
#
# At the end of the operation, regardless of the result, the service must be
# calling function affine_tasks_to_platform_cores to re-affine platform tasks
# back to their assigned core(s).
#
# Kernel, vswitch and VM related tasks are untouched.
################################################################################
function affine_tasks_to_idle_cores {
    local cpulist
    local vswitch_pid
    local pidlist
    local idle_cpulist
    local platform_cpus
    local count=0
    local rc=0

    # Keep the last invocation of affining, truncate when we use idle cores
    :> ${LOG_FILE}

    # Ensure this only runs on AIO
    if ! { [[ "$nodetype" = "controller" ]] && [[ $subfunction = *worker* ]]; }
    then
        LOG "Not AIO, nothing to do."
        return $rc
    fi

    if [ -f ${TASK_AFFINING_INCOMPLETE} ]; then
        read cpulist < ${TASK_AFFINING_INCOMPLETE}
        LOG "Tasks have already been affined to CPU ($cpulist)."
        return $rc
    fi

    # Get idle cpu occupancy of all logical cores in the last 5 seconds.
    declare -a cpuocc_list=( $(sar -P ALL 1 5 | grep Average | awk '{if(NR>2)print $8}') )

    # Determine logical cpus that are considered platform, or application
    # cores with idle percentage greater than 95%.
    declare -a idle_cpus=()
    for cpu in ${!cpuocc_list[@]}; do
        idleocc=${cpuocc_list[$cpu]}
        is_vswitch_core $cpu
        if [ $? -eq 1 ]; then
            continue
        fi

        is_isolcpus_core $cpu
        if [ $? -eq 1 ]; then
            continue
        fi

        is_platform_core $cpu
        if [ $? -eq 1 ]; then
            idle_cpus+=( ${cpu} )
        else
            if [[ $(echo "${idleocc} > ${IDLEOCC_THRESHOLD}" | bc) -eq 1 ]]; then
                idle_cpus+=( ${cpu} )
            fi
        fi
    done

    # comma separated list of idle cpus
    idle_cpulist=$(printf '%s,' "${idle_cpus[@]}")
    idle_cpulist=${idle_cpulist%,}

    LOG "Affining all tasks to idle CPU ($idle_cpulist)"
    pidlist=( $(reaffineable_pids) )
    for pid in ${pidlist[@]}; do
        count=$((${count} + 1))
        taskset --all-tasks --pid --cpu-list \
            ${idle_cpulist} ${pid} > /dev/null 2>&1
    done

    # Save the cpu list to the temp file which will be read and removed when
    # tasks are reaffined to the platform cores later on.
    # This list is consumed by SM so it knows about extra cores.
    echo $idle_cpulist > ${TASK_AFFINING_INCOMPLETE}
    LOG "Affined ${count} processes to idle cores."

    # Wait for affining flag file to disappear. If the timeout period is reached,
    # affine tasks back to platform cores.
    watch_start_seconds=${SECONDS}
    while [ -f ${TASK_AFFINING_INCOMPLETE} ]; do
        elapsed_seconds=$(( ${SECONDS} - ${watch_start_seconds} ))
        LOG "Waiting for swact to complete: ${elapsed_seconds} seconds."
        if [ ${elapsed_seconds} -ge ${WATCH_TIMEOUT_SECONDS} ]; then
            LOG "Exceeded watch timeout: ${WATCH_TIMEOUT_SECONDS} seconds," \
                "affining tasks to platform cores."
            affine_tasks_to_platform_cores
            LOG "Idle cores watch completed," \
                "tasks reaffined to platform cores."
            break
        fi
        sleep 5
    done

    return $rc
}

################################################################################
# The following function is called by sm at the end of swact sequence
# to re-affine management tasks back to the platform cores.
################################################################################
function affine_tasks_to_platform_cores {
    local pidlist
    local rc=0
    local count=0

    # Ensure this only runs on AIO
    if ! { [[ "$nodetype" = "controller" ]] && [[ $subfunction = *worker* ]]; }
    then
        LOG "Not AIO, nothing to do."
        return $rc
    fi

    # Abort if affine-tasks.sh is running
    if [ -e ${PIDFILE} ]; then
        pid=$(cat ${PIDFILE})
        if [ -n "${pid}" -a -e /proc/${pid} ]; then
            LOG "Aborting, ${pid} already running: ${PIDFILE}."
            return $rc
        fi
    fi

    if [ ! -f ${TASK_AFFINING_INCOMPLETE} ]; then
        LOG "Either tasks have never been affined to all/idle cores" \
            "or they have already been reaffined to platform cores."
        return $rc
    fi

    LOG "Reaffining tasks to platform cores (${PLATFORM_CPUS})..."
    pidlist=( $(reaffineable_pids) )
    for pid in ${pidlist[@]}; do
        count=$((${count} + 1))
        taskset --all-tasks --pid --cpu-list \
            ${PLATFORM_CPUS} ${pid} > /dev/null 2>&1
    done

    # Reaffine vSwitch tasks that span multiple cpus to platform cpus
    pidlist=$(ps -eL -o pid=,comm= | awk '/eal-intr-thread/ {print $1}')
    for pid in ${pidlist[@]}; do
        grep Cpus_allowed_list /proc/${pid}/task/*/status 2>/dev/null | \
            sed 's#/# #g' | awk '/,|-/ {print $4}' | \
            xargs --no-run-if-empty -i{} \
            taskset --pid --cpu-list ${PLATFORM_CPUS} {} > /dev/null 2>&1
    done

    rm -v -f ${TASK_AFFINING_INCOMPLETE}
    LOG "Affined ${count} processes to platform cores."

    return $rc
}

################################################################################
# The following function returns a single logical cpu with greatest idle
# occupancy. This can be leveraged by cron tasks or other processes.
# (e.g., python-keystone)
################################################################################
function get_most_idle_core {
    local most_idle_value=${IDLEOCC_THRESHOLD}
    local most_idle_cpu=0

    declare -a cpuocc_list=( $(sar -P ALL 1 5 | grep Average | awk '{if(NR>2)print $8}') )

    for cpu in ${!cpuocc_list[@]}; do
        idle_value=${cpuocc_list[$cpu]}
        is_vswitch_core $cpu
        if [ $? -eq 1 ]; then
            continue
        fi

        is_isolcpus_core $cpu
        if [ $? -eq 1 ]; then
            continue
        fi

        if [ $(echo "${idle_value} > ${most_idle_value}" | bc) -eq 1 ]; then
            most_idle_value=${idle_value}
            most_idle_cpu=${cpu}
        fi
    done

    LOG "get_most_idle_core: cpu=$most_idle_cpu, idleocc=$most_idle_value"
    echo ${most_idle_cpu}
}

