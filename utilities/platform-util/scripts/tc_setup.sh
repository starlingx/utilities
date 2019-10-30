#!/bin/sh

#
# Copyright (c) 2017-2019 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# $1 - interface
# $2 - interface type [mgmt]
# $3 - link capacity
# $4 - dummy used to determine if we're backgrounded or not

DEV=$1
NETWORKTYPE=$2
NETWORKSPEED=$3

# log file
LOG_FILE=/var/log/platform.log

# default ethertype for filters
DEFAULT_FILTER_ETHERTYPE=ip

# default match protocol for filters
DEFAULT_FILTER_MATCH_PROTOCOL=ip

# default priority for filters
DEFAULT_FILTER_PRIORITY=1

# default HTB class quantum (borrowing amount) in bytes
DEFAULT_HTB_QUANTUM=60000

# default HTB class burst (amount of bytes that can be burst at ceil speed)
DEFAULT_HTB_BURST=15k

# default SFQ algorithm pertubation in seconds (recommended 10)
DEFAULT_SFQ_PERTUBATION=10

# major handle for the root qdisc / class.
# All objects in the same traffic control structure must share a major handle
# number. Conventionally, numbering schemes start at 1 for objects attached
# directly to the root qdisc.
ROOT_HANDLE_MAJOR=1

# minor handle for the root class.
ROOT_HANDLE_MINOR=1

# root qdisc id. The minor number namespace is left available for classes
ROOT_QDISC_ID="${ROOT_HANDLE_MAJOR}:"

# root class id.  The root class id is typically 1:1
ROOT_CLASS_ID="${ROOT_HANDLE_MAJOR}:${ROOT_HANDLE_MINOR}"

# minor handle for a qdisc. Unambiguously identifies an object as a qdisc
QDISC_HANDLE_MINOR=0

# RFC 2474 class selector codepoints (DCSP)
IPTOS_CLASS_CS0=0x00
IPTOS_CLASS_CS1=0x20
IPTOS_CLASS_CS2=0x40
IPTOS_CLASS_CS3=0x60
IPTOS_CLASS_CS4=0x80
IPTOS_CLASS_CS5=0xa0
IPTOS_CLASS_CS6=0xc0
IPTOS_CLASS_CS7=0xe0

# protocol numbers
IPPROTO_TCP=6
IPPROTO_UDP=17

# relative guaranteed bandwidth percentages for traffic classes
#  in case of over-percentage, bandwidth is divided based on bandwidth ratios
BW_PCT_DEFAULT=90
BW_PCT_HIPRIO=10

# ceiling percentages for traffic classes
CEIL_PCT_DEFAULT=100
CEIL_PCT_HIPRIO=20

# class priority for traffic classes (lower = higher priority)
CLASS_PRIORITY_DEFAULT=4
CLASS_PRIORITY_HIPRIO=${DEFAULT_FILTER_PRIORITY}

# arbitrary flow id for traffic classes
FLOWID_DEFAULT=40
FLOWID_HIPRIO=10

# Network types to apply traffic controls on
VALID_NETWORKTYPES=("mgmt")

function log {
    echo `date +%FT%T.%3N` `hostname` TC_SETUP: $@ >> ${LOG_FILE}
}

## sanity check the given speed
function test_valid_speed {
    # After the link is enabled but before the autonegotiation is complete
    # the link speed may be read as either -1 or as 4294967295 (which is
    # uint(-1) in twos-complement) depending on the kernel.  Neither one is
    # valid.
    if (( $1 > 0 )) && (( $1 != 4294967295 ))
    then
        return 0
    else
        return 1
    fi
}

## determine the negotiated speed for a given interface
function get_dev_speed {
    # If the link doesn't come up we won't go enabled, so here we can
    # afford to wait forever for the link.
    while true; do
        if [ -e /sys/class/net/$1/bonding ]; then
            for VAL in `cat /sys/class/net/$1/lower_*/speed`; do
                if test_valid_speed ${VAL}; then
                    log slave for bond link $1 reported speed ${VAL}
                    echo ${VAL}
                    return 0
                else
                    log slave for bond link $1 reported invalid speed ${VAL}
                fi
            done
            log all slaves for bond link $1 reported invalid speeds, \
                will sleep 30 sec and try again
        else
            VAL=`cat /sys/class/net/$1/speed`
            if test_valid_speed ${VAL}; then
                log link $1 reported speed ${VAL}
                echo ${VAL}
                return 0
            else
                log link $1 returned invalid speed ${VAL}, \
                    will sleep 30 sec and try again
            fi
        fi
        sleep 30
    done
}

