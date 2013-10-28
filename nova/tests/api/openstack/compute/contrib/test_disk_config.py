# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

from nova.api.openstack import compute
from nova import db
from nova.openstack.common import jsonutils
import nova.openstack.common.rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
import nova.tests.image.fake


MANUAL_INSTANCE_UUID = fakes.FAKE_UUID
AUTO_INSTANCE_UUID = fakes.FAKE_UUID.replace('a', 'b')

stub_instance = fakes.stub_instance

API_DISK_CONFIG = 'OS-DCF:diskConfig'


def instance_addresses(context, instance_id):
    return None


class DiskConfigTestCase(test.TestCase):

    def setUp(self):
        super(DiskConfigTestCase, self).setUp()
        self.flags(verbose=True,
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Disk_config'])
        self._setup_fake_image_service()

        fakes.stub_out_nw_api(self.stubs)

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

        self.stubs.Set(db, 'instance_get', fake_instance_get)

        def fake_instance_get_by_uuid(context, uuid,
                                      columns_to_join=None, use_slave=False):
            for instance in FAKE_INSTANCES:
                if uuid == instance['uuid']:
                    return instance

        self.stubs.Set(db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid)

        def fake_instance_get_all(context, *args, **kwargs):
            return FAKE_INSTANCES

        self.stubs.Set(db, 'instance_get_all', fake_instance_get_all)
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_instance_get_all)

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
                    })

            def fake_instance_get_for_create(context, id_, *args, **kwargs):
                return (inst, inst)

            self.stubs.Set(db, 'instance_update_and_get_original',
                          fake_instance_get_for_create)

            def fake_instance_get_all_for_create(context, *args, **kwargs):
                return [inst]
            self.stubs.Set(db, 'instance_get_all',
                           fake_instance_get_all_for_create)
            self.stubs.Set(db, 'instance_get_all_by_filters',
                           fake_instance_get_all_for_create)

            def fake_instance_add_security_group(context, instance_id,
                                                 security_group_id):
                pass

            self.stubs.Set(db,
                           'instance_add_security_group',
                           fake_instance_add_security_group)

            return inst

        self.stubs.Set(db, 'instance_create', fake_instance_create)

        self.app = compute.APIRouter(init_only=('servers', 'images'))

    def _setup_fake_image_service(self):
        self.image_service = nova.tests.image.fake.stub_out_image_service(
                self.stubs)
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
        super(DiskConfigTestCase, self).tearDown()
        nova.tests.image.fake.FakeImageService_reset()

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

        req.body = jsonutils.dumps(body)
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

        req.body = jsonutils.dumps(body)
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

        req.body = jsonutils.dumps(body)
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

        req.body = jsonutils.dumps(body)
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

        req.body = jsonutils.dumps(body)
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

        req.body = jsonutils.dumps(body)
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

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        server_dict = jsonutils.loads(res.body)['server']
        self.assertDiskConfig(server_dict, 'MANUAL')

    def test_update_server_invalid_disk_config(self):
        # Return BadRequest if user passes an invalid diskConfig value.
        req = fakes.HTTPRequest.blank(
            '/fake/servers/%s' % MANUAL_INSTANCE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {API_DISK_CONFIG: 'server_test'}}
        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 400)
        expected_msg = ('{"badRequest": {"message": "%s must be either'
                        ' \'MANUAL\' or \'AUTO\'.", "code": 400}}' %
                        API_DISK_CONFIG)
        self.assertEqual(res.body, expected_msg)
