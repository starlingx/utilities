#!/bin/bash
#
# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Common bash utility functions for StarlingX ISO tools
#

declare BUILDDIR=
declare EFIBOOT_IMG_LOOP=
declare EFI_MOUNT=
declare MNTDIR=
declare WORKDIR=

function common_cleanup {
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

function common_check_requirements {
    local -a required_utils=(
        awk
        grep
        implantisomd5
        isohybrid
        mkisofs
        mktemp
        rm
        rmdir
        rsync
        sed
    )
    if [ $UID -eq 0 ]; then
        required_utils+=(
            losetup
            mount
            mountpoint
            umount
        )
    else
        # If running as non-root user, additional utils are required
        required_utils+=(
            guestmount
            guestunmount
            udisksctl
        )
    fi

    required_utils+=( $@ )

    local -i missing=0

    which which >&/dev/null
    if [ $? -ne 0 ]; then
        log_error "Unable to find 'which' utility. Aborting..."
        exit 1
    fi

    for req in ${required_utils[@]}; do
        which ${req} >&/dev/null
        if [ $? -ne 0 ]; then
            log_error "Unable to find required utility: ${req}"
            let -i missing++
        fi
    done

    if [ ${missing} -gt 0 ]; then
        log_error "One or more required utilities are missing. Aborting..."
        exit 1
    fi
}

function check_required_param {
    local param="${1}"
    local value="${2}"

    if [ -z "${value}" ]; then
        log_error "Required parameter ${param} is not set"
        exit 1
    fi
}

function check_files_exist {
    for value in "$@"; do
        if [ ! -f "${value}" ]; then
            log_error "file path '${value}' is invalid"
            exit 1
        fi
    done
}

function check_files_size {
    local file_size

    # Aprox 4 GB file size limit for iso file systems.
    local file_size_limit=4000000000

    for value in "$@"; do
        file_size=$(stat --printf="%s" ${value})
        if [ ${file_size} -gt ${file_size_limit} ]; then
            log_error "file size of '${value}' exceeds 4 GB limit"
            exit 1
        fi
    done
}

function mount_iso {
    local input_iso=$1

    MNTDIR=$(mktemp -d -p $PWD stx-iso-utils_mnt_XXXXXX)
    if [ -z "${MNTDIR}" -o ! -d ${MNTDIR} ]; then
        log_error "Failed to create mntdir. Aborting..."
        exit 1
    fi

    if [ $UID -eq 0 ]; then
        # Mount the ISO
        mount -o loop ${input_iso} ${MNTDIR}
        if [ $? -ne 0 ]; then
            echo "Failed to mount ${input_iso}" >&2
            exit 1
        fi
    else
        # As non-root user, mount the ISO using guestmount
        guestmount -a ${input_iso} -m /dev/sda1 --ro ${MNTDIR}
        rc=$?
        if [ $rc -ne 0 ]; then
            # Add a retry
            echo "Call to guestmount failed with rc=$rc. Retrying once..."

            guestmount -a ${input_iso} -m /dev/sda1 --ro ${MNTDIR}
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

    if [ -e ${isodir}/images/efiboot.img ]; then
        local efiboot_img=${isodir}/images/efiboot.img
    else
        local efiboot_img=${isodir}/efi.img
    fi

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
                log_error "Failed to update parameter ($param)"
                exit 1
            fi
        else
            # Parameter doesn't exist. Add it to the cmdline
            sed -i -e "s|^\([[:space:]]*append\>.*\)|\1 ${param}=${value}|" ${f}
            if [ $? -ne 0 ]; then
                log_error "Failed to add parameter ($param)"
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
                log_error "Failed to update parameter ($param)"
                exit 1
            fi
        else
            # Parameter doesn't exist. Add it to the cmdline
            sed -i -e "s|^\([[:space:]]*linuxefi\>.*\)|\1 ${param}=${value}|" ${f}
            if [ $? -ne 0 ]; then
                log_error "Failed to add parameter ($param)"
                exit 1
            fi
        fi
    done
}

