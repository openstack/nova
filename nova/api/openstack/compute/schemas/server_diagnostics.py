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
index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

# NOTE(stephenfin): We could define all available response types for the
# various virt drivers, but we'd need to be able to do this (accurately) for
# every virt driver including those we once supported but no longer do. Seems
# like a lot of work with very little in return.
index_response = {
    'type': 'object',
    'properties': {},
    'required': [],
    'additionalProperties': True,
}

index_response_v248 = {
    'type': 'object',
    'properties': {
        'config_drive': {'type': 'boolean'},
        'cpu_details': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'id': {'type': ['integer', 'null']},
                    'time': {'type': ['integer', 'null']},
                    'utilisation': {'type': ['integer', 'null']},
                },
                'required': ['id', 'time', 'utilisation'],
                'additionalProperties': False,
            },
        },
        'disk_details': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'errors_count': {'type': ['integer', 'null']},
                    'read_bytes': {'type': ['integer', 'null']},
                    'read_requests': {'type': ['integer', 'null']},
                    'write_bytes': {'type': ['integer', 'null']},
                    'write_requests': {'type': ['integer', 'null']},
                },
                'required': [
                    'errors_count',
                    'read_bytes',
                    'read_requests',
                    'write_bytes',
                    'write_requests',
                ],
                'additionalProperties': False,
            },
        },
        'driver': {
            'type': 'string',
            'enum': [
                'ironic',
                'libvirt',
                'vmwareapi',
                'xenapi',
            ],
        },
        'hypervisor': {'type': ['string', 'null']},
        'hypervisor_os': {'type': ['string', 'null']},
        'memory_details': {
            'type': 'object',
            'properties': {
                'maximum': {'type': ['integer', 'null']},
                'used': {'type': ['integer', 'null']},
            },
            'required': ['maximum', 'used'],
            'additionalProperties': False,
        },
        'nic_details': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'mac_address': {'type': ['string', 'null']},
                    'rx_drop': {'type': ['integer', 'null']},
                    'rx_errors': {'type': ['integer', 'null']},
                    'rx_octets': {'type': ['integer', 'null']},
                    'rx_packets': {'type': ['integer', 'null']},
                    'rx_rate': {'type': ['integer', 'null']},
                    'tx_drop': {'type': ['integer', 'null']},
                    'tx_errors': {'type': ['integer', 'null']},
                    'tx_octets': {'type': ['integer', 'null']},
                    'tx_packets': {'type': ['integer', 'null']},
                    'tx_rate': {'type': ['integer', 'null']},
                },
                'required': [
                    'mac_address',
                    'rx_drop',
                    'rx_errors',
                    'rx_octets',
                    'rx_packets',
                    'rx_rate',
                    'tx_drop',
                    'tx_errors',
                    'tx_octets',
                    'tx_packets',
                    'tx_rate',
                ],
                'additionalProperties': False,
            },
        },
        'num_cpus': {'type': ['integer', 'null']},
        'num_disks': {'type': ['integer', 'null']},
        'num_nics': {'type': ['integer', 'null']},
        'state': {
            'type': 'string',
            'enum': [
                'pending',
                'running',
                'paused',
                'shutdown',
                'crashed',
                'suspended',
            ],
        },
        'uptime': {'type': ['integer', 'null']},
    },
    'required': [
        'config_drive',
        'cpu_details',
        'disk_details',
        'driver',
        'hypervisor',
        'hypervisor_os',
        'memory_details',
        'nic_details',
        'num_cpus',
        'num_disks',
        'num_nics',
        'state',
        'uptime',
    ],
    'additionalProperties': False,
}