## Determines the maximum speed (Mbps) that should be used in traffic control
## rate / ceiling calculations
function get_speed {
    local dev=$1
    local networktype=$2
    local net_speed=${NETWORKSPEED}
    local dev_speed=$(get_dev_speed ${dev})
    local speed=${dev_speed}

    if [ ${net_speed} != ${dev_speed} ]; then
        log WARNING: ${dev} has a different operational speed [${dev_speed}] \
            than configured speed [${net_speed}] for network type ${networktype}
        if test_valid_speed ${net_speed}; then
            # Use greater of configured net speed / recorded dev speed
            if [ ${net_speed} -gt ${dev_speed} ]; then
                speed=${net_speed}
            fi
        fi
    fi
    log using speed ${speed} for tc filtering on ${dev}
    echo ${speed}
}

## Determines whether a device is a loopback interface
function is_loopback {
    local DEVICE=$1

    # (from include/uapi/linux/if.h)
    # IFF_LOOPBACK = 1<<3 = 8. Using a left shifted syntax can confuse bashate.
    IFF_LOOPBACK=8

    # get the interface flags
    FLAGS=`cat /sys/class/net/${DEVICE}/flags`

    if (((${IFF_LOOPBACK} & ${FLAGS}) == 0))
    then
        return 1
    else
        return 0
    fi
}

## Determines whether the network type requires traffic controls
function is_valid_networktype {
    local NETTYPE=$1

    for nt in ${VALID_NETWORKTYPES}; do
        if [ "${NETTYPE}" == ${nt} ]; then
            return 0
        fi
    done
    return 1
}

## Determines whether the given device is a vlan interface
function is_vlan {
    local DEVICE=$1
    if [ -f /proc/net/vlan/${DEVICE} ]; then
        return 0
    else
        return 1
    fi
}

## Delete existing classes, qdiscs, and filters
function delete_tcs {
    local DEVICE=$1

    # Deleting the root qdisc will also delete all underlying
    # classes, qdiscs and filters
    tc qdisc del dev ${DEVICE} root > /dev/null 2>&1
}

## Create the root qdisc and class
function setup_root_tc {
    local DEVICE=$1
    local RATE=$2

    local QDISC_TYPE="htb"
    local CLASS_TYPE="htb"

    tc qdisc add dev ${DEVICE} root handle ${ROOT_QDISC_ID} ${QDISC_TYPE} \
        default ${FLOWID_DEFAULT}

    tc class add dev ${DEVICE} parent ${ROOT_QDISC_ID} \
        classid ${ROOT_CLASS_ID} \
        ${CLASS_TYPE} \
        rate ${RATE}mbit \
        burst ${DEFAULT_HTB_BURST} \
        quantum ${DEFAULT_HTB_QUANTUM}
}

## Create classes and qdiscs for default (unfiltered) traffic
function setup_default_tc {
    local DEVICE=$1
    local MAXSPEED=$2
    local MIN_BW_PCT=$3
    local MAX_BW_PCT=$4
    local RATE=$((${MIN_BW_PCT}*${MAXSPEED}/100))
    local CEIL=$((${MAX_BW_PCT}*${MAXSPEED}/100))
    local CLASS_TYPE="htb"
    local QDISC_TYPE="sfq"
    local QDISC_ID="${FLOWID_DEFAULT}:"

    # associate the objects with the root qdisc/class
    local CLASS_ID=${ROOT_HANDLE_MAJOR}:${FLOWID_DEFAULT}
    local QDISC_PARENT=${ROOT_CLASS_ID}

    tc class add dev ${DEVICE} parent ${QDISC_PARENT} classid ${CLASS_ID} \
        ${CLASS_TYPE} \
        rate ${RATE}mbit \
        burst ${DEFAULT_HTB_BURST} \
        ceil ${CEIL}mbit \
        prio ${CLASS_PRIORITY_DEFAULT} \
        quantum ${DEFAULT_HTB_QUANTUM}

    tc qdisc add dev ${DEVICE} parent ${CLASS_ID} handle ${QDISC_ID} \
        ${QDISC_TYPE} \
        perturb ${DEFAULT_SFQ_PERTUBATION}
}

## Get the match parameters to filter on TOS/DSCP
function get_tc_tos_match {
    local IP_VERSION=$1
    local TOS=$2

    # 6 bits DSCP
    local TOSMASK=0xfc

    if [ ${IP_VERSION} == 6 ]; then
        L3PROTO="ip6"
        TOS_FIELD="priority"
    else
        L3PROTO="ip"
        TOS_FIELD="tos"
    fi

    echo "match ${L3PROTO} ${TOS_FIELD} ${TOS} ${TOSMASK}"
}

