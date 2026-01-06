# Testing baomon
Testing should include both the host-based deployment of openbao as well
as the StarlingX application deployment (helm, kubernetes).

## Addressing a host-based openbao server
This method runs the openbao server within a docker container, listening
on 0.0.0.0:8200. Then runs baomon commands to initialize ('init'), check
'health', 'unseal' and monitor the server with 'run' command.

To setup for testing, run the build instructions in build/Dockerfile and
test/Dockerfile, for example:

```
docker build --target bin --output bin/ -f ./build/Dockerfile .
test/scripts/gen_certs.sh
docker build -f test/Dockerfile .
```

After successfully building the test image use docker to run a
container, the openbao server, and baomon commands:

```
# Get the image id from docker build output or 'docker image ls' command
TEST_IMAGE=<image id>
docker run -it --add-host="OpenBao:0.0.0.0" $TEST_IMAGE bash

# assert I am 'manager' and that baomon and openbao are present
whoami
which baomon
which bao

# Switch user to root. PW is 'root' per test/Dockerfile
su root

# Add the certificates.
cp -r /workdir/OpenBaoCA/ca.crt /usr/local/share/ca-certificates/; /usr/sbin/update-ca-certificates

# run the server as root (manager does not have permission to the data
# directory).
/usr/bin/bao server --config=/workdir/testOpenbaoConfig.hcl \
    > /workdir/server.log 2>&1 &

exit # return to manager

# ping the server's health with curl
curl --cacert /workdir/OpenBaoCA/ca.crt \
    https://Openbao:8200/v1/sys/health \
| jq .

# observe the config file at default path
cat /workdir/testConfig.yaml

# ping the server's health with baomon
baomon health controller-0

# initialize the server
baomon init controller-0 --secret-shares 5 --secret-threshold 3

# Observe initialized status
baomon health controller-0

# unseal the server
baomon unseal controller-0

# Observe the unsealed status
baomon health controller-0

# Run the boamon 'run' command to monitor and unseal the server
baomon run &

# kill the server process
su root
pkill -f /usr/bin/bao

# observe the baomon 'run' command give errors about missing server
tail -f /workdir/openbao_monitor.log

# restart the server
/usr/bin/bao server --config=/workdir/testOpenbaoConfig.hcl \
    > /workdir/server.log2 2>&1 &

# observe the baomon 'run' command unseal the server
tail -f /workdir/openbao_monitor.log

exit # return to manager

# observe the server pod unseal status
baomon health controller-0
```
## Addressing openbao in kubernetes
The following method can be used to test baomon with the Starlingx
application. The openbao application is applied, the openbao-manager
pod is paused, and an alternate pod is run to test baomon.

Begin by copying the yaml template file to your controller-0 host:
k8s-openbao-baomon.yaml.temp.template. Update the template according
to your test, including updating the image reference.  For example:
```
TEST_IMAGE="docker.io/starlingx/stx-openbao-manager:master-debian-stable-latest"
TEST_CMD="baomon --in-cluster=true --k8s --config /mnt/conf/config.yaml run"
cat k8s-openbao-baomon.yaml.template \
| sed "s;%%IMAGE_REF_TAG%%;$TEST_IMAGE;" \
| sed "s;%%COMMAND%%;$TEST_CMD;" \
    > k8s-openbao-baomon.yaml
```
Prepare to pause the openbao-manager pod.  A pause value of '10'
will pause an active pod at an appropriate point in code. Pause
value '1' is appropriate for pausing the pod as it is started,
before it does anything.  This example pauses openbao-manager as
the application is being applied for the first time.
```
cat <<EOF > openbao-manager-helm-override.yaml
manager:
  pause: 1
EOF
```
Upload the application, apply helm-overrides, apply the application,
observe the paused openbao-manager pod, and apply the yaml for testing baomon:
```
system application-upload /usr/local/share/applications/helm/openbao-*.tgz

system helm-override-update openbao openbao-manager openbao --values openbao-manager-helm-override.yaml

system application-apply openbao

kubectl logs -n openbao stx-openbao-manager-3-0 | grep paused

kubectl apply -f k8s-openbao-baomon.yaml
```
Proceed to test the baomon code within the stx-openbao-baomon-0 pod, using commands such as:
```
kubectl exec -n openbao stx-openbao-baomon-0 -it -- bash

# ping the server's health with curl
curl --cacert /mnt/data/ca/tls.crt \
    https://stx-openbao.openbao.svc.cluster.local:8200/v1/sys/health \
| jq .

# ping the server's health with baomon
baomon --k8s --in-cluster --config=/mnt/conf/config.yaml health stx-openbao-0

# Initialize baomon
baomon --k8s --in-cluster --config=/mnt/conf/config.yaml init stx-openbao-0 --secret-shares 5 --secret-threshold 3

# Unseal baomon
baomon --k8s --in-cluster --config=/mnt/conf/config.yaml unseal stx-openbao-0

# etc etc
```
For updating the baomon executable without building a new test image:
copy over the executable file into the pod's workdir, and run that instead
kubectl cp ~/baomon stx-openbao-baomon-0:/workdir
/workdir/baomon ...
