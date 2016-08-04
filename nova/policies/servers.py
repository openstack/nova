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

from nova.policies import base


RULE_AOO = base.RULE_ADMIN_OR_OWNER
SERVERS = 'os_compute_api:servers:%s'

rules = [
    policy.RuleDefault(SERVERS % 'index', RULE_AOO),
    policy.RuleDefault(SERVERS % 'detail', RULE_AOO),
    policy.RuleDefault(SERVERS % 'detail:get_all_tenants',
                       base.RULE_ADMIN_API),
    policy.RuleDefault(SERVERS % 'index:get_all_tenants', base.RULE_ADMIN_API),
    policy.RuleDefault(SERVERS % 'show', RULE_AOO),
    # the details in host_status are pretty sensitive, only admins
    # should do that by default.
    policy.RuleDefault(SERVERS % 'show:host_status', base.RULE_ADMIN_API),
    policy.RuleDefault(SERVERS % 'create', RULE_AOO),
    policy.RuleDefault(SERVERS % 'create:forced_host', base.RULE_ADMIN_API),
    policy.RuleDefault(SERVERS % 'create:attach_volume', RULE_AOO),
    policy.RuleDefault(SERVERS % 'create:attach_network', RULE_AOO),
    policy.RuleDefault(SERVERS % 'delete', RULE_AOO),
    policy.RuleDefault(SERVERS % 'update', RULE_AOO),
    policy.RuleDefault(SERVERS % 'confirm_resize', RULE_AOO),
    policy.RuleDefault(SERVERS % 'revert_resize', RULE_AOO),
    policy.RuleDefault(SERVERS % 'reboot', RULE_AOO),
    policy.RuleDefault(SERVERS % 'resize', RULE_AOO),
    policy.RuleDefault(SERVERS % 'rebuild', RULE_AOO),
    policy.RuleDefault(SERVERS % 'create_image', RULE_AOO),
    policy.RuleDefault(SERVERS % 'create_image:allow_volume_backed', RULE_AOO),
    policy.RuleDefault(SERVERS % 'start', RULE_AOO),
    policy.RuleDefault(SERVERS % 'stop', RULE_AOO),
    policy.RuleDefault(SERVERS % 'trigger_crash_dump', RULE_AOO),
    policy.RuleDefault(SERVERS % 'discoverable', base.RULE_ANY),
]


def list_rules():
    return rules
