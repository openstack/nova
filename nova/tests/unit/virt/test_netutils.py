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

from nova.network import model as network_model
from nova import test
from nova.tests.unit import fake_network
from nova.virt import netutils


class TestNetUtilsTestCase(test.NoDBTestCase):
    def test_get_cached_vifs_with_vlan_no_nw_info(self):
        # Make sure that an empty dictionary will be returned when
        # nw_info is None
        self.assertEqual({}, netutils.get_cached_vifs_with_vlan(None))

    def test_get_cached_vifs_with_vlan_with_no_vlan_details(self):
        network_info = fake_network.fake_get_instance_nw_info(self, 1)
        network_info[0]['vnic_type'] = network_model.VNIC_TYPE_DIRECT_PHYSICAL
        network_info[0]['address'] = "51:5a:2c:a4:5e:1b"
        self.assertEqual({}, netutils.get_cached_vifs_with_vlan(network_info))

    def test_get_cached_vifs_with_vlan(self):
        network_info = fake_network.fake_get_instance_nw_info(self, 2)
        network_info[0]['vnic_type'] = network_model.VNIC_TYPE_DIRECT_PHYSICAL
        network_info[0]['address'] = "51:5a:2c:a4:5e:1b"

        network_info[1]['vnic_type'] = network_model.VNIC_TYPE_DIRECT_PHYSICAL
        network_info[1]['address'] = "fa:16:3e:d1:28:e4"
        network_info[1]['details'] = dict(vlan='2145')
        expected = {'fa:16:3e:d1:28:e4': '2145'}
        self.assertEqual(expected,
                         netutils.get_cached_vifs_with_vlan(network_info))
