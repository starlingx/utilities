#!/bin/bash
# vim: filetype=sh shiftwidth=4 softtabstop=4 expandtab
#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# IPMI serial console capture script.
# Captures the serial console output via underlying 'ipmitool' tool.
# Also acts as an interactive ipmitool wrapper, capturing all console input/output.
#
set -o nounset;  # Do not allow use of undefined vars. Use ${VAR:-} to use an undefined VAR. Same as 'set -u'
set -o pipefail; # Catch the error in case a piped command fails
set +o posix     # Ensure posix mode is off. Required for process substitution
# set -o xtrace;   # Turn on traces, useful while debugging (short form: on: 'set -x' off: 'set +x')

################################################################################
# Helpers

# shellcheck disable=SC2155
readonly SCRIPTNAME=$(basename "$0")
# shellcheck disable=SC2155,SC2034
readonly SCRIPTDIR=$(readlink -m "$(dirname "$0")")

BMC_USER=${BMC_USER:-}
BMC_ADDRESS=${BMC_ADDRESS:-}
BMC_CIPHERSUITE=${BMC_CIPHERSUITE:-}
BMC_PASSWORD=${BMC_PASSWORD:-}

LOG_FILE=${LOG_FILE:-$(pwd)/${SCRIPTNAME%.*}-$(date '+%Y%m%d-%H%M').log}

# IPMITOOL_OPTS: Insert custom ipmitool options. By default we override the escape character
# The default escape is '~', but that conflicts with the SSH escape character
# Examples:  IPMITOOL_OPTS="-e @ -v"
IPMITOOL_OPTS=${IPMITOOL_OPTS:-"-e @"}

export SOL_ACTIVE=false

DEBUG=

help() {
cat<<EOF
Wrapper script to capture the output of 'ipmitool' in a log file.

This script starts up ipmitool for the given BMC session parameters, capturing all output into a log file.

Once connected, you can interact with the session normally.

To stop the capture you either exit the ipmitool session normally (via the
hotkey: '<Enter>~.'), or you can invoke the script again using the --kill
option to cleanly shut everything down.

There are two intended use-cases for this script:
1. Automatically capturing the serial console output during install via ipmitool
   In this case, the --redirect flag is provided, which simply redirects all output
   to the given log file. The console is not meant to be interactive in this case
2. Provide an interactive wrapper around ipmitool which captures all input and output
   into the provided log file.

Note on log file: The log file is captured including raw control characters. It
is best viewed using 'less' with the '-R/--RAW-CONTROL-CHARS' option.

USAGE:
  $SCRIPTNAME [ [-H <bmc-address] [-U <bmc-user>] [ -P <bmc-password> ] || --rvmc-config <rvmc-config.yaml> ] [--force-deactivate]

ARGUMENTS:
  IPMI connection arguments: You will be prompted for required parameters.
  You can also provide any of these as environment variables if preferred.
    Required:
      -H|--host <bmc-address>     : BMC host address [env: BMC_ADDRESS]
      -U|--user <bmc-user>        : BMC user         [env: BMC_USER]
      -P|--password <bmc-address> : BMC password     [env: BMC_PASSWORD]
    Optional:
      -C|--ciphersuite <bmc-ciphersuite>: BMC ciphersuite  [env: BMC_CIPHERSUITE]
  OR
  --rvmc-config <rvmc-config.yaml> : A yaml file specifying the above parameters, in form:
      bmc_address: <ip address>
      bmc_username: <username>
      bmc_password: <base64-encoded password>
      bmc_ciphersuite: <ciphersuite number>

  -l|--log <file path> : Path to the console capture log file (directory must exist)
                         Default: ./${SCRIPTNAME%.*}-YYYY-MM-DD-HHMM.log
  -k|--kill : Stop the capture, cleanup the ipmitool session for this BMC address
  -f|--force-deactivate : Issue a 'sol deactivate' command before connecting
  -r|--redirect : Redirect all ouput to file (do not show on local console)
                  This option is only useful for automated/background capture.

  -h|--help: print this help

EXAMPLES:

Capture:
  $SCRIPTNAME -H 2620:10a:a001:df0::2 -U sysadmin -P sysadmin
  $SCRIPTNAME  # you will be prompted for BMC details

  # You can provide any of BMC_ADDRESS, BMC_USER, BMC_PASSWORD via environment variables:
  export BMC_PASSWORD=SecretPassword
  $SCRIPTNAME -H 2620:10a:a001:df0::2 -U sysadmin

  # Override log file
  $SCRIPTNAME -l ./subcloud1-console-\$(date '+%Y%m%d-%H%M').log

Shutdown:
  # Inside the ipmitool session:  <Enter>~.

  # Or force sol deactivate and kill ipmitool for this configuration:
  $SCRIPTNAME -H 2620:10a:a001:df0::2 -U sysadmin -P sysadmin --kill
EOF
exit 1
}

