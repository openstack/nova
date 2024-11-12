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
from nova.api.validation import response_types

# NOTE(stephenfin): These schemas are incomplete but won't be enhanced further
# since these APIs have been removed

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

index_query = {
    'type': 'object',
    'properties': {
        # NOTE(stephenfin): We never validated these and we're not going to add
        # that validation now.
        # field filters
        'name': {},
        'status': {},
        'changes-since': {},
        'server': {},
        'type': {},
        'minRam': {},
        'minDisk': {},
        # pagination filters
        'limit': parameter_types.multi_params(
            parameter_types.positive_integer),
        'page_size': parameter_types.multi_params(
            parameter_types.positive_integer),
        'marker': {},
        'offset': parameter_types.multi_params(
            parameter_types.positive_integer),
    },
    'patternProperties': {
        '^property-.*$': {},
    },
    'additionalProperties': True,
}

detail_query = index_query

_links_response = {
    'type': 'array',
    'prefixItems': [
        {
            'type': 'object',
            'properties': {
                'href': {'type': 'string', 'format': 'uri'},
                'rel': {'const': 'self'},
            },
            'required': ['href', 'rel'],
            'additionalProperties': False,
        },
        {
            'type': 'object',
            'properties': {
                'href': {'type': 'string', 'format': 'uri'},
                'rel': {'const': 'bookmark'},
            },
            'required': ['href', 'rel'],
            'additionalProperties': False,
        },
        {
            'type': 'object',
            'properties': {
                'href': {'type': 'string', 'format': 'uri'},
                'rel': {'const': 'alternate'},
                'type': {'const': 'application/vnd.openstack.image'},
            },
            'required': ['href', 'rel', 'type'],
            'additionalProperties': False,
        },
    ],
    'minItems': 3,
    'maxItems': 3,
}

_image_response = {
    'type': 'object',
    'properties': {
        'created': {'type': 'string', 'format': 'date-time'},
        'id': {'type': 'string', 'format': 'uuid'},
        'links': _links_response,
        'metadata': {
            'type': 'object',
            'patternProperties': {
                # unlike nova's metadata, glance doesn't have a maximum length
                # on property values. Also, while glance serializes all
                # non-null values as strings, nova's image API deserializes
                # these again, so we can expected practically any primitive
                # type here. Listing all these is effectively the same as
                # providing an empty schema so we're mainly doing it for the
                # benefit of tooling.
                '^[a-zA-Z0-9-_:. ]{1,255}$': {
                    'type': [
                        'array',
                        'boolean',
                        'integer',
                        'number',
                        'object',
                        'string',
                        'null',
                    ]
                },
            },
            'additionalProperties': False,
        },
        'minDisk': {'type': 'integer', 'minimum': 0},
        'minRam': {'type': 'integer', 'minimum': 0},
        'name': {'type': ['string', 'null']},
        'progress': {
            'type': 'integer',
            'enum': [0, 25, 50, 100],
        },
        'server': {
            'type': 'object',
            'properties': {
                'id': {'type': 'string', 'format': 'uuid'},
                'links': {
                    'type': 'array',
                    'prefixItems': [
                        {
                            'type': 'object',
                            'properties': {
                                'href': {'type': 'string', 'format': 'uri'},
                                'rel': {'const': 'self'},
                            },
                            'required': ['href', 'rel'],
                            'additionalProperties': False,
                        },
                        {
                            'type': 'object',
                            'properties': {
                                'href': {'type': 'string', 'format': 'uri'},
                                'rel': {'const': 'bookmark'},
                            },
                            'required': ['href', 'rel'],
                            'additionalProperties': False,
                        },
                    ],
                    'minItems': 2,
                    'maxItems': 2,
                },
            },
            'required': ['id', 'links'],
            'additionalProperties': False,
        },
        'status': {
            'type': 'string',
            'enum': ['ACTIVE', 'SAVING', 'DELETED', 'ERROR', 'UNKNOWN'],
        },
        'updated': {'type': ['string', 'null'], 'format': 'date-time'},
        'OS-DCF:diskConfig': {'type': 'string', 'enum': ['AUTO', 'MANUAL']},
        'OS-EXT-IMG-SIZE:size': {'type': 'integer'},
    },
    'required': [
        'created',
        'id',
        'links',
        'metadata',
        'minDisk',
        'minRam',
        'name',
        'progress',
        'status',
        'updated',
        'OS-EXT-IMG-SIZE:size',
    ],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'properties': {
        'image': copy.deepcopy(_image_response),
    },
    'required': [],
    'additionalProperties': False,
}

delete_response = {'type': 'null'}

index_response = {
    'type': 'object',
    'properties': {
        'images': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string', 'format': 'uuid'},
                    'links': _links_response,
                    'name': {'type': ['string', 'null']},
                },
                'required': ['id', 'links', 'name'],
                'additionalProperties': False,
            },
        },
        'images_links': response_types.collection_links,
    },
    'required': [],
    'additionalProperties': False,
}

detail_response = {
    'type': 'object',
    'properties': {
        'images': {
            'type': 'array',
            'items': copy.deepcopy(_image_response),
        },
        'images_links': response_types.collection_links,
    },
    'required': ['images'],
    'additionalProperties': False,
}
