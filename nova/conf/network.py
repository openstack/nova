# Copyright 2016 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Config options for the nova-network service and related services."""

# NOTE(sfinucan): Don't make any non-bugfix changes to this file, as every
# single option found here will be removed in a future release.

from oslo_config import cfg

from nova.conf import paths

network_opts = [
    cfg.BoolOpt('use_neutron',
        default=True,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Enable neutron as the backend for networking.

Determine whether to use Neutron or Nova Network as the back end. Set to true
to use neutron.
"""),
    # TODO(sfinucan): This option is tied into the XenAPI, VMWare and Libvirt
    # drivers.
    # We should remove this dependency by either adding a new opt for each
    # driver or simply removing the offending code. Until then we cannot
    # deprecate this option.
    cfg.BoolOpt("flat_injected",
        default=False,
        help="""
This option determines whether the network setup information is injected into
the VM before it is booted. While it was originally designed to be used only
by nova-network, it is also used by the vmware and xenapi virt drivers to
control whether network information is injected into a VM. The libvirt virt
driver also uses it when we use config_drive to configure network to control
whether network information is injected into a VM.
"""),
    cfg.StrOpt("flat_network_bridge",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines the bridge used for simple network interfaces when no
bridge is specified in the VM creation request.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment.

Possible values:

* Any string representing a valid network bridge, such as 'br100'

Related options:

* ``use_neutron``
"""),
    cfg.StrOpt("flat_network_dns",
        default="8.8.4.4",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is the address of the DNS server for a simple network. If this option is
not specified, the default of '8.8.4.4' is used.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment.

Possible values:

* Any valid IP address.

Related options:

* ``use_neutron``
"""),
    cfg.StrOpt("flat_interface",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option is the name of the virtual interface of the VM on which the bridge
will be built. While it was originally designed to be used only by
nova-network, it is also used by libvirt for the bridge interface name.

Possible values:

* Any valid virtual interface name, such as 'eth0'
"""),
    cfg.IntOpt("vlan_start",
        default=100,
        min=1,
        max=4094,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is the VLAN number used for private networks. Note that the when creating
the networks, if the specified number has already been assigned, nova-network
will increment this number until it finds an available VLAN.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment. It also will be ignored if the configuration option
for `network_manager` is not set to the default of
'nova.network.manager.VlanManager'.

Possible values:

* Any integer between 1 and 4094. Values outside of that range will raise a
  ValueError exception.

Related options:

* ``network_manager``
* ``use_neutron``
"""),
    cfg.StrOpt("vlan_interface",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options. While
this option has an effect when using neutron, it incorrectly override the value
provided by neutron and should therefore not be used.
""",
        help="""
This option is the name of the virtual interface of the VM on which the VLAN
bridge will be built. While it was originally designed to be used only by
nova-network, it is also used by libvirt and xenapi for the bridge interface
name.

Please note that this setting will be ignored in nova-network if the
configuration option for `network_manager` is not set to the default of
'nova.network.manager.VlanManager'.

Possible values:

* Any valid virtual interface name, such as 'eth0'
"""),
    cfg.IntOpt("num_networks",
        default=1,
        min=1,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option represents the number of networks to create if not explicitly
specified when the network is created. The only time this is used is if a CIDR
is specified, but an explicit network_size is not. In that case, the subnets
are created by diving the IP address space of the CIDR by num_networks. The
resulting subnet sizes cannot be larger than the configuration option
`network_size`; in that event, they are reduced to `network_size`, and a
warning is logged.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment.

Possible values:

* Any positive integer is technically valid, although there are practical
  limits based upon available IP address space and virtual interfaces.

Related options:

* ``use_neutron``
* ``network_size``
"""),
    cfg.StrOpt("vpn_ip",
        default="$my_ip",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option is no longer used since the /os-cloudpipe API was removed in the
16.0.0 Pike release. This is the public IP address for the cloudpipe VPN
servers. It defaults to the IP address of the host.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment. It also will be ignored if the configuration option
for `network_manager` is not set to the default of
'nova.network.manager.VlanManager'.

Possible values:

* Any valid IP address. The default is ``$my_ip``, the IP address of the VM.

Related options:

* ``network_manager``
* ``use_neutron``
* ``vpn_start``
"""),
    cfg.PortOpt("vpn_start",
        default=1000,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is the port number to use as the first VPN port for private networks.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment. It also will be ignored if the configuration option
for `network_manager` is not set to the default of
'nova.network.manager.VlanManager', or if you specify a value the 'vpn_start'
parameter when creating a network.

Possible values:

* Any integer representing a valid port number. The default is 1000.

Related options:

* ``use_neutron``
* ``vpn_ip``
* ``network_manager``
"""),
    cfg.IntOpt("network_size",
        default=256,
        min=1,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines the number of addresses in each private subnet.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment.

Possible values:

* Any positive integer that is less than or equal to the available network
  size. Note that if you are creating multiple networks, they must all fit in
  the available IP address space. The default is 256.

Related options:

* ``use_neutron``
* ``num_networks``
"""),
    cfg.StrOpt("fixed_range_v6",
        default="fd00::/48",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines the fixed IPv6 address block when creating a network.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment.

Possible values:

* Any valid IPv6 CIDR

Related options:

* ``use_neutron``
"""),
    cfg.StrOpt("gateway",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is the default IPv4 gateway. It is used only in the testing suite.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment.

Possible values:

* Any valid IP address.

Related options:

* ``use_neutron``
* ``gateway_v6``
"""),
    cfg.StrOpt("gateway_v6",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is the default IPv6 gateway. It is used only in the testing suite.

Please note that this option is only used when using nova-network instead of
Neutron in your deployment.

Possible values:

* Any valid IP address.

Related options:

* ``use_neutron``
* ``gateway``
"""),
    cfg.IntOpt("cnt_vpn_clients",
        default=0,
        min=0,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option represents the number of IP addresses to reserve at the top of the
address range for VPN clients. It also will be ignored if the configuration
option for `network_manager` is not set to the default of
'nova.network.manager.VlanManager'.

Possible values:

* Any integer, 0 or greater.

Related options:

* ``use_neutron``
* ``network_manager``
"""),
    cfg.IntOpt("fixed_ip_disassociate_timeout",
        default=600,
        min=0,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is the number of seconds to wait before disassociating a deallocated fixed
IP address. This is only used with the nova-network service, and has no effect
when using neutron for networking.

Possible values:

* Any integer, zero or greater.

Related options:

* ``use_neutron``
"""),
    cfg.IntOpt("create_unique_mac_address_attempts",
        default=5,
        min=1,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines how many times nova-network will attempt to create a
unique MAC address before giving up and raising a
`VirtualInterfaceMacAddressException` error.

Possible values:

* Any positive integer. The default is 5.

Related options:

* ``use_neutron``
"""),
    cfg.BoolOpt("teardown_unused_network_gateway",
        default=False,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Determines whether unused gateway devices, both VLAN and bridge, are deleted if
the network is in nova-network VLAN mode and is multi-hosted.

Related options:

* ``use_neutron``
* ``vpn_ip``
* ``fake_network``
"""),
    cfg.BoolOpt("force_dhcp_release",
        default=True,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
When this option is True, a call is made to release the DHCP for the instance
when that instance is terminated.

Related options:

* ``use_neutron``
"""),
    cfg.BoolOpt("update_dns_entries",
        default=False,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
When this option is True, whenever a DNS entry must be updated, a fanout cast
message is sent to all network hosts to update their DNS entries in multi-host
mode.

Related options:

* ``use_neutron``
"""),
    cfg.IntOpt("dns_update_periodic_interval",
        default=-1,
        min=-1,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines the time, in seconds, to wait between refreshing DNS
entries for the network.

Possible values:

* A positive integer
* -1 to disable updates

Related options:

* ``use_neutron``
"""),
    cfg.StrOpt("dhcp_domain",
        default="novalocal",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option allows you to specify the domain for the DHCP server.

Possible values:

* Any string that is a valid domain name.

Related options:

* ``use_neutron``
"""),
    cfg.StrOpt("l3_lib",
        default="nova.network.l3.LinuxNetL3",
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option allows you to specify the L3 management library to be used.

Possible values:

* Any dot-separated string that represents the import path to an L3 networking
  library.

Related options:

* ``use_neutron``
"""),
    cfg.BoolOpt("share_dhcp_address",
        default=False,
        deprecated_for_removal=True,
        deprecated_since='2014.2',
        help="""
THIS VALUE SHOULD BE SET WHEN CREATING THE NETWORK.

If True in multi_host mode, all compute hosts share the same dhcp address. The
same IP address used for DHCP will be added on each nova-network node which is
only visible to the VMs on the same host.

The use of this configuration has been deprecated and may be removed in any
release after Mitaka. It is recommended that instead of relying on this option,
an explicit value should be passed to 'create_networks()' as a keyword argument
with the name 'share_address'.
"""),
]

