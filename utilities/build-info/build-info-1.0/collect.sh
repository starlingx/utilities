#!/bin/bash

#
# Copyright (c) 2013-2016 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

#
# Environment:
#
#  JENKINS_BUILD_FILE   - optional; if provided it must exist, otherwise
#                         we will generate build.info with default values
#  MY_REPO              - required
#  MY_WORKSPACE         - required; used to gauge Git rev info etc
#  RELEASE_INFO_FILE    - required; must exist
#  BUILD_DATE           - optional; defaults to current date
#

destFile="build.info"
destH="build_info.h"

# Make sure JENKINS_BUILD_FILE is unset, or refers to an existing file
if [[ -n "$JENKINS_BUILD_FILE" && ! -f "$JENKINS_BUILD_FILE" ]] ; then
    echo "JENKINS_BUILD_FILE: $JENKINS_BUILD_FILE: file not found" >&2
    exit 1
fi

# Validate MY_REPO
if [[ -z "$MY_REPO" ]] ; then
    echo "MY_REPO must be set" >&2
    exit 1
fi
MY_REPO=$(readlink -f "$MY_REPO") || exit 1
if [[ ! -d "$MY_REPO" ]] ; then
    echo "MY_REPO: $MY_REPO: not a directory" >&2
    exit 1
fi


# Validate MY_WORKSPACE
if [[ -z "$MY_WORKSPACE" ]] ; then
    echo "MY_WORKSPACE must be set" >&2
    exit 1
fi
MY_WORKSPACE=$(readlink -f "$MY_WORKSPACE") || exit 1
if [[ ! -d "$MY_REPO" ]] ; then
    echo "MY_WORKSPACE: $MY_WORKSPACE: not a directory" >&2
    exit 1
fi

# Validate RELEASE_INFO_FILE
if [[ -z "$RELEASE_INFO_FILE" ]] ; then
    echo "RELEASE_INFO_FILE must be set" >&2
    exit 1
fi
if [[ ! -f "$RELEASE_INFO_FILE" ]] ; then
    echo "RELEASE_INFO_FILE: not a regular file" >&2
    exit 1
fi

# Always source release-info.inc
source "$RELEASE_INFO_FILE" || exit 1

# Source JENKINS_BUILD_FILE if exists
if [[ -n "$JENKINS_BUILD_FILE" ]] ; then
    cp "$JENKINS_BUILD_FILE" "$destFile"
    source "$JENKINS_BUILD_FILE" || exit 1

# Otherwise generate default build info
else
    # PLATFORM_RELEASE should be set in release-info.inc
    if [ "x${PLATFORM_RELEASE}" == "x" ]; then
        SW_VERSION="Unknown"
    else
        SW_VERSION="${PLATFORM_RELEASE}"
    fi

    BUILD_TARGET="Unknown"
    BUILD_TYPE="Informal"
    BUILD_ID="n/a"
    JOB="n/a"
    if [ "${BUILD_BY}x" == "x" ]; then
        BUILD_BY="$USER"
    fi
    BUILD_NUMBER="n/a"
    BUILD_HOST="$HOSTNAME"
    if [ "${BUILD_DATE}x" == "x" ]; then
        # Older versions of "date" don't like the "+" in front of the format string
        BUILD_DATE=`date "%F %T %z" 2>&1`
        if [ $? -ne 0 ]; then
            BUILD_DATE=`date "+%F %T %z"`
        fi
    fi

    echo "generating $destFile ..." >&2
    echo "SW_VERSION=\"$SW_VERSION\"" > $destFile
    echo "BUILD_TARGET=\"$BUILD_TARGET\"" >> $destFile
    echo "BUILD_TYPE=\"$BUILD_TYPE\""  >> $destFile
    echo "BUILD_ID=\"$BUILD_ID\"" >> $destFile
    echo "" >> $destFile
    echo "JOB=\"$JOB\"" >> $destFile
    echo "BUILD_BY=\"$BUILD_BY\""  >> $destFile
    echo "BUILD_NUMBER=\"$BUILD_NUMBER\"" >> $destFile
    echo "BUILD_HOST=\"$BUILD_HOST\"" >> $destFile
    echo "BUILD_DATE=\"$BUILD_DATE\"" >> $destFile
    echo "" >> $destFile
    echo "BUILD_DIR=\""`bash -c "cd $MY_WORKSPACE; pwd"`"\"" >> $destFile
    echo "WRS_SRC_DIR=\"$MY_REPO\"" >> $destFile
    if [ "${WRS_GIT_BRANCH}x" == "x" ]; then
        echo "WRS_GIT_BRANCH=\""`cd $MY_REPO; git status -s -b | grep '##' | awk ' { printf $2 } '`"\"" >> $destFile
    else
        echo "WRS_GIT_BRANCH=\"$WRS_GIT_BRANCH\"" >> $destFile
    fi

    echo "CGCS_SRC_DIR=\"$MY_REPO/stx\"" >> $destFile
    if [ "${CGCS_GIT_BRANCH}x" == "x" ]; then
        echo "CGCS_GIT_BRANCH=\""`cd $MY_REPO/stx/; git status -s -b | grep '##' | awk ' { printf $2 } '`"\"" >> $destFile
    else
        echo "CGCS_GIT_BRANCH=\"$CGCS_GIT_BRANCH\"" >> $destFile
    fi

fi

echo "generating $destH ..." >&2
echo "#ifndef _BUILD_INFO_H_" > $destH
echo "#define _BUILD_INFO_H_" >> $destH
echo "" >> $destH
echo "#define RELEASE_NAME \"$RELEASE_NAME\"" >> $destH
echo "#define SW_VERSION \"$SW_VERSION\"" >> $destH
echo "" >> $destH
echo "#define BUILD_TARGET \"$BUILD_TARGET\"" >> $destH
echo "#define BUILD_TYPE \"$BUILD_TYPE\""  >> $destH
echo "#define BUILD_ID \"$BUILD_ID\"" >> $destH
echo "" >> $destH
echo "#define JOB \"$JOB\"" >> $destH
echo "#define BUILD_BY \"$BUILD_BY\""  >> $destH
echo "#define BUILD_NUMBER \"$BUILD_NUMBER\"" >> $destH
echo "#define BUILD_HOST \"$BUILD_HOST\"" >> $destH
echo "#define BUILD_DATE \"$BUILD_DATE\"" >> $destH
echo "#endif /* _BUILD_INFO_H_ */" >> $destH
