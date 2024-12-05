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

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

# TODO(stephenfin): Remove additionalProperties in a future API version
multi_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

_version_obj = {
    'type': 'object',
    'properties': {
        'id': {'type': 'string'},
        'status': {
            'type': 'string',
            'enum': ['CURRENT', 'SUPPORTED', 'DEPRECATED'],
        },
        'links': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'href': {'type': 'string'},
                    'rel': {'type': 'string'},
                    'type': {'type': 'string'},
                },
                'required': ['rel', 'href'],
                'additionalProperties': False,
            },
        },
        'min_version': {'type': 'string'},
        'updated': {'type': 'string', 'format': 'date-time'},
        'version': {'type': 'string'},
    },
    'required': ['id', 'status', 'links', 'min_version', 'updated'],
    'additionalProperties': False,
}

index_response = {
    'type': 'object',
    'properties': {
        'versions': {'type': 'array', 'items': _version_obj}
    },
    'required': ['versions'],
    'additionalProperties': False,
}

_version_obj_with_media_types = _version_obj
_version_obj_with_media_types['properties'].update({
    'media-types': {
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'base': {'type': 'string'},
                'type': {'type': 'string'},
            },
            'required': ['base', 'type'],
            'additionalProperties': False,
        },
    }
})

show_response = {
    'type': 'object',
    'properties': {
        'version': _version_obj_with_media_types
    },
    'required': ['version'],
    'additionalProperties': False,
}

_legacy_version_obj = {
    'type': 'object',
    'properties': {
        'id': {'type': 'string'},
        'status': {'type': 'string'},
        'links': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'href': {'type': 'string'},
                    'rel': {'type': 'string'},
                    'type': {'type': 'string'},
                },
                'required': ['rel', 'href'],
                'additionalProperties': False,
            },
        },
        'media-types': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'base': {'type': 'string'},
                    'type': {'type': 'string'},
                },
                'required': ['base', 'type'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['id', 'status', 'links', 'media-types'],
    'additionalProperties': False,
}

multi_response = {
    'type': 'object',
    'properties': {
        'choices': {'type': 'array', 'items': _legacy_version_obj}
    },
    'required': ['choices'],
    'additionalProperties': False,
}