## Get the match parameters to filter on a L4 protocol
function get_tc_l4_protocol_match {
    local IP_VERSION=$1
    local L4PROTOCOL=$2

    # 8 bits protocol
    local PROTOCOLMASK=0xff

    if [ ${IP_VERSION} == 6 ]; then
        L3PROTO="ip6"
    else
        L3PROTO="ip"
    fi

    echo "match ${L3PROTO} protocol ${L4PROTOCOL} ${PROTOCOLMASK}"
}

## Get the match parameters to filter on a port range
function get_tc_port_match {
    local IP_VERSION=$1
    local PORT=$2
    local PORTMASK=$3
    local TYPE=${4:-"src"}

    if [ ${TYPE} == "src" ]; then
        TYPE="sport"
    else
        TYPE="dport"
    fi

    if [ ${IP_VERSION} == 6 ]; then
        L3PROTO="ip6"
    else
        L3PROTO="ip"
    fi

    echo "match ${L3PROTO} ${TYPE} ${PORT} ${PORTMASK}"
}

## Get the l2/l3 protocol
function get_tc_protocol {
    local IP_VERSION=$1
    local ETHERTYPE=$2
    local PROTOCOL=${ETHERTYPE}

    if [ -z ${PROTOCOL} ]; then
        # If the ethertype was not explicitly specified, infer it
        # from the IP version
        if [ ${IP_VERSION} == 6 ]; then
            PROTOCOL="ipv6"
        else
            PROTOCOL="ip"
        fi
    fi

    echo "${PROTOCOL}"
}

## Create a filter to deliver system maintenance heartbeats to the high
## priority class
function setup_tc_sm_filter {
    local DEVICE=$1
    local FLOWID=$2
    local ETHERTYPE=$3
    local PRIORITY=${DEFAULT_FILTER_PRIORITY}

    # Setup filters for both IPv4 and IPv6
    local IP_VERSIONS=(4 6)

    # SM uses UDP over ports 2222-2223 with a TOS of 12
    local SM_PORT=2222
    local SM_PORTMASK=0xfffe
    local SM_PORTTYPE="dst"
    local SM_TOS=${IPTOS_CLASS_CS6}
    local SM_PROTO=${IPPROTO_UDP}

    # specifies attaching the filter to the root qdisc
    local QDISC_ID=${ROOT_HANDLE_MAJOR}:${QDISC_HANDLE_MINOR}

    for idx in "${!IP_VERSIONS[@]}"; do
        IP_VERSION=${IP_VERSIONS[$idx]}

        local PROTOCOL=$(get_tc_protocol ${IP_VERSION} ${ETHERTYPE})
        local TOS_MATCH=$(get_tc_tos_match ${IP_VERSION} ${SM_TOS})
        local PROTO_MATCH=$(get_tc_l4_protocol_match ${IP_VERSION} ${SM_PROTO})
        local PORT_MATCH=$(get_tc_port_match \
            ${IP_VERSION} ${SM_PORT} ${SM_PORTMASK} ${SM_PORTTYPE})
        local MATCH_PARAMS="${TOS_MATCH} ${PROTO_MATCH} ${PORT_MATCH}"

        tc filter add dev ${DEVICE} protocol ${PROTOCOL} parent ${QDISC_ID} \
            prio ${PRIORITY} u32 ${MATCH_PARAMS} flowid ${FLOWID}

        PRIORITY=$(($PRIORITY+1))
    done
}

