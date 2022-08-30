#!/usr/bin/env python
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
import setuptools

setuptools.setup(
    name='k8s_coredump',
    version='1.0.0',
    description='K8s coredump handler',
    license='Apache-2.0',
    install_requires=['requests', 'nsenter'],
    packages=['k8s_coredump'],
    include_package_data=True,
    setup_requires=['pbr>=2.0.0'],
    pbr=True,
    entry_points={
    }
)
