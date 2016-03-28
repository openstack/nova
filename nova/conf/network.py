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

import itertools

from oslo_config import cfg


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

ALL_DEFAULT_OPTS = itertools.chain(
                   network_opts,
                   ldap_dns_opts)


def register_opts(conf):
    conf.register_opts(ALL_DEFAULT_OPTS)


def list_opts():
    return {"DEFAULT": ALL_DEFAULT_OPTS}