# Logging: these all log to stderr
get_logdate() { date '+%Y-%m-%d %H:%M:%S'; }
die() { >&2 colorecho red "$(get_logdate) FATAL: $*"; exit 1; }
die_with_rc() { local rc=$1; shift; >&2 colorecho red "$(get_logdate) FATAL: $*, rc=$rc"; exit "$rc"; }
check_rc_die() { local rc=$1; shift; [ "$rc" != "0" ] && die_with_rc "$rc" "$@"; return 0; }
check_rc_err() { local rc=$1; shift; [ "$rc" != "0" ] && log_error "$*, rc=$rc"; return 0; }
log_error() { >&2 colorecho red "$(get_logdate) ERROR: $*"; }
log_warn() { >&2 colorecho orange "$(get_logdate) WARN: $*"; }
log_info() { >&2 echo "$(get_logdate) $*"; }
log_debug() { if [ -n "$DEBUG" ]; then >&2 echo "$(get_logdate) DEBUG: $*"; fi; }
log_progress() { >&2 colorecho green "$(get_logdate) $*"; }

_init_log() {
    LOG_FILE="${LOG_FILE:-$(pwd)/${SCRIPTNAME%.*}.log}"
    log_debug "Logging output to $LOG_FILE"
}

redirect_output_to_file() {
    # output to file only:
    _init_log
    if [ -f "${LOG_FILE}" ]; then
        # append
        exec &>> "${LOG_FILE}"
    else
        exec &> "${LOG_FILE}"
    fi
}

tee_output_to_file() {
    # output to console and file:
    _init_log
    exec &> >(exec tee --append "${LOG_FILE}")
}

colorecho() {  # usage: colorecho <colour> <text> or colorecho -n <colour> <text>
    local echo_arg=
    if [ "$1" = "-n" ]; then
        echo_arg="-n"; shift;
    fi
    local colour="$1"; shift
    case "${colour}" in
        red) echo ${echo_arg} -e "$(tput setaf 1)$*$(tput sgr0)"; ;;
        green) echo ${echo_arg} -e "$(tput setaf 2)$*$(tput sgr0)"; ;;
        green-bold) echo ${echo_arg} -e "$(tput setaf 2; tput bold)$*$(tput sgr0)"; ;;
        yellow) echo ${echo_arg} -e "$(tput setaf 3; tput bold)$*$(tput sgr0)"; ;;
        orange) echo ${echo_arg} -e "$(tput setaf 3)$*$(tput sgr0)"; ;;
        blue) echo ${echo_arg} -e "$(tput setaf 4)$*$(tput sgr0)"; ;;
        purple) echo ${echo_arg} -e "$(tput setaf 5)$*$(tput sgr0)"; ;;
        cyan) echo ${echo_arg} -e "$(tput setaf 6)$*$(tput sgr0)"; ;;
        bold) echo ${echo_arg} -e "$(tput bold)$*$(tput sgr0)"; ;;
        normal|*) echo ${echo_arg} -e "$*"; ;;
    esac
}


################################################################################
# Script Functions

ipmitool_deactivate() {
    # Forcefully deactivate via sol deactivate
    # Use -E to supply password via IPMI_PASSWORD (security)
    export IPMI_PASSWORD=${BMC_PASSWORD}
    log_info "Disconnecting: ipmitool  ${CIPHERSUITE_OPTS} -I lanplus -H ${BMC_ADDRESS} -U ${BMC_USER} -E sol deactivate"
    # shellcheck disable=SC2086
    ipmitool ${CIPHERSUITE_OPTS} -I lanplus -H "${BMC_ADDRESS}" -U "${BMC_USER}" -E sol deactivate
    rc=$?
    log_info "Exit code from sol deactivate: ${rc}"
    export SOL_ACTIVE=false
}

