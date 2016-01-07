# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class BlockDeviceMappingV1BootJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-block-device-mapping-v1"

    def test_servers_post_with_bdm(self):
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        self.stub_out('nova.volume.cinder.API.check_attach',
                      fakes.stub_volume_check_attach)
        return self._post_server()


class BlockDeviceMappingV2BootJsonTest(BlockDeviceMappingV1BootJsonTest):
    extension_name = "os-block-device-mapping"

    def _get_flags(self):
        f = super(BlockDeviceMappingV2BootJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.legacy_v2.contrib.'
            'block_device_mapping_v2_boot.Block_device_mapping_v2_boot')
        return f
