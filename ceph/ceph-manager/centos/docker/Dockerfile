ARG BASE
FROM ${BASE}

ARG STX_REPO_FILE=/etc/yum.repos.d/stx.repo

RUN set -ex ;                   \
    yum erase  -y               \
        librados2 librbd1 ;     \
    yum install --disablerepo=* \
        $(grep '^name=stx' ${STX_REPO_FILE} | awk -F '=' '{printf "--enablerepo=" $2 " "}') \
        -y                      \
        --setopt=skip_missing_names_on_install=False \
        ceph-manager            \
        python-cephclient       \
        python-oslo-messaging   \
        python2-eventlet        \
        fm-api                  \
        fm-rest-api             \
        python-fmclient         \
        fm-common               \
        librados2               \
        librbd1                 \
        ceph-common             \
        ceph-mon                \
        ceph-osd                \
        ceph-mgr


CMD ["bash"]
