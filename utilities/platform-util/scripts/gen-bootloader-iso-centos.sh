#!/bin/bash
# vim: filetype=sh shiftwidth=4 expandtab
#
# Copyright (c) 2020-2023 Wind River Systems, Inc.
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
readonly SCRIPTDIR=$(readlink -m "$(dirname "$0")")
readonly SCRIPTNAME=$(basename "$0")

# Source shared utility functions
# shellcheck disable=SC1090 # ignore source warning
source "$SCRIPTDIR"/stx-iso-utils-centos.sh

ADDON=
BASE_URL=
BOOT_ARGS_COMMON=
BOOT_GATEWAY=
BOOT_HOSTNAME=
BOOT_INTERFACE=
BOOT_IP=
BOOT_NETMASK=
CLEAN_NODE_DIR="no"
CLEAN_SHARED_DIR="no"
DEFAULT_GRUB_ENTRY=
DEFAULT_SYSLINUX_ENTRY=
DELETE="no"
GRUB_TIMEOUT=-1
INPUT_ISO=
INSTALL_TYPE=
ISO_VERSION=
KS_NODETYPE=
LOCK_FILE=/var/run/.gen-bootloader-iso.lock
LOCK_TMOUT=600  # Wait up to 10 minutes, by default
LOG_TAG=$SCRIPTNAME
NODE_ID=
NODE_URL=
OUTPUT_ISO=
PATCHES_FROM_HOST="yes"
SCRATCH_DIR=${SCRATCH_DIR:-/scratch}
TIMEOUT=0
UPDATE_TIMEOUT="no"
VERBOSE=${VERBOSE:-}
VERBOSE_LOG_DIR=/var/log/dcmanager/miniboot
VERBOSE_OVERRIDE_FILE=/tmp/gen-bootloader-verbose  # turn on verbose if this file is present
WWW_ROOT_DIR=

declare -a PARAMS

# Initialized via initialize_and_lock:
BUILDDIR=
NODE_DIR=
NODE_DIR_BASE=
VERBOSE_RSYNC=
WORKDIR=

# Initialized by stx-iso-utils-centos.sh:mount_efiboot_img
EFI_MOUNT=

# Set this to a directory path containing kickstart *.cfg script(s) for testing:
KICKSTART_OVERRIDE_DIR=${KICKSTART_OVERRIDE_DIR:-/var/miniboot/kickstart-override-centos}

function log_verbose {
    if [ -n "$VERBOSE" ]; then
        echo "$@"
    fi
}

function log_info {
    echo "$@"
}

function log_error {
    logger -i -s -t "${LOG_TAG}" -- "ERROR: $*"
}

function log_warn {
    logger -i -s -t "${LOG_TAG}" -- "WARN: $*"
}

function fatal_error {
    logger -i -s -t "${LOG_TAG}" -- "FATAL: $*"
    exit 1
}

function check_rc_exit {
    local rc=$1
    shift
    if [ "$rc" -ne 0 ]; then
        logger -i -s -t "${LOG_TAG}" -- "FATAL: $* [exit: $rc]"
        exit "$rc"
    fi
}

function get_os {
    local os
    os=$(awk -F '=' '/^ID=/ { print $2; }' /etc/os-release)
    case "$os" in
        *debian*)
            echo debian
            ;;
        *centos*)
            echo centos
            ;;
        *)
            echo "$os"
            ;;
    esac
}

function get_path_size {
    local path=$1
    du -hs "$path" | awk '{print $1}'
}

function log_path_size {
    local path=$1
    local msg=$2
    log_info "$msg: $(get_path_size "$path")"
}