ipmitool_activate() {
    # Establish remote console access via ipmi sol
    # Use -E to supply password via IPMI_PASSWORD
    export IPMI_PASSWORD=${BMC_PASSWORD}
    export SOL_ACTIVE=true
    log_info "Connecting: ipmitool ${CIPHERSUITE_OPTS} -I lanplus ${IPMITOOL_OPTS} -H ${BMC_ADDRESS} -U ${BMC_USER} -E sol activate"
    # shellcheck disable=SC2086
    ipmitool  ${CIPHERSUITE_OPTS} -I lanplus ${IPMITOOL_OPTS} -H "${BMC_ADDRESS}" -U "${BMC_USER}" -E sol activate
    local -i rc=$?
    export SOL_ACTIVE=false
    # We see exit code of 143 when killed
    if [ ${rc} -eq 0 ] || [ ${rc} -eq 143 ]; then
        log_progress "ipmitool sol activate normal exit"
    else
        log_error "ipmitool sol activate abnormal exit [rc: ${rc}]"
        exit ${rc}
    fi
}

is_ipmitool_running() {
    local pid
    pid=$(pgrep -a ipmitool | awk '/'"${BMC_ADDRESS}"'/ { print $1; }')
    if [ -n "${pid}" ]; then
        return 0
    fi
    return 1
}

get_ipmitool_escape_char() {
    local escape_char='~'
    case "${IPMITOOL_OPTS:-}" in
        *"-e "*)
            escape_char=${IPMITOOL_OPTS##-e }  # strip out everything before '-e '
            escape_char=${escape_char:0:1}     # use first character
            ;;
    esac
    log_debug "Using escape character: ${escape_char}"
    echo "${escape_char}"
}

get_ipmitool_pids() {
    # Return all process id matching ipmitool against this BMC address (have
    # seen cases where there are multiple active ipmitool processes active for
    # a given IP)
    pgrep -a ipmitool | awk '/'"${BMC_ADDRESS}"'/ { print $1; }'
}

ipmitool_kill() {
    # Kill all ipmitool processes using this BMC address
    log_progress "Shutting down IPMI capture"
    local -a pids
    local pid
    for pid in $(get_ipmitool_pids); do
        pids+=("${pid}")
    done
    if [ -n "${pids[*]}" ]; then
        ipmitool_deactivate
        sleep 1
    else
        log_info "Finished. No ipmitool sessions found for ${BMC_ADDRESS}"
        return 0
    fi
    log_info "Killing ipmitool pids: ${pids[*]}"
    local -a failure_pids
    for pid in "${pids[@]}"; do
        kill "${pid}"
        rc=$?
        if [ "${rc}" != 0 ]; then
            sleep 1
            log_error "FAILED to kill ipmitool pid: ${pid} [rc=${rc}]. Retrying with -9"
            kill -9 "${pid}"
            rc=$?
            if [ "${rc}" != 0 ]; then
                failure_pids+=("${pid}")
                log_error "kill -9 ${pid} failed [rc=${rc}]"
            fi
        fi
    done
    if [ -n "${failure_pids[*]}" ]; then
        log_warn "Finished with errors. Process: ${failure_pids[*]}"
    else
        log_info "Finished. You may need to run 'reset' in the original terminal."
    fi
}

do_cleanup() {
    local running=false
    if is_ipmitool_running; then
        running=true
    fi
    log_info "cleanup: sol active: ${SOL_ACTIVE}, ipmitool: ${running}"
    if [ "${SOL_ACTIVE}" = "true" ] && [ "${running}" = "true" ]; then
        ipmitool_deactivate
    fi
}


