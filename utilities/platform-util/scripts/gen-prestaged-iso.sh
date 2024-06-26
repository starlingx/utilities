#!/bin/bash
#
# Copyright (c) 2022-2024 Wind River Systems, Inc.
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
    # red
    echo "$(tput setaf 1)$(date "+%F %H:%M:%S") FATAL: ${*}$(tput sgr0)" >&2
    exit 1
}

function log_error {
    # red
    echo "$(tput setaf 1)$(date "+%F %H:%M:%S"): ERROR: ${*}$(tput sgr0)" >&2
}

function log_warn {
    # orange
    echo "$(tput setaf 3)$(date "+%F %H:%M:%S"): WARN: ${*}$(tput sgr0)" >&2
}

function log_info {
    echo "$(date "+%F %H:%M:%S"): INFO: $*" >&2
}

# Usage manual.
function usage {
    cat <<ENDUSAGE
Utility to convert a StarlingX installation iso into a Debian prestaged subcloud installation iso.

Usage:
   $(basename "$0") --input <input bootimage.iso>
                  --output <output bootimage.iso>
                  [ --images <images.tar.gz> ]
                  [ --patch <patch-name.patch> ]
                  [ --kickstart-patch <kickstart.cfg> ]
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
        --kickstart-patch <kickstart.cfg>:
                         A cfg to replace the prestaged installer kickstart.

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
                         0 - Prestage Serial Console
                         1 - Prestage Graphical Console (default)
                         2 - Prestage cloud-init All-in-one Serial Console
                         3 - Prestage cloud-init All-in-one Graphical Console
                         4 - Prestage cloud-init All-in-one (lowlatency) Serial Console
                         5 - Prestage cloud-init All-in-one (lowlatency) Graphical Console
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
    if [ "${path: -1:1}" == "/" ]; then   # Note: space is required after : to distinguish from ${path:-...}
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

function generate_boot_cfg {
    log_info "Generating boot config"
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img "${isodir}"
    fi

    local PARAM_LIST=
    # Set/update boot parameters
    if [ ${#PARAMS[@]} -gt 0 ]; then
        log_info "Pre-parsing params: ${PARAMS[*]}"
        for p in "${PARAMS[@]}"; do
            param=${p%%=*}
            value=${p#*=}
            # Pull the boot device out of PARAMS and convert to instdev
            if [ "${param}" = "boot_device" ]; then
                log_info "Setting instdev=${value} from boot_device param"
                instdev=${value}
            elif [ "${param}" = "rootfs_device" ]; then
                log_info "Setting instdev=${value} from boot_device param"
                instdev=${value}
            fi

            PARAM_LIST="${PARAM_LIST} ${param}=${value}"
        done
        log_info "Using parameters: ${PARAM_LIST}"
    fi

    if [[ "${KS_PATCH}" == "true" ]]; then
        log_info "Setting Kickstart patch from the kickstart_patches directory"
        ks="${KICKSTART_PATCH_DIR}"/kickstart.cfg
    else
        log_info "Setting Kickstart patch from the kickstart directory"
        ks=kickstart/kickstart.cfg
    fi

    COMMON_ARGS="initrd=/initrd instdate=@$(date +%s) instw=60 instiso=instboot"
    COMMON_ARGS="${COMMON_ARGS} biosplusefi=1 instnet=0"
    COMMON_ARGS="${COMMON_ARGS} ks=file:///${ks}"
    COMMON_ARGS="${COMMON_ARGS} rdinit=/install instname=debian instbr=starlingx instab=0"
    COMMON_ARGS="${COMMON_ARGS} insturl=file://NOT_SET prestage ip=${BOOT_IP_ARG}"
    COMMON_ARGS="${COMMON_ARGS} BLM=2506 FSZ=32 BSZ=512 RSZ=20480 VSZ=20480 instl=/ostree_repo instdev=${instdev}"
    COMMON_ARGS="${COMMON_ARGS} inst_ostree_root=/dev/mapper/cgts--vg-root--lv"
    COMMON_ARGS="${COMMON_ARGS} inst_ostree_var=/dev/mapper/cgts--vg-var--lv"

    if [ -n "${FORCE_INSTALL}" ]; then
        COMMON_ARGS="${COMMON_ARGS} force_install"
    fi

    # Uncomment for LAT debugging:
    #COMMON_ARGS="${COMMON_ARGS} instsh=2"
    COMMON_ARGS="${COMMON_ARGS} ${PARAM_LIST}"
    log_info "COMMON_ARGS: ${COMMON_ARGS}"

    COMMON_ARGS_LOW_LATENCY="${COMMON_ARGS} defaultkernel=vmlinuz-*-rt-amd64"
    COMMON_ARGS_DEFAULT="${COMMON_ARGS} defaultkernel=vmlinuz*[!t]-amd64"

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
menu begin
  menu title Prestage Install
  label 0
    menu label Serial Console
    kernel /bzImage-std
    ipappend 2
    append ${COMMON_ARGS_DEFAULT} traits=controller console=ttyS0,115200 console=tty0
  label 1
    menu label Graphical Console
    kernel /bzImage-std
    ipappend 2
    append ${COMMON_ARGS_DEFAULT} traits=controller console=tty0
menu end

menu begin
  menu title Prestage cloud-init All-in-one Install
  label 2
    menu label Serial Console
    kernel /bzImage-std
    ipappend 2
    append ${COMMON_ARGS_DEFAULT} traits=controller,worker ${CLOUDINIT_BOOT_ARG} console=ttyS0,115200 console=tty0
  label 3
    menu label Graphical Console
    kernel /bzImage-std
    ipappend 2
    append ${COMMON_ARGS_DEFAULT} traits=controller,worker ${CLOUDINIT_BOOT_ARG} console=tty0
menu end

menu begin
  menu title Prestage cloud-init All-in-one (lowlatency) Install
  label 4
    menu label Serial Console
    kernel /bzImage-rt
    ipappend 2
    append ${COMMON_ARGS_LOW_LATENCY} traits=controller,worker,lowlatency ${CLOUDINIT_BOOT_ARG} console=ttyS0,115200 console=tty0
  label 5
    menu label Graphical Console
    kernel /bzImage-rt
    ipappend 2
    append ${COMMON_ARGS_LOW_LATENCY} traits=controller,worker,lowlatency ${CLOUDINIT_BOOT_ARG} console=tty0
menu end

EOF
    done
    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        cat <<EOF > "${f}"
default="${DEFAULT_GRUB_ENTRY}"
timeout=${GRUB_TIMEOUT}
search --no-floppy --set=root -l 'instboot'
set color_normal='light-gray/black'
set color_highlight='light-green/blue'

menuentry 'Debian Local Install : Select kernel options and boot kernel' --id=title {
    set fallback=1
}

submenu 'Prestage Install' --id=prestage-install {
 menuentry 'Serial Console' --id=serial {
    linux /bzImage-std ${COMMON_ARGS_DEFAULT} traits=controller console=ttyS0,115200 serial
    initrd /initrd
  }
  menuentry 'Graphical Console' --id=graphical {
    linux /bzImage-std ${COMMON_ARGS_DEFAULT} traits=controller console=tty0
    initrd /initrd
  }
}

submenu 'Prestage cloud-init All-in-one Install' --id=cloud-init-aio {
  menuentry 'Serial Console' --id=serial {
    linux /bzImage-std ${COMMON_ARGS_DEFAULT} traits=controller,worker ${CLOUDINIT_BOOT_ARG} console=ttyS0,115200 serial
    initrd /initrd
  }
  menuentry 'Graphical Console' --id=graphical {
    linux /bzImage-std ${COMMON_ARGS_DEFAULT} traits=controller,worker ${CLOUDINIT_BOOT_ARG} console=tty0
    initrd /initrd
  }
}

submenu 'Prestage cloud-init (lowlatency) All-in-one Install' --id=cloud-init-aio-lowlat {
  menuentry 'Serial Console' --id=serial {
    linux /bzImage-rt ${COMMON_ARGS_LOW_LATENCY} traits=controller,worker,lowlatency ${CLOUDINIT_BOOT_ARG} console=ttyS0,115200 serial
    initrd /initrd
  }
  menuentry 'Graphical Console' --id=graphical {
    linux /bzImage-rt ${COMMON_ARGS_LOW_LATENCY} traits=controller,worker,lowlatency ${CLOUDINIT_BOOT_ARG} console=tty0
    initrd /initrd
  }
}

EOF
    done

    unmount_efiboot_img
}

function generate_ostree_checkum {
    # Generate a directory-based md5 checksum across the ostree repo.
    # This checksum is used to validate the ostree_repo before installation.
    # We use a checksum instead of ostree fsck due to the length of time
    # required for the fsck to complete.
    local dest_dir=${1}
    if [ ! -d "${dest_dir}" ]; then
        log_fatal "generate_ostree_checkum: ${dest_dir} does not exist"
    fi
    (
        # subshell:
        log_info "Calculating new checksum for ostree_repo at ${dest_dir}"
        cd "${dest_dir}" || log_fatal "generate_ostree_checkum: cd ${dest_dir} failed"
        find ostree_repo -type f -exec md5sum {} + | LC_ALL=C sort | md5sum | awk '{ print $1; }' \
            > .ostree_repo_checksum
        log_info "ostree_repo checksum: $(cat .ostree_repo_checksum)"
    )
}

# Constants
DIR_NAME=$(dirname "$0")
if [ ! -e "${DIR_NAME}"/stx-iso-utils.sh ]; then
    echo "${DIR_NAME}/stx-iso-utils.sh does not exist" >&2
    exit 1
else
    source "${DIR_NAME}"/stx-iso-utils.sh
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
declare DEFAULT_LABEL=0
declare DEFAULT_SYSLINUX_ENTRY=1
declare DEFAULT_GRUB_ENTRY="prestage-install>graphical"
declare FORCE_INSTALL=
declare PLATFORM_ROOT="opt/platform-backup"
declare MD5_FILE="container-image.tar.gz.md5"
declare KS_PATCH=false
declare CLOUDINIT_BOOT_ARG=cloud-init=enabled

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
            # warn about renaming to ks-addon.cfg:
            if [ "$(basename "${KS_ADDON}")" != "ks-addon.cfg" ]; then
                log_warn "--addon ${KS_ADDON}: will be renamed to ks-addon.cfg inside ISO"
            fi
            shift 2
            ;;
        -p | --param)
            # shellcheck disable=2206
            PARAMS+=(${2//,/ })
            shift 2
            ;;
        # TODO(kmacleod) Does providing patches make sense?
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
                    DEFAULT_GRUB_ENTRY="prestage-install>serial"
                    ;;
                1)
                    DEFAULT_SYSLINUX_ENTRY=1
                    DEFAULT_GRUB_ENTRY="prestage-install>graphical"
                    ;;
                2)
                    DEFAULT_SYSLINUX_ENTRY=2
                    DEFAULT_GRUB_ENTRY="cloud-init-aio>serial"
                    ;;
                3)
                    DEFAULT_SYSLINUX_ENTRY=3
                    DEFAULT_GRUB_ENTRY="cloud-init-aio>graphical"
                    ;;
                4)
                    DEFAULT_SYSLINUX_ENTRY=4
                    DEFAULT_GRUB_ENTRY="cloud-init-aio-lowlat>serial"
                    ;;
                5)
                    DEFAULT_SYSLINUX_ENTRY=5
                    DEFAULT_GRUB_ENTRY="cloud-init-aio-lowlat>graphical"
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
            # TODO(kmacleod): UPDATE_TIMEOUT is not used, why is that?
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
check_files_exist ${INPUT_ISO} ${PATCHES[@]} ${IMAGES[@]} ${KS_SETUP} ${KS_ADDON} ${KICKSTART_PATCHES[@]}
# shellcheck disable=2068
check_files_size               ${PATCHES[@]} ${IMAGES[@]} ${KS_SETUP} ${KS_ADDON} ${KICKSTART_PATCHES[@]}

