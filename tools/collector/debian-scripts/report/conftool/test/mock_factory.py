#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Mock Data Factory for Conftool Tests
#
# Provides synthetic .info file content and bundle directory scaffolding
# for unit and integration testing. Data is derived from real collect
# bundle sections (anonymized) to ensure parsers are tested against
# production formats.

# No hardcoded paths — all content is generated into
# tempfile directories.
#
#
########################################################################


import os
import sys

sys.dont_write_bytecode = True


# ---------------------------------------------------------------------------
# Section wrapper — mimics the ---- delimited format of .info files
# ---------------------------------------------------------------------------

def make_section(cmd, output, hostname='controller-0'):
    """Wrap command output in the .info section format."""
    ts = 'Tue 11 Feb 2025 09:24:12 PM UTC'
    sep = '-' * 68
    return (f"{sep}\n"
            f"{ts} : {hostname} : {cmd}\n"
            f"{sep}\n"
            f"{output}\n")


def make_info_file(*sections):
    """Concatenate multiple sections into a single .info file."""
    return ''.join(sections)


# ---------------------------------------------------------------------------
# Network domain mock data (from real collect bundle, anonymized)
# ---------------------------------------------------------------------------

NETWORK_IP_LINK = """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    RX: bytes  packets  errors  dropped missed  mcast
    942269871  839968   0       0       0       0
    TX: bytes  packets  errors  dropped carrier collsns
    942269871  839968   0       0       0       0
2: eno12399: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc htb state UP mode DEFAULT group default qlen 1000
    link/ether 30:3e:a7:09:30:f0 brd ff:ff:ff:ff:ff:ff
    altname enp51s0f0
    RX: bytes  packets  errors  dropped missed  mcast
    1629705965 2169015  0       0       0       310950
    TX: bytes  packets  errors  dropped carrier collsns
    1498180265 1864988  0       0       0       0
73: vlan113@eno12399: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
    link/ether 30:3e:a7:09:30:f0 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped missed  mcast
    301469219  94914    0       0       0       57
    TX: bytes  packets  errors  dropped carrier collsns
    33016198   70275    0       0       0       0
75: vlan41@eno12399: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc htb state UP mode DEFAULT group default qlen 1000
    link/ether 30:3e:a7:09:30:f0 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped missed  mcast
    995643653  800717   0       0       0       78026
    TX: bytes  packets  errors  dropped carrier collsns
    1121044542 789781   0       0       0       0
79: vlan42@eno12399: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
    link/ether 30:3e:a7:09:30:f0 brd ff:ff:ff:ff:ff:ff
    RX: bytes  packets  errors  dropped missed  mcast
    242786639  464479   0       0       0       75852
    TX: bytes  packets  errors  dropped carrier collsns
    295178187  377830   0       0       0       0
87: cali3a818d1e072@if2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
    link/ether ee:ee:ee:ee:ee:ee brd ff:ff:ff:ff:ff:ff link-netns cni-cc7b0da8-f7d8-0e59-0edc-7a2ab7b56259
    RX: bytes  packets  errors  dropped missed  mcast
    1146       15       0       0       0       0
    TX: bytes  packets  errors  dropped carrier collsns
    2078       13       0       0       0       0
"""  # noqa: E501, W291

NETWORK_IP_ADDR = """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
2: eno12399: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc htb state UP group default qlen 1000
    altname enp51s0f0
    inet 192.168.202.2/24 brd 192.168.202.255 scope global eno12399
       valid_lft forever preferred_lft forever
    inet 192.168.202.1/24 brd 192.168.202.255 scope global secondary eno12399
       valid_lft forever preferred_lft forever
73: vlan113@eno12399: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    inet 10.64.13.15/24 brd 10.64.13.255 scope global vlan113:3-8
       valid_lft forever preferred_lft forever
    inet 10.64.13.14/24 brd 10.64.13.255 scope global secondary vlan113
       valid_lft forever preferred_lft forever
75: vlan41@eno12399: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc htb state UP group default qlen 1000
    inet 10.81.81.3/24 brd 10.81.81.255 scope global vlan41:1-2
       valid_lft forever preferred_lft forever
    inet 10.81.81.2/24 brd 10.81.81.255 scope global secondary vlan41
       valid_lft forever preferred_lft forever
79: vlan42@eno12399: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    inet 192.168.206.2/24 brd 192.168.206.255 scope global vlan42
       valid_lft forever preferred_lft forever
"""  # noqa: E501

