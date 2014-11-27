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

import webob

from nova.api.openstack.compute.contrib import shelve as shelve_v2
from nova.api.openstack.compute.plugins.v3 import shelve as shelve_v21
from nova.compute import api as compute_api
from nova import db
from nova import exception
from nova.openstack.common import policy as common_policy
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


def fake_instance_get_by_uuid(context, instance_id,
                              columns_to_join=None, use_slave=False):
    return fake_instance.fake_db_instance(
        **{'name': 'fake', 'project_id': '%s_unequal' % context.project_id})


def fake_auth_context(context):
    return True


class ShelvePolicyTestV21(test.NoDBTestCase):
    plugin = shelve_v21
    prefix = 'v3:os-shelve:'
    offload = 'shelve_offload'

    def setUp(self):
        super(ShelvePolicyTestV21, self).setUp()
        self.controller = self.plugin.ShelveController()

    def _fake_request(self):
        return fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')

    def test_shelve_restricted_by_role(self):
        rules = {'compute_extension:%sshelve' % self.prefix:
                     common_policy.parse_rule('role:admin')}
        policy.set_rules(rules)

        req = self._fake_request()
        self.assertRaises(exception.Forbidden, self.controller._shelve,
                req, str(uuid.uuid4()), {})

    def test_shelve_allowed(self):
        rules = {'compute:get': common_policy.parse_rule(''),
                 'compute_extension:%sshelve' % self.prefix:
                     common_policy.parse_rule('')}
        policy.set_rules(rules)

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = self._fake_request()
        self.assertRaises(exception.Forbidden, self.controller._shelve,
                req, str(uuid.uuid4()), {})

    def test_shelve_locked_server(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        self.stubs.Set(self.plugin, 'auth_shelve', fake_auth_context)
        self.stubs.Set(compute_api.API, 'shelve',
                       fakes.fake_actions_to_locked_server)
        req = self._fake_request()
        self.assertRaises(webob.exc.HTTPConflict, self.controller._shelve,
                          req, str(uuid.uuid4()), {})

    def test_unshelve_restricted_by_role(self):
        rules = {'compute_extension:%sunshelve' % self.prefix:
                     common_policy.parse_rule('role:admin')}
        policy.set_rules(rules)

        req = self._fake_request()
        self.assertRaises(exception.Forbidden, self.controller._unshelve,
                req, str(uuid.uuid4()), {})

    def test_unshelve_allowed(self):
        rules = {'compute:get': common_policy.parse_rule(''),
                 'compute_extension:%sunshelve' % self.prefix:
                 common_policy.parse_rule('')}
        policy.set_rules(rules)

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = self._fake_request()
        self.assertRaises(exception.Forbidden, self.controller._unshelve,
                req, str(uuid.uuid4()), {})

    def test_unshelve_locked_server(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        self.stubs.Set(self.plugin, 'auth_unshelve', fake_auth_context)
        self.stubs.Set(compute_api.API, 'unshelve',
                       fakes.fake_actions_to_locked_server)
        req = self._fake_request()
        self.assertRaises(webob.exc.HTTPConflict, self.controller._unshelve,
                          req, str(uuid.uuid4()), {})

    def test_shelve_offload_restricted_by_role(self):
        rules = {'compute_extension:%s%s' % (self.prefix, self.offload):
                  common_policy.parse_rule('role:admin')}
        policy.set_rules(rules)

        req = self._fake_request()
        self.assertRaises(exception.Forbidden,
                self.controller._shelve_offload, req, str(uuid.uuid4()), {})

    def test_shelve_offload_allowed(self):
        rules = {'compute:get': common_policy.parse_rule(''),
                 'compute_extension:%s%s' % (self.prefix, self.offload):
                     common_policy.parse_rule('')}
        policy.set_rules(rules)

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = self._fake_request()
        self.assertRaises(exception.Forbidden,
                self.controller._shelve_offload, req, str(uuid.uuid4()), {})

    def test_shelve_offload_locked_server(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        self.stubs.Set(self.plugin, 'auth_shelve_offload', fake_auth_context)
        self.stubs.Set(compute_api.API, 'shelve_offload',
                       fakes.fake_actions_to_locked_server)
        req = self._fake_request()
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._shelve_offload,
                          req, str(uuid.uuid4()), {})


class ShelvePolicyTestV2(ShelvePolicyTestV21):
    plugin = shelve_v2
    prefix = ''
    offload = 'shelveOffload'
