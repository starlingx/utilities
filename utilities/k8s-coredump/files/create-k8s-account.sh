#! /bin/bash

LOG_FILE="/var/log/k8s-account-creation-script.log"
FILE="/etc/k8s-coredump-conf.json"

# Check if file exists and token is not empty before trying to create.
if test -f "$FILE"; then
    if ! grep -q '"k8s_coredump_token": ""' $FILE; then
        echo "Token already created, skiping account and token file creation." >>$LOG_FILE
        exit 0
    fi
fi

echo "Initializing k8s-coredump kubernetes ServiceAccount creation" >>$LOG_FILE

# Create k8s-coredump account
echo "Running kubectl apply" >>$LOG_FILE
kubectl --kubeconfig=/etc/kubernetes/admin.conf apply -f /etc/k8s-coredump/k8s-coredump.yaml -n kube-system >>$LOG_FILE 2>&1

echo "Getting token and creating config file" >>$LOG_FILE

# Create token file
TOKEN=$(kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system get secrets coredump-secret-token -ojsonpath='{.data.token}' | base64 -d)
echo "TOKEN='$TOKEN'" >>$LOG_FILE
/bin/cat <<EOM >$FILE
{
    "k8s_coredump_token": "$TOKEN"
}
EOM