linux_net_opts = [
    cfg.MultiStrOpt('dhcpbridge_flagfile',
        default=['/etc/nova/nova-dhcpbridge.conf'],
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option is a list of full paths to one or more configuration files for
dhcpbridge. In most cases the default path of '/etc/nova/nova-dhcpbridge.conf'
should be sufficient, but if you have special needs for configuring dhcpbridge,
you can change or add to this list.

Possible values

* A list of strings, where each string is the full path to a dhcpbridge
  configuration file.
"""),
    cfg.StrOpt('networks_path',
        default=paths.state_path_def('networks'),
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
The location where the network configuration files will be kept. The default is
the 'networks' directory off of the location where nova's Python module is
installed.

Possible values

* A string containing the full path to the desired configuration directory
"""),
    cfg.StrOpt('public_interface',
        default='eth0',
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is the name of the network interface for public IP addresses. The default
is 'eth0'.

Possible values:

* Any string representing a network interface name
"""),
    cfg.StrOpt('dhcpbridge',
        default=paths.bindir_def('nova-dhcpbridge'),
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
The location of the binary nova-dhcpbridge. By default it is the binary named
'nova-dhcpbridge' that is installed with all the other nova binaries.

Possible values:

* Any string representing the full path to the binary for dhcpbridge
"""),
    cfg.StrOpt('routing_source_ip',
        default='$my_ip',
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
The public IP address of the network host.

This is used when creating an SNAT rule.

Possible values:

* Any valid IP address

Related options:

* ``force_snat_range``
"""),
    cfg.IntOpt('dhcp_lease_time',
        default=86400,
        min=1,
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
The lifetime of a DHCP lease, in seconds. The default is 86400 (one day).

Possible values:

* Any positive integer value.
"""),
    cfg.MultiStrOpt("dns_server",
        default=[],
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Despite the singular form of the name of this option, it is actually a list of
zero or more server addresses that dnsmasq will use for DNS nameservers. If
this is not empty, dnsmasq will not read /etc/resolv.conf, but will only use
the servers specified in this option. If the option use_network_dns_servers is
True, the dns1 and dns2 servers from the network will be appended to this list,
and will be used as DNS servers, too.

Possible values:

* A list of strings, where each string is either an IP address or a FQDN.

Related options:

* ``use_network_dns_servers``
"""),
    cfg.BoolOpt("use_network_dns_servers",
        default=False,
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
When this option is set to True, the dns1 and dns2 servers for the network
specified by the user on boot will be used for DNS, as well as any specified in
the `dns_server` option.

Related options:

* ``dns_server``
"""),
    cfg.ListOpt("dmz_cidr",
        default=[],
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option is a list of zero or more IP address ranges in your network's DMZ
that should be accepted.

Possible values:

* A list of strings, each of which should be a valid CIDR.
"""),
    cfg.MultiStrOpt("force_snat_range",
        default=[],
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is a list of zero or more IP ranges that traffic from the
`routing_source_ip` will be SNATted to. If the list is empty, then no SNAT
rules are created.

Possible values:

* A list of strings, each of which should be a valid CIDR.

Related options:

* ``routing_source_ip``
"""),
    cfg.StrOpt("dnsmasq_config_file",
        default="",
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
The path to the custom dnsmasq configuration file, if any.

Possible values:

* The full path to the configuration file, or an empty string if there is no
  custom dnsmasq configuration file.
"""),
    cfg.StrOpt("linuxnet_interface_driver",
        default="nova.network.linux_net.LinuxBridgeInterfaceDriver",
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This is the class used as the ethernet device driver for linuxnet bridge
operations. The default value should be all you need for most cases, but if you
wish to use a customized class, set this option to the full dot-separated
import path for that class.

Possible values:

* Any string representing a dot-separated class path that Nova can import.
"""),
    cfg.StrOpt("linuxnet_ovs_integration_bridge",
        default="br-int",
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
The name of the Open vSwitch bridge that is used with linuxnet when connecting
with Open vSwitch."

Possible values:

* Any string representing a valid bridge name.
"""),
    cfg.BoolOpt("send_arp_for_ha",
        default=False,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
When True, when a device starts up, and upon binding floating IP addresses, arp
messages will be sent to ensure that the arp caches on the compute hosts are
up-to-date.

Related options:

* ``send_arp_for_ha_count``
"""),
    cfg.IntOpt("send_arp_for_ha_count",
        default=3,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
When arp messages are configured to be sent, they will be sent with the count
set to the value of this option. Of course, if this is set to zero, no arp
messages will be sent.

Possible values:

* Any integer greater than or equal to 0

Related options:

* ``send_arp_for_ha``
"""),
    cfg.BoolOpt("use_single_default_gateway",
        default=False,
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
When set to True, only the firt nic of a VM will get its default gateway from
the DHCP server.
"""),
    cfg.MultiStrOpt("forward_bridge_interface",
        default=["all"],
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
One or more interfaces that bridges can forward traffic to. If any of the items
in this list is the special keyword 'all', then all traffic will be forwarded.

Possible values:

* A list of zero or more interface names, or the word 'all'.
"""),
    cfg.StrOpt("metadata_host",
        default="$my_ip",
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines the IP address for the network metadata API server.

This is really the client side of the metadata host equation that allows
nova-network to find the metadata server when doing a default multi host
networking.

Possible values:

* Any valid IP address. The default is the address of the Nova API server.

Related options:

* ``metadata_port``
"""),
    cfg.PortOpt("metadata_port",
        default=8775,
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines the port used for the metadata API server.

Related options:

* ``metadata_host``
"""),
    cfg.StrOpt("iptables_top_regex",
        default="",
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This expression, if defined, will select any matching iptables rules and place
them at the top when applying metadata changes to the rules.

Possible values:

* Any string representing a valid regular expression, or an empty string

Related options:

* ``iptables_bottom_regex``
"""),
    cfg.StrOpt("iptables_bottom_regex",
        default="",
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This expression, if defined, will select any matching iptables rules and place
them at the bottom when applying metadata changes to the rules.

Possible values:

* Any string representing a valid regular expression, or an empty string

Related options:

* iptables_top_regex
"""),
    cfg.StrOpt("iptables_drop_action",
        default="DROP",
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
By default, packets that do not pass the firewall are DROPped. In many cases,
though, an operator may find it more useful to change this from DROP to REJECT,
so that the user issuing those packets may have a better idea as to what's
going on, or LOGDROP in order to record the blocked traffic before DROPping.

Possible values:

* A string representing an iptables chain. The default is DROP.
"""),
    cfg.IntOpt("ovs_vsctl_timeout",
        default=120,
        min=0,
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option represents the period of time, in seconds, that the ovs_vsctl calls
will wait for a response from the database before timing out. A setting of 0
means that the utility should wait forever for a response.

Possible values:

* Any positive integer if a limited timeout is desired, or zero if the calls
  should wait forever for a response.
"""),
    cfg.BoolOpt("fake_network",
        default=False,
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option is used mainly in testing to avoid calls to the underlying network
utilities.
"""),
    cfg.IntOpt("ebtables_exec_attempts",
        default=3,
        min=1,
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines the number of times to retry ebtables commands before
giving up. The minimum number of retries is 1.

Possible values:

* Any positive integer

Related options:

* ``ebtables_retry_interval``
"""),
    cfg.FloatOpt("ebtables_retry_interval",
        default=1.0,
        deprecated_for_removal=True,
        deprecated_since="16.0.0",
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
This option determines the time, in seconds, that the system will sleep in
between ebtables retries. Note that each successive retry waits a multiple of
this value, so for example, if this is set to the default of 1.0 seconds, and
ebtables_exec_attempts is 4, after the first failure, the system will sleep for
1 * 1.0 seconds, after the second failure it will sleep 2 * 1.0 seconds, and
after the third failure it will sleep 3 * 1.0 seconds.

Possible values:

* Any non-negative float or integer. Setting this to zero will result in no
  waiting between attempts.

Related options:

* ebtables_exec_attempts
"""),
]

