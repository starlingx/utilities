# UAR 9: disable
find /etc/puppet/manifests -type f -exec \
  sed -i 's@include ::platform::ntp@#include ::platform::ntp@g' {} +
 
# UAR 10: disable
find /etc/puppet/manifests -type f -exec \
  sed -i 's@include ::platform::ptp@#include ::platform::ptp@g' {} +
#find /etc/puppet/manifests -type f -exec \
#  sed -i 's@include ::platform::ptpinstance@#include ::platform::ptpinstance@g' {} +
 
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
