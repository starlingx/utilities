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
        git \
        git-review \
        unzip \
        autogen \
        autoconf-archive \
        linux-perf-5.10 \
        libcap-dev \
        uuid-dev \
        ncurses-dev \
        dwarves \
        cmake \
        libhwloc-dev \
        libjson-c-dev \
        doxygen \
        sphinx-doc \
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
        sudo \
        bash \
        python3-yaml \
        curl \
        wget \
        make \
        automake \
        bc \
        bison \
        isomd5sum \
        gettext \
        mkisofs \
        gcc \
        g++ \
        rsync \
        vim \
        linux-headers-5.10.0-6 \
        fakeroot \
        flex \
        libelf-dev \
        libssl-dev \
        xz-utils \
        sphinx-common \
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
