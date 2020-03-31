#!/bin/bash
#
# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Utility for setting up a mini ISO and boot structure to support a
# hybrid boot that combines an ISO and network boot, where:
# - mini ISO contains kernel and initrd, with boot parameters
# configured to access everything else from network
# - setup rootfs (squashfs.img), kickstart, and software repositories
# under an http/https served directory
#
#

# Source shared utility functions
source $(dirname $0)/stx-iso-utils.sh

declare LOG_TAG=$(basename $0)

function log_error {
    logger -i -s -t ${LOG_TAG} -- "$@"
}

declare ADDON=
declare BASE_URL=
declare BOOT_GATEWAY=
declare BOOT_HOSTNAME=
declare BOOT_INTERFACE=
declare BOOT_IP=
declare BOOT_NETMASK=
declare DEFAULT_GRUB_ENTRY=
declare DEFAULT_LABEL=
declare DEFAULT_SYSLINUX_ENTRY=
declare DELETE="no"
declare GRUB_TIMEOUT=-1
declare INPUT_ISO=
declare KS_NODETYPE=
declare NODE_ID=
declare ORIG_PWD=$PWD
declare OUTPUT_ISO=
declare -a PARAMS
declare -i TIMEOUT=0
declare UPDATE_TIMEOUT="no"
declare WWW_ROOT_DIR=

function usage {
    cat <<ENDUSAGE
Description: Sets up a mini bootimage.iso that includes the minimum required to
retrieve the rootfs and software packages needed for installation via http or
https, generated for a specific node.

Mandatory parameters for setup:
    --input <file>:          Specify input ISO file
    --www-root <dir>:        Specify www-serviced directory
    --baseurl <url>:         Specify URL for www-root dir
    --id <node id>:          Specify ID for target node
    --boot-interface <intf>: Specify target node boot interface
    --boot-ip <ip address>:  Specify address for boot interface
    --default-boot <0-5>:    Specify install type:
        0 - Standard Controller, Serial Console
        1 - Standard Controller, Graphical Console
        2 - AIO, Serial Console
        3 - AIO, Graphical Console
        4 - AIO Low-latency, Serial Console
        5 - AIO Low-latency, Graphical Console

Optional parameters for setup:
    --addon <file>:          Specify custom kickstart %post addon, for
                             post-install interface config
    --boot-hostname <host>:  Specify temporary hostname for target node
    --boot-netmask <mask>:   Specify netmask for boot interface
    --boot-gateway <addr>:   Specify gateway for boot interface
    --timeout <seconds>:     Specify boot menu timeout, in seconds
    --param <p=v>:           Specify boot parameter customization
        Examples:
        --param rootfs_device=nvme0n1 --param boot_device=nvme0n1

        --param rootfs_device=/dev/disk/by-path/pci-0000:00:0d.0-ata-1.0
        --param boot_device=/dev/disk/by-path/pci-0000:00:0d.0-ata-1.0

Generated ISO will be: <www-root>/nodes/<node-id>/bootimage.iso

Mandatory parameters for cleanup:
    --www-root <dir>:        Specify www-serviced directory
    --id <node id>:          Specify ID for target node
    --delete:                Request file deletion

Example kickstart addon, to define a VLAN on initial OAM interface setup:
#### start custom kickstart
OAM_DEV=enp0s3
OAM_VLAN=1234

    cat << EOF > /etc/sysconfig/network-scripts/ifcfg-\$OAM_DEV
DEVICE=\$OAM_DEV
BOOTPROTO=none
ONBOOT=yes
LINKDELAY=20
EOF

    cat << EOF > /etc/sysconfig/network-scripts/ifcfg-\$OAM_DEV.\$OAM_VLAN
DEVICE=\$OAM_DEV.\$OAM_VLAN
BOOTPROTO=dhcp
ONBOOT=yes
VLAN=yes
LINKDELAY=20
EOF
#### end custom kickstart

ENDUSAGE
}

#
# Parse cmdline arguments
#
LONGOPTS="input:,addon:,param:,default-boot:,timeout:"
LONGOPTS="${LONGOPTS},base-url:,www-root:,id:,delete"
LONGOPTS="${LONGOPTS},boot-gateway:,boot-hostname:,boot-interface:,boot-ip:,boot-netmask:"
LONGOPTS="${LONGOPTS},help"

