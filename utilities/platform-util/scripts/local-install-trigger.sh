#!/bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Arm a local reinstall and restore on an AIO-SX subcloud.
#
# Validates locally prestaged data, writes a one-shot
# backup_restore_values.yml to platform_backup, updates install_kargs
# in boot.env, and sets BootNext to the "Local Factory Restore" UEFI
# entry before rebooting.
#

function log_fatal {
    echo "$(date "+%F %H:%M:%S") FATAL: ${*}" >&2
    exit 1
}

function log_warn {
    echo "$(date "+%F %H:%M:%S") WARN: ${*}" >&2
}

function log_info {
    echo "$(date "+%F %H:%M:%S") INFO: $*"
}

function check_rc_die {
    local -i rc=${1}
    local msg="${2}"
    if [ ${rc} -ne 0 ]; then
        log_fatal "${msg} [rc=${rc}]"
    fi
}

function usage {
    cat <<ENDUSAGE
Arm a local reinstall and restore on an AIO-SX subcloud.

Usage:
    $(basename "$0") --restore-mode <factory|auto>
                     [--sw-version <version>]
                     [--extra-kargs <string>]

    --restore-mode <factory|auto>
        factory: restore from the factory backup (factory_backup.tgz)
        auto:    restore from a versioned platform backup tarball

    --sw-version <version>
        SW version to reinstall. Defaults to the running system version.

    --extra-kargs <string>
        Additional kernel arguments appended to install_kargs in boot.env.
ENDUSAGE
}

RESTORE_MODE=""
SW_VERSION=""
EXTRA_KARGS=""
BOOT_ENV="/boot/efi/EFI/BOOT/boot.env"
PLATFORM_BACKUP="/opt/platform-backup"
EFI_LABEL="Local Factory Restore"

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --help|-h)
            usage
            exit 0
            ;;
        --restore-mode)
            RESTORE_MODE="$2"
            shift 2
            ;;
        --sw-version)
            SW_VERSION="$2"
            shift 2
            ;;
        --extra-kargs)
            EXTRA_KARGS="$2"
            shift 2
            ;;
        *)
            log_fatal "Unexpected option: $1"
            ;;
    esac
done

if [ -z "${RESTORE_MODE}" ]; then
    usage
    log_fatal "--restore-mode is required"
fi

if [ "${RESTORE_MODE}" != "factory" ] && [ "${RESTORE_MODE}" != "auto" ]; then
    log_fatal "--restore-mode must be 'factory' or 'auto'; got '${RESTORE_MODE}'"
fi

if [ -z "${SW_VERSION}" ]; then
    SW_VERSION=$(awk -F= '/^SW_VERSION/ {print $2}' /etc/build.info | tr -d '"')
    if [ -z "${SW_VERSION}" ]; then
        log_fatal "Could not determine SW version from /etc/build.info; use --sw-version"
    fi
    log_info "Using SW version from build.info: ${SW_VERSION}"
else
    log_info "Using SW version: ${SW_VERSION}"
fi

# Validate that the required prestaged artifacts exist on platform_backup.
# Factory mode: ostree_repo, factory_backup tarball, and miniboot.cfg under
# factory/<version>/
# Auto mode: ostree_repo under <version>/, platform backup tarball under
# backups/<version>/
if [ ! -d "${PLATFORM_BACKUP}" ]; then
    log_fatal "platform_backup not found at ${PLATFORM_BACKUP}"
fi

if [ "${RESTORE_MODE}" = "factory" ]; then
    BACKUP_DIR="${PLATFORM_BACKUP}/factory/${SW_VERSION}"
    log_info "Validating factory prestaged data at ${BACKUP_DIR}"
    [ -d "${BACKUP_DIR}/ostree_repo" ] || \
        log_fatal "ostree_repo not found at ${BACKUP_DIR}/ostree_repo"
    ls "${BACKUP_DIR}"/factory_backup*.tgz >/dev/null 2>&1 || \
        log_fatal "factory_backup tarball not found in ${BACKUP_DIR}"
    [ -f "${BACKUP_DIR}/miniboot.cfg" ] || \
        log_fatal "miniboot.cfg not found at ${BACKUP_DIR}/miniboot.cfg"
else
    BACKUP_DIR="${PLATFORM_BACKUP}/backups/${SW_VERSION}"
    log_info "Validating auto-restore prestaged data at ${BACKUP_DIR}"
    [ -d "${PLATFORM_BACKUP}/${SW_VERSION}/ostree_repo" ] || \
        log_fatal "prestaged ostree_repo not found at ${PLATFORM_BACKUP}/${SW_VERSION}/ostree_repo"
    ls "${BACKUP_DIR}"/*_platform_backup_*.tgz >/dev/null 2>&1 || \
        log_fatal "platform backup tarball not found in ${BACKUP_DIR}"
fi

# Update install_kargs in boot.env for this reinstall:
if [ ! -f "${BOOT_ENV}" ]; then
    log_fatal "boot.env not found at ${BOOT_ENV}"
fi

INSTALL_KARGS=$(grep "^install_kargs=" "${BOOT_ENV}" | cut -d= -f2-)
if [ -z "${INSTALL_KARGS}" ]; then
    log_fatal "install_kargs not found in ${BOOT_ENV}"
fi

# Patch version-specific paths (ks=, insturl=) to target the requested SW_VERSION
INSTALL_KARGS=$(echo "${INSTALL_KARGS}" | sed \
    -e "s|ks=partition://platform_backup:factory/[^/]*/|ks=partition://platform_backup:factory/${SW_VERSION}/|" \
    -e "s|insturl=file:///tmp/platform-backup/factory/[^/]*/|insturl=file:///tmp/platform-backup/factory/${SW_VERSION}/|")

