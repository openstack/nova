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


create = {
    'type': 'object',
    'properties': {
        'cloudpipe': {
            'type': 'object',
            'properties': {
                'project_id': parameter_types.project_id,
            },
            'additionalProperties': False,
        },
    },
    'required': ['cloudpipe'],
    'additionalProperties': False,
}

update = {
    'type': 'object',
    'properties': {
        'configure_project': {
            'type': 'object',
            'properties': {
                'vpn_ip': parameter_types.ip_address,
                'vpn_port': parameter_types.tcp_udp_port,
            },
            'required': ['vpn_ip', 'vpn_port'],
            'additionalProperties': False,
        },
    },
    'required': ['configure_project'],
    'additionalProperties': False,
}
