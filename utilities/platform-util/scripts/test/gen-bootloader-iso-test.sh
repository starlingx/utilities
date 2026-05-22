#!/bin/bash
# vim:ft=sh:sts=4:sw=4

# This is a shunit2 test file for gen-bootloader-iso.sh
# See https://github.com/kward/shunit2
# Run the tests by executing this script.

# shellcheck disable=SC2016
# shellcheck disable=SC1090
# shellcheck disable=SC1091

NAME=gen-bootloader-iso-test

# shellcheck disable=SC2155,SC2034
SCRIPTDIR=$(readlink -m "$(dirname "$0")")
# shellcheck disable=SC2155,SC2034
readonly TARGET_SCRIPTDIR=$(readlink -m "${SCRIPTDIR}/..")

# Source shared test helpers
. "${SCRIPTDIR}/shunit2_helper.sh"

# Relax unset variable checking for sourcing (the script uses arrays that
# trigger errors under set -u in some bash versions)
set +u

# Source the script under test (it won't run main because of the BASH_SOURCE guard)
# Unset readonly SCRIPTDIR from the target script by sourcing in a way that avoids conflict
. "${TARGET_SCRIPTDIR}"/stx-iso-utils.sh
SCRIPTDIR=$(readlink -m "$(dirname "$0")")
source "${TARGET_SCRIPTDIR}"/gen-bootloader-iso.sh 2>/dev/null || true

set -u

BUILDDIR_TEST=

# Executed at start of all tests
oneTimeSetUp() {
    th_info oneTimeSetUp
    BUILDDIR_TEST=$(mktemp -d /tmp/gen-bootloader-iso-test.XXXXXX)
}

oneTimeTearDown() {
    th_info oneTimeTearDown
    if [ -n "${BUILDDIR_TEST}" ] && [ -d "${BUILDDIR_TEST}" ]; then
        rm -rf "${BUILDDIR_TEST}"
    fi
}

setUp() {
    # Reset globals before each test
    ADDON=
    BASE_URL=
    BOOT_ARGS_COMMON=
    BOOT_ARGS_SPECIFIC=
    BOOT_GATEWAY=
    BOOT_HOSTNAME=
    BOOT_INTERFACE=
    BOOT_IP=
    BOOT_NETMASK=
    DEFAULT_GRUB_ENTRY=
    DEFAULT_SYSLINUX_ENTRY=
    DELETE="no"
    GRUB_TIMEOUT=-1
    INCLUDE_PATHS=()
    INITRD_FILE=
    INPUT_ISO=
    INSTALL_TYPE=
    NODE_ID=
    OUTPUT_ISO=
    RELEASE=
    TIMEOUT=100
    PARAMS=()
    KICKSTART_URI="${DEFAULT_KICKSTART_URI}"
}

tearDown() {
    :
}

#
# Tests for parse_arguments
#

test_parse_arguments_basic() {
    th_info "Running test_parse_arguments_basic"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 0

    assertEquals "INPUT_ISO" "/tmp/test.iso" "${INPUT_ISO}"
    assertEquals "WWW_ROOT_DIR" "/tmp/www" "${WWW_ROOT_DIR}"
    assertEquals "BASE_URL" "http://example.com" "${BASE_URL}"
    assertEquals "NODE_ID" "subcloud1" "${NODE_ID}"
    assertEquals "BOOT_INTERFACE" "eth0" "${BOOT_INTERFACE}"
    assertEquals "BOOT_IP" "10.10.10.2" "${BOOT_IP}"
    assertEquals "INSTALL_TYPE" "0" "${INSTALL_TYPE}"
    assertEquals "DEFAULT_SYSLINUX_ENTRY" "0" "${DEFAULT_SYSLINUX_ENTRY}"
    assertEquals "DEFAULT_GRUB_ENTRY" "serial" "${DEFAULT_GRUB_ENTRY}"
}

test_parse_arguments_graphical_console() {
    th_info "Running test_parse_arguments_graphical_console"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 1

    assertEquals "INSTALL_TYPE" "1" "${INSTALL_TYPE}"
    assertEquals "DEFAULT_SYSLINUX_ENTRY" "1" "${DEFAULT_SYSLINUX_ENTRY}"
    assertEquals "DEFAULT_GRUB_ENTRY" "graphical" "${DEFAULT_GRUB_ENTRY}"
}

