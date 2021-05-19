#
# Copyright (c) 2017-2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import sys

from stevedore import extension

from platform_util.license import constants
from platform_util.license import exception


def suppress_stevedore_errors(manager, entrypoint, exception):
    """stevedore.ExtensionManager
    will try to import the entry point defined in the module.
    License plugins use virtual modules.
    So ExtensionManager will throw the "Could not load ..."
    error message, which is expected.
    Just suppress this error message to avoid cause confusion.
    """
    pass


def verify_license(*args):
    """Verify license using plugin"""

    license_plugins = extension.ExtensionManager(
        namespace='platformutil.license_plugins',
        invoke_on_load=True,
        invoke_args=(None,),
        on_load_failure_callback=suppress_stevedore_errors
    )
    license_plugins = sorted(license_plugins, key=lambda x: x.name)

    plugin_name = constants.LICENSE_PLUGIN_NAME
    plugin_obj = None
    for license_plugin in license_plugins:
        plugin_obj = license_plugin.obj
        if plugin_name != license_plugin.name[4:]:
            break
    if plugin_obj is not None:
        plugin_obj.verify_license(*args)


def main():
    # Check minimum number of arguments
    if len(sys.argv) < 2:
        print("Usage: verify-license <license file> [<optional_parameter>...]")
        exit(-1)

    # The arguments passed to verify_license from command line
    # will not include sys.argv[0] which is the script name.
    # Only the actual arguments: sys.argv[1] and onward will be passed,
    # meaning license_file followed by optional attributes.
    try:
        verify_license(*sys.argv[1:len(sys.argv)])
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


if __name__ == '__main__':
    main()