OPTS=$(getopt -o h --long "${LONGOPTS}" --name "$0" -- "$@")

if [ $? -ne 0 ]; then
    usage
    exit 1
fi

eval set -- "${OPTS}"

while :; do
    case "$1" in
        --input)
            INPUT_ISO=$2
            shift 2
            ;;
        --addon)
            ADDON=$2
            shift 2
            ;;
        --boot-gateway)
            BOOT_GATEWAY=$2
            shift 2
            ;;
        --boot-hostname)
            BOOT_HOSTNAME=$2
            shift 2
            ;;
        --boot-interface)
            BOOT_INTERFACE=$2
            shift 2
            ;;
        --boot-ip)
            BOOT_IP=$2
            shift 2
            ;;
        --boot-netmask)
            BOOT_NETMASK=$2
            shift 2
            ;;
        --param)
            PARAMS+=($2)
            shift 2
            ;;
        --default-boot)
            DEFAULT_LABEL=$2
            shift 2

            case ${DEFAULT_LABEL} in
                0)
                    DEFAULT_SYSLINUX_ENTRY=0
                    DEFAULT_GRUB_ENTRY="serial"
                    KS_NODETYPE='controller'
                    ;;
                1)
                    DEFAULT_SYSLINUX_ENTRY=1
                    DEFAULT_GRUB_ENTRY="graphical"
                    KS_NODETYPE='controller'
                    ;;
                2)
                    DEFAULT_SYSLINUX_ENTRY=0
                    DEFAULT_GRUB_ENTRY="serial"
                    KS_NODETYPE='smallsystem'
                    ;;
                3)
                    DEFAULT_SYSLINUX_ENTRY=1
                    DEFAULT_GRUB_ENTRY="graphical"
                    KS_NODETYPE='smallsystem'
                    ;;
                4)
                    DEFAULT_SYSLINUX_ENTRY=0
                    DEFAULT_GRUB_ENTRY="serial"
                    KS_NODETYPE='smallsystem_lowlatency'
                    ;;
                5)
                    DEFAULT_SYSLINUX_ENTRY=1
                    DEFAULT_GRUB_ENTRY="graphical"
                    KS_NODETYPE='smallsystem_lowlatency'
                    ;;
                *)
                    log_error "Invalid default boot menu option: ${DEFAULT_LABEL}"
                    usage
                    exit 1
                    ;;
            esac
            ;;
        --timeout)
            let -i timeout_arg=$2
            shift 2

            if [ ${timeout_arg} -gt 0 ]; then
                let -i TIMEOUT=${timeout_arg}*10
                GRUB_TIMEOUT=${timeout_arg}
            elif [ ${timeout_arg} -eq 0 ]; then
                GRUB_TIMEOUT=0.001
            fi

            UPDATE_TIMEOUT="yes"
            ;;
        --www-root)
            WWW_ROOT_DIR=$2
            shift 2
            ;;
        --base-url)
            BASE_URL=$2
            shift 2
            ;;
        --id)
            NODE_ID=$2
            shift 2
            ;;
        --delete)
            DELETE="yes"
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            usage
            exit 1
            ;;
    esac
done

#
# Functions
#

