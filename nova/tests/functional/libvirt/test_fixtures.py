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

from unittest import mock

from oslo_concurrency import lockutils

from nova import test
from nova.tests.functional.libvirt import base


class TestLibvirtNeutronFixture(test.NoDBTestCase):
    def test_create_port_uses_fixture_lock(self):
        neutron = self.useFixture(base.LibvirtNeutronFixture(self))
        # The override does not call the base create_port, so it must acquire
        # the same lock itself before modifying the shared port inventory.
        with mock.patch.object(
            lockutils, 'lock', autospec=True, side_effect=lockutils.lock,
        ) as lock:
            response = neutron.create_port(
                {'port': {'network_id': neutron.network_1['id']}})

        lock.assert_called_once()
        self.assertEqual('neutron-fixture', lock.call_args.args[0])
        port_id = response['port']['id']
        self.assertEqual(response['port'], neutron.show_port(port_id)['port'])
        response['port']['binding:vif_details']['changed'] = True
        stored_port = neutron.show_port(port_id)['port']
        self.assertNotIn('changed', stored_port['binding:vif_details'])
