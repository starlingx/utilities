#!/usr/bin/env python
#
# Copyright (c) 2013-2014, 2016, 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


import setuptools

setuptools.setup(
    name='ceph_manager',
    version='1.0.1',
    description='CEPH manager',
    license='Apache-2.0',
    packages=['ceph_manager', 'ceph_manager.usm_api'],
    entry_points={
    }
)
