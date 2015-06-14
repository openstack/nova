#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

from nova.api.validation import parameter_types


add_fixed_ip = {
    'type': 'object',
    'properties': {
        'addFixedIp': {
            'type': 'object',
            'properties': {
                # The maxLength is from the column 'uuid' of the
                # table 'networks'
                'networkId': {
                    'type': ['string', 'number'],
                    'minLength': 1, 'maxLength': 36,
                },
            },
            'required': ['networkId'],
            'additionalProperties': False,
        },
    },
    'required': ['addFixedIp'],
    'additionalProperties': False,
}


remove_fixed_ip = {
    'type': 'object',
    'properties': {
        'removeFixedIp': {
            'type': 'object',
            'properties': {
                'address': parameter_types.ip_address
            },
            'required': ['address'],
            'additionalProperties': False,
        },
    },
    'required': ['removeFixedIp'],
    'additionalProperties': False,
}
