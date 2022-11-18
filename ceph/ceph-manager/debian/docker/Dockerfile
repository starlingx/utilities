ARG BASE
FROM ${BASE}

RUN     apt-get update -y &&    \
        apt-get install -y      \
        python3-oslo.messaging  \
        python3-eventlet        \
        python3-fm-api          \
        fm-rest-api             \
        python3-fmclient        \
        fm-common               \
        librados2               \
        librbd1                 \
        ceph-common             \
        ceph-mon                \
        ceph-osd                \
        ceph-mgr

CMD ["bash"]
