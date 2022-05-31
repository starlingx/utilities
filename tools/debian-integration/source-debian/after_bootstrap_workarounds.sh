# UAR 20: lvm.conf issue
sed -i "s@match => '\^\[ ]\*global_filter =',@match => '\^\[ \\\t]\*#? ?global_filter =',@g" /usr/share/puppet/modules/platform/manifests/worker.pp
sed -i "s@match => '\^\[ ]\*global_filter =',@match => '\^\[ \\\t]\*#? ?global_filter =',@g" /usr/share/puppet/modules/platform/manifests/lvm.pp

# UAR 10: disable
find /etc/puppet/manifests -type f -exec \
  sed -i 's@include ::platform::ptp@#include ::platform::ptp@g' {} +
#find /etc/puppet/manifests -type f -exec \
#  sed -i 's@include ::platform::ptpinstance@#include ::platform::ptpinstance@g' {} +