function usage {
    cat <<ENDUSAGE
Description: Sets up a mini bootimage.iso that includes the minimum required to
retrieve the rootfs and software packages needed for installation via http or
https, generated for a specific node.

Mandatory parameters for setup:
    --input <file>:          Specify input ISO file
    --www-root <dir>:        Specify www-serviced directory (for target mini bootimage.iso)
    --base-url <url>:        Specify URL for www-root dir
    --id <node id>:          Specify ID for target node (typically subcloud name)
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
    --lock-timeout <secs>:   Specify time to wait for mutex lock before aborting
    --patches-from-iso:      Use patches from the ISO, if any, rather than host
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
# Functions
#

function parse_arguments {
    # Parse cmdline arguments
    local longopts opts
    longopts="input:,addon:,param:,default-boot:,timeout:,lock-timeout:,patches-from-iso"
    longopts="${longopts},base-url:,www-root:,id:,delete"
    longopts="${longopts},boot-gateway:,boot-hostname:,boot-interface:,boot-ip:,boot-netmask:"
    longopts="${longopts},verbose,help"

    opts=$(getopt -o h --long "${longopts}" --name "$0" -- "$@")
    # shellcheck disable=SC2181 # prefer to check exit code:
    if [ $? -ne 0 ]; then
        usage
        exit 1
    fi

    eval set -- "${opts}"

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
                INSTALL_TYPE=$2
                shift 2
                case ${INSTALL_TYPE} in
                    0)
                        DEFAULT_SYSLINUX_ENTRY=0
                        DEFAULT_GRUB_ENTRY=serial
                        KS_NODETYPE='controller'
                        ;;
                    1)
                        DEFAULT_SYSLINUX_ENTRY=1
                        DEFAULT_GRUB_ENTRY=graphical
                        KS_NODETYPE='controller'
                        ;;
                    2)
                        DEFAULT_SYSLINUX_ENTRY=0
                        DEFAULT_GRUB_ENTRY=serial
                        KS_NODETYPE='smallsystem'
                        ;;
                    3)
                        DEFAULT_SYSLINUX_ENTRY=1
                        DEFAULT_GRUB_ENTRY=graphical
                        KS_NODETYPE='smallsystem'
                        ;;
                    4)
                        DEFAULT_SYSLINUX_ENTRY=0
                        DEFAULT_GRUB_ENTRY=serial
                        KS_NODETYPE='smallsystem_lowlatency'
                        ;;
                    5)
                        DEFAULT_SYSLINUX_ENTRY=1
                        DEFAULT_GRUB_ENTRY=graphical
                        KS_NODETYPE='smallsystem_lowlatency'
                        ;;
                    *)
                        log_error "Invalid default boot menu option: ${INSTALL_TYPE}"
                        usage
                        exit 1
                        ;;
                esac
                ;;
            --timeout)
                local -i timeout_arg=$2
                shift 2
                if [ ${timeout_arg} -gt 0 ]; then
                    TIMEOUT=$(( timeout_arg * 10 ))
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
            --lock-timeout)
                local -i LOCK_TMOUT=$2
                shift 2
                if [ "${LOCK_TMOUT}" -le 0 ]; then
                    echo "Lock timeout must be greater than 0" >&2
                    exit 1
                fi
                ;;
            --delete)
                DELETE="yes"
                shift
                ;;
            --patches-from-iso)
                PATCHES_FROM_HOST="no"
                shift
                ;;
            --verbose)
                VERBOSE=1
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
}

function get_lock {
    # Grab the lock, to protect against simultaneous execution
    # Open $LOCK_FILE for reading, with assigned file handle 200
    exec 200>${LOCK_FILE}
    flock -w "${LOCK_TMOUT}" 200
    check_rc_exit $? "Failed waiting for lock: ${LOCK_FILE}"
}

function initialize_and_lock {
    check_requirements

    # Check mandatory parameters
    check_required_param "--id" "${NODE_ID}"
    check_required_param "--www-root" "${WWW_ROOT_DIR}"
    [ -d "${WWW_ROOT_DIR}" ] || fatal_error "Root directory ${WWW_ROOT_DIR} does not exist"

    [ -f "${VERBOSE_OVERRIDE_FILE}" ] && VERBOSE=1
    if [ -n "${VERBOSE}" ]; then
        VERBOSE_RSYNC="--verbose"

        # log all output to file
        if [ ! -d "$(dirname "${VERBOSE_LOG_DIR}")" ]; then
            # For testing: the base directory does not exist - use /tmp instead
            VERBOSE_LOG_DIR=/tmp/miniboot
        fi
        [ -d "${VERBOSE_LOG_DIR}" ] || mkdir -p "${VERBOSE_LOG_DIR}"
        local logfile="${VERBOSE_LOG_DIR}/gen-bootloader-iso-centos-${NODE_ID}.log"
        [ -f "${logfile}" ] && rm -f "${logfile}"
        touch "${logfile}"
        echo "Verbose: logging output to ${logfile}"
        echo "$(date) Starting $0"
        printenv >> "${logfile}"
        exec > >(tee --append "${logfile}") 2>&1
    fi

    # Initialize dynamic variables
    NODE_DIR_BASE="${WWW_ROOT_DIR}/nodes"
    NODE_DIR="${NODE_DIR_BASE}/${NODE_ID}"
    SHARED_DIR="${WWW_ROOT_DIR}/shared"

    if [ ! -d "$SCRATCH_DIR" ]; then
        log_warn "SCRATCH_DIR does not exist, using /tmp"
        SCRATCH_DIR=/tmp
    fi

    get_lock

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

    NODE_URL="${BASE_URL%\/}/nodes/${NODE_ID}"

    if [ ! -f "${INPUT_ISO}" ]; then
        fatal_error "Input file does not exist: ${INPUT_ISO}"
    fi
    if [ -d "${NODE_DIR}" ]; then
        fatal_error "Output dir already exists: ${NODE_DIR}"
    fi

    # Run cleanup on any exit
    trap cleanup_on_exit EXIT

    BUILDDIR=$(mktemp -d -p "${SCRATCH_DIR}" gen_bootloader_build_XXXXXX)
    if [ -z "${BUILDDIR}" ] || [ ! -d "${BUILDDIR}" ]; then
        fatal_error "Failed to create builddir: ${BUILDDIR}"
    fi

    WORKDIR=$(mktemp -d -p "${SCRATCH_DIR}" gen_bootloader_workdir_XXXXXX)
    if [ -z "${WORKDIR}" ] || [ ! -d "${WORKDIR}" ]; then
        fatal_error "Failed to create WORKDIR directory: $WORKDIR"
    fi
}

