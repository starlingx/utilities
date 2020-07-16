# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os

from platform_util.license import base
from platform_util.license import exception


class StxVerifyLicense(base.BaseLicense):
    """Class to encapsulate license verification for starlingX """

    def verify_license(self, *args):
        """Verify the license file"""

        if len(args) < 1:
            raise Exception("Usage: verify-license <license file> [<optional_parameter>...]")

        if not os.path.isfile(args[0]):
            raise exception.LicenseNotFound()
