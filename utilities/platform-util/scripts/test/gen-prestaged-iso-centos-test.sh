#!/bin/bash
# vim:ft=sh:sts=4:sw=4

# This is a shunit2 test file.
# See https://github.com/kward/shunit2
# Run the tests by executing this script.

# shellcheck disable=SC2016
# shellcheck disable=SC1090
# shellcheck disable=SC1091

NAME=gen-prestaged-iso-centos-test

# shellcheck disable=SC2155,SC2034
readonly SCRIPTDIR=$(readlink -m "$(dirname "$0")")
# shellcheck disable=SC2155,SC2034
readonly TARGET_SCRIPTDIR=$(readlink -m "${SCRIPTDIR}/..")

INPUT_DIR="${SCRIPTDIR}"/input/centos
IMAGES_DIR="${INPUT_DIR}/images"
PATCHES_DIR="${INPUT_DIR}/patches"
ISOFILE=${ISOFILE:-$INPUT_DIR/bootimage.iso}
#ISOFILE=/localdisk/designer/kmacleod/dc-libvirt/isofiles/wrcp-22.12-release/starlingx-intel-x86-64-cd.iso
#ISOFILE=/localdisk/designer/kmacleod/dc-libvirt/isofiles/WRCP-21.12-formal-patch/bootimage.iso

# source the script under test
. "${TARGET_SCRIPTDIR}"/stx-iso-utils-centos.sh
. "${SCRIPTDIR}/shunit2_helper.sh"

KEEP_ARTIFACTS=${KEEP_ARTIFACTS:-}
BUILDDIR=${SCRIPTDIR}/output/${NAME}
OUTPUT_ISO=${BUILDDIR}/generated.iso

_create_fake_image() {
    local imagename=$1
    local targetdir=$2
    if hash docker 2>/dev/null; then
        echo "Creating fake image ${imagename} using docker"
        tar cv --files-from /dev/null | docker import - "${imagename}:latest"
        docker save -o "${targetdir}/${imagename}.tar.gz" "${imagename}:latest"
        docker rmi "${imagename}:latest"
    else
        echo "Creating fake empty image ${imagename}"
        touch "${targetdir}/${imagename}.tar.gz"
    fi
}

_create_fake_images() {
    if [ ! -d "${IMAGES_DIR}" ]; then
        echo "Creating fake images"
        mkdir -p "${IMAGES_DIR}" || fail "mkdir failed"
        local image
        for image in image1 image2 image3; do
            _create_fake_image "${image}" "${IMAGES_DIR}"
        done
    fi
}

_fetch_iso_and_patches() {
    # Fetch CentOS ISO and test patches from yow-cgts4-lx
    [ -d "${INPUT_DIR}" ] || mkdir -p "${INPUT_DIR}" || fail "mkdir failed"
    if [ ! -f "${INPUT_DIR}/bootimage.iso" ]; then
        echo "Fetching ISO"
        scp 'yow-cgts4-lx:/localdisk/loadbuild/jenkins/WRCP_21.12_Build/last_build_with_test_patches/export/bootimage.{iso,sig}' "${INPUT_DIR}/"
    fi
    if [ ! -d "${PATCHES_DIR}" ]; then
        echo "Fetching patches"
        mkdir -p "${PATCHES_DIR}" || fail "mkdir failed"
        scp 'yow-cgts4-lx:/localdisk/loadbuild/jenkins/WRCP_21.12_Build/last_build_with_test_patches/test_patches/*{A,B,C}.patch' "${PATCHES_DIR}/"
    fi
}

# Executed at start of all tests
oneTimeSetUp() {
    th_info oneTimeSetUp
    if [ -d "${BUILDDIR}" ]; then
        th_debug "Cleaning ${BUILDDIR}"
        rm -rf "${BUILDDIR}"
    fi
    mkdir -p "${BUILDDIR}" || fail "Failed to create ${BUILDDIR}"
    _create_fake_images
    _fetch_iso_and_patches
}

# Executed at start of each tests
setUp() {
    th_info setUp
}

