# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import os
import shlex
import shutil
import subprocess
import tempfile

from network_platform_audit import state
from network_platform_audit.log import log
from network_platform_audit.log import log_result


def ssh_skip_only(hostname):
    """Return True if the host should be skipped (no-pass, no failure recorded).

    - No --ssh-pass provided -> True (skip silently, no failure)
    - --ssh-pass provided but SSH failed -> False (real failure, must FAIL)
    """
    return hostname in state.SSH_NO_PASS_HOSTS


def ssh_check_remote(cat, hostname, label):
    """Log SKIP or FAILED for a remote host depending on why SSH is unavailable.

    Call this instead of bare log_result(..., "SKIP") when a test is being
    skipped because SSH is not available.  If --ssh-pass was provided the
    failure is real and goes into category_failures.
    """
    if ssh_skip_only(hostname):
        log_result(f"host {hostname}: {label}", "SKIP")
        log(f"  [SKIP] --ssh-pass not provided - skipping remote checks for {hostname}")
    else:
        log_result(f"host {hostname}: {label}", "FAILED")
        log(f"  [FAIL] SSH connection to {hostname} failed - remote checks could not run")
        state.category_failures[cat].append(
            f"{hostname}: SSH connection failed - {label} could not be verified"
        )


def _ensure_ssh_dir():
    """Return the private ControlMaster socket directory, creating it if needed.

    Uses /run (not /tmp) with mode 0700 so unprivileged users cannot place
    symlinks or guess the path, eliminating the predictable-name attack surface.
    """
    if state.SSH_SOCKET_DIR is None:
        state.SSH_SOCKET_DIR = tempfile.mkdtemp(prefix="nta-ssh-", dir="/run")
        os.chmod(state.SSH_SOCKET_DIR, 0o700)
    return state.SSH_SOCKET_DIR


