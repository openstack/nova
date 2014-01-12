# Copyright 2014 NEC Corporation.  All rights reserved.
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
Common parameter types for validating request Body.

"""

boolean = {
    'type': ['boolean', 'string'],
    'enum': [True, 'True', 'TRUE', 'true', '1',
             False, 'False', 'FALSE', 'false', '0'],
}


hostname = {
    'type': 'string', 'minLength': 1, 'maxLength': 255,
    # NOTE: 'host' is defined in "services" table, and that
    # means a hostname. The hostname grammar in RFC952 does
    # not allow for underscores in hostnames. However, this
    # schema allows them, because it sometimes occurs in
    # real systems.
    'pattern': '^[a-zA-Z0-9-._]*$',
}


hostname_or_ip_address = {
    # NOTE: Allow to specify hostname, ipv4 and ipv6.
    'type': 'string', 'maxLength': 255,
    'pattern': '^[a-zA-Z0-9-_.:]*$'
}


tcp_udp_port = {
    'type': ['integer', 'string'], 'pattern': '^[0-9]*$',
    'minimum': 0, 'maximum': 65535,
}


project_id = {
    'type': 'string', 'minLength': 1, 'maxLength': 255,
    'pattern': '^[a-zA-Z0-9-]*$'
}


admin_password = {
    # NOTE: admin_password is the admin password of a server
    # instance, and it is not stored into nova's data base.
    # In addition, users set sometimes long/strange string
    # as password. It is unnecessary to limit string length
    # and string pattern.
    'type': 'string',
}
