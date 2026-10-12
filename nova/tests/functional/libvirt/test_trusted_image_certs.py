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

import io
import os
from unittest import mock

from cryptography import exceptions as crypto_exceptions
import fixtures
from glanceclient.common import utils as glance_utils
from oslo_utils.fixture import uuidsentinel as uuids

from nova.image import glance
from nova.policies import base as base_policies
from nova.policies import servers as servers_policies
from nova.tests.functional.libvirt import base
from nova.virt.libvirt import driver as libvirt_driver
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import utils as libvirt_utils


class TestCrossCellColdMigrateTrustedCerts(base.ServersTestBase):
    """Reproduce trusted certificates disappearing from the server API."""

    NUMBER_OF_CELLS = 2
    ADMIN_API = True
    CAST_AS_CALL = False
    microversion = 'latest'

    def test_cold_migrate_loses_trusted_certs(self):
        self.policy.set_rules({
            servers_policies.CROSS_CELL_RESIZE: base_policies.RULE_ADMIN_API,
        }, overwrite=False)
        source = self.start_compute(hostname='source', cell_name='cell1')
        dest = self.start_compute(hostname='dest', cell_name='cell2')

        cert_ids = [uuids.cert1]
        body = self._build_server(networks='none', host=source)
        body['trusted_image_certificates'] = cert_ids
        server = self.api.post_server({'server': body})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual(source, server['OS-EXT-SRV-ATTR:host'])
        self.assertEqual(cert_ids, server['trusted_image_certificates'])

        server = self._migrate_server(server, host=dest)
        self.assertEqual(dest, server['OS-EXT-SRV-ATTR:host'])
        # This is bug https://bugs.launchpad.net/nova/+bug/2169692
        # nova lost the trusted_image_certificates when the server was migrated
        # to a different cell.
        self.assertIsNone(server['trusted_image_certificates'])


class TestShelveTrustedCerts(base.ServersTestBase):
    """Reproduce shelving with trusted certificates to an unsigned image."""

    ADMIN_API = True
    CAST_AS_CALL = False
    microversion = 'latest'

    def test_shelve_with_trusted_certs(self):
        self.flags(shelved_offload_time=-1)
        host = self.start_compute()

        cert_ids = [uuids.cert1]
        image = self.glance.images[self.glance.image1['id']]
        signature = {
            'img_signature': 'ZmFrZSBzaWduYXR1cmU=',
            'img_signature_hash_method': 'SHA-256',
            'img_signature_key_type': 'RSA-PSS',
            'img_signature_certificate_uuid': cert_ids[0],
        }
        image['properties'].update(signature)
        body = self._build_server(
            image_uuid=image['id'], networks='none', host=host)
        body['trusted_image_certificates'] = cert_ids
        server = self.api.post_server({'server': body})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual(cert_ids, server['trusted_image_certificates'])

        with mock.patch.object(
                self.glance, 'create', wraps=self.glance.create) as create:
            self._shelve_server(server, expected_state='SHELVED')

        create.assert_called_once()
        properties = create.call_args.args[1]['properties']
        self.assertEqual(server['id'], properties['instance_uuid'])
        self.assertEqual('snapshot', properties['image_type'])
        # This is bug https://bugs.launchpad.net/nova/+bug/2169692:
        # unshelve would boot from an unsigned snapshot despite the trusted
        # certificates. Glance is mocked, so signature verification cannot
        # fail here; check the metadata Nova sends to create the image.
        for key in signature:
            self.assertNotIn(key, properties)


