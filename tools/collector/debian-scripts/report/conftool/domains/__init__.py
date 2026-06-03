########################################################################
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
"""
Domain Plugin Registry

Each domain is a sub-package under domains/ that exports:
    INPUT_FILES   - list of (label, relative_path) tuples
    load_config   - load_config(host_dir, config)
    build_summary - build_summary(config) -> summary dict
    write_json    - write_json(summary, output_path)
    write_text    - write_text(summary, lines)
    NAME          - human-readable domain name
    FILE_PREFIX   - filename prefix for output files
"""

import sys

sys.dont_write_bytecode = True

# Ordered dict of domain_name -> module
# Add new domains here as they are created.
DOMAIN_NAMES = ['network', 'container', 'software', 'platform', 'storage']


def _make_domain(module):
    """Wrap a domain module into a Domain object."""
    return type('Domain', (), {
        'INPUT_FILES': module.INPUT_FILES,
        'NAME': module.NAME,
        'FILE_PREFIX': module.FILE_PREFIX,
        'load_config': staticmethod(module.load_config),
        'build_summary': staticmethod(module.build_summary),
        'write_json': staticmethod(module.write_json),
        'write_text': staticmethod(module.write_text),
    })


def get_domain(name):
    """Import and return a domain module by name."""
    if name == 'network':
        from domains import network  # noqa: F811
        return _make_domain(network)
    if name == 'container':
        from domains import container  # noqa: F811
        return _make_domain(container)
    if name == 'software':
        from domains import software  # noqa: F811
        return _make_domain(software)
    if name == 'platform':
        from domains import platform  # noqa: F811
        return _make_domain(platform)
    if name == 'storage':
        from domains import storage  # noqa: F811
        return _make_domain(storage)
    raise ValueError(f"Unknown domain: {name}")


def get_all_domains():
    """Return list of (name, domain_module) for all registered domains."""
    return [(name, get_domain(name)) for name in DOMAIN_NAMES]
