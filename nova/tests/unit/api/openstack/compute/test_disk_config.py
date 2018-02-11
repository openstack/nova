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

import datetime

import mock
from oslo_serialization import jsonutils
import six

from nova.api.openstack import compute
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
import nova.tests.unit.image.fake


MANUAL_INSTANCE_UUID = fakes.FAKE_UUID
AUTO_INSTANCE_UUID = fakes.FAKE_UUID.replace('a', 'b')

stub_instance = fakes.stub_instance

API_DISK_CONFIG = 'OS-DCF:diskConfig'


def instance_addresses(context, instance_id):
    return None


class DiskConfigTestCaseV21(test.TestCase):

    def setUp(self):
        super(DiskConfigTestCaseV21, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_secgroup_api(self)
        self._set_up_app()
        self._setup_fake_image_service()

        FAKE_INSTANCES = [
            fakes.stub_instance(1,
                                uuid=MANUAL_INSTANCE_UUID,
                                auto_disk_config=False),
            fakes.stub_instance(2,
                                uuid=AUTO_INSTANCE_UUID,
                                auto_disk_config=True)
        ]

        def fake_instance_get(context, id_):
            for instance in FAKE_INSTANCES:
                if id_ == instance['id']:
                    return instance

        self.stub_out('nova.db.api.instance_get', fake_instance_get)

        def fake_instance_get_by_uuid(context, uuid,
                                      columns_to_join=None, use_slave=False):
            for instance in FAKE_INSTANCES:
                if uuid == instance['uuid']:
                    return instance

        self.stub_out('nova.db.api.instance_get_by_uuid',
                      fake_instance_get_by_uuid)

        def fake_instance_get_all(context, *args, **kwargs):
            return FAKE_INSTANCES

        self.stub_out('nova.db.api.instance_get_all', fake_instance_get_all)
        self.stub_out('nova.db.api.instance_get_all_by_filters',
                      fake_instance_get_all)

        self.stub_out('nova.objects.Instance.save',
                      lambda *args, **kwargs: None)

        def fake_rebuild(*args, **kwargs):
            pass

        self.stub_out('nova.compute.api.API.rebuild', fake_rebuild)

        def fake_instance_create(context, inst_, session=None):
            inst = fake_instance.fake_db_instance(**{
                    'id': 1,
                    'uuid': AUTO_INSTANCE_UUID,
                    'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
                    'updated_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
                    'progress': 0,
                    'name': 'instance-1',  # this is a property
                    'task_state': '',
                    'vm_state': '',
                    'auto_disk_config': inst_['auto_disk_config'],
                    'security_groups': inst_['security_groups'],
                    'instance_type': flavors.get_default_flavor(),
                    })

            def fake_instance_get_for_create(context, id_, *args, **kwargs):
                return (inst, inst)

            self.stub_out('nova.db.api.instance_update_and_get_original',
                          fake_instance_get_for_create)

            def fake_instance_get_all_for_create(context, *args, **kwargs):
                return [inst]
            self.stub_out('nova.db.api.instance_get_all',
                           fake_instance_get_all_for_create)
            self.stub_out('nova.db.api.instance_get_all_by_filters',
                           fake_instance_get_all_for_create)

            def fake_instance_add_security_group(context, instance_id,
                                                 security_group_id):
                pass

            self.stub_out('nova.db.api.instance_add_security_group',
                          fake_instance_add_security_group)

            return inst

        self.stub_out('nova.db.api.instance_create', fake_instance_create)

    def _set_up_app(self):
        self.app = compute.APIRouterV21()

    def _get_expected_msg_for_invalid_disk_config(self):
        if six.PY3:
            return ('{{"badRequest": {{"message": "Invalid input for'
                    ' field/attribute {0}. Value: {1}. \'{1}\' is'
                    ' not one of [\'AUTO\', \'MANUAL\']", "code": 400}}}}')
        else:
            return ('{{"badRequest": {{"message": "Invalid input for'
                    ' field/attribute {0}. Value: {1}. u\'{1}\' is'
                    ' not one of [\'AUTO\', \'MANUAL\']", "code": 400}}}}')

    def _setup_fake_image_service(self):
        self.image_service = nova.tests.unit.image.fake.stub_out_image_service(
                self)
        timestamp = datetime.datetime(2011, 1, 1, 1, 2, 3)
        image = {'id': '88580842-f50a-11e2-8d3a-f23c91aec05e',
                 'name': 'fakeimage7',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': False,
                 'container_format': 'ova',
                 'disk_format': 'vhd',
                 'size': '74185822',
                 'properties': {'auto_disk_config': 'Disabled'}}
        self.image_service.create(None, image)

    def tearDown(self):
        super(DiskConfigTestCaseV21, self).tearDown()
        nova.tests.unit.image.fake.FakeImageService_reset()

    def assertDiskConfig(self, dict_, value):
        self.assertIn(API_DISK_CONFIG, dict_)
        self.assertEqual(dict_[API_DISK_CONFIG], value)

    def test_show_server(self):
        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s' % MANUAL_INSTANCE_UUID)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s' % AUTO_INSTANCE_UUID)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_detail_servers(self):
        req = fakes.HTTPRequest.blank('/fake/servers/detail')
        res = req.get_response(self.app)
        server_dicts = jsonutils.loads(res.body)['servers']

        expectations = ['MANUAL', 'AUTO']
        for server_dict, expected in zip(server_dicts, expectations):
            self.assertDiskConfig(server_dict, expected)

    def test_show_image(self):
        self.flags(group='glance', api_servers=['http://localhost:9292'])

        req = fakes.HTTPRequest.blank(
            '/fake/images/a440c04b-79fa-479c-bed1-0b816eaec379')
        res = req.get_response(self.app)
        image_dict = jsonutils.loads(res.body)['image']
        self.assertDiskConfig(image_dict, 'MANUAL')

        req = fakes.HTTPRequest.blank(
            '/fake/images/70a599e0-31e7-49b7-b260-868f441e862b')
        res = req.get_response(self.app)
        image_dict = jsonutils.loads(res.body)['image']
        self.assertDiskConfig(image_dict, 'AUTO')

    def test_detail_image(self):
        req = fakes.HTTPRequest.blank('/fake/images/detail')
        res = req.get_response(self.app)
        image_dicts = jsonutils.loads(res.body)['images']

        expectations = ['MANUAL', 'AUTO']
        for image_dict, expected in zip(image_dicts, expectations):
            # NOTE(sirp): image fixtures 6 and 7 are setup for
            # auto_disk_config testing
            if image_dict['id'] in (6, 7):
                self.assertDiskConfig(image_dict, expected)

    def test_create_server_override_auto(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
                  API_DISK_CONFIG: 'AUTO'
               }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_create_server_override_manual(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
                  API_DISK_CONFIG: 'MANUAL'
               }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

    def test_create_server_detect_from_image(self):
        """If user doesn't pass in diskConfig for server, use image metadata
        to specify AUTO or MANUAL.
        """
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': 'a440c04b-79fa-479c-bed1-0b816eaec379',
                  'flavorRef': '1',
               }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': '70a599e0-31e7-49b7-b260-868f441e862b',
                  'flavorRef': '1',
               }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_create_server_detect_from_image_disabled_goes_to_manual(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': '88580842-f50a-11e2-8d3a-f23c91aec05e',
                  'flavorRef': '1',
               }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

    def test_create_server_errors_when_disabled_and_auto(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': '88580842-f50a-11e2-8d3a-f23c91aec05e',
                  'flavorRef': '1',
                  API_DISK_CONFIG: 'AUTO'
               }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 400)

    def test_create_server_when_disabled_and_manual(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': '88580842-f50a-11e2-8d3a-f23c91aec05e',
                  'flavorRef': '1',
                  API_DISK_CONFIG: 'MANUAL'
               }}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

    @mock.patch('nova.api.openstack.common.get_instance')
    def _test_update_server_disk_config(self, uuid, disk_config,
                                        get_instance_mock):
        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s' % uuid)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {API_DISK_CONFIG: disk_config}}
        req.body = jsonutils.dump_as_bytes(body)
        auto_disk_config = (disk_config == 'AUTO')
        instance = fakes.stub_instance_obj(
                       req.environ['nova.context'],
                       project_id=req.environ['nova.context'].project_id,
                       user_id=req.environ['nova.context'].user_id,
                       auto_disk_config=auto_disk_config)
        get_instance_mock.return_value = instance
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, disk_config)

    def test_update_server_override_auto(self):
        self._test_update_server_disk_config(AUTO_INSTANCE_UUID, 'AUTO')

    def test_update_server_override_manual(self):
        self._test_update_server_disk_config(MANUAL_INSTANCE_UUID, 'MANUAL')

    def test_update_server_invalid_disk_config(self):
        # Return BadRequest if user passes an invalid diskConfig value.
        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s' % MANUAL_INSTANCE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {API_DISK_CONFIG: 'server_test'}}
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 400)
        expected_msg = self._get_expected_msg_for_invalid_disk_config()
        expected_msg = expected_msg.format(API_DISK_CONFIG, 'server_test')

        self.assertJsonEqual(jsonutils.loads(expected_msg),
                             jsonutils.loads(res.body))

    @mock.patch('nova.api.openstack.common.get_instance')
    def _test_rebuild_server_disk_config(self, uuid, disk_config,
                                         get_instance_mock):
        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s/action' % uuid)
        req.method = 'POST'
        req.content_type = 'application/json'
        auto_disk_config = (disk_config == 'AUTO')
        instance = fakes.stub_instance_obj(
                       req.environ['nova.context'],
                       project_id=req.environ['nova.context'].project_id,
                       user_id=req.environ['nova.context'].user_id,
                       auto_disk_config=auto_disk_config)
        get_instance_mock.return_value = instance
        body = {"rebuild": {
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  API_DISK_CONFIG: disk_config
               }}
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, disk_config)

    def test_rebuild_server_override_auto(self):
        self._test_rebuild_server_disk_config(AUTO_INSTANCE_UUID, 'AUTO')

    def test_rebuild_server_override_manual(self):
        self._test_rebuild_server_disk_config(MANUAL_INSTANCE_UUID, 'MANUAL')

    def test_create_server_with_auto_disk_config(self):
        req = fakes.HTTPRequest.blank('/fake/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'server': {
                  'name': 'server_test',
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  'flavorRef': '1',
                  API_DISK_CONFIG: 'AUTO'
               }}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIn('auto_disk_config', kwargs)
            self.assertTrue(kwargs['auto_disk_config'])
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    @mock.patch('nova.api.openstack.common.get_instance')
    def test_rebuild_server_with_auto_disk_config(self, get_instance_mock):
        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s/action' % AUTO_INSTANCE_UUID)
        req.method = 'POST'
        req.content_type = 'application/json'
        instance = fakes.stub_instance_obj(
                       req.environ['nova.context'],
                       project_id=req.environ['nova.context'].project_id,
                       user_id=req.environ['nova.context'].user_id,
                       auto_disk_config=True)
        get_instance_mock.return_value = instance
        body = {"rebuild": {
                  'imageRef': 'cedef40a-ed67-4d10-800e-17455edce175',
                  API_DISK_CONFIG: 'AUTO'
               }}

        def rebuild(*args, **kwargs):
            self.assertIn('auto_disk_config', kwargs)
            self.assertTrue(kwargs['auto_disk_config'])

        self.stub_out('nova.compute.api.API.rebuild', rebuild)

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'AUTO')

    def test_resize_server_with_auto_disk_config(self):
        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s/action' % AUTO_INSTANCE_UUID)
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {"resize": {
                    "flavorRef": "3",
                    API_DISK_CONFIG: 'AUTO'
               }}

        def resize(*args, **kwargs):
            self.assertIn('auto_disk_config', kwargs)
            self.assertTrue(kwargs['auto_disk_config'])

        self.stub_out('nova.compute.api.API.resize', resize)

        req.body = jsonutils.dump_as_bytes(body)
        req.get_response(self.app)
