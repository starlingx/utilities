ARG BASE
FROM ${BASE}

ARG STX_REPO_FILE=/etc/yum.repos.d/stx.repo

RUN set -ex ;                   \
    yum install --disablerepo=* \
        $(grep '^name=' ${STX_REPO_FILE} | awk -F '=' '{printf "--enablerepo=" $2 " "}') \
        -y                      \
        ceph-manager            \
        python-cephclient       \
        python-oslo-messaging   \
        python2-eventlet        \
        fm-api                  \
        fm-core                 \
        fm-rest-api             \
        python-fmclient         \
        fm-common               \
        ceph-common

CMD ["bash"]
