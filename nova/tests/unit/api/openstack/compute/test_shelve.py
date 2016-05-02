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

import uuid

import mock
from oslo_policy import policy as oslo_policy
import webob

from nova.api.openstack.compute import shelve as shelve_v21
from nova.compute import api as compute_api
from nova import exception
from nova import objects
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests import uuidsentinel


class ShelvePolicyTestV21(test.NoDBTestCase):
    plugin = shelve_v21
    prefix = 'os_compute_api:os-shelve'
    offload = 'shelve_offload'

    def setUp(self):
        super(ShelvePolicyTestV21, self).setUp()
        self.controller = self.plugin.ShelveController()
        self.req = fakes.HTTPRequest.blank('')

    def test_shelve_restricted_by_role(self):
        rules = {'compute_extension:%sshelve' % self.prefix: 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

        self.assertRaises(exception.Forbidden, self.controller._shelve,
                self.req, str(uuid.uuid4()), {})

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    def test_shelve_locked_server(self, mock_instance_get):
        instance = objects.Instance(uuid=uuidsentinel.instance1)
        mock_instance_get.return_value = instance
        self.stubs.Set(compute_api.API, 'shelve',
                       fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self.controller._shelve,
                          self.req, str(uuid.uuid4()), {})

    def test_unshelve_restricted_by_role(self):
        rules = {'compute_extension:%sunshelve' % self.prefix: 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

        self.assertRaises(exception.Forbidden, self.controller._unshelve,
                self.req, str(uuid.uuid4()), {})

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    def test_unshelve_locked_server(self, mock_instance_get):
        instance = objects.Instance(uuid=uuidsentinel.instance1)
        mock_instance_get.return_value = instance
        self.stubs.Set(compute_api.API, 'unshelve',
                       fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self.controller._unshelve,
                          self.req, str(uuid.uuid4()), {})

    def test_shelve_offload_restricted_by_role(self):
        rules = {'compute_extension:%s%s' % (self.prefix, self.offload):
                     'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

        self.assertRaises(exception.Forbidden,
                self.controller._shelve_offload, self.req,
                str(uuid.uuid4()), {})

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    def test_shelve_offload_locked_server(self, mock_instance_get):
        instance = objects.Instance(uuid=uuidsentinel.instance1)
        mock_instance_get.return_value = instance
        self.stubs.Set(compute_api.API, 'shelve_offload',
                       fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._shelve_offload,
                          self.req, str(uuid.uuid4()), {})


class ShelvePolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(ShelvePolicyEnforcementV21, self).setUp()
        self.controller = shelve_v21.ShelveController()
        self.req = fakes.HTTPRequest.blank('')

    def test_shelve_policy_failed(self):
        rule_name = "os_compute_api:os-shelve:shelve"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._shelve, self.req, fakes.FAKE_UUID,
            body={'shelve': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_shelve_offload_policy_failed(self):
        rule_name = "os_compute_api:os-shelve:shelve_offload"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._shelve_offload, self.req, fakes.FAKE_UUID,
            body={'shelve_offload': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_unshelve_policy_failed(self):
        rule_name = "os_compute_api:os-shelve:unshelve"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._unshelve, self.req, fakes.FAKE_UUID,
            body={'unshelve': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())
