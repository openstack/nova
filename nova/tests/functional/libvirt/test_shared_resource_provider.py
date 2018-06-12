# Copyright (C) 2018 NTT DATA, Inc
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

import fixtures

from nova import conf
from nova.tests.functional import integrated_helpers
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.tests import uuidsentinel as uuids

CONF = conf.CONF


class SharedStorageProviderUsageTestCase(
        integrated_helpers.ProviderUsageBaseTestCase):
    compute_driver = 'libvirt.LibvirtDriver'

    def setUp(self):
        super(SharedStorageProviderUsageTestCase, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
                        'nova.virt.libvirt.driver.libvirt',
                        fakelibvirt))
        self.useFixture(fixtures.MonkeyPatch('nova.virt.libvirt.host.libvirt',
                        fakelibvirt))
        self.useFixture(
            fixtures.MockPatch(
                'nova.virt.libvirt.driver.LibvirtDriver.init_host'))
        self.useFixture(
            fixtures.MockPatch(
                'nova.virt.libvirt.driver.LibvirtDriver.spawn'))
        self.useFixture(
            fixtures.MockPatch('nova.virt.libvirt.utils.get_fs_info'))
        self.compute = self._start_compute(CONF.host)
        nodename = self.compute.manager._get_nodename(None)
        self.host_uuid = self._get_provider_uuid_by_host(nodename)

    def test_shared_storage_rp_configuration_with_cn_rp(self):
        """Test to check whether compute node and shared storage resource
        provider inventory is configured properly or not.
        """

        # shared storage resource provider
        shared_RP = self._post_resource_provider(
            rp_name='shared_resource_provider')

        # created inventory for shared storage RP
        inv = {"resource_class": "DISK_GB",
               "total": 78, "reserved": 0, "min_unit": 1, "max_unit": 78,
               "step_size": 1, "allocation_ratio": 1.0}
        self._set_inventory(shared_RP['uuid'], inv)

        # Added traits to shared storage resource provider
        self._set_provider_traits(shared_RP['uuid'],
                                  ['MISC_SHARES_VIA_AGGREGATE'])

        # add both cn_rp and shared_rp under one aggregate
        self._set_aggregate(shared_RP['uuid'], uuids.shr_disk_agg)
        self._set_aggregate(self.host_uuid, uuids.shr_disk_agg)

        self.assertIn("DISK_GB", self._get_provider_inventory(self.host_uuid))

        # run update_available_resource periodic task after configuring shared
        # resource provider to update compute node resources
        self._run_periodics()

        # we expect that the virt driver stops reporting DISK_GB on the compute
        # RP as soon as a shared RP with DISK_GB is created in the compute tree
        self.assertNotIn("DISK_GB",
                         self._get_provider_inventory(self.host_uuid))

        server_req_body = {
            'server': {
                'imageRef': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'flavorRef': '1',
                'name': 'test_shared_storage_rp_configuration_with_cn_rp',
                'networks': 'none'
            }
        }
        # create server
        server = self.api.post_server(server_req_body)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # get shared_rp and cn_rp usages
        shared_rp_usages = self._get_provider_usages(shared_RP['uuid'])
        cn_rp_usages = self._get_provider_usages(self.host_uuid)
        # Check if DISK_GB resource is allocated from shared_RP and the
        # remaining resources are allocated from host_uuid.
        self.assertEqual({'DISK_GB': 1}, shared_rp_usages)
        self.assertEqual({'MEMORY_MB': 512, 'VCPU': 1},
                         cn_rp_usages)
