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

import copy

get_vnc_console = {
    'type': 'object',
    'properties': {
        'os-getVNCConsole': {
            'type': 'object',
            'properties': {
                # NOTE(stephenfin): While we only support novnc nowadays, we
                # previously supported xvpvnc for the XenServer driver. Since
                # our generated schemas are unversioned, we need to accept
                # these old values here and reject them lower down the stack.
                # Ditto for other schemas in this file.
                'type': {
                    'type': 'string',
                    'enum': ['novnc', 'xvpvnc'],
                },
            },
            'required': ['type'],
            'additionalProperties': False,
        },
    },
    'required': ['os-getVNCConsole'],
    'additionalProperties': False,
}

get_spice_console = {
    'type': 'object',
    'properties': {
        'os-getSPICEConsole': {
            'type': 'object',
            'properties': {
                'type': {
                    'type': 'string',
                    'enum': ['spice-html5'],
                },
            },
            'required': ['type'],
            'additionalProperties': False,
        },
    },
    'required': ['os-getSPICEConsole'],
    'additionalProperties': False,
}

# NOTE(stephenfin): This schema is intentionally empty since the action has
# been removed
get_rdp_console = {}

get_serial_console = {
    'type': 'object',
    'properties': {
        'os-getSerialConsole': {
            'type': 'object',
            'properties': {
                'type': {
                    'type': 'string', 'enum': ['serial'],
                },
            },
            'required': ['type'],
            'additionalProperties': False,
        },
    },
    'required': ['os-getSerialConsole'],
    'additionalProperties': False,
}

create_v26 = {
    'type': 'object',
    'properties': {
        'remote_console': {
            'type': 'object',
            'properties': {
                'protocol': {
                    'type': 'string',
                    # While we no longer support the rdp console type, we still
                    # list it here for documentation purposes. It is rejected
                    # at the controller level.
                    'enum': ['vnc', 'spice', 'serial', 'rdp'],
                },
                'type': {
                    'type': 'string',
                    'enum': [
                        'novnc', 'xvpvnc', 'spice-html5', 'serial', 'rdp-html5'
                    ],
                },
            },
            'required': ['protocol', 'type'],
            'additionalProperties': False,
        },
    },
    'required': ['remote_console'],
    'additionalProperties': False,
}

create_v28 = copy.deepcopy(create_v26)
create_v28['properties']['remote_console']['properties']['protocol'][
    'enum'
].append('mks')
create_v28['properties']['remote_console']['properties']['type'][
    'enum'
].append('webmks')

create_v299 = copy.deepcopy(create_v28)
create_v299['properties']['remote_console']['properties']['type'][
    'enum'
].append('spice-direct')

get_vnc_console_response = {
    'type': 'object',
    'properties': {
        'console': {
            'type': 'object',
            'properties': {
                'type': {'type': 'string', 'enum': ['novnc', 'xvpvnc']},
                'url': {'type': 'string', 'format': 'uri'},
            },
            'required': ['type', 'url'],
            'additionalProperties': False,
        },
    },
    'required': ['console'],
    'additionalProperties': False,
}

get_spice_console_response = {
    'type': 'object',
    'properties': {
        'console': {
            'type': 'object',
            'properties': {
                'type': {'type': 'string', 'const': 'spice-html5'},
                'url': {'type': 'string', 'format': 'uri'},
            },
            'required': ['type', 'url'],
            'additionalProperties': False,
        },
    },
    'additionalProperties': False,
}

get_rdp_console_response = {
    'type': 'object',
    'properties': {
        'console': {
            'type': 'object',
            'properties': {
                'type': {'type': 'string', 'const': 'rdp-html5'},
                'url': {'type': 'string', 'format': 'uri'},
            },
            'required': ['type', 'url'],
            'additionalProperties': False,
        },
    },
    'required': ['console'],
    'additionalProperties': False,
}

get_serial_console_response = {
    'type': 'object',
    'properties': {
        'console': {
            'type': 'object',
            'properties': {
                'type': {'type': 'string', 'const': 'serial'},
                'url': {'type': 'string', 'format': 'uri'},
            },
            'required': ['type', 'url'],
            'additionalProperties': False,
        },
    },
    'required': ['console'],
    'additionalProperties': False,
}

create_response = {
    'type': 'object',
    'properties': {
        'remote_console': {
            'type': 'object',
            'properties': {
                'protocol': {
                    'type': 'string',
                    'enum': ['vnc', 'spice', 'serial', 'rdp'],
                },
                'type': {
                    'type': 'string',
                    'enum': [
                        'novnc', 'xvpvnc', 'spice-html5', 'serial', 'rdp-html5'
                    ],
                },
                'url': {'type': 'string', 'format': 'uri'},
            },
            'required': ['protocol', 'type', 'url'],
            'additionalProperties': False,
        },
    },
    'required': ['remote_console'],
    'additionalProperties': False,
}

create_response_v28 = copy.deepcopy(create_response)
create_response_v28['properties']['remote_console']['properties'][
    'protocol'
]['enum'].append('mks')
create_response_v28['properties']['remote_console']['properties'][
    'type'
]['enum'].append('webmks')

create_response_v299 = copy.deepcopy(create_response_v28)
create_response_v299['properties']['remote_console']['properties'][
    'type'
]['enum'].append('spice-direct')
