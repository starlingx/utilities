# UAR 20: lvm.conf issue
sed -i "s@match => '\^\[ ]\*global_filter =',@match => '\^\[ \\\t]\*#? ?global_filter =',@g" /usr/share/puppet/modules/platform/manifests/worker.pp
sed -i "s@match => '\^\[ ]\*global_filter =',@match => '\^\[ \\\t]\*#? ?global_filter =',@g" /usr/share/puppet/modules/platform/manifests/lvm.pp

# UAR 10: disable
find /etc/puppet/manifests -type f -exec \
  sed -i 's@include ::platform::ptp@#include ::platform::ptp@g' {} +
#find /etc/puppet/manifests -type f -exec \
#  sed -i 's@include ::platform::ptpinstance@#include ::platform::ptpinstance@g' {} +
 
# UAR 16: fix in updated BI 34  
 
# UAR 17: not reproducible anymore

# UAR 28: not a fix
sed -i "s@command => 'reboot',@command => 'ls'@g" /usr/share/puppet/modules/platform/manifests/compute.pp
 
# UAR 29: moved the workaround to bootstrap issues section
 
# UAR 30: sm lighttpd
sed -i 's@ /www/tmp@ /var/www/tmp@g' /etc/init.d/lighttpd
mkdir -p /var/www/dev
touch /var/www/dev/null
chmod +777 /var/www/dev/null

