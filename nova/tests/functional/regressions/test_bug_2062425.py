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


import copy
import ddt

from oslo_utils.fixture import uuidsentinel as uuids

from nova.tests.functional.libvirt import base


@ddt.ddt
class TestSchedulingForImageCPUProperty(base.ServersTestBase):
    """Regression test for bug #2062425

    reference arch list
    https://docs.openstack.org/glance/latest/admin/useful-image-properties.html#image-property-keys-and-values
    """
    microversion = 'latest'

    def setUp(self):
        super().setUp()

        self.flags(image_metadata_prefilter=True, group='scheduler')
        self.start_compute()

    def test_server_create_with_valid_arch(self):
        arch = "x86_64"
        cpu_arch_image = copy.deepcopy(self.glance.image1)
        cpu_arch_image['properties']['hw_architecture'] = arch
        cpu_arch_image['id'] = uuids.cpu_arch_image
        self.glance.create(None, cpu_arch_image)

        server = self._create_server(
            image_uuid=uuids.cpu_arch_image,
            networks='none',
            # FIXME(auniyal): Server failed to spawn
            expected_state='ERROR'
        )
        # this is a bug, with valid hw_arch,
        # scheduler should be able to find host
        self.assertIn("No valid host was found", server['fault']['message'])
