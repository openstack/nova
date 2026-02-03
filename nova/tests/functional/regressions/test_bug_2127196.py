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

"""Regression test for bug 2127196.

https://bugs.launchpad.net/nova/+bug/2127196

When Cinder reports disk geometry (logical/physical block size) for LUN
volumes, Nova incorrectly includes a <blockio> element in the libvirt XML.
QEMU's scsi-block device driver (used for device="lun") does not support
these properties, causing QEMU to fail with:

    Property 'scsi-block.physical_block_size' not found

The fix ensures that <blockio> is not generated for LUN devices.
"""

from lxml import etree
from oslo_utils.fixture import uuidsentinel as uuids

import fixtures

from nova.tests.fixtures import cinder as cinder_fixture
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class CinderFixtureWithLunBlockSize(cinder_fixture.CinderFixture):
    """CinderFixture that provides a LUN volume with block size info."""

    # Volume ID for a LUN volume with block size info
    LUN_VOLUME_WITH_BLOCKSIZE = uuids.lun_volume_with_blocksize

    def __init__(self, test, az='nova'):
        super().__init__(test, az)
        # Add connection_info for the LUN volume that includes block size
        self.VOLUME_CONNECTION_INFO[self.LUN_VOLUME_WITH_BLOCKSIZE] = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_lun': '1',
                'logical_block_size': '512',
                'physical_block_size': '512',
            }
        }


class TestLunVolumeBlockio(
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Regression test for bug 2127196.

    Tests that blockio is not generated for LUN volumes even when Cinder
    provides block size information.
    """

    microversion = 'latest'
    ADMIN_API = True

    def setUp(self):
        super().setUp()
        self.cinder = self.useFixture(CinderFixtureWithLunBlockSize(self))
        self.useFixture(fixtures.MockPatch(
            'nova.compute.manager.ComputeVirtAPI.wait_for_instance_event'))
        self.start_compute(
            hostname='compute1',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))

    def _get_xml_element(self, xml, xpath):
        """Get element from XML using xpath."""
        xml_doc = etree.fromstring(xml.encode('utf-8'))
        element = xml_doc.find(xpath)
        return element

    def test_lun_volume_no_blockio(self):
        """Test that blockio is not included for LUN volumes.

        When Cinder reports block size information for a LUN volume,
        Nova should NOT include <blockio> in the libvirt XML because
        QEMU's scsi-block driver does not support these properties.
        """
        # Build a server with a LUN volume as the boot device
        server = self._build_server(image_uuid='', networks='none')
        server['block_device_mapping_v2'] = [{
            'boot_index': 0,
            'uuid': CinderFixtureWithLunBlockSize.LUN_VOLUME_WITH_BLOCKSIZE,
            'source_type': 'volume',
            'destination_type': 'volume',
            'device_type': 'lun',
            'disk_bus': 'scsi',
        }]

        created_server = self.api.post_server({'server': server})
        self._wait_for_state_change(created_server, 'ACTIVE')

        # Get the libvirt XML
        conn = self.computes['compute1'].driver._host.get_connection()
        dom = conn.lookupByUUIDString(created_server['id'])
        xml = dom.XMLDesc(0)

        # Find the disk element for the LUN volume
        xml_doc = etree.fromstring(xml.encode('utf-8'))
        disk = xml_doc.find('.//disk[@device="lun"]')
        self.assertIsNotNone(
            disk, "Expected to find a disk with device='lun' in the XML")

        # Verify that blockio is NOT present for the LUN device
        # This is the correct behavior after the fix
        blockio = disk.find('blockio')
        self.assertIsNone(
            blockio,
            "Bug 2127196: blockio should NOT be present for LUN devices "
            "because QEMU's scsi-block driver does not support "
            "physical_block_size and logical_block_size properties")
