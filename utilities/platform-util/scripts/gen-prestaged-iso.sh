#!/bin/bash
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Utility to convert a StarlingX installation iso into a
# prestaged subcloud installation iso.
#
# Docker images can also be added to the iso ,removing the need
# for each subcloud to download the images independently.
# Docker images must be in 'docker save' format.  Multiple container
# images can be captured in a single archive.  No single archive may
# exceed 4 GB. Multiple archives can be provided.  All archives
# must have the suffix 'tar.gz'.


# Error log print
function log_fatal {
    echo "ERROR: $@" >&2 && exit 1
}

function log_error {
    echo "ERROR: $@" >&2
}

# Info log
function log {
    echo "INFO: $@" >&2
}

# Usage manual.
function usage {
    cat <<ENDUSAGE
Utility to convert a StarlingX installation iso into a Debian prestaged
subcloud installation iso.

Usage:
   $(basename $0) --input <input bootimage.iso>
                  --output <output bootimage.iso>
                  [ --images <images.tar.gz> ]
                  [ --patch <patch-name.patch> ]
                  [ --kickstart-patch <kickstart-enabler.patch> ]
                  [ --addon <ks-addon.cfg> ]
                  [ --param <param>=<value> ]
                  [ --default-boot <default menu option> ]
                  [ --timeout <menu timeout> ]
                  [ --force-install ]

        --input  <file>: Specify input ISO file
        --output <file>: Specify output ISO file
        --images <images.tar.gz>:
                         Specify a collection of docker images in 'docker save'
                         format.  This option can be specified more than once,
                         or a comma separated list can be used.
                         Multiple images can be captured in a single archive.
                         No single archive may exceed 4 GB.
        --patch <patch-name.patch>:
                         Specify software patch file(s).
                         Can be specified more than once, or provide a comma separated list.
        --kickstart-patch <kickstart-enabler.patch>:
                         A patch to replace the prestaged installer kickstart.
                         Not to be included in the runtime patches.

        --setup  <file>: Specify ks-setup.cfg file.
        --addon  <file>: Specify ks-addon.cfg file.
        --param  <p=v>:  Specify boot parameter(s).
                         Can be specified more than once, or provide a comma separated list.
                         Examples:
                         --param rootfs_device=nvme0n1,boot_device=nvme0n1

                         --param rootfs_device=/dev/disk/by-path/pci-0000:00:0d.0-ata-1.0
                         --param boot_device=/dev/disk/by-path/pci-0000:00:0d.0-ata-1.0

        --default-boot <default menu option>:
                         Specify default boot menu option:
                         0 - Serial Console
                         1 - Graphical Console (default)
        --timeout <menu timeout>:
                         Specify boot menu timeout, in seconds.  (default 30)
                         A value of -1 will wait forever.
        --force-install:
                         Force install the prestaged content even if there is already an
                         installation on the target.
ENDUSAGE
}

function cleanup {
    # This is invoked from the trap handler.
    common_cleanup
}

function check_requirements {
    common_check_requirements mkisofs isohybrid cpio cp find
}

