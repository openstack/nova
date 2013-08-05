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

from nova.api.openstack.compute.plugins.v3 import shelve
from nova import db
from nova import exception
from nova.openstack.common import policy
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


class ShelvePolicyTest(test.NoDBTestCase):
    def setUp(self):
        super(ShelvePolicyTest, self).setUp()
        self.controller = shelve.ShelveController()

    def test_shelve_restricted_by_role(self):
        rules = policy.Rules({'compute_extension:v3:os-shelve:shelve':
                              policy.parse_rule('role:admin')})
        policy.set_rules(rules)

        req = fakes.HTTPRequest.blank('/v3/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized, self.controller._shelve,
                req, str(uuid.uuid4()), {})

    def test_shelve_allowed(self):
        rules = policy.Rules({'compute:get': policy.parse_rule(''),
                              'compute_extension:v3:os-shelve:shelve':
                              policy.parse_rule('')})
        policy.set_rules(rules)

        def fake_instance_get_by_uuid(context, instance_id,
                                      columns_to_join=None,
                                      use_slave=False):
            return fake_instance.fake_db_instance(
                **{'name': 'fake', 'project_id': '%s_unequal' %
                       context.project_id})

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = fakes.HTTPRequest.blank('/v3/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized, self.controller._shelve,
                req, str(uuid.uuid4()), {})

    def test_unshelve_restricted_by_role(self):
        rules = policy.Rules({'compute_extension:v3:os-shelve:unshelve':
                              policy.parse_rule('role:admin')})
        policy.set_rules(rules)

        req = fakes.HTTPRequest.blank('/v3/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized, self.controller._unshelve,
                req, str(uuid.uuid4()), {})

    def test_unshelve_allowed(self):
        rules = policy.Rules({'compute:get': policy.parse_rule(''),
                              'compute_extension:v3:os-shelve:unshelve':
                              policy.parse_rule('')})
        policy.set_rules(rules)

        def fake_instance_get_by_uuid(context, instance_id,
                                      columns_to_join=None,
                                      use_slave=False):
            return fake_instance.fake_db_instance(
                **{'name': 'fake', 'project_id': '%s_unequal' %
                       context.project_id})

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = fakes.HTTPRequest.blank('/v3/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized, self.controller._unshelve,
                req, str(uuid.uuid4()), {})

    def test_shelve_offload_restricted_by_role(self):
        rules = policy.Rules({'compute_extension:v3:os-shelve:shelve_offload':
                              policy.parse_rule('role:admin')})
        policy.set_rules(rules)

        req = fakes.HTTPRequest.blank('/v3/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized,
                self.controller._shelve_offload, req, str(uuid.uuid4()), {})

    def test_shelve_offload_allowed(self):
        rules = policy.Rules({'compute:get': policy.parse_rule(''),
                              'compute_extension:v3:shelve_offload':
                              policy.parse_rule('')})
        policy.set_rules(rules)

        def fake_instance_get_by_uuid(context, instance_id,
                                      columns_to_join=None):
            return fake_instance.fake_db_instance(
                **{'name': 'fake', 'project_id': '%s_unequal' %
                       context.project_id})

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = fakes.HTTPRequest.blank('/v3/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized,
                self.controller._shelve_offload, req, str(uuid.uuid4()), {})
