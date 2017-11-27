# Copyright 2014 IBM Corporation.  All rights reserved.
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

from nova.api.validation import parameter_types

snapshots_create = {
    'type': 'object',
    'properties': {
        'snapshot': {
            'type': 'object',
            'properties': {
                'volume_id': {
                    'type': 'string', 'minLength': 1,
                },
                'create_info': {
                    'type': 'object',
                    'properties': {
                        'snapshot_id': {
                            'type': 'string', 'minLength': 1,
                        },
                        'type': {
                            'type': 'string', 'enum': ['qcow2'],
                        },
                        'new_file': {
                            'type': 'string', 'minLength': 1,
                        },
                        'id': {
                            'type': 'string', 'minLength': 1,
                        },
                    },
                    'required': ['snapshot_id', 'type', 'new_file'],
                    'additionalProperties': False,
                 },
            },
            'required': ['volume_id', 'create_info'],
            'additionalProperties': False,
        }
    },
    'required': ['snapshot'],
    'additionalProperties': False,
}

delete_query = {
    'type': 'object',
    'properties': {
        'delete_info': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In the future, we may block the additional parameters
    # by bump in Microversion.
    'additionalProperties': True
}
