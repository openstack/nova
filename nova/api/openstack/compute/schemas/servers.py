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

from nova.api.validation import parameter_types


base_create = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'imageRef': parameter_types.image_ref,
                'flavorRef': parameter_types.flavor_ref,
                'adminPass': parameter_types.admin_password,
                'metadata': parameter_types.metadata,
                'networks': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'fixed_ip': parameter_types.ip_address,
                            'port': {
                                'oneOf': [{'type': 'string', 'format': 'uuid'},
                                          {'type': 'null'}]
                            },
                            'uuid': {'type': 'string'},
                        },
                        'additionalProperties': False,
                    }
                }
            },
            'required': ['name', 'flavorRef'],
            'additionalProperties': False,
        },
    },
    'required': ['server'],
    'additionalProperties': False,
}


base_create_v20 = copy.deepcopy(base_create)
base_create_v20['properties']['server'][
    'properties']['name'] = parameter_types.name_with_leading_trailing_spaces


base_create_v219 = copy.deepcopy(base_create)
base_create_v219['properties']['server'][
    'properties']['description'] = parameter_types.description


base_update = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
            },
            'additionalProperties': False,
        },
    },
    'required': ['server'],
    'additionalProperties': False,
}


base_update_v20 = copy.deepcopy(base_update)
base_update_v20['properties']['server'][
    'properties']['name'] = parameter_types.name_with_leading_trailing_spaces

base_update_v219 = copy.deepcopy(base_update)
base_update_v219['properties']['server'][
    'properties']['description'] = parameter_types.description

base_rebuild = {
    'type': 'object',
    'properties': {
        'rebuild': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'imageRef': parameter_types.image_ref,
                'adminPass': parameter_types.admin_password,
                'metadata': parameter_types.metadata,
                'preserve_ephemeral': parameter_types.boolean,
            },
            'required': ['imageRef'],
            'additionalProperties': False,
        },
    },
    'required': ['rebuild'],
    'additionalProperties': False,
}


base_rebuild_v20 = copy.deepcopy(base_rebuild)
base_rebuild_v20['properties']['rebuild'][
    'properties']['name'] = parameter_types.name_with_leading_trailing_spaces

base_rebuild_v219 = copy.deepcopy(base_rebuild)
base_rebuild_v219['properties']['rebuild'][
    'properties']['description'] = parameter_types.description

base_resize = {
    'type': 'object',
    'properties': {
        'resize': {
            'type': 'object',
            'properties': {
                'flavorRef': parameter_types.flavor_ref,
            },
            'required': ['flavorRef'],
            'additionalProperties': False,
        },
    },
    'required': ['resize'],
    'additionalProperties': False,
}

create_image = {
    'type': 'object',
    'properties': {
        'createImage': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'metadata': parameter_types.metadata
            },
            'required': ['name'],
            'additionalProperties': False
        }
    },
    'required': ['createImage'],
    'additionalProperties': False
}


create_image_v20 = copy.deepcopy(create_image)
create_image_v20['properties']['createImage'][
    'properties']['name'] = parameter_types.name_with_leading_trailing_spaces


reboot = {
    'type': 'object',
    'properties': {
        'reboot': {
            'type': 'object',
            'properties': {
                'type': {
                    'enum': ['HARD', 'Hard', 'hard', 'SOFT', 'Soft', 'soft']
                }
            },
            'required': ['type'],
            'additionalProperties': False
        }
    },
    'required': ['reboot'],
    'additionalProperties': False
}

trigger_crash_dump = {
    'type': 'object',
    'properties': {
        'trigger_crash_dump': {
            'type': 'null'
        }
    },
    'required': ['trigger_crash_dump'],
    'additionalProperties': False
}
