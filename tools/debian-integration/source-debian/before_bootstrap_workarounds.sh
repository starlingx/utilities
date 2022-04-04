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

# before bootstrap issue 7
hostnamectl set-hostname localhost

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

# BI 17:
bifile='/home/sysadmin/.bi17'
if [ ! -f ${bifile} ]; then
  # 1
  sed -i '82,86d' /usr/share/puppet/modules/sysinv/manifests/init.pp
  sed -i '81 a \ \ ensure_packages(["sysinv"], {\
\ \ \ \ ensure  => \$package_ensure,\
\ \ \ \ name    => \$::sysinv::params::package_name,\
\ \ \ \ require => Anchor["sysinv-start"],\
\ \ })' /usr/share/puppet/modules/sysinv/manifests/init.pp
  # 2
  sed -i '193,196d' /usr/share/puppet/modules/sysinv/manifests/api.pp
  sed -i '192 a \ \ \ \ ensure_packages(["sysinv"], {\
\ \ \ \ \ \ ensure  => \$package_ensure,\
\ \ \ \ \ \ name    => \$::sysinv::params::api_package,\
\ \ \ \ })' /usr/share/puppet/modules/sysinv/manifests/api.pp
  # 3
  sed -i '37,40d' /usr/share/puppet/modules/sysinv/manifests/conductor.pp
  sed -i '36 a \ \ \ \ ensure_packages(["sysinv-conductor"], {\
\ \ \ \ \ \ ensure => \$package_ensure,\
\ \ \ \ \ \ name   => \$::sysinv::params::conductor_package,\
\ \ \ \ })' /usr/share/puppet/modules/sysinv/manifests/conductor.pp
  # 4
  sed -i '44,47d' /usr/share/puppet/modules/sysinv/manifests/agent.pp
  sed -i '43 a \ \ \ \ ensure_packages(["sysinv-agent"], {\
\ \ \ \ \ \ ensure => \$package_ensure,\
\ \ \ \ \ \ name   => \$::sysinv::params::agent_package,\
\ \ \ \ })' /usr/share/puppet/modules/sysinv/manifests/agent.pp
  # do we need 1, 2 , 3, 4 anymore?
  sed -i "s@$api_package        = 'sysinv'@$api_package        = false@g" /usr/share/puppet/modules/sysinv/manifests/params.pp
  sed -i "s@agent_package      = 'sysinv'@agent_package      = false@g" /usr/share/puppet/modules/sysinv/manifests/params.pp
  sed -i "s@conductor_package  = 'sysinv'@conductor_package  = false@g" /usr/share/puppet/modules/sysinv/manifests/params.pp
  touch ${bifile}
fi

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
sed -i "s@docker-ce@docker.io@g" /usr/share/puppet/modules/platform/manifests/docker.pp
sed -i "s@python-fmclient@python3-fmclient@g" /usr/share/puppet/modules/fm/manifests/params.pp
sed -i "s@python-psycopg2@python3-psycopg2@g" /usr/share/puppet/modules/postgresql/manifests/params.pp

# BI 20.o:
bifile='/home/sysadmin/.20o'
if [ ! -f ${bifile} ]; then
  sed -i 's@/var/lib/postgresql/%I@/var/lib/postgresql/22.02@g' /lib/systemd/system/postgresql@.service
  sed -i 's@/var/lib/postgresql/13/main@/var/lib/postgresql/22.02@g' /etc/postgresql/13/main/postgresql.conf
  sed -i 's@ExecStart=-/usr/bin/pg_ctlcluster --skip-systemctl-redirect %i start@ExecStart=-/usr/bin/pg_ctlcluster --skip-systemctl-redirect %i start -- -D /var/lib/postgresql/22.02@g' /lib/systemd/system/postgresql@.service
  systemctl daemon-reload

  sed -i '86 a \ \ Anchor["postgresql::server::service::end"] ->' /usr/share/puppet/modules/postgresql/manifests/server/role.pp
  touch ${bifile}
fi

# BI 24:
bifile='/home/sysadmin/.24'
if [ ! -f ${bifile} ]; then
  sed -i '27 a \    return' /usr/lib/python3/dist-packages/sysinv/db/sqlalchemy/migrate_repo/versions/110_remove_snmp.py
  touch ${bifile}
fi

# BI 25: ignore puppet apply warnings until we fix them
sed -i 's@Warning|@MMAAAAAAAAAASKED|@g' /usr/local/bin/puppet-manifest-apply.sh

# BI 27: workaround remove grubby commands
bifile='/home/sysadmin/.27'
if [ ! -f ${bifile} ]; then
  A=$(grep -Rn "Get grub default kernel" /usr/share/ansible/stx-ansible/playbooks/roles/bootstrap/persist-config/tasks/one_time_config_tasks.yml | awk -F':' '{print $1}')
  B=$((A + 8))
  sed -i ${A}','${B}'d ' /usr/share/ansible/stx-ansible/playbooks/roles/bootstrap/persist-config/tasks/one_time_config_tasks.yml
  touch ${bifile}