function generate_boot_cfg {
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img ${isodir}
    fi

    local PARAM_LIST=
    log_info "Generating miniboot.iso from params: ${PARAMS[*]}"
    # Set/update boot parameters
    if [ ${#PARAMS[@]} -gt 0 ]; then
        for p in "${PARAMS[@]}"; do
            param=${p%%=*}
            value=${p#*=}
            # Pull the boot device out of PARAMS and convert to instdev
            if [ "$param" = "boot_device" ]; then
                log_info "Setting instdev=$value from boot_device param"
                instdev=$value
            fi
            PARAM_LIST="${PARAM_LIST} ${param}=${value}"
        done
    fi

    log_verbose "Parameters: ${PARAM_LIST}"

    COMMON_ARGS="initrd=/initrd instdate=@$(date +%s) instw=60 instiso=instboot"
    COMMON_ARGS="${COMMON_ARGS} biosplusefi=1 instnet=0"
    COMMON_ARGS="${COMMON_ARGS} ks=file:///kickstart/kickstart.cfg"
    COMMON_ARGS="${COMMON_ARGS} rdinit=/install instname=debian instbr=starlingx instab=0"
    COMMON_ARGS="${COMMON_ARGS} insturl=file://NOT_SET prestage ip=${BOOT_IP_ARG}"
    COMMON_ARGS="${COMMON_ARGS} BLM=2506 FSZ=32 BSZ=512 RSZ=20480 VSZ=20480 instl=/ostree_repo instdev=${instdev}"
    COMMON_ARGS="${COMMON_ARGS} defaultkernel=vmlinuz*[!t]-amd64"

    if [[ -n "${FORCE_INSTALL}" ]]; then
        COMMON_ARGS="${COMMON_ARGS} force_install"
    fi

    # Uncomment for LAT debugging:
    #COMMON_ARGS="${COMMON_ARGS} instsh=2"
    COMMON_ARGS="${COMMON_ARGS} ${PARAM_LIST}"
    log "COMMON_ARGS: $COMMON_ARGS"

    for f in ${isodir}/isolinux/isolinux.cfg; do
        cat <<EOF > "${f}"
prompt 0
timeout ${TIMEOUT}
allowoptions 1
serial 0 115200

ui vesamenu.c32
menu background   #ff555555
menu title Debian Local Install : Select kernel options and boot kernel
menu tabmsg Press [Tab] to edit, [Return] to select

DEFAULT ${DEFAULT_SYSLINUX_ENTRY}
LABEL 0
    menu label Serial Console
    kernel /bzImage-std
    ipappend 2
    append ${COMMON_ARGS} traits=controller console=ttyS0,115200 console=tty0

LABEL 1
    menu label Graphical Console
    kernel /bzImage-std
    ipappend 2
    append ${COMMON_ARGS} traits=controller console=tty0

EOF
done

    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        cat <<EOF > "${f}"
default=${DEFAULT_GRUB_ENTRY}
timeout=${GRUB_TIMEOUT}
search --no-floppy --set=root -l 'oe_iso_boot'

menuentry 'Serial Console' --id=serial {
    linux /bzImage-std ${COMMON_ARGS} traits=controller console=ttyS0,115200 serial
    initrd /initrd
}

menuentry 'Graphical Console' --id=graphical {
    linux /bzImage-std ${COMMON_ARGS} traits=controller console=tty0
    initrd /initrd
}
EOF
    done

    unmount_efiboot_img
}

# Constants
DIR_NAME=$(dirname "$0")
if [[ ! -e "${DIR_NAME}"/stx-iso-utils.sh ]]; then
    log_fatal "${DIR_NAME}/stx-iso-utils.sh does not exist"
else
    source "${DIR_NAME}"/stx-iso-utils.sh
fi

# Required variables
declare INPUT_ISO=
declare OUTPUT_ISO=
declare -a IMAGES
declare ORIG_PWD=$PWD
declare KS_SETUP=
declare KS_ADDON=
declare -a PARAMS
declare -a PATCHES
declare -a KICKSTART_PATCHES
declare DEFAULT_LABEL=0
declare DEFAULT_SYSLINUX_ENTRY=1
declare DEFAULT_GRUB_ENTRY="graphical"
declare UPDATE_TIMEOUT="no"
declare FORCE_INSTALL=

###############################################################################
# Get the command line arguments.
###############################################################################

SHORTOPTS="";    LONGOPTS=""
SHORTOPTS+="i:"; LONGOPTS+="input:,"
SHORTOPTS+="o:"; LONGOPTS+="output:,"
SHORTOPTS+="s:"; LONGOPTS+="setup:,"
SHORTOPTS+="a:"; LONGOPTS+="addon:,"
SHORTOPTS+="p:"; LONGOPTS+="param:,"
SHORTOPTS+="P:"; LONGOPTS+="patch:,"
SHORTOPTS+="K:"; LONGOPTS+="kickstart-patch:,"
SHORTOPTS+="d:"; LONGOPTS+="default-boot:,"
SHORTOPTS+="t:"; LONGOPTS+="timeout:,"
SHORTOPTS+="I:"; LONGOPTS+="images:,"
SHORTOPTS+="f";  LONGOPTS+="force-install,"
SHORTOPTS+="h";  LONGOPTS+="help"

OPTS=$(getopt -o "${SHORTOPTS}" --long "${LONGOPTS}" --name "$0" -- "$@")
if [[ "$?" -ne 0 ]]; then
    usage
    log_fatal "Options to $0 not properly parsed"
fi

eval set -- "${OPTS}"

if [[ $# == 1 ]]; then
    usage
    log_fatal "No arguments were provided"
fi

while :; do
    case $1 in
    -i | --input)
        INPUT_ISO="$2"
        shift 2
        ;;
    -o | --output)
        OUTPUT_ISO=$2
        shift 2
        ;;
    -s | --setup)
        KS_SETUP=$2
        shift 2
        ;;
    -a | --addon)
        KS_ADDON=$2
        shift 2
        ;;
    -p | --param)
        PARAMS+=(${2//,/ })
        shift 2
        ;;
    -P | --patch)
        PATCHES+=(${2//,/ })
        shift 2
        ;;
    -K | --kickstart-patch)
        KICKSTART_PATCHES+=(${2//,/ })
        shift 2
        ;;
    -I | --images)
        IMAGES+=(${2//,/ })
        shift 2
        ;;
    -d | --default-boot)
        DEFAULT_LABEL=$2
        case ${DEFAULT_LABEL} in
            0)
                DEFAULT_SYSLINUX_ENTRY=0
                DEFAULT_GRUB_ENTRY="serial"
                ;;
            1)
                DEFAULT_SYSLINUX_ENTRY=1
                DEFAULT_GRUB_ENTRY="graphical"
                ;;
            *)
                usage
                log_fatal "Invalid default boot menu option: ${DEFAULT_LABEL}"
                ;;
        esac
        shift 2
        ;;
    -t | --timeout)
        let -i timeout_arg=$2
        if [[ "${timeout_arg}" -gt 0 ]]; then
            let -i "TIMEOUT=${timeout_arg}*10"
            GRUB_TIMEOUT="${timeout_arg}"
        elif [[ "${timeout_arg}" -eq 0 ]]; then
            TIMEOUT=0
            GRUB_TIMEOUT=0.001
        elif [[ "${timeout_arg}" -lt 0 ]]; then
            TIMEOUT=0
            GRUB_TIMEOUT=${FOREVER_GRUB_TIMEOUT}
        fi
        UPDATE_TIMEOUT="yes"
        shift 2
        ;;
    -f | --force-install)
            FORCE_INSTALL="true"
        shift
        ;;
    --)
        break
        ;;
    *)
        shift
        break
        ;;
    esac