function generate_boot_cfg {
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img ${isodir}
    fi

    local KS_URL="${NODE_URL}/miniboot_${KS_NODETYPE}.cfg"
    local BOOT_IP_ARG="${BOOT_IP}::${BOOT_GATEWAY}:${BOOT_NETMASK}:${BOOT_HOSTNAME}:${BOOT_INTERFACE}:none"

    BOOT_ARGS_COMMON="inst.text inst.gpt boot_device=sda rootfs_device=sda"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} biosdevname=0 usbcore.autosuspend=-1"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} security_profile=standard user_namespace.enable=1"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} inst.repo=${NODE_URL} inst.stage2=${NODE_URL} inst.ks=${KS_URL}"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} ip=${BOOT_IP_ARG}"

    log_info "Using boot parameters: ${BOOT_ARGS_COMMON}"
    log_verbose "Generating isolinux.cfg/syslinux.cfg, default: $DEFAULT_SYSLINUX_ENTRY, timeout: $TIMEOUT"
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
    menu title ${NODE_ID}

    # Serial Console submenu
    label 0
        menu label Serial Console
        kernel vmlinuz
        initrd initrd.img
        append rootwait ${BOOT_ARGS_COMMON} console=ttyS0,115200 serial

    # Graphical Console submenu
    label 1
        menu label Graphical Console
        kernel vmlinuz
        initrd initrd.img
        append rootwait ${BOOT_ARGS_COMMON} console=tty0
menu end

EOF
    done

    log_verbose "Generating grub.cfg, install_type: ${INSTALL_TYPE}, default: ${DEFAULT_GRUB_ENTRY}, timeout: ${GRUB_TIMEOUT}"
    for f in "${isodir}/EFI/BOOT/grub.cfg" "${EFI_MOUNT}/EFI/BOOT/grub.cfg"; do
        cat <<EOF > "${f}"
default=${DEFAULT_GRUB_ENTRY}
timeout=${GRUB_TIMEOUT}
search --no-floppy --set=root -l 'oe_iso_boot'

menuentry "CentOS Miniboot Install ${NODE_ID}" {
    echo " "
}

menuentry 'Serial Console' --id=serial {
    linuxefi /vmlinuz ${BOOT_ARGS_COMMON} console=ttyS0,115200 serial
    initrdefi /initrd.img
}

menuentry 'Graphical Console' --id=graphical {
    linuxefi /vmlinuz ${BOOT_ARGS_COMMON} console=tty0
    initrdefi /initrd.img
}
EOF
    done
}

function cleanup_on_exit {
    # This is invoked from the trap handler.
    # The last exit code is used to determine if we are exiting
    # in failed state (non-zero exit), in which case we do the
    # full cleanup. Disable the warning here since we are
    # invoked as a trap handler
    # shellcheck disable=SC2181 # Check exit code directly...
    if [ $? -ne 0 ]; then
        log_info "Cleanup on failure"
        handle_delete
    fi
    common_cleanup
}

function check_requirements {
    common_check_requirements
}

