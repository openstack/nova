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

from nova.compute import api as compute
from nova import exception
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional.api_sample_tests import test_servers
from oslo_utils.fixture import uuidsentinel
from unittest import mock


class ServerSharesBase(test_servers.ServersSampleBase):
    sample_dir = 'os-server-shares'
    microversion = '2.97'
    scenarios = [('v2_97', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ServerSharesBase, self).setUp()
        self.manila_fixture = self.useFixture(nova_fixtures.ManilaFixture())
        self.compute_api = compute.API()

    def _get_create_subs(self):
        return {'share_id': 'e8debdc0-447a-4376-a10a-4cd9122d7986',
                'uuid': '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                '-[0-9a-f]{4}-[0-9a-f]{12}',
                }

    def create_server_ok(self, requested_flavor=None):
        flavor = self._create_flavor(extra_spec=requested_flavor)
        server = self._create_server(networks='auto', flavor_id=flavor)
        self._stop_server(server)
        return server['id']

    def create_server_not_stopped(self):
        server = self._create_server(networks='auto')
        return server['id']

    def _post_server_shares(self):
        """Verify the response status and returns the UUID of the
        newly created server with shares.
        """
        uuid = self.create_server_ok()
        subs = self._get_create_subs()
        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-req", subs
        )

        self._verify_response(
            'server-shares-create-resp', subs, response, 201)

        return uuid


