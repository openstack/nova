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
from oslo_serialization import jsonutils
import webob

from nova.api.openstack.compute.plugins.v3 import (extended_volumes
                                                   as extended_volumes_v21)
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


def fake_detach_volume(self, context, instance, volume):
    pass


def fake_volume_get(*args, **kwargs):
    pass


class ExtendedVolumesTestV21(test.TestCase):
    content_type = 'application/json'
    prefix = 'os-extended-volumes:'
    exp_volumes = [{'id': UUID1}, {'id': UUID2}]

    def setUp(self):
        super(ExtendedVolumesTestV21, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdms_get_all_by_instance)
        self._setUp()
        self.app = self._setup_app()
        return_server = fakes.fake_instance_get()
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

    def _setup_app(self):
        return fakes.wsgi_app_v21(init_only=('os-extended-volumes',
                                             'servers'))

    def _setUp(self):
        self.Controller = extended_volumes_v21.ExtendedVolumesController()
        self.stubs.Set(volume.cinder.API, 'get', fake_volume_get)
        self.stubs.Set(compute.api.API, 'detach_volume', fake_detach_volume)
        self.stubs.Set(compute.api.API, 'attach_volume', fake_attach_volume)
        self.action_url = "/%s/action" % UUID1

    def _make_request(self, url, body=None):
        req = webob.Request.blank('/v2/fake/servers' + url)
        req.headers['Accept'] = self.content_type
        if body:
            req.body = jsonutils.dumps(body)
            req.method = 'POST'
        req.content_type = self.content_type
        res = req.get_response(self.app)
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def test_show(self):
        res = self._make_request('/%s' % UUID1)

        self.assertEqual(200, res.status_int)
        server = self._get_server(res.body)
        actual = server.get('%svolumes_attached' % self.prefix)
        self.assertEqual(self.exp_volumes, actual)

    def test_detail(self):
        res = self._make_request('/detail')

        self.assertEqual(200, res.status_int)
        for i, server in enumerate(self._get_servers(res.body)):
            actual = server.get('%svolumes_attached' % self.prefix)
            self.assertEqual(self.exp_volumes, actual)


