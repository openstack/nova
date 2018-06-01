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

import mock
import testtools

from nova.api.openstack.placement import context
from nova.api.openstack.placement import exception


class TestPlacementRequestContext(testtools.TestCase):
    """Test cases for PlacementRequestContext."""

    def setUp(self):
        super(TestPlacementRequestContext, self).setUp()
        self.ctxt = context.RequestContext(user_id='fake', project_id='fake')
        self.default_target = {'user_id': self.ctxt.user_id,
                               'project_id': self.ctxt.project_id}

    @mock.patch('nova.api.openstack.placement.policy.authorize',
                return_value=True)
    def test_can_target_none_fatal_true_accept(self, mock_authorize):
        self.assertTrue(self.ctxt.can('placement:resource_providers:list'))
        mock_authorize.assert_called_once_with(
            self.ctxt, 'placement:resource_providers:list',
            self.default_target)

    @mock.patch('nova.api.openstack.placement.policy.authorize',
                side_effect=exception.PolicyNotAuthorized(
                    action='placement:resource_providers:list'))
    def test_can_target_none_fatal_true_reject(self, mock_authorize):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.ctxt.can, 'placement:resource_providers:list')
        mock_authorize.assert_called_once_with(
            self.ctxt, 'placement:resource_providers:list',
            self.default_target)

    @mock.patch('nova.api.openstack.placement.policy.authorize',
                side_effect=exception.PolicyNotAuthorized(
                    action='placement:resource_providers:list'))
    def test_can_target_none_fatal_false_reject(self, mock_authorize):
        self.assertFalse(self.ctxt.can('placement:resource_providers:list',
                                       fatal=False))
        mock_authorize.assert_called_once_with(
            self.ctxt, 'placement:resource_providers:list',
            self.default_target)

    @mock.patch('nova.api.openstack.placement.policy.authorize',
                return_value=True)
    def test_can_target_none_fatal_true_accept_custom_target(
            self, mock_authorize):
        class MyObj(object):
            user_id = project_id = 'fake2'

        target = MyObj()
        self.assertTrue(self.ctxt.can('placement:resource_providers:list',
                                      target=target))
        mock_authorize.assert_called_once_with(
            self.ctxt, 'placement:resource_providers:list', target)
