# Copyright 2015 NEC Corporation.  All rights reserved.
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

from nova.api.openstack.compute.schemas import quota_sets

update = {
    'type': 'object',
    'properties': {
        'quota_class_set': {
            'type': 'object',
            'properties': quota_sets._quota_resources,
            'additionalProperties': False,
        },
    },
    'required': ['quota_class_set'],
    'additionalProperties': False,
}

update_v250 = copy.deepcopy(update)
del update_v250['properties']['quota_class_set']['properties']['fixed_ips']
del update_v250['properties']['quota_class_set']['properties']['floating_ips']
del update_v250['properties']['quota_class_set']['properties'][
    'security_groups']
del update_v250['properties']['quota_class_set']['properties'][
    'security_group_rules']
del update_v250['properties']['quota_class_set']['properties']['networks']

# 2.57 builds on 2.50 and removes injected_file* quotas.
update_v257 = copy.deepcopy(update_v250)
del update_v257['properties']['quota_class_set']['properties'][
    'injected_files']
del update_v257['properties']['quota_class_set']['properties'][
    'injected_file_content_bytes']
del update_v257['properties']['quota_class_set']['properties'][
    'injected_file_path_bytes']

# TODO(stephenfin): Remove additionalProperties in a future API version
show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

_quota_response = {
    'type': 'object',
    'properties': {
        'cores': {'type': 'integer', 'minimum': -1},
        'fixed_ips': {'type': 'integer', 'minimum': -1},
        'floating_ips': {'type': 'integer', 'minimum': -1},
        'injected_file_content_bytes': {'type': 'integer', 'minimum': -1},
        'injected_file_path_bytes': {'type': 'integer', 'minimum': -1},
        'injected_files': {'type': 'integer', 'minimum': -1},
        'instances': {'type': 'integer', 'minimum': -1},
        'key_pairs': {'type': 'integer', 'minimum': -1},
        'metadata_items': {'type': 'integer', 'minimum': -1},
        'networks': {'type': 'integer', 'minimum': -1},
        'ram': {'type': 'integer', 'minimum': -1},
        'security_groups': {'type': 'integer', 'minimum': -1},
        'security_group_rules': {'type': 'integer', 'minimum': -1},
    },
    'required': [
        # only networks is optional (it only appears under nova-network)
        'cores',
        'fixed_ips',
        'floating_ips',
        'injected_file_content_bytes',
        'injected_file_path_bytes',
        'injected_files',
        'instances',
        'key_pairs',
        'metadata_items',
        'ram',
        'security_groups',
        'security_group_rules',
    ],
    'additionalProperties': False,
}

_quota_response_v250 = copy.deepcopy(_quota_response)
for field in {
    'fixed_ips', 'floating_ips', 'security_group_rules', 'security_groups'
}:
    del _quota_response_v250['properties'][field]
    _quota_response_v250['required'].pop(
        _quota_response_v250['required'].index(field)
    )
_quota_response_v250['properties'].update({
    'server_groups': {'type': 'integer', 'minimum': -1},
    'server_group_members': {'type': 'integer', 'minimum': -1},
})
_quota_response_v250['required'].extend(
    ['server_groups', 'server_group_members']
)

_quota_response_v257 = copy.deepcopy(_quota_response_v250)
for field in {
    'injected_files', 'injected_file_content_bytes', 'injected_file_path_bytes'
}:
    del _quota_response_v257['properties'][field]
    _quota_response_v257['required'].pop(
        _quota_response_v257['required'].index(field)
    )

show_response = {
    'type': 'object',
    'properties': {
        'quota_class_set': copy.deepcopy(_quota_response),
    },
    'required': ['quota_class_set'],
    'additionalProperties': False,
}
show_response['properties']['quota_class_set']['properties'].update({
    'id': {'type': 'string', 'const': 'default'},
})
show_response['properties']['quota_class_set']['required'].append('id')

show_response_v250 = copy.deepcopy(show_response)
show_response_v250['properties']['quota_class_set'] = copy.deepcopy(
    _quota_response_v250
)
show_response_v250['properties']['quota_class_set']['properties'].update({
    'id': {'type': 'string', 'const': 'default'},
})
show_response_v250['properties']['quota_class_set']['required'].append('id')

show_response_v257 = copy.deepcopy(show_response_v250)
show_response_v257['properties']['quota_class_set'] = copy.deepcopy(
    _quota_response_v257
)
show_response_v257['properties']['quota_class_set']['properties'].update({
    'id': {'type': 'string', 'const': 'default'},
})
show_response_v257['properties']['quota_class_set']['required'].append('id')

update_response = {
    'type': 'object',
    'properties': {
        'quota_class_set': _quota_response,
    },
    'required': ['quota_class_set'],
    'additionalProperties': False,
}

update_response_v250 = copy.deepcopy(update_response)
update_response_v250['properties']['quota_class_set'] = _quota_response_v250

update_response_v257 = copy.deepcopy(update_response_v250)
update_response_v257['properties']['quota_class_set'] = _quota_response_v257
