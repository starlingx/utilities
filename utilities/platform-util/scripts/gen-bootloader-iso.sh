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
source "$SCRIPTDIR"/stx-iso-utils.sh

ADDON=
BASE_URL=
BOOT_ARGS_COMMON=
BOOT_ARGS_SPECIFIC=
BOOT_GATEWAY=
BOOT_HOSTNAME=
BOOT_INTERFACE=
BOOT_IP=
BOOT_NETMASK=
MINIBOOT_INITRD_FILE=/var/miniboot/initrd-mini  # populated by the loadbuild at this location
DEFAULT_GRUB_ENTRY=
DEFAULT_SYSLINUX_ENTRY=
DELETE="no"
GRUB_TIMEOUT=-1
INITRD_FILE=
INSTALL_TYPE=
REPACK=no     # REPACK initrd is disabled until signing is fixed
INPUT_ISO=
LOCK_FILE=/var/run/.gen-bootloader-iso.lock
LOCK_TMOUT=600  # Wait up to 10 minutes, by default
LOG_TAG=$SCRIPTNAME
NODE_ID=
OUTPUT_ISO=
REPACK=yes  # Repack/trim the initrd and kernel images by default
SCRATCH_DIR=${SCRATCH_DIR:-/scratch}
TIMEOUT=100
VERBOSE=${VERBOSE:-}
VERBOSE_LOG_DIR=/var/log/dcmanager/miniboot
VERBOSE_OVERRIDE_FILE=/tmp/gen-bootloader-verbose  # turn on verbose if this file is present
WORKDIR=
WWW_ROOT_DIR=
XZ_ARGS="--threads=0 -9 --format=lzma"

declare -a PARAMS

# Initialized via initialize_and_lock:
BUILDDIR=
NODE_DIR=
NODE_DIR_BASE=
VERBOSE_RSYNC=
WORKDIR=

# Initialized by stx-iso-utils.sh:mount_efiboot_img
EFI_MOUNT=

# Set this to a directory path containing kickstart *.cfg script(s) for testing:
KICKSTART_OVERRIDE_DIR=${KICKSTART_OVERRIDE_DIR:-/var/miniboot/kickstart-override}

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

function get_path_size {
    local path=$1
    du -hs "$path" | awk '{print $1}'
}

