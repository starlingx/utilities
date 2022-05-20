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

