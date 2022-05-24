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
# Workaround BI 40: need to generate the correct dns with access to private docker registry
cat > /home/sysadmin/correct_dns.py <<EOF
#!/usr/bin/env python
import yaml
with open("/etc/resolv.conf", "w") as f:
    with open("/home/sysadmin/localhost.yml", "r") as stream:
        try:
            data = yaml.safe_load(stream)
            for dns in data['dns_servers']:
                    f.write('nameserver ' + dns)
                    f.write('\n')
        except yaml.YAMLError as exc:
            print(exc)
EOF
sudo python /home/sysadmin/correct_dns.py

# BI 25: ignore puppet apply warnings until we fix them
sed -i 's@Warning|@MMAAAAAAAAAASKED|@g' /usr/local/bin/puppet-manifest-apply.sh

# BI 36: first puppet runtime apply
bifile='/home/sysadmin/.bi36'
if [ ! -f ${bifile} ]; then
  # kdump service missing, disable kdump config
  sed -i 's@include ::platform::config::kdump@@g' /usr/share/puppet/modules/platform/manifests/config.pp

  touch ${bifile}
fi