function log_path_size {
    local path=$1
    local msg=$2
    log_info "$msg: $(get_path_size "$path")"
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
    --initrd <initrd-file>:  Specify an existing initrd file to use
    --timeout <seconds>:     Specify boot menu timeout, in seconds
    --lock-timeout <secs>:   Specify time to wait for mutex lock before aborting
    --patches-from-iso:      Ignored (obsolete)
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
    longopts="${longopts},base-url:,repack,initrd:,no-cache"
    longopts="${longopts},boot-gateway:,boot-hostname:,boot-interface:,boot-ip:,boot-netmask:"
    longopts="${longopts},help,verbose"

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
            # TODO: do we need to support --addon for debian?
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
                PARAMS+=("$2")
                shift 2
                ;;
            --default-boot)
                INSTALL_TYPE=$2
                shift 2
                # Supported install values:
                #0 - Standard Controller, Serial Console
                #1 - Standard Controller, Graphical Console
                #2 - AIO, Serial Console
                #3 - AIO, Graphical Console
                #4 - AIO Low-latency, Serial Console
                #5 - AIO Low-latency, Graphical Console
                local default_kernel='vmlinuz-*[!t]-amd64'
                local default_kernel_rt='vmlinuz-*-rt-amd64'
                local traits_standard="controller"
                local traits_aio="controller,worker"
                local traits_aio_rt="controller,worker,lowlatency"
                case ${INSTALL_TYPE} in
                    0)
                        DEFAULT_SYSLINUX_ENTRY=0
                        DEFAULT_GRUB_ENTRY=serial
                        BOOT_ARGS_SPECIFIC="traits=$traits_standard defaultkernel=$default_kernel"
                        ;;
                    1)
                        DEFAULT_SYSLINUX_ENTRY=1
                        DEFAULT_GRUB_ENTRY=graphical
                        BOOT_ARGS_SPECIFIC="traits=$traits_standard defaultkernel=$default_kernel"
                        ;;
                    2)
                        DEFAULT_SYSLINUX_ENTRY=0
                        DEFAULT_GRUB_ENTRY=serial
                        BOOT_ARGS_SPECIFIC="traits=$traits_aio defaultkernel=$default_kernel"
                        ;;
                    3)
                        DEFAULT_SYSLINUX_ENTRY=1
                        DEFAULT_GRUB_ENTRY=graphical
                        BOOT_ARGS_SPECIFIC="traits=$traits_aio defaultkernel=$default_kernel"
                        ;;
                    4)
                        DEFAULT_SYSLINUX_ENTRY=0
                        DEFAULT_GRUB_ENTRY=serial
                        BOOT_ARGS_SPECIFIC="traits=$traits_aio_rt defaultkernel=$default_kernel_rt"
                        ;;
                    5)
                        DEFAULT_SYSLINUX_ENTRY=1
                        DEFAULT_GRUB_ENTRY=graphical
                        BOOT_ARGS_SPECIFIC="traits=$traits_aio_rt defaultkernel=$default_kernel_rt"
                        ;;
                    *)
                        log_error "Invalid default boot menu option: ${INSTALL_TYPE}"
                        usage
                        exit 1
                        ;;
                esac
                ;;
            --timeout)
                timeout_arg=$2
                shift 2
                if [ $(( timeout_arg )) -gt 0 ]; then
                    TIMEOUT=$(( timeout_arg * 10 ))
                    GRUB_TIMEOUT=${timeout_arg}
                elif [ $(( timeout_arg )) -eq 0 ]; then
                    GRUB_TIMEOUT=0.001
                fi
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
            --no-repack)
                # Do not repack initrd and kernel images
                REPACK=no
                shift
                ;;
            --initrd)
                # Allow specifying an existing initrd file. If none is specified,
                # then $MINIBOOT_INITRD_FILE is used, if it exists
                INITRD_FILE=$2
                [ -f "$INITRD_FILE" ] || fatal_error "initrd file not found: $INITRD_FILE"
                shift 2
                ;;
            --lock-timeout)
                LOCK_TMOUT=$2
                shift 2
                if [ "$LOCK_TMOUT" -le 0 ]; then
                    echo "Lock timeout must be greater than 0" >&2
                    exit 1
                fi
                ;;
            --delete)
                DELETE="yes"
                shift
                ;;
            --patches-from-iso)
                # ignored - not applicable for debian/ostree
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
    [ -d "${WWW_ROOT_DIR}/iso" ] || mkdir "${WWW_ROOT_DIR}/iso"

    [ -f "$VERBOSE_OVERRIDE_FILE" ] && VERBOSE=1
    if [ -n "$VERBOSE" ]; then
        VERBOSE_RSYNC="--verbose"
        XZ_ARGS="--verbose $XZ_ARGS"

        # log all output to file
        if [ ! -d "$(dirname "$VERBOSE_LOG_DIR")" ]; then
            # For testing: the base directory does not exist - use /tmp instead
            VERBOSE_LOG_DIR=/tmp/miniboot
        fi
        [ -d "$VERBOSE_LOG_DIR" ] || mkdir -p "$VERBOSE_LOG_DIR"
        local logfile="${VERBOSE_LOG_DIR}/gen-bootloader-iso-${NODE_ID}.log"
        echo "Verbose: logging output to $logfile"
        exec > >(tee "$logfile") 2>&1
    fi

    # Initialize dynamic variables
    NODE_DIR_BASE="${WWW_ROOT_DIR}/nodes"
    NODE_DIR="${NODE_DIR_BASE}/${NODE_ID}"

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
    check_required_param "--default-boot" "${INSTALL_TYPE}"
    check_required_param "--base-url" "${BASE_URL}"
    check_required_param "--boot-ip" "${BOOT_IP}"
    check_required_param "--boot-interface" "${BOOT_INTERFACE}"

    if [ ! -f "${INPUT_ISO}" ]; then
        fatal_error "Input file does not exist: ${INPUT_ISO}"
    fi
    if [ -d "${NODE_DIR}" ]; then
        fatal_error "Output dir already exists: ${NODE_DIR}"
    fi

    # Run cleanup on any exit
    trap cleanup_on_exit EXIT

    BUILDDIR=$(mktemp -d -p "$SCRATCH_DIR" gen_bootloader_build_XXXXXX)
    if [ -z "${BUILDDIR}" ] || [ ! -d "${BUILDDIR}" ]; then
        fatal_error "Failed to create builddir: $BUILDDIR"
    fi

    WORKDIR=$(mktemp -d -p "$SCRATCH_DIR" gen_bootloader_initrd_XXXXXX)
    if [ -z "${WORKDIR}" ] || [ ! -d "${WORKDIR}" ]; then
        fatal_error "Failed to create initrd extract directory: $WORKDIR"
    fi
}

