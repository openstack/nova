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

import fixtures
from lxml import etree
import os
from requests import request

from nova import context as nova_context
from nova import exception
from nova.objects import instance
from nova.objects import share_mapping
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ServerSharesTestBase(base.ServersTestBase):
    api_major_version = 'v2.1'
    microversion = 'latest'
    ADMIN_API = True
    FAKE_LIBVIRT_VERSION = 8000000
    FAKE_QEMU_VERSION = 6002000

    def setUp(self):
        super(ServerSharesTestBase, self).setUp()

        self.context = nova_context.get_admin_context()
        self.manila_fixture = self.useFixture(nova_fixtures.ManilaFixture())
        self.flags(ram_allocation_ratio=1.0)
        self.flags(file_backed_memory=8192, group='libvirt')
        self.compute = self.start_compute(
            'host1',
            libvirt_version=self.FAKE_LIBVIRT_VERSION,
            qemu_version=self.FAKE_QEMU_VERSION
        )

        self.api_fixture = self.useFixture(nova_fixtures.OSMetadataServer())
        self.md_url = self.api_fixture.md_url

        self.host = self.computes[self.compute].driver._host

        self.mock_connect = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.volume.nfs.LibvirtNFSVolumeDriver.'
            'connect_volume')).mock

        self.mock_disconnect = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.volume.nfs.LibvirtNFSVolumeDriver.'
            'disconnect_volume')).mock

        self.mock_connect_ceph = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.volume.cephfs.LibvirtCEPHFSVolumeDriver'
            '.connect_volume')).mock

        self.mock_disconnect_ceph = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.volume.cephfs.LibvirtCEPHFSVolumeDriver'
            '.disconnect_volume')).mock

    def _get_xml(self, server):
        self.instance = instance.Instance.get_by_uuid(
            self.context, server['id'])
        guest = self.host.get_guest(self.instance)
        xml = guest.get_xml_desc()
        return xml

    def _get_filesystem_tag(self, xml, tag):
        tags = []
        tree = etree.fromstring(xml)
        device_nodes = tree.find('./devices')
        filesystems = device_nodes.findall('./filesystem')
        for filesystem in filesystems:
            target = filesystem.find('./target')
            tags.append(target.get('dir'))
        return tags

    def _assert_filesystem_tag(self, xml, tag):
        tags = self._get_filesystem_tag(xml, tag)
        self.assertIn(tag, tags)

    def _assert_filesystem_tag_not_present(self, xml, tag):
        tags = self._get_filesystem_tag(xml, tag)
        self.assertNotIn(tag, tags)

    def _get_metadata_url(self, server):
        # make sure that the metadata service returns information about the
        # server we created above

        def fake_get_fixed_ip_by_address(self, ctxt, address):
            return {'instance_uuid': server['id']}

        self.useFixture(
            fixtures.MonkeyPatch(
                'nova.network.neutron.API.get_fixed_ip_by_address',
                fake_get_fixed_ip_by_address))
        url = '%sopenstack/latest/meta_data.json' % self.md_url
        return url

    def _assert_share_in_metadata(self, metatdata_url, share_id, tag):
        device_share_and_tag = []
        res = request('GET', metatdata_url, timeout=5)
        self.assertEqual(200, res.status_code)
        metadata = jsonutils.loads(res.text)
        for device in metadata['devices']:
            device_share_and_tag.append((device['share_id'], device['tag']))
        self.assertIn((share_id, tag), device_share_and_tag)

    def _check_traits(self):
        expected_traits = {
            "COMPUTE_STORAGE_VIRTIO_FS", "COMPUTE_MEM_BACKING_FILE"
        }

        traits = self._get_provider_traits(self.compute_rp_uuids[self.compute])

        self.assertEqual(expected_traits, expected_traits.intersection(traits))


