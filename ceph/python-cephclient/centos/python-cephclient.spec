Summary: Handle Ceph API calls and provide status updates via alarms
Name: python-cephclient
Version: 13.2.2.0
Release: %{tis_patch_ver}%{?_tis_dist}
License: Apache-2.0
Group: base
Packager: Wind River <info@windriver.com>
URL: https://github.com/openstack/stx-integ/tree/master/ceph/python-cephclient/python-cephclient'
Source0: %{name}-%{version}.tar.gz

BuildArch: noarch

BuildRequires: python3
BuildRequires: python3-pip
BuildRequires: python3-wheel

Requires: python3
Requires: python3-six
Requires: python3-requests

Provides: python-cephclient

%description
A client library in Python for Ceph Mgr RESTful plugin providing REST API
access to the cluster over an SSL-secured connection. Python API is compatible
with the old Python Ceph client at
https://github.com/dmsimard/python-cephclient that no longer works in Ceph
mimic because Ceph REST API component was removed.

%define debug_package %{nil}

%prep
%autosetup -p 1 -n %{name}-%{version}

rm -rf .pytest_cache
rm -rf python_cephclient.egg-info
rm -f requirements.txt

%build
%{__python3} setup.py build
%{__python3} setup.py bdist_wheel

%install
%{__python3} setup.py install --skip-build --root %{buildroot}
mkdir -p $RPM_BUILD_ROOT/wheels
install -m 644 dist/*.whl $RPM_BUILD_ROOT/wheels/

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%license LICENSE
%{python3_sitelib}/cephclient
%{python3_sitelib}/*.egg-info

%package wheels
Summary: %{name} wheels

%description wheels
Contains python wheels for %{name}

%files wheels
/wheels/*
