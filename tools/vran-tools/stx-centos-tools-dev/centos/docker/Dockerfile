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
        net-tools \
        iproute \
        ethtool \
        tcpdump \
    && yum install -y \
        pciutils \
        which \
        hwloc-libs \
        sysvinit-tools \
        epel-release \
        dmidecode \
        acpica-tools \
        opae.admin \
        opae-devel \
        opae-libs \
        opae-tools \
        opae-tools-extra \
    && yum install -y python-pip \
    && pip install intelhex

# Install PCM
RUN TEMP_DIR=$(mktemp -d) \
    && pushd $TEMP_DIR \
    && wget https://download.opensuse.org/repositories/home:/opcm/CentOS_7/x86_64/pcm-0-395.1.x86_64.rpm \
    && yum install -y ./*.rpm \
    && popd \
    && yum clean all \
    && rm -rf \
        /var/log/* \
        /tmp/* \
        /var/tmp/* \
        /var/cache/yum