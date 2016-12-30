# Copyright 2011 Eldar Nugaev
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

import mock
from oslo_serialization import jsonutils

from nova.api.openstack import compute
from nova.api.openstack.compute import server_diagnostics
from nova.compute import api as compute_api
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


UUID = 'abc'


def fake_get_diagnostics(self, _context, instance_uuid):
    return {'data': 'Some diagnostic info'}


def fake_instance_get(self, _context, instance_uuid, expected_attrs=None):
    if instance_uuid != UUID:
        raise Exception("Invalid UUID")
    return {'uuid': instance_uuid}


class ServerDiagnosticsTestV21(test.NoDBTestCase):

    def _setup_router(self):
        self.router = compute.APIRouterV21()

    def _get_request(self):
        return fakes.HTTPRequest.blank(
                   '/fake/servers/%s/diagnostics' % UUID)

    def setUp(self):
        super(ServerDiagnosticsTestV21, self).setUp()
        self._setup_router()

    @mock.patch.object(compute_api.API, 'get_diagnostics',
                       fake_get_diagnostics)
    @mock.patch.object(compute_api.API, 'get',
                       fake_instance_get)
    def test_get_diagnostics(self):
        req = self._get_request()
        res = req.get_response(self.router)
        output = jsonutils.loads(res.body)
        self.assertEqual(output, {'data': 'Some diagnostic info'})

    @mock.patch.object(compute_api.API, 'get_diagnostics',
                fake_get_diagnostics)
    @mock.patch.object(compute_api.API, 'get',
                side_effect=exception.InstanceNotFound(instance_id=UUID))
    def test_get_diagnostics_with_non_existed_instance(self, mock_get):
        req = self._get_request()
        res = req.get_response(self.router)
        self.assertEqual(res.status_int, 404)

    @mock.patch.object(compute_api.API, 'get_diagnostics',
                side_effect=exception.InstanceInvalidState('fake message'))
    @mock.patch.object(compute_api.API, 'get', fake_instance_get)
    def test_get_diagnostics_raise_conflict_on_invalid_state(self,
                                                  mock_get_diagnostics):
        req = self._get_request()
        res = req.get_response(self.router)
        self.assertEqual(409, res.status_int)

    @mock.patch.object(compute_api.API, 'get_diagnostics',
                       side_effect=exception.InstanceNotReady('fake message'))
    @mock.patch.object(compute_api.API, 'get', fake_instance_get)
    def test_get_diagnostics_raise_instance_not_ready(self,
                                                      mock_get_diagnostics):
        req = self._get_request()
        res = req.get_response(self.router)
        self.assertEqual(409, res.status_int)

    @mock.patch.object(compute_api.API, 'get_diagnostics',
                side_effect=NotImplementedError)
    @mock.patch.object(compute_api.API, 'get', fake_instance_get)
    def test_get_diagnostics_raise_no_notimplementederror(self,
                      mock_get_diagnostics):
        req = self._get_request()
        res = req.get_response(self.router)
        self.assertEqual(501, res.status_int)


class ServerDiagnosticsEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(ServerDiagnosticsEnforcementV21, self).setUp()
        self.controller = server_diagnostics.ServerDiagnosticsController()
        self.req = fakes.HTTPRequest.blank('')

    def test_get_diagnostics_policy_failed(self):
        rule_name = "os_compute_api:os-server-diagnostics"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())
