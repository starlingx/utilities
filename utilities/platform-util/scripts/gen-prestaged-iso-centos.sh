#!/bin/bash
#
# Copyright (c) 2021-2023 Wind River Systems, Inc.
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

# shellcheck disable=1091    # don't warn about following 'source <file>'
# shellcheck disable=2164    # don't warn about pushd/popd failures
# shellcheck disable=2181    # don't warn about using rc=$?

function log_fatal {
    echo "$(date "+%F %H:%M:%S") FATAL: $*" >&2
    exit 1
}

function log_error {
    echo "$(date "+%F %H:%M:%S"): ERROR: $*" >&2
}

function log_info {
    echo "$(date "+%F %H:%M:%S"): INFO: $*" >&2
}

# Usage manual.
function usage {
    cat <<ENDUSAGE
Utility to convert a StarlingX installation iso into a CentOS prestaged subcloud installation iso.

Usage:
   $(basename "$0") --input <input bootimage.iso>
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
    common_check_requirements md5sum rpm2cpio cpio cp find
}

function set_default_label {
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img "${isodir}"
    fi

    for f in "${isodir}/isolinux.cfg" "${isodir}/syslinux.cfg"; do
        if [ "${DEFAULT_LABEL}" = "NULL" ]; then
            # Remove default, if set
            grep -q '^default' "${f}"
            if [ $? -eq 0 ]; then
                sed -i '/^default/d' "${f}"
            fi
        else
            grep -q '^default' "${f}"
            if [ $? -ne 0 ]; then
                cat <<EOF >> "${f}"

default ${DEFAULT_SYSLINUX_ENTRY}
EOF
            else
                sed -i "s/^default.*/default ${DEFAULT_SYSLINUX_ENTRY}/" "${f}"
            fi
        fi
    done

    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        sed -i "s/^default=.*/default=\"${DEFAULT_GRUB_ENTRY}\"/" "${f}"
    done
}

function set_timeout {
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img "${isodir}"
    fi

    for f in ${isodir}/isolinux.cfg ${isodir}/syslinux.cfg; do
        sed -i "s/^timeout.*/timeout ${TIMEOUT}/" "${f}"
    done

    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        sed -i "s/^timeout=.*/timeout=${GRUB_TIMEOUT}/" "${f}"

        grep -q "^  set timeout=" "${f}"
        if [ $? -eq 0 ]; then
            # Submenu timeout is already added. Update the value
            sed -i -e "s#^  set timeout=.*#  set timeout=${GRUB_TIMEOUT}#" "${f}"
            if [ $? -ne 0 ]; then
                log_error "Failed to update grub timeout"
                exit 1
            fi
        else
            # Parameter doesn't exist. Add it to the cmdline
            sed -i -e "/^submenu/a \ \ set timeout=${GRUB_TIMEOUT}" "${f}"
            if [ $? -ne 0 ]; then
                log_error "Failed to add grub timeout"
                exit 1
            fi
        fi
    done
}

function mkdir_on_iso {
    local dir="${1}"

    local final_dir="${BUILDDIR}/${dir}"

    mkdir -p "${final_dir}"
    if [ $? -ne 0 ]; then
        log_error "Error: mkdir_on_iso: Failed to create directory '${dir}'"
        exit 1
    fi
}

function normalized_path {
    local path="${1}"
    local default_fn="${2}"

    local path_name path_dir
    path_name="$(basename "${path}")"
    path_dir="$(dirname "${path}")"

    # If 'path' ends in '/' then path was intended to be a directory
    if [ "${path: -1:1}" = "/" ]; then   # Note: space is required after : to distinguish from ${path:-...}
        # Drop the trailing '/'
        path_dir="${path:0:-1}"
        path_name="${default_fn}"
    fi

    # drop leading '.' from path_dir
    if [ "${path_dir:0:1}" == "." ]; then
        path_dir="${path_dir:1}"
    fi

    # drop leading '/' from path_dir
    if [ "${path_dir:0:1}" == "/" ]; then
        path_dir="${path_dir:1}"
    fi

    if [ -z "${path_dir}" ]; then
        echo "${path_name}"
    else
        echo "${path_dir}/${path_name}"
    fi
}