ldap_dns_opts = [
    cfg.URIOpt('ldap_dns_url',
        default='ldap://ldap.example.com:389',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
URL for LDAP server which will store DNS entries

Possible values:

* A valid LDAP URL representing the server
"""),
    cfg.StrOpt('ldap_dns_user',
        default='uid=admin,ou=people,dc=example,dc=org',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help='Bind user for LDAP server'),
    cfg.StrOpt('ldap_dns_password',
        default='password',
        secret=True,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="Bind user's password for LDAP server"),
    cfg.StrOpt('ldap_dns_soa_hostmaster',
        default='hostmaster@example.org',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Hostmaster for LDAP DNS driver Statement of Authority

Possible values:

* Any valid string representing LDAP DNS hostmaster.
"""),
    cfg.MultiStrOpt('ldap_dns_servers',
        default=['dns.example.org'],
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
DNS Servers for LDAP DNS driver

Possible values:

* A valid URL representing a DNS server
"""),
    cfg.StrOpt('ldap_dns_base_dn',
        default='ou=hosts,dc=example,dc=org',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Base distinguished name for the LDAP search query

This option helps to decide where to look up the host in LDAP.
"""),
    cfg.IntOpt('ldap_dns_soa_refresh',
        default=1800,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Refresh interval (in seconds) for LDAP DNS driver Start of Authority

Time interval, a secondary/slave DNS server waits before requesting for
primary DNS server's current SOA record. If the records are different,
secondary DNS server will request a zone transfer from primary.

NOTE: Lower values would cause more traffic.
"""),
    cfg.IntOpt('ldap_dns_soa_retry',
        default=3600,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Retry interval (in seconds) for LDAP DNS driver Start of Authority

Time interval, a secondary/slave DNS server should wait, if an
attempt to transfer zone failed during the previous refresh interval.
"""),
    cfg.IntOpt('ldap_dns_soa_expiry',
        default=86400,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Expiry interval (in seconds) for LDAP DNS driver Start of Authority

Time interval, a secondary/slave DNS server holds the information
before it is no longer considered authoritative.
"""),
    cfg.IntOpt('ldap_dns_soa_minimum',
        default=7200,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Minimum interval (in seconds) for LDAP DNS driver Start of Authority

It is Minimum time-to-live applies for all resource records in the
zone file. This value is supplied to other servers how long they
should keep the data in cache.
"""),
]