function generate_boot_cfg {
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img ${isodir}
    fi

    local KS_URL="${NODE_URL}/miniboot_${KS_NODETYPE}.cfg"
    local BOOT_IP_ARG="${BOOT_IP}::${BOOT_GATEWAY}:${BOOT_NETMASK}:${BOOT_HOSTNAME}:${BOOT_INTERFACE}:none"

    local COMMON_ARGS="inst.text inst.gpt boot_device=sda rootfs_device=sda"
    COMMON_ARGS="${COMMON_ARGS} biosdevname=0 usbcore.autosuspend=-1"
    COMMON_ARGS="${COMMON_ARGS} security_profile=standard user_namespace.enable=1"
    COMMON_ARGS="${COMMON_ARGS} inst.repo=${NODE_URL} inst.stage2=${NODE_URL} inst.ks=${KS_URL}"
    COMMON_ARGS="${COMMON_ARGS} ip=${BOOT_IP_ARG}"

    for f in ${isodir}/isolinux.cfg ${isodir}/syslinux.cfg; do
        cat <<EOF > ${f}
display splash.cfg
timeout ${TIMEOUT}
F1 help.txt
F2 devices.txt
F3 splash.cfg
serial 0 115200
ui vesamenu.c32
menu background   #ff555555

default ${DEFAULT_SYSLINUX_ENTRY}

menu begin
    menu title ${NODE_ID}

    # Serial Console submenu
    label 0
        menu label Serial Console
        kernel vmlinuz
        initrd initrd.img
        append rootwait ${COMMON_ARGS} console=ttyS0,115200 serial

    # Graphical Console submenu
    label 1
        menu label Graphical Console
        kernel vmlinuz
        initrd initrd.img
        append rootwait ${COMMON_ARGS} console=tty0
menu end

EOF
    done

    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        cat <<EOF > ${f}
default=${DEFAULT_GRUB_ENTRY}
timeout=${GRUB_TIMEOUT}
search --no-floppy --set=root -l 'oe_iso_boot'

menuentry "${NODE_ID}" {
    echo " "
}

menuentry 'Serial Console' --id=serial {
    linuxefi /vmlinuz ${COMMON_ARGS} console=ttyS0,115200 serial
    initrdefi /initrd.img
}

menuentry 'Graphical Console' --id=graphical {
    linuxefi /vmlinuz ${COMMON_ARGS} console=tty0
    initrdefi /initrd.img
}
EOF

    done
}

function cleanup {
    common_cleanup
}

function check_requirements {
    common_check_requirements
}

function handle_delete {
    # Remove node-specific files
    if [ -d ${NODE_DIR} ]; then
        rm -rf ${NODE_DIR}
    fi

    # If there are no more nodes, cleanup everything else
    if [ -z "$(ls -A ${NODE_DIR_BASE})" ]; then
        rmdir ${NODE_DIR_BASE}

        rm -rf ${SHARED_DIR}
    fi
}

function extract_shared_files {
    if [ -d ${SHARED_DIR} ]; then
        # If the shared dir already exists, assume we don't need to re-extract
        return
    fi

    mkdir -p ${SHARED_DIR}
    if [ $? -ne 0 ]; then
        log_error "Failed to create directory: ${SHARED_DIR}"
        exit 1
    fi

    # Check ISO content
    if [ ! -f ${MNTDIR}/LiveOS/squashfs.img ]; then
        log_error "squashfs.img not found on ${INPUT_ISO}"
        exit 1
    fi

    rsync -a ${MNTDIR}/LiveOS/ ${SHARED_DIR}/LiveOS/
    if [ $? -ne 0 ]; then
        log_error "Failed to copy rootfs from ${INPUT_ISO}"
        exit 1
    fi

    rsync ${MNTDIR}/isolinux.cfg ${SHARED_DIR}/
    if [ $? -ne 0 ]; then
        log_error "Failed to copy isolinux.cfg from ${INPUT_ISO}"
        exit 1
    fi

    rsync -a ${MNTDIR}/Packages/ ${SHARED_DIR}/Packages/
    if [ $? -ne 0 ]; then
        log_error "Failed to copy base packages from ${INPUT_ISO}"
        exit 1
    fi

    rsync -a ${MNTDIR}/repodata/ ${SHARED_DIR}/repodata/
    if [ $? -ne 0 ]; then
        log_error "Failed to copy base repodata from ${INPUT_ISO}"
        exit 1
    fi

    if [ -d ${MNTDIR}/patches ]; then
        rsync -a ${MNTDIR}/patches/ ${SHARED_DIR}/patches/
        if [ $? -ne 0 ]; then
            log_error "Failed to copy patches repo from ${INPUT_ISO}"
            exit 1
        fi
    fi
}

