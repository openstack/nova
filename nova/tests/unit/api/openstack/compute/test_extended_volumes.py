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

from nova.api.openstack.compute import (extended_volumes
                                                   as extended_volumes_v21)
from nova.api.openstack import wsgi as os_wsgi
from nova import compute
from nova import context as nova_context
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids
from nova import volume

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID1)
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_compute_get_all(*args, **kwargs):
    db_list = [
        fakes.stub_instance(1, uuid=UUID1),
        fakes.stub_instance(2, uuid=UUID2),
    ]
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            objects.InstanceList(),
                                            db_list, fields)


def fake_bdms_get_all_by_instance_uuids(*args, **kwargs):
    return [
        fake_block_device.FakeDbBlockDeviceDict({
            'id': 1,
            'volume_id': 'some_volume_1',
            'instance_uuid': UUID1,
            'source_type': 'volume',
            'destination_type': 'volume',
            'delete_on_termination': True,
        }),
        fake_block_device.FakeDbBlockDeviceDict({
            'id': 2,
            'volume_id': 'some_volume_2',
            'instance_uuid': UUID2,
            'source_type': 'volume',
            'destination_type': 'volume',
            'delete_on_termination': False,
        }),
        fake_block_device.FakeDbBlockDeviceDict({
            'id': 3,
            'volume_id': 'some_volume_3',
            'instance_uuid': UUID2,
            'source_type': 'volume',
            'destination_type': 'volume',
            'delete_on_termination': False,
        }),
    ]


def fake_volume_get(*args, **kwargs):
    pass


class ExtendedVolumesTestV21(test.TestCase):
    content_type = 'application/json'
    prefix = 'os-extended-volumes:'
    exp_volumes_show = [{'id': 'some_volume_1'}]
    exp_volumes_detail = [
        [{'id': 'some_volume_1'}],
        [{'id': 'some_volume_2'}, {'id': 'some_volume_3'}],
    ]
    wsgi_api_version = os_wsgi.DEFAULT_API_VERSION

    def setUp(self):
        super(ExtendedVolumesTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_secgroup_api(self)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)
        self.stub_out('nova.db.block_device_mapping_get_all_by_instance_uuids',
                       fake_bdms_get_all_by_instance_uuids)
        self._setUp()
        self.app = self._setup_app()
        return_server = fakes.fake_instance_get()
        self.stub_out('nova.db.instance_get_by_uuid', return_server)

    def _setup_app(self):
        return fakes.wsgi_app_v21()

    def _setUp(self):
        self.Controller = extended_volumes_v21.ExtendedVolumesController()
        self.stubs.Set(volume.cinder.API, 'get', fake_volume_get)

    def _make_request(self, url, body=None):
        req = fakes.HTTPRequest.blank('/v2/fake/servers' + url)
        req.headers['Accept'] = self.content_type
        req.headers = {os_wsgi.API_VERSION_REQUEST_HEADER:
                       'compute %s' % self.wsgi_api_version}
        if body:
            req.body = jsonutils.dump_as_bytes(body)
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
        self.assertEqual(self.exp_volumes_show, actual)

    @mock.patch.object(objects.InstanceMappingList, 'get_by_instance_uuids')
    def test_detail(self, mock_get_by_instance_uuids):
        mock_get_by_instance_uuids.return_value = [
            objects.InstanceMapping(
                instance_uuid=UUID1,
                cell_mapping=objects.CellMapping(
                    uuid=uuids.cell1,
                    transport_url='fake://nowhere/',
                    database_connection=uuids.cell1)),
            objects.InstanceMapping(
                instance_uuid=UUID2,
                cell_mapping=objects.CellMapping(
                    uuid=uuids.cell1,
                    transport_url='fake://nowhere/',
                    database_connection=uuids.cell1))]

        res = self._make_request('/detail')
        mock_get_by_instance_uuids.assert_called_once_with(
            test.MatchType(nova_context.RequestContext), [UUID1, UUID2])

        self.assertEqual(200, res.status_int)
        for i, server in enumerate(self._get_servers(res.body)):
            actual = server.get('%svolumes_attached' % self.prefix)
            self.assertEqual(self.exp_volumes_detail[i], actual)


class ExtendedVolumesTestV23(ExtendedVolumesTestV21):

    exp_volumes_show = [
        {'id': 'some_volume_1', 'delete_on_termination': True},
    ]
    exp_volumes_detail = [
        [
            {'id': 'some_volume_1', 'delete_on_termination': True},
        ],
        [
            {'id': 'some_volume_2', 'delete_on_termination': False},
            {'id': 'some_volume_3', 'delete_on_termination': False},
        ],
    ]
    wsgi_api_version = '2.3'


class ExtendedVolumesEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(ExtendedVolumesEnforcementV21, self).setUp()
        self.controller = extended_volumes_v21.ExtendedVolumesController()
        self.req = fakes.HTTPRequest.blank('')

    @mock.patch.object(extended_volumes_v21.ExtendedVolumesController,
                       '_extend_server')
    def test_extend_show_policy_failed(self, mock_extend):
        rule_name = 'os_compute_api:os-extended-volumes'
        self.policy.set_rules({rule_name: "project:non_fake"})
        # Pass ResponseObj as None, the code shouldn't touch the None.
        self.controller.show(self.req, None, fakes.FAKE_UUID)
        self.assertFalse(mock_extend.called)

    @mock.patch.object(extended_volumes_v21.ExtendedVolumesController,
                   '_extend_server')
    def test_extend_detail_policy_failed(self, mock_extend):
        rule_name = 'os_compute_api:os-extended-volumes'
        self.policy.set_rules({rule_name: "project:non_fake"})
        # Pass ResponseObj as None, the code shouldn't touch the None.
        self.controller.detail(self.req, None)
        self.assertFalse(mock_extend.called)