driver_opts = [
    cfg.StrOpt('network_driver',
        default='nova.network.linux_net',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Driver to use for network creation.

Network driver initializes (creates bridges and so on) only when the
first VM lands on a host node. All network managers configure the
network using network drivers. The driver is not tied to any particular
network manager.

The default Linux driver implements vlans, bridges, and iptables rules
using linux utilities.

Note that this option is only used when using nova-network instead
of Neutron in your deployment.

Related options:

* ``use_neutron``
"""),
    cfg.StrOpt('firewall_driver',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        default='nova.virt.firewall.NoopFirewallDriver',
        help="""
Firewall driver to use with ``nova-network`` service.

This option only applies when using the ``nova-network`` service. When using
another networking services, such as Neutron, this should be to set to the
``nova.virt.firewall.NoopFirewallDriver``.

Possible values:

* ``nova.virt.firewall.IptablesFirewallDriver``
* ``nova.virt.firewall.NoopFirewallDriver``
* ``nova.virt.libvirt.firewall.IptablesFirewallDriver``
* [...]

Related options:

* ``use_neutron``: This must be set to ``False`` to enable ``nova-network``
  networking
"""),
    cfg.BoolOpt('allow_same_net_traffic',
        default=True,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Determine whether to allow network traffic from same network.

When set to true, hosts on the same subnet are not filtered and are allowed
to pass all types of traffic between them. On a flat network, this allows
all instances from all projects unfiltered communication. With VLAN
networking, this allows access between instances within the same project.

This option only applies when using the ``nova-network`` service. When using
another networking services, such as Neutron, security groups or other
approaches should be used.

Possible values:

* True: Network traffic should be allowed pass between all instances on the
  same network, regardless of their tenant and security policies
* False: Network traffic should not be allowed pass between instances unless
  it is unblocked in a security group

Related options:

* ``use_neutron``: This must be set to ``False`` to enable ``nova-network``
  networking
* ``firewall_driver``: This must be set to
  ``nova.virt.libvirt.firewall.IptablesFirewallDriver`` to ensure the
  libvirt firewall driver is enabled.
"""),
]

