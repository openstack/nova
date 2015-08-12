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
