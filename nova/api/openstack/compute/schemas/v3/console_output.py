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

get_console_output = {
    'type': 'object',
    'properties': {
        'os-getConsoleOutput': {
            'type': 'object',
            'properties': {
                'length': {
                    'type': ['integer', 'string', 'null'],
                    'pattern': '^-?[0-9]+$',
                    # NOTE: -1 means an unlimited length.
                    # TODO(cyeoh): None also means unlimited length
                    # and is supported for v2 backwards compatibility
                    # Should remove in the future with a microversion
                    'minimum': -1,
                },
            },
            'additionalProperties': False,
        },
    },
    'required': ['os-getConsoleOutput'],
    'additionalProperties': False,
}
