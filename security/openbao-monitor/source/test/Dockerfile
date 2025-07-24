#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Test image for go openbao monitor
# Debian image with openbao and go openbao monitor installed
# Example commands to build:
#   test/scripts/gen_certs.sh
#   docker build -f test/Dockerfile .
#
# gen_certs.sh only needs to be run once, with the CA cert expiry of
# 10 years and the server/client certs expiring in 30 days.
# gen_certs.sh will not regenerate the CA cert if it exists, so that
# testing with a web browser doesn't require replacing the trusted
# certificate.

FROM debian:stable-slim

ENV PKG_LIST="mawk bash coreutils curl grep sed jq uuid-runtime \
    wget procps less file vim bash-completion gzip tar sudo"

USER root

# install listed packages, and openbao server
RUN set -ex; \
    apt-get update && apt-get install -y $PKG_LIST \
    && apt-get clean && rm -r /var/lib/apt/lists/* \
    && mkdir -p /tmp \
    && wget -P /tmp/ https://github.com/openbao/openbao/releases/download/v2.1.0/bao_2.1.0_linux_amd64.deb \
    && dpkg -i /tmp/bao_2.1.0_linux_amd64.deb \
    && rm /tmp/bao_2.1.0_linux_amd64.deb

# Copy over go openbao monitor
# Use the output folder used in the build
COPY ./bin/baomon /usr/bin/

# create a non-root user/group for openbao-manager
RUN groupadd --gid 1000 manager \
    && adduser --uid 1000 --gid 1000 manager \
        --home /workdir --shell /bin/bash

RUN echo "root:root" | chpasswd
RUN echo "manager:manager" | chpasswd
RUN usermod -aG sudo manager

# Copy and run auto-completion
COPY ./bin/baomon.completion /usr/share/bash-completion/completions/baomon

RUN echo "source /etc/bash_completion" >> /workdir/.bashrc

# Copy testing files
COPY ./bin/OpenBaoCA/ /workdir/OpenBaoCA/
COPY ./bin/OpenBaoServerCert/ /workdir/OpenBaoServerCert/
COPY ./bin/OpenBaoClientCert/ /workdir/OpenBaoClientCert/
COPY ./test/* /workdir/

RUN chown -R manager:manager /workdir

USER manager

CMD ["bash"]
