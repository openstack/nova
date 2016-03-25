# Copyright 2016 IBM Corporation
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


def register_opts(conf):
    conf.register_opts(network_opts)


def list_opts():
    return {"DEFAULT": network_opts}
