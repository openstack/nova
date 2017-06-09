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

RULE_ADMIN_OR_OWNER = 'rule:admin_or_owner'
RULE_ADMIN_API = 'rule:admin_api'
RULE_ANY = '@'

# NOTE(johngarbutt) The base rules here affect so many APIs the list
# of related API operations has not been populated. It would be
# crazy hard to manually maintain such a list.
rules = [
    policy.RuleDefault(
        "context_is_admin",
        "role:admin",
        "Decides what is required for the 'is_admin:True' check to succeed."),
    policy.RuleDefault(
        "admin_or_owner",
        "is_admin:True or project_id:%(project_id)s",
        "Default rule for most non-Admin APIs."),
    policy.RuleDefault(
        "admin_api",
        "is_admin:True",
        "Default rule for most Admin APIs.")
]


def list_rules():
    return rules
