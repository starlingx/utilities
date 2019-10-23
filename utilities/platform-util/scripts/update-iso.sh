#!/bin/bash
#
# Copyright (c) 2019 Wind River Systems, Inc.
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

function check_requirements {
    local -a required_utils=(
        rsync
        mkisofs
        isohybrid
        implantisomd5
    )
    if [ $UID -ne 0 ]; then
        # If running as non-root user, additional utils are required
        required_utils+=(
            guestmount
            guestunmount
            udisksctl
        )
    fi

    local -i missing=0

    for req in ${required_utils[@]}; do
        which ${req} >&/dev/null
        if [ $? -ne 0 ]; then
            echo "Unable to find required utility: ${req}" >&2
            let -i missing++
        fi
    done

    if [ ${missing} -gt 0 ]; then
        echo "One or more required utilities are missing. Aborting..." >&2
        exit 1
    fi
}

function mount_iso {
    if [ $UID -eq 0 ]; then
        # Mount the ISO
        mount -o loop ${INPUT_ISO} ${MNTDIR}
        if [ $? -ne 0 ]; then
            echo "Failed to mount ${INPUT_ISO}" >&2
            exit 1
        fi
    else
        # As non-root user, mount the ISO using guestmount
        guestmount -a ${INPUT_ISO} -m /dev/sda1 --ro ${MNTDIR}
        rc=$?
        if [ $rc -ne 0 ]; then
            # Add a retry
            echo "Call to guestmount failed with rc=$rc. Retrying once..."

            guestmount -a ${INPUT_ISO} -m /dev/sda1 --ro ${MNTDIR}
            rc=$?
            if [ $rc -ne 0 ]; then
                echo "Call to guestmount failed with rc=$rc. Aborting..."
                exit $rc
            fi
        fi
    fi
}

function unmount_iso {
    if [ $UID -eq 0 ]; then
        umount ${MNTDIR}
    else
        guestunmount ${MNTDIR}
    fi
    rmdir ${MNTDIR}
}

function mount_efiboot_img {
    local isodir=$1
    local efiboot_img=${isodir}/images/efiboot.img
    local loop_setup_output=

    if [ $UID -eq 0 ]; then
        # As root, setup a writeable loop device for the
        # efiboot.img file and mount it
        loop_setup_output=$(losetup --show -f ${efiboot_img})
        if [ $? -ne 0 ]; then
            echo "Failed losetup" >&2
            exit 1
        fi

        EFIBOOT_IMG_LOOP=${loop_setup_output}

        EFI_MOUNT=$(mktemp -d -p /mnt -t EFI-noudev.XXXXXX)
        mount ${EFIBOOT_IMG_LOOP} ${EFI_MOUNT}
        if [ $? -ne 0 ]; then
            echo "Failed to mount loop device ${EFIBOOT_IMG_LOOP}" >&2
            exit 1
        fi
    else
        # As non-root user, we can use the udisksctl to setup a loop device
        # and mount the efiboot.img, with read/write access.
        loop_setup_output=$(udisksctl loop-setup -f ${efiboot_img} --no-user-interaction)
        if [ $? -ne 0 ]; then
            echo "Failed udisksctl loop-setup" >&2
            exit 1
        fi

        EFIBOOT_IMG_LOOP=$(echo ${loop_setup_output} | awk '{print $5;}' | sed -e 's/\.$//g')
        if [ -z "${EFIBOOT_IMG_LOOP}" ]; then
            echo "Failed to determine loop device from command output:" >&2
            echo "${loop_setup_output}" >&2
            exit 1
        fi

        udisksctl mount -b ${EFIBOOT_IMG_LOOP}
        if [ $? -ne 0 ]; then
            echo "Failed udisksctl mount" >&2
            exit 1
        fi

        EFI_MOUNT=$(udisksctl info -b ${EFIBOOT_IMG_LOOP} | grep MountPoints | awk '{print $2;}')
        if [ -z "${EFI_MOUNT}" ]; then
            echo "Failed to determine mount point from udisksctl info command" >&2
            exit 1
        fi
    fi
}

