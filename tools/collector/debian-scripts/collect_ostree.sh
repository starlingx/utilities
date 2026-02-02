#! /bin/bash
#
# Copyright (c) 2022,2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="ostree"
LOGFILE="${extradir}/${SERVICE}.info"

SYSROOT_REPO="/sysroot/ostree/repo"
FEED_OSTREE_BASE_DIR="/var/www/pages/feed"
OSTREE_REF="starlingx"


# Get the first two commit hashes (if they exist)
mapfile -t HASHES < <(ostree log "${OSTREE_REF}" \
    | awk '/^commit/{print $2}' \
    | head -n 2)

LATEST_HASH=${HASHES[0]:-}
PREVIOUS_HASH=${HASHES[1]:-}

if [[ -z "$LATEST_HASH" ]]; then
    echo "Error: No commits found for ref: ${OSTREE_REF}" >&2
fi

if [[ -z "$PREVIOUS_HASH" ]]; then
    echo "Warning: Only one commit found for ref: ${OSTREE_REF}."
    echo "LATEST_HASH=${LATEST_HASH}"
    echo "PREVIOUS_HASH=<none>"
fi

echo "LATEST_HASH=${LATEST_HASH}"
echo "PREVIOUS_HASH=${PREVIOUS_HASH}"

echo    "${hostname}: OSTREE Info .......: ${LOGFILE}"
###############################################################################
# OSTREE Info:
###############################################################################


###############################################################################
# ostree admin status (deployment)
# -v outputs additional data to stderr
###############################################################################
delimiter ${LOGFILE} "ostree admin status -v"
ostree admin status -v >> ${LOGFILE}  2>&1

###############################################################################
# ostree logs for the sysroot and patch feeds
###############################################################################
delimiter ${LOGFILE} "ostree log ${OSTREE_REF} --repo=${SYSROOT_REPO}"
ostree log ${OSTREE_REF} --repo=${SYSROOT_REPO} >> ${LOGFILE}  2>>${COLLECT_ERROR_LOG}

for feed_dir in ${FEED_OSTREE_BASE_DIR}/*/ostree_repo
do
    sleep ${COLLECT_RUNCMD_DELAY}
    delimiter ${LOGFILE} "ostree log ${OSTREE_REF} --repo=${feed_dir}"
    ostree log ${OSTREE_REF} --repo=${feed_dir} >> ${LOGFILE}  2>>${COLLECT_ERROR_LOG}
done

###############################################################################
# ostree repo summary for the feed ostrees
###############################################################################

for feed_dir in ${FEED_OSTREE_BASE_DIR}/*/ostree_repo
do
    sleep ${COLLECT_RUNCMD_DELAY}
    delimiter ${LOGFILE} "ostree summary -v --repo=${feed_dir}"
    ostree summary -v --repo=${feed_dir} >> ${LOGFILE}  2>>${COLLECT_ERROR_LOG}
done

###############################################################################
# ostree repo config file
###############################################################################
delimiter ${LOGFILE} "cat ${SYSROOT_REPO}/config"
cat ${SYSROOT_REPO}/config >> ${LOGFILE}

for feed_dir in ${FEED_OSTREE_BASE_DIR}/*/ostree_repo
do
    delimiter ${LOGFILE} "cat ${feed_dir}/config"
    cat ${feed_dir}/config >> ${LOGFILE}
done

###############################################################################
# ostree diff between the last two commits
###############################################################################
delimiter ${LOGFILE} "ostree diff ${PREVIOUS_HASH} ${LATEST_HASH}"
ostree diff ${PREVIOUS_HASH} ${LATEST_HASH} >> ${LOGFILE} 2>>${COLLECT_ERROR_LOG}

###############################################################################
# content of /sysroot/ostree
###############################################################################
SYSROOT_REPO_PARENT=$(dirname ${SYSROOT_REPO})
delimiter ${LOGFILE} "ls -l ${SYSROOT_REPO_PARENT}"

ls -l ${SYSROOT_REPO_PARENT} >> ${LOGFILE}

exit 0
