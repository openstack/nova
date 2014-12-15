# Copyright 2011 OpenStack Foundation
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
from mox3 import mox
from oslo.config import cfg
from oslo.serialization import jsonutils
import webob

from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import servers
from nova.compute import api as compute_api
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova import objects
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit.image import fake

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')
FAKE_UUID = fakes.FAKE_UUID
INSTANCE_IDS = {FAKE_UUID: 1}


def return_server_not_found(*arg, **kwarg):
    raise exception.InstanceNotFound(instance_id='42')


def instance_update_and_get_original(context, instance_uuid, values,
                                     update_cells=True,
                                     columns_to_join=None,
                                     ):
    inst = fakes.stub_instance(INSTANCE_IDS[instance_uuid], host='fake_host')
    inst = dict(inst, **values)
    return (inst, inst)


def instance_update(context, instance_uuid, kwargs, update_cells=True):
    inst = fakes.stub_instance(INSTANCE_IDS[instance_uuid], host='fake_host')
    return inst


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance, password):
        self.instance_id = instance['uuid']
        self.password = password


class ServerActionsControllerTest(test.TestCase):
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    image_href = 'http://localhost/v2/fake/images/%s' % image_uuid

    def setUp(self):
        super(ServerActionsControllerTest, self).setUp()

        CONF.set_override('host', 'localhost', group='glance')
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                                               host='fake_host'))
        self.stubs.Set(db, 'instance_update_and_get_original',
                       instance_update_and_get_original)

        fakes.stub_out_nw_api(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        fake.stub_out_image_service(self.stubs)
        self.flags(allow_instance_snapshots=True,
                   enable_instance_password=True)
        self.uuid = FAKE_UUID
        self.url = '/servers/%s/action' % self.uuid
        self._image_href = '155d900f-4e14-4e4c-a73d-069cbf4541e6'

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)
        self.compute_api = self.controller.compute_api
        self.context = context.RequestContext('fake', 'fake')
        self.app = fakes.wsgi_app_v21(init_only=('servers',),
                                      fake_auth_context=self.context)

    def _make_request(self, url, body):
        req = webob.Request.blank('/v2/fake' + url)
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.content_type = 'application/json'
        return req.get_response(self.app)

    def _stub_instance_get(self, uuid=None):
        self.mox.StubOutWithMock(compute_api.API, 'get')
        if uuid is None:
            uuid = uuidutils.generate_uuid()
        instance = fake_instance.fake_db_instance(
            id=1, uuid=uuid, vm_state=vm_states.ACTIVE, task_state=None)
        instance = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance)

        self.compute_api.get(self.context, uuid, want_objects=True,
                expected_attrs=['pci_devices']).AndReturn(instance)
        return instance

    def _test_locked_instance(self, action, method=None, body_map=None,
                              compute_api_args_map=None):
        if method is None:
            method = action
        if body_map is None:
            body_map = {}
        if compute_api_args_map is None:
            compute_api_args_map = {}

        instance = self._stub_instance_get()
        args, kwargs = compute_api_args_map.get(action, ((), {}))

        getattr(compute_api.API, method)(self.context, instance,
                                         *args, **kwargs).AndRaise(
            exception.InstanceIsLocked(instance_uuid=instance['uuid']))

        self.mox.ReplayAll()

        res = self._make_request('/servers/%s/action' % instance['uuid'],
                                 {action: body_map.get(action)})
        self.assertEqual(409, res.status_int)
        # Do these here instead of tearDown because this method is called
        # more than once for the same test case
        self.mox.VerifyAll()
        self.mox.UnsetStubs()

    def test_actions_with_locked_instance(self):
        actions = ['resize', 'confirmResize', 'revertResize', 'reboot',
                   'rebuild']

        method_translations = {'confirmResize': 'confirm_resize',
                               'revertResize': 'revert_resize'}

        body_map = {'resize': {'flavorRef': '2'},
                    'reboot': {'type': 'HARD'},
                    'rebuild': {'imageRef': self.image_uuid,
                                'adminPass': 'TNc53Dr8s7vw'}}

        args_map = {'resize': (('2'), {}),
                    'confirmResize': ((), {}),
                    'reboot': (('HARD',), {}),
                    'rebuild': ((self.image_uuid, 'TNc53Dr8s7vw'), {})}

        for action in actions:
            method = method_translations.get(action)
            self.mox.StubOutWithMock(compute_api.API, method or action)
            self._test_locked_instance(action, method=method,
                                       body_map=body_map,
                                       compute_api_args_map=args_map)

    def test_reboot_hard(self):
        body = dict(reboot=dict(type="HARD"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.controller._action_reboot(req, FAKE_UUID, body)

    def test_reboot_soft(self):
        body = dict(reboot=dict(type="SOFT"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.controller._action_reboot(req, FAKE_UUID, body)

    def test_reboot_incorrect_type(self):
        body = dict(reboot=dict(type="NOT_A_TYPE"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_reboot,
                          req, FAKE_UUID, body)

    def test_reboot_missing_type(self):
        body = dict(reboot=dict())
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_reboot,
                          req, FAKE_UUID, body)

    def test_reboot_none(self):
        body = dict(reboot=dict(type=None))
        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_reboot,
                          req, FAKE_UUID, body)

    def test_reboot_not_found(self):
        self.stubs.Set(db, 'instance_get_by_uuid',
                       return_server_not_found)

        body = dict(reboot=dict(type="HARD"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._action_reboot,
                          req, str(uuid.uuid4()), body)

    def test_reboot_raises_conflict_on_invalid_state(self):
        body = dict(reboot=dict(type="HARD"))

        def fake_reboot(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stubs.Set(compute_api.API, 'reboot', fake_reboot)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_reboot,
                          req, FAKE_UUID, body)

    def test_reboot_soft_with_soft_in_progress_raises_conflict(self):
        body = dict(reboot=dict(type="SOFT"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                                            task_state=task_states.REBOOTING))
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_reboot,
                          req, FAKE_UUID, body)

    def test_reboot_hard_with_soft_in_progress_does_not_raise(self):
        body = dict(reboot=dict(type="HARD"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                                        task_state=task_states.REBOOTING))
        self.controller._action_reboot(req, FAKE_UUID, body)

    def test_reboot_hard_with_hard_in_progress(self):
        body = dict(reboot=dict(type="HARD"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                                        task_state=task_states.REBOOTING_HARD))
        self.controller._action_reboot(req, FAKE_UUID, body)

    def test_rebuild_accepted_minimum(self):
        return_server = fakes.fake_instance_get(image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)
        self_href = 'http://localhost/v3/servers/%s' % FAKE_UUID

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        robj = self.controller._action_rebuild(req, FAKE_UUID, body=body)
        body = robj.obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(len(body['server']['adminPass']),
                         CONF.password_length)

        self.assertEqual(robj['location'], self_href)

    def test_rebuild_instance_with_image_uuid(self):
        info = dict(image_href_in_call=None)

        def rebuild(self2, context, instance, image_href, *args, **kwargs):
            info['image_href_in_call'] = image_href

        self.stubs.Set(db, 'instance_get',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        self.stubs.Set(compute_api.API, 'rebuild', rebuild)

        body = {
            'rebuild': {
                'imageRef': self.image_uuid,
            },
        }

        req = fakes.HTTPRequestV3.blank('/v2/fake/servers/a/action')
        self.controller._action_rebuild(req, FAKE_UUID, body=body)
        self.assertEqual(info['image_href_in_call'], self.image_uuid)

    def test_rebuild_instance_with_image_href_uses_uuid(self):
        info = dict(image_href_in_call=None)

        def rebuild(self2, context, instance, image_href, *args, **kwargs):
            info['image_href_in_call'] = image_href

        self.stubs.Set(db, 'instance_get',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        self.stubs.Set(compute_api.API, 'rebuild', rebuild)

        body = {
            'rebuild': {
                'imageRef': self.image_href,
            },
        }

        req = fakes.HTTPRequestV3.blank('/v2/fake/servers/a/action')
        self.controller._action_rebuild(req, FAKE_UUID, body=body)
        self.assertEqual(info['image_href_in_call'], self.image_uuid)

    def test_rebuild_accepted_minimum_pass_disabled(self):
        # run with enable_instance_password disabled to verify admin_password
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False)

        return_server = fakes.fake_instance_get(image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)
        self_href = 'http://localhost/v3/servers/%s' % FAKE_UUID

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        robj = self.controller._action_rebuild(req, FAKE_UUID, body=body)
        body = robj.obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertNotIn("admin_password", body['server'])

        self.assertEqual(robj['location'], self_href)

    def test_rebuild_raises_conflict_on_invalid_state(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        def fake_rebuild(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stubs.Set(compute_api.API, 'rebuild', fake_rebuild)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body=body)

    def test_rebuild_accepted_with_metadata(self):
        metadata = {'new': 'metadata'}

        return_server = fakes.fake_instance_get(metadata=metadata,
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "metadata": metadata,
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        body = self.controller._action_rebuild(req, FAKE_UUID, body=body).obj

        self.assertEqual(body['server']['metadata'], metadata)

    def test_rebuild_accepted_with_bad_metadata(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "metadata": "stack",
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body=body)

    def test_rebuild_with_too_large_metadata(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "metadata": {
                   256 * "k": "value"
                }
            }
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild, req,
                          FAKE_UUID, body=body)

    def test_rebuild_bad_entity(self):
        body = {
            "rebuild": {
                "imageId": self._image_href,
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body=body)

    def test_rebuild_admin_password(self):
        return_server = fakes.fake_instance_get(image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "adminPass": "asdf",
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        body = self.controller._action_rebuild(req, FAKE_UUID, body=body).obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(body['server']['adminPass'], 'asdf')

    def test_rebuild_admin_password_pass_disabled(self):
        # run with enable_instance_password disabled to verify admin_password
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False)

        return_server = fakes.fake_instance_get(image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "adminPass": "asdf",
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        body = self.controller._action_rebuild(req, FAKE_UUID, body=body).obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertNotIn('adminPass', body['server'])

    def test_rebuild_server_with_extra_arg(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "extra_arg": "asdf",
            },
        }

        req = fakes.HTTPRequestV3.blank('')
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body=body)

    def test_rebuild_server_not_found(self):
        def server_not_found(self, instance_id,
                             columns_to_join=None, use_slave=False):
            raise exception.InstanceNotFound(instance_id=instance_id)
        self.stubs.Set(db, 'instance_get_by_uuid', server_not_found)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body=body)

    def test_rebuild_with_bad_image(self):
        body = {
            "rebuild": {
                "imageRef": "foo",
            },
        }
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body=body)

    def test_rebuild_when_kernel_not_exists(self):

        def return_image_meta(*args, **kwargs):
            image_meta_table = {
                '2': {'id': 2, 'status': 'active', 'container_format': 'ari'},
                '155d900f-4e14-4e4c-a73d-069cbf4541e6':
                     {'id': 3, 'status': 'active', 'container_format': 'raw',
                      'properties': {'kernel_id': 1, 'ramdisk_id': 2}},
            }
            image_id = args[2]
            try:
                image_meta = image_meta_table[str(image_id)]
            except KeyError:
                raise exception.ImageNotFound(image_id=image_id)

            return image_meta

        self.stubs.Set(fake._FakeImageService, 'show', return_image_meta)
        body = {
            "rebuild": {
                "imageRef": "155d900f-4e14-4e4c-a73d-069cbf4541e6",
            },
        }
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body=body)

    def test_rebuild_proper_kernel_ram(self):
        instance_meta = {'kernel_id': None, 'ramdisk_id': None}

        orig_get = compute_api.API.get

        def wrap_get(*args, **kwargs):
            inst = orig_get(*args, **kwargs)
            instance_meta['instance'] = inst
            return inst

        def fake_save(context, **kwargs):
            instance = instance_meta['instance']
            for key in instance_meta.keys():
                if key in instance.obj_what_changed():
                    instance_meta[key] = instance[key]

        def return_image_meta(*args, **kwargs):
            image_meta_table = {
                '1': {'id': 1, 'status': 'active', 'container_format': 'aki'},
                '2': {'id': 2, 'status': 'active', 'container_format': 'ari'},
                '155d900f-4e14-4e4c-a73d-069cbf4541e6':
                     {'id': 3, 'status': 'active', 'container_format': 'raw',
                      'properties': {'kernel_id': 1, 'ramdisk_id': 2}},
            }
            image_id = args[2]
            try:
                image_meta = image_meta_table[str(image_id)]
            except KeyError:
                raise exception.ImageNotFound(image_id=image_id)

            return image_meta

        self.stubs.Set(fake._FakeImageService, 'show', return_image_meta)
        self.stubs.Set(compute_api.API, 'get', wrap_get)
        self.stubs.Set(objects.Instance, 'save', fake_save)
        body = {
            "rebuild": {
                "imageRef": "155d900f-4e14-4e4c-a73d-069cbf4541e6",
            },
        }
        req = fakes.HTTPRequestV3.blank(self.url)
        self.controller._action_rebuild(req, FAKE_UUID, body=body).obj
        self.assertEqual(instance_meta['kernel_id'], '1')
        self.assertEqual(instance_meta['ramdisk_id'], '2')

    def _test_rebuild_preserve_ephemeral(self, value=None):
        return_server = fakes.fake_instance_get(image_ref='2',
                                                vm_state=vm_states.ACTIVE,
                                                host='fake_host')
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }
        if value is not None:
            body['rebuild']['preserve_ephemeral'] = value

        req = fakes.HTTPRequestV3.blank(self.url)
        context = req.environ['nova.context']

        self.mox.StubOutWithMock(compute_api.API, 'rebuild')
        if value is not None:
            compute_api.API.rebuild(context, mox.IgnoreArg(), self._image_href,
                                    mox.IgnoreArg(), preserve_ephemeral=value)
        else:
            compute_api.API.rebuild(context, mox.IgnoreArg(), self._image_href,
                                    mox.IgnoreArg())
        self.mox.ReplayAll()

        self.controller._action_rebuild(req, FAKE_UUID, body=body)

    def test_rebuild_preserve_ephemeral_true(self):
        self._test_rebuild_preserve_ephemeral(True)

    def test_rebuild_preserve_ephemeral_false(self):
        self._test_rebuild_preserve_ephemeral(False)

    def test_rebuild_preserve_ephemeral_default(self):
        self._test_rebuild_preserve_ephemeral()

    @mock.patch.object(compute_api.API, 'rebuild',
                       side_effect=exception.AutoDiskConfigDisabledByImage(
                           image='dummy'))
    def test_rebuild_instance_raise_auto_disk_config_exc(self, mock_rebuild):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        req = fakes.HTTPRequest.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          req, FAKE_UUID, body=body)

    def test_resize_server(self):

        body = dict(resize=dict(flavorRef="http://localhost/3"))

        self.resize_called = False

        def resize_mock(*args):
            self.resize_called = True

        self.stubs.Set(compute_api.API, 'resize', resize_mock)

        req = fakes.HTTPRequestV3.blank(self.url)
        body = self.controller._action_resize(req, FAKE_UUID, body=body)

        self.assertEqual(self.resize_called, True)

    def test_resize_server_no_flavor(self):
        body = dict(resize=dict())

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    def test_resize_server_no_flavor_ref(self):
        body = dict(resize=dict(flavorRef=None))

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    def test_resize_server_with_extra_arg(self):
        body = dict(resize=dict(flavorRef="http://localhost/3",
                                extra_arg="extra_arg"))

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    def test_resize_server_invalid_flavor_ref(self):
        body = dict(resize=dict(flavorRef=1.2))

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    def test_resize_with_server_not_found(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))

        self.stubs.Set(compute_api.API, 'get', return_server_not_found)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    def test_resize_with_image_exceptions(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))
        self.resize_called = 0
        image_id = 'fake_image_id'

        exceptions = [
            (exception.ImageNotAuthorized(image_id=image_id),
             webob.exc.HTTPUnauthorized),
            (exception.ImageNotFound(image_id=image_id),
             webob.exc.HTTPBadRequest),
            (exception.Invalid, webob.exc.HTTPBadRequest),
            (exception.NoValidHost(reason='Bad host'),
             webob.exc.HTTPBadRequest),
            (exception.AutoDiskConfigDisabledByImage(image=image_id),
             webob.exc.HTTPBadRequest),
        ]

        raised, expected = map(iter, zip(*exceptions))

        def _fake_resize(obj, context, instance, flavor_id):
            self.resize_called += 1
            raise raised.next()

        self.stubs.Set(compute_api.API, 'resize', _fake_resize)

        for call_no in range(len(exceptions)):
            req = fakes.HTTPRequestV3.blank(self.url)
            next_exception = expected.next()
            actual = self.assertRaises(next_exception,
                              self.controller._action_resize,
                              req, FAKE_UUID, body=body)
            if (isinstance(exceptions[call_no][0],
                           exception.NoValidHost)):
                self.assertEqual(actual.explanation,
                                 'No valid host was found. Bad host')
            elif (isinstance(exceptions[call_no][0],
                             exception.AutoDiskConfigDisabledByImage)):
                self.assertEqual(actual.explanation,
                                 'Requested image fake_image_id has automatic'
                                 ' disk resize disabled.')
            self.assertEqual(self.resize_called, call_no + 1)

    def test_resize_with_too_many_instances(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))

        def fake_resize(*args, **kwargs):
            raise exception.TooManyInstances(message="TooManyInstance")

        self.stubs.Set(compute_api.API, 'resize', fake_resize)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.resize',
                side_effect=exception.CannotResizeDisk(reason=''))
    def test_resize_raises_cannot_resize_disk(self, mock_resize):
        body = dict(resize=dict(flavorRef="http://localhost/3"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.resize',
                side_effect=exception.FlavorNotFound(reason='',
                                                     flavor_id='fake_id'))
    def test_resize_raises_flavor_not_found(self, mock_resize):
        body = dict(resize=dict(flavorRef="http://localhost/3"))
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    def test_resize_raises_conflict_on_invalid_state(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))

        def fake_resize(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stubs.Set(compute_api.API, 'resize', fake_resize)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_resize,
                          req, FAKE_UUID, body=body)

    def test_confirm_resize_server(self):
        body = dict(confirmResize=None)

        self.confirm_resize_called = False

        def cr_mock(*args):
            self.confirm_resize_called = True

        self.stubs.Set(compute_api.API, 'confirm_resize', cr_mock)

        req = fakes.HTTPRequestV3.blank(self.url)
        body = self.controller._action_confirm_resize(req, FAKE_UUID, body)

        self.assertEqual(self.confirm_resize_called, True)

    def test_confirm_resize_migration_not_found(self):
        body = dict(confirmResize=None)

        def confirm_resize_mock(*args):
            raise exception.MigrationNotFoundByStatus(instance_id=1,
                                                      status='finished')

        self.stubs.Set(compute_api.API,
                       'confirm_resize',
                       confirm_resize_mock)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_confirm_resize,
                          req, FAKE_UUID, body)

    def test_confirm_resize_raises_conflict_on_invalid_state(self):
        body = dict(confirmResize=None)

        def fake_confirm_resize(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stubs.Set(compute_api.API, 'confirm_resize',
                fake_confirm_resize)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_confirm_resize,
                          req, FAKE_UUID, body)

    def test_revert_resize_migration_not_found(self):
        body = dict(revertResize=None)

        def revert_resize_mock(*args):
            raise exception.MigrationNotFoundByStatus(instance_id=1,
                                                      status='finished')

        self.stubs.Set(compute_api.API,
                       'revert_resize',
                       revert_resize_mock)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_revert_resize,
                          req, FAKE_UUID, body)

    def test_revert_resize_server_not_found(self):
        body = dict(revertResize=None)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob. exc.HTTPNotFound,
                          self.controller._action_revert_resize,
                          req, "bad_server_id", body)

    def test_revert_resize_server(self):
        body = dict(revertResize=None)

        self.revert_resize_called = False

        def revert_mock(*args):
            self.revert_resize_called = True

        self.stubs.Set(compute_api.API, 'revert_resize', revert_mock)

        req = fakes.HTTPRequestV3.blank(self.url)
        body = self.controller._action_revert_resize(req, FAKE_UUID, body)

        self.assertEqual(self.revert_resize_called, True)

    def test_revert_resize_raises_conflict_on_invalid_state(self):
        body = dict(revertResize=None)

        def fake_revert_resize(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stubs.Set(compute_api.API, 'revert_resize',
                fake_revert_resize)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_revert_resize,
                          req, FAKE_UUID, body)

    def test_create_image(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        response = self.controller._action_create_image(req, FAKE_UUID, body)

        location = response.headers['Location']
        self.assertEqual(glance.generate_image_url('123'), location)

    def test_create_image_name_too_long(self):
        long_name = 'a' * 260
        body = {
            'createImage': {
                'name': long_name,
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_create_image, req,
                          FAKE_UUID, body)

    def _do_test_create_volume_backed_image(self, extra_properties):

        def _fake_id(x):
            return '%s-%s-%s-%s' % (x * 8, x * 4, x * 4, x * 12)

        body = dict(createImage=dict(name='snapshot_of_volume_backed'))

        if extra_properties:
            body['createImage']['metadata'] = extra_properties

        image_service = glance.get_default_image_service()

        bdm = [dict(volume_id=_fake_id('a'),
                    volume_size=1,
                    device_name='vda',
                    delete_on_termination=False)]
        props = dict(kernel_id=_fake_id('b'),
                     ramdisk_id=_fake_id('c'),
                     root_device_name='/dev/vda',
                     block_device_mapping=bdm)
        original_image = dict(properties=props,
                              container_format='ami',
                              status='active',
                              is_public=True)

        image_service.create(None, original_image)

        def fake_block_device_mapping_get_all_by_instance(context, inst_id,
                                                          use_slave=False):
            return [fake_block_device.FakeDbBlockDeviceDict(
                        {'volume_id': _fake_id('a'),
                         'source_type': 'snapshot',
                         'destination_type': 'volume',
                         'volume_size': 1,
                         'device_name': 'vda',
                         'snapshot_id': 1,
                         'boot_index': 0,
                         'delete_on_termination': False,
                         'no_device': None})]

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_block_device_mapping_get_all_by_instance)

        instance = fakes.fake_instance_get(image_ref=original_image['id'],
                                           vm_state=vm_states.ACTIVE,
                                           root_device_name='/dev/vda')
        self.stubs.Set(db, 'instance_get_by_uuid', instance)

        volume = dict(id=_fake_id('a'),
                      size=1,
                      host='fake',
                      display_description='fake')
        snapshot = dict(id=_fake_id('d'))
        self.mox.StubOutWithMock(self.controller.compute_api, 'volume_api')
        volume_api = self.controller.compute_api.volume_api
        volume_api.get(mox.IgnoreArg(), volume['id']).AndReturn(volume)
        volume_api.create_snapshot_force(mox.IgnoreArg(), volume['id'],
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(snapshot)

        self.mox.ReplayAll()

        req = fakes.HTTPRequestV3.blank(self.url)
        response = self.controller._action_create_image(req, FAKE_UUID, body)

        location = response.headers['Location']
        image_id = location.replace(glance.generate_image_url(''), '')
        image = image_service.show(None, image_id)

        self.assertEqual(image['name'], 'snapshot_of_volume_backed')
        properties = image['properties']
        self.assertEqual(properties['kernel_id'], _fake_id('b'))
        self.assertEqual(properties['ramdisk_id'], _fake_id('c'))
        self.assertEqual(properties['root_device_name'], '/dev/vda')
        self.assertEqual(properties['bdm_v2'], True)
        bdms = properties['block_device_mapping']
        self.assertEqual(len(bdms), 1)
        self.assertEqual(bdms[0]['boot_index'], 0)
        self.assertEqual(bdms[0]['source_type'], 'snapshot')
        self.assertEqual(bdms[0]['destination_type'], 'volume')
        self.assertEqual(bdms[0]['snapshot_id'], snapshot['id'])
        for fld in ('connection_info', 'id',
                    'instance_uuid', 'device_name'):
            self.assertNotIn(fld, bdms[0])
        for k in extra_properties.keys():
            self.assertEqual(properties[k], extra_properties[k])

    def test_create_volume_backed_image_no_metadata(self):
        self._do_test_create_volume_backed_image({})

    def test_create_volume_backed_image_with_metadata(self):
        self._do_test_create_volume_backed_image(dict(ImageType='Gold',
                                                      ImageVersion='2.0'))

    def _test_create_volume_backed_image_with_metadata_from_volume(
            self, extra_metadata=None):

        def _fake_id(x):
            return '%s-%s-%s-%s' % (x * 8, x * 4, x * 4, x * 12)

        body = dict(createImage=dict(name='snapshot_of_volume_backed'))
        if extra_metadata:
            body['createImage']['metadata'] = extra_metadata

        image_service = glance.get_default_image_service()

        def fake_block_device_mapping_get_all_by_instance(context, inst_id,
                                                          use_slave=False):
            return [fake_block_device.FakeDbBlockDeviceDict(
                        {'volume_id': _fake_id('a'),
                         'source_type': 'snapshot',
                         'destination_type': 'volume',
                         'volume_size': 1,
                         'device_name': 'vda',
                         'snapshot_id': 1,
                         'boot_index': 0,
                         'delete_on_termination': False,
                         'no_device': None})]

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_block_device_mapping_get_all_by_instance)

        instance = fakes.fake_instance_get(image_ref='',
                                           vm_state=vm_states.ACTIVE,
                                           root_device_name='/dev/vda')
        self.stubs.Set(db, 'instance_get_by_uuid', instance)

        fake_metadata = {'test_key1': 'test_value1',
                         'test_key2': 'test_value2'}
        volume = dict(id=_fake_id('a'),
                      size=1,
                      host='fake',
                      display_description='fake',
                      volume_image_metadata=fake_metadata)
        snapshot = dict(id=_fake_id('d'))
        self.mox.StubOutWithMock(self.controller.compute_api, 'volume_api')
        volume_api = self.controller.compute_api.volume_api
        volume_api.get(mox.IgnoreArg(), volume['id']).AndReturn(volume)
        volume_api.get(mox.IgnoreArg(), volume['id']).AndReturn(volume)
        volume_api.create_snapshot_force(mox.IgnoreArg(), volume['id'],
               mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(snapshot)

        req = fakes.HTTPRequestV3.blank(self.url)

        self.mox.ReplayAll()
        response = self.controller._action_create_image(req, FAKE_UUID, body)
        location = response.headers['Location']
        image_id = location.replace('http://localhost:9292/images/', '')
        image = image_service.show(None, image_id)

        properties = image['properties']
        self.assertEqual(properties['test_key1'], 'test_value1')
        self.assertEqual(properties['test_key2'], 'test_value2')
        if extra_metadata:
            for key, val in extra_metadata.items():
                self.assertEqual(properties[key], val)

    def test_create_vol_backed_img_with_meta_from_vol_without_extra_meta(self):
        self._test_create_volume_backed_image_with_metadata_from_volume()

    def test_create_vol_backed_img_with_meta_from_vol_with_extra_meta(self):
        self._test_create_volume_backed_image_with_metadata_from_volume(
            extra_metadata={'a': 'b'})

    def test_create_image_snapshots_disabled(self):
        """Don't permit a snapshot if the allow_instance_snapshots flag is
        False
        """
        self.flags(allow_instance_snapshots=False)
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_with_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {'key': 'asdf'},
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        response = self.controller._action_create_image(req, FAKE_UUID, body)

        location = response.headers['Location']
        self.assertEqual(glance.generate_image_url('123'), location)

    def test_create_image_with_too_much_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {},
            },
        }
        for num in range(CONF.quota_metadata_items + 1):
            body['createImage']['metadata']['foo%i' % num] = "bar"

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_no_name(self):
        body = {
            'createImage': {},
        }
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_blank_name(self):
        body = {
            'createImage': {
                'name': '',
            }
        }
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_bad_metadata(self):
        body = {
            'createImage': {
                'name': 'geoff',
                'metadata': 'henry',
            },
        }
        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)

    def test_create_image_raises_conflict_on_invalid_state(self):
        def snapshot(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')
        self.stubs.Set(compute_api.API, 'snapshot', snapshot)

        body = {
            "createImage": {
                "name": "test_snapshot",
            },
        }

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_create_image,
                          req, FAKE_UUID, body)