done


###############################################################################
# Generate prestage iso.
#
###############################################################################
check_requirements

## Check for mandatory parameters
check_required_param "--input" "${INPUT_ISO}"
check_required_param "--output" "${OUTPUT_ISO}"

check_files_exist ${INPUT_ISO} ${KS_SETUP} ${KS_ADDON}
check_files_size  ${INPUT_ISO} ${KS_SETUP} ${KS_ADDON}

if [[ -e "${OUTPUT_ISO}" ]]; then
    log_fatal "${OUTPUT_ISO} exists. Delete before you execute this script."
fi

## Catch Control-C and handle.
trap cleanup EXIT

# Create a temporary build directory.
BUILDDIR=$(mktemp -d -p $PWD updateiso_build_XXXXXX)
if [ -z "${BUILDDIR}" -o ! -d ${BUILDDIR} ]; then
    log_fatal "Failed to create builddir. Aborting..."
fi
echo ${BUILDDIR}
mount_iso "${INPUT_ISO}"

# Copy the contents of the input iso to the build directory.
# This ensures that the ostree, kernel and the initramfs are all copied over
# to the prestage iso.

rsync -a --exclude "pxeboot" "${MNTDIR}/" "${BUILDDIR}/"
rc=$?
if [[ "${rc}" -ne 0 ]]; then
    unmount_iso
    log_fatal "Unable to rsync content from the ISO: Error rc=${rc}"
fi

unmount_iso

# generate the grub and isolinux cmd line parameters

generate_boot_cfg "${BUILDDIR}"
# copy the addon and setup files to the BUILDDIR

if [[ -e "${KS_SETUP}" ]]; then
    cp "${KS_SETUP}" "${BUILDDIR}"
fi

if [[ -e "${KS_ADDON}" ]]; then
    cp "${KS_ADDON}" "${BUILDDIR}"
fi

#  we are ready to create the prestage iso.

mkisofs -o "${OUTPUT_ISO}" \
        -A 'instboot' -V 'instboot' \
        -quiet -U -J -joliet-long -r -iso-level 2 \
        -b isolinux/isolinux.bin -c isolinux/boot.cat -no-emul-boot \
        -boot-load-size 4 -boot-info-table \
        -eltorito-alt-boot \
        -e efi.img \
        -no-emul-boot \
        "${BUILDDIR}"

isohybrid --uefi "${OUTPUT_ISO}"

