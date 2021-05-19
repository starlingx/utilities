#! /bin/bash
#
# Copyright (c) 2019-2021 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#


# Loads Up Utilities and Commands Variables

source /usr/local/sbin/collect_parms
source /usr/local/sbin/collect_utils

SERVICE="containerization"
LOGFILE="${extradir}/${SERVICE}.info"
LOGFILE_EVENT="${extradir}/${SERVICE}_events.info"
LOGFILE_API="${extradir}/${SERVICE}_api.info"
LOGFILE_HOST="${extradir}/${SERVICE}_host.info"
LOGFILE_IMG="${extradir}/${SERVICE}_images.info"
LOGFILE_KUBE="${extradir}/${SERVICE}_kube.info"
LOGFILE_PODS="${extradir}/${SERVICE}_pods.info"
LOGFILE_HELM="${extradir}/${SERVICE}_helm.info"

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
delimiter ${LOGFILE_IMG} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_IMG}

CMD="crictl images"
delimiter ${LOGFILE_IMG} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_IMG}

CMD="ctr -n k8s.io images list"
delimiter ${LOGFILE_IMG} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_IMG}

CMD="docker container ps -a"
delimiter ${LOGFILE_IMG} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_IMG}

CMD="crictl ps -a"
delimiter ${LOGFILE_IMG} "${CMD}"
${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_IMG}

CMD="cat /var/lib/kubelet/cpu_manager_state | python -m json.tool"
delimiter ${LOGFILE_HOST} "${CMD}"
eval ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_HOST}