class ExtendedVolumesAdditionTestV21(ExtendedVolumesTestV21):

    def test_show(self):
        pass

    def test_detail(self):
        pass

    def test_detach(self):
        res = self._make_request(self.action_url,
                                 {"detach": {"volume_id": UUID1}})
        self.assertEqual(202, res.status_int)

    def test_detach_volume_from_locked_server(self):
        self.stubs.Set(compute.api.API, 'detach_volume',
                       fakes.fake_actions_to_locked_server)
        res = self._make_request(self.action_url,
                                 {"detach": {"volume_id": UUID1}})
        self.assertEqual(409, res.status_int)

    @mock.patch('nova.volume.cinder.API.get',
                side_effect=exception.VolumeNotFound(volume_id=UUID1))
    def test_detach_with_non_existed_vol(self, mock_detach):
        res = self._make_request(self.action_url,
                                 {"detach": {"volume_id": UUID2}})
        self.assertEqual(404, res.status_int)

    @mock.patch('nova.compute.api.API.get',
                side_effect=exception.InstanceNotFound(instance_id=UUID1))
    def test_detach_with_non_existed_instance(self, mock_detach):
        res = self._make_request(self.action_url,
                                 {"detach": {"volume_id": UUID2}})
        self.assertEqual(404, res.status_int)

    @mock.patch('nova.compute.api.API.detach_volume',
                side_effect=exception.InvalidVolume(reason=''))
    def test_detach_with_invalid_vol(self, mock_detach):
        res = self._make_request(self.action_url,
                                 {"detach": {"volume_id": UUID2}})
        self.assertEqual(400, res.status_int)

    def test_detach_with_bad_id(self):
        res = self._make_request(self.action_url,
                                 {"detach": {"volume_id": 'xxx'}})
        self.assertEqual(400, res.status_int)

    def test_detach_without_id(self):
        res = self._make_request(self.action_url, {"detach": {}})
        self.assertEqual(400, res.status_int)

    def test_detach_volume_with_invalid_request(self):
        res = self._make_request(self.action_url,
                                 {"detach": None})
        self.assertEqual(400, res.status_int)

    @mock.patch('nova.objects.BlockDeviceMapping.is_root',
                 new_callable=mock.PropertyMock)
    def test_detach_volume_root(self, mock_isroot):
        mock_isroot.return_value = True
        res = self._make_request(self.action_url,
                                 {"detach": {"volume_id": UUID1}})
        self.assertEqual(403, res.status_int)

    def test_attach_volume(self):
        res = self._make_request(self.action_url,
                                 {"attach": {"volume_id": UUID1}})
        self.assertEqual(202, res.status_int)

    def test_attach_volume_to_locked_server(self):
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fakes.fake_actions_to_locked_server)
        res = self._make_request(self.action_url,
                                 {"attach": {"volume_id": UUID1}})
        self.assertEqual(409, res.status_int)

    def test_attach_volume_disk_bus_and_disk_dev(self):
        self._make_request(self.action_url,
                                            {"attach": {"volume_id": UUID1,
                                            "device": "/dev/vdb",
                                            "disk_bus": "ide",
                                            "device_type": "cdrom"}})

    def test_attach_volume_with_bad_id(self):
        res = self._make_request(self.action_url,
                                 {"attach": {"volume_id": 'xxx'}})
        self.assertEqual(400, res.status_int)

    def test_attach_volume_without_id(self):
        res = self._make_request(self.action_url, {"attach": {}})
        self.assertEqual(400, res.status_int)

    def test_attach_volume_with_invalid_request(self):
        res = self._make_request(self.action_url,
                                 {"attach": None})
        self.assertEqual(400, res.status_int)

    @mock.patch('nova.compute.api.API.attach_volume',
                side_effect=exception.VolumeNotFound(volume_id=UUID1))
    def test_attach_volume_with_non_existe_vol(self, mock_attach):
        res = self._make_request(self.action_url,
                                 {"attach": {"volume_id": UUID1}})
        self.assertEqual(404, res.status_int)

    @mock.patch('nova.compute.api.API.get',
                side_effect=exception.InstanceNotFound(instance_id=UUID1))
    def test_attach_volume_with_non_existed_instance(self, mock_attach):
        res = self._make_request(self.action_url,
                                 {"attach": {"volume_id": UUID1}})
        self.assertEqual(404, res.status_int)

    @mock.patch('nova.compute.api.API.attach_volume',
                side_effect=exception.InvalidDevicePath(path='xxx'))
    def test_attach_volume_with_invalid_device_path(self, mock_attach):
        res = self._make_request(self.action_url,
                                 {"attach": {"volume_id": UUID1,
                                                  'device': 'xxx'}})
        self.assertEqual(400, res.status_int)

    @mock.patch('nova.compute.api.API.attach_volume',
                side_effect=exception.InstanceInvalidState(instance_uuid=UUID1,
                                                           state='',
                                                           method='', attr=''))
    def test_attach_volume_with_instance_invalid_state(self, mock_attach):
        res = self._make_request(self.action_url,
                                 {"attach": {"volume_id": UUID1}})
        self.assertEqual(409, res.status_int)

    @mock.patch('nova.compute.api.API.attach_volume',
                side_effect=exception.InvalidVolume(reason=''))
    def test_attach_volume_with_invalid_volume(self, mock_attach):
        res = self._make_request(self.action_url,
                                 {"attach": {"volume_id": UUID1}})
        self.assertEqual(400, res.status_int)

    @mock.patch('nova.compute.api.API.attach_volume',
                side_effect=exception.InvalidVolume(reason=''))
    def test_attach_volume_with_invalid_request_body(self, mock_attach):
        res = self._make_request(self.action_url, {"attach": None})
        self.assertEqual(400, res.status_int)

    def _test_swap(self, uuid=UUID1, body=None):
        body = body or {'swap_volume_attachment': {'old_volume_id': uuid,
                                                   'new_volume_id': UUID2}}
        req = fakes.HTTPRequest.blank('/v2/fake/servers/%s/action' % UUID1)
        req.method = 'PUT'
        req.body = jsonutils.dumps({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = context.get_admin_context()
        return self.Controller.swap(req, UUID1, body=body)

    @mock.patch('nova.compute.api.API.swap_volume')
    def test_swap_volume(self, mock_swap):
        # Check any exceptions don't happen and status code
        self._test_swap()
        self.assertEqual(202, self.Controller.swap.wsgi_code)

    @mock.patch('nova.compute.api.API.swap_volume',
                side_effect=exception.InstanceIsLocked(instance_uuid=UUID1))
    def test_swap_volume_for_locked_server(self, mock_swap):
        self.assertRaises(webob.exc.HTTPConflict, self._test_swap)

    @mock.patch('nova.compute.api.API.swap_volume',
                side_effect=exception.InstanceIsLocked(instance_uuid=UUID1))
    def test_swap_volume_for_locked_server_new(self, mock_swap):
        self.assertRaises(webob.exc.HTTPConflict, self._test_swap)

    @mock.patch('nova.compute.api.API.get',
                side_effect=exception.InstanceNotFound(instance_id=UUID1))
    def test_swap_volume_instance_not_found(self, mock_swap):
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap)

    @mock.patch('nova.compute.api.API.swap_volume')
    def test_swap_volume_with_bad_action(self, mock_swap):
        body = {'swap_volume_attachment_bad_action': None}
        self.assertRaises(exception.ValidationError, self._test_swap,
                          body=body)

    @mock.patch('nova.compute.api.API.swap_volume')
    def test_swap_volume_with_invalid_body(self, mock_swap):
        body = {'swap_volume_attachment': {'bad_volume_id_body': UUID1,
                                           'new_volume_id': UUID2}}
        self.assertRaises(exception.ValidationError, self._test_swap,
                          body=body)

    @mock.patch('nova.compute.api.API.swap_volume',
                side_effect=exception.InvalidVolume(reason=''))
    def test_swap_volume_with_invalid_volume(self, mock_swap):
        self.assertRaises(webob.exc.HTTPBadRequest, self._test_swap)

    @mock.patch('nova.compute.api.API.swap_volume',
                side_effect=exception.VolumeUnattached(reason=''))
    def test_swap_volume_with_unattached_volume(self, mock_swap):
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap)

    @mock.patch('nova.compute.api.API.swap_volume',
                side_effect=exception.InstanceInvalidState(instance_uuid=UUID1,
                                                           state='',
                                                           method='', attr=''))
    def test_swap_volume_with_bad_state_instance(self, mock_swap):
        self.assertRaises(webob.exc.HTTPConflict, self._test_swap)

    @mock.patch('nova.compute.api.API.swap_volume')
    def test_swap_volume_no_attachment(self, mock_swap):
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap, UUID3)

    @mock.patch('nova.compute.api.API.swap_volume')
    @mock.patch('nova.volume.cinder.API.get',
                side_effect=exception.VolumeNotFound(volume_id=UUID1))
    def test_swap_volume_not_found(self, mock_swap, mock_cinder_get):
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap)


class ExtendedVolumesTestV2(ExtendedVolumesTestV21):

    def _setup_app(self):
        return fakes.wsgi_app(init_only=('servers',))

    def _setUp(self):
        self.flags(
                   osapi_compute_extension=['nova.api.openstack.compute.'
                                            'contrib.select_extensions'],
                   osapi_compute_ext_list=['Extended_volumes'])