rpcapi_opts = [
    cfg.BoolOpt('multi_host',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Default value for multi_host in networks.

nova-network service can operate in a multi-host or single-host mode.
In multi-host mode each compute node runs a copy of nova-network and the
instances on that compute node use the compute node as a gateway to the
Internet. Where as in single-host mode, a central server runs the nova-network
service. All compute nodes forward traffic from the instances to the
cloud controller which then forwards traffic to the Internet.

If this options is set to true, some rpc network calls will be sent directly
to host.

Note that this option is only used when using nova-network instead of
Neutron in your deployment.

Related options:

* ``use_neutron``
""")
]

floating_ip_opts = [
    cfg.StrOpt('default_floating_pool',
        default='nova',
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
This option was used for two purposes: to set the floating IP pool name for
nova-network and to do the same for neutron. nova-network is deprecated, as are
any related configuration options. Users of neutron, meanwhile, should use the
'default_floating_pool' option in the '[neutron]' group.
""",
        help="""
Default pool for floating IPs.

This option specifies the default floating IP pool for allocating floating IPs.

While allocating a floating ip, users can optionally pass in the name of the
pool they want to allocate from, otherwise it will be pulled from the
default pool.

If this option is not set, then 'nova' is used as default floating pool.

Possible values:

* Any string representing a floating IP pool name
"""),
    cfg.BoolOpt('auto_assign_floating_ip',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Autoassigning floating IP to VM

When set to True, floating IP is auto allocated and associated
to the VM upon creation.

Related options:

* use_neutron: this options only works with nova-network.
"""),
   cfg.StrOpt('floating_ip_dns_manager',
        default='nova.network.noop_dns_driver.NoopDNSDriver',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Full class name for the DNS Manager for floating IPs.

This option specifies the class of the driver that provides functionality
to manage DNS entries associated with floating IPs.

When a user adds a DNS entry for a specified domain to a floating IP,
nova will add a DNS entry using the specified floating DNS driver.
When a floating IP is deallocated, its DNS entry will automatically be deleted.

Possible values:

* Full Python path to the class to be used

Related options:

* use_neutron: this options only works with nova-network.
"""),
    cfg.StrOpt('instance_dns_manager',
        default='nova.network.noop_dns_driver.NoopDNSDriver',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Full class name for the DNS Manager for instance IPs.

This option specifies the class of the driver that provides functionality
to manage DNS entries for instances.

On instance creation, nova will add DNS entries for the instance name and
id, using the specified instance DNS driver and domain. On instance deletion,
nova will remove the DNS entries.

Possible values:

* Full Python path to the class to be used

Related options:

* use_neutron: this options only works with nova-network.
"""),
    cfg.StrOpt('instance_dns_domain',
        default='',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
If specified, Nova checks if the availability_zone of every instance matches
what the database says the availability_zone should be for the specified
dns_domain.

Related options:

* use_neutron: this options only works with nova-network.
""")
]

