#!/bin/bash
#
# Copyright (c) 2020-2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Common bash utility functions for StarlingX ISO tools
#
# Global shellcheck ignores:
# shellcheck disable=2181

declare BUILDDIR=
declare EFIBOOT_IMG_LOOP=
declare EFI_MOUNT=
declare MNTDIR=
declare WORKDIR=
declare VERBOSE=

function ilog {
    echo "$(date "+%F %H:%M:%S"): $*" >&2
}

function elog {
    echo "$(date "+%F %H:%M:%S") Error: $*" >&2
    exit 1
}

function vlog {
    [ "${VERBOSE}" = true ] && echo "$(date "+%F %H:%M:%S"): $*" >&2
}

function common_cleanup {
    unmount_efiboot_img

    if [ -n "${MNTDIR}" ] && [ -d "${MNTDIR}" ]; then
        unmount_iso
    fi

    if [ -n "${BUILDDIR}" ] && [ -d "${BUILDDIR}" ]; then
        chmod -R 755 "${BUILDDIR}"
        rm -rf "${BUILDDIR}"
    fi

    if [ -n "${WORKDIR}" ] && [ -d "${WORKDIR}" ]; then
        chmod -R 755 "${WORKDIR}"
        rm -rf "${WORKDIR}"
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

    if [ ${#@} -gt 0 ]; then
        required_utils+=( "$@" )
    fi

    local -i missing=0

    if which which >&/dev/null -ne 0 ; then
        elog "unable to find 'which' utility. Aborting..."
    fi

    for req in "${required_utils[@]}"; do
        which "${req}" >&/dev/null
        if [ $? -ne 0 ] ; then
            ilog "unable to find required utility: ${req}"
            (( missing++ ))
        fi
    done

    if [ "${missing}" -gt 0 ]; then
        elog "one or more required utilities are missing. Aborting..."
    else
        ilog "all required iso utilities present"
    fi
}

function check_required_param {
    local param="${1}"
    local value="${2}"

    if [ -z "${value}" ]; then
        elog "required parameter ${param} is not set"
    fi
}

function check_files_exist {
    for value in "$@"; do
        if [ ! -f "${value}" ]; then
            elog "file path '${value}' is invalid"
        fi
    done
}

function check_files_size {
    local file_size

    # Aprox 4 GB file size limit for iso file systems.
    local file_size_limit=4000000000

    for value in "$@"; do
        file_size=$(stat --printf="%s" "${value}")
        if [ "${file_size}" -gt "${file_size_limit}" ]; then
            elog "file size of '${value}' exceeds 4 GB limit"
        fi
    done
}

function mount_iso {
    local input_iso=$1
    local basedir=${2:-$PWD}
    local guestmount_dev=${3:-"/dev/sda1"}

    MNTDIR=$(mktemp -d -p "$basedir" stx-iso-utils_mnt_XXXXXX)
    if [ -z "${MNTDIR}" ] || [ ! -d "${MNTDIR}" ]; then
        elog "Failed to create mntdir $MNTDIR. Aborting..."
    fi
    ilog "mount_iso input_iso=${input_iso} basedir=${basedir} MNTDIR=${MNTDIR}"

    if [ $UID -eq 0 ]; then
        # Mount the ISO
        ilog "mounting ${input_iso} to ${MNTDIR}"
        mount -o loop "${input_iso}" "${MNTDIR}" >&/dev/null
        if [ $? -ne 0 ]; then
            elog "Failed to mount ${input_iso}" >&2
        fi
    else
        # As non-root user, mount the ISO using guestmount
        ilog "guestmounting ${input_iso} using ${guestmount_dev} to ${MNTDIR}"

        guestmount -a "${input_iso}" -m "${guestmount_dev}" --ro "${MNTDIR}"
        rc=$?
        if [ "${rc}" -ne 0 ]; then
            # Add a retry
            ilog "guestmount failed with rc=${rc}. Retrying once..."

            guestmount -a "${input_iso}" -m "${guestmount_dev}" --ro "${MNTDIR}" >&/dev/null
            rc=$?
            if [ ${rc} -ne 0 ]; then
                elog "guestmount retry failed with rc=$rc. Aborting..."
            else
                vlog "guestmount retry succeeded"
            fi
        else
            vlog "guestmount succeeded."
        fi
    fi
}

function unmount_iso {
    if [ "${UID}" -eq 0 ]; then
        ilog "unmounting ${MNTDIR}"
        umount "${MNTDIR}" >&/dev/null
    else
        guestunmount "${MNTDIR}" >&/dev/null
    fi
    rmdir "${MNTDIR}"
}

function mount_efiboot_img {
    local isodir=$1

    if [ -e "${isodir}/images/efiboot.img" ]; then
        local efiboot_img="${isodir}/images/efiboot.img"
    else
        local efiboot_img="${isodir}/efi.img"
        # LAT installs the efi.img as read only. Need to make it wr
        chmod 644 "${efiboot_img}"
        chmod 775 "${isodir}/isolinux"
        chmod 644 "${isodir}/isolinux/isolinux.cfg"
        chmod 775 "${isodir}/EFI/BOOT"
    fi

    local loop_setup_output=

    if [ $UID -eq 0 ]; then
        # As root, setup a writeable loop device for the
        # efiboot.img file and mount it
        loop_setup_output=$(losetup --show -f "${efiboot_img}")
        if [ $? -ne 0 ]; then
            elog "Failed losetup" >&2
        fi

        EFIBOOT_IMG_LOOP=${loop_setup_output}

        EFI_MOUNT=$(mktemp -d -p /mnt -t EFI-noudev.XXXXXX)
        mount "${EFIBOOT_IMG_LOOP}" "${EFI_MOUNT}"
        if [ $? -ne 0 ]; then
            elog "Failed to mount loop device ${EFIBOOT_IMG_LOOP}" >&2
        fi
    else
        # As non-root user, we can use the udisksctl to setup a loop device
        # and mount the efiboot.img, with read/write access.
        loop_setup_output=$(udisksctl loop-setup -f "${efiboot_img}" --no-user-interaction)
        if [ $? -ne 0 ]; then
            elog "Failed udisksctl loop-setup" >&2
        fi

        EFIBOOT_IMG_LOOP=$(echo "${loop_setup_output}" | awk '{print $5;}' | sed -e 's/\.$//g')
        if [ -z "${EFIBOOT_IMG_LOOP}" ]; then
            echo "Error: Failed to determine loop device from command output:" >&2
            echo "${loop_setup_output}" >&2
            exit 1
        fi

        udisksctl mount -b "${EFIBOOT_IMG_LOOP}" >&/dev/null
        if [ $? -ne 0 ]; then
            echo "Error: Failed udisksctl mount" >&2
            exit 1
        fi

        EFI_MOUNT=$(udisksctl info -b "${EFIBOOT_IMG_LOOP}" | grep MountPoints | awk '{print $2;}')
        if [ -z "${EFI_MOUNT}" ]; then
            echo "Error: Failed to determine mount point from udisksctl info command" >&2
            exit 1
        fi
    fi
}

function unmount_efiboot_img {
    if [ $UID -eq 0 ]; then
        if [ -n "${EFI_MOUNT}" ]; then
            mountpoint -q "${EFI_MOUNT}" && umount "${EFI_MOUNT}"
            rmdir "${EFI_MOUNT}"
            EFI_MOUNT=
        fi

        if [ -n "${EFIBOOT_IMG_LOOP}" ]; then
            losetup -d "${EFIBOOT_IMG_LOOP}"
            EFIBOOT_IMG_LOOP=
        fi
    else
        if [ -n "${EFIBOOT_IMG_LOOP}" ]; then
            udisksctl unmount -b "${EFIBOOT_IMG_LOOP}" >&/dev/null
            udisksctl loop-delete -b "${EFIBOOT_IMG_LOOP}"
            EFI_MOUNT=
            EFIBOOT_IMG_LOOP=
        fi
    fi
}

function update_parameter {
    local isodir=$1
    local param=$2
    local value=$3

    ilog "updating parameter ${param} to ${param}=${value}"
    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img "${isodir}"
    fi

    for f in "${isodir}"/isolinux/isolinux.cfg ; do
        grep -q "^[[:space:]]*append\>.*[[:space:]]${param}=" "${f}"
        if [ $? -eq 0 ]; then
            # Parameter already exists. Update the value
            sed -i -e "s#^\([[:space:]]*append\>.*${param}\)=[^[:space:]]*#\1=${value}#" "${f}"
            if [ $? -ne 0 ]; then
                elog "Failed to update parameter ($param)"
            fi
        else
            # Parameter doesn't exist. Add it to the cmdline
            sed -i -e "s|^\([[:space:]]*append\>.*\)|\1 ${param}=${value}|" "${f}"
            if [ $? -ne 0 ]; then
                elog "Failed to add parameter ($param)"
            fi
        fi
    done

    for f in "${isodir}/EFI/BOOT/grub.cfg" "${EFI_MOUNT}/EFI/BOOT/grub.cfg" ; do
        grep -q "^[[:space:]]*linux\>.*[[:space:]]${param}=" "${f}"
        if [ $? -eq 0 ]; then
            # Parameter already exists. Update the value
            sed -i -e "s#^\([[:space:]]*linux\>.*${param}\)=[^[:space:]]*#\1=${value}#" "${f}"
            if [ $? -ne 0 ]; then
                elog "Failed to update parameter ($param)"
            fi
        else
            # Parameter doesn't exist. Add it to the cmdline
            sed -i -e "s|^\([[:space:]]*linux\>.*\)|\1 ${param}=${value}|" "${f}"
            if [ $? -ne 0 ]; then
                elog "Failed to add parameter ($param)"
            fi
        fi
    done
}

