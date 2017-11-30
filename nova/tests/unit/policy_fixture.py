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

from nova.api.openstack.placement import policy as placement_policy
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
        self.policy_file = paths.state_path_def('etc/nova/policy.json')
        self._prepare_policy()
        CONF.set_override('policy_file', self.policy_file, group='oslo_policy')
        nova.policy.reset()
        nova.policy.init()
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
                                        'policy.json')

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
        self.policy_file = os.path.join(self.policy_dir.path, 'policy.json')
        with open(self.policy_file, 'w') as f:
            jsonutils.dump(policy, f)


class PlacementPolicyFixture(fixtures.Fixture):
    """Load the default placement policy for tests.

    This fixture requires nova.tests.unit.conf_fixture.ConfFixture.
    """
    def setUp(self):
        super(PlacementPolicyFixture, self).setUp()
        policy_file = paths.state_path_def('etc/nova/placement-policy.yaml')
        CONF.set_override('policy_file', policy_file, group='placement')
        placement_policy.reset()
        placement_policy.init()
        self.addCleanup(placement_policy.reset)

    @staticmethod
    def set_rules(rules, overwrite=True):
        """Set placement policy rules.

        .. note:: The rules must first be registered via the
                  Enforcer.register_defaults method.

        :param rules: dict of action=rule mappings to set
        :param overwrite: Whether to overwrite current rules or update them
                          with the new rules.
        """
        enforcer = placement_policy.get_enforcer()
        enforcer.set_rules(oslo_policy.Rules.from_dict(rules),
                           overwrite=overwrite)