function handle_delete {
    # Remove node-specific files
    if [ -d "${NODE_DIR}" ]; then
        rm -rf "${NODE_DIR}"
    fi

    # If there are no more nodes, cleanup everything else
    # shellcheck disable=SC2012
    if [ "$(ls -A "${NODE_DIR_BASE}" 2>/dev/null | wc -l)" = 0 ]; then
        if [ -d "${NODE_DIR_BASE}" ]; then
            rmdir "${NODE_DIR_BASE}"
        fi

        if [ -d "${SHARED_DIR}" ]; then
            rm -rf "${SHARED_DIR}"
        fi
    fi

    # TODO(kmacleod): do we need this?
    # Mark the DNF cache expired
    dnf clean expire-cache
}

function get_patches_from_host {
    local host_patch_repo=/var/www/pages/updates/rel-${ISO_VERSION}

    if [ ! -d "${host_patch_repo}" ]; then
        log_error "Patch repo not found: ${host_patch_repo}"
        # Don't fail, as there could be scenarios where there's nothing on
        # the host related to the release on the ISO
        return
    fi

    mkdir -p "${SHARED_DIR}/patches"
    check_rc_exit $? "Failed to create directory: ${SHARED_DIR}/patches"

    rsync -a "${host_patch_repo}/repodata" "${SHARED_DIR}/patches/"
    check_rc_exit $? "Failed to copy ${host_patch_repo}/repodata"

    if [ -d "${host_patch_repo}/Packages" ]; then
        rsync -a "${host_patch_repo}/Packages" "${SHARED_DIR}/patches/"
        check_rc_exit $? "Failed to copy ${host_patch_repo}/Packages"
    elif [ ! -d "${SHARED_DIR}/patches/Packages" ]; then
        # Create an empty Packages dir
        mkdir "${SHARED_DIR}/patches/Packages"
        check_rc_exit $? "Failed to create ${SHARED_DIR}/patches/Packages"
    fi

    mkdir -p \
        "${SHARED_DIR}/patches/metadata/available" \
        "${SHARED_DIR}/patches/metadata/applied" \
        "${SHARED_DIR}/patches/metadata/committed"
    check_rc_exit $? "Failed to create director(ies): ${SHARED_DIR}/patches/metadata/..."

    local metadata_to_copy=
    for state in applied committed; do
        if [ ! -d /opt/patching/metadata/${state} ]; then
            continue
        fi

        metadata_to_copy=$(find /opt/patching/metadata/${state} -type f -exec grep -q "<sw_version>${ISO_VERSION}</sw_version>" {} \; -print)
        if [ -n "${metadata_to_copy}" ]; then
            rsync -a "${metadata_to_copy}" "${SHARED_DIR}/patches/metadata/${state}/"
            check_rc_exit $? "Failed to copy ${state} patch metadata"
        fi
    done
}