if [ -e "${OUTPUT_ISO}" ]; then
    log_fatal "${OUTPUT_ISO} exists. Delete before you execute this script."
fi
# Check for rootfs_device/boot_device and warn if not present
found_rootfs_device=
found_boot_device=
if [ ${#PARAMS[@]} -gt 0 ]; then
    for p in "${PARAMS[@]}"; do
        param=${p%%=*}
        case "${param}" in
            rootfs_device)
                found_rootfs_device=1
                ;;
            boot_device)
                found_boot_device=1
                ;;
        esac
    done
fi
if [ -z "${found_rootfs_device}" ]; then
    log_warn "Missing '--param rootfs_device=...'. A default device will be selected during install, which may not be desired"
fi
if [ -z "${found_boot_device}" ]; then
    log_warn  "Missing '--param boot_device=...'. A default device will be selected during install, which may not be desired"
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
# This ensures that the ostree_repo, kernel and the initramfs are all copied over
# to the prestage iso.

log_info "Copying input ISO"
rsync -a --exclude "pxeboot" "${MNTDIR}/" "${BUILDDIR}/"
rc=$?
if [ "${rc}" -ne 0 ]; then
    unmount_iso
    log_fatal "Unable to rsync content from the ISO: Error rc=${rc}"
fi

generate_ostree_checkum "${BUILDDIR}"