# Ensure onsite_restore=1 is present (triggers restore workflow in kickstart)
if ! echo "${INSTALL_KARGS}" | grep -q '\bonsite_restore=1\b'; then
    INSTALL_KARGS="${INSTALL_KARGS} onsite_restore=1"
fi

# Append any operator-supplied extra kernel arguments
if [ -n "${EXTRA_KARGS}" ]; then
    INSTALL_KARGS="${INSTALL_KARGS} ${EXTRA_KARGS}"
fi

log_info "Updating install_kargs in ${BOOT_ENV}"
sed -i "s|^install_kargs=.*|install_kargs=${INSTALL_KARGS}|" "${BOOT_ENV}"
check_rc_die $? "Failed to update install_kargs in ${BOOT_ENV}"

# Write one-shot backup_restore_values.yml. The kickstart (onsite_restore=1)
# checks here first, copies to auto-restore/, and deletes this file so the
# next reinstall falls back to the permanent factory copy.
ONESHOT_DIR="${PLATFORM_BACKUP}/.onsite-restore"
mkdir -p "${ONESHOT_DIR}"
check_rc_die $? "Failed to create ${ONESHOT_DIR}"

log_info "Writing one-shot backup_restore_values.yml to ${ONESHOT_DIR}"
cat > "${ONESHOT_DIR}/backup_restore_values.yml" <<EOF
auto_restore_mode: ${RESTORE_MODE}
initial_backup_dir: ${BACKUP_DIR}
ipmi_sel_event_monitoring: false
restore_mode: optimized
skip_registry_login: true
skip_patches_restore: true
exclude_sw_deployments: true
EOF
check_rc_die $? "Failed to write backup_restore_values.yml"

# For factory restore, the prestaged registry images file must be inside
# the factory backup dir, so we override the images_archive_dir variable
if [ "${RESTORE_MODE}" = "factory" ]; then
    cat >> "${ONESHOT_DIR}/backup_restore_values.yml" <<EOF
images_archive_dir: ${BACKUP_DIR}
EOF
    check_rc_die $? "Failed to append factory settings to backup_restore_values.yml"
fi

# Recreate the UEFI boot entry. A stale entry from a previous install may
# reference an old partition UUID, causing the selection to fall back to
# BootOrder instead of honoring BootNext. BMC virtual media insert can
# also overwrite the entry.
EFI_DEV=$(awk '$2 == "/boot/efi" {print $1}' /proc/mounts | head -1)
if [ -z "${EFI_DEV}" ]; then
    log_fatal "Cannot detect EFI partition from /proc/mounts"
fi
EFI_DISK=$(echo "${EFI_DEV}" | sed 's/p\?[0-9]*$//')
EFI_PART_NUM=$(echo "${EFI_DEV}" | grep -o '[0-9]*$')
log_info "EFI device: ${EFI_DEV} (disk: ${EFI_DISK}, part: ${EFI_PART_NUM})"

OLD_BOOTNUM=$(efibootmgr | grep "${EFI_LABEL}" | cut -c5-8)
if [ -n "${OLD_BOOTNUM}" ]; then
    log_info "Removing existing UEFI boot entry Boot${OLD_BOOTNUM} ('${EFI_LABEL}')"
    efibootmgr -B -b "${OLD_BOOTNUM}" || log_warn "Failed to remove Boot${OLD_BOOTNUM}"
fi

log_info "Creating UEFI boot entry '${EFI_LABEL}'"
efibootmgr -C -w \
    -p "${EFI_PART_NUM}" \
    -L "${EFI_LABEL}" \
    -d "${EFI_DISK}" \
    -l '\EFI\BOOT\BOOTX64.EFI'
check_rc_die $? "Failed to create UEFI boot entry"
EFI_BOOTNUM=$(efibootmgr | grep "${EFI_LABEL}" | cut -c5-8)
if [ -z "${EFI_BOOTNUM}" ]; then
    log_fatal "UEFI entry '${EFI_LABEL}' not found after creation"
fi
log_info "Created UEFI boot entry Boot${EFI_BOOTNUM}"

# Update install_bootnum in boot.env so grub auto-selects the install entry
# when BootCurrent matches. The boot number may change if the UEFI entry was
# recreated.
EFI_BOOTNUM_DEC=$(printf '%d' "0x${EFI_BOOTNUM}")
CURRENT_BOOTNUM=$(grep "^install_bootnum=" "${BOOT_ENV}" | cut -d= -f2)
if [ "${CURRENT_BOOTNUM}" != "${EFI_BOOTNUM_DEC}" ]; then
    log_info "Updating install_bootnum in boot.env: ${CURRENT_BOOTNUM} -> ${EFI_BOOTNUM_DEC}"
    if grep -q "^install_bootnum=" "${BOOT_ENV}"; then
        sed -i "s/^install_bootnum=.*/install_bootnum=${EFI_BOOTNUM_DEC}/" "${BOOT_ENV}"
    else
        sed -i "1 a install_bootnum=${EFI_BOOTNUM_DEC}" "${BOOT_ENV}"
    fi
    check_rc_die $? "Failed to update install_bootnum in ${BOOT_ENV}"
fi

log_info "Setting BootNext to Boot${EFI_BOOTNUM} (${EFI_LABEL})"
efibootmgr -n "${EFI_BOOTNUM}"
check_rc_die $? "Failed to set BootNext"

log_info "Arming complete: restore-mode=${RESTORE_MODE} sw-version=${SW_VERSION}"
log_info "Rebooting..."
systemctl reboot
