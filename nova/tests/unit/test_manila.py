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

from requests import Response

import fixtures
from keystoneauth1 import loading as ks_loading

import nova.conf
from nova import context as nova_context
from nova import exception
from nova.share import manila
from nova import test

from openstack import exceptions as sdk_exc
from openstack.shared_file_system.v2 import (
    resource_locks as sdk_resource_locks
)

from openstack.shared_file_system.v2 import (
    share_access_rule as sdk_share_access_rule
)
from openstack.shared_file_system.v2 import (
    share_export_locations as sdk_share_export_locations
)
from openstack.shared_file_system.v2 import share as sdk_share

from openstack import utils
from unittest import mock

from nova.tests.unit.api.openstack import fakes

CONF = nova.conf.CONF


def stub_share(share_id):
    share = sdk_share.Share()
    share.id = share_id
    share.size = 1
    share.availability_zone = "nova"
    share.created_at = "2015-09-18T10:25:24.000000"
    share.status = "available"
    share.name = "share_London"
    share.description = "My custom share London"
    share.project_id = "16e1ab15c35a457e9c2b2aa189f544e1"
    share.snapshot_id = None
    share.share_network_id = "713df749-aac0-4a54-af52-10f6c991e80c"
    share.share_protocol = "NFS"
    share.metadata = {
            "project": "my_app",
            "aim": "doc"
        }
    share.share_type = "25747776-08e5-494f-ab40-a64b9d20d8f7"
    share.is_public = True
    share.share_server_id = "e268f4aa-d571-43dd-9ab3-f49ad06ffaef"
    share.host = "manila2@generic1#GENERIC1"

    share.location = utils.Munch(
        {
            "cloud": "envvars",
            "region_name": "RegionOne",
            "zone": "manila-zone-0",
            "project": utils.Munch(
                {
                    "id": "bce4fcc3bd0d4c598f610cb45ec5c5ba",
                    "name": "demo",
                    "domain_id": "default",
                    "domain_name": None,
                }
            ),
        }
    )
    return share


def stub_export_locations():
    export_locations = []
    export_location = sdk_share_export_locations.ShareExportLocation()
    export_location.id = "b6bd76ce-12a2-42a9-a30a-8a43b503867d"
    export_location.path = (
        "10.0.0.3:/shares/share-e1c2d35e-fe67-4028-ad7a-45f668732b1d"
    )
    export_location.is_preferred = True
    export_location.share_instance_id = (
        "e1c2d35e-fe67-4028-ad7a-45f668732b1d"
    )
    export_location.is_admin = True
    export_location.share_instance_id = "e1c2d35e-fe67-4028-ad7a-45f668732b1d"
    export_location.location = utils.Munch(
        {
            "cloud": "envvars",
            "region_name": "RegionOne",
            "zone": None,
            "project": utils.Munch(
                {
                    "id": "bce4fcc3bd0d4c598f610cb45ec5c5ba",
                    "name": "demo",
                    "domain_id": "default",
                    "domain_name": None,
                }
            ),
        }
    )

    export_locations.append(export_location)
    for item in export_locations:
        yield item


def stub_access_list():
    access_list = []
    access_list.append(stub_access())
    for access in access_list:
        yield access


def stub_access():
    access = sdk_share_access_rule.ShareAccessRule()
    access.id = "a25b2df3-90bd-4add-afa6-5f0dbbd50452"
    access.access_level = "rw"
    access.access_to = "0.0.0.0/0"
    access.access_type = "ip"
    access.state = "active"
    access.access_key = None
    access.created_at = "2023-07-21T15:20:01.812350"
    access.updated_at = "2023-07-21T15:20:01.812350"
    access.metadata = {}
    access.location = utils.Munch(
        {
            "cloud": "envvars",
            "region_name": "RegionOne",
            "zone": None,
            "project": utils.Munch(
                {
                    "id": "bce4fcc3bd0d4c598f610cb45ec5c5ba",
                    "name": "demo",
                    "domain_id": "default",
                    "domain_name": None,
                }
            ),
        }
    )
    return access