test_parse_arguments_aio_serial() {
    th_info "Running test_parse_arguments_aio_serial"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 2

    assertEquals "INSTALL_TYPE" "2" "${INSTALL_TYPE}"
    assertEquals "DEFAULT_SYSLINUX_ENTRY" "0" "${DEFAULT_SYSLINUX_ENTRY}"
    assertEquals "DEFAULT_GRUB_ENTRY" "serial" "${DEFAULT_GRUB_ENTRY}"
    assertContains "BOOT_ARGS_SPECIFIC should contain worker trait" \
        "${BOOT_ARGS_SPECIFIC}" "controller,worker"
}

test_parse_arguments_aio_graphical() {
    th_info "Running test_parse_arguments_aio_graphical"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 3

    assertEquals "INSTALL_TYPE" "3" "${INSTALL_TYPE}"
    assertEquals "DEFAULT_SYSLINUX_ENTRY" "1" "${DEFAULT_SYSLINUX_ENTRY}"
    assertEquals "DEFAULT_GRUB_ENTRY" "graphical" "${DEFAULT_GRUB_ENTRY}"
    assertContains "BOOT_ARGS_SPECIFIC should contain worker trait" \
        "${BOOT_ARGS_SPECIFIC}" "controller,worker"
}

test_parse_arguments_optional_params() {
    th_info "Running test_parse_arguments_optional_params"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --boot-gateway 10.10.10.1 \
        --boot-netmask 255.255.255.0 \
        --boot-hostname myhost \
        --default-boot 0 \
        --release 24.09

    assertEquals "BOOT_GATEWAY" "10.10.10.1" "${BOOT_GATEWAY}"
    assertEquals "BOOT_NETMASK" "255.255.255.0" "${BOOT_NETMASK}"
    assertEquals "BOOT_HOSTNAME" "myhost" "${BOOT_HOSTNAME}"
    assertEquals "RELEASE" "24.09" "${RELEASE}"
}

test_parse_arguments_timeout() {
    th_info "Running test_parse_arguments_timeout"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 0 \
        --timeout 30

    assertEquals "TIMEOUT" "300" "${TIMEOUT}"
    assertEquals "GRUB_TIMEOUT" "30" "${GRUB_TIMEOUT}"
}

test_parse_arguments_timeout_zero() {
    th_info "Running test_parse_arguments_timeout_zero"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 0 \
        --timeout 0

    assertEquals "GRUB_TIMEOUT" "0.001" "${GRUB_TIMEOUT}"
}

test_parse_arguments_params() {
    th_info "Running test_parse_arguments_params"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 0 \
        --param rootfs_device=nvme0n1 \
        --param boot_device=nvme0n1

    assertEquals "PARAMS count" "2" "${#PARAMS[@]}"
    assertEquals "PARAMS[0]" "rootfs_device=nvme0n1" "${PARAMS[0]}"
    assertEquals "PARAMS[1]" "boot_device=nvme0n1" "${PARAMS[1]}"
}

test_parse_arguments_delete() {
    th_info "Running test_parse_arguments_delete"
    parse_arguments --www-root /tmp/www --id subcloud1 --delete

    assertEquals "DELETE" "yes" "${DELETE}"
    assertEquals "NODE_ID" "subcloud1" "${NODE_ID}"
}

test_parse_arguments_kickstart_uri() {
    th_info "Running test_parse_arguments_kickstart_uri"
    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 0 \
        --kickstart-uri "partition://platform_backup:backups/25.09/miniboot.cfg"

    assertEquals "KICKSTART_URI" \
        "partition://platform_backup:backups/25.09/miniboot.cfg" "${KICKSTART_URI}"
}

test_parse_arguments_include_path() {
    th_info "Running test_parse_arguments_include_path"
    local testfile="${BUILDDIR_TEST}/include_test_file"
    touch "${testfile}"

    parse_arguments --input /tmp/test.iso \
        --www-root /tmp/www \
        --base-url http://example.com \
        --id subcloud1 \
        --boot-interface eth0 \
        --boot-ip 10.10.10.2 \
        --default-boot 0 \
        --include-path "${testfile}"

    assertEquals "INCLUDE_PATHS count" "1" "${#INCLUDE_PATHS[@]}"
    assertEquals "INCLUDE_PATHS[0]" "${testfile}" "${INCLUDE_PATHS[0]}"
}

