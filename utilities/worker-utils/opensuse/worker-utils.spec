Summary: Initial worker node resource reservation and misc. utilities
Name: worker-utils
Version: 1.0
Release: %{tis_patch_ver}%{?_tis_dist}
License: Apache-2.0
Group: System/Base
URL: https://opendev.org/starlingx/utilities
Source0: %{name}-%{version}.tar.gz
BuildArch: noarch

BuildRequires: systemd
BuildRequires: systemd-sysvinit
BuildRequires: sysvinit-tools
BuildRequires: insserv-compat
BuildRequires: python3
Requires: systemd
Requires: systemd-sysvinit
Requires: sysvinit-tools
Requires: insserv-compat
Requires: python3

%description
Initial worker node resource reservation and miscellaneous utilities for StarlingX.

%define local_bindir /usr/bin/
%define local_etc_initd /etc/init.d/
%define local_etc_platform /etc/platform/
%define local_etc_goenabledd /etc/goenabled.d/

%define debug_package %{nil}

%prep
%setup -n %{name}-%{version}/%{name}

%build
make

%install
make install BINDIR=%{buildroot}%{local_bindir} \
     INITDDIR=%{buildroot}%{local_etc_initd} \
     GOENABLEDDIR=%{buildroot}%{local_etc_goenabledd} \
     PLATFORMCONFDIR=%{buildroot}%{local_etc_platform} \
     SYSTEMDDIR=%{buildroot}%{_unitdir}

%pre
%service_add_pre affine-platform.sh.service affine-tasks.service

%post
%service_add_post affine-platform.sh.service affine-tasks.service
systemctl enable affine-platform.sh.service #>/dev/null 2>&1
systemctl enable affine-tasks.service #>/dev/null 2>&1

%preun
%service_del_preun affine-platform.sh.service affine-tasks.service

%postun
%service_del_postun affine-platform.sh.service affine-tasks.service
%insserv_cleanup

%files

%defattr(-,root,root,-)

%{local_bindir}/*
%{local_etc_initd}/*
%{local_etc_goenabledd}/*
%dir %{_sysconfdir}/goenabled.d
%dir %{_sysconfdir}/platform
%config(noreplace) %{local_etc_platform}/worker_reserved.conf

%{_unitdir}/affine-platform.sh.service
%{_unitdir}/affine-tasks.service

%changelog
