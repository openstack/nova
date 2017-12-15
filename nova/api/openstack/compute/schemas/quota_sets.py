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
from nova import db

common_quota = {
    'type': ['integer', 'string'],
    'pattern': '^-?[0-9]+$',
    # -1 is a flag value for unlimited
    'minimum': -1,
    'maximum': db.MAX_INT
}

quota_resources = {
    'instances': common_quota,
    'cores': common_quota,
    'ram': common_quota,
    'floating_ips': common_quota,
    'fixed_ips': common_quota,
    'metadata_items': common_quota,
    'key_pairs': common_quota,
    'security_groups': common_quota,
    'security_group_rules': common_quota,
    'injected_files': common_quota,
    'injected_file_content_bytes': common_quota,
    'injected_file_path_bytes': common_quota,
    'server_groups': common_quota,
    'server_group_members': common_quota,
    'networks': common_quota
}

update_quota_set = copy.deepcopy(quota_resources)
update_quota_set.update({'force': parameter_types.boolean})

update_quota_set_v236 = copy.deepcopy(update_quota_set)
del update_quota_set_v236['fixed_ips']
del update_quota_set_v236['floating_ips']
del update_quota_set_v236['security_groups']
del update_quota_set_v236['security_group_rules']
del update_quota_set_v236['networks']

update = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'quota_set': {
            'properties': update_quota_set,
            'additionalProperties': False,
        },
    },
    'required': ['quota_set'],
    'additionalProperties': False,
}

update_v236 = copy.deepcopy(update)
update_v236['properties']['quota_set']['properties'] = update_quota_set_v236