function query_patched_pkg {
    local pkg=$1
    local pkg_location=
    local shared_patch_repo=${SHARED_DIR}/patches

    pkg_location=$(dnf repoquery --disablerepo=* --repofrompath local,file:///${shared_patch_repo} --latest-limit=1 --location -q ${pkg})
    if [ $? -eq 0 -a -n "${pkg_location}" ]; then
        echo ${pkg_location/file:\/\/\//}
    fi
}

function extract_pkg_to_workdir {
    local pkg=$1
    local pkgfile=

    pkgfile=$(query_patched_pkg ${pkg})
    if [ -z "${pkgfile}" ]; then
        # Nothing to do
        return
    fi

    [ -f "${pkgfile}" ] || fatal_error "File doesn't exist, unable to extract: ${pkgfile}"

    pushd "${WORKDIR}" >/dev/null
    log_info "Extracting files from ${pkgfile}"
    rpm2cpio ${pkgfile} | cpio -idmv
    check_rc_exit $? "Failed to extract files from ${pkgfile}"
    popd >/dev/null
}

function extract_shared_files {
    if [ -d "${SHARED_DIR}" ]; then
        # If the shared dir already exists, assume we don't need to re-extract
        return
    fi

    mkdir -p "${SHARED_DIR}"
    check_rc_exit $? "Failed to create directory: ${SHARED_DIR}"

    # Check ISO content
    [ -f "${MNTDIR}/LiveOS/squashfs.img" ] || fatal_error "squashfs.img not found on ${INPUT_ISO}"

    # Setup shared patch data
    if [ "${PATCHES_FROM_HOST}" = "yes" ]; then
        get_patches_from_host
    else
        if [ -d "${MNTDIR}/patches" ]; then
            rsync -a "${MNTDIR}/patches/" "${SHARED_DIR}/patches/"
            check_rc_exit $? "Failed to copy patches repo from ${INPUT_ISO}"
        fi
    fi

    # Mark the DNF cache expired, in case there was previous ad-hoc repo data
    dnf clean expire-cache

    local squashfs_img_file=${MNTDIR}/LiveOS/squashfs.img
    if [ "${PATCHES_FROM_HOST}" = "yes" ]; then
        extract_pkg_to_workdir 'pxe-network-installer'

        local patched_squashfs_img_file=${WORKDIR}/var/www/pages/feed/rel-${ISO_VERSION}/LiveOS/squashfs.img
        if [ -f "${patched_squashfs_img_file}" ]; then
            # Use the patched squashfs.img
            squashfs_img_file=${patched_squashfs_img_file}
        fi
    fi

    mkdir "${SHARED_DIR}/LiveOS"
    rsync -a "${squashfs_img_file}" "${SHARED_DIR}/LiveOS/"
    check_rc_exit $? "Failed to copy rootfs: ${patched_squashfs_img_file}"

    # The CentOS kickstart files are on the system controller in their own directory.
    # Copy them into miniboot ISO.
    [ -f /etc/build.info ] || fatal_error "File /etc/build.info does not exist. Cannot determine software version."
    source /etc/build.info
    [ -n "$SW_VERSION" ] || fatal_error "SW_VERSION is not in /etc/build.info. Cannot determine software version."
    local kickstart_files_dir=/var/www/pages/feed/rel-${SW_VERSION}/kickstart/centos

    mkdir "${SHARED_DIR}/kickstart" || fatal_error "mkdir ${SHARED_DIR}/kickstart failed"
    rsync -a "${kickstart_files_dir}"/miniboot_*.cfg "${SHARED_DIR}"/kickstart
    check_rc_exit $? "Failed to copy kickstart files from ${kickstart_files_dir}"

    # Any files in $KICKSTART_OVERRIDE_DIR are used in place of the files from above:
    if [ -d "${KICKSTART_OVERRIDE_DIR}" ] && \
            [ "$(echo "${KICKSTART_OVERRIDE_DIR}"/miniboot_*.cfg)" != \
                "${KICKSTART_OVERRIDE_DIR}/miniboot_*.cfg" ]; then
        log_info "Copying override cfg files from ${KICKSTART_OVERRIDE_DIR}"
        cp "${KICKSTART_OVERRIDE_DIR}"/miniboot_*.cfg "${SHARED_DIR}"/kickstart
        check_rc_exit $? "Failed to copy override kickstart files from ${KICKSTART_OVERRIDE_DIR}"
    fi

    rsync -a "${MNTDIR}/isolinux.cfg" "${SHARED_DIR}/"
    check_rc_exit $? "Failed to copy isolinux.cfg from ${INPUT_ISO}"

    rsync -a "${MNTDIR}/Packages/" "${SHARED_DIR}/Packages/"
    check_rc_exit $? "Failed to copy base packages from ${INPUT_ISO}"

    rsync -a "${MNTDIR}/repodata/" "${SHARED_DIR}/repodata/"
    check_rc_exit $? "Failed to copy base repodata from ${INPUT_ISO}"
}

function extract_node_files {
    # Copy files for mini ISO build
    rsync ${VERBOSE_RSYNC} -a \
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
        "${MNTDIR}/" "${BUILDDIR}/"
    check_rc_exit $? "Failed to rsync ISO content from ${MNTDIR} to ${BUILDDIR}"

    if [ "${PATCHES_FROM_HOST}" = "yes" ]; then
        local patched_initrd_file=${WORKDIR}/pxeboot/rel-${ISO_VERSION}/installer-intel-x86-64-initrd_1.0
        local patched_vmlinuz_file=${WORKDIR}/pxeboot/rel-${ISO_VERSION}/installer-bzImage_1.0

        # First, check to see if pxe-network-installer is already extracted.
        # If this is the first setup for this ISO, it will have been extracted
        # during the shared setup, and we don't need to do it again.
        if [ ! -f "${patched_initrd_file}" ]; then
            extract_pkg_to_workdir 'pxe-network-installer'
        fi

        # Copy patched files, as appropriate
        if [ -f "${patched_initrd_file}" ]; then
            rsync -a "${patched_initrd_file}" "${BUILDDIR}"/initrd.img
            check_rc_exit $? "Failed to copy ${patched_initrd_file}"
        fi

        if [ -f "${patched_vmlinuz_file}" ]; then
            rsync -a "${patched_vmlinuz_file}" "${BUILDDIR}"/vmlinuz
            check_rc_exit $? "Failed to copy ${patched_vmlinuz_file}"
        fi
    fi

    # Setup syslinux and grub cfg files
    generate_boot_cfg "${BUILDDIR}"

    # Set/update boot parameters
    if [ ${#PARAMS[@]} -gt 0 ]; then
        for p in ${PARAMS[@]}; do
            param=${p%%=*} # Strip from the first '=' on
            value=${p#*=}  # Strip to the first '='

            update_parameter "${BUILDDIR}" "${param}" "${value}"
        done
    fi

    unmount_efiboot_img

    mkdir -p "${NODE_DIR}" || fatal_error "Failed to create ${NODE_DIR}"

    # Setup symlinks to the shared content, which lighttpd can serve
    pushd ${NODE_DIR} >/dev/null
    ln -s ../../shared/* .
    popd >/dev/null

    # Rebuild the ISO
    OUTPUT_ISO=${NODE_DIR}/bootimage.iso
    log_info "Creating ${OUTPUT_ISO} from BUILDDIR: ${BUILDDIR}"
    mkisofs -o "${OUTPUT_ISO}" \
        -R -D -A 'oe_iso_boot' -V 'oe_iso_boot' \
        -quiet \
        -b isolinux.bin -c boot.cat -no-emul-boot \
        -boot-load-size 4 -boot-info-table \
        -eltorito-alt-boot \
        -e images/efiboot.img \
        -no-emul-boot \
        "${BUILDDIR}"
    check_rc_exit $? "mkisofs failed"

    isohybrid --uefi "${OUTPUT_ISO}"
    check_rc_exit $? "isohybrid failed"
    implantisomd5 "${OUTPUT_ISO}"
    check_rc_exit $? "implantisomd5 failed"
    log_path_size "$OUTPUT_ISO" "Size of bootimage.iso"
    # Setup the kickstart
    local ksfile=${SHARED_DIR}/kickstart/miniboot_${KS_NODETYPE}_ks.cfg

    cp "${ksfile}" "${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg"
    check_rc_exit $? "Failed to copy ${ksfile} to ${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg"

    # Number of dirs in the NODE_URL: Count the / characters, subtracting 2 for http:// or https://
    DIRS=$(($(grep -o "/" <<< "$NODE_URL" | wc -l) - 2))

    # Escape the / chars for use in sed
    NODE_URL_SED="${NODE_URL//\//\\/}"

    sed -i "s#xxxHTTP_URLxxx#${NODE_URL_SED}#g;
            s#xxxHTTP_URL_PATCHESxxx#${NODE_URL_SED}/patches#g;
            s#NUM_DIRS#${DIRS}#g" \
        "${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg"

    # Append the custom addon
    if [ -n "${ADDON}" ]; then
        cat <<EOF >> "${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg"

%post --erroronfail

# Source common functions
. /tmp/ks-functions.sh

$(cat "${ADDON}")

%end
EOF
    fi
}

function create_miniboot_iso {
    # Determine release version from ISO
    [ -f ${MNTDIR}/upgrades/version ] || fatal_error "Version info not found on input ISO: ${INPUT_ISO}"
    ISO_VERSION=$(source ${MNTDIR}/upgrades/version && echo ${VERSION})
    if [ -z "${ISO_VERSION}" ]; then
        fatal_error "Failed to determine version of installation ISO from ${MNTDIR}/upgrades/version"
    fi

    # Copy the common files from the ISO, if needed
    extract_shared_files

    # Extract/generate the node-specific files
    extract_node_files
}

#
# Main
#
function main {
    # if [ "$(get_os)" != centos ]; then
    #     fatal_error "This script must be invoked on CentOS only"
    # fi
    parse_arguments "$@"
    initialize_and_lock
    mount_iso "${INPUT_ISO}" "${SCRATCH_DIR}"
    create_miniboot_iso
    unmount_iso
    exit 0
}

# Execute main if script is executed directly (not sourced):
# This allows for shunit2 testing
if [[ "${BASH_SOURCE[0]}" = "$0" ]]; then
    main "$@"
fi
