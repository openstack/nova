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

base_create = {
    'type': 'object',
    'properties': {
        'server': {
            'type': 'object',
            'properties': {
                # TODO(oomichi): To focus the schema extension, now these
                # properties are not defined. After it, we need to define
                # them.
                # 'name': ...
            },
            # TODO(oomichi): After all extension schema patches are merged,
            # this code should be enabled. If enabling before merger, API
            # extension parameters would be considered as bad parameters.
            # 'additionalProperties': False,
        },
    },
    'required': ['server'],
    # TODO(oomichi): ditto, enable here after all extension schema
    # patches are merged.
    # 'additionalProperties': False,
}
