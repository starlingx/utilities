#!/bin/bash
#
# Copyright (c) 2019,2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Utility for updating an ISO
#
# This utility supports the following:
# 1. Provide a custom kickstart post addon, allowing the user
# to add some custom configuration, such as custom network
# interface config
# 2. Add or modify installation boot parameters, such as changing
# the default boot_device and rootfs_device disks
#

# Source shared utility functions
source $(dirname $0)/stx-iso-utils-centos.sh

function log_error {
    echo "$@" >&2
}

function usage {
    cat <<ENDUSAGE
Usage:
   $(basename $0) -i <input bootimage.iso> -o <output bootimage.iso>
                   [ -a <ks-addon.cfg> ] [ -p param=value ]
                   [ -d <default menu option> ] [ -t <menu timeout> ]
        -i <file>: Specify input ISO file
        -o <file>: Specify output ISO file
        -a <file>: Specify ks-addon.cfg file
        -p <p=v>:  Specify boot parameter
                   Examples:
                   -p rootfs_device=nvme0n1 -p boot_device=nvme0n1

                   -p rootfs_device=/dev/disk/by-path/pci-0000:00:0d.0-ata-1.0
                   -p boot_device=/dev/disk/by-path/pci-0000:00:0d.0-ata-1.0

        -d <default menu option>:
                   Specify default boot menu option:
                   0 - Standard Controller, Serial Console
                   1 - Standard Controller, Graphical Console
                   2 - AIO, Serial Console
                   3 - AIO, Graphical Console
                   4 - AIO Low-latency, Serial Console
                   5 - AIO Low-latency, Graphical Console
                   NULL - Clear default selection
        -t <menu timeout>:
                   Specify boot menu timeout, in seconds

Example ks-addon.cfg, to define a VLAN on initial OAM interface setup:
#### start ks-addon.cfg
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
#### end ks-addon.cfg

ENDUSAGE
}

function cleanup {
    common_cleanup
}

function check_requirements {
    common_check_requirements
}

function set_default_label {
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img ${isodir}
    fi

    for f in ${isodir}/isolinux.cfg ${isodir}/syslinux.cfg; do
        if [ "${DEFAULT_LABEL}" = "NULL" ]; then
            # Remove default, if set
            grep -q '^default' ${f}
            if [ $? -eq 0 ]; then
                sed -i '/^default/d' ${f}
            fi
        else
            grep -q '^default' ${f}
            if [ $? -ne 0 ]; then
                cat <<EOF >> ${f}

default ${DEFAULT_LABEL}
EOF
            else
                sed -i "s/^default.*/default ${DEFAULT_LABEL}/" ${f}
            fi
        fi
    done

    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        sed -i "s/^default=.*/default=\"${DEFAULT_GRUB_ENTRY}\"/" ${f}
    done
}

function set_timeout {
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img ${isodir}
    fi

    for f in ${isodir}/isolinux.cfg ${isodir}/syslinux.cfg; do
        sed -i "s/^timeout.*/timeout ${TIMEOUT}/" ${f}
    done

    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        sed -i "s/^timeout=.*/timeout=${GRUB_TIMEOUT}/" ${f}

        grep -q "^  set timeout=" ${f}
        if [ $? -eq 0 ]; then
            # Submenu timeout is already added. Update the value
            sed -i -e "s#^  set timeout=.*#  set timeout=${GRUB_TIMEOUT}#" ${f}
            if [ $? -ne 0 ]; then
                echo "Failed to update grub timeout"
                exit 1
            fi
        else
            # Parameter doesn't exist. Add it to the cmdline
            sed -i -e "/^submenu/a \ \ set timeout=${GRUB_TIMEOUT}" ${f}
            if [ $? -ne 0 ]; then
                echo "Failed to add grub timeout"
                exit 1
            fi
        fi
    done
}

declare INPUT_ISO=
declare OUTPUT_ISO=
declare ORIG_PWD=$PWD
declare ADDON=
declare -a PARAMS
declare DEFAULT_LABEL=
declare DEFAULT_GRUB_ENTRY=
declare UPDATE_TIMEOUT="no"
declare -i TIMEOUT=0
declare GRUB_TIMEOUT=-1