class ServerSharesJsonTest(ServerSharesBase):
    def test_server_shares_create(self):
        """Verify we can create a share mapping.
        """
        self._post_server_shares()

    def test_server_shares_create_fails_if_already_created(self):
        """Verify we cannot create a share mapping already created.
        """
        uuid = self._post_server_shares()
        # Following mock simulate a race condition between 2 requests that
        # would hit the share_mapping.create() almost at the same time.
        with mock.patch(
            "nova.db.main.api.share_mapping_get_by_instance_uuid_and_share_id"
        ) as mock_db:
            mock_db.return_value = None
            subs = self._get_create_subs()
            response = self._do_post(
                "servers/%s/shares" % uuid, "server-shares-create-req", subs
            )
            self.assertEqual(409, response.status_code)
            self.assertIn('already associated to this server', response.text)

    def test_server_shares_create_with_tag_fails_if_already_created(self):
        """Verify we cannot create a share mapping with a new tag if it is
        already created.
        """
        uuid = self._post_server_shares()
        subs = self._get_create_subs()
        subs['tag'] = "my-tag"
        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-tag-req", subs
        )
        self.assertEqual(409, response.status_code)
        self.assertIn(
            "Share 'e8debdc0-447a-4376-a10a-4cd9122d7986' or "
            "tag 'my-tag' already associated to this server.",
            response.text,
        )

    def test_server_shares_create_fails_instance_not_stopped(self):
        """Verify we cannot create a share if instance is not stopped.
        """
        uuid = self.create_server_not_stopped()
        subs = self._get_create_subs()
        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-req", subs
        )
        self.assertEqual(409, response.status_code)
        self.assertIn('while it is in vm_state active', response.text)

    def test_server_shares_create_fails_incorrect_configuration(self):
        """Verify we cannot create a share we don't have the
        appropriate configuration.
        """
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_mem_backing_file=False):
            self.compute.stop()
            self.compute.start()
            uuid = self.create_server_ok()
            subs = self._get_create_subs()
            response = self._do_post('servers/%s/shares' % uuid,
                                    'server-shares-create-req', subs)
            self.assertEqual(409, response.status_code)
            self.assertIn(
                'Feature not supported because either compute or '
                'instance are not configured correctly.', response.text
            )

    def test_server_shares_create_fails_cannot_allow_policy(self):
        """Verify we raise an exception if we get a timeout to apply policy"""
        uuid = self.create_server_ok()
        subs = self._get_create_subs()
        # simulate that manila does not set the requested access in time and
        # nova times out waiting for it.
        self.manila_fixture.mock_get_access.return_value = None
        self.manila_fixture.mock_get_access.side_effect = None
        self.flags(share_apply_policy_timeout=2, group='manila')

        # Here we are using CastAsCallFixture so we got an exception from
        # nova api. This should not happen without the fixture.
        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-req", subs
        )
        self.assertEqual(500, response.status_code)
        self.assertIn(
            "nova.exception.ShareAccessGrantError",
            response.text,
        )

    def test_server_shares_create_with_alternative_flavor(self):
        """Verify we can create a share with the proper flavor.
        """
        with mock.patch.dict(self.compute.driver.capabilities,
                             supports_mem_backing_file=False):
            self.compute.stop()
            self.compute.start()
            uuid = self.create_server_ok(
                requested_flavor={"hw:mem_page_size": "large"}
            )
            subs = self._get_create_subs()
            response = self._do_post(
                "servers/%s/shares" % uuid, "server-shares-create-req", subs
            )
            self.assertEqual(201, response.status_code)

    def test_server_shares_create_fails_share_not_found(self):
        """Verify we can not create a share if the share does not
        exists.
        """
        self.manila_fixture.mock_get.side_effect = exception.ShareNotFound(
            share_id='fake_uuid')
        uuid = self.create_server_ok()
        subs = self._get_create_subs()
        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-req", subs
        )
        self.assertEqual(404, response.status_code)
        self.assertIn("Share fake_uuid could not be found", response.text)

    def test_server_shares_create_unknown_instance(self):
        """Verify creating a share on an unknown instance reports an error.
        """
        self.create_server_ok()
        subs = self._get_create_subs()
        response = self._do_post(
            "servers/%s/shares" % uuidsentinel.fake_uuid,
            "server-shares-create-req",
            subs,
        )
        self.assertEqual(404, response.status_code)
        self.assertIn("could not be found", response.text)

    def test_server_shares_create_fails_share_in_error(self):
        """Verify creating a share which is in error reports an error.
        """
        uuid = self.create_server_ok()
        subs = self._get_create_subs()
        self.manila_fixture.mock_get.side_effect = (
            self.manila_fixture.fake_get_share_status_error
        )

        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-req", subs
        )
        self.assertEqual(409, response.status_code)
        self.assertIn(
            "Share e8debdc0-447a-4376-a10a-4cd9122d7986 is in 'error' "
            "instead of 'available' status.",
            response.text,
        )

    def test_server_shares_create_fails_export_location_missing(self):
        """Verify creating a share without export location reports an error.
        """
        uuid = self.create_server_ok()
        subs = self._get_create_subs()
        self.manila_fixture.mock_get.side_effect = (
            self.manila_fixture.fake_get_share_export_location_missing
        )

        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-req", subs
        )
        self.assertEqual(409, response.status_code)
        self.assertIn(
            "Share e8debdc0-447a-4376-a10a-4cd9122d7986 export location is "
            "missing.",
            response.text,
        )

    def test_server_shares_create_fails_unknown_protocol(self):
        """Verify creating a share with an unknown protocol reports an error.
        """
        uuid = self.create_server_ok()
        subs = self._get_create_subs()
        self.manila_fixture.mock_get.side_effect = (
            self.manila_fixture.fake_get_share_unknown_protocol
        )

        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-req", subs
        )
        self.assertEqual(409, response.status_code)
        self.assertIn("Share protocol CIFS is not supported.", response.text)

    def test_server_shares_index(self):
        """Verify we can list shares.
        """
        uuid = self._post_server_shares()
        subs = self._get_create_subs()
        response = self._do_get("servers/%s/shares" % uuid)
        self._verify_response("server-shares-list-resp", subs, response, 200)

    def test_server_shares_index_unknown_instance(self):
        """Verify getting shares on an unknown instance reports an error.
        """
        response = self._do_get('servers/%s/shares' % uuidsentinel.fake_uuid)
        self.assertEqual(404, response.status_code)
        self.assertIn(
            "could not be found",
            response.text
        )

    def test_server_shares_show(self):
        """Verify we can show a share.
        """
        uuid = self._post_server_shares()
        subs = self._get_create_subs()
        response = self._do_get(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self._verify_response("server-shares-show-resp", subs, response, 200)

    def test_server_shares_show_fails_share_not_found(self):
        """Verify we can not show a share if the share does not
        exists.
        """
        uuid = self.create_server_ok()
        subs = self._get_create_subs()
        response = self._do_get(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self.assertEqual(404, response.status_code)
        self.assertIn(
            "Share e8debdc0-447a-4376-a10a-4cd9122d7986 could not be found",
            response.text
        )

    def test_server_shares_show_unknown_instance(self):
        """Verify showing a share on an unknown instance reports an error.
        """
        self._post_server_shares()
        subs = self._get_create_subs()
        response = self._do_get(
            "servers/%s/shares/%s" % (uuidsentinel.fake_uuid, subs["share_id"])
        )
        self.assertEqual(404, response.status_code)
        self.assertIn(
            "could not be found",
            response.text
        )

    def test_server_shares_delete(self):
        """Verify we can delete share.
        """
        uuid = self._post_server_shares()
        subs = self._get_create_subs()
        response = self._do_delete(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self.assertEqual(200, response.status_code)

        # Check share is not anymore available
        response = self._do_get(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self.assertEqual(404, response.status_code)

    def test_server_shares_delete_instance(self):
        """Verify we can delete an instance and its associated share is
        deleted as well.
        """
        uuid = self._post_server_shares()
        subs = self._get_create_subs()

        # Check share is created
        response = self._do_get(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self._verify_response("server-shares-show-resp", subs, response, 200)

        # Delete the instance
        response = self._do_delete(
            "servers/%s" % (uuid)
        )
        self.assertEqual(204, response.status_code)

        # Check share is not anymore available
        response = self._do_get(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self.assertEqual(404, response.status_code)

    def test_server_shares_delete_fails_share_not_found(self):
        """Verify we have an error if we want to remove an unknown share.
        """
        uuid = self._post_server_shares()
        response = self._do_delete(
            "servers/%s/shares/%s" % (uuid, uuidsentinel.wrong_share_id)
        )
        self.assertEqual(404, response.status_code)

    def test_server_shares_delete_fails_instance_not_stopped(self):
        """Verify we cannot remove a share if the instance is not stopped.
        """
        uuid = self._post_server()
        subs = self._get_create_subs()
        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-delete-req", subs
        )
        response = self._do_delete(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self.assertEqual(409, response.status_code)

    def test_server_shares_delete_unknown_instance(self):
        """Verify deleting a share on an unknown instance reports an error.
        """
        uuid = self._post_server_shares()
        subs = self._get_create_subs()
        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-delete-req", subs
        )
        response = self._do_delete(
            "servers/%s/shares/%s" % (uuidsentinel.fake_uuid, subs["share_id"])
        )
        self.assertEqual(404, response.status_code)
        self.assertIn(
            "could not be found",
            response.text
        )

    def test_server_shares_delete_fails_cannot_deny_policy(self):
        """Verify we raise an exception if we cannot deny the policy.
        """
        uuid = self._post_server_shares()
        subs = self._get_create_subs()
        self.manila_fixture.mock_deny.return_value = None
        self.manila_fixture.mock_deny.side_effect = (
            exception.ShareAccessRemovalError(
                share_id=subs["share_id"],
                reason="Resource could not be found.",
            )
        )

        # Here we are using CastAsCallFixture so we got an exception from
        # nova api. This should not happen without the fixture.
        response = self._do_delete(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self.assertEqual(500, response.status_code)
        self.assertIn('nova.exception.ShareAccessRemovalError', response.text)


class ServerSharesJsonAdminTest(ServerSharesBase):
    ADMIN_API = True

    def _post_server_shares(self):
        """Verify the response status and returns the UUID of the
        newly created server with shares.
        """
        uuid = self.create_server_ok()
        subs = self._get_create_subs()
        response = self._do_post(
            "servers/%s/shares" % uuid, "server-shares-create-req", subs
        )
        self._verify_response(
            'server-shares-admin-create-resp', subs, response, 201)

        return uuid

    def test_server_shares_create(self):
        """Verify we can create a share mapping.
        """
        self._post_server_shares()

    def test_server_shares_show(self):
        """Verify we can show a share as admin and thus have more
           information.
        """
        uuid = self._post_server_shares()
        subs = self._get_create_subs()
        response = self._do_get(
            "servers/%s/shares/%s" % (uuid, subs["share_id"])
        )
        self._verify_response(
            "server-shares-admin-show-resp", subs, response, 200
        )

    def _block_action(self, body):
        uuid = self._post_server_shares()

        ex = self.assertRaises(
            client.OpenStackApiException,
            self.api.post_server_action,
            uuid,
            body
        )

        self.assertEqual(409, ex.response.status_code)
        self.assertIn(
            "Feature not supported with instances that have shares.",
            ex.response.text
        )

    def test_shelve_server_with_share_fails(self):
        self._block_action({"shelve": None})

    def test_suspend_server_with_share_fails(self):
        self._block_action({"suspend": None})

    def test_evacuate_server_with_share_fails(self):
        self._block_action({"evacuate": {}})

    def test_resize_server_with_share_fails(self):
        self._block_action({"resize": {"flavorRef": "2"}})

    def test_migrate_server_with_share_fails(self):
        self._block_action({"migrate": None})

    def test_live_migrate_server_with_share_fails(self):
        self._block_action(
            {"os-migrateLive": {
                "host": None,
                "block_migration": "auto"
                }
             }
        )
