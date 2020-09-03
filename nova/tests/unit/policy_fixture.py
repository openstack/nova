# Copyright 2012 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os

import fixtures
from oslo_policy import policy as oslo_policy
from oslo_serialization import jsonutils

import nova.conf
from nova.conf import paths
from nova import policies
import nova.policy
from nova.tests.unit import fake_policy

CONF = nova.conf.CONF


class RealPolicyFixture(fixtures.Fixture):
    """Load the live policy for tests.

    A base policy fixture that starts with the assumption that you'd
    like to load and enforce the shipped default policy in tests.

    Provides interfaces to tinker with both the contents and location
    of the policy file before loading to allow overrides. To do this
    implement ``_prepare_policy`` in the subclass, and adjust the
    ``policy_file`` accordingly.

    """
    def _prepare_policy(self):
        """Allow changing of the policy before we get started"""
        pass

    def setUp(self):
        super(RealPolicyFixture, self).setUp()
        # policy_file can be overridden by subclasses
        self.policy_file = paths.state_path_def('etc/nova/policy.yaml')
        self._prepare_policy()
        CONF.set_override('policy_file', self.policy_file, group='oslo_policy')
        nova.policy.reset()
        # NOTE(gmann): Logging all the deprecation warning for every unit
        # test will overflow the log files. Suppress the deprecation warnings
        # for tests.
        nova.policy.init(suppress_deprecation_warnings=True)
        self.addCleanup(nova.policy.reset)

    def set_rules(self, rules, overwrite=True):
        policy = nova.policy._ENFORCER
        policy.set_rules(oslo_policy.Rules.from_dict(rules),
                         overwrite=overwrite)

    def add_missing_default_rules(self, rules):
        """Adds default rules and their values to the given rules dict.

        The given rulen dict may have an incomplete set of policy rules.
        This method will add the default policy rules and their values to
        the dict. It will not override the existing rules.
        """

        for rule in policies.list_rules():
            # NOTE(lbragstad): Only write the rule if it isn't already in the
            # rule set and if it isn't deprecated. Otherwise we're just going
            # to spam test runs with deprecate policy warnings.
            if rule.name not in rules and not rule.deprecated_for_removal:
                rules[rule.name] = rule.check_str


class PolicyFixture(RealPolicyFixture):
    """Load a fake policy from nova.tests.unit.fake_policy

    This overrides the policy with a completely fake and synthetic
    policy file.

    NOTE(sdague): the use of this is deprecated, and we should unwind
    the tests so that they can function with the real policy. This is
    mostly legacy because our default test instances and default test
    contexts don't match up. It appears that in many cases fake_policy
    was just modified to whatever makes tests pass, which makes it
    dangerous to be used in tree. Long term a NullPolicy fixture might
    be better in those cases.

    """
    def _prepare_policy(self):
        self.policy_dir = self.useFixture(fixtures.TempDir())
        self.policy_file = os.path.join(self.policy_dir.path,
                                        'policy.yaml')

        # load the fake_policy data and add the missing default rules.
        policy_rules = jsonutils.loads(fake_policy.policy_data)
        self.add_missing_default_rules(policy_rules)
        with open(self.policy_file, 'w') as f:
            jsonutils.dump(policy_rules, f)
        CONF.set_override('policy_dirs', [], group='oslo_policy')


class RoleBasedPolicyFixture(RealPolicyFixture):
    """Load a modified policy which allows all actions only by a single role.

    This fixture can be used for testing role based permissions as it
    provides a version of the policy which stomps over all previous
    declaration and makes every action only available to a single
    role.

    """

    def __init__(self, role="admin", *args, **kwargs):
        super(RoleBasedPolicyFixture, self).__init__(*args, **kwargs)
        self.role = role

    def _prepare_policy(self):
        # Convert all actions to require the specified role
        policy = {}
        for rule in policies.list_rules():
            policy[rule.name] = 'role:%s' % self.role

        self.policy_dir = self.useFixture(fixtures.TempDir())
        self.policy_file = os.path.join(self.policy_dir.path, 'policy.yaml')
        with open(self.policy_file, 'w') as f:
            jsonutils.dump(policy, f)


class OverridePolicyFixture(RealPolicyFixture):
    """Load the set of requested rules into policy file
    This overrides the policy with the requested rules only into
    policy file. This fixture is to verify the use case where operator
    has overridden the policy rules in policy file means default policy
    not used. One example is when policy rules are deprecated. In that case
    tests can use this fixture and verify if deprecated rules are overridden
    then does nova code enforce the overridden rules not only defaults.
    As per oslo.policy deprecattion feature, if deprecated rule is overridden
    in policy file then, overridden check is used to verify the policy.
    Example of usage:

        self.deprecated_policy = "os_compute_api:os-services"
        # set check_str as different than defaults to verify the
        # rule overridden case.
        override_rules = {self.deprecated_policy: 'is_admin:True'}
        # NOTE(gmann): Only override the deprecated rule in policy file so that
        # we can verify if overridden checks are considered by oslo.policy.
        # Oslo.policy will consider the overridden rules if:
        #  1. overridden checks are different than defaults
        #  2. new rules for deprecated rules are not present in policy file
        self.policy = self.useFixture(policy_fixture.OverridePolicyFixture(
                                      rules_in_file=override_rules))

    """

    def __init__(self, rules_in_file, *args, **kwargs):
        self.rules_in_file = rules_in_file
        super(OverridePolicyFixture, self).__init__(*args, **kwargs)

    def _prepare_policy(self):
        self.policy_dir = self.useFixture(fixtures.TempDir())
        self.policy_file = os.path.join(self.policy_dir.path,
                                        'policy.yaml')
        with open(self.policy_file, 'w') as f:
            jsonutils.dump(self.rules_in_file, f)
        CONF.set_override('policy_dirs', [], group='oslo_policy')
