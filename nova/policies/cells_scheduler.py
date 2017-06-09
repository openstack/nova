# Copyright 2016 Cloudbase Solutions Srl
# All Rights Reserved.
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

from oslo_policy import policy


POLICY_ROOT = 'cells_scheduler_filter:%s'


cells_scheduler_policies = [
    policy.RuleDefault(
        POLICY_ROOT % 'DifferentCellFilter',
        'is_admin:True',
        """Different cell filter to route a build away from a particular cell

This policy is read by nova-scheduler process.
"""),
    policy.RuleDefault(
        POLICY_ROOT % 'TargetCellFilter',
        'is_admin:True',
        """Target cell filter to route a build to a particular cell

This policy is read by nova-scheduler process.
""")
]


def list_rules():
    return cells_scheduler_policies
