#! /bin/bash
#
# Copyright (c) 2019 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="containerization"
LOGFILE="${extradir}/${SERVICE}.info"
HELM_DIR="${extradir}/helm"
ETCD_DB_FILE="${extradir}/etcd_database.dump"
KUBE_CONFIG_FILE="/etc/kubernetes/admin.conf"
KUBE_CONFIG="--kubeconfig ${KUBE_CONFIG_FILE}"
echo    "${hostname}: Containerization Info ...: ${LOGFILE}"

###############################################################################
# All nodes
###############################################################################
mkdir -p ${HELM_DIR}
source_openrc_if_needed

CMD="docker image ls -a"
delimiter ${LOGFILE} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE}

CMD="crictl images"
delimiter ${LOGFILE} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE}

CMD="docker container ps -a"
delimiter ${LOGFILE} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE}

CMD="crictl ps -a"
delimiter ${LOGFILE} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE}

###############################################################################
# Active Controller
###############################################################################
if [ "$nodetype" = "controller" -a "${ACTIVE}" = true ] ; then

    declare -a KUBE_CMDS=(
        "kubectl ${KUBE_CONFIG} version"
        "kubectl ${KUBE_CONFIG} api-resources --verbs=list --namespaced -o name | xargs -n 1 kubectl ${KUBE_CONFIG} get --show-kind --ignore-not-found --all-namespaces"
        "kubectl ${KUBE_CONFIG} api-resources --verbs=list --namespaced -o name | xargs -n 1 kubectl ${KUBE_CONFIG} get --show-kind --ignore-not-found --all-namespaces -o yaml"
        "kubectl ${KUBE_CONFIG} get pvc --all-namespaces"
        "kubectl ${KUBE_CONFIG} get pvc --all-namespaces -o yaml"
        "kubectl ${KUBE_CONFIG} get pv --all-namespaces"
        "kubectl ${KUBE_CONFIG} get pv --all-namespaces -o yaml"
        "kubectl ${KUBE_CONFIG} get events --all-namespaces --sort-by='.metadata.creationTimestamp'  -o go-template='{{range .items}}{{printf \"%s %s\t%s\t%s\t%s\t%s\n\" .firstTimestamp .involvedObject.name .involvedObject.kind .message .reason .type}}{{end}}'"
    )

    for CMD in "${KUBE_CMDS[@]}" ; do
        delimiter ${LOGFILE} "${CMD}"
        eval ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE}
    done

    CMD="helm ${KUBE_CONFIG} version"
    delimiter ${LOGFILE} "${CMD}"
    ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE}

    CMD="helm ${KUBE_CONFIG} list -a"
    delimiter ${LOGFILE} "${CMD}"
    APPLIST=$(${CMD} 2>>${COLLECT_ERROR_LOG} | tee -a ${LOGFILE})
    APPLIST=$(echo "${APPLIST}" | awk '{if (NR!=1) {print}}')
    while read -r app; do
        APPNAME=$(echo ${app} | awk '{print $1}')
        APPREVISION=$(echo ${app} | awk '{print $2}')
        helm ${KUBE_CONFIG} status ${APPNAME} > ${HELM_DIR}/${APPNAME}.status
        helm ${KUBE_CONFIG} get values ${APPNAME} --revision ${APPREVISION} \
            > ${HELM_DIR}/${APPNAME}.v${APPREVISION}
    done <<< "${APPLIST}"

    CMD="cp -r /opt/platform/helm_charts ${HELM_DIR}/"
    delimiter ${LOGFILE} "${CMD}"
    ${CMD} 2>>${COLLECT_ERROR_LOG}

    export ETCDCTL_API=3
    CMD="etcdctl --endpoints=localhost:2379 get / --prefix"
    delimiter ${LOGFILE} "${CMD}"
    ${CMD} 2>>${COLLECT_ERROR_LOG} >> ${ETCD_DB_FILE}
fi

exit 0
