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
        'type': 'object',
        'quota_class_set': {
            'properties': quota_sets.quota_resources,
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