function generate_boot_cfg {
    local isodir=$1
    local instdev=/dev/sda

    # The 'ip=' format is defined by LAT:
    # Format:   ip=<client-ip>::<gw-ip>:<netmask>:<hostname>:<device>:off:<dns0-ip>:<dns1-ip>
    # However, LAT isn't really using ip= except for dhcp, and it is broken for IPv6.
    # So we are changing the delimiter to ',' for easier parsing in our miniboot.cfg file.
    # It won't affect LAT (but it is something to keep an eye towards in the future).
    local BOOT_IP_ARG="${BOOT_IP},,${BOOT_GATEWAY},${BOOT_NETMASK},${BOOT_HOSTNAME},${BOOT_INTERFACE},off"

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
    BOOT_ARGS_COMMON="initrd=/initrd instdate=@$(date +%s) instw=60 instiso=instboot"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} biosplusefi=1 instnet=0"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} ks=file:///kickstart/miniboot.cfg"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} rdinit=/install instname=debian instbr=starlingx instab=0"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} insturl=${BASE_URL}/ostree_repo ip=${BOOT_IP_ARG}"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} BLM=2506 FSZ=32 BSZ=512 RSZ=20480 VSZ=20480 instdev=${instdev}"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} inst_ostree_root=/dev/mapper/cgts--vg-root--lv"
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} inst_ostree_var=/dev/mapper/cgts--vg-var--lv"
    if [ -n "$VERBOSE" ]; then
        # pass this through to the miniboot.cfg kickstart to turn on debug:
        BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} debug_kickstart"
    fi
    BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} ${PARAM_LIST}"

    # Search the install kernel command line for the 'extra_boot_params='
    # option. If present, propagate the value into our BOOT_ARGS_COMMON, so
    # that any extra boot parameters are also provided during the boot from
    # miniboot ISO.
    # Multiple parameters can be separated by ',' here; we want to
    # split them out to be space-separated when adding to kernel arguments.
    # e.g.: for extra_boot_params=arg1=1,arg2=2, set kernel params: arg1=1 arg2=2
    local option
    for option in ${PARAM_LIST}; do
        if [ "${option%%=*}" = "extra_boot_params" ]; then
            # Do not include the 'extra_boot_params' string.
            # Strip out any commas and replace with space.
            extra_boot_params=${option#*=}               # remove 'extra_boot_params='
            extra_boot_params=${extra_boot_params//,/ }  # replace all ',' with ' '
            ilog "Adding extra_boot_params to BOOT_ARGS_COMMON: ${extra_boot_params}"
            BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} ${extra_boot_params}"
            break
        fi
    done

    # Uncomment for debugging:
    #BOOT_ARGS_COMMON="${BOOT_ARGS_COMMON} instsh=2 instpost=shell"
    log_verbose "BOOT_ARGS_COMMON: $BOOT_ARGS_COMMON"

    local serial_args="console=ttyS0,115200 serial"
    local graphical_args="console=tty0"

    # NOTES on kernel arguments for miniboot.iso:
    # We never boot into the lowlatency/rt kernel in the miniboot ISO - in fact, we can't because
    # it has been stripped out due to size. However, we do configure the 'traits' for Lowlatency
    # in the miniboot grub/syslinux kernel arguments. The traits boot argument is then used during
    # the miniboot.cfg kickstart to configure the proper kernel arguments for the lowlatency
    # kernel when it reboots into the ostree-based installation.

    log_verbose "Generating isolinux.cfg, default: $DEFAULT_SYSLINUX_ENTRY, timeout: $TIMEOUT"
    for f in ${isodir}/isolinux/isolinux.cfg; do
        cat <<EOF > "${f}"
prompt 0
timeout ${TIMEOUT}
allowoptions 1
serial 0 115200

ui vesamenu.c32
menu background   #ff555555
menu title Debian Miniboot Install ${NODE_ID}
menu tabmsg Press [Tab] to edit, [Return] to select

DEFAULT ${DEFAULT_SYSLINUX_ENTRY}
LABEL 0
    menu label ^Serial Console
    kernel /bzImage-std
    ipappend 2
    append ${BOOT_ARGS_COMMON} ${BOOT_ARGS_SPECIFIC} ${serial_args}

LABEL 1
    menu label ^Graphical Console
    kernel /bzImage-std
    ipappend 2
    append ${BOOT_ARGS_COMMON} ${BOOT_ARGS_SPECIFIC} ${graphical_args}
EOF
    done

    log_verbose "Generating grub.cfg, install_type: $INSTALL_TYPE, default: $DEFAULT_GRUB_ENTRY, timeout: $GRUB_TIMEOUT"
    for f in ${isodir}/EFI/BOOT/grub.cfg ${EFI_MOUNT}/EFI/BOOT/grub.cfg; do
        cat <<EOF > "${f}"
default=${DEFAULT_GRUB_ENTRY}
timeout=${GRUB_TIMEOUT}
search --no-floppy --set=root -l 'instboot'
set color_normal='light-gray/black'
set color_highlight='light-green/blue'

menuentry "Debian Miniboot Install ${NODE_ID}" --id=title {
    echo " "
}

menuentry 'UEFI Serial Console' --id=serial {
    linux /bzImage-std ${BOOT_ARGS_COMMON} ${BOOT_ARGS_SPECIFIC} ${serial_args}
    initrd /initrd
}

menuentry 'UEFI Graphical Console' --id=graphical {
    linux /bzImage-std ${BOOT_ARGS_COMMON} ${BOOT_ARGS_SPECIFIC} ${graphical_args}
    initrd /initrd
}
EOF
    done
if [ -n "$VERBOSE" ]; then
    log_verbose "Contents of ${isodir}/EFI/BOOT/grub.cfg"
    cat "${isodir}/EFI/BOOT/grub.cfg"
    log_verbose ""
    log_verbose "Contents of ${EFI_MOUNT}/EFI/BOOT/grub.cfg"
    cat "${EFI_MOUNT}/EFI/BOOT/grub.cfg"
fi
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
    fi
}

