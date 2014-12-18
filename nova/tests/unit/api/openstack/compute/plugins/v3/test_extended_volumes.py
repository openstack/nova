# Copyright 2013 OpenStack Foundation
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
from oslo.serialization import jsonutils
import webob

from nova.api.openstack.compute.plugins.v3 import extended_volumes
from nova import compute
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova import volume

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID1)
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_compute_get_not_found(*args, **kwargs):
    raise exception.InstanceNotFound(instance_id=UUID1)


def fake_compute_get_all(*args, **kwargs):
    db_list = [fakes.stub_instance(1), fakes.stub_instance(2)]
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            objects.InstanceList(),
                                            db_list, fields)


def fake_bdms_get_all_by_instance(*args, **kwargs):
    return [fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': UUID1, 'source_type': 'volume',
             'destination_type': 'volume', 'id': 1}),
            fake_block_device.FakeDbBlockDeviceDict(
            {'volume_id': UUID2, 'source_type': 'volume',
             'destination_type': 'volume', 'id': 2})]


def fake_attach_volume(self, context, instance, volume_id,
                       device, disk_bus, device_type):
    pass


def fake_attach_volume_not_found_vol(self, context, instance, volume_id,
                                     device, disk_bus, device_type):
    raise exception.VolumeNotFound(volume_id=volume_id)


def fake_attach_volume_invalid_device_path(self, context, instance,
                                           volume_id, device, disk_bus,
                                           device_type):
    raise exception.InvalidDevicePath(path=device)


def fake_attach_volume_instance_invalid_state(self, context, instance,
                                              volume_id, device, disk_bus,
                                              device_type):
    raise exception.InstanceInvalidState(instance_uuid=UUID1, state='',
                                         method='', attr='')


def fake_attach_volume_invalid_volume(self, context, instance,
                                      volume_id, device, disk_bus,
                                      device_type):
    raise exception.InvalidVolume(reason='')


def fake_detach_volume(self, context, instance, volume):
    pass


def fake_swap_volume(self, context, instance,
                     old_volume_id, new_volume_id):
    pass


def fake_swap_volume_invalid_volume(self, context, instance,
                                    volume_id, device):
    raise exception.InvalidVolume(reason='', volume_id=volume_id)


def fake_swap_volume_unattached_volume(self, context, instance,
                                       volume_id, device):
    raise exception.VolumeUnattached(reason='', volume_id=volume_id)


def fake_detach_volume_invalid_volume(self, context, instance, volume):
    raise exception.InvalidVolume(reason='')


def fake_swap_volume_instance_invalid_state(self, context, instance,
                                              volume_id, device):
    raise exception.InstanceInvalidState(instance_uuid=UUID1, state='',
                                         method='', attr='')


def fake_volume_get(*args, **kwargs):
    pass


def fake_volume_get_not_found(*args, **kwargs):
    raise exception.VolumeNotFound(volume_id=UUID1)


