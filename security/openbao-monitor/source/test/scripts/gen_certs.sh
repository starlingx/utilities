#!/bin/bash

#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

function usage {
    (
    echo "Usage: "
    echo "  One optional parameter pair:"
    echo "    --certbase <dirname>"
    echo "The default certbase is ./bin, matching the output of build"
    ) >&2
}

if [ $# -ne 0 -a $# -ne 2 ]; then
    usage
    exit 1
fi

if [ "$1" != "--certbase" ]; then
    CERTBASE=bin
else
    if [ -d "$2" ]; then
        CERTBASE="$2"
    else
        echo "'$2' is not a directory" >&2
        exit 1
    fi
fi

CAPATH="${CERTBASE}/OpenBaoCA"
SERVERPATH="${CERTBASE}/OpenBaoServerCert"
CLIENTPATH="${CERTBASE}/OpenBaoClientCert"
mkdir -p "$CAPATH" "$SERVERPATH" "$CLIENTPATH"

# for the benefit of the tester, do not recreate their CA
if [ ! -f "${CAPATH}/ca.crt" -o ! -f "${CAPATH}/ca.key" ]; then
    # generate the CA key
    openssl ecparam -name prime256v1 -genkey -noout \
        -out "${CAPATH}/ca.key"

    # generate a CA cert for test that is valid forever (10 years)
    keyUsage="critical, keyCertSign, digitalSignature, keyEncipherment"
    openssl req -new -x509 -sha256 \
        -key "${CAPATH}/ca.key" \
        -out "${CAPATH}/ca.crt" \
        -days 3650 \
        -addext "keyUsage = $keyUsage" \
        -subj '/CN=OpenBao Test CA/C=CA/O=StarlingX'
fi

# generate private key for the openbao server
openssl genrsa -out "${SERVERPATH}/tls.key" 2048

# generate certificate signing request for server
openssl req -new \
    -key "${SERVERPATH}/tls.key" \
    -out "${SERVERPATH}/server.csr" \
    -addext "subjectAltName = DNS:OpenBao, DNS:localhost, IP:127.0.0.1, IP:0.0.0.0" \
    -addext "keyUsage = critical, digitalSignature, keyEncipherment" \
    -subj '/CN=OpenBao Test Server/C=CA/O=StarlingX'

# work around bug in copying extensions when signing the crt
cat <<EOF > "${SERVERPATH}/ssl-extensions-x509.cnf"
[v3_ca]
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
subjectAltName = DNS:OpenBao, DNS:localhost, IP:127.0.0.1, IP:0.0.0.0
EOF

# sign the csr using CA (create the server cert)
openssl x509 -req -in "${SERVERPATH}/server.csr" \
    -CA "${CAPATH}/ca.crt" -CAkey "${CAPATH}/ca.key" \
    -CAcreateserial \
    -out "${SERVERPATH}/tls.crt" \
    -days 30 \
    -extensions v3_ca \
    -extfile "${SERVERPATH}/ssl-extensions-x509.cnf"

# generate private key for the baomon client
openssl genrsa -out "${CLIENTPATH}/tls.key" 2048

# generate certificate signing request for client
openssl req -new -key "${CLIENTPATH}/tls.key" \
    -out "${CLIENTPATH}/client.csr" \
    -addext "keyUsage = critical, digitalSignature" \
    -addext "extendedKeyUsage = critical, clientAuth" \
    -subj '/CN=OpenBao Test Client/C=CA/O=StarlingX'

# work around bug in copying extensions when signing the crt
cat <<EOF > "${CLIENTPATH}/ssl-extensions-x509.cnf"
[v3_ca]
basicConstraints = CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = critical, clientAuth
EOF

# sign the csr using CA (create the server cert)
openssl x509 -req -in "${CLIENTPATH}/client.csr" \
    -CA "${CAPATH}/ca.crt" -CAkey "${CAPATH}/ca.key" \
    -CAcreateserial \
    -out "${CLIENTPATH}/tls.crt" \
    -days 30 \
    -extensions v3_ca \
    -extfile "${CLIENTPATH}/ssl-extensions-x509.cnf"