#
# Tests for validate_arguments
#

test_validate_arguments_install_type_4_release_22_12() {
    th_info "Running test_validate_arguments_install_type_4_release_22_12"
    INSTALL_TYPE=4
    RELEASE='22.12'
    # Should not exit
    validate_arguments
    assertEquals "validate_arguments should pass" 0 $?
}

test_validate_arguments_install_type_4_invalid_release() {
    th_info "Running test_validate_arguments_install_type_4_invalid_release"
    INSTALL_TYPE=4
    RELEASE='24.09'
    # Should exit with error
    (validate_arguments) 2>/dev/null
    assertNotEquals "validate_arguments should fail" 0 $?
}

test_validate_arguments_install_type_5_invalid_release() {
    th_info "Running test_validate_arguments_install_type_5_invalid_release"
    INSTALL_TYPE=5
    RELEASE='24.09'
    (validate_arguments) 2>/dev/null
    assertNotEquals "validate_arguments should fail" 0 $?
}

test_validate_arguments_install_type_0_any_release() {
    th_info "Running test_validate_arguments_install_type_0_any_release"
    INSTALL_TYPE=0
    RELEASE='24.09'
    validate_arguments
    assertEquals "validate_arguments should pass for type 0" 0 $?
}

#
# Tests for handle_delete
#

test_handle_delete_removes_node_dir() {
    th_info "Running test_handle_delete_removes_node_dir"
    local test_www="${BUILDDIR_TEST}/www_delete_test"
    NODE_DIR_BASE="${test_www}/nodes"
    NODE_DIR="${NODE_DIR_BASE}/testnode"
    mkdir -p "${NODE_DIR}"
    touch "${NODE_DIR}/bootimage.iso"

    handle_delete

    assertFalse "NODE_DIR should be removed" "[ -d '${NODE_DIR}' ]"
}

test_handle_delete_removes_base_if_empty() {
    th_info "Running test_handle_delete_removes_base_if_empty"
    local test_www="${BUILDDIR_TEST}/www_delete_empty"
    NODE_DIR_BASE="${test_www}/nodes"
    NODE_DIR="${NODE_DIR_BASE}/testnode"
    mkdir -p "${NODE_DIR}"

    handle_delete

    assertFalse "NODE_DIR_BASE should be removed when empty" "[ -d '${NODE_DIR_BASE}' ]"
}

test_handle_delete_keeps_base_if_other_nodes() {
    th_info "Running test_handle_delete_keeps_base_if_other_nodes"
    local test_www="${BUILDDIR_TEST}/www_delete_keep"
    NODE_DIR_BASE="${test_www}/nodes"
    NODE_DIR="${NODE_DIR_BASE}/testnode"
    mkdir -p "${NODE_DIR}"
    mkdir -p "${NODE_DIR_BASE}/othernode"

    handle_delete

    assertFalse "NODE_DIR should be removed" "[ -d '${NODE_DIR}' ]"
    assertTrue "NODE_DIR_BASE should remain" "[ -d '${NODE_DIR_BASE}' ]"
}

#
# Tests for generate_boot_cfg
#

