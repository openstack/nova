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


RULE_AOO = 'rule:admin_or_owner'


def get_name(action=None):
    name = 'os_compute_api:servers'
    if action:
        name = name + ':%s' % action
    return name

rules = [
    policy.RuleDefault(get_name('index'), RULE_AOO),
    policy.RuleDefault(get_name('detail'), RULE_AOO),
    policy.RuleDefault(get_name('detail:get_all_tenants'), RULE_AOO),
    policy.RuleDefault(get_name('index:get_all_tenants'), RULE_AOO),
    policy.RuleDefault(get_name('show'), RULE_AOO),
    policy.RuleDefault(get_name('create'), RULE_AOO),
    policy.RuleDefault(get_name('create:forced_host'), RULE_AOO),
    policy.RuleDefault(get_name('create:attach_volume'), RULE_AOO),
    policy.RuleDefault(get_name('create:attach_network'), RULE_AOO),
    policy.RuleDefault(get_name('delete'), RULE_AOO),
    policy.RuleDefault(get_name('update'), RULE_AOO),
    policy.RuleDefault(get_name('confirm_resize'), RULE_AOO),
    policy.RuleDefault(get_name('revert_resize'), RULE_AOO),
    policy.RuleDefault(get_name('reboot'), RULE_AOO),
    policy.RuleDefault(get_name('resize'), RULE_AOO),
    policy.RuleDefault(get_name('rebuild'), RULE_AOO),
    policy.RuleDefault(get_name('create_image'), RULE_AOO),
    policy.RuleDefault(get_name('create_image:allow_volume_backed'),
                       RULE_AOO),
    policy.RuleDefault(get_name('start'), RULE_AOO),
    policy.RuleDefault(get_name('stop'), RULE_AOO),
    policy.RuleDefault(get_name('trigger_crash_dump'), RULE_AOO),
]


def list_rules():
    return rules
