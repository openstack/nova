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


host = copy.deepcopy(parameter_types.hostname)
host['type'] = ['string', 'null']

migrate_live = {
    'type': 'object',
    'properties': {
        'os-migrateLive': {
            'type': 'object',
            'properties': {
                'block_migration': parameter_types.boolean,
                'disk_over_commit': parameter_types.boolean,
                'host': host
            },
            'required': ['block_migration', 'disk_over_commit', 'host'],
            'additionalProperties': False,
        },
    },
    'required': ['os-migrateLive'],
    'additionalProperties': False,
}

block_migration = copy.deepcopy(parameter_types.boolean)
block_migration['enum'].append('auto')

migrate_live_v2_25 = copy.deepcopy(migrate_live)

del migrate_live_v2_25['properties']['os-migrateLive']['properties'][
    'disk_over_commit']
migrate_live_v2_25['properties']['os-migrateLive']['properties'][
    'block_migration'] = block_migration
migrate_live_v2_25['properties']['os-migrateLive']['required'] = (
    ['block_migration', 'host'])

migrate_live_v2_30 = copy.deepcopy(migrate_live_v2_25)
migrate_live_v2_30['properties']['os-migrateLive']['properties'][
    'force'] = parameter_types.boolean
