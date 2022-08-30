import io
import json
import logging
import os
import re
import subprocess
import sys

import nsenter
import requests

from .common.constants import K8S_COREDUMP_CONF
from .common.constants import K8S_COREDUMP_LOG
from .common.constants import K8S_COREDUMP_TOKEN
from .common.constants import LOCALHOST_URL
from .common.constants import SYSTEMD_COREDUMP

logging.basicConfig(filename=K8S_COREDUMP_LOG, level=logging.DEBUG)
LOG = logging.getLogger("k8s-coredump")


def _getToken():
    try:
        with open(K8S_COREDUMP_CONF, 'r') as token_file:
            data = json.loads(token_file.read())
            token = data.get(K8S_COREDUMP_TOKEN)
            return token
    except IOError:
        LOG.error("Error: File does not appear to exist.")
    return None


# TODO (spresato) Need to be implemented
def _parseCoredumpPattern(pattern):
    pass


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
        LOG.error("Failed to read process cgroups: {}".format(e))
        sys.exit(-1)
    return None  # normal for processes not running in a container


def _lookupPod(pid):
    podUID = _getPodUID(pid)
    LOG.debug("lookupPod: podUID={}".format(podUID))
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


def _systemCoreFile():
    # delegate handling to systemd coredump handler
    try:
        cmd = [SYSTEMD_COREDUMP] + sys.argv[1:]
        subprocess.run(cmd)
    except subprocess.CalledProcessError as e:
        LOG.error("Failed to call systemd-coredump: {}".format(e))
        sys.exit(-1)


def _podCoreFile(pid, corefile):
    # create core file relative to dumping process if not an absolute path
    if not os.path.isabs(corefile):
        try:
            path = os.path.join("/proc", pid, "cwd")
            cwd = os.path.realpath(path)
            corefile = os.path.join(cwd, corefile)
        except os.OSError as e:
            LOG.error("Failed to get current working directory: {}".format(e))
            sys.exit(-1)

    LOG.debug("podCoreFile: corefile={}".format(corefile))

    with nsenter.Namespace(pid, 'mnt') as ns:
        try:
            with io.open(corefile, "wb") as f:
                f.write(sys.stdin.buffer.read())
                f.flush()
        except IOError as e:
            LOG.error("failed to create core file: {}".format(e))
            sys.exit(-1)


def CoreDumpHandler(**kwargs):
    pid = kwargs['pid']
    uid = kwargs['uid']
    exe = kwargs['comm']

    LOG.critical("Process %s (%s) of user %s dumped core." % (pid, exe, uid))

    pod = _lookupPod(pid)
    if pod:
        try:
            metadata = pod['metadata']
            annotations = metadata['annotations']
            core_pattern = annotations.get("starlingx.io/core_pattern")
            if core_pattern is not None:
                LOG.info("Pod %s/%s handling core dump for %s" % \
                         (metadata['namespace'], metadata['name'], pid))
                if not core_pattern:
                    # default core pattern
                    corefile = "core.%s.%s" % (exe, pid)
                else:
                    # https://man7.org/linux/man-pages/man5/core.5.html
                    corefile = _parseCoredumpPattern(core_pattern)

                _podCoreFile(pid, corefile)
                return  # core dump handled by Pod
            else:
                LOG.debug("Pod %s/%s does not define annotation core_pattern" % \
                          (metadata['namespace'], metadata['name']))
        except ValueError as e:
            LOG.error("Pod defined an invalid core dump annotation: {}".format(e))
            sys.exit(-1)
        except KeyError:
            LOG.debug("Pod does have annotations defined")
            pass

    # not handled by pod, redirect to systemd coredump handler
    _systemCoreFile()