ipv6_opts = [
    cfg.BoolOpt('use_ipv6',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Assign IPv6 and IPv4 addresses when creating instances.

Related options:

* use_neutron: this only works with nova-network.
"""),
    cfg.StrOpt('ipv6_backend',
        default='rfc2462',
        choices=('rfc2462', 'account_identifier'),
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help="""
Abstracts out IPv6 address generation to pluggable backends.

nova-network can be put into dual-stack mode, so that it uses
both IPv4 and IPv6 addresses. In dual-stack mode, by default, instances
acquire IPv6 global unicast addresses with the help of stateless address
auto-configuration mechanism.

Related options:

* use_neutron: this option only works with nova-network.
* use_ipv6: this option only works if ipv6 is enabled for nova-network.
"""),
]


quota_opts = [
    cfg.BoolOpt('enable_network_quota',
        deprecated_for_removal=True,
        deprecated_since='14.0.0',
        deprecated_reason="""
CRUD operations on tenant networks are only available when using nova-network
and nova-network is itself deprecated.""",
        default=False,
        help="""
This option is used to enable or disable quota checking for tenant networks.

Related options:

* quota_networks
"""),
    cfg.IntOpt('quota_networks',
        deprecated_for_removal=True,
        deprecated_since='14.0.0',
        deprecated_reason="""
CRUD operations on tenant networks are only available when using nova-network
and nova-network is itself deprecated.""",
        default=3,
        min=0,
        help="""
This option controls the number of private networks that can be created per
project (or per tenant).

Related options:

* enable_network_quota
"""),
]


service_opts = [
    cfg.StrOpt('network_manager',
        choices=[
            'nova.network.manager.FlatManager',
            'nova.network.manager.FlatDHCPManager',
            'nova.network.manager.VlanManager',
        ],
        default='nova.network.manager.VlanManager',
        deprecated_for_removal=True,
        deprecated_since='18.0.0',
        deprecated_reason="""
nova-network is deprecated, as are any related configuration options.
""",
        help='Full class name for the Manager for network'),
]


ALL_DEFAULT_OPTS = (linux_net_opts + network_opts + ldap_dns_opts
                    + rpcapi_opts + driver_opts + floating_ip_opts
                    + ipv6_opts + quota_opts + service_opts)


def register_opts(conf):
    conf.register_opts(ALL_DEFAULT_OPTS)


def list_opts():
    return {"DEFAULT": ALL_DEFAULT_OPTS}