function copy_to_iso {
    local src="${1}"
    local dest="${2}"
    local md5="${3}"
    local overwrite="${4}"

    local default_dest=
    local final_dest=
    local final_dest_dir=
    local final_md5=

    if [ -z "${src}" ] || [ -z "${dest}" ]; then
        log_error "Error: copy_to_iso: missing argument"
        exit 1
    fi

    if [ ! -f "${src}" ]; then
        log_error "Error: copy_to_iso: source file doesn't exist '${src}'"
        exit 1
    fi

    default_dest="$(basename "${src}")"
    dest="$(normalized_path "${dest}" "${default_dest}")"
    final_dest="${BUILDDIR}/${dest}"
    final_dest_dir="$(dirname "${final_dest}")"

    if [ -n "${md5}" ]; then
        case "${md5}" in
            y | Y | yes | YES )
                # Use a default name, in same dir as dest
                md5="$(dirname "${dest}")"
                ;;
        esac

        final_md5="${BUILDDIR}/${md5}"
    fi

    if [ -z "${overwrite}" ] || [ "${overwrite}" == 'n' ]; then
        if [ -f "${final_dest}" ]; then
            log_error "Error: copy_to_iso: destination already exists '${final_dest}'"
            exit 1
        fi
    fi

    if [ ! -d "${final_dest_dir}" ]; then
        log_error "Error: copy_to_iso: destination directory does not exist '${final_dest_dir}'"
        exit 1
    fi

    cp -f "${src}" "${final_dest}"
    if [ $? -ne 0 ]; then
        log_error "Error: Failed to copy '${src}' to '${final_dest}'"
        exit 1
    fi

    if [ -n "${final_md5}" ]; then
        pushd "${final_dest_dir}" > /dev/null
            md5sum "$(basename "${final_dest}")" >> "${final_md5}"
        popd > /dev/null
    fi
}

#
# find_in_mounted_iso: Find the relative path of a file name or directory
#                      within the pre-mounted iso found at '${MNTDIR}'.
#                      Returns the first match found only.
#                      Not intended for wildcard searches.
#                      The returned relative path is prefixed by './'.
#                      Returns '1' if not found.
#
function find_in_mounted_iso {
    local target="${1}"
    local path=

    pushd "${MNTDIR}" > /dev/null
    path=$(find . -name "${target}" 2> /dev/null)
    popd > /dev/null
    if [ -z "${path}" ]; then
        return 1
    fi
    echo "${path}"
    return 0
}

#
# find_in_rpm: Find the relative path of a file in an rpm file.
#              Returns the first match found only.
#              Not intended for wildcard searches.
#              The returned relative path is prefixed by './'.
#              Returns '1' if not found.
#
function find_in_rpm {
    local rpm="${1}"
    local target="${2}"
    local path=

    path=$(rpm2cpio "${rpm}" | cpio -t 2> /dev/null | grep "/${target}$" | head -n 1)
    if [ -z "${path}" ]; then
        return 1
    fi
    echo "${path}"
    return 0
}

#
# extract_patch: Extract a patch to the current directory.
#
function extract_patch {
    local patch="${1}"

    if [ -z "${patch}" ]; then
        log_error "Error: extract_patch: missing argument"
        return 1
    fi

    # Following the convention established in patch-functions.py
    tar xf "${patch}" || return 1
    tar xf software.tar || return 1
}

function abspath {
    local path="${1}"

    if [ "${path:0:1}" != "/" ] && [ "${path:0:1}" != "~" ]; then
        path="${PWD}/${path}"
    fi
    echo "${path}"
}

