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
from oslo.serialization import jsonutils
import webob

from nova.api.openstack.compute.contrib import evacuate as evacuate_v2
from nova.api.openstack.compute.plugins.v3 import evacuate as evacuate_v21
from nova.api.openstack import extensions
from nova.compute import api as compute_api
from nova.compute import vm_states
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


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
    validation_error = exception.ValidationError
    _methods = ('resize', 'evacuate')

    def setUp(self):
        super(EvacuateTestV21, self).setUp()
        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get)
        self.stubs.Set(compute_api.HostAPI, 'service_get_by_compute_host',
                       fake_service_get_by_compute_host)
        self.UUID = uuid.uuid4()
        for _method in self._methods:
            self.stubs.Set(compute_api.API, _method, fake_compute_api)
        self._set_up_controller()

    def _set_up_controller(self):
        self.controller = evacuate_v21.EvacuateController()

    def _get_evacuate_response(self, json_load, uuid=None):
        base_json_load = {'evacuate': json_load}
        req = fakes.HTTPRequest.blank('', use_admin_context=True)
        req.body = jsonutils.dumps(base_json_load)
        response = self.controller._evacuate(req, uuid or self.UUID,
                                             body=base_json_load)

        return response

    def _check_evacuate_failure(self, exception, body, uuid=None):
        body = {'evacuate': body}
        req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.assertRaises(exception,
                          self.controller._evacuate,
                          req, uuid or self.UUID, body=body)

    def _fake_update(self, inst, context, instance, task_state,
                     expected_task_state):
        return None

    def test_evacuate_with_valid_instance(self):
        admin_pass = 'MyNewPass'
        res = self._get_evacuate_response({'host': 'my-host',
                                           'onSharedStorage': 'False',
                                           'adminPass': admin_pass})

        self.assertEqual(admin_pass, res['adminPass'])

    def test_evacuate_with_invalid_instance(self):
        self._check_evacuate_failure(webob.exc.HTTPNotFound,
                                     {'host': 'my-host',
                                      'onSharedStorage': 'False',
                                      'adminPass': 'MyNewPass'},
                                     uuid='BAD_UUID')

    def test_evacuate_with_active_service(self):
        def fake_evacuate(*args, **kwargs):
            raise exception.ComputeServiceInUse("Service still in use")

        self.stubs.Set(compute_api.API, 'evacuate', fake_evacuate)
        self._check_evacuate_failure(webob.exc.HTTPBadRequest,
                                     {'host': 'my-host',
                                      'onSharedStorage': 'False',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_instance_with_no_target(self):
        admin_pass = 'MyNewPass'
        res = self._get_evacuate_response({'onSharedStorage': 'False',
                                           'adminPass': admin_pass})

        self.assertEqual(admin_pass, res['adminPass'])

    def test_evacuate_instance_without_on_shared_storage(self):
        self._check_evacuate_failure(self.validation_error,
                                     {'host': 'my-host',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_instance_with_invalid_characters_host(self):
        host = 'abc!#'
        self._check_evacuate_failure(self.validation_error,
                                     {'host': host,
                                      'onSharedStorage': 'False',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_instance_with_too_long_host(self):
        host = 'a' * 256
        self._check_evacuate_failure(self.validation_error,
                                     {'host': host,
                                      'onSharedStorage': 'False',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_instance_with_invalid_on_shared_storage(self):
        self._check_evacuate_failure(self.validation_error,
                                     {'host': 'my-host',
                                      'onSharedStorage': 'foo',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_instance_with_bad_target(self):
        self._check_evacuate_failure(webob.exc.HTTPNotFound,
                                     {'host': 'bad-host',
                                      'onSharedStorage': 'False',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_instance_with_target(self):
        self.stubs.Set(compute_api.API, 'update', self._fake_update)

        admin_pass = 'MyNewPass'
        res = self._get_evacuate_response({'host': 'my-host',
                                           'onSharedStorage': 'False',
                                           'adminPass': admin_pass})

        self.assertEqual(admin_pass, res['adminPass'])

    def test_evacuate_shared_and_pass(self):
        self.stubs.Set(compute_api.API, 'update', self._fake_update)
        self._check_evacuate_failure(webob.exc.HTTPBadRequest,
                                     {'host': 'bad-host',
                                      'onSharedStorage': 'True',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_not_shared_pass_generated(self):
        self.stubs.Set(compute_api.API, 'update', self._fake_update)
        res = self._get_evacuate_response({'host': 'my-host',
                                           'onSharedStorage': 'False'})
        self.assertEqual(CONF.password_length, len(res['adminPass']))

    def test_evacuate_shared(self):
        self.stubs.Set(compute_api.API, 'update', self._fake_update)
        self._get_evacuate_response({'host': 'my-host',
                                     'onSharedStorage': 'True'})

    def test_not_admin(self):
        body = {'evacuate': {'host': 'my-host',
                             'onSharedStorage': 'False'}}
        req = fakes.HTTPRequest.blank('', use_admin_context=False)
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._evacuate,
                          req, self.UUID, body=body)

    def test_evacuate_to_same_host(self):
        self._check_evacuate_failure(webob.exc.HTTPBadRequest,
                                     {'host': 'host1',
                                      'onSharedStorage': 'False',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_instance_with_empty_host(self):
        self._check_evacuate_failure(self.validation_error,
                                     {'host': '',
                                      'onSharedStorage': 'False',
                                      'adminPass': 'MyNewPass'})

    def test_evacuate_instance_with_underscore_in_hostname(self):
        # NOTE: The hostname grammar in RFC952 does not allow for
        # underscores in hostnames. However, we should test that it
        # is supported because it sometimes occurs in real systems.
        admin_pass = 'MyNewPass'
        self.stubs.Set(compute_api.API, 'update', self._fake_update)
        res = self._get_evacuate_response({'host': 'underscore_hostname',
                                           'onSharedStorage': 'False',
                                           'adminPass': admin_pass})

        self.assertEqual(admin_pass, res['adminPass'])

    def test_evacuate_disable_password_return(self):
        self._test_evacuate_enable_instance_password_conf(False)

    def test_evacuate_enable_password_return(self):
        self._test_evacuate_enable_instance_password_conf(True)

    def _test_evacuate_enable_instance_password_conf(self, enable_pass):
        self.flags(enable_instance_password=enable_pass)
        self.stubs.Set(compute_api.API, 'update', self._fake_update)

        res = self._get_evacuate_response({'host': 'underscore_hostname',
                                           'onSharedStorage': 'False'})
        if enable_pass:
            self.assertIn('adminPass', res)
        else:
            self.assertIsNone(res.get('adminPass'))


class EvacuateTestV2(EvacuateTestV21):
    validation_error = webob.exc.HTTPBadRequest

    def _set_up_controller(self):
        ext_mgr = extensions.ExtensionManager()
        ext_mgr.extensions = {'os-evacuate': 'fake'}
        self.controller = evacuate_v2.Controller(ext_mgr)

    def test_evacuate_instance_with_no_target(self):
        self._check_evacuate_failure(webob.exc.HTTPBadRequest,
                                     {'onSharedStorage': 'False',
                                      'adminPass': 'MyNewPass'})

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