test_generate_boot_cfg() {
    set +u
    th_info "Running test_generate_boot_cfg"
    local isodir="${BUILDDIR_TEST}/isodir_cfg"
    mkdir -p "${isodir}/isolinux"
    mkdir -p "${isodir}/EFI/BOOT"

    # Set up EFI_MOUNT to a temp dir
    EFI_MOUNT="${BUILDDIR_TEST}/efi_mount_cfg"
    mkdir -p "${EFI_MOUNT}/EFI/BOOT"

    # Set up required globals
    NODE_ID="subcloud-test"
    BOOT_IP="10.10.10.5"
    BOOT_GATEWAY="10.10.10.1"
    BOOT_NETMASK="255.255.255.0"
    BOOT_HOSTNAME="testhost"
    BOOT_INTERFACE="eth0"
    BASE_URL="http://192.168.1.1:8080"
    INSTALL_TYPE=0
    DEFAULT_SYSLINUX_ENTRY=0
    DEFAULT_GRUB_ENTRY=serial
    BOOT_ARGS_SPECIFIC="traits=controller defaultkernel=vmlinuz-*[!t]-amd64"
    TIMEOUT=100
    GRUB_TIMEOUT=-1
    PARAMS=()
    INCLUDE_PATHS=()
    VERBOSE=
    KICKSTART_URI="${DEFAULT_KICKSTART_URI}"

    # Create a fake ostree_repo config
    WWW_ROOT_DIR="${BUILDDIR_TEST}/www_cfg"
    mkdir -p "${WWW_ROOT_DIR}/ostree_repo"
    echo "gpg-verify=true" > "${WWW_ROOT_DIR}/ostree_repo/config"

    generate_boot_cfg "${isodir}"

    # Validate isolinux.cfg
    local syslinux_cfg="${isodir}/isolinux/isolinux.cfg"
    assertTrue "isolinux.cfg should exist" "[ -f '${syslinux_cfg}' ]"
    grep -q "DEFAULT 0" "${syslinux_cfg}" \
        || fail "Expected DEFAULT 0 in isolinux.cfg"
    grep -q "timeout 100" "${syslinux_cfg}" \
        || fail "Expected timeout 100 in isolinux.cfg"
    grep -q "instboot" "${syslinux_cfg}" \
        || fail "Expected instboot in isolinux.cfg"
    grep -q "10.10.10.5" "${syslinux_cfg}" \
        || fail "Expected boot IP in isolinux.cfg"
    grep -q "traits=controller" "${syslinux_cfg}" \
        || fail "Expected traits in isolinux.cfg"

    # Validate grub.cfg
    local grub_cfg="${isodir}/EFI/BOOT/grub.cfg"
    assertTrue "grub.cfg should exist" "[ -f '${grub_cfg}' ]"
    grep -q "default=serial" "${grub_cfg}" \
        || fail "Expected default=serial in grub.cfg"
    grep -q "timeout=-1" "${grub_cfg}" \
        || fail "Expected timeout=-1 in grub.cfg"
    grep -q "${NODE_ID}" "${grub_cfg}" \
        || fail "Expected NODE_ID in grub.cfg"
    grep -q "insturl=${BASE_URL}/ostree_repo" "${grub_cfg}" \
        || fail "Expected insturl in grub.cfg"
    set -u
}

test_generate_boot_cfg_with_extra_boot_params() {
    set +u
    th_info "Running test_generate_boot_cfg_with_extra_boot_params"
    local isodir="${BUILDDIR_TEST}/isodir_extra"
    mkdir -p "${isodir}/isolinux"
    mkdir -p "${isodir}/EFI/BOOT"

    EFI_MOUNT="${BUILDDIR_TEST}/efi_mount_extra"
    mkdir -p "${EFI_MOUNT}/EFI/BOOT"

    NODE_ID="subcloud-extra"
    BOOT_IP="10.10.10.5"
    BOOT_GATEWAY="10.10.10.1"
    BOOT_NETMASK="255.255.255.0"
    BOOT_HOSTNAME="testhost"
    BOOT_INTERFACE="eth0"
    BASE_URL="http://192.168.1.1:8080"
    INSTALL_TYPE=2
    DEFAULT_SYSLINUX_ENTRY=0
    DEFAULT_GRUB_ENTRY=serial
    BOOT_ARGS_SPECIFIC="traits=controller,worker defaultkernel=vmlinuz-*[!t]-amd64"
    TIMEOUT=100
    GRUB_TIMEOUT=-1
    PARAMS=("boot_device=/dev/sdb" "extra_boot_params=hugepagesz=1G hugepages=4 console=ttyS0,115200 noquiet")
    INCLUDE_PATHS=()
    VERBOSE=
    KICKSTART_URI="${DEFAULT_KICKSTART_URI}"

    WWW_ROOT_DIR="${BUILDDIR_TEST}/www_extra"
    mkdir -p "${WWW_ROOT_DIR}/ostree_repo"
    echo "gpg-verify=true" > "${WWW_ROOT_DIR}/ostree_repo/config"

    generate_boot_cfg "${isodir}"

    local syslinux_cfg="${isodir}/isolinux/isolinux.cfg"
    # boot_device should be translated to instdev
    grep -q "instdev=/dev/sdb" "${syslinux_cfg}" \
        || fail "Expected instdev=/dev/sdb in isolinux.cfg"
    # extra_boot_params value should appear directly in boot args (space-separated params preserved)
    grep -q "hugepagesz=1G hugepages=4 console=ttyS0,115200 noquiet" "${syslinux_cfg}" \
        || fail "Expected extra_boot_params content in isolinux.cfg"
    # extra_boot_params= key itself should NOT appear in the boot args
    ! grep -q "extra_boot_params=" "${syslinux_cfg}" \
        || fail "extra_boot_params= key should not appear in isolinux.cfg"

    # Verify grub.cfg as well
    local grub_cfg="${isodir}/EFI/BOOT/grub.cfg"
    grep -q "hugepagesz=1G hugepages=4 console=ttyS0,115200 noquiet" "${grub_cfg}" \
        || fail "Expected extra_boot_params content in grub.cfg"
    ! grep -q "extra_boot_params=" "${grub_cfg}" \
        || fail "extra_boot_params= key should not appear in grub.cfg"
    set -u
}