NETWORK_IP_ROUTE = """\
default via 10.64.13.1 dev vlan113 onlink
10.64.13.0/24 dev vlan113 proto kernel scope link src 10.64.13.15
10.81.81.0/24 dev vlan41 proto kernel scope link src 10.81.81.3
172.16.103.128/26 via 192.168.206.150 dev vlan42 proto bird
172.16.154.0/26 via 192.168.206.20 dev vlan42 proto bird
172.16.166.128/26 via 192.168.206.3 dev vlan42 proto bird
blackhole 172.16.192.64/26 proto bird
192.168.202.0/24 dev eno12399 proto kernel scope link src 192.168.202.2
192.168.206.0/24 dev vlan42 proto kernel scope link src 192.168.206.2
"""  # noqa: W291

PLATFORM_CONF = """\
nodetype=controller
subfunction=controller,worker,lowlatency
system_type=All-in-one
system_mode=duplex
sw_version=24.09
management_interface=vlan41
cluster_host_interface=vlan42
oam_interface=vlan113
"""

ETC_HOSTS = """\
127.0.0.1\tlocalhost\tlocalhost.localdomain
10.81.81.3\tcontroller-0
10.81.81.4\tcontroller-1
10.81.81.2\tcontroller\tregistry.local\tcontroller-platform-nfs
192.168.206.1\tcontroller-cluster-host
10.64.13.14\toamcontroller
"""


# ---------------------------------------------------------------------------
# Container domain mock data (from real collect bundle)
# ---------------------------------------------------------------------------

CONTAINER_GET_NODES = (  # noqa: E501
    "NAME           STATUS   ROLES           AGE   VERSION   "
    "INTERNAL-IP       EXTERNAL-IP   OS-IMAGE"
    "                         KERNEL-VERSION     CONTAINER-RUNTIME\n"
    "compute-0      Ready    <none>          24h   v1.29.2   "
    "192.168.206.20    <none>        Debian GNU/Linux 11 (bullseye)"
    "   6.6.0-1-rt-amd64   containerd://1.6.21\n"
    "compute-1      Ready    <none>          24h   v1.29.2   "
    "192.168.206.150   <none>        Debian GNU/Linux 11 (bullseye)"
    "   6.6.0-1-rt-amd64   containerd://1.6.21\n"
    "controller-0   Ready    control-plane   24h   v1.29.2   "
    "192.168.206.2     <none>        Debian GNU/Linux 11 (bullseye)"
    "   6.6.0-1-rt-amd64   containerd://1.6.21\n"
    "controller-1   Ready    control-plane   24h   v1.29.2   "
    "192.168.206.3     <none>        Debian GNU/Linux 11 (bullseye)"
    "   6.6.0-1-rt-amd64   containerd://1.6.21\n"
)

CONTAINER_GET_PODS = (  # noqa: E501
    "NAMESPACE        NAME                                   READY   STATUS"
    "      RESTARTS       AGE     IP               NODE"
    "           NOMINATED NODE   READINESS GATES\n"
    "cert-manager     cm-cert-manager-5d7fdf9b4-2sjzt        1/1     Running"
    "     0              55m     172.16.192.81    controller-0"
    "   <none>           <none>\n"
    "kube-system      calico-kube-controllers-7cdcb-djbjf    1/1     Running"
    "     0              37m     172.16.225.71    compute-2"
    "      <none>           <none>\n"
    "kube-system      coredns-78d4cf999f-abc12               1/1     Running"
    "     1 (22m ago)     130m    172.16.166.181   controller-1"
    "   <none>           <none>\n"
    "monitoring       prometheus-server-0                     0/1     "
    "CrashLoopBackOff   15(2d ago)     3d"
    "      172.16.192.88   controller-0"
    "   <none>           <none>\n"
)

