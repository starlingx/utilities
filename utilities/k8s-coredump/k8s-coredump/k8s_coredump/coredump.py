################################################################################
# Copyright (c) 2022,2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
import io
import json
import os
import re
import subprocess
import sys

import requests

from .common.constants import K8S_COREDUMP_CONF
from .common.constants import K8S_COREDUMP_TOKEN
from .common.constants import LOCALHOST_URL
from .common.constants import LOG
from .common.constants import SYSTEMD_COREDUMP
from .config_functions import get_annotations_config
from .config_functions import parse_core_pattern
from .config_functions import write_coredump_file


def _getToken():
    try:
        with open(K8S_COREDUMP_CONF, 'r') as token_file:
            data = json.loads(token_file.read())
            token = data.get(K8S_COREDUMP_TOKEN)
            return token
    except IOError:
        LOG.error("Error: File does not appear to exist.")
    return None


def _getPodUID(pid):
    try:
        pattern = re.compile("\d+:.+:/[^/]+/kubepods/[^/]+/pod([^/]+)/([0-9a-f]{64})")
        cgroups = os.path.join("/proc", pid, "cgroup")
        with io.open(cgroups, "r") as f:
            for line in f:
                match = re.match(pattern, line)
                if match:
                    # extract pod UID from pod cgroup path
                    return match.group(1)
    except IOError as e:
        LOG.error("Failed to read process cgroups: %s" % e)
        sys.exit(-1)
    return None  # normal for processes not running in a container


def _lookupPod(pid):
    podUID = _getPodUID(pid)
    LOG.debug("lookupPod: podUID=%s" % podUID)
    # retrieve pod details from kubelet
    if podUID:
        url = LOCALHOST_URL
        token = _getToken()
        headers = {"Authorization": "Bearer %s" % token}
        timeout = 1
        pods = requests.get(url=url, headers=headers, timeout=timeout, verify=False).json()
        for pod in pods.get('items'):
            metadata = pod.get('metadata')
            uid = metadata.get('uid')
            if uid == podUID:
                return pod

    return None


def _systemCoreFile(**kwargs):
    # delegate handling to systemd coredump handler
    try:
        systemd_args = [
            kwargs['host_pid'],  # %P
            kwargs['uid'],  # %u
            kwargs['gid'],  # %g
            kwargs['signal'],  # %s
            kwargs['timestamp'],  # %t
            kwargs['rlimit_core'],  # 9223372036854775808 %c
            kwargs['hostname']  # %h
        ]
        cmd = [SYSTEMD_COREDUMP] + systemd_args
        LOG.info("No pod information was found, using default system coredump. Command: %s" % cmd)
        subprocess.run(cmd)
        LOG.info("Dumped through default core process")
    except subprocess.CalledProcessError as e:
        LOG.error("Failed to call systemd-coredump: %s" % e)
        sys.exit(-1)


def _podCoreFile(pid, corefile, annotations_config):
    # create core file relative to dumping process if not an absolute path
    if not os.path.isabs(corefile):
        try:
            path = os.path.join("/proc", pid, "cwd")
            cwd = os.path.realpath(path)
            corefile = os.path.join(cwd, corefile)
        except os.OSError as e:
            LOG.error("Failed to get current working directory: %s" % e)
            sys.exit(-1)

    LOG.debug("podCoreFile: corefile=%s" % corefile)

    write_coredump_file(pid, corefile, annotations_config)


def CoreDumpHandler(**kwargs):
    pid = kwargs['host_pid']
    uid = kwargs['uid']
    exe = kwargs['comm']
    container_pid = kwargs['container_pid']
    LOG.critical(
        "Process of External PID %s / Internal PID %s (command:%s) of user %s dumped core" %
        (pid, container_pid, exe, uid)
    )

    pod = _lookupPod(pid)
    if pod:
        try:
            metadata = pod['metadata']
            annotations_config = get_annotations_config(pod)
            if annotations_config['core_pattern'] is not None:
                LOG.info("Pod %s/%s handling core dump for %s" %
                         (metadata['namespace'], metadata['name'], pid))
                if not annotations_config['core_pattern']:
                    # default core pattern
                    corefile = "core.%s.%s" % (exe, pid)
                else:
                    # https://man7.org/linux/man-pages/man5/core.5.html
                    corefile = parse_core_pattern(annotations_config['core_pattern'], **kwargs)

                _podCoreFile(pid, corefile, annotations_config)
                return  # core dump handled by Pod
            else:
                LOG.debug("Pod %s/%s does not define annotation core_pattern" %
                          (metadata['namespace'], metadata['name']))
        except ValueError as e:
            LOG.error("Pod defined an invalid core dump annotation: %s" % e)
            sys.exit(-1)
        except KeyError as e:
            LOG.debug("Pod does have annotations defined but some configuration is missing: %s" % e)
            pass

    # not handled by pod, redirect to systemd coredump handler
    _systemCoreFile(**kwargs)
