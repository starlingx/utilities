Summary: Management of /var/log filesystem
Name: logmgmt
Version: 1.0
Release: %{tis_patch_ver}%{?_tis_dist}
License: Apache-2.0
Group: base
Packager: Wind River <info@windriver.com>
URL: unknown
Source0: %{name}-%{version}.tar.gz
Source1: LICENSE

BuildRequires: python3-setuptools
BuildRequires: python3-pip
BuildRequires: python3-wheel
BuildRequires: systemd-devel
BuildRequires: python3-devel
Requires: systemd
Requires: python3-daemon

%description
Management of /var/log filesystem

%define local_bindir /usr/bin/
%define local_etc_initd /etc/init.d/
%define local_etc_pmond /etc/pmon.d/
%define pythonroot %{python3_sitearch}

%define debug_package %{nil}

%prep
%setup

# Remove bundled egg-info
rm -rf *.egg-info

%build
%{__python3} setup.py build
%{__python3} setup.py bdist_wheel

%install
%{__python3} setup.py install --root=$RPM_BUILD_ROOT \
                             --install-lib=%{pythonroot} \
                             --prefix=/usr \
                             --install-data=/usr/share \
                             --single-version-externally-managed
mkdir -p $RPM_BUILD_ROOT/wheels
install -m 644 dist/*.whl $RPM_BUILD_ROOT/wheels/

install -d -m 755 %{buildroot}%{local_bindir}
install -p -D -m 700 scripts/bin/logmgmt %{buildroot}%{local_bindir}/logmgmt
install -p -D -m 700 scripts/bin/logmgmt_postrotate %{buildroot}%{local_bindir}/logmgmt_postrotate
install -p -D -m 700 scripts/bin/logmgmt_prerotate %{buildroot}%{local_bindir}/logmgmt_prerotate

install -d -m 755 %{buildroot}%{local_etc_initd}
install -p -D -m 700 scripts/init.d/logmgmt %{buildroot}%{local_etc_initd}/logmgmt

install -d -m 755 %{buildroot}%{local_etc_pmond}
install -p -D -m 644 scripts/pmon.d/logmgmt %{buildroot}%{local_etc_pmond}/logmgmt

install -p -D -m 644 scripts/etc/systemd/system/logmgmt.service %{buildroot}%{_unitdir}/logmgmt.service

%post
/usr/bin/systemctl enable logmgmt.service >/dev/null 2>&1

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%doc LICENSE
%{local_bindir}/*
%{local_etc_initd}/*
%dir %{local_etc_pmond}
%{local_etc_pmond}/*
%{_unitdir}/logmgmt.service
%dir %{pythonroot}/%{name}
%{pythonroot}/%{name}/*
%dir %{pythonroot}/%{name}-%{version}.0-py3.6.egg-info
%{pythonroot}/%{name}-%{version}.0-py3.6.egg-info/*

%package wheels
Summary: %{name} wheels

%description wheels
Contains python wheels for %{name}

%files wheels
/wheels/*