def stub_lock(share_id):
    lock = sdk_resource_locks.ResourceLock()
    lock.id = "a37b7da7-5d72-49d3-bf3b-aebd64828089"
    lock.project_id = "ded249b25f6f46918fef4e69f427590c"
    lock.resource_type = "share"
    lock.resource_id = share_id
    lock.resource_action = "delete"
    lock.lock_reason = "nova lock"
    lock.created_at = "2023-07-31T09:39:38.441320"
    lock.updated_at = None
    lock.location = utils.Munch(
        {
            "cloud": "envvars",
            "region_name": "RegionOne",
            "zone": None,
            "project": utils.Munch(
                {
                    "id": "bce4fcc3bd0d4c598f610cb45ec5c5ba",
                    "name": "demo",
                    "domain_id": "default",
                    "domain_name": None,
                }
            ),
        }
    )
    return lock


def stub_resource_locks(share_id):
    resource_locks = []
    resource_lock = stub_lock(share_id)
    resource_locks.append(resource_lock)
    for lock in resource_locks:
        yield lock


class BaseManilaTestCase(object):
    project_id = fakes.FAKE_PROJECT_ID

    def setUp(self):

        super(BaseManilaTestCase, self).setUp()

        self.mock_get_confgrp = self.useFixture(fixtures.MockPatch(
            'nova.utils._get_conf_group')).mock

        self.mock_ks_loading = self.useFixture(
            fixtures.MockPatchObject(ks_loading, 'load_auth_from_conf_options')
        ).mock

        self.service_type = 'shared-file-system'
        self.mock_connection = self.useFixture(
            fixtures.MockPatch(
                "nova.utils.connection.Connection", side_effect=self.fake_conn
            )
        ).mock

        # We need to stub the CONF global in nova.utils to assert that the
        # Connection constructor picks it up.
        self.mock_conf = self.useFixture(fixtures.MockPatch(
            'nova.utils.CONF')).mock

        self.api = manila.API()

        self.context = nova_context.RequestContext(
            user_id="fake_user", project_id=self.project_id
        )

    def fake_conn(self, *args, **kwargs):
        class FakeConnection(object):
            def __init__(self):
                self.shared_file_system = FakeConnectionShareV2Proxy()

        class FakeConnectionShareV2Proxy(object):
            def __init__(self):
                pass

            def get_share(self, share_id):
                if share_id == 'nonexisting':
                    raise sdk_exc.ResourceNotFound
                return stub_share(share_id)

            def export_locations(self, share_id):
                return stub_export_locations()

            def access_rules(self, share_id):
                if share_id == 'nonexisting':
                    raise sdk_exc.ResourceNotFound
                if share_id == 'nonexisting2':
                    raise sdk_exc.ResourceNotFound
                if share_id == '4567':
                    return []
                return stub_access_list()

            def create_access_rule(self, share_id, **kwargs):
                if share_id == '2345':
                    raise sdk_exc.BadRequestException
                if share_id == 'nonexisting':
                    raise sdk_exc.ResourceNotFound
                return stub_access()

            def delete_access_rule(self, access_id, share_id, unrestrict):
                if share_id == 'nonexisting':
                    raise sdk_exc.ResourceNotFound
                res = Response()
                res.status_code = 202
                res.reason = "Internal error"
                if share_id == '2345':
                    res.status_code = 500
                return res

            def get_all_resource_locks(self, resource_id=None):
                if resource_id == '1234':
                    return []
                if resource_id == '2345':
                    return []
                if resource_id == 'nonexisting':
                    return []
                return stub_resource_locks(resource_id)

            def create_resource_lock(
                self, resource_id=None, resource_type=None, lock_reason=None
            ):
                if resource_id == "nonexisting":
                    raise sdk_exc.BadRequestException
                return stub_lock(resource_id)

            def delete_resource_lock(self, share_id):
                pass

        return FakeConnection()

    @mock.patch('nova.utils.get_sdk_adapter')
    def test_client(self, mock_get_sdk_adapter):
        client = manila._manilaclient(self.context)
        self.assertTrue(hasattr(client, 'get_share'))
        self.assertTrue(hasattr(client, 'export_locations'))
        self.assertTrue(hasattr(client, 'access_rules'))
        self.assertTrue(hasattr(client, 'create_access_rule'))
        self.assertTrue(hasattr(client, 'delete_access_rule'))
        mock_get_sdk_adapter.assert_called_once_with(
            "shared-file-system",
            admin=False,
            check_service=True,
            context=self.context,
            shared_file_system_api_version="2.82",
            global_request_id=self.context.global_id,
        )

    @mock.patch('nova.utils.get_sdk_adapter')
    def test_client_admin(self, mock_get_sdk_adapter):
        client = manila._manilaclient(self.context, admin=True)
        self.assertTrue(hasattr(client, 'get_share'))
        self.assertTrue(hasattr(client, 'export_locations'))
        self.assertTrue(hasattr(client, 'access_rules'))
        self.assertTrue(hasattr(client, 'create_access_rule'))
        self.assertTrue(hasattr(client, 'delete_access_rule'))
        mock_get_sdk_adapter.assert_called_once_with(
            "shared-file-system",
            admin=True,
            check_service=True,
            context=self.context,
            shared_file_system_api_version="2.82",
            global_request_id=self.context.global_id,
        )