test_generate_boot_cfg_extra_boot_params_not_in_param_list() {
    set +u
    th_info "Running test_generate_boot_cfg_extra_boot_params_not_in_param_list"
    # Verify that extra_boot_params does not end up in PARAM_LIST alongside other params
    local isodir="${BUILDDIR_TEST}/isodir_paramlist"
    mkdir -p "${isodir}/isolinux"
    mkdir -p "${isodir}/EFI/BOOT"

    EFI_MOUNT="${BUILDDIR_TEST}/efi_mount_paramlist"
    mkdir -p "${EFI_MOUNT}/EFI/BOOT"

    NODE_ID="subcloud-paramlist"
    BOOT_IP="10.10.10.5"
    BOOT_GATEWAY=""
    BOOT_NETMASK=""
    BOOT_HOSTNAME=""
    BOOT_INTERFACE="eth0"
    BASE_URL="http://192.168.1.1:8080"
    INSTALL_TYPE=0
    DEFAULT_SYSLINUX_ENTRY=0
    DEFAULT_GRUB_ENTRY=serial
    BOOT_ARGS_SPECIFIC="traits=controller defaultkernel=vmlinuz-*[!t]-amd64"
    TIMEOUT=100
    GRUB_TIMEOUT=-1
    PARAMS=("rootfs_device=nvme0n1" "extra_boot_params=console=ttyAMA0,115200" "boot_device=nvme0n1")
    INCLUDE_PATHS=()
    VERBOSE=
    KICKSTART_URI="${DEFAULT_KICKSTART_URI}"

    WWW_ROOT_DIR="${BUILDDIR_TEST}/www_paramlist"
    mkdir -p "${WWW_ROOT_DIR}/ostree_repo"
    echo "gpg-verify=true" > "${WWW_ROOT_DIR}/ostree_repo/config"

    generate_boot_cfg "${isodir}"

    local syslinux_cfg="${isodir}/isolinux/isolinux.cfg"
    # rootfs_device should be in the normal param list
    grep -q "rootfs_device=nvme0n1" "${syslinux_cfg}" \
        || fail "Expected rootfs_device=nvme0n1 in isolinux.cfg"
    # extra_boot_params value injected directly
    grep -q "console=ttyAMA0,115200" "${syslinux_cfg}" \
        || fail "Expected extra_boot_params value in isolinux.cfg"
    # extra_boot_params= key must not appear
    ! grep -q "extra_boot_params=" "${syslinux_cfg}" \
        || fail "extra_boot_params= key should not appear in isolinux.cfg"
    # instdev should reflect boot_device
    grep -q "instdev=nvme0n1" "${syslinux_cfg}" \
        || fail "Expected instdev=nvme0n1 in isolinux.cfg"
    set -u
}

