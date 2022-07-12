ARG BASE
FROM ${BASE}

# Install stx-dev repo (StarlingX-Debian CENGN repo)
COPY stx-dev.list /etc/apt/sources.list.d/stx-dev.list.disabled

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

# Install packages provided only by Debian.
RUN set -ex && \
    cp -f /etc/apt/sources.list.d/debian.list.disabled /etc/apt/sources.list.d/debian.list && \
    cp -f /etc/apt/sources.list.d/stx.list.disabled /etc/apt/sources.list.d/stx.list && \
    apt-get update -y && \
    apt-get install -y \
        autoconf-archive \
        autogen \
        cmake \
        doxygen \
        dwarves \
        git \
        git-review \
        libcap-dev \
        libjson-c-dev \
        linux-perf-5.10 \
        ncurses-dev \
        sphinx-doc \
        unzip \
        uuid-dev \
        && \
    rm -f /etc/apt/sources.list.d/debian.list && \
    rm -f /etc/apt/sources.list.d/stx.list && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Enable stx repo only. Packages installs below this point will use
# only the managed locally-built & 3rd-party repos.
RUN set -ex && \
    cp /etc/apt/sources.list.d/stx.list.disabled /etc/apt/sources.list.d/stx.list

# Install required packages
RUN set -ex && \
    apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y \
        automake \
        bash \
        bc \
        bison \
        curl \
        fakeroot \
        flex \
        gcc \
        g++ \
        gettext \
        isomd5sum \
        libelf-dev \
        libhwloc-dev=1.11.12-3 \
        libssl-dev \
        linux-headers-5.10.0-6 \
        make \
        mkisofs \
        python3-yaml \
        rsync \
        sphinx-common \
        sudo \
        vim \
        wget \
        xz-utils \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Enable StarlingX-Debian CENGN repo
# Packages installs below this point will use DEB packages on CENGN repo.
RUN set -ex && \
    cp -f /etc/apt/sources.list.d/stx-dev.list.disabled /etc/apt/sources.list.d/stx.list && \
    apt-get update && \
    apt-get clean && \
    rm -rf \
        /var/lib/apt/lists/* \
        /var/log/* \
        /var/tmp/* \
        /tmp/*
