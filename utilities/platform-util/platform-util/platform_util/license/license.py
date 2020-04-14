#
# Copyright (c) 2017-2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
import os
from platform_util.license import exception
import sys


def verify_license(*args):
    """Verify the license file"""
    if not os.path.isfile(args[1]):
        raise exception.LicenseNotFound()
    else:
        print("License file: ", args[1], " is installed")


def main():
    # Pass the command arguments to verify_license
    if len(sys.argv) < 2:
        print("Usage: verify-license <license file> [<optional_parameter>...]")
        exit(-1)

    arg_list = []
    for arg in sys.argv:
        arg_list.append(arg)

    try:
        verify_license(*arg_list)
    except exception.InvalidLicenseType:
        exit(1)
    except exception.LicenseNotFound:
        exit(2)
    except exception.ExpiredLicense:
        exit(3)
    except exception.InvalidLicenseVersion:
        exit(4)
    except exception.InvalidLicense:
        exit(5)
