#
# Copyright (c) 2017-2019 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
import logging
import os
from platform_util.license import exception
import sys

LOG = logging.getLogger(__name__)

def verify_license(license_file):
    """Verify all features in a license file"""
    if not os.path.isfile(license_file):
        raise exception.LicenseNotFound()


def main():
    if len(sys.argv) == 2:
        licensefile = sys.argv[1]
    else:
        print("Usage: verify-license <license file>")
        exit(-1)

    try:
        verify_license(licensefile)
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