CONTAINER_HELM_LIST = (
    "NAME\tNAMESPACE\tREVISION\tUPDATED\tSTATUS\tCHART\tAPP VERSION\n"
    "cm-cert-manager\tcert-manager\t2\t"
    "2025-02-10 20:38:37 +0000 UTC\tdeployed\t"
    "cert-manager-v1.15.3+STX.3\t1.15.3\n"
    "ic-nginx-ingress\tkube-system\t1\t"
    "2025-02-10 19:10:33 +0000 UTC\tdeployed\t"
    "ingress-nginx-4.11.1+STX.3\t1.11.1\n"
    "stx-cephfs-provisioner\tkube-system\t1\t"
    "2025-02-10 21:09:38 +0000 UTC\tdeployed\t"
    "ceph-csi-cephfs-3.11.0+STX.21\t3.11.0\n"
    "stuck-release\tmonitoring\t1\t"
    "2025-02-10 21:09:38 +0000 UTC\tpending-upgrade\t"
    "stuck-chart-0.1.0\t0.1\n"
)


# ---------------------------------------------------------------------------
# Software domain mock data (from real collect bundle)
# ---------------------------------------------------------------------------

SOFTWARE_LIST = """\
+--------------+------+----------+
| Release      | RR   |  State   |
+--------------+------+----------+
| WRCP-24.09.0 | True | deployed |
| WRCP-24.09.1 | True | deployed |
+--------------+------+----------+"""

SOFTWARE_DEPLOY_SHOW = "No deploy in progress"

SOFTWARE_DEPLOY_HOST_LIST = "No deploy in progress"

BUILD_INFO = """\
SW_VERSION="24.09"
BUILD_TARGET="Host Installer"
BUILD_TYPE="Formal"
BUILD_ID="2024-11-15_19-26-06"
SRC_BUILD_ID="22"

JOB="wrcp-24.09-debian"
BUILD_BY="jenkins"
BUILD_NUMBER="22"
BUILD_HOST="yow-wrcp3-lx"
BUILD_DATE="2024-11-16 00:26:06 +0000"
"""


# ---------------------------------------------------------------------------
# Platform domain mock data (from real collect bundle)
# ---------------------------------------------------------------------------

PLATFORM_DMIDECODE = """\
# dmidecode 3.3
Getting SMBIOS data from sysfs.
SMBIOS 3.3.0 present.

Handle 0x0000, DMI type 0, 26 bytes
BIOS Information
\tVendor: Dell Inc.
\tVersion: 1.14.1
\tRelease Date: 03/11/2024
\tAddress: 0xF0000
\tRuntime Size: 64 kB

Handle 0x0100, DMI type 1, 27 bytes
System Information
\tManufacturer: Dell Inc.
\tProduct Name: PowerEdge R750
\tVersion: Not Specified
\tSerial Number: DXG4N34
\tUUID: 4c4c4544-0058-4710-8034-c4c04f4e3334
\tWake-up Type: Power Switch
\tSKU Number: SKU=090E;ModelName=PowerEdge R750
\tFamily: PowerEdge

Handle 0x0200, DMI type 2, 8 bytes
"""

PLATFORM_LSCPU = """\
Architecture:                         x86_64
CPU op-mode(s):                       32-bit, 64-bit
CPU(s):                               128
Thread(s) per core:                   2
Core(s) per socket:                   32
Socket(s):                            2
NUMA node(s):                         2
Vendor ID:                            GenuineIntel
Model name:                           Intel(R) Xeon(R) Gold 6338N CPU @ 2.20GHz
Stepping:                             6
CPU MHz:                              3155.250
BogoMIPS:                             4400.00
L1d cache:                            3 MiB
L1i cache:                            2 MiB
L2 cache:                             96 MiB
L3 cache:                             96 MiB
"""

PLATFORM_UPTIME = """\
 21:22:47 up 47 min,  1 user,  load average: 4.67, 6.37, 6.64
"""

PLATFORM_MEMINFO = """\
MemTotal:       261189476 kB
MemFree:        242242440 kB
MemAvailable:   242280860 kB
Buffers:          192584 kB
Cached:          3537512 kB
SwapCached:            0 kB
Active:          1419408 kB
Inactive:        6800120 kB
HugePages_Total:       0
HugePages_Free:        0
Hugepagesize:       2048 kB
"""

