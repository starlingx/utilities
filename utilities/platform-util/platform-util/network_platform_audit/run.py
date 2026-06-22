# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
import shlex
import shutil
import subprocess

from network_platform_audit import state
from network_platform_audit.log import log_exec
from network_platform_audit.log import log_to_file_only


def _cmd_str(cmd):
    """Return a printable string for a command (list or string)."""
    return shlex.join(cmd) if isinstance(cmd, list) else cmd


def _timeout(t):
    """Return t if explicitly set, else the global CMD_TIMEOUT."""
    return t if t is not None else state.CMD_TIMEOUT


def run(cmd, timeout=None):
    try:
        process = subprocess.run(
            cmd, shell=isinstance(cmd, str), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=_timeout(timeout),
        )
        log_exec(_cmd_str(cmd), process.returncode, process.stdout.strip(), process.stderr.strip())
        return process.returncode, process.stdout.strip(), process.stderr.strip()
    except Exception as error:
        log_exec(_cmd_str(cmd), 1, "", str(error))
        return 1, "", str(error)


def run_checked(cmd, timeout=None):
    rc, out, err = run(cmd, timeout=timeout)
    if rc != 0 and state.current_category:
        state.category_failures[state.current_category].append(
            f"command failed (rc={rc}): {_cmd_str(cmd)}"
        )
    return rc, out, err


def run_silent(cmd, timeout=None):
    """Run a command without logging - used for internal checks only."""
    try:
        process = subprocess.run(
            cmd, shell=isinstance(cmd, str), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=_timeout(timeout),
        )
        return process.returncode, process.stdout.strip(), process.stderr.strip()
    except Exception as error:
        return 1, "", str(error)


def run_log_only(cmd, timeout=None):
    """Run a command and write output to the log file only (not to console).

    Used for data-gathering commands whose output is needed for post-analysis
    in /var/log/network_diag.log but should not clutter real-time console output.
    Full output is always written - no truncation.
    """
    cmd_display = _cmd_str(cmd)
    try:
        process = subprocess.run(
            cmd, shell=isinstance(cmd, str), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=_timeout(timeout),
        )
        rc = process.returncode
        out = process.stdout.strip()
        err = process.stderr.strip()
    except Exception as error:
        rc, out, err = 1, "", str(error)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_to_file_only(f"[{timestamp}] $ {cmd_display}  (rc={rc})")
    if out:
        for line in out.splitlines():
            log_to_file_only(f"  {line}")
    if err:
        log_to_file_only(f"stderr: {err}")
    return rc, out, err


def tool_available(tool):
    """Return True if the tool binary is found in PATH."""
    return shutil.which(tool) is not None
