# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Dispatcher: decide whether to run network_platform_audit (full platform
# audit requiring CLI/openrc access) or fall back to network_diagnostics
# (node-local diagnostic that works on any node without database access).
#
# Detection logic:
#   1. /etc/platform/openrc must exist.
#   2. After sourcing openrc, `system show` must succeed (rc=0).
#   3. The current host must match controller-0 or controller-1.
#   4. sm-query must report the service-group as active.
#
# If all conditions are met  -> run network_platform_audit (full audit).
# Otherwise                  -> run network_diagnostics (local-only mode).
#
# This module is the entry-point used by the bundled script when the user
# invokes it as `./network_platform_audit` (or any copy of the bundle).

import os
import re
import subprocess
import sys


def _run_silent(cmd):
    """Run *cmd* (str or list) and return (rc, stdout, stderr) with no logging."""
    try:
        result = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def _has_platform_cli_access():
    """Return True when the full platform audit can be executed.

    Checks (in order):
      1. /etc/platform/openrc exists.
      2. The current host is controller-0 or controller-1.
      3. openrc can be sourced without errors.
      4. `system show` succeeds (platform services are up).
      5. sm-query reports controller-services as active.
    """
    openrc = "/etc/platform/openrc"
    if not os.path.isfile(openrc):
        return False

    hostname = os.uname().nodename
    if not re.match(r"^controller-[01]$", hostname):
        return False

    # Source openrc and run `system show` in a single shell invocation
    rc, _, _ = _run_silent(f"bash -c 'source {openrc} && system show'")
    if rc != 0:
        return False

    # Verify this is the active controller
    rc, out, _ = _run_silent("sm-query service-group controller-services")
    if rc != 0:
        return False
    if not re.search(r"controller-services\s+active\b", out):
        return False

    return True


def dispatch():
    """Entry point for the bundled script.

    Probes CLI access and delegates to the appropriate audit function,
    passing through all command-line arguments transparently.
    """
    if _has_platform_cli_access():
        # Full platform audit – uses sysinv/Keystone and remote SSH checks.
        # Import the real main() from __main__ (already bundled in this file).
        _run_platform_audit()
    else:
        _print_fallback_reason()
        # Node-local diagnostics – no database access required.
        _run_network_diagnostics()


def _print_fallback_reason():
    """Print a brief explanation of why the fallback mode was selected."""
    openrc = "/etc/platform/openrc"
    hostname = os.uname().nodename

    reasons = []
    if not os.path.isfile(openrc):
        reasons.append(f"{openrc} not found")
    elif not re.match(r"^controller-[01]$", hostname):
        reasons.append(f"host '{hostname}' is not controller-0 or controller-1")
    else:
        rc, _, _ = _run_silent(f"bash -c 'source {openrc} && system show'")
        if rc != 0:
            reasons.append("platform CLI (system show) is not available")
        else:
            rc2, out, _ = _run_silent("sm-query service-group controller-services")
            if rc2 != 0 or not re.search(r"controller-services\s+active\b", out):
                reasons.append("this controller is not active (sm-query)")

    msg = "; ".join(reasons) if reasons else "platform CLI not accessible"
    print(f"[INFO] Platform CLI access not available ({msg}).")
    print("[INFO] Falling back to node-local network_diagnostics mode.")
    print("[WARN] Database/sysinv checks will NOT be executed - "
          "only node-local network tests are available without CLI access.")
    print()


def _run_platform_audit():
    """Invoke the network_platform_audit main() which is bundled in __main__."""
    # __main__.main() is already defined earlier in this bundled file.
    # We call it directly so argument parsing works as expected.
    try:
        main()  # noqa: F821
    except NameError:
        print("[ERROR] dispatcher.py must be executed inside the bundled script.")
        sys.exit(1)


def _run_network_diagnostics():
    """Invoke the self-contained network_diagnostics logic (bundled inline)."""
    try:
        _network_diagnostics_main()  # noqa: F821
    except NameError:
        print("[ERROR] dispatcher.py must be executed inside the bundled script.")
        sys.exit(1)
