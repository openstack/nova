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

import webob

from nova.api.openstack.compute import server_shares
from nova.compute import vm_states
from nova import context
from nova.db.main import models
from nova import objects
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.compute.test_compute import BaseTestCase
from nova.tests.unit import fake_instance

from nova.tests import fixtures as nova_fixtures
from oslo_utils import timeutils

from unittest import mock

UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
NON_EXISTING_UUID = '123'


def return_server(compute_api, context, instance_id, expected_attrs=None):
    return fake_instance.fake_instance_obj(context, vm_state=vm_states.ACTIVE)


def return_invalid_server(compute_api, context, instance_id,
                          expected_attrs=None):
    return fake_instance.fake_instance_obj(context,
                                           vm_state=vm_states.BUILDING)


class ServerSharesTest(BaseTestCase):
    wsgi_api_version = '2.97'

    def setUp(self):
        super(ServerSharesTest, self).setUp()
        self.controller = server_shares.ServerSharesController()
        inst_map = objects.InstanceMapping(
            project_id=fakes.FAKE_PROJECT_ID,
            user_id=fakes.FAKE_USER_ID,
            cell_mapping=objects.CellMappingList.get_all(
                context.get_admin_context())[1])
        self.stub_out('nova.objects.InstanceMapping.get_by_instance_uuid',
                      lambda s, c, u: inst_map)
        self.req = fakes.HTTPRequest.blank(
                '/servers/%s/shares' % (UUID),
                use_admin_context=False, version=self.wsgi_api_version)
        self.manila_fixture = self.useFixture(nova_fixtures.ManilaFixture())

    def fake_get_instance(self):
        ctxt = self.req.environ['nova.context']
        return fake_instance.fake_instance_obj(
                ctxt,
                uuid=fakes.FAKE_UUID,
                flavor = objects.Flavor(id=1, name='flavor1',
                    memory_mb=256, vcpus=1,
                    root_gb=1, ephemeral_gb=1,
                    flavorid='1',
                    swap=0, rxtx_factor=1.0,
                    vcpu_weight=1,
                    disabled=False,
                    is_public=True,
                    extra_specs={
                        'virtiofs': 'required',
                        'mem_backing_file': 'required'
                        },
                    projects=[]),
                vm_state=vm_states.STOPPED)

    @mock.patch(
        'nova.virt.hardware.check_shares_supported', return_value=None
    )
    @mock.patch('nova.db.main.api.share_mapping_get_by_instance_uuid')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_index(
            self, mock_get_instance, mock_db_get_shares, mock_shares_support
    ):
        timeutils.set_time_override()
        NOW = timeutils.utcnow()
        instance = self.fake_get_instance()
        mock_get_instance.return_value = instance

        fake_db_shares = [
            {
                'created_at': NOW,
                'updated_at': None,
                'deleted_at': None,
                'deleted': False,
                "id": 1,
                "uuid": "33a8e0cb-5f82-409a-b310-89c41f8bf023",
                "instance_uuid": "48c16a1a-183f-4052-9dac-0e4fc1e498ae",
                "share_id": "48c16a1a-183f-4052-9dac-0e4fc1e498ad",
                "status": "active",
                "tag": "foo",
                "export_location": "10.0.0.50:/mnt/foo",
                "share_proto": "NFS",
            },
            {
                'created_at': NOW,
                'updated_at': None,
                'deleted_at': None,
                'deleted': False,
                "id": 2,
                "uuid": "33a8e0cb-5f82-409a-b310-89c41f8bf024",
                "instance_uuid": "48c16a1a-183f-4052-9dac-0e4fc1e498ae",
                "share_id": "e8debdc0-447a-4376-a10a-4cd9122d7986",
                "status": "active",
                "tag": "bar",
                "export_location": "10.0.0.50:/mnt/bar",
                "share_proto": "NFS",
            }
        ]

        fake_shares = {
            "shares": [
                {
                    "share_id": "48c16a1a-183f-4052-9dac-0e4fc1e498ad",
                    "status": "active",
                    "tag": "foo",
                },
                {
                    "share_id": "e8debdc0-447a-4376-a10a-4cd9122d7986",
                    "status": "active",
                    "tag": "bar",
                }
            ]
        }

        mock_db_get_shares.return_value = fake_db_shares
        output = self.controller.index(self.req, instance.uuid)
        mock_db_get_shares.assert_called_once_with(mock.ANY, instance.uuid)
        self.assertEqual(output, fake_shares)

    @mock.patch(
        'nova.virt.hardware.check_shares_supported', return_value=None
    )
    @mock.patch(
        'nova.compute.utils.notify_about_share_attach_detach',
        return_value=None
    )
    @mock.patch(
        'nova.db.main.api.share_mapping_get_by_instance_uuid_and_share_id'
    )
    @mock.patch('nova.db.main.api.share_mapping_update')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_create(
        self,
        mock_get_instance,
        mock_db_update_share,
        mock_db_get_share,
        mock_notifications,
        mock_shares_support,
    ):
        instance = self.fake_get_instance()

        mock_get_instance.return_value = instance

        fake_db_share = {
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
            "id": 1,
            "uuid": "7ddcf3ae-82d4-4f93-996a-2b6cbcb42c2b",
            "instance_uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "share_id": "e8debdc0-447a-4376-a10a-4cd9122d7986",
            "status": "attaching",
            "tag": "e8debdc0-447a-4376-a10a-4cd9122d7986",
            "export_location": "10.0.0.50:/mnt/foo",
            "share_proto": "NFS",
        }

        body = {
            'share': {
                'share_id': 'e8debdc0-447a-4376-a10a-4cd9122d7986'
            }}

        mock_db_update_share.return_value = fake_db_share
        mock_db_get_share.side_effect = [None, fake_db_share]
        self.controller.create(self.req, instance.uuid, body=body)

        mock_db_update_share.assert_called_once_with(
            mock.ANY,
            mock.ANY,
            instance.uuid,
            fake_db_share['share_id'],
            'attaching',
            fake_db_share['tag'],
            fake_db_share['export_location'],
            fake_db_share['share_proto'],
        )

    @mock.patch('nova.compute.api.API.allow_share')
    @mock.patch(
        'nova.virt.hardware.check_shares_supported', return_value=None
    )
    @mock.patch(
        'nova.db.main.api.share_mapping_get_by_instance_uuid_and_share_id'
    )
    @mock.patch('nova.db.main.api.share_mapping_update')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_create_share_with_new_tag(
        self,
        mock_get_instance,
        mock_db_update_share,
        mock_db_get_share,
        mock_shares_support,
        mock_allow
    ):
        instance = self.fake_get_instance()

        mock_get_instance.return_value = instance

        fake_db_share = {
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
            "id": 1,
            "uuid": "7ddcf3ae-82d4-4f93-996a-2b6cbcb42c2b",
            "instance_uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "share_id": "e8debdc0-447a-4376-a10a-4cd9122d7986",
            "status": "attaching",
            "tag": "e8debdc0-447a-4376-a10a-4cd9122d7986",
            "export_location": "10.0.0.50:/mnt/foo",
            "share_proto": "NFS",
        }

        body = {
            'share': {
                'share_id': 'e8debdc0-447a-4376-a10a-4cd9122d7986'
            }}

        mock_db_update_share.return_value = fake_db_share
        mock_db_get_share.side_effect = [None, fake_db_share]
        self.controller.create(self.req, instance.uuid, body=body)

        mock_allow.assert_called_once()
        self.assertIsInstance(
            mock_allow.call_args.args[1], objects.instance.Instance)
        self.assertEqual(mock_allow.call_args.args[1].uuid, instance.uuid)
        self.assertIsInstance(
            mock_allow.call_args.args[2], objects.share_mapping.ShareMapping)
        self.assertEqual(
            mock_allow.call_args.args[2].share_id, fake_db_share['share_id'])

        mock_db_update_share.assert_called_once_with(
            mock.ANY,
            mock.ANY,
            instance.uuid,
            fake_db_share['share_id'],
            'attaching',
            fake_db_share['tag'],
            fake_db_share['export_location'],
            fake_db_share['share_proto'],
        )

        # Change the tag of the share
        body['share']['tag'] = 'my-tag'
        mock_db_update_share.return_value['tag'] = "my-tag"
        mock_db_get_share.side_effect = [
            fake_db_share,
            mock_db_update_share.return_value,
        ]

        exc = self.assertRaises(
            webob.exc.HTTPConflict,
            self.controller.create,
            self.req,
            instance.uuid,
            body=body,
        )

        self.assertIn(
            "Share 'e8debdc0-447a-4376-a10a-4cd9122d7986' or tag 'my-tag' "
            "already associated to this server",
            str(exc))

    @mock.patch(
        'nova.virt.hardware.check_shares_supported', return_value=None
    )
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_create_passing_a_share_with_an_error(
        self,
        mock_get_instance,
        mock_shares_support,
    ):
        instance = self.fake_get_instance()

        mock_get_instance.return_value = instance

        body = {
            'share': {
                'share_id': 'e8debdc0-447a-4376-a10a-4cd9122d7986'
            }}

        self.manila_fixture.mock_get.side_effect = (
            self.manila_fixture.fake_get_share_status_error
        )

        exc = self.assertRaises(
            webob.exc.HTTPConflict,
            self.controller.create,
            self.req,
            instance.uuid,
            body=body,
        )
        self.assertEqual(
            str(exc),
            "Share e8debdc0-447a-4376-a10a-4cd9122d7986 is in 'error' "
            "instead of 'available' status.",
        )

    @mock.patch(
        'nova.virt.hardware.check_shares_supported', return_value=None
    )
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_create_passing_unknown_protocol(
        self,
        mock_get_instance,
        mock_shares_support,
    ):
        instance = self.fake_get_instance()

        mock_get_instance.return_value = instance

        body = {
            'share': {
                'share_id': 'e8debdc0-447a-4376-a10a-4cd9122d7986'
            }}

        self.manila_fixture.mock_get.side_effect = (
            self.manila_fixture.fake_get_share_unknown_protocol
        )

        exc = self.assertRaises(
            webob.exc.HTTPConflict,
            self.controller.create,
            self.req,
            instance.uuid,
            body=body,
        )
        self.assertEqual(
            str(exc),
            "Share protocol CIFS is not supported."
        )

    @mock.patch('nova.compute.api.API.deny_share')
    @mock.patch(
        'nova.virt.hardware.check_shares_supported', return_value=None
    )
    @mock.patch(
        'nova.compute.utils.notify_about_share_attach_detach',
        return_value=None
    )
    @mock.patch('nova.db.main.api.'
            'share_mapping_delete_by_instance_uuid_and_share_id')
    @mock.patch('nova.db.main.api.'
            'share_mapping_get_by_instance_uuid_and_share_id')
    @mock.patch('nova.api.openstack.common.get_instance')
    def test_delete(
        self,
        mock_get_instance,
        mock_db_get_shares,
        mock_db_delete_share,
        mock_notifications,
        mock_shares_support,
        mock_deny
    ):
        instance = self.fake_get_instance()

        mock_get_instance.return_value = instance

        fake_db_share = models.ShareMapping()
        fake_db_share.created_at = None
        fake_db_share.updated_at = None
        fake_db_share.deleted_at = None
        fake_db_share.deleted = False
        fake_db_share.id = 1
        fake_db_share.uuid = "33a8e0cb-5f82-409a-b310-89c41f8bf023"
        fake_db_share.instance_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        fake_db_share.share_id = "e8debdc0-447a-4376-a10a-4cd9122d7986"
        fake_db_share.status = "inactive"
        fake_db_share.tag = "e8debdc0-447a-4376-a10a-4cd9122d7986"
        fake_db_share.export_location = "10.0.0.50:/mnt/foo"
        fake_db_share.share_proto = "NFS"

        mock_db_get_shares.return_value = fake_db_share
        self.controller.delete(
                self.req, instance.uuid, fake_db_share.share_id)

        mock_deny.assert_called_once()
        self.assertIsInstance(
            mock_deny.call_args.args[1], objects.instance.Instance)
        self.assertEqual(mock_deny.call_args.args[1].uuid, instance.uuid)
        self.assertIsInstance(
            mock_deny.call_args.args[2], objects.share_mapping.ShareMapping)
        self.assertEqual(
            mock_deny.call_args.args[2].share_id, fake_db_share['share_id'])
