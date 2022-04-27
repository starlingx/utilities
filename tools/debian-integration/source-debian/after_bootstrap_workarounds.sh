# UBR 2: don't start collectd
bifile='/home/sysadmin/.ubr2'
if [ ! -f ${bifile} ]; then
  sed -i '53,56d' /usr/share/puppet/modules/platform/manifests/collectd.pp
  touch ${bifile}
fi

# UAR 8: nslcd
sed -i 's@gid ldap@gid openldap@g' /etc/nslcd.conf
 
# UAR 9: disable
find /etc/puppet/manifests -type f -exec \
  sed -i 's@include ::platform::ntp@#include ::platform::ntp@g' {} +
 
# UAR 10: disable
find /etc/puppet/manifests -type f -exec \
  sed -i 's@include ::platform::ptp@#include ::platform::ptp@g' {} +
#find /etc/puppet/manifests -type f -exec \
#  sed -i 's@include ::platform::ptpinstance@#include ::platform::ptpinstance@g' {} +
 
# UAR 12: disable
find /etc/puppet/manifests -type f -exec \
  sed -i 's@include ::platform::multipath@#include ::platform::multipath@g' {} +
 
# UAR 13: disable
find /usr/share/puppet/modules/platform -type f -exec \
  sed -i 's@require ::platform::compute::machine@#require ::platform::compute::machine@g' {} +
# UAR 14: disable
find /usr/share/puppet/modules/platform -type f -exec \
  sed -i 's@require ::platform::compute::kvm_timer_advance@#require ::platform::compute::kvm_timer_advance@g' {} +
 
# UAR 16: fix in updated BI 34  
 
# UAR 17: not reproducible anymore

# UAR 18: backup-lv already mounted
sed -i '113 a \ \ \ \ -> exec { "workaround: umount ${device}":\
\ \ \ \ \ \ command => "umount ${mountpoint}; sleep 2",\
\ \ \ \ \ \ path    => "/usr/bin"\
\ \ \ \ }' /usr/share/puppet/modules/platform/manifests/filesystem.pp
sed -i '125 a \ \ \ \ -> exec { "second mount ${device}":\
\ \ \ \ \ \ unless  => "mount | awk '\''{print \$3}'\'' | grep -Fxq -e /var/rootdirs${mountpoint} -e ${mountpoint}",\
\ \ \ \ \ \ command => "mount ${mountpoint} || true",\
\ \ \ \ \ \ path    => "/usr/bin",\
\ \ \ \ }' /usr/share/puppet/modules/platform/manifests/filesystem.pp

# UAR 20: lvm.conf issue
sed -i "s@match => '\^\[ ]\*global_filter =',@match => '\^\[ \\\t]\*#? ?global_filter =',@g" /usr/share/puppet/modules/platform/manifests/worker.pp
sed -i "s@match => '\^\[ ]\*global_filter =',@match => '\^\[ \\\t]\*#? ?global_filter =',@g" /usr/share/puppet/modules/platform/manifests/lvm.pp
   
# UAR 21:
bifile='/home/sysadmin/.uar21'
if [ ! -f ${bifile} ]; then
  sed -i "s@random: '--random',@random: '--random-fully',@g" /usr/share/puppet/modules.available/puppetlabs-firewall/lib/puppet/provider/firewall/iptables.rb
  touch ${bifile}
fi
 
# UAR 24:
sed -i 's@  \$ha_primary.*= false,@  \$ha_primary     = true,@g' /usr/share/puppet/modules/drbd/manifests/resource.pp
sed -i 's@  \$ha_primary.*= false,@  \$ha_primary     = true,@g' /usr/share/puppet/modules/platform/manifests/drbd.pp
sed -i 's@  \$automount.*= false,@  \$automount     = true,@g' /usr/share/puppet/modules/platform/manifests/drbd.pp
systemctl daemon-reload
 
 
# UAR 25:
sed -i 's@/etc/sysconfig/kubelet@/etc/default/kubelet@g' /usr/share/puppet/modules/platform/manifests/kubernetes.pp 
 
# UAR 26: not a fix
bifile='/home/sysadmin/.uar26'
if [ ! -f ${bifile} ]; then
  A=$(grep -Rn "Create \\$" /usr/share/puppet/modules/platform/manifests/kubernetes.pp | head -1 | awk -F':' '{print $1}')
  A=$((A + 1))
  B=$((A + 39))
  sed -i ${A}','${B}'d ' /usr/share/puppet/modules/platform/manifests/kubernetes.pp
  touch ${bifile}
