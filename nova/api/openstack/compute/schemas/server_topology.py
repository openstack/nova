# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# TODO(stephenfin): Remove additionalProperties in a future API version
query_params_v21 = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

index_response = {
    'type': 'object',
    'properties': {
        'nodes': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'cpu_pinning': {
                        'type': 'object',
                        'patternProperties': {
                            '^[0-9]+$': {'type': 'integer'},
                        },
                        'additionalProperties': False,
                    },
                    'host_node': {'type': 'integer'},
                    'memory_mb': {'type': 'integer'},
                    'siblings': {
                        'type': 'array',
                        'items': {
                            'type': 'array',
                            'items': {'type': 'integer'},
                        },
                    },
                    'vcpu_set': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                    },
                },
                'required': ['memory_mb', 'siblings', 'vcpu_set'],
                'additionalProperties': False,
            },
        },
        'pagesize_kb': {'type': ['integer', 'null']},
    },
    'required': ['nodes', 'pagesize_kb'],
    'additionalProperties': False,
}
