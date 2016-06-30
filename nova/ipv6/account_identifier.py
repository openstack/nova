# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""IPv6 address generation with account identifier embedded."""

import hashlib

import netaddr
import six

from nova.i18n import _


def to_global(prefix, mac, project_id):
    addr = project_id
    if isinstance(addr, six.text_type):
        addr = addr.encode('utf-8')
    addr = hashlib.sha1(addr)
    addr = int(addr.hexdigest()[:8], 16) << 32

    project_hash = netaddr.IPAddress(addr)
    static_num = netaddr.IPAddress(0xff << 24)

    try:
        mac_suffix = netaddr.EUI(mac).value & 0xffffff
        mac_addr = netaddr.IPAddress(mac_suffix)
    except netaddr.AddrFormatError:
        raise TypeError(_('Bad mac for to_global_ipv6: %s') % mac)

    try:
        maskIP = netaddr.IPNetwork(prefix).ip
        return (project_hash ^ static_num ^ mac_addr | maskIP).format()
    except netaddr.AddrFormatError:
        raise TypeError(_('Bad prefix for to_global_ipv6: %s') % prefix)


def to_mac(ipv6_address):
    address = netaddr.IPAddress(ipv6_address)
    mask1 = netaddr.IPAddress('::ff:ffff')
    mac = netaddr.EUI(int(address & mask1)).words
    return ':'.join(['02', '16', '3e'] + ['%02x' % i for i in mac[3:6]])
