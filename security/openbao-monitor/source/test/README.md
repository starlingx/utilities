# Testing baomon
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
