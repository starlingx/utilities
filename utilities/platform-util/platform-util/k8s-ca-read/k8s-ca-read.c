/*
 * Copyright (c) 2025 Wind River Systems, Inc.
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Setuid wrapper to securely invoke the python script for
 * reading the kubernetes CA certificate.
 */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>

int main() {
    setuid(0);
    execl("/usr/bin/python3", "python3", "/usr/local/bin/k8s-ca-read.py", (char *)NULL);
    perror("execl failed");
    return 1;
}
