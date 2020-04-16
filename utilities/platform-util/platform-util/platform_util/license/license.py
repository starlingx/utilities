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
    if not os.path.isfile(args[0]):
        raise exception.LicenseNotFound()


def main():
    # Pass the command arguments to verify_license
    if len(sys.argv) < 2:
        print("Usage: verify-license <license file> [<optional_parameter>...]")
        exit(-1)

    arg_list = []
    for arg in sys.argv:
        arg_list.append(arg)

    # The arguments passed to verify_license from command line
    # will not include sys.argv[0] which is the script name.
    # Only the actual arguments: sys.argv[1] and onward will be passed,
    # meaning license_file followed by optional attributes.
    try:
        verify_license(*arg_list[1:len(sys.argv)])
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
