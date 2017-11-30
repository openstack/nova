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

import os

from oslo_policy import policy as oslo_policy
import testtools

from nova.api.openstack.placement import context
from nova.api.openstack.placement import exception
from nova.api.openstack.placement import policy
from nova.tests.unit import conf_fixture
from nova.tests.unit import policy_fixture
from nova import utils


class PlacementPolicyTestCase(testtools.TestCase):
    """Tests interactions with placement policy.

    These tests do not rely on the base nova.test.TestCase to avoid
    interference from the PlacementPolicyFixture which is not used in all
    test cases.
    """
    def setUp(self):
        super(PlacementPolicyTestCase, self).setUp()
        self.conf = self.useFixture(conf_fixture.ConfFixture()).conf
        self.ctxt = context.RequestContext(user_id='fake', project_id='fake')
        self.target = {'user_id': 'fake', 'project_id': 'fake'}

    def test_modified_policy_reloads(self):
        """Creates a temporary placement-policy.yaml file and tests
        authorizations against a fake rule between updates to the physical
        policy file.
        """
        with utils.tempdir() as tmpdir:
            tmpfilename = os.path.join(tmpdir, 'placement-policy.yaml')

            self.conf.set_default(
                'policy_file', tmpfilename, group='placement')

            action = 'placement:test'
            # Expect PolicyNotRegistered since defaults are not yet loaded.
            self.assertRaises(oslo_policy.PolicyNotRegistered,
                              policy.authorize, self.ctxt, action, self.target)

            # Load the default action and rule (defaults to "any").
            enforcer = policy.get_enforcer()
            rule = oslo_policy.RuleDefault(action, '')
            enforcer.register_default(rule)

            # Now auth should work because the action is registered and anyone
            # can perform the action.
            policy.authorize(self.ctxt, action, self.target)

            # Now update the policy file and reload it to disable the action
            # from all users.
            with open(tmpfilename, "w") as policyfile:
                policyfile.write('"%s": "!"' % action)
            enforcer.load_rules(force_reload=True)
            self.assertRaises(exception.PolicyNotAuthorized, policy.authorize,
                              self.ctxt, action, self.target)

    def test_authorize_do_raise_false(self):
        """Tests that authorize does not raise an exception when the check
        fails.
        """
        fixture = self.useFixture(policy_fixture.PlacementPolicyFixture())
        fixture.set_rules({'placement': '!'})
        self.assertFalse(
            policy.authorize(
                self.ctxt, 'placement', self.target, do_raise=False))