function setup_tc_port_filter {
    local DEVICE=$1
    local FLOWID=$2
    local ETHERTYPE=$3
    local PORT=$4
    local PORTMASK=$5
    local L4PROTOCOL=$6
    local PRIORITY=${DEFAULT_FILTER_PRIORITY}

    # Setup filters for both IPv4 and IPv6
    local IP_VERSIONS=(4 6)

    # Setup filters for both sport and dport
    local PORT_TYPES=("src" "dst")

    # specifies attaching the filter to the root qdisc
    local QDISC_ID=${ROOT_HANDLE_MAJOR}:${QDISC_HANDLE_MINOR}

    for i in "${!IP_VERSIONS[@]}"; do
        local IP_VERSION=${IP_VERSIONS[$i]}
        local PROTOCOL=$(get_tc_protocol ${IP_VERSION} ${ETHERTYPE})

        for j in "${!PORT_TYPES[@]}"; do

            local PORT_MATCH=$(get_tc_port_match \
                ${IP_VERSION} ${PORT} ${PORTMASK} ${PORT_TYPES[$j]})

            if [ -z $L4PROTOCOL ]; then
                # Apply to TCP and UDP
                tc filter add dev ${DEVICE} protocol ${PROTOCOL} \
                    parent ${QDISC_ID} prio ${PRIORITY} u32 ${PORT_MATCH} \
                    flowid ${FLOWID}
            else
                # Apply to specific protocol only
                local PROTO_MATCH=$(get_tc_l4_protocol_match \
                    ${IP_VERSION} ${L4PROTOCOL})
                tc filter add dev ${DEVICE} protocol ${PROTOCOL} \
                    parent ${QDISC_ID} prio ${PRIORITY} u32 ${PROTO_MATCH} \
                    ${PORT_MATCH} flowid ${FLOWID}
            fi
        done
        PRIORITY=$(($PRIORITY+1))
    done
}

## Create classes, qdiscs, and filters for high priority traffic
function setup_hiprio_tc {
    local DEVICE=$1
    local MAXSPEED=$2
    local MIN_BW_PCT=$3
    local MAX_BW_PCT=$4
    local ETHERTYPE=$5
    local MATCH_PROTOCOL=$6
    local RATE=$((${MIN_BW_PCT}*${MAXSPEED}/100))
    local CEIL=$((${MAX_BW_PCT}*${MAXSPEED}/100))
    local CLASS_TYPE="htb"
    local QDISC_ID="${FLOWID_HIPRIO}:"
    local QDISC_TYPE="sfq"

    # associate the objects with the root qdisc/class
    local CLASS_ID=${ROOT_HANDLE_MAJOR}:${FLOWID_HIPRIO}
    local QDISC_PARENT=${ROOT_CLASS_ID}
    local FLOWID=${CLASS_ID}

    tc class add dev ${DEVICE} parent ${QDISC_PARENT} classid ${CLASS_ID} \
        ${CLASS_TYPE} \
        rate ${RATE}mbit \
        burst ${DEFAULT_HTB_BURST} \
        ceil ${CEIL}mbit \
        prio ${CLASS_PRIORITY_HIPRIO} \
        quantum ${DEFAULT_HTB_QUANTUM}

    tc qdisc add dev ${DEVICE} parent ${CLASS_ID} handle ${QDISC_ID} \
        ${QDISC_TYPE} \
        perturb ${DEFAULT_SFQ_PERTUBATION}

    # Treat system maintenance heartbeats as high priority traffic
    setup_tc_sm_filter "${DEVICE}" "${FLOWID}" "${ETHERTYPE}"
}

if ! is_valid_networktype $NETWORKTYPE; then
    exit 0
fi

if is_loopback $DEV; then
    # Don't setup traffic classes for a loopback device (ie simplex system)
    exit 0
fi

# We want to be able to wait some time (typically <10 sec) for the
# network link to autonegotiate link speed.  Re-run the script in
# the background so the parent can return right away and init can
# continue.
if [ $# -eq 3 ]; then
    $0 ${DEV} ${NETWORKTYPE} ${NETWORKSPEED} dummy &
    disown
    exit 0
fi

log running tc setup script for ${DEV} ${NETWORKTYPE} in background

if [ -f /etc/platform/platform.conf ]; then
    source /etc/platform/platform.conf
fi

SPEED=$(get_speed ${DEV} ${NETWORKTYPE})

delete_tcs ${DEV}
setup_root_tc ${DEV} ${SPEED}
setup_default_tc ${DEV} ${SPEED} ${BW_PCT_DEFAULT} ${CEIL_PCT_DEFAULT}
setup_hiprio_tc ${DEV} ${SPEED} ${BW_PCT_HIPRIO} ${CEIL_PCT_HIPRIO}

if is_vlan ${DEV}; then
    if [ -e /sys/class/net/${DEV}/lower_* ]; then
        for LOWER in `basename $(readlink /sys/class/net/${DEV}/lower_*)`; do
            # In the case of a vlan interface, reserve bandwidth for high
            # priority traffic on the underlying interface.
            delete_tcs ${LOWER}
            setup_root_tc ${LOWER} ${SPEED}
            setup_default_tc ${LOWER} ${SPEED} $((100-${BW_PCT_HIPRIO})) 100
            setup_hiprio_tc ${LOWER} ${SPEED} ${BW_PCT_HIPRIO} \
                ${CEIL_PCT_HIPRIO} "802.1q"
        done
    fi
fi


