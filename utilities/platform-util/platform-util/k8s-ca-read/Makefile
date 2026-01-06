#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

CFLAGS := -Wall -O2

all: k8s-ca-read

k8s-ca-read: k8s-ca-read.c
	$(CC) $(CFLAGS) -o k8s-ca-read k8s-ca-read.c

clean:
	rm -f k8s-ca-read