class TestBootCachedImageTrustedCerts(base.ServersTestBase):
    """Reproduce signature verification being skipped for a cached image."""

    ADMIN_API = True
    CAST_AS_CALL = False
    microversion = 'latest'

    def setUp(self):
        # The base fixtures replace the image backend and skip image creation.
        # Restore the real path so this test exercises the cache decisions.
        create_image = libvirt_driver.LibvirtDriver._create_image
        backend = imagebackend.Backend.backend
        fetch_image = libvirt_utils.fetch_image
        super().setUp()
        self.stub_out('nova.virt.libvirt.driver.LibvirtDriver._create_image',
                      create_image)
        self.stub_out(
            'nova.virt.libvirt.imagebackend.Backend.backend', backend)
        self.stub_out('nova.virt.libvirt.utils.fetch_image', fetch_image)
        self.flags(images_type='qcow2', group='libvirt')

        # Keep real files and cache handling, but avoid qemu disk operations.
        def fake_create_image(path, *args, **kwargs):
            with open(path, 'wb'):
                pass

        self.stub_out(
            'nova.virt.libvirt.utils.create_image', fake_create_image)
        # The test owns the cache files, so updating them needs no privsep.
        self.stub_out('nova.privsep.path.utime', os.utime)
        self.useFixture(fixtures.MockPatch('nova.virt.disk.api.extend'))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.images.qemu_img_info',
            return_value=mock.Mock(file_format='raw', backing_file=None,
                                   format_specific={}, virtual_size=1)))

        # Use Nova's real Glance download and verification code. Only the
        # external Glance client and cryptographic operations are mocked.
        self.image_data = b'An image with an invalid signature'

        def fake_glance_data(*args, **kwargs):
            image_chunks = glance_utils.IterableWithLength(
                io.BytesIO(self.image_data), len(self.image_data))
            return glance_utils.RequestIdProxy(
                (image_chunks, mock.Mock(headers={})))

        client = mock.Mock()
        client.call.side_effect = fake_glance_data
        image_service = glance.GlanceImageServiceV2(client=client)
        image_service.show = self.glance.show
        self.useFixture(fixtures.MockPatchObject(
            self.glance, 'download', side_effect=image_service.download))
        self.get_verifier = self.useFixture(fixtures.MockPatch(
            'nova.image.glance.signature_utils.get_verifier')).mock
        self.verifier = self.get_verifier.return_value
        self.verifier.verify.side_effect = crypto_exceptions.InvalidSignature(
            'Invalid image signature')
        self.verify_certificate = self.useFixture(fixtures.MockPatch(
            'nova.image.glance.certificate_utils.verify_certificate')).mock

    def test_boot_cached_image_skips_signature_verification(self):
        host = self.start_compute()
        cert_ids = [uuids.cert1]
        image = self.glance.images[self.glance.image1['id']]
        image['properties'].update({
            'img_signature': 'ZmFrZSBzaWduYXR1cmU=',
            'img_signature_hash_method': 'SHA-256',
            'img_signature_key_type': 'RSA-PSS',
            'img_signature_certificate_uuid': cert_ids[0],
        })
        cache_path = os.path.join(
            self.computes[host].driver.image_cache_manager.cache_dir,
            imagecache.get_cache_fname(image['id']))
        self.assertFalse(os.path.exists(cache_path))

        body = self._build_server(
            image_uuid=image['id'], networks='none', host=host)
        body['trusted_image_certificates'] = cert_ids

        # With an empty cache, the invalid signature prevents booting.
        server = self.api.post_server({'server': body})
        self._wait_for_state_change(server, 'ERROR')
        self.verifier.update.assert_called_once_with(self.image_data)
        self.verifier.verify.assert_called_once_with()
        self.verify_certificate.assert_called_once_with(
            context=mock.ANY, certificate_uuid=cert_ids[0],
            trusted_certificate_uuids=cert_ids)
        self.assertFalse(os.path.exists(cache_path))
        self.get_verifier.reset_mock()
        self.verify_certificate.reset_mock()

        # Populate the same compute's cache without requesting validation.
        self._create_server(image_uuid=image['id'], networks='none', host=host)
        with open(cache_path, 'rb') as cached_image:
            self.assertEqual(self.image_data, cached_image.read())
        self.get_verifier.assert_not_called()
        self.verify_certificate.assert_not_called()

        # This is bug https://bugs.launchpad.net/nova/+bug/2169692: the same
        # request now boots despite the invalid signature. A cache hit skips
        # both signature verification and the requested certificate validation.
        server = self.api.post_server({'server': body})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual(host, server['OS-EXT-SRV-ATTR:host'])
        self.assertEqual(cert_ids, server['trusted_image_certificates'])
        self.get_verifier.assert_not_called()
        self.verifier.verify.assert_not_called()
        self.verify_certificate.assert_not_called()
