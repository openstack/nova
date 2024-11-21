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

index_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

show_query = {
    'type': 'object',
    'properties': {},
    'additionalProperties': True,
}

_instance_usage_audit_log_response = {
    'type': 'object',
    'properties': {
        'hosts_not_run': {
            'type': 'array',
            'items': {'type': 'string', 'format': 'uuid'},
        },
        'log': {
            'type': 'object',
            'additionalProperties': {
                'instances': {'type': 'integer', 'minimum': 0},
                'errors': {'type': 'integer', 'minimum': 0},
                'message': {'type': 'string'},
                'state': {'type': 'string', 'enum': ['RUNNING', 'DONE']},
            },
        },
        'num_hosts': {'type': 'integer', 'minimum': 0},
        'num_hosts_done': {'type': 'integer', 'minimum': 0},
        'num_hosts_not_run': {'type': 'integer', 'minimum': 0},
        'num_hosts_running': {'type': 'integer', 'minimum': 0},
        'overall_status': {'type': 'string'},
        'period_beginning': {'type': 'string', 'format': 'date-time'},
        'period_ending': {'type': 'string', 'format': 'date-time'},
        'total_errors': {'type': 'integer', 'minimum': 0},
        'total_instances': {'type': 'integer', 'minimum': 0},
    },
    'required': [
        'hosts_not_run',
        'log',
        'num_hosts',
        'num_hosts_done',
        'num_hosts_not_run',
        'num_hosts_running',
        'overall_status',
        'period_beginning',
        'period_ending',
        'total_errors',
        'total_instances',
    ],
    'additionalProperties': False,
}

index_response = {
    'type': 'object',
    'properties': {
        # NOTE(stephenfin): Yes, this is correct: the index response is
        # identical to the show response. In fact, the show response is really
        # the index response with a 'before' filter and a singular key
        'instance_usage_audit_logs': _instance_usage_audit_log_response,
    },
    'required': ['instance_usage_audit_logs'],
    'additionalProperties': False,
}

show_response = {
    'type': 'object',
    'properties': {
        'instance_usage_audit_log': _instance_usage_audit_log_response,
    },
    'required': ['instance_usage_audit_log'],
    'additionalProperties': False,
}