class ServerSharesTest(ServerSharesTestBase):

    def test_server_share_metadata(self):
        """Verify that share metadata are available"""
        self._check_traits()
        server = self._create_server(networks='auto')
        self._stop_server(server)

        share_id = '4b021746-d0eb-4031-92aa-23c3bec182cd'
        self._attach_share(server, share_id)
        self._start_server(server)

        # tag is the filesystem target directory.
        # if post /server/{server_id}/share was called without a specific
        # tag then the tag is the share id.
        self._assert_filesystem_tag(self._get_xml(server), share_id)

        self._assert_share_in_metadata(
            self._get_metadata_url(server), share_id, share_id)
        return (server, share_id)

    def test_server_share_metadata_with_tag(self):
        """Verify that share metadata are available with the provided tag"""
        self._check_traits()
        server = self._create_server(networks='auto')
        self._stop_server(server)

        share_id = '4b021746-d0eb-4031-92aa-23c3bec182cd'
        tag = 'mytag'
        self._attach_share(server, share_id, tag=tag)
        self._start_server(server)

        # tag is the filesystem target directory.
        # if post /server/{server_id}/share was called without a specific
        # tag then the tag is the share id.
        self._assert_filesystem_tag(self._get_xml(server), tag)

        self._assert_share_in_metadata(
            self._get_metadata_url(server), share_id, tag)
        return (server, share_id)

    def test_server_share_fails_with_tag_already_used(self):
        """Verify that share create fails if we use an already assigned tag"""
        self._check_traits()
        server = self._create_server(networks='auto')
        self._stop_server(server)

        share_id = '4b021746-d0eb-4031-92aa-23c3bec182cd'
        tag = 'mytag'
        self._attach_share(server, share_id, tag=tag)

        share_id = '1457bd85-7e7f-4835-92de-47834e1516b5'
        tag = 'mytag'

        exc = self.assertRaises(
            client.OpenStackApiException,
            self._attach_share,
            server,
            share_id,
            tag=tag
        )

        self.assertEqual(409, exc.response.status_code)
        self.assertIn(
            "Share '1457bd85-7e7f-4835-92de-47834e1516b5' or "
            "tag 'mytag' already associated to this server.",
            str(exc.response.text),
        )

    def test_server_cephfs_share_metadata(self):
        """Verify that cephfs share metadata are available"""
        # update the mock to call the cephfs fake values
        self.manila_fixture.mock_get.side_effect = (
            self.manila_fixture.fake_get_cephfs
        )
        self.manila_fixture.mock_get_access.side_effect = (
            self.manila_fixture.fake_get_access_cephfs
        )

        self._check_traits()
        server = self._create_server(networks='auto')
        self._stop_server(server)

        share_id = '4b021746-d0eb-4031-92aa-23c3bec182cd'
        self._attach_share(server, share_id)
        self._start_server(server)

        # tag is the filesystem target directory.
        # if post /server/{server_id}/share was called without a specific
        # tag then the tag is the share id.
        self._assert_filesystem_tag(self._get_xml(server), share_id)

        self._assert_share_in_metadata(
            self._get_metadata_url(server), share_id, share_id)
        return (server, share_id)

    def test_server_share_after_hard_reboot(self):
        """Verify that share is still available after a reboot"""
        server, share_id = self.test_server_share_metadata()
        self._reboot_server(server, hard=True)

        self._assert_filesystem_tag(self._get_xml(server), share_id)

        self._assert_share_in_metadata(
            self._get_metadata_url(server), share_id, share_id)

    def test_server_share_mount_failure(self):
        os.environ['OS_DEBUG'] = "true"
        self._check_traits()

        self.mock_connect.side_effect = processutils.ProcessExecutionError
        server = self._create_server(networks='auto')
        self._stop_server(server)

        share_id = '4b021746-d0eb-4031-92aa-23c3bec182cd'

        self._attach_share(server, share_id)
        response = self._get_share(server, share_id)

        self.assertEqual(
            response["share_id"], "4b021746-d0eb-4031-92aa-23c3bec182cd"
        )
        self.assertEqual(response["status"], "inactive")

        # Here we are using CastAsCallFixture so we got an exception from
        # nova compute. This should not happen without the fixture and
        # the api should answer with a 201 status code.
        exc = self.assertRaises(
            client.OpenStackApiException,
            self._start_server,
            server
        )

        self.assertIn("nova.exception.ShareMountError", str(exc))

        log_out = self.stdlog.logger.output

        self.assertIn(
            "Share id 4b021746-d0eb-4031-92aa-23c3bec182cd mount error "
            "from server",
            log_out)

        sm = share_mapping.ShareMapping.get_by_instance_uuid_and_share_id(
            self.context, server['id'], share_id)
        self.assertEqual(sm.status, 'error')
        self.instance = instance.Instance.get_by_uuid(
            self.context, server['id'])
        self.assertEqual(self.instance.vm_state, 'error')
        return (server, share_id)

    def test_server_start_fails_share_in_error(self):
        """Ensure a server can not start if its attached share is in error
           status and hard reboot attempts allow to restart the server as
           soon as the share issue is fixed.
        """
        server, share_id = self.test_server_share_mount_failure()
        self._verify_start_fails_share_in_error(server, share_id)

        server, share_id = self.test_server_share_umount_failure()
        self._verify_start_fails_share_in_error(server, share_id)

    def _verify_start_fails_share_in_error(self, server, share_id):
        exc = self.assertRaises(
            client.OpenStackApiException,
            self._start_server,
            server
        )

        # Try to start a vm in error state.
        self.assertEqual(exc.response.status_code, 409)
        self.assertIn("Cannot \'start\' instance", exc.response.text)
        self.assertIn("while it is in vm_state error", exc.response.text)

        # Reboot to do another mount attempt and fix the error.
        # But the error is not fixed.
        self.mock_connect.side_effect = processutils.ProcessExecutionError
        # Here we are using CastAsCallFixture so we got an exception from
        # nova api. This should not happen without the fixture.
        exc = self.assertRaises(
            client.OpenStackApiException,
            self._reboot_server,
            server,
            hard=True
        )

        log_out = self.stdlog.logger.output

        self.assertIn(
            "Share id 4b021746-d0eb-4031-92aa-23c3bec182cd mount error "
            "from server",
            log_out)

        sm = share_mapping.ShareMapping.get_by_instance_uuid_and_share_id(
            self.context, server['id'], share_id)
        self.assertEqual(sm.status, 'error')
        self.instance = instance.Instance.get_by_uuid(
            self.context, server['id'])
        self.assertEqual(self.instance.vm_state, 'error')

        # Reboot to do another mount attempt and fix the error.
        # But the error is fixed now.
        self.mock_connect.side_effect = None
        self._reboot_server(server, hard=True)

        sm = share_mapping.ShareMapping.get_by_instance_uuid_and_share_id(
            self.context, server['id'], share_id)
        self.assertEqual(sm.status, 'active')
        self.instance = instance.Instance.get_by_uuid(
            self.context, server['id'])
        self.assertEqual(self.instance.vm_state, 'active')

    def test_detach_server_share_in_error(self):
        """Ensure share can still be detached even if
           the share are in an error state.
        """
        os.environ['OS_DEBUG'] = "true"
        server, share_id = self.test_server_share_umount_failure()

        # Simulate an attempt to detach that fail due to umount error.
        # In that case we should have an umount error.
        self.mock_disconnect.side_effect = processutils.ProcessExecutionError
        # Ensure we failed to umount he share
        log_out = self.stdlog.logger.output

        self.assertIn(
            "Share id 4b021746-d0eb-4031-92aa-23c3bec182cd umount error",
            log_out)

        # We detach the share. As a consequence, we are leaking the share
        # mounted on the compute.
        self._detach_share(server, share_id)

        # Share is removed so not anymore in the DB.
        self.assertRaises(
            exception.ShareNotFound,
            share_mapping.ShareMapping.get_by_instance_uuid_and_share_id,
            self.context,
            server['id'],
            share_id
        )
        self.instance = instance.Instance.get_by_uuid(
            self.context, server['id'])
        self.assertEqual(self.instance.vm_state, 'error')

        # Reboot the server to restart it without the share.
        self._reboot_server(server, hard=True)

        self.instance = instance.Instance.get_by_uuid(
            self.context, server['id'])
        self.assertEqual(self.instance.vm_state, 'active')

    def test_server_share_umount_failure(self):
        self.mock_disconnect.side_effect = processutils.ProcessExecutionError
        os.environ['OS_DEBUG'] = "true"
        self._check_traits()
        server = self._create_server(networks='auto')
        self._stop_server(server)

        share_id = '4b021746-d0eb-4031-92aa-23c3bec182cd'
        self._attach_share(server, share_id)
        self._start_server(server)

        # Here we are using CastAsCallFixture so we got an exception from
        # nova compute. This should not happen without the fixture and
        # the api should answer with a 202 status code.
        exc = self.assertRaises(
            client.OpenStackApiException,
            self._stop_server,
            server,
        )

        self.assertIn("nova.exception.ShareUmountError", str(exc))

        log_out = self.stdlog.logger.output

        self.assertIn(
            "Share id 4b021746-d0eb-4031-92aa-23c3bec182cd umount error "
            "from server",
            log_out)

        sm = share_mapping.ShareMapping.get_by_instance_uuid_and_share_id(
            self.context, server['id'], share_id)
        self.assertEqual(sm.status, 'error')
        self.instance = instance.Instance.get_by_uuid(
            self.context, server['id'])
        self.assertEqual(self.instance.vm_state, 'error')
        return (server, share_id)

    def test_server_resume_with_shares(self):
        server = self._create_server(networks='auto')
        self._stop_server(server)

        share_id = '4b021746-d0eb-4031-92aa-23c3bec182cd'
        self._attach_share(server, share_id)
        self._start_server(server)
        self.assertRaises(
            client.OpenStackApiException,
            self._suspend_server,
            server,
        )

    def test_server_rescue_with_shares(self):
        server = self._create_server(networks='auto')
        self._stop_server(server)

        share_id = '4b021746-d0eb-4031-92aa-23c3bec182cd'
        self._attach_share(server, share_id)
        self._start_server(server)
        self._rescue_server(server)

        self._assert_filesystem_tag(self._get_xml(server), share_id)

        self._assert_share_in_metadata(
            self._get_metadata_url(server), share_id, share_id)

        self._unrescue_server(server)

        self._assert_filesystem_tag(self._get_xml(server), share_id)

        self._assert_share_in_metadata(
            self._get_metadata_url(server), share_id, share_id)
        return (server, share_id)
