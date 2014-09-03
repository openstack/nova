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

from oslo.config import cfg
import webob

from nova.compute import api as compute_api
from nova.compute import vm_states
from nova import context
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')


def fake_compute_api(*args, **kwargs):
    return True


def fake_compute_api_get(self, context, instance_id, want_objects=False,
                         **kwargs):
    # BAD_UUID is something that does not exist
    if instance_id == 'BAD_UUID':
        raise exception.InstanceNotFound(instance_id=instance_id)
    else:
        return fake_instance.fake_instance_obj(context, id=1, uuid=instance_id,
                                               task_state=None, host='host1',
                                               vm_state=vm_states.ACTIVE)


def fake_service_get_by_compute_host(self, context, host):
    if host == 'bad-host':
        raise exception.ComputeHostNotFound(host=host)
    else:
        return {
            'host_name': host,
            'service': 'compute',
            'zone': 'nova'
            }


class EvacuateTestV21(test.NoDBTestCase):

    _methods = ('resize', 'evacuate')
    fake_url = '/v3'

    def setUp(self):
        super(EvacuateTestV21, self).setUp()
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get)
        self.stubs.Set(compute_api.HostAPI, 'service_get_by_compute_host',
                       fake_service_get_by_compute_host)
        self.UUID = uuid.uuid4()
        for _method in self._methods:
            self.stubs.Set(compute_api.API, _method, fake_compute_api)

    def _fake_wsgi_app(self, ctxt):
        return fakes.wsgi_app_v3(fake_auth_context=ctxt)

    def _gen_resource_with_app(self, json_load, is_admin=True, uuid=None):
        ctxt = context.get_admin_context()
        ctxt.user_id = 'fake'
        ctxt.project_id = 'fake'
        ctxt.is_admin = is_admin
        app = self._fake_wsgi_app(ctxt)
        req = webob.Request.blank('%s/servers/%s/action' % (self.fake_url,
                                  uuid or self.UUID))
        req.method = 'POST'
        base_json_load = {'evacuate': json_load}
        req.body = jsonutils.dumps(base_json_load)
        req.content_type = 'application/json'

        return req.get_response(app)

    def _fake_update(self, inst, context, instance, task_state,
                     expected_task_state):
        return None

    def test_evacuate_with_valid_instance(self):
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})

        self.assertEqual(res.status_int, 200)

    def test_evacuate_with_invalid_instance(self):
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'},
                                           uuid='BAD_UUID')

        self.assertEqual(res.status_int, 404)

    def test_evacuate_with_active_service(self):
        def fake_evacuate(*args, **kwargs):
            raise exception.ComputeServiceInUse("Service still in use")

        self.stubs.Set(compute_api.API, 'evacuate', fake_evacuate)
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(res.status_int, 400)

    def test_evacuate_instance_with_no_target(self):
        res = self._gen_resource_with_app({'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(200, res.status_int)

    def test_evacuate_instance_without_on_shared_storage(self):
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(res.status_int, 400)

    def test_evacuate_instance_with_invalid_characters_host(self):
        host = 'abc!#'
        res = self._gen_resource_with_app({'host': host,
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(400, res.status_int)

    def test_evacuate_instance_with_too_long_host(self):
        host = 'a' * 256
        res = self._gen_resource_with_app({'host': host,
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(400, res.status_int)

    def test_evacuate_instance_with_invalid_on_shared_storage(self):
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'foo',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(400, res.status_int)

    def test_evacuate_instance_with_bad_target(self):
        res = self._gen_resource_with_app({'host': 'bad-host',
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(res.status_int, 404)

    def test_evacuate_instance_with_target(self):
        self.stubs.Set(compute_api.API, 'update', self._fake_update)

        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(res.status_int, 200)
        resp_json = jsonutils.loads(res.body)
        self.assertEqual("MyNewPass", resp_json['adminPass'])

    def test_evacuate_shared_and_pass(self):
        self.stubs.Set(compute_api.API, 'update', self._fake_update)
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'True',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(res.status_int, 400)

    def test_evacuate_not_shared_pass_generated(self):
        self.stubs.Set(compute_api.API, 'update', self._fake_update)
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'False'})
        self.assertEqual(res.status_int, 200)
        resp_json = jsonutils.loads(res.body)
        self.assertEqual(CONF.password_length, len(resp_json['adminPass']))

    def test_evacuate_shared(self):
        self.stubs.Set(compute_api.API, 'update', self._fake_update)
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'True'})
        self.assertEqual(res.status_int, 200)

    def test_not_admin(self):
        res = self._gen_resource_with_app({'host': 'my-host',
                                           'onSharedStorage': 'True'},
                                          is_admin=False)
        self.assertEqual(res.status_int, 403)

    def test_evacuate_to_same_host(self):
        res = self._gen_resource_with_app({'host': 'host1',
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(res.status_int, 400)

    def test_evacuate_instance_with_empty_host(self):
        res = self._gen_resource_with_app({'host': '',
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(400, res.status_int)

    def test_evacuate_instance_with_underscore_in_hostname(self):
        # NOTE: The hostname grammar in RFC952 does not allow for
        # underscores in hostnames. However, we should test that it
        # is supported because it sometimes occurs in real systems.
        self.stubs.Set(compute_api.API, 'update', self._fake_update)
        res = self._gen_resource_with_app({'host': 'underscore_hostname',
                                           'onSharedStorage': 'False',
                                           'adminPass': 'MyNewPass'})
        self.assertEqual(200, res.status_int)
        resp_json = jsonutils.loads(res.body)
        self.assertEqual("MyNewPass", resp_json['adminPass'])

    def test_evacuate_disable_password_return(self):
        self._test_evacuate_enable_instance_password_conf(False)

    def test_evacuate_enable_password_return(self):
        self._test_evacuate_enable_instance_password_conf(True)

    def _test_evacuate_enable_instance_password_conf(self, enable_pass):
        self.flags(enable_instance_password=enable_pass)
        self.stubs.Set(compute_api.API, 'update', self._fake_update)

        res = self._gen_resource_with_app({'host': 'my_host',
                                           'onSharedStorage': 'False'})
        self.assertEqual(res.status_int, 200)
        resp_json = jsonutils.loads(res.body)
        if enable_pass:
            self.assertIn('adminPass', resp_json)
        else:
            self.assertIsNone(resp_json.get('adminPass'))


class EvacuateTestV2(EvacuateTestV21):
    fake_url = '/v2/fake'

    def setUp(self):
        super(EvacuateTestV2, self).setUp()
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Evacuate'])

    def _fake_wsgi_app(self, ctxt):
        return fakes.wsgi_app(fake_auth_context=ctxt)

    def test_evacuate_instance_with_no_target(self):
        res = self._gen_resource_with_app({'onSharedStorage': 'False',
                                               'adminPass': 'MyNewPass'})
        self.assertEqual(400, res.status_int)

    def test_evacuate_instance_with_too_long_host(self):
        pass

    def test_evacuate_instance_with_invalid_characters_host(self):
        pass

    def test_evacuate_instance_with_invalid_on_shared_storage(self):
        pass

    def test_evacuate_disable_password_return(self):
        pass

    def test_evacuate_enable_password_return(self):
        pass
