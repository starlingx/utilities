#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Tests for domains/__init__.py — registry and loader.
#
########################################################################

import os
import sys
import unittest

CONFTOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CONFTOOL_DIR)


from domains import DOMAIN_NAMES       # noqa: E402
from domains import get_all_domains    # noqa: E402
from domains import get_domain         # noqa: E402


class TestDomainRegistry(unittest.TestCase):
    """Test domain plugin registry."""

    def test_domain_names_list(self):
        expected = ['network', 'container', 'software', 'platform', 'storage']
        self.assertEqual(DOMAIN_NAMES, expected)

    def test_get_domain_returns_valid_domain(self):
        for name in DOMAIN_NAMES:
            domain = get_domain(name)
            self.assertTrue(hasattr(domain, 'INPUT_FILES'))
            self.assertTrue(hasattr(domain, 'NAME'))
            self.assertTrue(hasattr(domain, 'FILE_PREFIX'))
            self.assertTrue(callable(domain.load_config))
            self.assertTrue(callable(domain.build_summary))
            self.assertTrue(callable(domain.write_json))
            self.assertTrue(callable(domain.write_text))

    def test_get_domain_unknown_raises(self):
        with self.assertRaises(ValueError):
            get_domain('nonexistent')

    def test_get_all_domains_returns_all(self):
        domains = get_all_domains()
        self.assertEqual(len(domains), len(DOMAIN_NAMES))
        for name, domain in domains:
            self.assertIn(name, DOMAIN_NAMES)
            self.assertTrue(hasattr(domain, 'NAME'))


if __name__ == '__main__':
    unittest.main()
