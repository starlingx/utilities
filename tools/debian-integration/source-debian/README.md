VM steps:
- boot iso
- copy workarounds to /home/sysadmin
- generate /home/sysadmin/localhost.yml (with dns_servers entry)
- run before_bootstrap_workarounds.sh
- run bootstrap
- generate /home/sysadmin/interfaces file
- run after_bootstrap_workarounds.sh
- unlock

HW steps:
- boot iso
- copy workarounds to /home/sysadmin
- generate /home/sysadmin/localhost.yml (with dns_servers entry)
- run before_bootstrap_workarounds.sh
- run bootstrap
- generate /home/sysadmin/interfaces file
- run after_bootstrap_workarounds.sh
- unlock