unmount_iso

#
# Copy ISO, patches, and docker image bundles to /opt on the iso.
# These will be processed by the prestaged installer kickstart.
# RPM has no role in the installation of these files.
#
PLATFORM_PATH="${PLATFORM_ROOT}/${ISO_VERSION}"
mkdir_on_iso "${PLATFORM_PATH}"

if [ -n "${PATCHES[*]}" ]; then
    log_info "Including patches: ${PATCHES[*]}"
    for PATCH in "${PATCHES[@]}"; do
        copy_to_iso "${PATCH}" "${PLATFORM_PATH}/"
    done
fi

if [ -n "${IMAGES[*]}" ]; then
    log_info "Including images: ${IMAGES[*]}"
    for IMAGE in "${IMAGES[@]}"; do
        copy_to_iso "${IMAGE}" "${PLATFORM_PATH}/" "${PLATFORM_PATH}/${MD5_FILE}"
    done
fi

KICKSTART_PATCH_DIR="kickstart_patch"
mkdir_on_iso "${KICKSTART_PATCH_DIR}"
for PATCH in "${KICKSTART_PATCHES[@]}"; do
    log_info "Including kickstart patch: ${PATCH}"
    copy_to_iso "${PATCH}" "${KICKSTART_PATCH_DIR}"
    KS_PATCH="true"
done

# generate the grub and isolinux cmd line parameters
generate_boot_cfg "${BUILDDIR}"

# copy the addon and setup files to the BUILDDIR
if [[ -e "${KS_SETUP}" ]]; then
    cp "${KS_SETUP}" "${BUILDDIR}"
fi

if [[ -e "${KS_ADDON}" ]]; then
    # always name the addon "ks-addon.cfg" since that is what kickstart.cfg looks for in the root directory
    cp "${KS_ADDON}" "${BUILDDIR}/ks-addon.cfg"
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

log_info "Prestage ISO created successfully: ${OUTPUT_ISO}"