fi

# BI 30: this is based on fixes to generate SOURCES.txt
sed -i 's@if relative in distribution.files:@if distribution.files and relative in distribution.files:@g' /usr/lib/python3/dist-packages/sysinv/common/utils.py

# BI 34: partial populate_initial_config.py
bifile='/home/sysadmin/.34'
if [ ! -f ${bifile} ]; then
  # workaround rootfs detection, hardcode /dev/sda
  sed -i 's@device_path = out.rstrip()@device_path = out.split("\\n")[0].rstrip()@g' /usr/share/ansible/stx-ansible/playbooks/roles/bootstrap/persist-config/files/populate_initial_config.py
  sed -i 's@"""Cloned from sysinv"""@return "/dev/sda"@g' /usr/share/ansible/stx-ansible/playbooks/roles/bootstrap/persist-config/files/populate_initial_config.py

cat > /tmp/34_restart_sysinv <<EOF

- name: Restart sysinv
  shell: |
    systemctl stop sysinv-agent
    sleep 3
    systemctl start sysinv-agent
    sleep 3
    systemctl stop sysinv-conductor
    sleep 10
    systemctl start sysinv-conductor
    sleep 10

EOF
  sed -i '64 {
    r /tmp/34_restart_sysinv
    }' /usr/share/ansible/stx-ansible/playbooks/roles/bootstrap/persist-config/tasks/update_sysinv_database.yml

  # .first_boot missing
  touch /etc/platform/.first_boot
  # workaround slow database interaction, use cached query
  sed -i 's@def _find_local_mgmt_interface_vlan_id(self):@def _find_local_mgmt_interface_vlan_id(self, interface_list):@g' /usr/lib/python3/dist-packages/sysinv/conductor/manager.py
  sed -i 's@interface_list = self.dbapi.iinterface_get_all(host_id, expunge=True)@@g' /usr/lib/python3/dist-packages/sysinv/conductor/manager.py
  sed -i 's@vlan_id = self._find_local_mgmt_interface_vlan_id()@vlan_id = self._find_local_mgmt_interface_vlan_id(iinterfaces)@g' /usr/lib/python3/dist-packages/sysinv/conductor/manager.py
  # missing /etc/platform/worker_reserved.conf
cp /usr/share/debian-integration/worker_reserved.conf /etc/platform/worker_reserved.conf


  touch ${bifile}
fi

# BI 36: first puppet runtime apply
bifile='/home/sysadmin/.bi36'
if [ ! -f ${bifile} ]; then
  # kdump service missing, disable kdump config
  sed -i 's@include ::platform::config::kdump@@g' /usr/share/puppet/modules/platform/manifests/config.pp

  touch ${bifile}
fi

# BI 40: workaround located at bootstrap section

# BI 48: fm service
sed -i 's@/etc/rc.d/init.d/fm-api@/etc/init.d/fm-api@g' /lib/systemd/system/fm-api.service
sed -i 's@/etc/rc.d/init.d/fminit@/etc/init.d/fminit@g' /lib/systemd/system/fminit.service
cp /usr/bin/fm* /usr/local/bin/
chmod 644 /etc/fm/fm.conf
systemctl daemon-reload

# BI 50: postgres configuration issue
sed -i 's@#listen_addresses = '\''localhost'\''@listen_addresses = '\''*'\''@g' /etc/postgresql/13/main/postgresql.conf
echo "host    all             all             0.0.0.0/0               md5" >> /etc/postgresql/13/main/pg_hba.conf

# BI 38.b: slow rpc calls.
echo "jit = off" >> /etc/postgresql/13/main/postgresql.conf

# BI 52: stevedore + python 3.9
cp /usr/share/debian-integration/helm.py.patched /usr/lib/python3/dist-packages/sysinv/helm/helm.py

# BI 53: intermittent armada not ready in 30 seconds
sed -i 's@async_timeout: 30@async_timeout: 120@g' /usr/share/ansible/stx-ansible/playbooks/roles/bootstrap/bringup-essential-services/tasks/main.yml
sed -i 's@async_retries: 10@async_retries: 40@g' /usr/share/ansible/stx-ansible/playbooks/roles/bootstrap/bringup-essential-services/tasks/main.yml

# BI 60:
sed -i 's@^ordering@#ordering@g' /etc/puppet/puppet.conf

# BI 58: LVM
sed -i "s/args = \[]/args = \['-y', '-Wy', '-Zy']/g" /usr/share/puppet/modules.available/puppet-lvm/lib/puppet/provider/logical_volume/lvm.rb

# BI 61:
systemctl stop docker-registry