test_generate_boot_cfg_gpg_verify_false() {
    set +u
    th_info "Running test_generate_boot_cfg_gpg_verify_false"
    local isodir="${BUILDDIR_TEST}/isodir_gpg"
    mkdir -p "${isodir}/isolinux"
    mkdir -p "${isodir}/EFI/BOOT"

    EFI_MOUNT="${BUILDDIR_TEST}/efi_mount_gpg"
    mkdir -p "${EFI_MOUNT}/EFI/BOOT"

    NODE_ID="subcloud-gpg"
    BOOT_IP="10.10.10.5"
    BOOT_GATEWAY=""
    BOOT_NETMASK=""
    BOOT_HOSTNAME=""
    BOOT_INTERFACE="eth0"
    BASE_URL="http://192.168.1.1:8080"
    INSTALL_TYPE=0
    DEFAULT_SYSLINUX_ENTRY=0
    DEFAULT_GRUB_ENTRY=serial
    BOOT_ARGS_SPECIFIC="traits=controller defaultkernel=vmlinuz-*[!t]-amd64"
    TIMEOUT=100
    GRUB_TIMEOUT=-1
    PARAMS=()
    INCLUDE_PATHS=()
    VERBOSE=
    KICKSTART_URI="${DEFAULT_KICKSTART_URI}"

    WWW_ROOT_DIR="${BUILDDIR_TEST}/www_gpg"
    mkdir -p "${WWW_ROOT_DIR}/ostree_repo"
    echo "gpg-verify=false" > "${WWW_ROOT_DIR}/ostree_repo/config"

    generate_boot_cfg "${isodir}"

    local syslinux_cfg="${isodir}/isolinux/isolinux.cfg"
    grep -q "instgpg=0" "${syslinux_cfg}" \
        || fail "Expected instgpg=0 when gpg-verify=false"
    set -u
}

test_generate_boot_cfg_include_paths() {
    set +u
    th_info "Running test_generate_boot_cfg_include_paths"
    local isodir="${BUILDDIR_TEST}/isodir_inc"
    mkdir -p "${isodir}/isolinux"
    mkdir -p "${isodir}/EFI/BOOT"

    EFI_MOUNT="${BUILDDIR_TEST}/efi_mount_inc"
    mkdir -p "${EFI_MOUNT}/EFI/BOOT"

    NODE_ID="subcloud-inc"
    BOOT_IP="10.10.10.5"
    BOOT_GATEWAY=""
    BOOT_NETMASK=""
    BOOT_HOSTNAME=""
    BOOT_INTERFACE="eth0"
    BASE_URL="http://192.168.1.1:8080"
    INSTALL_TYPE=0
    DEFAULT_SYSLINUX_ENTRY=0
    DEFAULT_GRUB_ENTRY=serial
    BOOT_ARGS_SPECIFIC="traits=controller defaultkernel=vmlinuz-*[!t]-amd64"
    TIMEOUT=100
    GRUB_TIMEOUT=-1
    PARAMS=()
    INCLUDE_PATHS=("/tmp/file1" "/tmp/file2")
    VERBOSE=
    KICKSTART_URI="${DEFAULT_KICKSTART_URI}"

    WWW_ROOT_DIR="${BUILDDIR_TEST}/www_inc"
    mkdir -p "${WWW_ROOT_DIR}/ostree_repo"
    echo "gpg-verify=true" > "${WWW_ROOT_DIR}/ostree_repo/config"

    generate_boot_cfg "${isodir}"

    local syslinux_cfg="${isodir}/isolinux/isolinux.cfg"
    grep -q "include_paths=file1,file2" "${syslinux_cfg}" \
        || fail "Expected include_paths=file1,file2 in isolinux.cfg"
    set -u
}

#
# Tests for get_os
#

test_get_os() {
    th_info "Running test_get_os"
    # Just verify it returns something without error
    local os
    os=$(get_os)
    assertNotNull "get_os should return a value" "${os}"
}

# shellcheck disable=SC2154
trap 'rc=$?; echo "Caught abnormal signal rc=$rc"; exit $rc' 2 3 15

th_info "Running shunit2"

# Load and run shunit2.
# shellcheck disable=SC2034
[ -n "${ZSH_VERSION:-}" ] && SHUNIT_PARENT=$0
. "${TH_SHUNIT}"
