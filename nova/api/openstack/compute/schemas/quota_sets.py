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

_common_quota = {
    'type': ['integer', 'string'],
    'pattern': '^-?[0-9]+$',
    # -1 is a flag value for unlimited
    'minimum': -1,
    # maximum's value is limited to db constant's MAX_INT
    # (in nova/db/constants.py)
    'maximum': 0x7FFFFFFF
}

_quota_resources = {
    'instances': _common_quota,
    'cores': _common_quota,
    'ram': _common_quota,
    'floating_ips': _common_quota,
    'fixed_ips': _common_quota,
    'metadata_items': _common_quota,
    'key_pairs': _common_quota,
    'security_groups': _common_quota,
    'security_group_rules': _common_quota,
    'injected_files': _common_quota,
    'injected_file_content_bytes': _common_quota,
    'injected_file_path_bytes': _common_quota,
    'server_groups': _common_quota,
    'server_group_members': _common_quota,
    # NOTE(stephenfin): This will always be rejected since it was nova-network
    # only, but we need to allow users to submit it at a minimum
    'networks': _common_quota
}

_update_quota_set = copy.deepcopy(_quota_resources)
_update_quota_set.update({'force': parameter_types.boolean})

_update_quota_set_v236 = copy.deepcopy(_update_quota_set)
del _update_quota_set_v236['fixed_ips']
del _update_quota_set_v236['floating_ips']
del _update_quota_set_v236['security_groups']
del _update_quota_set_v236['security_group_rules']
del _update_quota_set_v236['networks']

_update_quota_set_v257 = copy.deepcopy(_update_quota_set_v236)
del _update_quota_set_v257['injected_files']
del _update_quota_set_v257['injected_file_content_bytes']
del _update_quota_set_v257['injected_file_path_bytes']

update = {
    'type': 'object',
    'properties': {
        'quota_set': {
            'type': 'object',
            'properties': _update_quota_set,
            'additionalProperties': False,
        },
    },
    'required': ['quota_set'],
    'additionalProperties': False,
}

update_v236 = copy.deepcopy(update)
update_v236['properties']['quota_set']['properties'] = _update_quota_set_v236

update_v257 = copy.deepcopy(update_v236)
update_v257['properties']['quota_set']['properties'] = _update_quota_set_v257

show_query = {
    'type': 'object',
    'properties': {
        'user_id': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

show_query_v275 = copy.deepcopy(show_query)
show_query_v275['additionalProperties'] = False

detail_query = copy.deepcopy(show_query)
detail_query_v275 = copy.deepcopy(show_query_v275)

update_query = copy.deepcopy(show_query)
update_query_v275 = copy.deepcopy(show_query_v275)

# TODO(stephenfin): Remove additionalProperties in a future API version
defaults_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

delete_query = copy.deepcopy(show_query)
delete_query_v275 = copy.deepcopy(show_query_v275)

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
        'server_groups': {'type': 'integer', 'minimum': -1},
        'server_group_members': {'type': 'integer', 'minimum': -1},
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
        'server_groups',
        'server_group_members',
    ],
    'additionalProperties': False,
}

_quota_response_v236 = copy.deepcopy(_quota_response)
for field in {
    'fixed_ips', 'floating_ips', 'security_group_rules', 'security_groups'
}:
    del _quota_response_v236['properties'][field]
    _quota_response_v236['required'].pop(
        _quota_response_v236['required'].index(field)
    )

_quota_response_v257 = copy.deepcopy(_quota_response_v236)
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
        'quota_set': copy.deepcopy(_quota_response),
    },
    'required': ['quota_set'],
    'additionalProperties': False,
}
show_response['properties']['quota_set']['properties'].update({
    'id': {'type': 'string'},
})
show_response['properties']['quota_set']['required'].append('id')

show_response_v236 = copy.deepcopy(show_response)
show_response_v236['properties']['quota_set'] = copy.deepcopy(
    _quota_response_v236
)
show_response_v236['properties']['quota_set']['properties'].update({
    'id': {'type': 'string'},
})
show_response_v236['properties']['quota_set']['required'].append('id')

show_response_v257 = copy.deepcopy(show_response_v236)
show_response_v257['properties']['quota_set'] = copy.deepcopy(
    _quota_response_v257
)
show_response_v257['properties']['quota_set']['properties'].update({
    'id': {'type': 'string'},
})
show_response_v257['properties']['quota_set']['required'].append('id')

_detail_quota = {
    'type': 'object',
    'properties': {
        'in_use': {'type': 'integer', 'minimum': -1},
        'limit': {'type': 'integer', 'minimum': -1},
        'reserved': {'type': 'integer', 'minimum': -1},
    },
    'required': ['in_use', 'limit', 'reserved'],
    'additionalProperties': False,
}

_detail_quota_response = copy.deepcopy(_quota_response)
for field in _detail_quota_response['properties']:
    if field == 'id':
        continue

    _detail_quota_response['properties'][field] = _detail_quota

_detail_quota_response_v236 = copy.deepcopy(_detail_quota_response)
for field in {
    'fixed_ips', 'floating_ips', 'security_group_rules', 'security_groups'
}:
    del _detail_quota_response_v236['properties'][field]
    _detail_quota_response_v236['required'].pop(
        _detail_quota_response_v236['required'].index(field)
    )

_detail_quota_response_v257 = copy.deepcopy(_detail_quota_response_v236)
for field in {
    'injected_files', 'injected_file_content_bytes', 'injected_file_path_bytes'
}:
    del _detail_quota_response_v257['properties'][field]
    _detail_quota_response_v257['required'].pop(
        _detail_quota_response_v257['required'].index(field)
    )

detail_response = {
    'type': 'object',
    'properties': {
        'quota_set': copy.deepcopy(_detail_quota_response),
    },
    'required': ['quota_set'],
    'additionalProperties': False,
}
detail_response['properties']['quota_set']['properties'].update({
    'id': {'type': 'string'},
})
detail_response['properties']['quota_set']['required'].append('id')

detail_response_v236 = copy.deepcopy(detail_response)
detail_response_v236['properties']['quota_set'] = copy.deepcopy(
    _detail_quota_response_v236
)
detail_response_v236['properties']['quota_set']['properties'].update({
    'id': {'type': 'string'},
})
detail_response_v236['properties']['quota_set']['required'].append('id')

detail_response_v257 = copy.deepcopy(detail_response_v236)
detail_response_v257['properties']['quota_set'] = copy.deepcopy(
    _detail_quota_response_v257
)
detail_response_v257['properties']['quota_set']['properties'].update({
    'id': {'type': 'string'},
})
detail_response_v257['properties']['quota_set']['required'].append('id')

update_response = {
    'type': 'object',
    'properties': {
        'quota_set': _quota_response,
    },
    'required': ['quota_set'],
    'additionalProperties': False,
}

update_response_v236 = copy.deepcopy(update_response)
update_response_v236['properties']['quota_set'] = _quota_response_v236

update_response_v257 = copy.deepcopy(update_response_v236)
update_response_v257['properties']['quota_set'] = _quota_response_v257

defaults_response = copy.deepcopy(show_response)
defaults_response_v236 = copy.deepcopy(show_response_v236)
defaults_response_v257 = copy.deepcopy(show_response_v257)

delete_response = {'type': 'null'}
