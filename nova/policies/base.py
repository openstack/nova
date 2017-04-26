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

from oslo_policy import policy

COMPUTE_API = 'os_compute_api'
NETWORK_ATTACH_EXTERNAL = 'network:attach_external_network'

RULE_ADMIN_OR_OWNER = 'rule:admin_or_owner'
RULE_ADMIN_API = 'rule:admin_api'
RULE_ANY = '@'

rules = [
    policy.RuleDefault('context_is_admin', 'role:admin'),
    policy.RuleDefault('admin_or_owner',
                       'is_admin:True or project_id:%(project_id)s'),
    policy.RuleDefault('admin_api', 'is_admin:True'),
    policy.RuleDefault(NETWORK_ATTACH_EXTERNAL, 'is_admin:True'),
]


def _unwrap_text(text):

    def _split_paragraphs(lines):
        output = []
        for line in lines.split('\n'):
            if line:
                output.append(line.strip())
            elif output:
                yield ' '.join(output)
                output = []

        if output:
            yield ' '.join(output)

    return '\n\n'.join([x for x in _split_paragraphs(text)])


def create_rule_default(name, check_str, description, operations):
    # TODO(sneti): use DocumentedRuleDefault instead of RuleDefault when
    # oslo.policy library is bumped to 1.21.0. The formatted_description hack
    # can be removed then.
    ops = ""
    for operation in operations:
            ops += ('%(method)s %(path)s\n' %
                     {'method': operation['method'],
                      'path': operation['path']})
    template = """%(description)s\n\n%(operations)s\n"""
    formatted_description = template % {
        "description": _unwrap_text(description),
        "operations": ops,
    }

    return policy.RuleDefault(name, check_str, formatted_description)


def list_rules():
    return rules