#
# find_in_patch: Find the location of a file in any of the rpms of a patch.
#                Returns a compound path consisting of two parts ...
#                          '<rpm-name>:<relative-path>'
#                Returns the first match found only.
#                Not intended for wildcard searches.
#                The relative path component is prefixed by './'.
#                Returns '1' if not found in any rpm of the patch.
#
function find_in_patch {
    local patch="${1}"
    local target="${2}"

    local patchdir=
    local found_rpm=
    local path=

    if [ -z "${patch}" ] || [ -z "${target}" ]; then
        log_error "Error: find_in_patch: missing argument"
        return 1
    fi

    if [ ! -f "${patch}" ]; then
        log_error "Error: find_in_patch: patch not found at '${patch}'"
        return 1
    fi

    # make sure patch is an absolute path
    patch="$(abspath "${patch}")"

    patchdir=$(mktemp -d -p "${PWD}" updateiso_build_patch_XXXXXX)
    pushd "${patchdir}" > /dev/null
        extract_patch "${patch}"
        # shellcheck disable=2044
        for rpm in $(find . -name '*.rpm'); do
            if path="$(find_in_rpm "${rpm}" "${target}")"; then
                found_rpm="$(basename "${rpm}")"
                break
            fi
        done
    popd > /dev/null
    rm -rf "${patchdir}"
    if [ -z "${found_rpm}" ]; then
        return 1
    fi
    echo "${found_rpm}:${path}"
    return 0
}

function copy_rpm_file_to_iso {
    local rpm="${1}"
    local src="${2}"
    local dest="${3}"
    local overwrite="${4}"

    local patchdir=
    local rc=0

    if [ -z "${rpm}" ] || [ -z "${src}" ] || [ -z "${dest}" ]; then
        log_error "Error: copy_rpm_file_to_iso: missing argument"
        return 1
    fi

    if [ ! -f "${rpm}" ]; then
        log_error "Error: copy_rpm_file_to_iso: rpm not found at '${rpm}'"
        return 1
    fi

    # make sure patch is an absolute path
    rpm="$(abspath "${rpm}")"

    patchdir=$(mktemp -d -p "${PWD}" updateiso_build_rpm_XXXXXX)
    pushd "${patchdir}" > /dev/null
        rpm2cpio "${rpm}" | cpio -imdv "${src}"
        if [ $? -ne 0 ]; then
            log_error "copy_rpm_file_to_iso: extraction error from rpm '$(basename "${rpm}")'"
            rc=1
        elif [ ! -e "${src}" ]; then
            log_error "copy_rpm_file_to_iso: file '${src}' not found in rpm '$(basename "${rpm}")'"
            rc=1
        else
            # we do not need an md5 here, so leaving third argument empty
            copy_to_iso "${src}" "${dest}" "" "${overwrite}"
            rc=$?
        fi
    popd > /dev/null
    rm -rf "${patchdir}"
    return ${rc}
}

function copy_patch_file_to_iso {
    local patch="${1}"
    local rpm="${2}"
    local src="${3}"
    local dest="${4}"
    local overwrite="${5}"

    local rpmdir=
    local rc=0

    if [ -z "${patch}" ] || [ -z "${rpm}" ] || [ -z "${src}" ] || [ -z "${dest}" ]; then
        log_error "Error: copy_patch_file_to_iso: missing argument"
        return 1
    fi

    if [ ! -f "${patch}" ]; then
        log_error "Error: copy_patch_file_to_iso: patch not found at '${patch}'"
        return 1
    fi

    # make sure patch is an absolute path
    patch="$(abspath "${patch}")"

    rpmdir=$(mktemp -d -p "${PWD}" updateiso_build_patch_XXXXXX)
    pushd "${rpmdir}" > /dev/null
        extract_patch "${patch}"
        if [ ! -f "${rpm}" ]; then
            log_error "copy_patch_file_to_iso: rpm '${rpm}' not found in patch '$(basename "${patch}")'"
            rc=1
        else
            copy_rpm_file_to_iso "${rpm}" "${src}" "${dest}" "${overwrite}"
            rc=$?
        fi
    popd > /dev/null
    rm -rf "${rpmdir}"
    if [ -z "${found_rpm}" ]; then
        return 1
    fi
    echo "${found_rpm}:${path}"
    return 0

}

