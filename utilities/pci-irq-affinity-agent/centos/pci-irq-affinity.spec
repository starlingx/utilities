Summary: StarlingX PCI Interrupt Affinity Agent Package
Name: pci-irq-affinity-agent
Version: 1.0
Release: %{tis_patch_ver}%{?_tis_dist}
License: Apache-2.0
Group: base
Packager: StarlingX
URL: unknown

Source0: %{name}-%{version}.tar.gz

Requires:   python-novaclient
BuildRequires: python-setuptools
BuildRequires: systemd-devel
BuildRequires: python2-wheel

%description
StarlingX PCI Interrupt Affinity Agent Package

%define local_etc_initd /etc/init.d/
%define local_etc_pmond /etc/pmon.d/
%define pythonroot           /usr/lib64/python2.7/site-packages
%define debug_package %{nil}

%prep
%setup

# Remove bundled egg-info
rm -rf *.egg-info

%build
%{__python} setup.py build
%{__python} setup.py bdist_wheel

%install
mkdir -p $RPM_BUILD_ROOT/wheels
%{__install}  -m 644 dist/*.whl $RPM_BUILD_ROOT/wheels/

%{__install}  -d  %{buildroot}%{_bindir}
%{__install}  -p -D -m 755 nova-sriov %{buildroot}%{_bindir}/nova-sriov

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%doc LICENSE
%{_bindir}/nova-sriov

%package wheels
Summary: %{name} wheels

%description wheels
Contains python wheels for %{name}

%files wheels
/wheels/*