oneTimeTearDown() {
    th_info oneTimeTearDown
    if [ -z "${KEEP_ARTIFACTS}" ]; then
        if [ -n "${BUILDDIR}" ] && [ -d "${BUILDDIR}" ]; then
            th_debug "Cleaning ${BUILDDIR}"
            rm -rf "${BUILDDIR}"
        fi
    fi
}

# Executed at completion of each tests
tearDown() {
    th_info tearDown
    if [ -n "${MNTDIR}" ] && [ -d "${MNTDIR}" ]; then
        th_info "tearDown: unmounting ${MNTDIR}"
        sudo umount "${MNTDIR}" 2>/dev/null || th_warn "umount failed for ${MNTDIR}"
    fi
    if [ -f "${OUTPUT_ISO}" ]; then
        sudo rm "${OUTPUT_ISO}"
    fi
}

create_ks_addon_file() {
cat <<EOF > "${BUILDDIR}/ks-addon.cfg"
ilog "Executing ks-addon.cfg"
EOF
}

validate_generated_iso() {
    local syslinux_boot=1
    local grub_boot=graphical
    local param=
    local syslinux_timeout=300
    local grub_timeout=30
    local ks_addon=
    while [ $# -gt 0 ] ; do
        case "${1:-""}" in
            --syslinux-boot)
                shift
                syslinux_boot=$1
                ;;
            --grub-boot)
                shift
                grub_boot=$1
                ;;
            --param)
                shift
                param=$1
                ;;
            --syslinux-timeout)
                shift
                syslinux_timeout=$1
                ;;
            --grub-timeout)
                shift
                grub_timeout=$1
                ;;
            --ks-addon)
                shift
                ks_addon=ks-addon.cfg
                ;;
            *)
                echo "Invalid expected value '$1'"
                exit 1
                ;;
        esac
        shift
    done

    # Mount the ISO
    [ -f "${OUTPUT_ISO}" ] || fail "${OUTPUT_ISO} does not exist"
    MNTDIR=${BUILDDIR}/mnt
    [ -d "${MNTDIR}" ] || mkdir "${MNTDIR}" || fail "mkdir failed"
    sudo mount "${OUTPUT_ISO}" "${MNTDIR}" || fail "Failed to mount ${OUTPUT_ISO}"

    # Check that images are included:
    th_info "Image check: validating images are in ISO"
    for image in "${IMAGES_DIR}"/*.tar.gz; do
        [ "$(find "${MNTDIR}"/opt/platform-backup -name "$(basename "${image}")" | wc -l)" -eq 1 ]  \
            || fail "Missing expected image ${image}"
        th_info "Found expected image: ${image}"
    done
    th_info "Image check passed"

    # Check that patches are included:
    th_info "Patch check: validating patches are in ISO"
    for patch in "${PATCHES_DIR}"/*.patch; do
        [ "$(find "${MNTDIR}"/opt/platform-backup -name "$(basename "${patch}")" | wc -l)" -eq 1 ]  \
            || fail "Missing expected patch ${patch}"
        th_info "Found expected patch: ${patch}"
    done
    th_info "Patch check passed"

    local syslinux_cfg=${MNTDIR}/syslinux.cfg
    local grub_cfg=${MNTDIR}/EFI/BOOT/grub.cfg

    if [ -n "${syslinux_boot}" ]; then
        grep -q -i "default ${syslinux_boot}" "${syslinux_cfg}" \
            || fail "Incorrect syslinux boot: ${syslinux_boot} in ${syslinux_cfg}"
    fi
    if [ -n "${syslinux_timeout}" ]; then
        grep -q "timeout ${syslinux_timeout}" "${syslinux_cfg}" \
            || fail "Incorrect syslinux timeout: (expected ${syslinux_timeout}) in ${syslinux_cfg}"
    fi
    if [ -n "${grub_boot}" ]; then
        grep 'default=' "${grub_cfg}" | grep -q "${grub_boot}" \
            || fail "Incorrect grub boot (expected ${grub_boot}) in EFI/BOOT/grub.cfg"
    fi
    if [ -n "${grub_timeout}" ]; then
        grep -q "timeout=${grub_timeout}" "${grub_cfg}" \
            || fail "Incorrect grub timeout: ${grub_timeout} in EFI/BOOT/grub.cfg"
    fi
    if [ -n "${param}" ]; then
        # There should be two boot entries containing param (graphical + serial)
        [ "$(grep -c "${param}" "${syslinux_cfg}")" -eq 2 ] \
            || fail "Incorrect param value (expected ${param}) in ${syslinux_cfg}"
        [ "$(grep -c "${param}" "${grub_cfg}")" -eq 2 ] \
            || fail  "Incorrect param value (expected ${param}) in EFI/BOOT/grub.cfg"
    fi
    if [ -n "${ks_addon}" ]; then
        [ -f "${MNTDIR}/${ks_addon}" ] || fail "Expected ks-addon ${ks_addon} not found"
    fi
}

test_generate_prestaged_iso_1() {
    th_info "Running test_generate_prestaged_iso_1"
    (   # subshell
        cd "${TARGET_SCRIPTDIR}"
        local images=""
        local image
        for image in "${IMAGES_DIR}"/*.tar.gz; do
            images="${images} --image ${image}"
        done
        local patches=""
        local patch
        for patch in "${PATCHES_DIR}"/*.patch; do
            patches="${patches} --patch ${patch}"
        done
        # shellcheck disable=2086
        sudo ./gen-prestaged-iso-centos.sh --input "${ISOFILE}" \
            --output "${OUTPUT_ISO}" \
            ${images} ${patches}
    ) || fail "gen-prestaged-iso-centos.sh failed"

    th_info "Generated ${OUTPUT_ISO}"

    if [ -n "${KEEP_ARTIFACTS}" ]; then
        th_info "Preserving ISO in ${SCRIPTDIR}/generated_centos_1.iso"
        cp "${OUTPUT_ISO}" "${SCRIPTDIR}"/generated_centos_1.iso
    fi

    validate_generated_iso --syslinux-boot 1 --grub-boot graphical \
        --syslinux-timeout 300 --grub-timeout 30
}

test_generate_prestaged_iso_2() {
    th_info "Running test_generate_prestaged_iso_2"
    (   # subshell
        cd "${TARGET_SCRIPTDIR}"
        local images=""
        local image
        for image in "${IMAGES_DIR}"/*.tar.gz; do
            if [ -z "${images}" ]; then
                images="--image ${image}"
            else
                images="${images},${image}"
            fi
        done
        local patches=""
        local patch
        for patch in "${PATCHES_DIR}"/*.patch; do
            if [ -z "${patches}" ]; then
                patches="--patch ${patch}"
            else
                patches="${patches},${patch}"
            fi
        done
        create_ks_addon_file

        # shellcheck disable=2086
        sudo ./gen-prestaged-iso-centos.sh --input "${ISOFILE}" \
            --output "${OUTPUT_ISO}" \
            --addon "${BUILDDIR}/ks-addon.cfg" \
            --default-boot 0 \
            --timeout 90 \
            --force-install \
            --param "param1=1,param2=2" \
            ${images} ${patches}
    ) || fail "gen-prestaged-iso-centos.sh failed"

    th_info "Generated ${OUTPUT_ISO}"

    if [ -n "${KEEP_ARTIFACTS}" ]; then
        th_info "Preserving ISO in ${SCRIPTDIR}/generated_centos_2.iso"
        cp "${OUTPUT_ISO}" "${SCRIPTDIR}"/generated_centos_2.iso
    fi

    validate_generated_iso --syslinux-boot 0 --grub-boot serial \
        --syslinux-timeout 900 --grub-timeout 90 \
        --param "param1=1 param2=2" --ks-addon ks-addon.cfg
}

# shellcheck disable=SC2154
trap 'rc=$?; echo "Caught abnormal signal rc=$rc"; exit $rc' 2 3 15

th_info "Running shunit2"

# Load and run shunit2.
# shellcheck disable=SC2034
[ -n "${ZSH_VERSION:-}" ] && SHUNIT_PARENT=$0
. "${TH_SHUNIT}"