function extract_node_files {
    # Copy files for mini ISO build
    rsync -a \
        --exclude LiveOS/ \
        --exclude Packages/ \
        --exclude repodata/ \
        --exclude patches/ \
        --exclude pxeboot/ \
        --exclude pxeboot_setup.sh \
        --exclude upgrades/ \
        --exclude '*_ks.cfg' \
        --exclude ks.cfg \
        --exclude ks \
        ${MNTDIR}/ ${BUILDDIR}/
    rc=$?
    if [ $rc -ne 0 ]; then
        log_error "Call to rsync ISO content. Aborting..."
        exit $rc
    fi

    # Setup syslinux and grub cfg files
    generate_boot_cfg ${BUILDDIR}

    # Set/update boot parameters
    if [ ${#PARAMS[@]} -gt 0 ]; then
        for p in ${PARAMS[@]}; do
            param=${p%%=*} # Strip from the first '=' on
            value=${p#*=}  # Strip to the first '='

            update_parameter ${BUILDDIR} "${param}" "${value}"
        done
    fi

    unmount_efiboot_img

    mkdir -p ${NODE_DIR}
    if [ $? -ne 0 ]; then
        log_error "Failed to create ${NODE_DIR}"
        exit 1
    fi

    # Setup symlinks to the shared content, which lighttpd can serve
    pushd ${NODE_DIR} >/dev/null
    ln -s ../../shared/* .
    popd >/dev/null

    # Rebuild the ISO
    OUTPUT_ISO=${NODE_DIR}/bootimage.iso
    mkisofs -o ${OUTPUT_ISO} \
        -R -D -A 'oe_iso_boot' -V 'oe_iso_boot' \
        -quiet \
        -b isolinux.bin -c boot.cat -no-emul-boot \
        -boot-load-size 4 -boot-info-table \
        -eltorito-alt-boot \
        -e images/efiboot.img \
        -no-emul-boot \
        ${BUILDDIR}

    isohybrid --uefi ${OUTPUT_ISO}
    implantisomd5 ${OUTPUT_ISO}

    # Setup the kickstart
    cp ${MNTDIR}/pxeboot/pxeboot_${KS_NODETYPE}.cfg ${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg

    # Number of dirs in the NODE_URL: Count the / characters, subtracting 2 for http:// or https://
    DIRS=$(($(grep -o "/" <<< "$NODE_URL" | wc -l) - 2))

    # Escape the / chars for use in sed
    NODE_URL_SED="${NODE_URL//\//\\/}"

    sed -i "s#xxxHTTP_URLxxx#${NODE_URL_SED}#g;
            s#xxxHTTP_URL_PATCHESxxx#${NODE_URL_SED}/patches#g;
            s#NUM_DIRS#${DIRS}#g" \
        ${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg

    # Append the custom addon
    if [ -n "${ADDON}" ]; then
        cat <<EOF >>${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg

%post --erroronfail

# Source common functions
. /tmp/ks-functions.sh

$(cat ${ADDON})

%end
EOF
    fi
}

#
# Main
#

# Run cleanup on any exit
trap cleanup EXIT

# Check script dependencies
check_requirements

# Validate parameters

# Check mandatory parameters

check_required_param "--id" "${NODE_ID}"
check_required_param "--www-root" "${WWW_ROOT_DIR}"

declare NODE_DIR_BASE="${WWW_ROOT_DIR}/nodes"
declare NODE_DIR="${NODE_DIR_BASE}/${NODE_ID}"
declare SHARED_DIR="${WWW_ROOT_DIR}/shared"

if [ ! -d "${WWW_ROOT_DIR}" ]; then
    log_error "Root directory ${WWW_ROOT_DIR} does not exist"
    exit 1
fi

# Check for deletion
if [ ${DELETE} = "yes" ]; then
    handle_delete
    exit 0
fi

# Handle extraction and setup

check_required_param "--input" "${INPUT_ISO}"
check_required_param "--default-boot" "${DEFAULT_GRUB_ENTRY}"
check_required_param "--base-url" "${BASE_URL}"
check_required_param "--boot-ip" "${BOOT_IP}"
check_required_param "--boot-interface" "${BOOT_INTERFACE}"

declare NODE_URL="${BASE_URL%\/}/nodes/${NODE_ID}"

if [ ! -f ${INPUT_ISO} ]; then
    log_error "Input file does not exist: ${INPUT_ISO}"
    exit 1
fi

if [ -d ${NODE_DIR} ]; then
    log_error "Output dir already exists: ${NODE_DIR}"
    exit 1
fi

BUILDDIR=$(mktemp -d -p $PWD updateiso_build_XXXXXX)
if [ -z "${BUILDDIR}" -o ! -d ${BUILDDIR} ]; then
    log_error "Failed to create builddir. Aborting..."
    exit 1
fi

mount_iso ${INPUT_ISO}

# Copy the common files from the ISO, if needed
extract_shared_files

# Extract/generate the node-specific files
extract_node_files

unmount_iso

exit 0

