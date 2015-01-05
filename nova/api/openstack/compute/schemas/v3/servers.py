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

from nova.api.validation import parameter_types


base_create = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'object',
            'properties': {
                'name': parameter_types.hostname,
                'imageRef': parameter_types.image_ref,
                'flavorRef': parameter_types.flavor_ref,
                'adminPass': parameter_types.admin_password,
                'metadata': parameter_types.metadata,
                'networks': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'fixed_ip': {
                                'type': ['string', 'null'],
                                'oneOf': [
                                    {'format': 'ipv4'},
                                    {'format': 'ipv6'}
                                ]
                            },
                            'port': {
                                'type': ['string', 'null'],
                                'format': 'uuid'
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

base_update = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'object',
            'properties': {
                'name': parameter_types.hostname,
            },
            'additionalProperties': False,
        },
    },
    'required': ['server'],
    'additionalProperties': False,
}

base_rebuild = {
    'type': 'object',
    'properties': {
        'rebuild': {
            'type': 'object',
            'properties': {
                'name': parameter_types.hostname,
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