while getopts "hi:o:a:p:d:t:" opt; do
    case $opt in
        i)
            INPUT_ISO=$OPTARG
            ;;
        o)
            OUTPUT_ISO=$OPTARG
            ;;
        a)
            ADDON=$OPTARG
            ;;
        p)
            PARAMS+=(${OPTARG})
            ;;
        d)
            DEFAULT_LABEL=${OPTARG}

            case ${DEFAULT_LABEL} in
                0)
                    DEFAULT_GRUB_ENTRY="standard>serial"
                    ;;
                1)
                    DEFAULT_GRUB_ENTRY="standard>graphical"
                    ;;
                2)
                    DEFAULT_GRUB_ENTRY="aio>serial"
                    ;;
                3)
                    DEFAULT_GRUB_ENTRY="aio>graphical"
                    ;;
                4)
                    DEFAULT_GRUB_ENTRY="aio-lowlat>serial"
                    ;;
                5)
                    DEFAULT_GRUB_ENTRY="aio-lowlat>graphical"
                    ;;
                'NULL')
                    DEFAULT_GRUB_ENTRY=2
                    ;;
                *)
                    echo "Invalid default boot menu option: ${DEFAULT_LABEL}" >&2
                    usage
                    exit 1
                    ;;
            esac
            ;;
        t)
            let -i timeout_arg=${OPTARG}
            if [ ${timeout_arg} -gt 0 ]; then
                let -i TIMEOUT=${timeout_arg}*10
                GRUB_TIMEOUT=${timeout_arg}
            elif [ ${timeout_arg} -eq 0 ]; then
                GRUB_TIMEOUT=0.001
            fi

            UPDATE_TIMEOUT="yes"
            ;;
        *)
            usage
            exit 1
            ;;
    esac
done

if [ "${DEFAULT_LABEL}" = "NULL" ]; then
    # Reset timeouts to default
    TIMEOUT=0
    GRUB_TIMEOUT=-1
    UPDATE_TIMEOUT="yes"
fi

check_requirements

check_required_param "-i" "${INPUT_ISO}"
check_required_param "-o" "${OUTPUT_ISO}"

if [ ! -f ${INPUT_ISO} ]; then
    echo "Input file does not exist: ${INPUT_ISO}"
    exit 1
fi

if [ -f ${OUTPUT_ISO} ]; then
    echo "Output file already exists: ${OUTPUT_ISO}"
    exit 1
fi

shift $((OPTIND-1))

trap cleanup EXIT

BUILDDIR=$(mktemp -d -p $PWD updateiso_build_XXXXXX)
if [ -z "${BUILDDIR}" -o ! -d ${BUILDDIR} ]; then
    echo "Failed to create builddir. Aborting..."
    exit $rc
fi

mount_iso ${INPUT_ISO}

rsync -a ${MNTDIR}/ ${BUILDDIR}/
rc=$?
if [ $rc -ne 0 ]; then
    echo "Call to rsync ISO content. Aborting..."
    exit $rc
fi

unmount_iso

if [ ${#PARAMS[@]} -gt 0 ]; then
    for p in ${PARAMS[@]}; do
        param=${p%%=*} # Strip from the first '=' on
        value=${p#*=}  # Strip to the first '='

        update_parameter ${BUILDDIR} "${param}" "${value}"
    done
fi

if [ -n "${DEFAULT_LABEL}" ]; then
    set_default_label ${BUILDDIR}
fi

if [ "${UPDATE_TIMEOUT}" = "yes" ]; then
    set_timeout ${BUILDDIR}
fi

if [ -n "${ADDON}" ]; then
    \rm -f ${BUILDDIR}/ks-addon.cfg
    \cp ${ADDON} ${BUILDDIR}/ks-addon.cfg
    if [ $? -ne 0 ]; then
        echo "Error: Failed to copy ${ADDON}"
        exit 1
    fi
fi

unmount_efiboot_img

# Rebuild the ISO
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

echo "Updated ISO: ${OUTPUT_ISO}"

