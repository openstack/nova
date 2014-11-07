#   Copyright 2013 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import uuid

import mock
from oslo.serialization import jsonutils
import webob

from nova.compute import vm_states
from nova import context
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


class ExtendedEvacuateFindHostTest(test.NoDBTestCase):

    def setUp(self):
        super(ExtendedEvacuateFindHostTest, self).setUp()
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Extended_evacuate_find_host',
                                    'Evacuate'])
        self.UUID = uuid.uuid4()

    def _get_admin_context(self, user_id='fake', project_id='fake'):
        ctxt = context.get_admin_context()
        ctxt.user_id = user_id
        ctxt.project_id = project_id
        return ctxt

    def _fake_compute_api(*args, **kwargs):
        return True

    def _fake_compute_api_get(self, context, instance_id, **kwargs):
        instance = fake_instance.fake_db_instance(id=1, uuid=uuid,
                                                  task_state=None,
                                                  host='host1',
                                                  vm_state=vm_states.ACTIVE)
        instance = instance_obj.Instance._from_db_object(context,
                                                    instance_obj.Instance(),
                                                    instance)
        return instance

    def _fake_service_get_by_compute_host(self, context, host):
        return {'host_name': host,
                'service': 'compute',
                'zone': 'nova'
                }

    @mock.patch('nova.compute.api.HostAPI.service_get_by_compute_host')
    @mock.patch('nova.compute.api.API.get')
    @mock.patch('nova.compute.api.API.evacuate')
    def test_evacuate_instance_with_no_target(self, evacuate_mock,
                                              api_get_mock,
                                              service_get_mock):
        service_get_mock.side_effects = self._fake_service_get_by_compute_host
        api_get_mock.side_effects = self._fake_compute_api_get
        evacuate_mock.side_effects = self._fake_compute_api

        ctxt = self._get_admin_context()
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % self.UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'onSharedStorage': 'False',
                'adminPass': 'MyNewPass'
            }
        })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(200, res.status_int)
        evacuate_mock.assert_called_once_with(mock.ANY, mock.ANY, None,
                                    mock.ANY, mock.ANY)

    @mock.patch('nova.compute.api.HostAPI.service_get_by_compute_host')
    @mock.patch('nova.compute.api.API.get')
    def test_no_target_fails_if_extension_not_loaded(self, api_get_mock,
                                                     service_get_mock):
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Evacuate'])
        service_get_mock.side_effects = self._fake_service_get_by_compute_host
        api_get_mock.side_effects = self._fake_compute_api_get

        ctxt = self._get_admin_context()
        app = fakes.wsgi_app(fake_auth_context=ctxt)
        req = webob.Request.blank('/v2/fake/servers/%s/action' % self.UUID)
        req.method = 'POST'
        req.body = jsonutils.dumps({
            'evacuate': {
                'onSharedStorage': 'False',
                'adminPass': 'MyNewPass'
            }
        })
        req.content_type = 'application/json'
        res = req.get_response(app)
        self.assertEqual(400, res.status_int)
