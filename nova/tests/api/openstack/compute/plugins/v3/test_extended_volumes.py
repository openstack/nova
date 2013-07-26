# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from lxml import etree
import webob

from nova.api.openstack.compute.plugins.v3 import extended_volumes
from nova import compute
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova import volume

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get(*args, **kwargs):
    return fakes.stub_instance(1, uuid=UUID1)


def fake_compute_get_not_found(*args, **kwargs):
    raise exception.InstanceNotFound(instance_id=UUID1)


def fake_compute_get_all(*args, **kwargs):
    db_list = [fakes.stub_instance(1), fakes.stub_instance(2)]
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            instance_obj.InstanceList(),
                                            db_list, fields)


def fake_compute_get_instance_bdms(*args, **kwargs):
    return [{'volume_id': UUID1}, {'volume_id': UUID2}]


def fake_attach_volume(self, context, instance, volume_id, device):
    pass


def fake_attach_volume_not_found_vol(self, context, instance, volume_id,
                                     device):
    raise exception.VolumeNotFound(volume_id=volume_id)


def fake_attach_volume_invalid_device_path(self, context, instance,
                                           volume_id, device):
    raise exception.InvalidDevicePath(path=device)


def fake_attach_volume_instance_invalid_state(self, context, instance,
                                              volume_id, device):
    raise exception.InstanceInvalidState(instance_uuid=UUID1, state='',
                                         method='', attr='')


def fake_attach_volume_invalid_volume(self, context, instance,
                                      volume_id, device):
    raise exception.InvalidVolume(reason='')


def fake_detach_volume(self, context, instance, volume):
    pass


def fake_detach_volume_invalid_volume(self, context, instance, volume):
    raise exception.InvalidVolume(reason='')


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
        self.stubs.Set(compute.api.API, 'get_instance_bdms',
                       fake_compute_get_instance_bdms)
        self.stubs.Set(volume.cinder.API, 'get', fake_volume_get)
        self.stubs.Set(compute.api.API, 'detach_volume', fake_detach_volume)
        self.stubs.Set(compute.api.API, 'attach_volume', fake_attach_volume)
        self.app = fakes.wsgi_app_v3(init_only=('os-extended-volumes',
                                                'servers'))

    def _make_request(self, url, body=None):
        req = webob.Request.blank(url)
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
        url = '/v3/servers/%s' % UUID1
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        server = self._get_server(res.body)
        exp_volumes = [{'id': UUID1}, {'id': UUID2}]
        if self.content_type == 'application/json':
            actual = server.get('%svolumes_attached' % self.prefix)
        elif self.content_type == 'application/xml':
            actual = [dict(elem.items()) for elem in
                      server.findall('%svolume_attached' % self.prefix)]
        self.assertEqual(exp_volumes, actual)

    def test_detail(self):
        url = '/v3/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        exp_volumes = [{'id': UUID1}, {'id': UUID2}]
        for i, server in enumerate(self._get_servers(res.body)):
            if self.content_type == 'application/json':
                actual = server.get('%svolumes_attached' % self.prefix)
            elif self.content_type == 'application/xml':
                actual = [dict(elem.items()) for elem in
                          server.findall('%svolume_attached' % self.prefix)]
            self.assertEqual(exp_volumes, actual)

    def test_detach(self):
        url = "/v3/servers/%s/action" % UUID1
        res = self._make_request(url, {"detach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 202)

    def test_detach_with_non_existed_vol(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(volume.cinder.API, 'get', fake_volume_get_not_found)
        res = self._make_request(url, {"detach": {"volume_id": UUID2}})
        self.assertEqual(res.status_int, 404)

    def test_detach_with_non_existed_instance(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'get', fake_compute_get_not_found)
        res = self._make_request(url, {"detach": {"volume_id": UUID2}})
        self.assertEqual(res.status_int, 404)

    def test_detach_with_invalid_vol(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'detach_volume',
                       fake_detach_volume_invalid_volume)
        res = self._make_request(url, {"detach": {"volume_id": UUID2}})
        self.assertEqual(res.status_int, 400)

    def test_detach_with_bad_id(self):
        url = "/v3/servers/%s/action" % UUID1
        res = self._make_request(url, {"detach": {"volume_id": 'xxx'}})
        self.assertEqual(res.status_int, 400)

    def test_detach_without_id(self):
        url = "/v3/servers/%s/action" % UUID1
        res = self._make_request(url, {"detach": {}})
        self.assertEqual(res.status_int, 400)

    def test_detach_volume_with_invalid_request(self):
        url = "/v3/servers/%s/action" % UUID1
        res = self._make_request(url, {"detach": None})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume(self):
        url = "/v3/servers/%s/action" % UUID1
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 202)

    def test_attach_volume_with_bad_id(self):
        url = "/v3/servers/%s/action" % UUID1
        res = self._make_request(url, {"attach": {"volume_id": 'xxx'}})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_without_id(self):
        url = "/v3/servers/%s/action" % UUID1
        res = self._make_request(url, {"attach": {}})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_with_invalid_request(self):
        url = "/v3/servers/%s/action" % UUID1
        res = self._make_request(url, {"attach": None})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_with_non_existe_vol(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_not_found_vol)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 404)

    def test_attach_volume_with_non_existed_instance(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'get', fake_compute_get_not_found)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 404)

    def test_attach_volume_with_invalid_device_path(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_invalid_device_path)
        res = self._make_request(url, {"attach": {"volume_id": UUID1,
                                                  'device': 'xxx'}})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_with_instance_invalid_state(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_instance_invalid_state)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 409)

    def test_attach_volume_with_invalid_volume(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_invalid_volume)
        res = self._make_request(url, {"attach": {"volume_id": UUID1}})
        self.assertEqual(res.status_int, 400)

    def test_attach_volume_with_invalid_request_body(self):
        url = "/v3/servers/%s/action" % UUID1
        self.stubs.Set(compute.api.API, 'attach_volume',
                       fake_attach_volume_invalid_volume)
        res = self._make_request(url, {"attach": None})
        self.assertEqual(res.status_int, 400)


class ExtendedVolumesXmlTest(ExtendedVolumesTest):
    content_type = 'application/xml'
    prefix = '{%s}' % extended_volumes.ExtendedVolumes.namespace

    def _get_server(self, body):
        return etree.XML(body)

    def _get_servers(self, body):
        return etree.XML(body).getchildren()
