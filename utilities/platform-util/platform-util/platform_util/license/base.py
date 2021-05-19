#
# Copyright (c) 2020 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import abc
import six


@six.add_metaclass(abc.ABCMeta)
class BaseLicense(object):
    """Base class for license validation operations.
    """

    @abc.abstractmethod
    def verify_license(self, *args):
        """Validate license file

        :param : variable number of parameters
        """

    def __init__(self, operator):
        self._operator = operator
