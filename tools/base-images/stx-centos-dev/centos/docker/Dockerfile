ARG BASE
FROM ${BASE}
COPY stx-dev.repo /etc/yum.repos.d/stx.repo
RUN yum-config-manager --disable stx-local-build stx-mirror-distro \
    && yum -y install yum-plugin-priorities \
    && yum-config-manager --enableplugin=priorities
RUN set -ex \
    && yum upgrade -y \
    && yum install -y \
        sudo \
        bash \
        python3-yaml \
        git \
        curl \
        unzip \
        wget \
        make \
        autogen \
        automake \
        autoconf-archive \
        bc \
        bison \
        isomd5sum \
        gettext \
        mkisofs \
        gcc \
        gcc-c++ \
        kernel-tools \
        kernel-devel \
        libcap-devel \
        libuuid-devel \
    && yum clean all \
    && rm -rf \
        /var/log/* \
        /tmp/* \
        /var/tmp/*