# Copyright 2015 Cloudbase Solutions Srl
#
# All Rights Reserved.
#
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

import mock

from nova.tests.unit.virt.hyperv import test_base
from nova.virt.hyperv import vif


class HyperVNovaNetworkVIFDriverTestCase(test_base.HyperVBaseTestCase):
    def setUp(self):
        super(HyperVNovaNetworkVIFDriverTestCase, self).setUp()
        self.vif_driver = vif.HyperVNovaNetworkVIFDriver()

    def test_plug(self):
        self.flags(vswitch_name=mock.sentinel.vswitch_name, group='hyperv')
        fake_vif = {'id': mock.sentinel.fake_id}

        self.vif_driver.plug(mock.sentinel.instance, fake_vif)
        netutils = self.vif_driver._netutils
        netutils.connect_vnic_to_vswitch.assert_called_once_with(
            mock.sentinel.vswitch_name, mock.sentinel.fake_id)