################################################################################
# Main
#
main() {
    local arg_force_deactivate=
    local arg_redirect_to_file=
    local arg_rvmc_config=
    local arg_kill=
    while [ $# -gt 0 ] ; do
        case "${1:-""}" in
            -h|--help)
                help
                ;;
            -D|--debug)
                DEBUG=1
                ;;
            -f|--force-deactivate)
                arg_force_deactivate=1
                ;;
            -k|--kill)
                arg_kill=1
                ;;
            -r|--redirect)
                arg_redirect_to_file=1
                ;;
            -H|--host)
                shift
                BMC_ADDRESS=$1
                ;;
            -U|--user)
                shift
                BMC_USER=$1
                ;;
            -P|--password)
                shift
                BMC_PASSWORD=$1
                ;;
            -C|--ciphersuite)
                shift
                BMC_CIPHERSUITE=$1
                ;;
            -l|--log*)
                shift
                LOG_FILE=$1
                export LOG_FILE
                ;;
            --rvmc-config)
                shift
                arg_rvmc_config=$1
                ;;
            *)
                die "Invalid argument '$1' [use -h/--help for help]"
                ;;
        esac
        shift
    done
    if ! hash ipmitool 2>&-; then
        die "Cannot find 'ipmitool' in path. Is it installed?"
    fi
    if [ -n "${arg_rvmc_config}" ]; then
        if [ ! -r "${arg_rvmc_config}" ]; then
            die "RVMC config file does not exist or is not accessible: ${arg_rvmc_config}"
        fi
        BMC_ADDRESS=$(awk '/bmc_address:/ { print $2; }' "${arg_rvmc_config}" | sed 's/\"//g')
        [ -n "${BMC_ADDRESS}" ] || die "Could not set BMC_ADDRESS from ${arg_rvmc_config}"
        BMC_CIPHERSUITE=$(awk '/bmc_ciphersuite:/ { print $2; }' "${arg_rvmc_config}" | sed 's/\"//g')
        BMC_USER=$(awk '/bmc_username:/ { print $2; }' "${arg_rvmc_config}" | sed 's/\"//g')
        [ -n "${BMC_USER}" ] || die "Could not set BMC_USER from ${arg_rvmc_config}"
        BMC_PASSWORD=$(awk '/bmc_password:/ { print $2; }' "${arg_rvmc_config}" | sed 's/\"//g' | base64 -d)
        [ -n "${BMC_PASSWORD}" ] || die "Could not set BMC_PASSWORD from ${arg_rvmc_config}"
    else
        # Interactive. Prompt for BMC info:
        [ -n "${BMC_ADDRESS}" ] || read -r -p "BMC address: " BMC_ADDRESS
        [ -n "${BMC_USER}" ] || read -r -p "BMC user: " BMC_USER
        [ -n "${BMC_PASSWORD}" ] || read -r -s -p "BMC password: " BMC_PASSWORD
    fi
    # Final check
    [ -n "${BMC_ADDRESS}" ] || die "BMC_ADDRESS is empty"
    [ -n "${BMC_USER}" ] || die "BMC_USER is empty"
    [ -n "${BMC_PASSWORD}" ] || die "BMC_PASSWORD is empty"
    export BMC_ADDRESS BMC_USER BMC_PASSWORD

    CIPHERSUITE_OPTS=""
    if [ -n "${BMC_CIPHERSUITE}" ]; then
        CIPHERSUITE_OPTS="-C ${BMC_CIPHERSUITE}"
    fi
    export CIPHERSUITE_OPTS

    interactive_shell=1
    if [[ $- == *i* ]] || [ -n "${arg_redirect_to_file}" ] || [ -n "${arg_kill}" ]; then
        interactive_shell=
        export TERM=dumb
    fi

    if [ -n "${arg_kill}" ]; then
        ipmitool_kill
        exit $?
    fi

    if [ -n "${interactive_shell}" ]; then
        log_progress "Capturing console output at: ${LOG_FILE}"
        log_progress "To disconnect, use '<Enter>$(get_ipmitool_escape_char).' or reinvoke this script with the --kill option."
    fi

    # captures output in $LOG_FILE
    if [ -n "${arg_redirect_to_file}" ]; then
        redirect_output_to_file
    else
        tee_output_to_file
    fi

    if [ -n "${arg_force_deactivate}" ]; then
        log_progress "Forcing deactivate"
        ipmitool_deactivate
    fi

    # Ensure we disconnect on normal and abnormal termination signals:
    trap do_cleanup INT QUIT TERM EXIT

    ipmitool_activate
}

if [[ "${BASH_SOURCE[0]}" = "$0" ]]; then
    main "$@"
fi
