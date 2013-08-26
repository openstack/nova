Name:           openstack-xen-plugins
Version:        2012.1
Release:        1
Summary:        Files for XenAPI support.
License:        ASL 2.0
Group:          Applications/Utilities
Source0:        openstack-xen-plugins.tar.gz
BuildArch:      noarch
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

%define debug_package %{nil}

%description
This package contains files that are required for XenAPI support for OpenStack.

%prep
%setup -q -n openstack-xen-plugins

%install
rm -rf $RPM_BUILD_ROOT
mkdir -p $RPM_BUILD_ROOT/etc
cp -r xapi.d $RPM_BUILD_ROOT/etc
chmod a+x $RPM_BUILD_ROOT/etc/xapi.d/plugins/*

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
/etc/xapi.d/plugins/_bittorrent_seeder
/etc/xapi.d/plugins/agent
/etc/xapi.d/plugins/bandwidth
/etc/xapi.d/plugins/bittorrent
/etc/xapi.d/plugins/config_file
/etc/xapi.d/plugins/console
/etc/xapi.d/plugins/glance
/etc/xapi.d/plugins/ipxe
/etc/xapi.d/plugins/kernel
/etc/xapi.d/plugins/migration
/etc/xapi.d/plugins/pluginlib_nova.py
/etc/xapi.d/plugins/workarounds
/etc/xapi.d/plugins/xenhost
/etc/xapi.d/plugins/xenstore.py
/etc/xapi.d/plugins/utils.py
