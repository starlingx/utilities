#!/bin/bash

echo "Running all unit tests"

# shellcheck disable=SC2155,SC2034
readonly SCRIPTDIR=$(readlink -m "$(dirname "$0")")
cd "${SCRIPTDIR}" || { echo "cd failed"; exit 1; }

TESTS="./gen-prestaged-iso-test.sh ./gen-prestaged-iso-test.sh"

log_progress() { echo -e "$(tput setaf 2)$*$(tput sgr0)"; }
log_error() { echo -e "$(tput setaf 1)ERROR: $*$(tput sgr0)"; }

declare -i rc
for testscript in ${TESTS}; do
    log_progress "--------------------------------------------------------------------------------"
    log_progress "Executing ${testscript}"
    ${testscript}
    rc=$?
    if [ $rc -ne 0 ]; then
        log_error "failure in ${testscript}, rc=${rc}"
        exit $rc
    fi
done
