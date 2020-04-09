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

import nova.conf
from nova import test


CONF = nova.conf.CONF


class DevicesConfTestCase(test.NoDBTestCase):

    def test_register_dynamic_opts(self):
        self.flags(enabled_vgpu_types=['nvidia-11', 'nvidia-12'],
                   group='devices')

        self.assertNotIn('vgpu_nvidia-11', CONF)
        self.assertNotIn('vgpu_nvidia-12', CONF)

        nova.conf.devices.register_dynamic_opts(CONF)

        self.assertIn('vgpu_nvidia-11', CONF)
        self.assertIn('vgpu_nvidia-12', CONF)
        self.assertEqual([], getattr(CONF, 'vgpu_nvidia-11').device_addresses)
        self.assertEqual([], getattr(CONF, 'vgpu_nvidia-12').device_addresses)
