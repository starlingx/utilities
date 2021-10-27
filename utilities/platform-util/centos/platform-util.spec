Summary: platform-util
Name: platform-util
Version: 1.0
Release: %{tis_patch_ver}%{?_tis_dist}
License: Apache-2.0
Group: base
Packager: Wind River <info@windriver.com>
URL: unknown
BuildArch: noarch
Source: %name-%version.tar.gz

BuildRequires: python-setuptools
BuildRequires: python2-pip
BuildRequires: python2-wheel

%global _buildsubdir %{_builddir}/%{name}-%{version}

%description
Platform utilities

%package controller
Summary: Controller platform utilities
Requires: genisoimage

%description controller
Platform utilities installed only on controllers

%package noncontroller
Summary: non controller platform utilities

%description noncontroller
Platform utilities that don't get packaged on controller hosts

%define local_dir /usr/local
%define local_bindir %{local_dir}/bin
%define local_sbindir %{local_dir}/sbin
%define pythonroot /usr/lib64/python2.7/site-packages
%define local_etc_initd %{_sysconfdir}/init.d

%prep
%setup

%build
%{__python} setup.py build
%py2_build_wheel

%install


%{__python} setup.py install --root=$RPM_BUILD_ROOT \
                             --install-lib=%{pythonroot} \
                             --prefix=/usr \
                             --install-data=/usr/share \
                             --single-version-externally-managed

mkdir -p $RPM_BUILD_ROOT/wheels
install -m 644 dist/*.whl $RPM_BUILD_ROOT/wheels/

install -d %{buildroot}%{local_bindir}
install %{_buildsubdir}/scripts/tc_setup.sh %{buildroot}%{local_bindir}
install %{_buildsubdir}/scripts/remotelogging_tc_setup.sh %{buildroot}%{local_bindir}
install %{_buildsubdir}/scripts/connectivity_test %{buildroot}%{local_bindir}
install -m 555 %{_buildsubdir}/scripts/is-rootdisk-device.sh %{buildroot}%{local_bindir}
install -m 555 %{_buildsubdir}/scripts/update-iso.sh %{buildroot}%{local_bindir}
install -m 555 %{_buildsubdir}/scripts/gen-bootloader-iso.sh %{buildroot}%{local_bindir}
install -m 555 %{_buildsubdir}/scripts/stx-iso-utils.sh %{buildroot}%{local_bindir}
install -m 555 %{_buildsubdir}/scripts/show-certs.sh %{buildroot}%{local_bindir}
install -m 555 %{_buildsubdir}/scripts/update_docker_registry_auth.sh %{buildroot}%{local_bindir}
install -m 555 %{_buildsubdir}/scripts/change_system_private_registry.sh %{buildroot}%{local_bindir}

install -d %{buildroot}%{local_etc_initd}
install %{_buildsubdir}/scripts/log_functions.sh %{buildroot}%{local_etc_initd}

install -d %{buildroot}%{local_sbindir}
install -m 700 -P -D %{_buildsubdir}/scripts/patch-restart-mtce %{buildroot}%{local_sbindir}
install -m 700 -p -D %{_buildsubdir}/scripts/patch-restart-processes %{buildroot}%{local_sbindir}
install -m 700 -p -D %{_buildsubdir}/scripts/patch-restart-haproxy %{buildroot}%{local_sbindir}

install -d %{buildroot}/etc/systemd/system
install -m 644 -p -D %{_buildsubdir}/scripts/opt-platform.mount %{buildroot}/etc/systemd/system
install -m 644 -p -D %{_buildsubdir}/scripts/opt-platform.service %{buildroot}/etc/systemd/system

install -m 750 %{_buildsubdir}/scripts/set_keystone_user_option.sh %{buildroot}%{local_bindir}

# Mask the systemd ctrl-alt-delete.target, to disable reboot on ctrl-alt-del
ln -sf /dev/null %{buildroot}/etc/systemd/system/ctrl-alt-del.target

%clean
rm -rf $RPM_BUILD_ROOT

%post noncontroller
mkdir -p /opt/platform
systemctl enable opt-platform.service

%files
%license LICENSE
%defattr(-,root,root,-)
/usr/bin/verify-license
%{local_bindir}/tc_setup.sh
%{local_bindir}/remotelogging_tc_setup.sh
%{local_bindir}/connectivity_test
%{local_bindir}/is-rootdisk-device.sh
%{local_bindir}/set_keystone_user_option.sh
%{local_sbindir}/patch-restart-mtce
%{local_sbindir}/patch-restart-processes
%{local_sbindir}/patch-restart-haproxy
/etc/systemd/system/ctrl-alt-del.target
%dir %{pythonroot}/platform_util
%{pythonroot}/platform_util/*
%dir %{pythonroot}/platform_util-%{version}.0-py2.7.egg-info
%{pythonroot}/platform_util-%{version}.0-py2.7.egg-info/*
%{local_etc_initd}/log_functions.sh

%files controller
%defattr(-,root,root,-)
%{local_bindir}/update-iso.sh
%{local_bindir}/gen-bootloader-iso.sh
%{local_bindir}/stx-iso-utils.sh
%{local_bindir}/show-certs.sh
%{local_bindir}/update_docker_registry_auth.sh
%{local_bindir}/change_system_private_registry.sh

%files noncontroller
%defattr(-,root,root,-)
# This is necessary to mask opt-platform.mount, so that the version generated
# from parsing the fstab is not used by systemd.
/etc/systemd/system/opt-platform.mount
/etc/systemd/system/opt-platform.service

%package wheels
Summary: %{name} wheels

%description wheels
Contains python wheels for %{name}

%files wheels
/wheels/*
