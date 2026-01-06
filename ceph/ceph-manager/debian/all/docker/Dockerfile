ARG BASE
FROM ${BASE} AS stx-debian

FROM docker.io/openstackhelm/ceph-config-helper:ubuntu_jammy_18.2.2-1-20240312

RUN mkdir -p /tmp/build
WORKDIR /tmp/build

# Copy the STX sources list from the $BASE image
COPY --from=stx-debian /etc/apt/sources.list.d/stx.list /etc/apt/sources.list.d/

RUN apt-get update -y

# Install python3.9
RUN apt-get install -y               \
    python3.9                        \
    libpython3.9                     \
    software-properties-common

RUN add-apt-repository ppa:deadsnakes/ppa -y
RUN apt-get install python3.9-distutils -y
RUN add-apt-repository --remove ppa:deadsnakes/ppa -y

# Install pip3.9
RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
RUN python3.9 get-pip.py

# Install pip dependencies
RUN pip3.9 install greenlet yappi

# Install apt dependencies
RUN apt-get install -y               \
    python3-ldap=3.2.0-4ubuntu7.2    \
    libpq5 libldap-2.4-2             \
    python3-pyasn1                   \
    python3-pyasn1-modules

# Create fm user
RUN useradd -ms /bin/bash fm

# Change Python dependency version
RUN apt-get download fm-common
RUN dpkg-deb -x fm-common*.deb fm-common
RUN dpkg-deb --control fm-common*.deb fm-common/DEBIAN
RUN sed -i 's/<< 3.10/<< 3.11/g' fm-common/DEBIAN/control
RUN dpkg-deb -b fm-common
RUN dpkg -i fm-common.deb

# Install STX packages
RUN apt-get install -y               \
    fm-rest-api                      \
    python3-fm-api                   \
    python3-fmclient                 \
    python3-cephclient               \
    ceph-manager

# Ensures that ceph-manager will run on python3.9
RUN sed -i 's/python3\.*[0-9]*/python3.9/g' /usr/bin/ceph-manager

# Suppress warning messages because the mgr restful module is configured with a self-signed certificate
ENV PYTHONWARNINGS="ignore:Unverified HTTPS request"
RUN sed -i '/import sys/a import os\nos.environ["CURL_CA_BUNDLE"] = ""' /usr/bin/ceph-manager

# Cleanup
RUN rm -rf /tmp/build
RUN rm -rf /var/lib/apt/lists/*
RUN rm -f /etc/apt/sources.list.d/stx.list
RUN apt-get clean

WORKDIR /

CMD ["bash"]
