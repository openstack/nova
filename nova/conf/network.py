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

from oslo_config import cfg

from nova import paths


network_opts = [
    cfg.StrOpt("flat_network_bridge",
               help="Bridge for simple network instances"),
    cfg.StrOpt("flat_network_dns",
               default="8.8.4.4",
               help="DNS server for simple network"),
    cfg.BoolOpt("flat_injected",
                default=False,
                help="Whether to attempt to inject network setup into guest"),
    cfg.StrOpt("flat_interface",
               help="FlatDhcp will bridge into this interface if set"),
    cfg.IntOpt("vlan_start",
               default=100,
               min=1,
               max=4094,
               help="First VLAN for private networks"),
    cfg.StrOpt("vlan_interface",
               help="VLANs will bridge into this interface if set"),
    cfg.IntOpt("num_networks",
               default=1,
               help="Number of networks to support"),
    cfg.StrOpt("vpn_ip",
               default="$my_ip",
               help="Public IP for the cloudpipe VPN servers"),
    cfg.IntOpt("vpn_start",
               default=1000,
               help="First Vpn port for private networks"),
    cfg.IntOpt("network_size",
               default=256,
               help="Number of addresses in each private subnet"),
    cfg.StrOpt("fixed_range_v6",
               default="fd00::/48",
               help="Fixed IPv6 address block"),
    cfg.StrOpt("gateway",
               help="Default IPv4 gateway"),
    cfg.StrOpt("gateway_v6",
               help="Default IPv6 gateway"),
    cfg.IntOpt("cnt_vpn_clients",
               default=0,
               help="Number of addresses reserved for vpn clients"),
    cfg.IntOpt("fixed_ip_disassociate_timeout",
               default=600,
               help="Seconds after which a deallocated IP is disassociated"),
    cfg.IntOpt("create_unique_mac_address_attempts",
               default=5,
               help="Number of attempts to create unique mac address"),
    cfg.BoolOpt("fake_call",
                default=False,
                help="If True, skip using the queue and make local calls"),
    cfg.BoolOpt("teardown_unused_network_gateway",
                default=False,
                help="If True, unused gateway devices (VLAN and bridge) are "
                     "deleted in VLAN network mode with multi hosted "
                     "networks"),
    cfg.BoolOpt("force_dhcp_release",
                default=True,
                help="If True, send a dhcp release on instance termination"),
    cfg.BoolOpt("update_dns_entries",
                default=False,
                help="If True, when a DNS entry must be updated, it sends a "
                     "fanout cast to all network hosts to update their DNS "
                     "entries in multi host mode"),
    cfg.IntOpt("dns_update_periodic_interval",
               default=-1,
               help="Number of seconds to wait between runs of updates to DNS "
                    "entries."),
    cfg.StrOpt("dhcp_domain",
               default="novalocal",
               help="Domain to use for building the hostnames"),
    cfg.StrOpt("l3_lib",
               default="nova.network.l3.LinuxNetL3",
               help="Indicates underlying L3 management library"),
    cfg.BoolOpt("share_dhcp_address",
            default=False,
            deprecated_for_removal=True,
            help="""
DEPRECATED: THIS VALUE SHOULD BE SET WHEN CREATING THE NETWORK.

If True in multi_host mode, all compute hosts share the same dhcp address. The
same IP address used for DHCP will be added on each nova-network node which is
only visible to the VMs on the same host.

The use of this configuration has been deprecated and may be removed in any
release after Mitaka. It is recommended that instead of relying on this option,
an explicit value should be passed to 'create_networks()' as a keyword argument
with the name 'share_address'.

* Services that use this:

    ``nova-network``

* Related options:

    None
"""),

    # NOTE(mriedem): Remove network_device_mtu in Newton.
    cfg.IntOpt("network_device_mtu",
            deprecated_for_removal=True,
            help="""
DEPRECATED: THIS VALUE SHOULD BE SET WHEN CREATING THE NETWORK.

MTU (Maximum Transmission Unit) setting for a network interface.

The use of this configuration has been deprecated and may be removed in any
release after Mitaka. It is recommended that instead of relying on this option,
an explicit value should be passed to 'create_networks()' as a keyword argument
with the name 'mtu'.

* Services that use this:

    ``nova-network``

* Related options:

    None
"""),
]