PLATFORM_PROC_VERSION = """\
Linux version 6.6.0-1-rt-amd64 (root@wrcp-24-09-debian-stx-pkgbuilder-54bbcd64cb-vkcrn) (gcc-10 (Debian 10.2.1-6) 10.2.1 20210110, GNU ld (GNU Binutils for Debian) 2.35.2) #1 SMP PREEMPT_RT StarlingX Debian 6.6.52-1.stx.95 (2024-11-16)
"""  # noqa: E501

PLATFORM_SM_DUMP = """\
oam-services                     active               active
controller-services              active               active
cloud-services                   active               active
patching-services                active               active
directory-services               active               active
web-services                     active               active
storage-services                 active               active
storage-monitoring-services      active               active
vim-services                     active               active
"""

PLATFORM_COREDUMPS = ""


# ---------------------------------------------------------------------------
# Storage domain mock data (from real collect bundle)
# ---------------------------------------------------------------------------

STORAGE_CEPH_STATUS = """\
  cluster:
    id:     471183b8-9997-45cd-90ef-7e7e78615412
    health: HEALTH_OK

  services:
    mon: 3 daemons, quorum controller,controller-0,controller-1 (age 21m)
    mgr: controller-1(active, since 2h), standbys: controller-0
    mds: kube-cephfs:1 {0=controller-1=up:active} 1 up:standby
    osd: 2 osds: 2 up (since 42m), 2 in (since 42m)

  data:
    pools:   3 pools, 192 pgs
    objects: 22 objects, 17 KiB
    usage:   13 GiB used, 1.7 TiB / 1.7 TiB avail
    pgs:     192 active+clean
"""

STORAGE_DF = """\
Filesystem                       Type  Size  Used Avail Use% Mounted on
/dev/mapper/cgts--vg-root--lv    ext4   21G  7.8G   13G  40% /sysroot
/dev/sda3                        ext4  2.1G  271M  1.7G  15% /boot
/dev/mapper/cgts--vg-var--lv     ext4   21G  5.8G   15G  29% /var
/dev/mapper/cgts--vg-log--lv     ext4  8.2G  226M  7.5G   3% /var/log
/dev/sda1                        ext4   31G   37k   30G   1% /var/rootdirs/opt/platform-backup
/dev/mapper/cgts--vg-docker--lv  xfs    33G  9.1G   24G  29% /var/lib/docker
"""  # noqa: E501

STORAGE_DRBD = """\
version: 8.4.11 (api:1/proto:86-101)
srcversion: E101BCE78F2AA7247827232
 0: cs:Connected ro:Primary/Secondary ds:UpToDate/UpToDate C r-----
    ns:18044 nr:21456 dw:39528 dr:32669 al:30 bm:0 lo:0 pe:0 ua:0 ap:0 ep:1 wo:f oos:0
 1: cs:Connected ro:Primary/Secondary ds:UpToDate/UpToDate C r-----
    ns:688 nr:208 dw:900 dr:11889 al:8 bm:0 lo:0 pe:0 ua:0 ap:0 ep:1 wo:f oos:0
 2: cs:Connected ro:Primary/Secondary ds:UpToDate/UpToDate C r-----
    ns:2816 nr:0 dw:2820 dr:14409 al:7 bm:0 lo:0 pe:0 ua:0 ap:0 ep:1 wo:f oos:0
"""  # noqa: E501

STORAGE_LSBLK = """\
NAME                          MAJ:MIN RM   SIZE RO TYPE MOUNTPOINTS
sda                             8:0    0 447.1G  0 disk
|-sda1                          8:1    0  30.5G  0 part /var/rootdirs/opt/platform-backup
|-sda2                          8:2    0   512M  0 part
|-sda3                          8:3    0     2G  0 part /boot
|-sda4                          8:4    0   512M  0 part
|-sda5                          8:5    0 413.7G  0 part
sdb                             8:16   0 894.3G  0 disk
|-sdb1                          8:17   0 894.3G  0 part
"""


# ---------------------------------------------------------------------------
# Bundle scaffolding helpers
# ---------------------------------------------------------------------------