def open_ssh_session(hostname):
    """Open a persistent SSH ControlMaster connection to hostname."""
    ssh_dir = _ensure_ssh_dir()
    socket_path = os.path.join(ssh_dir, hostname)

    # Remove stale socket from a previous reconnect attempt.  Safe here because
    # ssh_dir is 0700/root-owned, so no unprivileged symlink can exist inside it.
    if os.path.lexists(socket_path):
        try:
            os.unlink(socket_path)
        except Exception:
            pass

    ssh_base = (
        f"ssh -o StrictHostKeyChecking=no "
        f"-o ConnectTimeout=30 "
        f"-o ControlMaster=yes -o ControlPath={socket_path} "
        f"-o ControlPersist=3600 "
        f"{state.SSH_USER}@{hostname} true"
    )

    if state.SSH_PASSWORD:
        env = os.environ.copy()
        env["SSHPASS"] = state.SSH_PASSWORD
        cmd = f"sshpass -e {ssh_base}"
    else:
        cmd = (
            f"ssh -o StrictHostKeyChecking=no "
            f"-o ConnectTimeout=30 "
            f"-o BatchMode=yes "
            f"-o ControlMaster=yes -o ControlPath={socket_path} "
            f"-o ControlPersist=3600 "
            f"{state.SSH_USER}@{hostname} true"
        )
        env = None

    try:
        result = subprocess.run(cmd, shell=True, timeout=60,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env)
        if result.returncode != 0:
            err_msg = result.stderr.strip().splitlines()
            relevant = [line for line in err_msg if "Permission denied" in line
                        or "No route" in line or "Connection refused" in line
                        or "timed out" in line]
            short_err = relevant[-1] if relevant else (err_msg[-1] if err_msg else "unknown error")
            log(f"[WARN] SSH to {hostname} failed: {short_err}")
            state.SSH_FAILED_HOSTS.add(hostname)
            return None
    except Exception as e:
        log(f"[WARN] SSH to {hostname} failed: {e}")
        state.SSH_FAILED_HOSTS.add(hostname)
        return None

    # Validate the socket actually works - sshpass can return rc=0 even when
    # the ControlMaster socket was created before auth completed, causing all
    # subsequent BatchMode=yes commands to fail with Permission denied.
    verify_cmd = (
        f"ssh -o StrictHostKeyChecking=no -o BatchMode=yes "
        f"-o ControlPath={socket_path} "
        f"{state.SSH_USER}@{hostname} true"
    )
    try:
        verify = subprocess.run(verify_cmd, shell=True, timeout=15,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        if verify.returncode != 0:
            log(f"[WARN] SSH to {hostname} failed: ControlMaster socket not usable "
                f"(auth error - check password)")
            state.SSH_FAILED_HOSTS.add(hostname)
            return None
    except Exception as e:
        log(f"[WARN] SSH to {hostname} socket verify failed: {e}")
        state.SSH_FAILED_HOSTS.add(hostname)
        return None

    return socket_path


def remote_run(hostname, cmd, use_sudo=False, timeout=None):
    """Run a command on a remote host via persistent SSH ControlMaster.

    If use_sudo=True, wraps with 'sudo -S' and pipes SSH_PASSWORD via stdin.
    Returns (rc, stdout, stderr). If SSH is unavailable, returns failure.
    Automatically reconnects if the ControlMaster socket has expired.
    timeout: subprocess timeout in seconds. None uses state.CMD_TIMEOUT.
             Pass an explicit value for long-running commands (e.g. tcpdump).
    """
    if hostname in state.SSH_FAILED_HOSTS:
        return 1, "", f"SSH not available for {hostname}"

    if hostname not in state.ssh_sessions:
        state.ssh_sessions[hostname] = open_ssh_session(hostname)

    socket_path = state.ssh_sessions[hostname]
    if socket_path is None:
        return 1, "", f"SSH not available for {hostname}"

    cmd_shell = shlex.join(cmd) if isinstance(cmd, list) else cmd
    if use_sudo:
        remote_cmd = f"sudo -S {cmd_shell}"
        # Password is delivered via subprocess stdin, never interpolated into
        # the shell command string, so no quoting or injection risk.
        sudo_input = (state.SSH_PASSWORD + "\n") if state.SSH_PASSWORD else None
    else:
        remote_cmd = cmd_shell
        sudo_input = None

    def _run_via_socket(sock_path):
        ssh_cmd = (
            f"ssh -o StrictHostKeyChecking=no -o BatchMode=yes "
            f"-o ControlPath={sock_path} "
            f"{state.SSH_USER}@{hostname} {shlex.quote(remote_cmd)}"
        )
        try:
            process = subprocess.run(
                ssh_cmd, shell=True, text=True,
                input=sudo_input,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout if timeout is not None else state.CMD_TIMEOUT,
            )
            stderr = process.stderr.strip()
            stderr = "\n".join(line for line in stderr.splitlines()
                               if "[sudo]" not in line and "Password:" not in line)
            return process.returncode, process.stdout.strip(), stderr
        except Exception as error:
            return 1, "", str(error)

    rc, out, err = _run_via_socket(socket_path)

    # Detect expired/broken ControlMaster socket and reconnect once
    socket_broken = (
        rc != 0 and (
            not os.path.exists(socket_path)
            or "Permission denied" in err
            or "ControlPath" in err
            or "Connection closed" in err
            or "packet_write_wait" in err
        )
    )
    if socket_broken:
        log(f"[WARN] SSH ControlMaster to {hostname} lost - reconnecting...")
        state.ssh_sessions[hostname] = open_ssh_session(hostname)
        socket_path = state.ssh_sessions[hostname]
        if socket_path is None:
            return 1, "", f"SSH reconnect failed for {hostname}"
        rc, out, err = _run_via_socket(socket_path)

    return rc, out, err


def close_all_sessions():
    for hostname, socket_path in state.ssh_sessions.items():
        if socket_path is None:
            continue
        try:
            subprocess.run(
                f"ssh -O exit -o ControlPath={socket_path} {state.SSH_USER}@{hostname}",
                shell=True, timeout=5,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except Exception:
            pass

    if state.SSH_SOCKET_DIR and os.path.isdir(state.SSH_SOCKET_DIR):
        shutil.rmtree(state.SSH_SOCKET_DIR, ignore_errors=True)
        state.SSH_SOCKET_DIR = None
