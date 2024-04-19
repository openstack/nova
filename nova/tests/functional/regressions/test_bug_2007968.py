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

import fixtures

from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.api import client
from nova.tests.functional.libvirt import base


class Bug2007968RegressionTest(base.ServersTestBase):
    """Regression test for bug 2007968
    """

    api_major_version = 'v2.1'
    microversion = 'latest'

    def setUp(self):
        super().setUp()

        self.useFixture(
            fixtures.MockPatch(
                'nova.virt.libvirt.driver.LibvirtDriver.'
                'migrate_disk_and_power_off',
                return_value='{}'
            )
        )

        self.flags(allow_resize_to_same_host=True)
        host_info = fakelibvirt.HostInfo()
        self.start_compute(host_info=host_info, hostname='compute1')

    def test_resize_with_smaller_memory_image_required(self):
        # Resize down from old_flavor to new_flavor.
        old_flavor = self._create_flavor(id='2007968_old', memory_mb=4096)
        new_flavor = self._create_flavor(id='2007968_new', memory_mb=512)

        # Now the instance for boot from image already has verification for
        # image min ram, but the instance for boot from volume does not have
        # such verification, so this bug only applies to instance that boot
        # from volume.
        server = self._create_server_boot_from_volume(
            networks='auto',
            image_args={'min_ram': 4096},
            flavor_id=old_flavor
        )

        # This can cause the instance for boot from volume to be allowed to
        # get to the resize verify status, but the instance's application runs
        # abnormally due to insufficient memory, and it may be killed by OOM.

        # After the fix, compute api will directly raise FlavorMemoryTooSmall
        # and will not continue the resize.
        ex = self.assertRaises(client.OpenStackApiException,
                               self._resize_server, server, new_flavor)
        self.assertEqual(400, ex.response.status_code)
        self.assertIn('Flavor\'s memory is too small for requested image.',
                      ex.response.text)