class ManilaTestCase(BaseManilaTestCase, test.NoDBTestCase):
    def test_get_fails_non_existing_share(self):
        """Tests that we fail if trying to get an
        non existing share.
        """
        exc = self.assertRaises(
            exception.ShareNotFound, self.api.get, self.context, "nonexisting"
        )

        self.assertIn("Share nonexisting could not be found.", exc.message)

    @mock.patch(
        'nova.utils.get_sdk_adapter', side_effect=nova.utils.get_sdk_adapter)
    def test_get_share(self, mock_get_sdk_adapter):
        """Tests that we manage to get a share.
        """
        share = self.api.get(self.context, '1234')
        mock_get_sdk_adapter.assert_called_once_with(
            "shared-file-system",
            admin=False,
            check_service=True,
            context=self.context,
            shared_file_system_api_version="2.82",
            global_request_id=self.context.global_id,
        )
        self.assertIsInstance(share, manila.Share)
        self.assertEqual('1234', share.id)
        self.assertEqual(1, share.size)
        self.assertEqual('nova', share.availability_zone)
        self.assertEqual('2015-09-18T10:25:24.000000',
                         share.created_at)
        self.assertEqual('available', share.status)
        self.assertEqual('share_London', share.name)
        self.assertEqual('My custom share London',
                         share.description)
        self.assertEqual('16e1ab15c35a457e9c2b2aa189f544e1',
                         share.project_id)
        self.assertIsNone(share.snapshot_id)
        self.assertEqual(
            '713df749-aac0-4a54-af52-10f6c991e80c',
            share.share_network_id)
        self.assertEqual('NFS', share.share_proto)
        self.assertEqual(share.export_location,
                "10.0.0.3:/shares/"
                "share-e1c2d35e-fe67-4028-ad7a-45f668732b1d"
                )
        self.assertEqual({"project": "my_app", "aim": "doc"},
                         share.metadata)
        self.assertEqual(
            '25747776-08e5-494f-ab40-a64b9d20d8f7',
            share.share_type)
        self.assertTrue(share.is_public)

    def test_get_access_fails_non_existing_share(self):
        """Tests that we fail if trying to get an access on a
        non existing share.
        """
        exc = self.assertRaises(
            exception.ShareNotFound,
            self.api.get_access,
            self.context,
            "nonexisting",
            "ip",
            "0.0.0.0/0",
        )

        self.assertIn("Share nonexisting could not be found.", exc.message)

        exc = self.assertRaises(
            exception.ShareNotFound,
            self.api.get_access,
            self.context,
            "nonexisting2",
            "ip",
            "0.0.0.0/0",
        )

        self.assertIn("Share nonexisting2 could not be found.", exc.message)

    @mock.patch(
        'nova.utils.get_sdk_adapter', side_effect=nova.utils.get_sdk_adapter)
    def test_get_access(self, mock_get_sdk_adapter):
        """Tests that we manage to get an access id based on access_type and
        access_to parameters.
        """
        access = self.api.get_access(self.context, '1234', 'ip', '0.0.0.0/0')
        mock_get_sdk_adapter.assert_called_once_with(
            "shared-file-system",
            admin=True,
            check_service=True,
            context=self.context,
            shared_file_system_api_version="2.82",
            global_request_id=self.context.global_id,
        )
        self.assertEqual('a25b2df3-90bd-4add-afa6-5f0dbbd50452', access.id)
        self.assertEqual('rw', access.access_level)
        self.assertEqual('active', access.state)
        self.assertEqual('ip', access.access_type)
        self.assertEqual('0.0.0.0/0', access.access_to)
        self.assertIsNone(access.access_key)

    def test_get_access_not_existing(self):
        """Tests that we get None if the access id does not exist.
        """
        access = self.api.get_access(
            self.context, "1234", "ip", "192.168.0.1/32"
        )

        self.assertIsNone(access)

    def test_allow_access_fails_non_existing_share(self):
        """Tests that we fail if trying to allow an
        non existing share.
        """
        exc = self.assertRaises(
            exception.ShareNotFound,
            self.api.allow,
            self.context,
            "nonexisting",
            "ip",
            "0.0.0.0/0",
            "rw",
        )

        self.assertIn("Share nonexisting could not be found.", exc.message)

    @mock.patch(
        'nova.utils.get_sdk_adapter', side_effect=nova.utils.get_sdk_adapter)
    def test_allow_access(self, mock_get_sdk_adapter):
        """Tests that we manage to allow access to a share.
        """
        access = self.api.allow(self.context, '1234', 'ip', '0.0.0.0/0', 'rw')
        mock_get_sdk_adapter.assert_called_once_with(
            "shared-file-system",
            admin=True,
            check_service=True,
            context=self.context,
            shared_file_system_api_version="2.82",
            global_request_id=self.context.global_id,
        )
        self.assertEqual('a25b2df3-90bd-4add-afa6-5f0dbbd50452', access.id)
        self.assertEqual('rw', access.access_level)
        self.assertEqual('active', access.state)
        self.assertEqual('ip', access.access_type)
        self.assertEqual('0.0.0.0/0', access.access_to)
        self.assertIsNone(access.access_key)

    def test_allow_access_fails_already_exists(self):
        """Tests that we have an exception is the share already exists.
        """
        exc = self.assertRaises(
            exception.ShareAccessGrantError,
            self.api.allow,
            self.context,
            '2345',
            'ip',
            '0.0.0.0/0',
            'rw'
        )

        self.assertIn(
            'Share access could not be granted to share',
            exc.message)

    def test_deny_access_fails_non_existing_share(self):
        """Tests that we fail if trying to deny an
        non existing share.
        """
        exc = self.assertRaises(
            exception.ShareNotFound,
            self.api.deny,
            self.context,
            "nonexisting",
            "ip",
            "0.0.0.0/0",
        )

        self.assertIn("Share nonexisting could not be found.", exc.message)

    @mock.patch(
        'nova.utils.get_sdk_adapter', side_effect=nova.utils.get_sdk_adapter)
    def test_deny_access(self, mock_get_sdk_adapter):
        """Tests that we manage to deny access to a share.
        """
        self.api.deny(
            self.context,
            '1234',
            'ip',
            '0.0.0.0/0'
        )
        self.assertEqual(2, mock_get_sdk_adapter.call_count)

        self.assertEqual(
            mock_get_sdk_adapter.call_args_list[0].args,
            (
                "shared-file-system",
            ),
        )
        self.assertEqual(
            mock_get_sdk_adapter.call_args_list[0].kwargs,
            {
                "admin": True,
                "check_service": True,
                "context": self.context,
                "shared_file_system_api_version": "2.82",
                "global_request_id": self.context.global_id,
            },
        )

        self.assertEqual(
            mock_get_sdk_adapter.call_args_list[1].args,
            (
                "shared-file-system",
            ),
        )
        self.assertEqual(
            mock_get_sdk_adapter.call_args_list[1].kwargs,
            {
                "admin": True,
                "check_service": True,
                "context": self.context,
                "shared_file_system_api_version": "2.82",
                "global_request_id": self.context.global_id,
            },
        )

    def test_deny_access_fails_id_missing(self):
        """Tests that we fail if something wrong happens calling deny method.
        """
        exc = self.assertRaises(exception.ShareAccessRemovalError,
                self.api.deny,
                self.context,
                '2345',
                'ip',
                '0.0.0.0/0'
                )

        self.assertIn(
            'Share access could not be removed from',
            exc.message)
        self.assertEqual(
            500,
            exc.code)

    def test_deny_access_fails_access_not_found(self):
        """Tests that we fail if access is missing.
        """
        exc = self.assertRaises(exception.ShareAccessNotFound,
                self.api.deny,
                self.context,
                '4567',
                'ip',
                '0.0.0.0/0'
                )

        self.assertIn(
            'Share access from Manila could not be found',
            exc.message)
        self.assertEqual(
            404,
            exc.code)
