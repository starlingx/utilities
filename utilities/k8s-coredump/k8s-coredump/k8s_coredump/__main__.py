################################################################################
# Copyright (c) 2022,2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
import sys

from . import coredump


def main():
    # https://man7.org/linux/man-pages/man5/core.5.html
    kwargs = {
        'host_pid': sys.argv[1],  # %P
        'uid': sys.argv[2],  # %u
        'gid': sys.argv[3],  # %g
        'signal': sys.argv[4],  # %s
        'timestamp': sys.argv[5],  # %t
        'rlimit_core': sys.argv[6],  # %c
        'hostname': sys.argv[7],  # %h
        'comm': sys.argv[8],  # %e
        'container_pid': sys.argv[9],  # %p
    }
    coredump.CoreDumpHandler(**kwargs)


if __name__ == "__main__":
    main()
