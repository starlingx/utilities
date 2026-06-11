# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime

from network_platform_audit import state


def log_result(message, result):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    dots = "." * max(1, state.LOG_WIDTH - len(entry))
    log(f"{entry}{dots}{result}")


def log(msg=""):
    print(msg)
    state.LOG_BUFFER.append(msg)
    _write_to_log_file(msg)


def log_to_file_only(msg):
    if state.VERBOSE:
        print(msg)
    state.LOG_BUFFER.append(msg)
    _write_to_log_file(msg)


def _write_to_log_file(msg):
    if state.REPORT_FD is None:
        try:
            state.REPORT_FD = open(state.REPORT_FILE, "a")
        except Exception:
            return
    try:
        state.REPORT_FD.write(msg + "\n")
        state.REPORT_FD.flush()
    except Exception:
        pass


def print_category(title, files=None, description=None):
    state.current_category = title
    if title not in state.executed_categories:
        state.executed_categories.append(title)
    log("")
    log("=" * 50)
    log(title)
    log("=" * 50)
    if description:
        log("[TEST DESCRIPTION]")
        for line in description:
            log(line)
        log("")
    if files:
        for f in files:
            if f:
                log(f"Analyzing file: {f}")


def log_exec(cmd, rc, out, err):
    result = "PASS" if rc == 0 else "FAILED"
    log_result(cmd, result)
    if out:
        log_to_file_only(f"stdout: {out}")
    if rc != 0 and err:
        log(f"error: {err.strip()}")
        log_to_file_only(f"stderr: {err.strip()}")
    elif err:
        log_to_file_only(f"stderr: {err.strip()}")
