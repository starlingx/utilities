#!/bin/bash
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Bash utility to generate a prestage shared directory
#     - Packages directory containing a list of new RPMs to download
#     - File containing a list of unchanged RPMs to copy locally on the target
#     - Packages comps.xml file

source $(dirname $0)/stx-iso-utils.sh

declare LOG_ERROR_TAG="$(basename $0) Error: "
declare LOG_TAG=$(basename $0)

function log_error {
    logger -i -s -t ${LOG_ERROR_TAG} -- "$@"
    exit -1
}

function log {
    logger -i -s -t ${LOG_TAG} -- "$@"
}

declare CURRENT_PACKAGE_LIST_FILE=
declare COMPS_FILE=
declare FEED_DIR=
declare PREVIOUS_PACKAGE_LIST_FILE=
declare RELEASE_ID=
declare RPM_COMMON_LIST=
declare RPM_DIR=
declare RPM_LIST=
declare TEMPDIR=

declare RPM_COMMON_LIST_NAME="common_packages.txt"
declare RPM_PACKAGE_LIST_DIR="/usr/local/share/pkg-list"
declare PRESTAGE_DIR_PREFIX="/opt/platform/deploy"

function usage {
    cat <<ENDUSAGE
Description: Sets up a prestage shared directory that contains the following:
   - Packages directory containing the RPMs to be downloaded
   - File containing a list of unchanged RPMs to copy locally on the target
   - a comps.xml file (usually with a long hexadecimal prefix)

Mandatory parameters for setup:
    --release-id              Specify the release version
    -h                        Print this help page
ENDUSAGE
}

#
# Parse command line arguments
#
LONGOPTS="release-id:"
OPTS=$(getopt -o h --long "${LONGOPTS}" --name "${0}" -- "$@")

if [ $? -ne 0 ]; then
    usage
    exit 1
fi

while :; do
    case "$1" in
        --release-id)
            RELEASE_ID=$2
            shift 2
            ;;
        -h)
            usage
            shift
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

function cleanup {

    if [ -d "${TEMPDIR}" ]; then
        rm -rf ${TEMPDIR}
    fi
}

function create_common_package_list {

    local TEMP_COMMON_PKGS_WITH_CHKSUM=common_pkgs_with_chksum.txt

    if [ ! -f "${CURRENT_PACKAGE_LIST_FILE}" ]; then
        log_error "Package list for current release (${CURRENT_PACKAGE_LIST_FILE}) does not exist. Abort"
    fi

    if [ ! -f "${PREVIOUS_PACKAGE_LIST_FILE}" ]; then
        log_error "Package list for previous release (${PREVIOUS_PACKAGE_LIST_FILE}) does not exist. Abort"
    fi

    # generate the list unchanged packages between previous and current releases.
    RPM_COMMON_LIST=${PRESTAGE_SHARED_DIR}/${RPM_COMMON_LIST_NAME}

    comm -12 ${CURRENT_PACKAGE_LIST_FILE} ${PREVIOUS_PACKAGE_LIST_FILE} > ${TEMPDIR}/${TEMP_COMMON_PKGS_WITH_CHKSUM}

    cat ${TEMPDIR}/${TEMP_COMMON_PKGS_WITH_CHKSUM} | awk '{print $1}' > ${RPM_COMMON_LIST}

    if [ $? -ne 0 ]; then
        log_error "Unable to create the common list of packages. Abort"
    fi
}

function populate_prestage_shared_dir {
    # create the exclude list
    EXCLUDE_LIST=${TEMPDIR}/exclude_list.txt
    cat ${RPM_COMMON_LIST} > ${EXCLUDE_LIST}

    # add the exclude filter to the files in the exclude list
    sed -i 's/^/- /g' ${EXCLUDE_LIST}

    # copy the rpms to the Packages directory
    rsync -a --filter="merge ${EXCLUDE_LIST}" ${RPM_DIR} ${PRESTAGE_SHARED_DIR}/

    if [ $? -ne 0 ]; then
        log_error "Unable to copy packages to ${PRESTAGE_SHARED_DIR}"
    fi

    # copy over the comps.xml file
    cp ${COMPS_FILE} ${PRESTAGE_SHARED_DIR}
    if [ $? -ne 0 ]; then
        log_error "Unable to copy ${COMPS_FILE} to ${PRESTAGE_SHARED_DIR}"
    fi
}

# main script goes here.

check_required_param "--release-id" "${RELEASE_ID}"


trap cleanup EXIT
trap cleanup 2

PRESTAGE_SHARED_DIR="${PRESTAGE_DIR_PREFIX}/${RELEASE_ID}/prestage/shared"

if [ ! -d ${PRESTAGE_SHARED_DIR} ]; then
    log_error "${PRESTAGE_SHARED_DIR} does not exist. Abort"
fi

if [ -f "${PRESTAGE_SHARED_DIR}/.prestage_preparation_completed" ]; then
    log "The prestage shared content has already been created."
    exit 0
fi

FEED_DIR="/var/www/pages/feed/rel-${RELEASE_ID}"
COMPS_FILE="${FEED_DIR}/repodata/*comps.xml"

RPM_DIR="${FEED_DIR}/Packages"

CURRENT_PACKAGE_LIST_FILE=$(ls ${RPM_PACKAGE_LIST_DIR}/*packages_list.txt)
PREVIOUS_PACKAGE_LIST_FILE=$(ls ${PRESTAGE_SHARED_DIR}/*packages_list.txt)

CURRENT_PACKAGE_LIST_FILE_COUNT=$(echo ${CURRENT_PACKAGE_LIST_FILE} | wc -l)
if [ ${CURRENT_PACKAGE_LIST_FILE_COUNT} -ne 1 ]; then
    logger_error "No Unique packages list found at ${RPM_PACKAGE_LIST_DIR}"
fi

if [ ! -s ${CURRENT_PACKAGE_LIST_FILE} ]; then
    log_error "${CURRENT_PACKAGE_LIST_FILE} is empty. Abort"
fi

PREVIOUS_PACKAGE_LIST_FILE_COUNT=$(echo ${PREVIOUS_PACKAGE_LIST_FILE} | wc -l)
if [ ${PREVIOUS_PACKAGE_LIST_FILE_COUNT} -ne 1 ]; then
    logger_error "No Unique packages list found at ${PRESTAGE_SHARED_DIR}"
fi

if [ ! -s ${PREVIOUS_PACKAGE_LIST_FILE} ]; then
    logger_error "${PREVIOUS_PACKAGE_LIST_FILE} is empty. Abort"
fi

TEMPDIR=$(mktemp -d -p /scratch package_list_dir_XXXXXX)
if [ $? -ne 0 ]; then
    log_error "Unable to create temporary directory in /scratch"
fi

# create the download list.
declare download_rpm_list=()
declare common_rpm_list=()

ls ${RPM_DIR} > ${TEMPDIR}/package_list.txt
RPM_LIST=${TEMPDIR}/package_list.txt

if [ ! -f "${RPM_LIST}" ]; then
    log_error "${RPM_LIST} not created. Abort"
fi

# create the common package list
create_common_package_list
log "Created the common package list"

# copy the required items to the prestage shared directory
populate_prestage_shared_dir
log "Prestage shared directory populated"

touch "${PRESTAGE_SHARED_DIR}/.prestage_preparation_completed"

exit 0
