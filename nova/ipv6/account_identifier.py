# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""IPv6 address generation with account identifier embedded"""

import hashlib
import netaddr


def to_global(prefix, mac, project_id):
    project_hash = netaddr.IPAddress(int(hashlib.sha1(project_id).\
                        hexdigest()[:8], 16) << 32)
    static_num = netaddr.IPAddress(0xff << 24)

    try:
        mac_suffix = netaddr.EUI(mac).words[3:]
        int_addr = int(''.join(['%02x' % i for i in mac_suffix]), 16)
        mac_addr = netaddr.IPAddress(int_addr)
        maskIP = netaddr.IPNetwork(prefix).ip
        return (project_hash ^ static_num ^ mac_addr | maskIP).format()
    except netaddr.AddrFormatError:
        raise TypeError(_('Bad mac for to_global_ipv6: %s') % mac)
    except TypeError:
        raise TypeError(_('Bad prefix for to_global_ipv6: %s') % prefix)
    except NameError:
        raise TypeError(_('Bad project_id for to_global_ipv6: %s') %
                        project_id)


def to_mac(ipv6_address):
    address = netaddr.IPAddress(ipv6_address)
    mask1 = netaddr.IPAddress('::ff:ffff')
    mac = netaddr.EUI(int(address & mask1)).words
    return ':'.join(['02', '16', '3e'] + ['%02x' % i for i in mac[3:6]])
