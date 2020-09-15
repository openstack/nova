# Copyright 2020, Red Hat, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import datetime

from oslo_utils.fixture import uuidsentinel as uuids

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class TestNonBootableImageMeta(integrated_helpers._IntegratedTestBase):
    """Regression test for bug 1895696

    This regression test asserts the behaviour of server creation requests when
    using an image with nonbootable properties either directly in the request
    or to create a volume that is then booted from.
    """

    microversion = 'latest'

    def setUp(self):
        super().setUp()

        # Add an image to the Glance fixture with cinder_encryption_key set
        timestamp = datetime.datetime(2011, 1, 1, 1, 2, 3)
        cinder_encrypted_image = {
            'id': uuids.cinder_encrypted_image_uuid,
            'name': 'cinder_encryption_key_image',
            'created_at': timestamp,
            'updated_at': timestamp,
            'deleted_at': None,
            'deleted': False,
            'status': 'active',
            'is_public': False,
            'container_format': 'ova',
            'disk_format': 'vhd',
            'size': '74185822',
            'min_ram': 0,
            'min_disk': 0,
            'protected': False,
            'visibility': 'public',
            'tags': [],
            'properties': {
                'cinder_encryption_key_id': uuids.cinder_encryption_key_id,
            }
        }
        self.glance.create(None, cinder_encrypted_image)

        # Mock out nova.volume.cinder.API.{create,get} so that when n-api
        # requests that c-api create a volume from the above image that the
        # response includes cinder_encryption_key_id in the
        # volume_image_metadata
        cinder_encrypted_volume = {
            'status': 'available',
            'display_name': 'cinder_encrypted_volume',
            'attach_status': 'detached',
            'id': uuids.cinder_encrypted_volume_uuid,
            'multiattach': False,
            'size': 1,
            'encrypted': True,
            'volume_image_metadata': {
                'cinder_encryption_key_id': uuids.cinder_encryption_key_id
            }
        }

        def fake_cinder_create(self_api, context, size, name, description,
                snapshot=None, image_id=None, volume_type=None, metadata=None,
                availability_zone=None):
            if image_id == uuids.cinder_encrypted_image_uuid:
                return cinder_encrypted_volume
        self.stub_out(
            'nova.volume.cinder.API.create', fake_cinder_create)

        def fake_cinder_get(self_api, context, volume_id, microversion=None):
            return cinder_encrypted_volume
        self.stub_out(
            'nova.volume.cinder.API.get', fake_cinder_get)

    def test_nonbootable_metadata_image_metadata(self):
        """Assert behaviour when booting from an encrypted image
        """
        server = self._build_server(
            name='test_nonbootable_metadata_bfv_image_metadata',
            image_uuid=uuids.cinder_encrypted_image_uuid,
            networks='none'
        )
        # NOTE(lyarwood): This should always fail as Nova will attempt to boot
        # directly from this encrypted image.
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.post_server,
            {'server': server})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn(
            "Direct booting of an image uploaded from an encrypted volume is "
            "unsupported", str(ex))

    def test_nonbootable_metadata_bfv_image_metadata(self):
        """Assert behaviour when n-api creates volume using an encrypted image
        """
        server = self._build_server(
            name='test_nonbootable_metadata_bfv_image_metadata',
            image_uuid='', networks='none'
        )
        # TODO(lyarwood): Merge this into _build_server
        server['block_device_mapping_v2'] = [{
            'source_type': 'image',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': uuids.cinder_encrypted_image_uuid,
            'volume_size': 1,
        }]

        # Assert that this request is accepted and the server moves to ACTIVE
        server = self.api.post_server({'server': server})
        self._wait_for_state_change(server, 'ACTIVE')

    def test_nonbootable_metadata_bfv_volume_image_metadata(self):
        """Assert behaviour when c-api has created volume using encrypted image
        """
        server = self._build_server(
            name='test_nonbootable_metadata_bfv_volume_image_metadata',
            image_uuid='', networks='none'
        )
        # TODO(lyarwood): Merge this into _build_server
        server['block_device_mapping_v2'] = [{
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0,
            'uuid': uuids.cinder_encrypted_volume_uuid,
        }]

        # Assert that this request is accepted and the server moves to ACTIVE
        server = self.api.post_server({'server': server})
        self._wait_for_state_change(server, 'ACTIVE')
