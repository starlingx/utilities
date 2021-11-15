#
# Copyright (c) 2019-2021 StarlingX.
#
# SPDX-License-Identifier: Apache-2.0
#

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# All Rights Reserved.
#

""" Define Logger class for this agent"""

import logging
import sys
from pci_irq_affinity.config import CONF


LOG = logging.getLogger("pci-interrupt-affinity")
formatter = logging.Formatter("%(asctime)s %(threadName)s[%(process)d] "
                              "%(name)s.%(pathname)s.%(lineno)d - %(levelname)s "
                              "%(message)s")
handler = logging.StreamHandler(stream=sys.stdout)
handler.setFormatter(formatter)
LOG.addHandler(handler)
LOG.setLevel(CONF.log_level)
