#!/bin/bash
#
# Copyright (c) 2021 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Utility script to display certificates in the system
#

USAGE="usage: ${0##*/} [-h for help] [-k for certificates stored in k8s secrets] [-e <num> to use a custom number of days for the expiry check]"

BOLD=$(tput bold)
RED=$(tput setaf 1)
GREEN=$(tput setaf 2)
RESET=$(tput sgr0)

KUBERNETES_SECRETS_MODE="NO"
EXPIRY_WARNING="90"
HAS_SUBCLOUD_CERTS=0
AUTO_LABEL="Automatic [Managed by Cert-Manager]"

TMP_SUBCLOUD_SECRETS_FILE=$(mktemp /tmp/subcloud-icas-tls-secrets.XXXXXXXXXX.txt)
TMP_TLS_SECRETS_FILE=$(mktemp)
TMP_GEN_SECRETS_FILE=$(mktemp)
TMP_SECRET_SECRET_FILE=$(mktemp)
TMP_GEN_SECRET_FILE=$(mktemp)

chmod +r $TMP_SUBCLOUD_SECRETS_FILE

while getopts "khe:" opt; do
    case $opt in
        k) KUBERNETES_SECRETS_MODE="YES" ;;
        e) EXPIRY_WARNING=${OPTARG} ;;
        h) echo $USAGE
            echo
            exit
            ;;
    esac
done

source /etc/platform/platform.conf

# Gets the name of all secrets used by cert-manager certs
CERT_MANAGER_SECRETS=$(kubectl --kubeconfig /etc/kubernetes/admin.conf get cert -A -o yaml | grep secretName: | grep -v f: | awk '{ print $2 }')

