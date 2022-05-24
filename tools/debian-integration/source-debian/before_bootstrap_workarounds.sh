# syntactic sugar
echo 'set mouse-=a' > ~/.vimrc
#############################
# WORKAROUNDS PRE-BOOTSTRAP #
#############################
# May want to sudo source this
# WARNING: Everything here was run under root user.

# NOTE: some of the issues may be hidden by this remount, ideally it should be reverted after each command. Don't expect many such issues so leave it as it is for now.
# mount -o remount,rw /usr
# mount -o remount,rw /
ostree admin unlock --hotfix

# sudo instant response and download stuff

# BI 25: ignore puppet apply warnings until we fix them
sed -i 's@Warning|@MMAAAAAAAAAASKED|@g' /usr/local/bin/puppet-manifest-apply.sh

# BI 36: first puppet runtime apply
bifile='/home/sysadmin/.bi36'
if [ ! -f ${bifile} ]; then
  # kdump service missing, disable kdump config
  sed -i 's@include ::platform::config::kdump@@g' /usr/share/puppet/modules/platform/manifests/config.pp

  touch ${bifile}
fi

# Debian ClusterIssuer cert-manager v1 is not currently available for test-issuer during bootstrap
bifile='/home/sysadmin/.cm'
if [ ! -f ${bifile} ]; then
  sed -i "s@cert-manager.io/v1@cert-manager.io/v1alpha2@" /usr/share/ansible/stx-ansible/playbooks/roles/bootstrap/bringup-bootstrap-applications/templates/test-issuer.yaml.j2
  touch ${bifile}
fi
