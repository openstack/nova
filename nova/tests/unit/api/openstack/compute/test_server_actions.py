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

import fixtures
import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
import webob

from nova.api.openstack.compute import servers as servers_v21
from nova.compute import api as compute_api
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova import exception
from nova.image import glance
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit.image import fake


CONF = nova.conf.CONF
FAKE_UUID = fakes.FAKE_UUID


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance, password):
        self.instance_id = instance['uuid']
        self.password = password


class ServerActionsControllerTestV21(test.TestCase):
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    image_base_url = 'http://localhost:9292/images/'
    image_href = image_base_url + '/' + image_uuid
    servers = servers_v21
    validation_error = exception.ValidationError
    request_too_large_error = exception.ValidationError
    image_url = None

    def setUp(self):
        super(ServerActionsControllerTestV21, self).setUp()
        self.flags(group='glance', api_servers=['http://localhost:9292'])
        self.stub_out('nova.compute.api.API.get',
                      fakes.fake_compute_get(vm_state=vm_states.ACTIVE,
                                             project_id=fakes.FAKE_PROJECT_ID,
                                             host='fake_host'))
        self.stub_out('nova.objects.Instance.save', lambda *a, **kw: None)

        fakes.stub_out_compute_api_snapshot(self)
        fake.stub_out_image_service(self)
        self.flags(enable_instance_password=True, group='api')
        self._image_href = '155d900f-4e14-4e4c-a73d-069cbf4541e6'

        self.controller = self._get_controller()
        self.compute_api = self.controller.compute_api
        # We don't care about anything getting as far as hitting the compute
        # RPC API so we just mock it out here.
        mock_rpcapi = mock.patch.object(self.compute_api, 'compute_rpcapi')
        mock_rpcapi.start()
        self.addCleanup(mock_rpcapi.stop)
        # The project_id here matches what is used by default in
        # fake_compute_get which need to match for policy checks.
        self.req = fakes.HTTPRequest.blank('',
                                           project_id=fakes.FAKE_PROJECT_ID)
        self.context = self.req.environ['nova.context']

        self.image_api = glance.API()
        # Assume that anything that hits the compute API and looks for a
        # RequestSpec doesn't care about it, since testing logic that deep
        # should be done in nova.tests.unit.compute.test_compute_api.
        mock_reqspec = mock.patch('nova.objects.RequestSpec')
        mock_reqspec.start()
        self.addCleanup(mock_reqspec.stop)
        # Similarly we shouldn't care about anything hitting conductor from
        # these tests.
        mock_conductor = mock.patch.object(
            self.controller.compute_api, 'compute_task_api')
        mock_conductor.start()
        self.addCleanup(mock_conductor.stop)
        # Assume that none of the tests are using ports with resource requests.
        self.mock_list_port = self.useFixture(
            fixtures.MockPatch('nova.network.neutron.API.list_ports')).mock
        self.mock_list_port.return_value = {'ports': []}

    def _get_controller(self):
        return self.servers.ServersController()

    def _test_locked_instance(self, action, method=None, body_map=None,
                              compute_api_args_map=None):
        if body_map is None:
            body_map = {}
        if compute_api_args_map is None:
            compute_api_args_map = {}

        args, kwargs = compute_api_args_map.get(action, ((), {}))

        uuid = uuidutils.generate_uuid()
        context = self.req.environ['nova.context']
        instance = fake_instance.fake_db_instance(
            id=1, uuid=uuid, vm_state=vm_states.ACTIVE, task_state=None,
            project_id=context.project_id,
            user_id=context.user_id)
        instance = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance)

        with test.nested(
            mock.patch.object(compute_api.API, 'get',
                              return_value=instance),
            mock.patch.object(compute_api.API, method,
                              side_effect=exception.InstanceIsLocked(
                                  instance_uuid=instance['uuid'])),
        ) as (mock_get, mock_method):

            controller_function = 'self.controller.' + action
            self.assertRaises(webob.exc.HTTPConflict,
                              eval(controller_function),
                              self.req, instance['uuid'],
                              body=body_map.get(action))
            expected_attrs = ['flavor', 'numa_topology']
            if method == 'resize':
                expected_attrs.append('services')
            mock_get.assert_called_once_with(self.context, uuid,
                expected_attrs=expected_attrs,
                cell_down_support=False)
            mock_method.assert_called_once_with(self.context, instance,
                                                *args, **kwargs)

    def test_actions_with_locked_instance(self):
        actions = ['_action_resize', '_action_confirm_resize',
                   '_action_revert_resize', '_action_reboot',
                   '_action_rebuild']

        method_translations = {'_action_resize': 'resize',
                               '_action_confirm_resize': 'confirm_resize',
                               '_action_revert_resize': 'revert_resize',
                               '_action_reboot': 'reboot',
                               '_action_rebuild': 'rebuild'}

        body_map = {'_action_resize': {'resize': {'flavorRef': '2'}},
                    '_action_reboot': {'reboot': {'type': 'HARD'}},
                    '_action_rebuild': {'rebuild': {
                                'imageRef': self.image_uuid,
                                'adminPass': 'TNc53Dr8s7vw'}}}

        args_map = {'_action_resize': (('2'), {'auto_disk_config': None}),
                    '_action_confirm_resize': ((), {}),
                    '_action_reboot': (('HARD',), {}),
                    '_action_rebuild': ((self.image_uuid,
                                         'TNc53Dr8s7vw'), {})}

        for action in actions:
            method = method_translations.get(action)
            self._test_locked_instance(action, method=method,
                                       body_map=body_map,
                                       compute_api_args_map=args_map)

    def test_reboot_hard(self):
        body = dict(reboot=dict(type="HARD"))
        self.controller._action_reboot(self.req, FAKE_UUID, body=body)

    def test_reboot_soft(self):
        body = dict(reboot=dict(type="SOFT"))
        self.controller._action_reboot(self.req, FAKE_UUID, body=body)

    def test_reboot_incorrect_type(self):
        body = dict(reboot=dict(type="NOT_A_TYPE"))
        self.assertRaises(self.validation_error,
                          self.controller._action_reboot,
                          self.req, FAKE_UUID, body=body)

    def test_reboot_missing_type(self):
        body = dict(reboot=dict())
        self.assertRaises(self.validation_error,
                          self.controller._action_reboot,
                          self.req, FAKE_UUID, body=body)

    def test_reboot_none(self):
        body = dict(reboot=dict(type=None))
        self.assertRaises(self.validation_error,
                          self.controller._action_reboot,
                          self.req, FAKE_UUID, body=body)

    def test_reboot_not_found(self):
        body = dict(reboot=dict(type="HARD"))
        with mock.patch('nova.compute.api.API.get',
                        side_effect=exception.InstanceNotFound(
                            instance_id=uuids.fake)):
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.controller._action_reboot,
                              self.req, uuids.fake, body=body)

    def test_reboot_raises_conflict_on_invalid_state(self):
        body = dict(reboot=dict(type="HARD"))

        def fake_reboot(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stub_out('nova.compute.api.API.reboot', fake_reboot)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_reboot,
                          self.req, FAKE_UUID, body=body)

    def test_reboot_soft_with_soft_in_progress_raises_conflict(self):
        body = dict(reboot=dict(type="SOFT"))
        self.stub_out('nova.compute.api.API.get',
                      fakes.fake_compute_get(project_id=fakes.FAKE_PROJECT_ID,
                                             vm_state=vm_states.ACTIVE,
                                             task_state=task_states.REBOOTING))
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_reboot,
                          self.req, FAKE_UUID, body=body)

    def test_reboot_hard_with_soft_in_progress_does_not_raise(self):
        body = dict(reboot=dict(type="HARD"))
        self.stub_out('nova.compute.api.API.get',
                      fakes.fake_compute_get(project_id=fakes.FAKE_PROJECT_ID,
                                             vm_state=vm_states.ACTIVE,
                                             task_state=task_states.REBOOTING))
        self.controller._action_reboot(self.req, FAKE_UUID, body=body)

    def test_reboot_hard_with_hard_in_progress(self):
        body = dict(reboot=dict(type="HARD"))
        self.stub_out('nova.compute.api.API.get',
                      fakes.fake_compute_get(
                          project_id=fakes.FAKE_PROJECT_ID,
                          vm_state=vm_states.ACTIVE,
                          task_state=task_states.REBOOTING_HARD))
        self.controller._action_reboot(self.req, FAKE_UUID, body=body)

    def test_reboot_soft_with_hard_in_progress_raises_conflict(self):
        body = dict(reboot=dict(type="SOFT"))
        self.stub_out('nova.compute.api.API.get',
                      fakes.fake_compute_get(
                          project_id=fakes.FAKE_PROJECT_ID,
                          vm_state=vm_states.ACTIVE,
                          task_state=task_states.REBOOTING_HARD))
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_reboot,
                          self.req, FAKE_UUID, body=body)

    def _test_rebuild_preserve_ephemeral(self, value=None):
        return_server = fakes.fake_compute_get(
                project_id=fakes.FAKE_PROJECT_ID,
                image_ref='2',
                vm_state=vm_states.ACTIVE,
                host='fake_host')
        self.stub_out('nova.compute.api.API.get', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }
        if value is not None:
            body['rebuild']['preserve_ephemeral'] = value

        with mock.patch.object(compute_api.API, 'rebuild') as mock_rebuild:
            self.controller._action_rebuild(self.req, FAKE_UUID, body=body)

            if value is not None:
                mock_rebuild.assert_called_once_with(self.context, mock.ANY,
                    self._image_href, mock.ANY, preserve_ephemeral=value)
            else:
                mock_rebuild.assert_called_once_with(self.context, mock.ANY,
                    self._image_href, mock.ANY)

    def test_rebuild_preserve_ephemeral_true(self):
        self._test_rebuild_preserve_ephemeral(True)

    def test_rebuild_preserve_ephemeral_false(self):
        self._test_rebuild_preserve_ephemeral(False)

    def test_rebuild_preserve_ephemeral_default(self):
        self._test_rebuild_preserve_ephemeral()

    def test_rebuild_accepted_minimum(self):
        return_server = fakes.fake_compute_get(
                project_id=fakes.FAKE_PROJECT_ID,
                image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stub_out('nova.compute.api.API.get', return_server)
        self_href = 'http://localhost/v2/servers/%s' % FAKE_UUID

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        robj = self.controller._action_rebuild(self.req, FAKE_UUID, body=body)
        body = robj.obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(len(body['server']['adminPass']),
                         CONF.password_length)

        self.assertEqual(robj['location'], self_href)
        # pep3333 requires applications produces headers which are str
        self.assertEqual(str, type(robj['location']))

    def test_rebuild_instance_with_image_uuid(self):
        info = dict(image_href_in_call=None)

        def rebuild(self2, context, instance, image_href, *args, **kwargs):
            info['image_href_in_call'] = image_href

        self.stub_out('nova.compute.api.API.rebuild', rebuild)

        # proper local hrefs must start with 'http://localhost/v2/'
        body = {
            'rebuild': {
                'imageRef': self.image_uuid,
            },
        }

        self.controller._action_rebuild(self.req, FAKE_UUID, body=body)
        self.assertEqual(info['image_href_in_call'], self.image_uuid)

    def test_rebuild_instance_with_image_href_uses_uuid(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        body = {
            'rebuild': {
                'imageRef': self.image_href,
            },
        }

        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_accepted_minimum_pass_disabled(self):
        # run with enable_instance_password disabled to verify adminPass
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False, group='api')

        return_server = fakes.fake_compute_get(
                project_id=fakes.FAKE_PROJECT_ID,
                image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stub_out('nova.compute.api.API.get', return_server)
        self_href = 'http://localhost/v2/servers/%s' % FAKE_UUID

        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        robj = self.controller._action_rebuild(self.req, FAKE_UUID, body=body)
        body = robj.obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertNotIn("adminPass", body['server'])

        self.assertEqual(robj['location'], self_href)
        # pep3333 requires applications produces headers which are str
        self.assertEqual(str, type(robj['location']))

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

        self.stub_out('nova.compute.api.API.rebuild', fake_rebuild)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_accepted_with_metadata(self):
        metadata = {'new': 'metadata'}

        return_server = fakes.fake_compute_get(
                project_id=fakes.FAKE_PROJECT_ID,
                metadata=metadata,
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stub_out('nova.compute.api.API.get', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "metadata": metadata,
            },
        }

        body = self.controller._action_rebuild(self.req, FAKE_UUID,
                                               body=body).obj

        self.assertEqual(body['server']['metadata'], metadata)

    def test_rebuild_accepted_with_bad_metadata(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "metadata": "stack",
            },
        }

        self.assertRaises(self.validation_error,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_with_too_large_metadata(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "metadata": {
                   256 * "k": "value"
                }
            }
        }

        self.assertRaises(self.request_too_large_error,
                          self.controller._action_rebuild, self.req,
                          FAKE_UUID, body=body)

    def test_rebuild_bad_entity(self):
        body = {
            "rebuild": {
                "imageId": self._image_href,
            },
        }

        self.assertRaises(self.validation_error,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_admin_pass(self):
        return_server = fakes.fake_compute_get(
                project_id=fakes.FAKE_PROJECT_ID,
                image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stub_out('nova.compute.api.API.get', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "adminPass": "asdf",
            },
        }

        body = self.controller._action_rebuild(self.req, FAKE_UUID,
                                               body=body).obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertEqual(body['server']['adminPass'], 'asdf')

    def test_rebuild_admin_pass_pass_disabled(self):
        # run with enable_instance_password disabled to verify adminPass
        # is missing from response. See lp bug 921814
        self.flags(enable_instance_password=False, group='api')

        return_server = fakes.fake_compute_get(
                project_id=fakes.FAKE_PROJECT_ID,
                image_ref='2',
                vm_state=vm_states.ACTIVE, host='fake_host')
        self.stub_out('nova.compute.api.API.get', return_server)

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "adminPass": "asdf",
            },
        }

        body = self.controller._action_rebuild(self.req, FAKE_UUID,
                                               body=body).obj

        self.assertEqual(body['server']['image']['id'], '2')
        self.assertNotIn('adminPass', body['server'])

    def test_rebuild_server_not_found(self):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }
        with mock.patch('nova.compute.api.API.get',
                        side_effect=exception.InstanceNotFound(
                            instance_id=FAKE_UUID)):
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.controller._action_rebuild,
                              self.req, FAKE_UUID, body=body)

    def test_rebuild_with_bad_image(self):
        body = {
            "rebuild": {
                "imageRef": "foo",
            },
        }
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_accessIP(self):
        attributes = {
            'access_ip_v4': '172.19.0.1',
            'access_ip_v6': 'fe80::1',
        }

        body = {
            "rebuild": {
                "imageRef": self._image_href,
                "accessIPv4": "172.19.0.1",
                "accessIPv6": "fe80::1",
            },
        }

        data = {'changes': {}}
        orig_get = compute_api.API.get

        def wrap_get(*args, **kwargs):
            data['instance'] = orig_get(*args, **kwargs)
            return data['instance']

        def fake_save(context, **kwargs):
            data['changes'].update(data['instance'].obj_get_changes())

        self.stub_out('nova.compute.api.API.get', wrap_get)
        self.stub_out('nova.objects.Instance.save', fake_save)

        self.controller._action_rebuild(self.req, FAKE_UUID, body=body)

        self.assertEqual(self._image_href, data['changes']['image_ref'])
        self.assertEqual("", data['changes']['kernel_id'])
        self.assertEqual("", data['changes']['ramdisk_id'])
        self.assertEqual(task_states.REBUILDING, data['changes']['task_state'])
        self.assertEqual(0, data['changes']['progress'])
        for attr, value in attributes.items():
            self.assertEqual(value, str(data['changes'][attr]))

    def test_rebuild_when_kernel_not_exists(self):

        def return_image_meta(*args, **kwargs):
            image_meta_table = {
                '2': {'id': uuids.image_id, 'status': 'active',
                      'container_format': 'ari'},
                '155d900f-4e14-4e4c-a73d-069cbf4541e6':
                     {'id': uuids.image_id, 'status': 'active',
                      'container_format': 'raw',
                      'properties': {'kernel_id': 1, 'ramdisk_id': 2}},
            }
            image_id = args[2]
            try:
                image_meta = image_meta_table[str(image_id)]
            except KeyError:
                raise exception.ImageNotFound(image_id=image_id)

            return image_meta

        self.stub_out('nova.tests.unit.image.fake._FakeImageService.show',
                      return_image_meta)
        body = {
            "rebuild": {
                "imageRef": "155d900f-4e14-4e4c-a73d-069cbf4541e6",
            },
        }
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

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
                uuids.kernel_image_id: {
                    'id': uuids.kernel_image_id,
                    'status': 'active',
                    'container_format': 'aki'},
                uuids.ramdisk_image_id: {
                    'id': uuids.ramdisk_image_id,
                    'status': 'active',
                    'container_format': 'ari'},
                '155d900f-4e14-4e4c-a73d-069cbf4541e6':
                     {'id': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                      'status': 'active',
                      'container_format': 'raw',
                      'properties': {'kernel_id': uuids.kernel_image_id,
                                     'ramdisk_id': uuids.ramdisk_image_id}},
            }
            image_id = args[2]
            try:
                image_meta = image_meta_table[str(image_id)]
            except KeyError:
                raise exception.ImageNotFound(image_id=image_id)

            return image_meta

        self.stub_out('nova.tests.unit.image.fake._FakeImageService.show',
                      return_image_meta)
        self.stub_out('nova.compute.api.API.get', wrap_get)
        self.stub_out('nova.objects.Instance.save', fake_save)
        body = {
            "rebuild": {
                "imageRef": "155d900f-4e14-4e4c-a73d-069cbf4541e6",
            },
        }
        self.controller._action_rebuild(self.req, FAKE_UUID, body=body).obj
        self.assertEqual(instance_meta['kernel_id'], uuids.kernel_image_id)
        self.assertEqual(instance_meta['ramdisk_id'], uuids.ramdisk_image_id)

    @mock.patch.object(compute_api.API, 'rebuild')
    def test_rebuild_instance_raise_auto_disk_config_exc(self, mock_rebuild):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        mock_rebuild.side_effect = exception.AutoDiskConfigDisabledByImage(
            image='dummy')

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    @mock.patch.object(compute_api.API, 'rebuild')
    def test_rebuild_raise_invalid_architecture_exc(self, mock_rebuild):
        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        mock_rebuild.side_effect = exception.InvalidArchitectureName('arm64')

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    @mock.patch.object(compute_api.API, 'rebuild')
    def test_rebuild_raise_invalid_volume_exc(self, mock_rebuild):
        """Make sure that we can't rebuild with an InvalidVolume exception."""
        body = {
            "rebuild": {
                "imageRef": self._image_href,
            },
        }

        mock_rebuild.side_effect = exception.InvalidVolume('error')

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_resize_server(self):

        body = dict(resize=dict(flavorRef="http://localhost/3"))

        self.resize_called = False

        def resize_mock(*args, **kwargs):
            self.resize_called = True

        self.stub_out('nova.compute.api.API.resize', resize_mock)

        self.controller._action_resize(self.req, FAKE_UUID, body=body)

        self.assertTrue(self.resize_called)

    def test_resize_server_no_flavor(self):
        body = dict(resize=dict())

        self.assertRaises(self.validation_error,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    def test_resize_server_no_flavor_ref(self):
        body = dict(resize=dict(flavorRef=None))

        self.assertRaises(self.validation_error,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    def test_resize_server_with_extra_arg(self):
        body = dict(resize=dict(favorRef="http://localhost/3",
                                extra_arg="extra_arg"))
        self.assertRaises(self.validation_error,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    def test_resize_server_invalid_flavor_ref(self):
        body = dict(resize=dict(flavorRef=1.2))

        self.assertRaises(self.validation_error,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    def test_resize_with_server_not_found(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))
        with mock.patch('nova.compute.api.API.get',
                        side_effect=exception.InstanceNotFound(
                            instance_id=FAKE_UUID)):
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.controller._action_resize,
                              self.req, FAKE_UUID, body=body)

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
            (exception.AutoDiskConfigDisabledByImage(image=image_id),
             webob.exc.HTTPBadRequest),
        ]

        raised, expected = map(iter, zip(*exceptions))

        def _fake_resize(obj, context, instance, flavor_id,
                         auto_disk_config=None):
            self.resize_called += 1
            raise next(raised)

        self.stub_out('nova.compute.api.API.resize', _fake_resize)

        for call_no in range(len(exceptions)):
            next_exception = next(expected)
            actual = self.assertRaises(next_exception,
                                       self.controller._action_resize,
                                       self.req, FAKE_UUID, body=body)
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

    @mock.patch('nova.compute.api.API.resize',
                side_effect=exception.CannotResizeDisk(reason=''))
    def test_resize_raises_cannot_resize_disk(self, mock_resize):
        body = dict(resize=dict(flavorRef="http://localhost/3"))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.resize',
                side_effect=exception.FlavorNotFound(reason='',
                                                     flavor_id='fake_id'))
    def test_resize_raises_flavor_not_found(self, mock_resize):
        body = dict(resize=dict(flavorRef="http://localhost/3"))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    def test_resize_with_too_many_instances(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))

        def fake_resize(*args, **kwargs):
            raise exception.TooManyInstances(message="TooManyInstance")

        self.stub_out('nova.compute.api.API.resize', fake_resize)

        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    def test_resize_raises_conflict_on_invalid_state(self):
        body = dict(resize=dict(flavorRef="http://localhost/3"))

        def fake_resize(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stub_out('nova.compute.api.API.resize', fake_resize)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    @mock.patch.object(compute_api.API, 'resize')
    def test_resize_instance_raise_auto_disk_config_exc(self, mock_resize):
        mock_resize.side_effect = exception.AutoDiskConfigDisabledByImage(
            image='dummy')

        body = dict(resize=dict(flavorRef="http://localhost/3"))

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.resize',
                side_effect=exception.PciRequestAliasNotDefined(
                    alias='fake_name'))
    def test_resize_pci_alias_not_defined(self, mock_resize):
        # Tests that PciRequestAliasNotDefined is translated to a 400 error.
        body = dict(resize=dict(flavorRef="http://localhost/3"))
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

    def test_confirm_resize_server(self):
        body = dict(confirmResize=None)

        self.confirm_resize_called = False

        def cr_mock(*args):
            self.confirm_resize_called = True

        self.stub_out('nova.compute.api.API.confirm_resize', cr_mock)

        self.controller._action_confirm_resize(self.req, FAKE_UUID, body=body)

        self.assertTrue(self.confirm_resize_called)

    def test_confirm_resize_migration_not_found(self):
        body = dict(confirmResize=None)

        def confirm_resize_mock(*args):
            raise exception.MigrationNotFoundByStatus(instance_id=1,
                                                      status='finished')

        self.stub_out('nova.compute.api.API.confirm_resize',
                      confirm_resize_mock)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_confirm_resize,
                          self.req, FAKE_UUID, body=body)

    def test_confirm_resize_raises_conflict_on_invalid_state(self):
        body = dict(confirmResize=None)

        def fake_confirm_resize(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stub_out('nova.compute.api.API.confirm_resize',
                      fake_confirm_resize)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_confirm_resize,
                          self.req, FAKE_UUID, body=body)

    def test_revert_resize_migration_not_found(self):
        body = dict(revertResize=None)

        def revert_resize_mock(*args):
            raise exception.MigrationNotFoundByStatus(instance_id=1,
                                                      status='finished')

        self.stub_out('nova.compute.api.API.revert_resize',
                      revert_resize_mock)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_revert_resize,
                          self.req, FAKE_UUID, body=body)

    def test_revert_resize_server_not_found(self):
        body = dict(revertResize=None)
        with mock.patch('nova.compute.api.API.get',
                        side_effect=exception.InstanceNotFound(
                            instance_id='bad_server_id')):
            self.assertRaises(webob. exc.HTTPNotFound,
                              self.controller._action_revert_resize,
                              self.req, "bad_server_id", body=body)

    def test_revert_resize_server(self):
        body = dict(revertResize=None)

        self.revert_resize_called = False

        def revert_mock(*args):
            self.revert_resize_called = True

        self.stub_out('nova.compute.api.API.revert_resize', revert_mock)

        body = self.controller._action_revert_resize(self.req, FAKE_UUID,
                                                     body=body)

        self.assertTrue(self.revert_resize_called)

    def test_revert_resize_raises_conflict_on_invalid_state(self):
        body = dict(revertResize=None)

        def fake_revert_resize(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')

        self.stub_out('nova.compute.api.API.revert_resize',
                      fake_revert_resize)

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_revert_resize,
                          self.req, FAKE_UUID, body=body)

    def test_create_image(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }

        response = self.controller._action_create_image(self.req, FAKE_UUID,
                                                        body=body)

        location = response.headers['Location']
        self.assertEqual(self.image_url + '123' if self.image_url else
            self.image_api.generate_image_url('123', self.context),
            location)

    def test_create_image_v2_45(self):
        """Tests the createImage server action API with the 2.45 microversion
        where there is a response body but no Location header.
        """
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }
        req = fakes.HTTPRequest.blank('', version='2.45')
        response = self.controller._action_create_image(req, FAKE_UUID,
                                                        body=body)
        self.assertIsInstance(response, dict)
        self.assertEqual('123', response['image_id'])

    def test_create_image_name_too_long(self):
        long_name = 'a' * 260
        body = {
            'createImage': {
                'name': long_name,
            },
        }

        self.assertRaises(self.validation_error,
                          self.controller._action_create_image, self.req,
                          FAKE_UUID, body=body)

    def _do_test_create_volume_backed_image(
            self, extra_properties, mock_vol_create_side_effect=None):

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

        self.stub_out('nova.db.api.block_device_mapping_get_all_by_instance',
                      fake_block_device_mapping_get_all_by_instance)

        system_metadata = dict(image_kernel_id=_fake_id('b'),
                               image_ramdisk_id=_fake_id('c'),
                               image_root_device_name='/dev/vda',
                               image_block_device_mapping=str(bdm),
                               image_container_format='ami')
        instance = fakes.fake_compute_get(project_id=fakes.FAKE_PROJECT_ID,
                                          image_ref=uuids.fake,
                                          vm_state=vm_states.ACTIVE,
                                          root_device_name='/dev/vda',
                                          system_metadata=system_metadata)
        self.stub_out('nova.compute.api.API.get', instance)

        volume = dict(id=_fake_id('a'),
                      size=1,
                      host='fake',
                      display_description='fake')

        snapshot = dict(id=_fake_id('d'))

        with test.nested(
            mock.patch.object(
                self.controller.compute_api.volume_api, 'get_absolute_limits',
                return_value={'totalSnapshotsUsed': 0,
                              'maxTotalSnapshots': 10}),
            mock.patch.object(self.controller.compute_api.compute_rpcapi,
                'quiesce_instance',
                side_effect=exception.InstanceQuiesceNotSupported(
                    instance_id='fake', reason='test')),
            mock.patch.object(self.controller.compute_api.volume_api, 'get',
                              return_value=volume),
            mock.patch.object(self.controller.compute_api.volume_api,
                              'create_snapshot_force',
                              return_value=snapshot),
        ) as (mock_get_limits, mock_quiesce, mock_vol_get, mock_vol_create):

            if mock_vol_create_side_effect:
                mock_vol_create.side_effect = mock_vol_create_side_effect

            response = self.controller._action_create_image(self.req,
                FAKE_UUID, body=body)

            location = response.headers['Location']
            image_id = location.replace(self.image_url or
                 self.image_api.generate_image_url('', self.context),
                                        '')
            image = image_service.show(None, image_id)

            self.assertEqual(image['name'], 'snapshot_of_volume_backed')
            properties = image['properties']
            self.assertEqual(properties['kernel_id'], _fake_id('b'))
            self.assertEqual(properties['ramdisk_id'], _fake_id('c'))
            self.assertEqual(properties['root_device_name'], '/dev/vda')
            self.assertTrue(properties['bdm_v2'])
            bdms = properties['block_device_mapping']
            self.assertEqual(len(bdms), 1)
            self.assertEqual(bdms[0]['boot_index'], 0)
            self.assertEqual(bdms[0]['source_type'], 'snapshot')
            self.assertEqual(bdms[0]['destination_type'], 'volume')
            self.assertEqual(bdms[0]['snapshot_id'], snapshot['id'])
            self.assertEqual('/dev/vda', bdms[0]['device_name'])
            for fld in ('connection_info', 'id', 'instance_uuid'):
                self.assertNotIn(fld, bdms[0])
            for k in extra_properties.keys():
                self.assertEqual(properties[k], extra_properties[k])

            mock_quiesce.assert_called_once_with(mock.ANY, mock.ANY)
            mock_vol_get.assert_called_once_with(mock.ANY, volume['id'])
            mock_vol_create.assert_called_once_with(mock.ANY, volume['id'],
                                                    mock.ANY, mock.ANY)

    def test_create_volume_backed_image_no_metadata(self):
        self._do_test_create_volume_backed_image({})

    def test_create_volume_backed_image_with_metadata(self):
        self._do_test_create_volume_backed_image(dict(ImageType='Gold',
                                                      ImageVersion='2.0'))

    def test_create_volume_backed_image_cinder_over_quota(self):
        self.assertRaises(
            webob.exc.HTTPForbidden,
            self._do_test_create_volume_backed_image, {},
            mock_vol_create_side_effect=exception.OverQuota(
                overs='snapshot'))

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

        self.stub_out('nova.db.api.block_device_mapping_get_all_by_instance',
                      fake_block_device_mapping_get_all_by_instance)

        instance = fakes.fake_compute_get(
            project_id=fakes.FAKE_PROJECT_ID,
            image_ref='',
            vm_state=vm_states.ACTIVE,
            root_device_name='/dev/vda',
            system_metadata={'image_test_key1': 'test_value1',
                             'image_test_key2': 'test_value2'})
        self.stub_out('nova.compute.api.API.get', instance)

        volume = dict(id=_fake_id('a'),
                      size=1,
                      host='fake',
                      display_description='fake')

        snapshot = dict(id=_fake_id('d'))

        with test.nested(
            mock.patch.object(
                self.controller.compute_api.volume_api, 'get_absolute_limits',
                return_value={'totalSnapshotsUsed': 0,
                              'maxTotalSnapshots': 10}),
            mock.patch.object(self.controller.compute_api.compute_rpcapi,
                'quiesce_instance',
                side_effect=exception.InstanceQuiesceNotSupported(
                    instance_id='fake', reason='test')),
            mock.patch.object(self.controller.compute_api.volume_api, 'get',
                              return_value=volume),
            mock.patch.object(self.controller.compute_api.volume_api,
                              'create_snapshot_force',
                              return_value=snapshot),
        ) as (mock_get_limits, mock_quiesce, mock_vol_get, mock_vol_create):

            response = self.controller._action_create_image(self.req,
                FAKE_UUID, body=body)
            location = response.headers['Location']
            image_id = location.replace(self.image_base_url, '')
            image = image_service.show(None, image_id)

            properties = image['properties']
            self.assertEqual(properties['test_key1'], 'test_value1')
            self.assertEqual(properties['test_key2'], 'test_value2')
            if extra_metadata:
                for key, val in extra_metadata.items():
                    self.assertEqual(properties[key], val)

            mock_quiesce.assert_called_once_with(mock.ANY, mock.ANY)
            mock_vol_get.assert_called_once_with(mock.ANY, volume['id'])
            mock_vol_create.assert_called_once_with(mock.ANY, volume['id'],
                                                    mock.ANY, mock.ANY)

    def test_create_vol_backed_img_with_meta_from_vol_without_extra_meta(self):
        self._test_create_volume_backed_image_with_metadata_from_volume()

    def test_create_vol_backed_img_with_meta_from_vol_with_extra_meta(self):
        self._test_create_volume_backed_image_with_metadata_from_volume(
            extra_metadata={'a': 'b'})

    def test_create_image_with_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {'key': 'asdf'},
            },
        }

        response = self.controller._action_create_image(self.req, FAKE_UUID,
                                                        body=body)

        location = response.headers['Location']
        self.assertEqual(self.image_url + '123' if self.image_url else
            self.image_api.generate_image_url('123', self.context), location)

    def test_create_image_with_too_much_metadata(self):
        body = {
            'createImage': {
                'name': 'Snapshot 1',
                'metadata': {},
            },
        }
        for num in range(CONF.quota.metadata_items + 1):
            body['createImage']['metadata']['foo%i' % num] = "bar"

        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller._action_create_image,
                          self.req, FAKE_UUID, body=body)

    def test_create_image_no_name(self):
        body = {
            'createImage': {},
        }

        self.assertRaises(self.validation_error,
                          self.controller._action_create_image,
                          self.req, FAKE_UUID, body=body)

    def test_create_image_blank_name(self):
        body = {
            'createImage': {
                'name': '',
            }
        }

        self.assertRaises(self.validation_error,
                          self.controller._action_create_image,
                          self.req, FAKE_UUID, body=body)

    def test_create_image_bad_metadata(self):
        body = {
            'createImage': {
                'name': 'geoff',
                'metadata': 'henry',
            },
        }

        self.assertRaises(self.validation_error,
                          self.controller._action_create_image,
                          self.req, FAKE_UUID, body=body)

    def test_create_image_raises_conflict_on_invalid_state(self):
        def snapshot(*args, **kwargs):
            raise exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')
        self.stub_out('nova.compute.api.API.snapshot', snapshot)

        body = {
            "createImage": {
                "name": "test_snapshot",
            },
        }

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_create_image,
                          self.req, FAKE_UUID, body=body)

    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    @mock.patch('nova.api.openstack.common.'
                'instance_has_port_with_resource_request', return_value=True)
    def test_resize_with_bandwidth_from_old_compute_not_supported(
            self, mock_has_res_req, mock_get_service):
        body = dict(resize=dict(flavorRef="http://localhost/3"))
        mock_get_service.return_value = objects.Service()
        mock_get_service.return_value.version = 38

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_resize,
                          self.req, FAKE_UUID, body=body)

        mock_has_res_req.assert_called_once_with(
            FAKE_UUID, self.controller.network_api)
        mock_get_service.assert_called_once_with(
            self.req.environ['nova.context'], 'fake_host', 'nova-compute')
