#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

SUBDIRS += k8s-ca-read

BUNDLE  := ../scripts/network_platform_audit
BUNDLER := tools/bundle_network_platform_audit.py

.PHONY: all build bundle clean

all: build

build: bundle
	for d in $(SUBDIRS); do \
		$(MAKE) -C $$d; \
	done

bundle:
	python3 $(BUNDLER) -o $(BUNDLE)

clean:
	for d in $(SUBDIRS); do \
		$(MAKE) -C $$d clean; \
	done
	rm -f $(BUNDLE)
