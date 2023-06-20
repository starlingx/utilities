#!/bin/bash

# -----------------------------------------------------------------------------
# Helper stuff taken from https://github.com/kward/shunit2/blob/master/shunit2_test_helpers

# Note: the last release, 2.1.8 is buggy/not working. Checkout the git repo and use that instead.
SHUNIT_DIR="${SCRIPTDIR:-.}/shunit2"
if [ ! -d "${SHUNIT_DIR}" ]; then
    (   # subprocess
        cd "$SCRIPTDIR"
        git clone "https://github.com/kward/shunit2.git" || { echo "ERROR: failed to clone shunit2"; exit 1; }
    )
fi
# Path to shunit2 library. Can be overridden by setting SHUNIT_INC.
TH_SHUNIT=${SHUNIT_DIR}/shunit2 export TH_SHUNIT

set -e  # Exit immediately if a simple command exits with a non-zero status.
set -u  # Treat unset variables as an error when performing parameter expansion.

# Set shwordsplit for zsh.
[ -n "${ZSH_VERSION:-}" ] && setopt shwordsplit

#
# Constants.
#

# Configure debugging. Set the DEBUG environment variable to any
# non-empty value to enable debug output, or TRACE to enable trace
# output.
TRACE=${TRACE:+'th_trace '}
[ -n "${TRACE}" ] && DEBUG=1
[ -z "${TRACE}" ] && TRACE=':'

DEBUG=${DEBUG:+'th_debug '}
[ -z "${DEBUG}" ] && DEBUG=':'

#
# Functions.
#

# Logging functions.
th_trace() { echo "test:TRACE $*" >&2; }
th_debug() { echo "test:DEBUG $*" >&2; }
th_info()  { echo "test:INFO $*" >&2; }
th_warn()  { echo "test:WARN $*" >&2; }
th_error() { echo "test:ERROR $*" >&2; }
th_fatal() { echo "test:FATAL $*" >&2; }

# Output subtest name.
th_subtest() { echo " $*" >&2; }


#
# Bind in our own non-exiting functions. These overwrite the functions from stx-iso-utils.sh:
#
function elog {
    echo "$(date "+%F %H-%M-%S") Error: $*" >&2
    return 1
}

function check_rc_die {
    local -i rc=$1; shift
    if [ $rc -ne 0 ]; then
        echo "$(date "+%F %H-%M-%S") Error: $*" >&2
        return $rc
    fi
}

