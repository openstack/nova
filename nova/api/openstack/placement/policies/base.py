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

RULE_ADMIN_API = 'rule:admin_api'

rules = [
    # "placement" is the default rule (action) used for all routes that do
    # not yet have granular policy rules. It is used in
    # PlacementHandler.__call__ and can be dropped once all routes have
    # granular policy handling.
    policy.RuleDefault(
        "placement",
        "role:admin",
        description="This rule is used for all routes that do not yet "
                    "have granular policy rules. It will be replaced "
                    "with rule:admin_api.",
        deprecated_for_removal=True,
        deprecated_reason="This was a catch-all rule hard-coded into "
                          "the placement service and has been superseded by "
                          "granular policy rules per operation.",
        deprecated_since="18.0.0"),
    policy.RuleDefault(
        "admin_api",
        "role:admin",
        description="Default rule for most placement APIs.",
        scope_types=['system']),
]


def list_rules():
    return rules
