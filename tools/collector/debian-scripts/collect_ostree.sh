#! /bin/bash
#
# Copyright (c) 2022 Wind River Systems, Inc.
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
    delimiter ${LOGFILE} "ostree log ${OSTREE_REF} --repo=${feed_dir}"
    ostree log ${OSTREE_REF} --repo=${feed_dir} >> ${LOGFILE}  2>>${COLLECT_ERROR_LOG}
done

exit 0
