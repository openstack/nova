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

import copy


boolean = {
    'type': ['boolean', 'string'],
    'enum': [True, 'True', 'TRUE', 'true', '1', 'ON', 'On', 'on',
             'YES', 'Yes', 'yes',
             False, 'False', 'FALSE', 'false', '0', 'OFF', 'Off', 'off',
             'NO', 'No', 'no'],
}


positive_integer = {
    'type': ['integer', 'string'],
    'pattern': '^[0-9]*$', 'minimum': 1
}


non_negative_integer = {
    'type': ['integer', 'string'],
    'pattern': '^[0-9]*$', 'minimum': 0
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


name = {
    # NOTE: Nova v3 API contains some 'name' parameters such
    # as keypair, server, flavor, aggregate and so on. They are
    # stored in the DB and Nova specific parameters.
    # This definition is used for all their parameters.
    'type': 'string', 'minLength': 1, 'maxLength': 255,

    # NOTE: Allow to some spaces in middle of name.
    # Also note that the regexp below deliberately allows and
    # empty string. This is so only the constraint above
    # which enforces a minimum length for the name is triggered
    # when an empty string is tested. Otherwise it is not
    # deterministic which constraint fails and this causes issues
    # for some unittests when PYTHONHASHSEED is set randomly.
    'pattern': '^(?! )[a-zA-Z0-9. _-]*(?<! )$',
}


tcp_udp_port = {
    'type': ['integer', 'string'], 'pattern': '^[0-9]*$',
    'minimum': 0, 'maximum': 65535,
    'minLength': 1
}


project_id = {
    'type': 'string', 'minLength': 1, 'maxLength': 255,
    'pattern': '^[a-zA-Z0-9-]*$'
}


server_id = {
    'type': 'string', 'format': 'uuid'
}


image_id = {
    'type': 'string', 'format': 'uuid'
}


volume_id = {
    'type': 'string', 'format': 'uuid'
}


network_id = {
    'type': 'string', 'format': 'uuid'
}


network_port_id = {
    'type': 'string', 'format': 'uuid'
}


admin_password = {
    # NOTE: admin_password is the admin password of a server
    # instance, and it is not stored into nova's data base.
    # In addition, users set sometimes long/strange string
    # as password. It is unnecessary to limit string length
    # and string pattern.
    'type': 'string',
}


image_ref = {
    'type': 'string',
}


flavor_ref = {
    'type': ['string', 'integer'], 'minLength': 1
}


metadata = {
    'type': 'object',
    'patternProperties': {
        '^[a-zA-Z0-9-_:. ]{1,255}$': {
            'type': 'string', 'maxLength': 255
        }
    },
    'additionalProperties': False
}


metadata_with_null = copy.deepcopy(metadata)
metadata_with_null['patternProperties']['^[a-zA-Z0-9-_:. ]{1,255}$']['type'] =\
    ['string', 'null']


mac_address = {
    'type': 'string',
    'pattern': '^([0-9a-fA-F]{2})(:[0-9a-fA-F]{2}){5}$'
}
