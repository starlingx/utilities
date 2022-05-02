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

# BI 20 e and n:
bifile='/home/sysadmin/.bi20e'
if [ ! -f ${bifile} ]; then
  for f in /usr/lib/postgresql/13/bin/*
  do
    echo "Linked $f"
    ln -s "$f" /usr/bin
  done
  touch ${bifile}
fi

# BI 20 f:
sed -i "s@python-psycopg2@python3-psycopg2@g" /usr/share/puppet/modules/postgresql/manifests/params.pp

# BI 20.o:
bifile='/home/sysadmin/.20o'
if [ ! -f ${bifile} ]; then
  sed -i 's@/var/lib/postgresql/%I@/var/lib/postgresql/22.06@g' /lib/systemd/system/postgresql@.service
  sed -i 's@/var/lib/postgresql/13/main@/var/lib/postgresql/22.06@g' /etc/postgresql/13/main/postgresql.conf
  sed -i 's@ExecStart=-/usr/bin/pg_ctlcluster --skip-systemctl-redirect %i start@ExecStart=-/usr/bin/pg_ctlcluster --skip-systemctl-redirect %i start -- -D /var/lib/postgresql/22.06@g' /lib/systemd/system/postgresql@.service
  systemctl daemon-reload

  sed -i '86 a \ \ Anchor["postgresql::server::service::end"] ->' /usr/share/puppet/modules/postgresql/manifests/server/role.pp
  touch ${bifile}
fi

# BI 25: ignore puppet apply warnings until we fix them
sed -i 's@Warning|@MMAAAAAAAAAASKED|@g' /usr/local/bin/puppet-manifest-apply.sh

# BI 36: first puppet runtime apply
bifile='/home/sysadmin/.bi36'
if [ ! -f ${bifile} ]; then
  # kdump service missing, disable kdump config
  sed -i 's@include ::platform::config::kdump@@g' /usr/share/puppet/modules/platform/manifests/config.pp

  touch ${bifile}
fi

# BI 40: workaround located at bootstrap section

# BI 50: postgres configuration issue
sed -i 's@#listen_addresses = '\''localhost'\''@listen_addresses = '\''*'\''@g' /etc/postgresql/13/main/postgresql.conf
echo "host    all             all             0.0.0.0/0               md5" >> /etc/postgresql/13/main/pg_hba.conf
# ipv6
echo "host    all             all             ::0/0                   md5" >> /etc/postgresql/13/main/pg_hba.conf

# BI 38.b: slow rpc calls.
echo "jit = off" >> /etc/postgresql/13/main/postgresql.conf