class ExtendedVolumesTest(test.TestCase):
    content_type = 'application/json'
    prefix = 'os-extended-volumes:'

    def setUp(self):
        super(ExtendedVolumesTest, self).setUp()
        self.Controller = extended_volumes.ExtendedVolumesController()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdms_get_all_by_instance)
        self.stubs.Set(volume.cinder.API, 'get', fake_volume_get)
        self.stubs.Set(compute.api.API, 'detach_volume', fake_detach_volume)
        self.stubs.Set(compute.api.API, 'attach_volume', fake_attach_volume)
        self.app = fakes.wsgi_app_v21(init_only=('os-extended-volumes',
                                                 'servers'))
        return_server = fakes.fake_instance_get()
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

    def _make_request(self, url, body=None):
        base_url = '/v2/fake/servers'
        req = webob.Request.blank(base_url + url)
        req.headers['Accept'] = self.content_type
        if body:
            req.body = jsonutils.dumps(body)
            req.method = 'POST'
        req.content_type = 'application/json'
        res = req.get_response(self.app)
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def test_show(self):
        url = '/%s' % UUID1
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        server = self._get_server(res.body)
        exp_volumes = [{'id': UUID1}, {'id': UUID2}]
        if self.content_type == 'application/json':
            actual = server.get('%svolumes_attached' % self.prefix)
        self.assertEqual(exp_volumes, actual)

    def test_detail(self):
        url = '/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        exp_volumes = [{'id': UUID1}, {'id': UUID2}]
        for i, server in enumerate(self._get_servers(res.body)):
            if self.content_type == 'application/json':
                actual = server.get('%svolumes_attached' % self.prefix)
            self.assertEqual(exp_volumes, actual)

    def test_detach(self):
        url = "/%s/action" % UUID1
        res = self._make_request(url, {"detach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 202)

    def test_detach_volume_from_locked_server(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'detach_volume',
                       fakes.fake_actions_to_locked_server)
        res = self._make_request(url, {"detach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 409)

    def test_detach_with_non_existed_vol(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(volume.cinder.API, 'get', fake_volume_get_not_found)
        res = self._make_request(url, {"detach": {"volume_id": UUID2}})
        self.assertEqual(res.status_int, 404)

    def test_detach_with_non_existed_instance(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'get', fake_compute_get_not_found)
        res = self._make_request(url, {"detach": {"volume_id": UUID2}})
        self.assertEqual(res.status_int, 404)

    def test_detach_with_invalid_vol(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'detach_volume',
                       fake_detach_volume_invalid_volume)
        res = self._make_request(url, {"detach": {"volume_id": UUID2}})
        self.assertEqual(res.status_int, 400)

    def test_detach_with_bad_id(self):
        url = "/%s/action" % UUID1
        res = self._make_request(url, {"detach": {"volume_id": 'xxx'}})
        self.assertEqual(res.status_int, 400)

    def test_detach_without_id(self):
        url = "/%s/action" % UUID1
        res = self._make_request(url, {"detach": {}})
        self.assertEqual(res.status_int, 400)

    def test_detach_volume_with_invalid_request(self):
        url = "/%s/action" % UUID1
        res = self._make_request(url, {"detach": None})
        self.assertEqual(res.status_int, 400)

    @mock.patch('nova.objects.BlockDeviceMapping.is_root',
                 new_callable=mock.PropertyMock)
    def test_detach_volume_root(self, mock_isroot):
        url = "/%s/action" % UUID1
        mock_isroot.return_value = True
        res = self._make_request(url, {"detach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 403)

    def test_attach_volume(self):
        url = "/%s/action" % UUID1
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 202)

    def test_attach_volume_to_locked_server(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fakes.fake_actions_to_locked_server)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 409)

    def test_attach_volume_disk_bus_and_disk_dev(self):
        url = "/%s/action" % UUID1
        self._make_request(url, {"attach": {"volume_id": UUID1,
                                            "device": "/dev/vdb",
                                            "disk_bus": "ide",
                                            "device_type": "cdrom"}})

    def test_attach_volume_with_bad_id(self):
        url = "/%s/action" % UUID1
        res = self._make_request(url, {"attach": {"volume_id": 'xxx'}})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_without_id(self):
        url = "/%s/action" % UUID1
        res = self._make_request(url, {"attach": {}})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_with_invalid_request(self):
        url = "/%s/action" % UUID1
        res = self._make_request(url, {"attach": None})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_with_non_existe_vol(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_not_found_vol)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 404)

    def test_attach_volume_with_non_existed_instance(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'get', fake_compute_get_not_found)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 404)

    def test_attach_volume_with_invalid_device_path(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_invalid_device_path)
        res = self._make_request(url, {"attach": {"volume_id": UUID1,
                                                  'device': 'xxx'}})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_with_instance_invalid_state(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_instance_invalid_state)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 409)

    def test_attach_volume_with_invalid_volume(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_invalid_volume)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_with_invalid_request_body(self):
        url = "/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_invalid_volume)
        res = self._make_request(url, {"attach": None})
        self.assertEqual(res.status_int, 400)

    def _test_swap(self, uuid=UUID1, body=None):
        body = body or {'swap_volume_attachment': {'old_volume_id': uuid,
                                                   'new_volume_id': UUID2}}
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' % UUID1)
        req.method = 'PUT'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = context.get_admin_context()
        return self.Controller.swap(req, UUID1, body=body)

    def test_swap_volume(self):
        self.stubs.Set(compute.api.API, 'swap_volume', fake_swap_volume)
        # Check any exceptions don't happen and status code
        self._test_swap()
        self.assertEqual(202, self.Controller.swap.wsgi_code)

    def test_swap_volume_for_locked_server(self):
        def fake_swap_volume_for_locked_server(self, context, instance,
                                                old_volume, new_volume):
            raise exception.InstanceIsLocked(instance_uuid=instance['uuid'])
        self.stubs.Set(compute.api.API, 'swap_volume',
                       fake_swap_volume_for_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self._test_swap)

    def test_swap_volume_for_locked_server_new(self):
        self.stubs.Set(compute.api.API, 'swap_volume',
                       fakes.fake_actions_to_locked_server)
        self.assertRaises(webob.exc.HTTPConflict, self._test_swap)

    def test_swap_volume_instance_not_found(self):
        self.stubs.Set(compute.api.API, 'get', fake_compute_get_not_found)
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap)

    def test_swap_volume_with_bad_action(self):
        self.stubs.Set(compute.api.API, 'swap_volume', fake_swap_volume)
        body = {'swap_volume_attachment_bad_action': None}
        self.assertRaises(exception.ValidationError, self._test_swap,
                          body=body)

    def test_swap_volume_with_invalid_body(self):
        self.stubs.Set(compute.api.API, 'swap_volume', fake_swap_volume)
        body = {'swap_volume_attachment': {'bad_volume_id_body': UUID1,
                                           'new_volume_id': UUID2}}
        self.assertRaises(exception.ValidationError, self._test_swap,
                          body=body)

    def test_swap_volume_with_invalid_volume(self):
        self.stubs.Set(compute.api.API, 'swap_volume',
                       fake_swap_volume_invalid_volume)
        self.assertRaises(webob.exc.HTTPBadRequest, self._test_swap)

    def test_swap_volume_with_unattached_volume(self):
        self.stubs.Set(compute.api.API, 'swap_volume',
                       fake_swap_volume_unattached_volume)
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap)

    def test_swap_volume_with_bad_state_instance(self):
        self.stubs.Set(compute.api.API, 'swap_volume',
                       fake_swap_volume_instance_invalid_state)
        self.assertRaises(webob.exc.HTTPConflict, self._test_swap)

    def test_swap_volume_no_attachment(self):
        self.stubs.Set(compute.api.API, 'swap_volume', fake_swap_volume)
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap, UUID3)

    def test_swap_volume_not_found(self):
        self.stubs.Set(compute.api.API, 'swap_volume', fake_swap_volume)
        self.stubs.Set(volume.cinder.API, 'get', fake_volume_get_not_found)
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap)