PrintCertInfo () {

    FILE=$1
    if [ ! -f "$FILE" ]; then
        return
    fi

    SUBJECT=$(cat $FILE | openssl x509 -noout -subject)
    echo -e '\t' "Subject\t: " ${SUBJECT#*=}

    ISSUER=$(cat $FILE | openssl x509 -noout -issuer)
    echo -e '\t' "Issuer \t: " ${ISSUER#*=}

    STARTDATE=$(cat $FILE | openssl x509 -noout -startdate)
    echo -e '\t' "Issue Date\t: " ${STARTDATE#*=}

    ENDDATE=$(cat $FILE | openssl x509 -noout -enddate)
    echo -e '\t' "Expiry Date\t: " ${ENDDATE#*=}

    SECONDSFUTURE=`date -d "${ENDDATE#*=}" "+%s"`
    SECONDSNOW=`date "+%s"`
    DIFFSECONDS=$(($SECONDSFUTURE-$SECONDSNOW))
    DIFFDAYS=$(($DIFFSECONDS/(60*60*24)))
    if [ $DIFFDAYS -gt $EXPIRY_WARNING ]; then
        echo -e '\t' "Residual Time\t: " "${GREEN}${DIFFDAYS}d${RESET}"
    else
        echo -e '\t' "Residual Time\t: " "${RED}${DIFFDAYS}d${RESET}"
    fi
}


PrintCertInfo-fromFile () {

    NAME=$1
    FILE=$2
    RENEWAL=$3
    FILENAME=$4
    if [ ! -f "$FILE" ]; then
        return
    fi

    if [ ! -n "$FILENAME" ]; then
        FILENAME=$FILE
    fi

    echo
    echo "$BOLD" $NAME " CERTIFICATE:" "$RESET"
    echo "$BOLD" "------------------------------------------" "$RESET"

    echo -e '\t' "Renewal \t: " $RENEWAL

    echo -e '\t' "Filename\t: " $FILENAME

    PrintCertInfo $FILE
}


PrintCertInfo-fromTlsSecret () {

    NAME=$1
    NAMESPACE=$2
    SECRET=$3
    RENEWAL="${RED}Manual${RESET}"
    AUTO_BY_DC_ORCH="sc-adminep-ca-certificate"

    if [[ $CERT_MANAGER_SECRETS == *$SECRET* || $AUTO_BY_DC_ORCH == *$SECRET* ]]; then
        RENEWAL="${GREEN}$AUTO_LABEL${RESET}"
    fi

    kubectl --kubeconfig /etc/kubernetes/admin.conf -n $NAMESPACE get secret $SECRET &> /dev/null
    if [ $? -eq 0 ]; then

        kubectl --kubeconfig /etc/kubernetes/admin.conf -n $NAMESPACE get secret $SECRET -o yaml | fgrep tls.crt | fgrep -v "f:tls.crt" | awk '{print $2}' | base64 --decode > $TMP_SECRET_SECRET_FILE

        echo
        echo "$BOLD" $NAMESPACE " / " $SECRET " CERTIFICATE:" "$RESET"
        echo "$BOLD" "------------------------------------------" "$RESET"

        echo -e '\t' "Renewal    \t: " $RENEWAL

        echo -e '\t' "Namespace\t: " $NAMESPACE

        echo -e '\t' "Secret     \t: " $SECRET

        PrintCertInfo $TMP_SECRET_SECRET_FILE
    fi
}


PrintCertInfo-fromGenericSecret () {

    NAME=$1
    NAMESPACE=$2
    SECRET=$3
    SECRETFILE=$4
    RENEWAL="${RED}Manual${RESET}"

    kubectl --kubeconfig /etc/kubernetes/admin.conf -n $NAMESPACE get secret $SECRET &> /dev/null
    if [ $? -eq 0 ]; then
        SECRET_VALUE=$(kubectl --kubeconfig /etc/kubernetes/admin.conf -n $NAMESPACE get secret $SECRET -o yaml | fgrep " $SECRETFILE" | awk '{print $2}')

        if ! IsACertificate $SECRET_VALUE; then
            return
        fi

        if [[ "mon-elastic-services-secrets" == $SECRET ]]; then
            TLS_SECRET_NAME=""
            if [[ "ca.crt" == $SECRETFILE ]]; then
                TLS_SECRET_NAME="mon-elastic-services-ca-crt"
            elif [[ "ext-ca.crt" == $SECRETFILE ]]; then
                TLS_SECRET_NAME="mon-elastic-services-extca-crt"
            fi
            TLS_SECRET_VALUE=$(kubectl --kubeconfig /etc/kubernetes/admin.conf -n $NAMESPACE get secret $TLS_SECRET_NAME -o yaml 2> /dev/null | fgrep " tls.crt" | awk '{print $2}')
            if [[ $TLS_SECRET_VALUE == $SECRET_VALUE && $CERT_MANAGER_SECRETS == *$TLS_SECRET_NAME* ]]; then
                RENEWAL="${GREEN}$AUTO_LABEL${RESET}"
            fi
        fi

        echo "$SECRET_VALUE" | base64 --decode > $TMP_GEN_SECRET_FILE

        echo
        echo "$BOLD" $NAMESPACE " / " $SECRET " / " $SECRETFILE " CERTIFICATE:" "$RESET"
        echo "$BOLD" "------------------------------------------" "$RESET"

        echo -e '\t' "Renewal    \t: " "${RENEWAL}"

        echo -e '\t' "Namespace\t: " $NAMESPACE

        echo -e '\t' "Secret     \t: " $SECRET

        PrintCertInfo $TMP_GEN_SECRET_FILE
    fi
}


PrintCertInfo-from-TlsSecret-or-File () {

    NAME=$1
    NAMESPACE=$2
    SECRET=$3
    FILE=$4
    RENEWAL="UNKNOWN"

    kubectl --kubeconfig /etc/kubernetes/admin.conf -n $NAMESPACE get secret $SECRET &> /dev/null
    if [ $? -eq 0 ]; then
        PrintCertInfo-fromTlsSecret "$NAME" "$NAMESPACE" "$SECRET"
    else
        PrintCertInfo-fromFile "$NAME" "$FILE" "${RED}Manual${RESET}"
    fi
}


IsACertificate () {
    echo "$1" | base64 -d 2> /dev/null | openssl x509 -text &> /dev/null
}


CleanUp () {
    rm -rf $TMP_TLS_SECRETS_FILE
    rm -rf $TMP_GEN_SECRETS_FILE
    rm -rf $TMP_SECRET_SECRET_FILE
    rm -rf $TMP_GEN_SECRET_FILE
}


# ALL TLS Certificates

if [ "$KUBERNETES_SECRETS_MODE" = "YES" ]; then
    echo "$BOLD" "----------------------------------------------" "$RESET"
    echo "$BOLD" "certificates stored in kubernetes tls secrets" "$RESET"
    echo "$BOLD" "----------------------------------------------" "$RESET"

    echo -e "$BOLD" " Renewal\t\tNamespace\t\tSecret\t\tResidual Time" "$RESET" >> $TMP_SUBCLOUD_SECRETS_FILE
    echo -e "$BOLD" " ----------------------------------------------------------------------------" "$RESET" >> $TMP_SUBCLOUD_SECRETS_FILE

    kubectl --kubeconfig /etc/kubernetes/admin.conf get secrets -A --field-selector type=kubernetes.io/tls | fgrep -v NAMESPACE | tr -s " "| cut -d' ' -f1-2 > $TMP_TLS_SECRETS_FILE
    while read line; do
        NAMESPACE="$(echo $line | cut -d' ' -f1)"
        SECRET="$(echo $line | cut -d' ' -f2)"
        # As number of subclouds may be high, it filters out subcloud certificates and saves it to a file.
        if [[ $SECRET == *"-adminep-ca-certificate"* && $NAMESPACE == "dc-cert" ]]; then
            TEXT=$( PrintCertInfo-fromTlsSecret " " $NAMESPACE $SECRET )
            echo "$TEXT" | grep "Renewal\|Namespace\|Secret\|Residual Time" | cut -d ':' -f2 | tr '\n' ' ' >> $TMP_SUBCLOUD_SECRETS_FILE
            echo >> $TMP_SUBCLOUD_SECRETS_FILE
            HAS_SUBCLOUD_CERTS=1
        else
            PrintCertInfo-fromTlsSecret " " $NAMESPACE $SECRET
        fi
    done < $TMP_TLS_SECRETS_FILE

# ALL OPAQUE SECRETS MATCHING WELL_KNOWN_CERT_KEY_PATTERNS

    echo
    echo "$BOLD" "---------------------------------------------------------------------" "$RESET"
    echo "$BOLD" "certificates stored in kubernetes opaque type secrets," "$RESET"
    echo "$BOLD" "with keys matching regex (^.*\.crt:|^.*\.pem:|^ca:|^.*cert:|^.*cer:)" "$RESET"
    echo "$BOLD" "---------------------------------------------------------------------" "$RESET"

    OPAQUE_SECRETS=$(kubectl --kubeconfig /etc/kubernetes/admin.conf get secrets --field-selector type=Opaque -A --no-headers | awk '{print $1 "|" $2 }')
    WELL_KNOWN_CERT_KEY_PATTERNS="(^.*\.crt:|^.*\.pem:|^ca:|^.*cert:|^.*cer:)"

    for secret in $OPAQUE_SECRETS; do
        NAMESPACE="$(echo $secret | cut -d'|' -f1)"
        SECRET="$(echo $secret | cut -d'|' -f2)"

        DESCRIBE_SECRET=$(kubectl --kubeconfig /etc/kubernetes/admin.conf describe secret $SECRET -n $NAMESPACE)
        MATCHES=$(echo "$DESCRIBE_SECRET" | egrep $WELL_KNOWN_CERT_KEY_PATTERNS)

        if [ -z "$MATCHES" ]; then
            continue
        fi
        echo "$MATCHES" > $TMP_GEN_SECRETS_FILE
        while read line; do
            KEY_FOUND=$(echo $line | cut -d':' -f1)
            PrintCertInfo-fromGenericSecret " " $NAMESPACE $SECRET $KEY_FOUND
        done < $TMP_GEN_SECRETS_FILE

    done

    if [ $HAS_SUBCLOUD_CERTS -eq 1 ]; then
        echo
        echo "$BOLD" "Note:" "$RESET" "Subcloud ICA certificates (*-adminep-ca-certificate) were saved to $TMP_SUBCLOUD_SECRETS_FILE in order to limit the size of the output."
    fi

    echo
    CleanUp
    exit 0
fi

# Main (default mode)

# SSL (restapi/gui) Certificate
PrintCertInfo-from-TlsSecret-or-File "ssl (restapi/gui)" "deployment" "system-restapi-gui-certificate" "/etc/ssl/private/server-cert.pem"

# Local Registry Certificate
PrintCertInfo-from-TlsSecret-or-File "registry.local" "deployment" "system-registry-local-certificate" "/etc/ssl/private/registry-cert.crt"

# Trusted CA Certifiates

for FILE in /opt/platform/config/${sw_version}/ssl_ca/*; do
    PrintCertInfo-fromFile "$FILE" "$FILE" "${RED}Manual${RESET}"
done

# DC AdminEp Certificates
PrintCertInfo-fromFile "DC-AdminEp-RootCA" "/etc/pki/ca-trust/source/anchors/dc-adminep-root-ca.crt" "${GREEN}$AUTO_LABEL${RESET}"

if [ -f "/etc/ssl/private/admin-ep-cert.pem" ]; then
    rm -rf /tmp/dc-adminep-inter-ca.crt
    cat /etc/ssl/private/admin-ep-cert.pem | sed -n '/-----END CERTIFICATE/,/END CERTIFICATE-----$/p' | tail -n +2 > /tmp/dc-adminep-inter-ca.crt
    if [ -s /tmp/dc-adminep-inter-ca.crt ]; then
        PrintCertInfo-fromFile "DC-AdminEp-InterCA" "/tmp/dc-adminep-inter-ca.crt" "${GREEN}$AUTO_LABEL${RESET}" "/etc/ssl/private/admin-ep-cert.pem"
    fi
fi

PrintCertInfo-fromFile "DC-AdminEp-Server" "/etc/ssl/private/admin-ep-cert.pem" "${GREEN}$AUTO_LABEL${RESET}"

# ETCD CA
PrintCertInfo-fromFile "etcd CA certificate" "/etc/etcd/ca.crt" "${RED}Manual${RESET}"
PrintCertInfo-fromFile "etcd client certificate" "/etc/etcd/etcd-client.crt" "${RED}Manual${RESET}"
PrintCertInfo-fromFile "etcd server certificate" "/etc/etcd/etcd-server.crt" "${RED}Manual${RESET}"
PrintCertInfo-fromFile "etcd apiserver client certificate" "/etc/etcd/apiserver-etcd-client.crt" "${RED}Manual${RESET}"

# OpenStack Certificates
PrintCertInfo-fromFile "openstack" "/etc/ssl/private/openstack/cert.pem" "${RED}Manual${RESET}"
PrintCertInfo-fromFile "openstack CA" "/etc/ssl/private/openstack/ca-cert.pem" "${RED}Manual${RESET}"

# OIDC certificates
PrintCertInfo-fromTlsSecret "OIDC" "kube-system" "local-dex.tls"
PrintCertInfo-fromGenericSecret "OIDC CA" "kube-system" "dex-client-secret" "dex-ca.pem"
PrintCertInfo-fromGenericSecret "OIDC WAD CA" "kube-system" "wadcert" "AD_CA.cer"


PrintCertInfo-fromGenericSecret "" "monitor" "mon-elastic-services-secrets" "ca.crt"
PrintCertInfo-fromGenericSecret "" "monitor" "mon-elastic-services-secrets" "ext-ca.crt"
PrintCertInfo-fromGenericSecret "" "monitor" "mon-elastic-services-secrets" "kibana.crt"

# Kubernetes Certificates
echo
echo "$BOLD" "Kubernetes CERTIFICATES:" "$RESET"
echo "$BOLD" "------------------------------------------" "$RESET"
echo "Note: 'CERTIFICATES'            are Renewal: ${GREEN}Automatic${RESET}"
echo "Note: 'CERTIFICATE AUTHORITIES' are Renewal: ${RED}Manual${RESET}"
echo
kubeadm alpha certs check-expiration
echo
CleanUp
exit 0
