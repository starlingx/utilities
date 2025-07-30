#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

SUBDIRS += k8s-ca-read

.PHONY: all build clean

all: build

build:
	for d in $(SUBDIRS); do \
		$(MAKE) -C $$d; \
	done

clean:
	for d in $(SUBDIRS); do \
		$(MAKE) -C $$d clean; \
	done