function create_miniboot_iso {
    log_info "Creating minitboot ISO"
    # Copy files for mini ISO build
    rsync $VERBOSE_RSYNC -a \
          --exclude ostree_repo \
          --exclude pxeboot \
        "${MNTDIR}/" "${BUILDDIR}"
    check_rc_exit $? "Failed to rsync ISO from $MNTDIR to $BUILDDIR"

    if [ "$REPACK" = yes ]; then
        # Use default initrd-mini location if none specified
        # This picks up the initrd-mini file if it is available
        # (included in ISO by the loadbuild). Otherwise we warn
        # and continue without repacking initrd - instead using
        # the original from the ISO.
        if [ -z "$INITRD_FILE" ]; then
            INITRD_FILE="$MINIBOOT_INITRD_FILE"
        fi
        if [ -f "$INITRD_FILE" ]; then
            if [ -f "${INITRD_FILE}.sig" ]; then
                # Overwrite the original ISO initrd file:
                log_info "Repacking miniboot ISO using initrd: ${INITRD_FILE} and ${INITRD_FILE}.sig"
                cp "$INITRD_FILE" "${BUILDDIR}/initrd"
                check_rc_exit $? "copy initrd failed"
                cp "${INITRD_FILE}.sig" "${BUILDDIR}/initrd.sig"
                check_rc_exit $? "copy initrd.sig failed"
            else
                log_error "No initrd.sig found at: ${INITRD_FILE}.sig ...skipping initrd repack"
            fi
        else
            log_warn "Could not find initrd file at $INITRD_FILE ...skipping initrd repack"
        fi
        log_info "Trimming miniboot ISO content"
        log_path_size "$BUILDDIR" "Size of extracted miniboot before trim"
        # Remove unused kernel images:
        rm "$BUILDDIR"/{bzImage,bzImage.sig,bzImage-rt,bzImage-rt.sig}
        check_rc_exit $? "failed to trim miniboot iso files"
        log_path_size "$BUILDDIR" "Size of extracted miniboot after trim"
    fi

    # For testing/debugging kickstart scripts. Support an override directory,
    # where any .cfg files are now copied into the /kickstart directory in the ISO
    # Any files in this override directory can replace the files from the ISO copied
    # from the rsync above.
    if [ -n "$KICKSTART_OVERRIDE_DIR" ] \
        && [ -d "$KICKSTART_OVERRIDE_DIR" ] \
        && [ "$(echo "$KICKSTART_OVERRIDE_DIR/"*.cfg)" != "$KICKSTART_OVERRIDE_DIR/*.cfg" ]; then
        log_info "Copying .cfg files from KICKSTART_OVERRIDE_DIR=$KICKSTART_OVERRIDE_DIR to $BUILDDIR/kickstart"
        cp "$KICKSTART_OVERRIDE_DIR/"*.cfg "$BUILDDIR/kickstart"
    fi

    # Setup syslinux and grub cfg files
    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img "${BUILDDIR}"
        check_rc_exit $? "failed to mount EFI"
        log_info "Using EFI_MOUNT=$EFI_MOUNT"
    fi
    generate_boot_cfg "${BUILDDIR}"
    unmount_efiboot_img

    mkdir -p "${NODE_DIR}" || fatal_error "Failed to create ${NODE_DIR}"

    # Rebuild the ISO
    OUTPUT_ISO=${NODE_DIR}/bootimage.iso
    log_info "Creating $OUTPUT_ISO from BUILDDIR: ${BUILDDIR}"
    mkisofs -o "${OUTPUT_ISO}" \
        -A 'instboot' -V 'instboot' \
        -quiet -U -J -joliet-long -r -iso-level 2 \
        -b isolinux/isolinux.bin -c isolinux/boot.cat -no-emul-boot \
        -boot-load-size 4 -boot-info-table \
        -eltorito-alt-boot \
        -e efi.img \
        -no-emul-boot \
        "${BUILDDIR}"
    check_rc_exit $? "mkisofs failed"

    isohybrid --uefi "${OUTPUT_ISO}"
    check_rc_exit $? "isohybrid failed"
    # implantisomd5 "${OUTPUT_ISO}"
    # check_rc_exit $? "implantisomd5 failed"
    log_path_size "$OUTPUT_ISO" "Size of bootimage.iso"
}

#
# Main
#
function main {
    if [ "$(get_os)" = centos ]; then
        # Invoke the legacy centos script then exit:
        "$SCRIPTDIR/gen-bootloader-iso-centos.sh" "$@"
        exit $?
    fi
    parse_arguments "$@"
    initialize_and_lock
    mount_iso "$INPUT_ISO" "$SCRATCH_DIR"
    create_miniboot_iso
    unmount_iso
    exit 0
}

# Execute main if script is executed directly (not sourced):
# This allows for shunit2 testing
if [[ "${BASH_SOURCE[0]}" = "$0" ]]; then
    main "$@"
fi
