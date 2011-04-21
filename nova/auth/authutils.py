# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 NTT DATA CORPORATION.
# Copyright 2011 OpenStack LLC.
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

"""
Auth module specific utilities and helper functions.
"""

import netaddr
import string


def get_host_only_server_string(server_str):
    """
    Returns host part only of the given server_string if it's a combination
    of host part and port. Otherwise, return null string.
    """

    # First of all, exclude pure IPv6 address (w/o port).
    if netaddr.valid_ipv6(server_str):
        return ''

    # Next, check if this is IPv6 address with port number combination.
    if server_str.find("]:") != -1:
        [address, sep, port] = server_str.replace('[', '', 1).partition(']:')
        return address

    # Third, check if this is a combination of general address and port
    if server_str.find(':') == -1:
        return ''

    # This must be a combination of host part and port
    (address, port) = server_str.split(':')
    return address