def create_bundle(base_dir, hostname='controller-0',
                  timestamp='20250211.212225'):
    """Create a minimal collect bundle directory structure.

    Returns the bundle_dir path.
    """
    bundle_dir = base_dir
    host_dirname = f"{hostname}_{timestamp}"
    host_dir = os.path.join(bundle_dir, host_dirname)

    # Create required directories
    dirs = [
        os.path.join(host_dir, 'var', 'extra'),
        os.path.join(host_dir, 'var', 'extra', 'software'),
        os.path.join(host_dir, 'etc', 'platform'),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)

    # --- Network files ---
    networking_info = make_info_file(
        make_section('ip -s link', NETWORK_IP_LINK, hostname),
        make_section('ip -4 -s addr', NETWORK_IP_ADDR, hostname),
        make_section('ip -4 route', NETWORK_IP_ROUTE, hostname),
    )
    _write(host_dir, 'var/extra/networking.info', networking_info)
    _write(host_dir, 'var/extra/interface.info', '')
    _write(host_dir, 'var/extra/netstat.info', '')
    _write(host_dir, 'etc/platform/platform.conf', PLATFORM_CONF)
    _write(host_dir, 'etc/hosts', ETC_HOSTS)

    # --- Container files ---
    kube_info = make_info_file(
        make_section('kubectl get nodes -o wide',
                     CONTAINER_GET_NODES, hostname),
        make_section('kubectl get pods --all-namespaces -o wide',
                     CONTAINER_GET_PODS, hostname),
    )
    _write(host_dir, 'var/extra/containerization_kube.info', kube_info)

    helm_info = make_info_file(
        make_section(
            'sudo -u root KUBECONFIG=/etc/kubernetes/admin.conf '
            'helm list --all --all-namespaces',
            CONTAINER_HELM_LIST, hostname),
    )
    _write(host_dir, 'var/extra/containerization_helm.info', helm_info)
    _write(host_dir, 'var/extra/containerization_host.info', '')
    _write(host_dir, 'var/extra/containerization_events.info', '')

    # --- Software files ---
    usm_info = make_info_file(
        make_section('software list', SOFTWARE_LIST, hostname),
        make_section('software deploy show',
                     SOFTWARE_DEPLOY_SHOW, hostname),
        make_section('software deploy host-list',
                     SOFTWARE_DEPLOY_HOST_LIST, hostname),
    )
    _write(host_dir, 'var/extra/usm.info', usm_info)
    _write(host_dir, 'etc/build.info', BUILD_INFO)

    # --- Platform files ---
    host_info = make_info_file(
        make_section('dmidecode', PLATFORM_DMIDECODE, hostname),
        make_section('lscpu', PLATFORM_LSCPU, hostname),
        make_section('uptime', PLATFORM_UPTIME, hostname),
        make_section('cat /proc/version',
                     PLATFORM_PROC_VERSION, hostname),
        make_section('cat /proc/meminfo', PLATFORM_MEMINFO, hostname),
    )
    _write(host_dir, 'var/extra/host.info', host_info)

    memory_info = make_info_file(
        make_section('cat /proc/meminfo', PLATFORM_MEMINFO, hostname),
    )
    _write(host_dir, 'var/extra/memory.info', memory_info)
    _write(host_dir, 'var/extra/process.info', '')
    _write(host_dir, 'var/extra/bmc.info', '')

    sm_info = make_info_file(
        make_section('sm-dump', PLATFORM_SM_DUMP, hostname),
    )
    _write(host_dir, 'var/extra/sm.info', sm_info)

    _write(host_dir, 'var/extra/coredump.info', PLATFORM_COREDUMPS)

    # --- Storage files ---
    ceph_info = make_info_file(
        make_section('ceph status', STORAGE_CEPH_STATUS, hostname),
    )
    _write(host_dir, 'var/extra/ceph.info', ceph_info)

    fs_info = make_info_file(
        make_section(
            'df -h -H -T --local -t ext2 -t ext3 -t ext4 -t xfs --total',
            STORAGE_DF, hostname),
        make_section('cat /proc/drbd', STORAGE_DRBD, hostname),
    )
    _write(host_dir, 'var/extra/filesystem.info', fs_info)
    _write(host_dir, 'var/extra/disk.info', '')

    blockdev_info = make_info_file(
        make_section('lsblk', STORAGE_LSBLK, hostname),
    )
    _write(host_dir, 'var/extra/blockdev.info', blockdev_info)
    _write(host_dir, 'var/extra/iscsi.info', '')

    return bundle_dir


def _write(host_dir, rel_path, content):
    """Write content to a file relative to host_dir."""
    path = os.path.join(host_dir, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
