ARG BASE
FROM ${BASE}

# Install stx-tools-dev repo (StarlingX-Debian repo)
COPY stx-tools-dev.list /etc/apt/sources.list.d/stx-tools-dev.list.disabled

#
# repos:
#   /etc/apt/sources.list.d/
#     debian.list.disabled         - vanilla debian repo
#     stx-x.list.disabled          - starlingx binary & build repos
#
# To enable a repo list:
#     cp /etc/apt/sources.list.d/$repo_list.disabled \
#        /etc/apt/sources.list.d/$repo_list
#
# To disable a repo list:
#     rm -f /etc/apt/sources.list.d/$repo_list
#

# Upgrade base packages to versions in managed repos
RUN set -ex && \
    cp -f /etc/apt/sources.list.d/stx.list.disabled /etc/apt/sources.list.d/stx.list && \
    apt-get update -y && \
    apt-get upgrade -y && \
    rm -f /etc/apt/sources.list.d/stx.list && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Enable stx repo only. Packages installs below this point will use
# only the managed locally-built & 3rd-party repos.
RUN set -ex && \
    cp /etc/apt/sources.list.d/stx.list.disabled /etc/apt/sources.list.d/stx.list

# Install dev tools package dependencies
RUN set -ex && \
    apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y \
        autoconf-archive \
        autogen \
        automake \
        bash \
        bc \
        bison \
        cmake \
        curl \
        doxygen \
        dwarves \
        fakeroot \
        flex \
        g++ \
        gcc \
        genisoimage \
        gettext \
        isomd5sum \
        kmod \
        libcap-dev \
        libelf-dev \
        libncurses-dev \
        libhwloc-dev=1.11.12-3 \
        libjson-c-dev \
        libssl-dev \
        linux-headers-5.10.0-6 \
        linux-perf-5.10 \
        make \
        pciutils \
        python-is-python3 \
        python3-intelhex \
        python3-pip \
        python3-pybind11 \
        python3-yaml \
        rsync \
        sphinx-common \
        sphinx-doc \
        sudo \
        sysvinit-utils \
        uuid-dev \
        vim \
        wget \
        xz-utils \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install dev tools
RUN set -ex && \
    apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y \
        acpica-tools \
        dmidecode \
        ethtool \
        git \
        git-review \
        iproute2 \
        linux-cpupower \
        net-tools \
        opae-libs opae-tools opae-tools-extra opae-devel \
        pcm \
        python3-opae.admin python3-opae.pacsign \
        tcpdump \
        trace-cmd \
        tree \
        unzip \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Enable StarlingX-Debian repo
# Packages installs below this point will use DEB packages from the StarlingX-Debian repo.
RUN set -ex && \
    cp -f /etc/apt/sources.list.d/stx-tools-dev.list.disabled /etc/apt/sources.list.d/stx.list && \
    apt-get update && \
    apt-get clean && \
    rm -rf \
        /var/lib/apt/lists/* \
        /var/log/* \
        /var/tmp/* \
        /tmp/*

# Enable upstream Debian repo so users may install other dev tools if needed.
# Packages installs below this point might differ from those on StarlingX.
RUN set -ex && \
    cp /etc/apt/sources.list.d/debian.list.disabled /etc/apt/sources.list.d/debian.list