###############################################################################
# Active Controller
###############################################################################
if [ "$nodetype" = "controller" -a "${ACTIVE}" = true ] ; then

    # Environment for kubectl and helm
    export KUBECONFIG=${KUBE_CONFIG_FILE}

    declare -a CMDS=()
    CMDS+=("kubectl version")
    CMDS+=("kubectl get nodes -o wide")
    CMDS+=("kubectl get nodes --show-labels")
    CMDS+=("kubectl get nodes -o json")
    CMDS+=("kubectl describe nodes")
    CMDS+=("kubectl describe nodes | grep -e Capacity: -B1 -A40 | grep -e 'System Info:' -B13 | grep -v 'System Info:'")
    CMDS+=("kubectl services")
    CMDS+=("kubectl get configmaps --all-namespaces")
    CMDS+=("kubectl get daemonsets --all-namespaces")
    CMDS+=("kubectl get pods --all-namespaces -o wide")
    CMDS+=("kubectl get pvc --all-namespaces")
    CMDS+=("kubectl get pvc --all-namespaces -o yaml")
    CMDS+=("kubectl get pv --all-namespaces")
    CMDS+=("kubectl get pv --all-namespaces -o yaml")
    CMDS+=("kubectl get sc --all-namespaces")
    CMDS+=("kubectl get serviceaccounts --all-namespaces")
    CMDS+=("kubectl get deployments.apps --all-namespaces")
    CMDS+=("kubectl get rolebindings.rbac.authorization.k8s.io --all-namespaces")
    CMDS+=("kubectl get roles.rbac.authorization.k8s.io --all-namespaces")
    CMDS+=("kubectl get clusterrolebindings.rbac.authorization.k8s.io")
    CMDS+=("kubectl get clusterroles.rbac.authorization.k8s.io")
    for CMD in "${CMDS[@]}" ; do
        delimiter ${LOGFILE_KUBE} "${CMD}"
        eval ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_KUBE}
        echo >>${LOGFILE_KUBE}
    done

    # api-resources; verbose, place in separate file
    CMDS=()
    CMDS+=("kubectl api-resources --verbs=list --namespaced -o name | xargs -n 1 kubectl get --show-kind --ignore-not-found --all-namespaces")
    CMDS+=("kubectl api-resources --verbs=list --namespaced -o name | xargs -n 1 kubectl get --show-kind --ignore-not-found --all-namespaces -o yaml")
    for CMD in "${CMDS[@]}" ; do
        delimiter ${LOGFILE_API} "${CMD}"
        eval ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_API}
        echo >>${LOGFILE_API}
    done

    # describe pods; verbose, place in separate file
    CMDS=()
    CMDS+=("kubectl describe pods --all-namespaces")
    for CMD in "${CMDS[@]}" ; do
        delimiter ${LOGFILE_PODS} "${CMD}"
        eval ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_PODS}
        echo >>${LOGFILE_API}
    done

    # events; verbose, place in separate file
    CMDS=()
    CMDS+=("kubectl get events --all-namespaces --sort-by='.metadata.creationTimestamp'  -o go-template='{{range .items}}{{printf \"%s %s\t%s\t%s\t%s\t%s\n\" .firstTimestamp .involvedObject.name .involvedObject.kind .message .reason .type}}{{end}}'")
    for CMD in "${CMDS[@]}" ; do
        delimiter ${LOGFILE_EVENT} "${CMD}"
        eval ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_EVENT}
        echo >>${LOGFILE_EVENT}
    done

    # Helm related
    CMD="helm version"
    delimiter ${LOGFILE_HELM} "${CMD}"
    ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_HELM}
    echo >>${LOGFILE_HELM}

    HELM_VERSION=$(helm version --client --short)
    if [[ $HELM_VERSION =~ v2 ]]; then
        CMD="helm list -a"
        delimiter ${LOGFILE_HELM} "${CMD}"
        APPLIST=$(${CMD} 2>>${COLLECT_ERROR_LOG} | tee -a ${LOGFILE_HELM})
        APPLIST=$(echo "${APPLIST}" | awk '{if (NR!=1) {print}}')
        while read -r app; do
            APPNAME=$(echo ${app} | awk '{print $1}')
            APPREVISION=$(echo ${app} | awk '{print $2}')
            helm status ${APPNAME} > ${HELM_DIR}/${APPNAME}.status
            helm get values ${APPNAME} --revision ${APPREVISION} \
                > ${HELM_DIR}/${APPNAME}.v${APPREVISION}
        done <<< "${APPLIST}"
    elif [[ $HELM_VERSION =~ v3 ]]; then
        # NOTE: helm environment not configured for root user
        CMD="sudo -u sysadmin KUBECONFIG=${KUBECONFIG} helm list --all --all-namespaces"
        delimiter ${LOGFILE_HELM} "${CMD}"
        ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_HELM}

        CMD="sudo -u sysadmin KUBECONFIG=${KUBECONFIG} helm search repo"
        delimiter ${LOGFILE_HELM} "${CMD}"
        ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_HELM}

        CMD="sudo -u sysadmin KUBECONFIG=${KUBECONFIG} helm repo list"
        delimiter ${LOGFILE_HELM} "${CMD}"
        ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_HELM}
    fi

    HELM2CLI=$(which helmv2-cli)
    if [ $? -eq 0 ]; then
        CMD="helmv2-cli -- helm version --short"
        delimiter ${LOGFILE_HELM} "${CMD}"
        ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_HELM}

        CMD="helmv2-cli -- helm list -a"
        delimiter ${LOGFILE_HELM} "${CMD}"
        mapfile -t ARR < <( ${CMD} 2>>${COLLECT_ERROR_LOG} )
        printf "%s\n" "${ARR[@]}" >> ${LOGFILE_HELM}
        for((i=1; i < ${#ARR[@]}; i++))
        do
            APPNAME=$(echo ${ARR[$i]} | awk '{print $1}')
            APPREVISION=$(echo ${ARR[$i]} | awk '{print $2}')
            ${HELM2CLI} -- helm status ${APPNAME} > ${HELM_DIR}/${APPNAME}.status
            ${HELM2CLI} -- helm get values ${APPNAME} --revision ${APPREVISION} \
                > ${HELM_DIR}/${APPNAME}.v${APPREVISION}
        done <<< "${APPLIST}"

        CMD="helmv2-cli -- helm search"
        delimiter ${LOGFILE_HELM} "${CMD}"
        ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_HELM}

        CMD="helmv2-cli -- helm repo list"
        delimiter ${LOGFILE_HELM} "${CMD}"
        ${CMD} 2>>${COLLECT_ERROR_LOG} >>${LOGFILE_HELM}
    fi

    CMD="cp -r /opt/platform/helm_charts ${HELM_DIR}/"
    delimiter ${LOGFILE} "${CMD}"
    ${CMD} 2>>${COLLECT_ERROR_LOG}

    export $(grep '^ETCD_LISTEN_CLIENT_URLS=' /etc/etcd/etcd.conf | tr -d '"')

    CMD="sudo ETCDCTL_API=3  etcdctl \
    --endpoints=$ETCD_LISTEN_CLIENT_URLS get / --prefix"

    #Use certificate if secured access is detected
    SEC_STR='https'
    if [[ "$ETCD_LISTEN_CLIENT_URLS" == *"$SEC_STR"* ]]; then
        CMD="$CMD --cert=/etc/etcd/etcd-server.crt \
        --key=/etc/etcd/etcd-server.key --cacert=/etc/etcd/ca.crt"
    fi

    delimiter ${LOGFILE} "${CMD}"
    ${CMD} 2>>${COLLECT_ERROR_LOG} >> ${ETCD_DB_FILE}
fi

exit 0