function unmount_efiboot_img {
    if [ $UID -eq 0 ]; then
        if [ -n "${EFI_MOUNT}" ]; then
            mountpoint -q ${EFI_MOUNT} && umount ${EFI_MOUNT}
            rmdir ${EFI_MOUNT}
            EFI_MOUNT=
        fi

        if [ -n "${EFIBOOT_IMG_LOOP}" ]; then
            losetup -d ${EFIBOOT_IMG_LOOP}
            EFIBOOT_IMG_LOOP=
        fi
    else
        if [ -n "${EFIBOOT_IMG_LOOP}" ]; then
            udisksctl unmount -b ${EFIBOOT_IMG_LOOP}
            udisksctl loop-delete -b ${EFIBOOT_IMG_LOOP}
            EFI_MOUNT=
            EFIBOOT_IMG_LOOP=
        fi
    fi
}

function update_parameter {
    local isodir=$1
    local param=$2
    local value=$3

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img ${isodir}
    fi

    for f in ${isodir}/isolinux.cfg ${isodir}/syslinux.cfg; do
        grep -q "^[[:space:]]*append\>.*[[:space:]]${param}=" ${f}
        if [ $? -eq 0 ]; then
            # Parameter already exists. Update the value
            sed -i -e "s#^\([[:space:]]*append\>.*${param}\)=[^[:space:]]*#\1=${value}#" ${f}
            if [ $? -ne 0 ]; then
                echo "Failed to update parameter ($param)"
                exit 1
            fi
        else
            # Parameter doesn't exist. Add it to the cmdline
            sed -i -e "s|^\([[:space:]]*append\>.*\)|\1 ${param}=${value}|" ${f}
            if [ $? -ne 0 ]; then
                echo "Failed to add parameter ($param)"
                exit 1
            fi
        fi
    done

    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        grep -q "^[[:space:]]*linuxefi\>.*[[:space:]]${param}=" ${f}
        if [ $? -eq 0 ]; then
            # Parameter already exists. Update the value
            sed -i -e "s#^\([[:space:]]*linuxefi\>.*${param}\)=[^[:space:]]*#\1=${value}#" ${f}
            if [ $? -ne 0 ]; then
                echo "Failed to update parameter ($param)"
                exit 1
            fi
        else
            # Parameter doesn't exist. Add it to the cmdline
            sed -i -e "s|^\([[:space:]]*linuxefi\>.*\)|\1 ${param}=${value}|" ${f}
            if [ $? -ne 0 ]; then
                echo "Failed to add parameter ($param)"
                exit 1
            fi
        fi
    done
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
        grep -q "^  set timeout=" ${f}
        if [ $? -eq 0 ]; then
            # Submenu timeout is already added. Update the value
            sed -i -e "s#^  set timeout=.*#${GRUB_TIMEOUT}#" ${f}
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
declare -i GRUB_TIMEOUT=-1
declare EFI_MOUNT=
declare EFIBOOT_IMG_LOOP=

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
                let -i GRUB_TIMEOUT=${timeout_arg}
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

if [ -z "$INPUT_ISO" -o -z "$OUTPUT_ISO" ]; then
    usage
    exit 1
fi

if [ ! -f ${INPUT_ISO} ]; then
    echo "Input file does not exist: ${INPUT_ISO}"
    exit 1
fi

if [ -f ${OUTPUT_ISO} ]; then
    echo "Output file already exists: ${OUTPUT_ISO}"
    exit 1
fi

shift $((OPTIND-1))

declare MNTDIR=
declare BUILDDIR=
declare WORKDIR=

function cleanup {
    unmount_efiboot_img

    if [ -n "$MNTDIR" -a -d "$MNTDIR" ]; then
        unmount_iso
    fi

    if [ -n "$BUILDDIR" -a -d "$BUILDDIR" ]; then
        \rm -rf $BUILDDIR
    fi

    if [ -n "$WORKDIR" -a -d "$WORKDIR" ]; then
        \rm -rf $WORKDIR
    fi
}

trap cleanup EXIT

MNTDIR=$(mktemp -d -p $PWD updateiso_mnt_XXXXXX)
if [ -z "${MNTDIR}" -o ! -d ${MNTDIR} ]; then
    echo "Failed to create mntdir. Aborting..."
    exit $rc
fi

BUILDDIR=$(mktemp -d -p $PWD updateiso_build_XXXXXX)
if [ -z "${BUILDDIR}" -o ! -d ${BUILDDIR} ]; then
    echo "Failed to create builddir. Aborting..."
    exit $rc
fi

mount_iso

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

