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

"""RFC2462 style IPv6 address generation."""

import netaddr

from nova.i18n import _


def to_global(prefix, mac, project_id):
    try:
        mac64 = netaddr.EUI(mac).modified_eui64().value
        mac64_addr = netaddr.IPAddress(mac64)
    except netaddr.AddrFormatError:
        raise TypeError(_('Bad mac for to_global_ipv6: %s') % mac)

    try:
        maskIP = netaddr.IPNetwork(prefix).ip
        return (mac64_addr | maskIP).format()
    except netaddr.AddrFormatError:
        raise TypeError(_('Bad prefix for to_global_ipv6: %s') % prefix)


def to_mac(ipv6_address):
    address = netaddr.IPAddress(ipv6_address)
    mask1 = netaddr.IPAddress('::ffff:ffff:ffff:ffff')
    mask2 = netaddr.IPAddress('::0200:0:0:0')
    mac64 = netaddr.EUI(int(address & mask1 ^ mask2)).words
    return ':'.join(['%02x' % i for i in mac64[0:3] + mac64[5:8]])
