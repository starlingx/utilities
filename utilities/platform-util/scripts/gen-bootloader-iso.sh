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
declare CLEAN_NODE_DIR="no"
declare CLEAN_SHARED_DIR="no"
declare DEFAULT_GRUB_ENTRY=
declare DEFAULT_LABEL=
declare DEFAULT_SYSLINUX_ENTRY=
declare DELETE="no"
declare GRUB_TIMEOUT=-1
declare INPUT_ISO=
declare ISO_VERSION=
declare KS_NODETYPE=
declare -i LOCK_TMOUT=600 # Wait up to 10 minutes, by default
declare NODE_ID=
declare ORIG_PWD=$PWD
declare OUTPUT_ISO=
declare -a PARAMS
declare PATCHES_FROM_HOST="yes"
declare -i TIMEOUT=0
declare UPDATE_TIMEOUT="no"
declare WORKDIR=
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
# Parse cmdline arguments
#
LONGOPTS="input:,addon:,param:,default-boot:,timeout:,lock-timeout:,patches-from-iso"
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
        --lock-timeout)
            LOCK_TMOUT=$2
            shift 2
            if [ $LOCK_TMOUT -le 0 ]; then
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

#
# generate boot cfg for CentOS
#
function generate_boot_cfg_centos {
    local isodir=$1

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


#
# generate boot cfg for Debian
# This requires the following arguments:
function generate_boot_cfg_debian {
    local isodir=$1

    local BOOT_IP_ARG="${BOOT_IP}::${BOOT_GATEWAY}:${BOOT_NETMASK}:${BOOT_HOSTNAME}:${BOOT_INTERFACE}:${DNS}"
    local PARAM_LIST=
    # Set/update boot parameters
    if [ ${#PARAMS[@]} -gt 0 ]; then
        for p in ${PARAMS[@]}; do
            param=${p%%=*}
            value=${p#*=}
            PARAM_LIST="${PARAM_LIST} ${param}=${value}"
        done
    fi
    echo ${PARAM_LIST}
    COMMON_ARGS="initrd=/initrd instdate=@1656353118 instw=60 instiso=instboot"
    COMMON_ARGS="${COMMON_ARGS} biosplusefi=1 instnet=0"
    COMMON_ARGS="${COMMON_ARGS} ks=file:///kickstart/miniboot.cfg"
    COMMON_ARGS="${COMMON_ARGS} rdinit=/install instname=debian instbr=starlingx instab=0"
    COMMON_ARGS="${COMMON_ARGS} insturl=${BASE_URL}/ostree_repo ip=${BOOT_IP_ARG}"
    COMMON_ARGS="${COMMON_ARGS} BLM=2506 FSZ=32 BSZ=512 RSZ=20480 VSZ=20480 instdev=/dev/sda"
    COMMON_ARGS="${COMMON_ARGS} console=ttyS0,115200 console=tty1 defaultkernel=vmlinuz-*[!t]-amd64"
    COMMON_ARGS="${COMMON_ARGS} ${PARAM_LIST}"

    for f in ${isodir}/isolinux/isolinux.cfg; do
             cat <<EOF > ${f}
prompt 0
timeout 100
allowoptions 1
serial 0 115200

ui vesamenu.c32
menu background   #ff555555
menu title Select kernel options and boot kernel
menu tabmsg Press [Tab] to edit, [Return] to select

DEFAULT 0
LABEL 0
    menu label ^Debian Controller Install
    kernel /bzImage-std
    ipappend 2
    append ${COMMON_ARGS} traits=controller

LABEL 1
    menu label ^Debian All-In-One Install
    kernel /bzImage-std
    ipappend 2
    append ${COMMON_ARGS} traits=controller,worker

LABEL 2
    menu label ^Debian All-In-One (lowlatency) Install
    kernel /bzImage-rt
    ipappend 2
    append ${COMMON_ARGS} traits=controller,worker,lowlatency

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
    linuxefi /bzImage ${COMMON_ARGS} console=ttyS0,115200 serial
    initrdefi /initrd
}

menuentry 'Graphical Console' --id=graphical {
    linuxefi /bzImage ${COMMON_ARGS} console=tty0
    initrdefi /initrd
}
EOF
    done
}

function generate_boot_cfg {
    local isodir=$1

    if [ -z "${EFI_MOUNT}" ]; then
        mount_efiboot_img ${isodir}
    fi

    if [ "${OS_NAME}" == "CentOS" ]; then
        generate_boot_cfg_centos ${isodir}
    else
        generate_boot_cfg_debian ${isodir}
    fi
}

function cleanup {
    if [ $? -ne 0 ]; then
        # Clean up from failure
        handle_delete
    fi

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
    if [ $(ls -A ${NODE_DIR_BASE} 2>/dev/null | wc -l) = 0 ]; then
        if [ -d ${NODE_DIR_BASE} ]; then
            rmdir ${NODE_DIR_BASE}
        fi

        if [ -d ${SHARED_DIR} ]; then
            rm -rf ${SHARED_DIR}
        fi
    fi

    # Mark the DNF cache expired
    dnf clean expire-cache
}

function get_patches_from_host {
    local host_patch_repo=/var/www/pages/updates/rel-${ISO_VERSION}

    if [ ! -d ${host_patch_repo} ]; then
        log_error "Patch repo not found: ${host_patch_repo}"
        # Don't fail, as there could be scenarios where there's nothing on
        # the host related to the release on the ISO
        return
    fi

    mkdir -p ${SHARED_DIR}/patches
    if [ $? -ne 0 ]; then
        log_error "Failed to create directory: ${SHARED_DIR}/patches"
        exit 1
    fi

    rsync -a ${host_patch_repo}/repodata ${SHARED_DIR}/patches/
    if [ $? -ne 0 ]; then
        log_error "Failed to copy ${host_patch_repo}/repodata"
        exit 1
    fi

    if [ -d ${host_patch_repo}/Packages ]; then
        rsync -a ${host_patch_repo}/Packages ${SHARED_DIR}/patches/
        if [ $? -ne 0 ]; then
            log_error "Failed to copy ${host_patch_repo}/Packages"
            exit 1
        fi
    elif [ ! -d ${SHARED_DIR}/patches/Packages ]; then
        # Create an empty Packages dir
        mkdir ${SHARED_DIR}/patches/Packages
        if [ $? -ne 0 ]; then
            log_error "Failed to create ${SHARED_DIR}/patches/Packages"
            exit 1
        fi
    fi

    mkdir -p \
        ${SHARED_DIR}/patches/metadata/available \
        ${SHARED_DIR}/patches/metadata/applied \
        ${SHARED_DIR}/patches/metadata/committed
    if [ $? -ne 0 ]; then
        log_error "Failed to create directory: ${SHARED_DIR}/patches/metadata/${state}"
        exit 1
    fi

    local metadata_to_copy=
    for state in applied committed; do
        if [ ! -d /opt/patching/metadata/${state} ]; then
            continue
        fi

        metadata_to_copy=$(find /opt/patching/metadata/${state} -type f -exec grep -q "<sw_version>${ISO_VERSION}</sw_version>" {} \; -print)
        if [ -n "${metadata_to_copy}" ]; then
            rsync -a ${metadata_to_copy} ${SHARED_DIR}/patches/metadata/${state}/
            if [ $? -ne 0 ]; then
                log_error "Failed to copy ${state} patch metadata"
                exit 1
            fi
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

    if [ ! -f "${pkgfile}" ]; then
        log_error "File doesn't exist, unable to extract: ${pkgfile}"
        exit 1
    fi

    pushd ${WORKDIR} >/dev/null
    echo "Extracting files from ${pkgfile}"
    rpm2cpio ${pkgfile} | cpio -idmv
    if [ $? -ne 0 ]; then
        log_error "Failed to extract files from ${pkgfile}"
        exit 1
    fi
    popd >/dev/null
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

    # Setup shared patch data
    if [ ${PATCHES_FROM_HOST} = "yes" ]; then
        get_patches_from_host
    else
        if [ -d ${MNTDIR}/patches ]; then
            rsync -a ${MNTDIR}/patches/ ${SHARED_DIR}/patches/
            if [ $? -ne 0 ]; then
                log_error "Failed to copy patches repo from ${INPUT_ISO}"
                exit 1
            fi
        fi
    fi

    # Mark the DNF cache expired, in case there was previous ad-hoc repo data
    dnf clean expire-cache

    local squashfs_img_file=${MNTDIR}/LiveOS/squashfs.img
    if [ ${PATCHES_FROM_HOST} = "yes" ]; then
        extract_pkg_to_workdir 'pxe-network-installer'

        local patched_squashfs_img_file=${WORKDIR}/var/www/pages/feed/rel-${ISO_VERSION}/LiveOS/squashfs.img
        if [ -f ${patched_squashfs_img_file} ]; then
            # Use the patched squashfs.img
            squashfs_img_file=${patched_squashfs_img_file}
        fi
    fi

    mkdir ${SHARED_DIR}/LiveOS
    rsync -a ${squashfs_img_file} ${SHARED_DIR}/LiveOS/
    if [ $? -ne 0 ]; then
        log_error "Failed to copy rootfs: ${patched_squashfs_img_file}"
        exit 1
    fi

    local kickstart_files_dir=${MNTDIR}/
    if [ ${PATCHES_FROM_HOST} = "yes"  ]; then
        extract_pkg_to_workdir 'platform-kickstarts'

        local patched_kickstart_files_dir=${WORKDIR}/var/www/pages/feed/rel-${ISO_VERSION}
        if [ -f ${patched_kickstart_files_dir}/miniboot_controller_ks.cfg ]; then
            # Use the patched kickstart files
            kickstart_files_dir=${patched_kickstart_files_dir}
        fi
    fi

    mkdir ${SHARED_DIR}/kickstart/
    rsync -a ${kickstart_files_dir}/miniboot_*.cfg ${SHARED_DIR}/kickstart
    if [ $? -ne 0 ]; then
        log_error "Failed to copy kickstart files from ${kickstart_files_dir}"
        exit 1
    fi

    rsync -a ${MNTDIR}/isolinux.cfg ${SHARED_DIR}/
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
}

function extract_debian_files {
    # Copy files for mini ISO build
    rsync -a \
          --exclude ostree_repo \
          --exclude pxeboot \
        ${MNTDIR}/ ${BUILDDIR}

    rc=$?
    if [ "${rc}" -ne "0" ]; then
        log_error "Call to rsync ISO content on debian failed: [rc=${rc}]."
        exit "${rc}"
    fi

    # Setup syslinux and grub cfg files
    generate_boot_cfg ${BUILDDIR}

    unmount_efiboot_img

    mkdir -p ${NODE_DIR}
    if [ $? -ne 0 ]; then
        log_error "Failed to create ${NODE_DIR}"
        exit 1
    fi

    echo "BUILDDIR is ${BUILDDIR}"
    # Rebuild the ISO
    OUTPUT_ISO=${NODE_DIR}/bootimage.iso
    mkisofs -o ${OUTPUT_ISO} \
        -A 'instboot' -V 'instboot' \
        -quiet -U -J -joliet-long -r -iso-level 2 \
        -b isolinux/isolinux.bin -c isolinux/boot.cat -no-emul-boot \
        -boot-load-size 4 -boot-info-table \
        -eltorito-alt-boot \
        -e efi.img \
        -no-emul-boot \
        ${BUILDDIR}

    isohybrid --uefi ${OUTPUT_ISO}
    implantisomd5 ${OUTPUT_ISO}
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

    if [ ${PATCHES_FROM_HOST} = "yes" ]; then
        local patched_initrd_file=${WORKDIR}/pxeboot/rel-${ISO_VERSION}/installer-intel-x86-64-initrd_1.0
        local patched_vmlinuz_file=${WORKDIR}/pxeboot/rel-${ISO_VERSION}/installer-bzImage_1.0

        # First, check to see if pxe-network-installer is already extracted.
        # If this is the first setup for this ISO, it will have been extracted
        # during the shared setup, and we don't need to do it again.
        if [ ! -f ${patched_initrd_file} ]; then
            extract_pkg_to_workdir 'pxe-network-installer'
        fi

        # Copy patched files, as appropriate
        if [ -f ${patched_initrd_file} ]; then
            rsync -a ${patched_initrd_file} ${BUILDDIR}/initrd.img
            if [ $? -ne 0 ]; then
                log_error "Failed to copy ${patched_initrd_file}"
                exit 1
            fi
        fi

        if [ -f ${patched_vmlinuz_file} ]; then
            rsync -a ${patched_vmlinuz_file} ${BUILDDIR}/vmlinuz
            if [ $? -ne 0 ]; then
                log_error "Failed to copy ${patched_vmlinuz_file}"
                exit 1
            fi
        fi
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
    local ksfile=${SHARED_DIR}/kickstart/miniboot_${KS_NODETYPE}_ks.cfg

    cp ${ksfile} ${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg
    if [ $? -ne 0 ]; then
        log_error "Failed to copy ${ksfile} to ${NODE_DIR}/miniboot_${KS_NODETYPE}.cfg"
        exit 1
    fi

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

# Grab the lock, to protect against simultaneous execution
LOCK_FILE=/var/run/.gen-bootloader-iso.lock
exec 200>${LOCK_FILE}
flock -w ${LOCK_TMOUT} 200
if [ $? -ne 0 ]; then
    log_error "Failed waiting for lock: ${LOCK_FILE}"
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

# Run cleanup on any exit
trap cleanup EXIT

BUILDDIR=$(mktemp -d -p /scratch gen_bootloader_build_XXXXXX)
if [ -z "${BUILDDIR}" -o ! -d ${BUILDDIR} ]; then
    log_error "Failed to create builddir. Aborting..."
    exit 1
fi

WORKDIR=$(mktemp -d -p /scratch gen_bootloader_workdir_XXXXXX)
if [ -z "${WORKDIR}" -o ! -d ${WORKDIR} ]; then
    log_error "Failed to create builddir. Aborting..."
    exit 1
fi

mount_iso ${INPUT_ISO}

if [ -e "${MNTDIR}/ostree_repo" ]; then
    # This is a debian ISO.
    echo "ostree_repo exists in the iso"
    OS_NAME="Debian"
    extract_debian_files
else
    OS_NAME="CentOS"
    # Determine release version from ISO
    if [ ! -f ${MNTDIR}/upgrades/version ]; then
        log_error "Version info not found on ${INPUT_ISO}"
        exit 1
    fi

    ISO_VERSION=$(source ${MNTDIR}/upgrades/version && echo ${VERSION})
    if [ -z "${ISO_VERSION}" ]; then
        log_error "Failed to determine version of installation ISO"
        exit 1
    fi

    # Copy the common files from the ISO, if needed
    extract_shared_files

    # Extract/generate the node-specific files
    extract_node_files
fi

unmount_iso

exit 0