function generate_boot_cfg {
    log_info "Generating boot config"
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img "${isodir}"
    fi

    local COMMON_ARGS="inst.text inst.gpt boot_device=sda rootfs_device=sda"
    COMMON_ARGS="${COMMON_ARGS} biosdevname=0 usbcore.autosuspend=-1"
    COMMON_ARGS="${COMMON_ARGS} security_profile=standard user_namespace.enable=1"
    COMMON_ARGS="${COMMON_ARGS} inst.stage2=hd:LABEL=${VOLUME_LABEL} inst.ks=hd:LABEL=${VOLUME_LABEL}:/${PRESTAGED_KICKSTART}"
    if [ -n "${FORCE_INSTALL}" ]; then
        COMMON_ARGS="${COMMON_ARGS} force_install"
    fi
    log_info "COMMON_ARGS: ${COMMON_ARGS}"

    for f in "${isodir}/isolinux.cfg" "${isodir}/syslinux.cfg"; do
        cat <<EOF > "${f}"
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
    menu title ${MENU_NAME}

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
        cat <<EOF > "${f}"
default=${DEFAULT_GRUB_ENTRY}
timeout=${GRUB_TIMEOUT}
search --no-floppy --set=root -l '${VOLUME_LABEL}'

menuentry "${MENU_NAME}" {
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

# Source shared utility functions
DIR_NAME=$(dirname "$0")
if [ ! -e "${DIR_NAME}"/stx-iso-utils-centos.sh ]; then
    echo  "${DIR_NAME}/stx-iso-utils-centos.sh does not exist" >&2
    exit 1
else
    source "${DIR_NAME}"/stx-iso-utils-centos.sh
fi

# Required variables
declare INPUT_ISO=
declare OUTPUT_ISO=
declare -a IMAGES
declare KS_SETUP=
declare KS_ADDON=
declare UPDATE_TIMEOUT="no"
declare -i FOREVER_GRUB_TIMEOUT=-1
declare -i DEFAULT_GRUB_TIMEOUT=30
declare -i DEFAULT_TIMEOUT=$(( DEFAULT_GRUB_TIMEOUT*10 ))
declare -i TIMEOUT=${DEFAULT_TIMEOUT}
declare -i GRUB_TIMEOUT=${DEFAULT_GRUB_TIMEOUT}
declare -a PARAMS
declare -a PATCHES
declare -a KICKSTART_PATCHES
declare DEFAULT_LABEL=
declare DEFAULT_SYSLINUX_ENTRY=1
declare DEFAULT_GRUB_ENTRY="graphical"
declare FORCE_INSTALL=
declare PLATFORM_ROOT="opt/platform-backup"
declare MD5_FILE="container-image.tar.gz.md5"
declare VOLUME_LABEL="oe_prestaged_iso_boot"
declare PRESTAGED_KICKSTART="prestaged_installer_ks.cfg"
declare MENU_NAME="Prestaged Local Installer"

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

declare -i rc
OPTS=$(getopt -o "${SHORTOPTS}" --long "${LONGOPTS}" --name "$0" -- "$@")
if [ $? -ne 0 ]; then
    usage
    log_fatal "Options to $0 not properly parsed"
fi

eval set -- "${OPTS}"

if [ $# = 1 ]; then
    usage
    log_fatal "No arguments were provided"
fi

while :; do
    case $1 in
        -h | --help)
            usage
            exit 0
            ;;
        -i | --input)
            INPUT_ISO=$2
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
            # shellcheck disable=2206
            PARAMS+=(${2//,/ })
            shift 2
            ;;
        -P | --patch)
            # shellcheck disable=2206
            PATCHES+=(${2//,/ })
            shift 2
            ;;
        -K | --kickstart-patch)
            # shellcheck disable=2206
            KICKSTART_PATCHES+=(${2//,/ })
            shift 2
            ;;
        -I | --images)
            # shellcheck disable=2206
            IMAGES+=(${2//,/ })
            shift 2
            ;;
        -d | --default-boot)
            DEFAULT_LABEL=${2}
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
            declare -i timeout_arg=${2}
            if [ "${timeout_arg}" -gt 0 ]; then
                TIMEOUT=$(( timeout_arg * 10 ))
                GRUB_TIMEOUT=${timeout_arg}
            elif [ ${timeout_arg} -eq 0 ]; then
                TIMEOUT=0
                GRUB_TIMEOUT=0.001
            elif [ ${timeout_arg} -lt 0 ]; then
                TIMEOUT=0
                GRUB_TIMEOUT=${FOREVER_GRUB_TIMEOUT}
            fi
            UPDATE_TIMEOUT="yes"
            shift 2
            ;;
        -f | --force-install)
            FORCE_INSTALL=true
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            usage
            log_fatal "Unexpected argument: $*"
            ;;
    esac
done


###############################################################################
# Generate prestage iso.
#
###############################################################################

log_info "Checking system requirements"
check_requirements

## Check for mandatory parameters
check_required_param "--input" "${INPUT_ISO}"
check_required_param "--output" "${OUTPUT_ISO}"

# shellcheck disable=2068
check_files_exist ${INPUT_ISO} ${IMAGES[@]} ${PATCHES[@]} ${KICKSTART_PATCHES[@]} ${KS_SETUP} ${KS_ADDON}
# shellcheck disable=2068
check_files_size  ${INPUT_ISO} ${IMAGES[@]} ${PATCHES[@]} ${KICKSTART_PATCHES[@]} ${KS_SETUP} ${KS_ADDON}

if [ -e "${OUTPUT_ISO}" ]; then
    log_fatal "${OUTPUT_ISO} exists. Delete before you execute this script."
fi

## Catch Control-C and handle.
trap cleanup EXIT

# Create a temporary build directory.
BUILDDIR=$(mktemp -d -p "${PWD}" updateiso_build_XXXXXX)
if [ -z "${BUILDDIR}" ] || [ ! -d "${BUILDDIR}" ]; then
    log_fatal "Failed to create builddir. Aborting..."
fi
log_info "Using BUILDDIR=${BUILDDIR}"
mount_iso "${INPUT_ISO}"

#
# prestaging kickstart
#

# Verify prestaging kickstart is present, and where.
# KICKSTART_PATCHES take precedence over a platform PATCHES, which in
# turn take precedence over any content from the ISO.
PRESTAGED_KICKSTART_PATCH=
PRESTAGED_KICKSTART_PATH=

# Scan KICKSTART_PATCHES last to first.
for patch in $(printf '%s\n' "${KICKSTART_PATCHES[@]}" | tac); do
    if PRESTAGED_KICKSTART_PATH="$(find_in_patch "${patch}" "${PRESTAGED_KICKSTART}")" ; then
        PRESTAGED_KICKSTART_PATCH="${patch}"
        break
    fi
done

# Scan PATCHES last to first. Prefer the most recent patch.
# Assumes patches will be listed in order 0001, 0002, .... when given as args.
if [ -z "${PRESTAGED_KICKSTART_PATCH}" ]; then
    for patch in $(printf '%s\n' "${PATCHES[@]}" | tac); do
        if PRESTAGED_KICKSTART_PATH="$(find_in_patch "${patch}" "${PRESTAGED_KICKSTART}")" ; then
            PRESTAGED_KICKSTART_PATCH="${patch}"
            break
        fi
    done
fi

if [ -z "${PRESTAGED_KICKSTART_PATCH}" ]; then
    if PRESTAGED_KICKSTART_PATH="$(find_in_mounted_iso "${PRESTAGED_KICKSTART}")" ; then
        log_info "Using ${PRESTAGED_KICKSTART} from original ISO"
    else
        log_fatal "Failed to find required file '${PRESTAGED_KICKSTART}' in the supplied iso and patches."
    fi
fi

#
# Determine release version from ISO
#
if [ ! -f "${MNTDIR}"/upgrades/version ]; then
    log_error "Version info not found on ${INPUT_ISO}"
    exit 1
fi

ISO_VERSION=$(source "${MNTDIR}/upgrades/version" && echo "${VERSION}")
if [ -z "${ISO_VERSION}" ]; then
    log_error "Failed to determine version of installation ISO"
    exit 1
fi

# Copy the contents of the input iso to the build directory.

log_info "Copying input ISO"
rsync -av "${MNTDIR}/" "${BUILDDIR}/"
rc=$?
if [ "${rc}" -ne 0 ]; then
    unmount_iso
    log_fatal "Unable to rsync content from the ISO: Error rc=${rc}"
fi

# Copy kickstart if it is anywhere outside of the mounted ISO (otherwise it will already have been copied by the above)
if [ -n "${PRESTAGED_KICKSTART_PATCH}" ]; then
    log_info "Prestaging kickstart from ${PRESTAGED_KICKSTART_PATCH}"
    copy_patch_file_to_iso "${PRESTAGED_KICKSTART_PATCH}" "${PRESTAGED_KICKSTART_PATH%%:*}" "${PRESTAGED_KICKSTART_PATH##*:}" "/" "y"
fi

unmount_iso

#
# Setup syslinux and grub cfg files
#
generate_boot_cfg "${BUILDDIR}"

#
# Set/update boot parameters
#
log_info "Updating boot parameters"
if [ ${#PARAMS[@]} -gt 0 ]; then
    for p in "${PARAMS[@]}"; do
        param=${p%%=*} # Strip from the first '=' on
        value=${p#*=}  # Strip to the first '='
        update_parameter "${BUILDDIR}" "${param}" "${value}"
    done
fi

if [ -n "${DEFAULT_LABEL}" ]; then
    set_default_label "${BUILDDIR}"
fi

if [ "${UPDATE_TIMEOUT}" = "yes" ]; then
    set_timeout "${BUILDDIR}"
fi

if [ -n "${KS_SETUP}" ]; then
    \rm -f "${BUILDDIR}"/ks-setup.cfg
    \cp "${KS_SETUP}" "${BUILDDIR}"/ks-setup.cfg
    if [ $? -ne 0 ]; then
        log_error "Error: Failed to copy ${KS_SETUP}"
        exit 1
    fi
fi

if [ -n "${KS_ADDON}" ]; then
    \rm -f "${BUILDDIR}"/ks-addon.cfg
    \cp "${KS_ADDON}" "${BUILDDIR}"/ks-addon.cfg
    if [ $? -ne 0 ]; then
        log_error "Error: Failed to copy ${KS_ADDON}"
        exit 1
    fi
fi

unmount_efiboot_img


#
# Copy ISO, patches, and docker image bundles to /opt on the iso.
# These will be processed by the prestaged installer kickstart.
# RPM has no role in the installation of these files.
#
PLATFORM_PATH="${PLATFORM_ROOT}/${ISO_VERSION}"
mkdir_on_iso "${PLATFORM_PATH}"

INPUT_ISO_NAME="$(basename "${INPUT_ISO}")"
copy_to_iso "${INPUT_ISO}" "${PLATFORM_PATH}/${INPUT_ISO_NAME}"  "${PLATFORM_PATH}/${INPUT_ISO_NAME/%.iso/.md5}"

if [ -n "${PATCHES[*]}" ]; then
    log_info "Including patches: ${PATCHES[*]}"
    for patch in "${PATCHES[@]}"; do
        copy_to_iso "${patch}" "${PLATFORM_PATH}/"
    done
fi

if [ -n "${IMAGES[*]}" ]; then
    log_info "Including images: ${IMAGES[*]}"
    for IMAGE in "${IMAGES[@]}"; do
        copy_to_iso "${IMAGE}" "${PLATFORM_PATH}/" "${PLATFORM_PATH}/${MD5_FILE}"
    done
fi

#  we are ready to create the prestage iso.
log_info "Creating ${OUTPUT_ISO}"
mkisofs -o "${OUTPUT_ISO}" \
        -R -D -A "${VOLUME_LABEL}" -V "${VOLUME_LABEL}" \
        -quiet \
        -b isolinux.bin -c boot.cat -no-emul-boot \
        -boot-load-size 4 -boot-info-table \
        -eltorito-alt-boot \
        -e images/efiboot.img \
        -no-emul-boot \
        "${BUILDDIR}"

isohybrid --uefi "${OUTPUT_ISO}"
implantisomd5 "${OUTPUT_ISO}"

log_info "Prestage ISO created successfully: ${OUTPUT_ISO}"
