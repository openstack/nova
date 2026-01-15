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


index_query = {
    'type': 'object',
    'properties': {
        'tenant_id': parameter_types.common_query_param,
    },
    # For backward compatible changes
    # In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

index_query_v275 = copy.deepcopy(index_query)
index_query_v275['additionalProperties'] = False

_absolute_quota_response = {
    'type': 'object',
    'properties': {
        'maxImageMeta': {'type': 'integer', 'minimum': -1},
        'maxPersonality': {'type': 'integer', 'minimum': -1},
        'maxPersonalitySize': {'type': 'integer', 'minimum': -1},
        'maxSecurityGroups': {'type': 'integer', 'minimum': -1},
        'maxSecurityGroupRules': {'type': 'integer', 'minimum': -1},
        'maxServerMeta': {'type': 'integer', 'minimum': -1},
        'maxServerGroups': {'type': 'integer', 'minimum': -1},
        'maxServerGroupMembers': {'type': 'integer', 'minimum': -1},
        'maxTotalCores': {'type': 'integer', 'minimum': -1},
        'maxTotalFloatingIps': {'type': 'integer', 'minimum': -1},
        'maxTotalInstances': {'type': 'integer', 'minimum': -1},
        'maxTotalKeypairs': {'type': 'integer', 'minimum': -1},
        'maxTotalRAMSize': {'type': 'integer', 'minimum': -1},
        'totalCoresUsed': {'type': 'integer', 'minimum': -1},
        'totalFloatingIpsUsed': {'type': 'integer', 'minimum': -1},
        'totalInstancesUsed': {'type': 'integer', 'minimum': -1},
        'totalRAMUsed': {'type': 'integer', 'minimum': -1},
        'totalSecurityGroupsUsed': {'type': 'integer', 'minimum': -1},
        'totalServerGroupsUsed': {'type': 'integer', 'minimum': -1},
    },
    'required': [
        'maxImageMeta',
        'maxPersonality',
        'maxPersonalitySize',
        'maxSecurityGroups',
        'maxSecurityGroupRules',
        'maxServerMeta',
        'maxServerGroups',
        'maxServerGroupMembers',
        'maxTotalCores',
        'maxTotalFloatingIps',
        'maxTotalInstances',
        'maxTotalKeypairs',
        'maxTotalRAMSize',
        'totalCoresUsed',
        'totalFloatingIpsUsed',
        'totalInstancesUsed',
        'totalRAMUsed',
        'totalSecurityGroupsUsed',
        'totalServerGroupsUsed',
    ],
    'additionalProperties': False,
}

_absolute_quota_response_v236 = copy.deepcopy(_absolute_quota_response)
del _absolute_quota_response_v236['properties']['maxSecurityGroups']
del _absolute_quota_response_v236['properties']['maxSecurityGroupRules']
del _absolute_quota_response_v236['properties']['maxTotalFloatingIps']
del _absolute_quota_response_v236['properties']['totalFloatingIpsUsed']
del _absolute_quota_response_v236['properties']['totalSecurityGroupsUsed']
_absolute_quota_response_v236['required'].pop(
    _absolute_quota_response_v236['required'].index('maxSecurityGroups')
)
_absolute_quota_response_v236['required'].pop(
    _absolute_quota_response_v236['required'].index('maxSecurityGroupRules')
)
_absolute_quota_response_v236['required'].pop(
    _absolute_quota_response_v236['required'].index('maxTotalFloatingIps')
)
_absolute_quota_response_v236['required'].pop(
    _absolute_quota_response_v236['required'].index('totalFloatingIpsUsed')
)
_absolute_quota_response_v236['required'].pop(
    _absolute_quota_response_v236['required'].index('totalSecurityGroupsUsed')
)

_absolute_quota_response_v239 = copy.deepcopy(_absolute_quota_response_v236)
del _absolute_quota_response_v239['properties']['maxImageMeta']
_absolute_quota_response_v239['required'].pop(
    _absolute_quota_response_v239['required'].index('maxImageMeta')
)

_absolute_quota_response_v257 = copy.deepcopy(_absolute_quota_response_v239)
del _absolute_quota_response_v257['properties']['maxPersonality']
del _absolute_quota_response_v257['properties']['maxPersonalitySize']
_absolute_quota_response_v257['required'].pop(
    _absolute_quota_response_v257['required'].index('maxPersonality')
)
_absolute_quota_response_v257['required'].pop(
    _absolute_quota_response_v257['required'].index('maxPersonalitySize')
)

index_response = {
    'type': 'object',
    'properties': {
        'limits': {
            'type': 'object',
            'properties': {
                'absolute': _absolute_quota_response,
                'rate': {
                    'type': 'array',
                    # Yes, this is an empty array
                    'items': {},
                    'maxItems': 0,
                    'additionalItems': False,
                },
            },
            'required': ['absolute', 'rate'],
            'additionalProperties': False,
        },
    },
    'required': ['limits'],
    'additionalProperties': False,
}

index_response_v236 = copy.deepcopy(index_response)
index_response_v236['properties']['limits']['properties']['absolute'] = (
    _absolute_quota_response_v236
)

index_response_v239 = copy.deepcopy(index_response)
index_response_v239['properties']['limits']['properties']['absolute'] = (
    _absolute_quota_response_v239
)

index_response_v257 = copy.deepcopy(index_response_v236)
index_response_v257['properties']['limits']['properties']['absolute'] = (
    _absolute_quota_response_v257
)
