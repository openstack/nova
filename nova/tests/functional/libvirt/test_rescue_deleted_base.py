# All Rights Reserved.
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

import fixtures
from oslo_log import log as logging
from oslo_utils.fixture import uuidsentinel as uuids

from nova import conf
from nova import context as nova_context
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.libvirt import base

LOG = logging.getLogger(__name__)
CONF = conf.CONF


class RescueServerTestWithDeletedBaseImage(
    base.ServersTestBase
):

    api_major_version = 'v2.1'
    microversion = '2.87'

    # BUG #2002606
    # Rescue in stable rescue mode with deleted original image must be
    # successful
    def setUp(self):
        super(RescueServerTestWithDeletedBaseImage, self).setUp()

        self.ctxt = nova_context.get_admin_context()

        # to create bfv server with libvirt driver
        self.cinder = self.useFixture(nova_fixtures.CinderFixture(self))
        self.useFixture(nova_fixtures.OSBrickFixture())
        # disk.rescue image_create ignoring privsep
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.imagebackend._update_utime_ignore_eacces'))

        # dir to create 'unrescue.xml'
        def fake_path(_self, *args, **kwargs):
            return CONF.instances_path

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.utils.get_instance_path', fake_path))

    def _create_test_images(self):
        timestamp = datetime.datetime(2021, 1, 2, 3, 4, 5)
        base_image = {
            'id': uuids.base_image,
            'name': 'base_image',
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
            'properties': {}
        }
        rescue_stable_image = {
            'id': uuids.rescue_stable_image,
            'name': 'base_image',
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
               'hw_rescue_bus': 'scsi',
               'hw_rescue_device': 'cdrom'
            }
        }
        self.glance.create(self.ctxt, base_image)
        self.glance.create(self.ctxt, rescue_stable_image)
        return base_image, rescue_stable_image

    def test_stable_rescue_server_local_disk(self):
        self.start_compute()

        # create a local server with base image
        base_image, rescue_stable_image = self._create_test_images()
        server = self._create_server(image_uuid=uuids.base_image,
            networks='none')
        # instance.image_ref exists
        self.assertEqual(base_image['id'], server['image']['id'])

        # Delete base image
        self.glance.delete(self.ctxt, base_image['id'])

        rescue_req = {
            'rescue': {
                'rescue_image_ref': rescue_stable_image['id']
            }
        }
        # Rescue in stable device mode successful
        res = self.api.api_post('/servers/%s/action' % server['id'],
            rescue_req)
        self.assertEqual(200, res.status)

        # BUG #2002606
        # This test fails and server never reach RESCUE state.
        # It is expected behavior when server in stable rescue mode cannot
        # find original glance image.
        #
        # FIX with fallback:
        # except exception.ImageNotFound:
        #    image_meta = instance.image_meta
        # leads to passing this test

        self._wait_for_state_change(server, 'RESCUE')

    def test_stable_rescue_server_bfv(self):
        self.start_compute()

        # create a boot from volume server with libvirt driver
        base_image_not_used, rescue_stable_image = self._create_test_images()
        server_request = self._build_server(networks=[])
        server_request.pop('imageRef')
        server_request['block_device_mapping_v2'] = [{
            'boot_index': 0,
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL,
            'source_type': 'volume',
            'destination_type': 'volume'}]
        server = self.api.post_server({'server': server_request})
        server = self._wait_for_state_change(server, 'ACTIVE')
        # instance.image_ref is missing, attached volume exists
        self.assertEqual('', server['image'])
        self.assertEqual(1,
           len(server['os-extended-volumes:volumes_attached']))

        # Delete all glance images except rescue image
        ids = []
        for o in self.glance.images.keys():
            ids.append(o)
        for o in ids:
            if o != rescue_stable_image['id']:
                self.glance.delete(self.ctxt, o)
        self.assertEqual(1, len(self.glance.images.keys()))

        rescue_req = {
            'rescue': {
                'rescue_image_ref': rescue_stable_image['id']
            }
        }
        # Rescue in stable device mode successful
        res = self.api.api_post('/servers/%s/action' % server['id'],
            rescue_req)
        self.assertEqual(200, res.status)

        # BUG #2002606 does not affect server with bfv root
        # disks unless server.image_ref defined for bfv server.

        self._wait_for_state_change(server, 'RESCUE')