linux_net_opts = [
    cfg.MultiStrOpt('dhcpbridge_flagfile',
                    default=['/etc/nova/nova-dhcpbridge.conf'],
                    help='Location of flagfiles for dhcpbridge'),
    cfg.StrOpt('networks_path',
               default=paths.state_path_def('networks'),
               help='Location to keep network config files'),
    cfg.StrOpt('public_interface',
               default='eth0',
               help='Interface for public IP addresses'),
    cfg.StrOpt('dhcpbridge',
               default=paths.bindir_def('nova-dhcpbridge'),
               help='Location of nova-dhcpbridge'),
    cfg.StrOpt('routing_source_ip',
               default='$my_ip',
               help='Public IP of network host'),
    cfg.IntOpt('dhcp_lease_time',
               default=86400,
               help='Lifetime of a DHCP lease in seconds'),
    cfg.MultiStrOpt('dns_server',
                    default=[],
                    help='If set, uses specific DNS server for dnsmasq. Can'
                         ' be specified multiple times.'),
    cfg.BoolOpt('use_network_dns_servers',
                default=False,
                help='If set, uses the dns1 and dns2 from the network ref.'
                     ' as dns servers.'),
    cfg.ListOpt('dmz_cidr',
               default=[],
               help='A list of dmz ranges that should be accepted'),
    cfg.MultiStrOpt('force_snat_range',
               default=[],
               help='Traffic to this range will always be snatted to the '
                    'fallback IP, even if it would normally be bridged out '
                    'of the node. Can be specified multiple times.'),
    cfg.StrOpt('dnsmasq_config_file',
               default='',
               help='Override the default dnsmasq settings with this file'),
    cfg.StrOpt('linuxnet_interface_driver',
               default='nova.network.linux_net.LinuxBridgeInterfaceDriver',
               help='Driver used to create ethernet devices.'),
    cfg.StrOpt('linuxnet_ovs_integration_bridge',
               default='br-int',
               help='Name of Open vSwitch bridge used with linuxnet'),
    cfg.BoolOpt('send_arp_for_ha',
                default=False,
                help='Send gratuitous ARPs for HA setup'),
    cfg.IntOpt('send_arp_for_ha_count',
               default=3,
               help='Send this many gratuitous ARPs for HA setup'),
    cfg.BoolOpt('use_single_default_gateway',
                default=False,
                help='Use single default gateway. Only first nic of vm will '
                     'get default gateway from dhcp server'),
    cfg.MultiStrOpt('forward_bridge_interface',
                    default=['all'],
                    help='An interface that bridges can forward to. If this '
                         'is set to all then all traffic will be forwarded. '
                         'Can be specified multiple times.'),
    cfg.StrOpt('metadata_host',
               default='$my_ip',
               help='The IP address for the metadata API server'),
    cfg.IntOpt('metadata_port',
               default=8775,
               min=1,
               max=65535,
               help='The port for the metadata API port'),
    cfg.StrOpt('iptables_top_regex',
               default='',
               help='Regular expression to match the iptables rule that '
                    'should always be on the top.'),
    cfg.StrOpt('iptables_bottom_regex',
               default='',
               help='Regular expression to match the iptables rule that '
                    'should always be on the bottom.'),
    cfg.StrOpt('iptables_drop_action',
               default='DROP',
               help='The table that iptables to jump to when a packet is '
                    'to be dropped.'),
    cfg.IntOpt('ovs_vsctl_timeout',
               default=120,
               help='Amount of time, in seconds, that ovs_vsctl should wait '
                    'for a response from the database. 0 is to wait forever.'),
    cfg.BoolOpt('fake_network',
                default=False,
                help='If passed, use fake network devices and addresses'),
    cfg.IntOpt('ebtables_exec_attempts',
               default=3,
               help='Number of times to retry ebtables commands on failure.'),
    cfg.FloatOpt('ebtables_retry_interval',
                 default=1.0,
                 help='Number of seconds to wait between ebtables retries.'),
]


ldap_dns_opts = [
    cfg.StrOpt('ldap_dns_url',
                default='ldap://ldap.example.com:389',
                help='URL for LDAP server which will store DNS entries'),
    cfg.StrOpt('ldap_dns_user',
                default='uid=admin,ou=people,dc=example,dc=org',
                help='User for LDAP DNS'),
    cfg.StrOpt('ldap_dns_password',
                default='password',
                help='Password for LDAP DNS',
                secret=True),
    cfg.StrOpt('ldap_dns_soa_hostmaster',
                default='hostmaster@example.org',
                help='Hostmaster for LDAP DNS driver Statement of Authority'),
    cfg.MultiStrOpt('ldap_dns_servers',
                default=['dns.example.org'],
                help='DNS Servers for LDAP DNS driver'),
    cfg.StrOpt('ldap_dns_base_dn',
                default='ou=hosts,dc=example,dc=org',
                help='Base DN for DNS entries in LDAP'),
    cfg.StrOpt('ldap_dns_soa_refresh',
                default='1800',
                help='Refresh interval (in seconds) for LDAP DNS driver '
                     'Statement of Authority'),
    cfg.StrOpt('ldap_dns_soa_retry',
                default='3600',
                help='Retry interval (in seconds) for LDAP DNS driver '
                     'Statement of Authority'),
    cfg.StrOpt('ldap_dns_soa_expiry',
                default='86400',
                help='Expiry interval (in seconds) for LDAP DNS driver '
                     'Statement of Authority'),
    cfg.StrOpt('ldap_dns_soa_minimum',
                default='7200',
                help='Minimum interval (in seconds) for LDAP DNS driver '
                     'Statement of Authority'),
]

ALL_DEFAULT_OPTS = linux_net_opts + network_opts + ldap_dns_opts


def register_opts(conf):
    conf.register_opts(linux_net_opts)
    conf.register_opts(network_opts)
    conf.register_opts(ldap_dns_opts)


def list_opts():
    return {"DEFAULT": ALL_DEFAULT_OPTS}