fi
 
# UAR 28: not a fix
sed -i "s@command => 'reboot',@command => 'ls'@g" /usr/share/puppet/modules/platform/manifests/compute.pp
 
# UAR 29: moved the workaround to bootstrap issues section
 
# UAR 30: sm lighttpd
sed -i 's@ /www/tmp@ /var/www/tmp@g' /etc/init.d/lighttpd
mkdir -p /var/www/dev
touch /var/www/dev/null
chmod +777 /var/www/dev/null
 
# UAR 32: sm rabbit
bifile='/home/sysadmin/.uar32'
if [ ! -f ${bifile} ]; then
  sed -i 's@2)@2|69)@g' /usr/lib/ocf/resource.d/rabbitmq/stx.rabbitmq-server
 
  A=$(grep -Rn "\$RABBITMQ_CTL stop \$RABBITMQ_PID_FILE" /usr/lib/ocf/resource.d/rabbitmq/stx.rabbitmq-server | head -1 | awk -F':' '{print $1}')
  A=$((A - 1))
  sed -i ${A}' a \ \ \ \ touch $RABBITMQ_PID_FILE' /usr/lib/ocf/resource.d/rabbitmq/stx.rabbitmq-server
  touch ${bifile}
fi
 
# UAR 33:
bifile='/home/sysadmin/.uar33'
if [ ! -f ${bifile} ]; then
  sed -i '26d' /usr/share/puppet/modules/rabbitmq/templates/rabbitmq.config.erb
  sed -i '22d' /usr/share/puppet/modules/rabbitmq/templates/rabbitmq.config.erb
  sed -i '11d' /usr/share/puppet/modules/rabbitmq/templates/rabbitmq.config.erb
  sed -i '10 a \ \ \ \ {loopback_users, []},' /usr/share/puppet/modules/rabbitmq/templates/rabbitmq.config.erb
  touch ${bifile}
fi

# UAR 43: haproxy
A=$(grep -Rn "reqadd" /usr/share/puppet/modules/platform/manifests/haproxy.pp | awk -F':' '{print $1}')
B=$((A + 0))
sed -i ${A}','${B}'d ' /usr/share/puppet/modules/platform/manifests/haproxy.pp
A=$(grep -Rn "rspadd" /usr/share/puppet/modules/platform/manifests/haproxy.pp | awk -F':' '{print $1}')
B=$((A + 0))
sed -i ${A}','${B}'d ' /usr/share/puppet/modules/platform/manifests/haproxy.pp


# UAR 50.a ceph
bifile='/home/sysadmin/.uar_ceph_1'
if [ ! -f ${bifile} ]; then
  sed -i 's@pstack \$pid@eu-stack -p \$pid@g' /etc/init.d/ceph-init-wrapper
  sed -i 's@LIBDIR=/usr/lib64/ceph@LIBDIR=/usr/lib/ceph@g' /etc/init.d/ceph-init-wrapper
  sed -i 's@LIBDIR=/usr/lib64/ceph@LIBDIR=/usr/lib/ceph@g' /etc/init.d/ceph
  systemctl disable radosgw   # do we need this ?
  chown -R root:root /var/lib/ceph/
  deluser ceph

  touch ${bifile}
fi

# UAR 50.b platform-integ-apps apply
bifile='/home/sysadmin/.uar_50b'
if [ ! -f ${bifile} ]; then
  # nfv kubernetes
  sed -i 's@c = kubernetes.client.Configuration()$@c = kubernetes.client.Configuration().get_default_copy()@g' /usr/lib/python3/dist-packages/nfv_plugins/nfvi_plugins/clients/kubernetes_client.py
 
  # Disable patching audit
  A=$(grep -Rn "def _check_patching_operation" /usr/lib/python3/dist-packages/sysinv/api/controllers/v1/kube_app.py | tail -n 1 | awk -F':' '{print $1}')
  if [[ ! -z "$A" ]]; then
    sed -i ${A}' a \ \ \ \ \ \ \ \ return None' /usr/lib/python3/dist-packages/sysinv/api/controllers/v1/kube_app.py
  fi
  systemctl restart sysinv-conductor

  touch ${bifile}
fi

# UAR 52.a
cp /usr/bin/guest* /usr/local/bin/
# UAR 52.b
mv /etc/pmon.d/pci-irq-affinity-agent.conf /home/sysadmin/
systemctl disable pci-irq-affinity-agent

 
