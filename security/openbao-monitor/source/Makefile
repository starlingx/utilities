#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

SHELL := /bin/bash

BAOMON_NAME ?= baomon
FAILPOINT_CTL_VERSION ?= v0.0.0-20260521055755-e7642935314f

# Local bin directory for build tools
TOOLBIN := $(CURDIR)/bin

# Auto-detect failpoint branch: if on openbao_failpoint, enable failpoint builds
CURRENT_BRANCH := $(shell git branch --show-current 2>/dev/null || echo "")
ifeq ($(CURRENT_BRANCH), openbao_failpoint)
    FAILPOINT_BUILD := true
else
    FAILPOINT_BUILD := false
endif

.PHONY: all build build-test clean test failpoint-ctl failpoint-enable failpoint-disable verify-no-failpoints

all: build

# Install failpoint-ctl to local bin directory
failpoint-ctl:
	GOBIN=$(TOOLBIN) go install github.com/pingcap/failpoint/failpoint-ctl@$(FAILPOINT_CTL_VERSION)

failpoint-enable: failpoint-ctl
	$(TOOLBIN)/failpoint-ctl enable ./commands ./config ./rekey

failpoint-disable:
	@if [ -x "$(TOOLBIN)/failpoint-ctl" ]; then \
		$(TOOLBIN)/failpoint-ctl disable ./commands ./config ./rekey; \
	fi

ifeq ($(FAILPOINT_BUILD),true)
build: failpoint-enable
	go mod download
	go build -tags failpoint -o $(BAOMON_NAME) .
else
build:
	go mod download
	go build -o $(BAOMON_NAME) .
endif

build-test: failpoint-enable
	go mod download
	go build -tags failpoint -o $(BAOMON_NAME)-test .

verify-no-failpoints:
	$(MAKE) FAILPOINT_BUILD=false build
	@echo "Verifying production binary has no failpoint symbols..."
	@if go tool nm $(BAOMON_NAME) | grep -qi "failpoint"; then \
		echo "FAIL: production binary contains failpoint symbols"; \
		exit 1; \
	fi
	@echo "PASS: no failpoint symbols in production binary"

clean: failpoint-disable
	rm -f $(BAOMON_NAME) $(BAOMON_NAME)-test
	rm -rf $(TOOLBIN)

test:
	go test ./...
