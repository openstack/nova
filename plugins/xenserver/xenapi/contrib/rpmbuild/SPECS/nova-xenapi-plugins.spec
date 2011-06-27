Name:           nova-xenapi-plugins
Version:        1.0
Release:        1
Summary:        Files for XenAPI support.
License:        Apache
Group:          Applications/Utilities
Source0:        nova-xenapi-plugins.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

%define debug_package %{nil}

%description
This package contains files that are required for XenAPI support for OpenStack.

%prep
%setup -q -n nova-xenapi-plugins

%install
rm -rf $RPM_BUILD_ROOT
mkdir -p $RPM_BUILD_ROOT/etc
cp -r xapi.d $RPM_BUILD_ROOT/etc
chmod u+x $RPM_BUILD_ROOT/etc/xapi.d/plugins/objectstore
#%{_fixperms} $RPM_BUILD_ROOT/*

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
/etc/xapi.d/plugins/agent
/etc/xapi.d/plugins/glance
/etc/xapi.d/plugins/migration
/etc/xapi.d/plugins/objectstore
/etc/xapi.d/plugins/pluginlib_nova.py
/etc/xapi.d/plugins/xenhost
/etc/xapi.d/plugins/xenstore.py
