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

from oslo_config import cfg
from oslo_log import log as logging

from nova import objects
from nova.tests.functional.libvirt import integrated_helpers
from nova.tests.unit.virt.libvirt import fake_imagebackend
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class VPMEMTestBase(integrated_helpers.LibvirtProviderUsageBaseTestCase):

    FAKE_LIBVIRT_VERSION = 5000000
    FAKE_QEMU_VERSION = 3001000

    def setUp(self):
        super(VPMEMTestBase, self).setUp()

        self.flags(pmem_namespaces="4GB:ns_0,SMALL:ns_1|ns_2",
                   group='libvirt')
        self.fake_pmem_namespaces = '''
            [{"dev":"namespace0.0",
            "mode":"devdax",
            "map":"mem",
            "size":4292870144,
            "uuid":"24ffd5e4-2b39-4f28-88b3-d6dc1ec44863",
            "daxregion":{"id": 0, "size": 4292870144,"align": 2097152,
            "devices":[{"chardev":"dax0.0",
            "size":4292870144}]},
            "name":"ns_0",
            "numa_node":0},
            {"dev":"namespace0.1",
            "mode":"devdax",
            "map":"mem",
            "size":4292870144,
            "uuid":"ac64fe52-de38-465b-b32b-947a6773ac66",
            "daxregion":{"id": 0, "size": 4292870144,"align": 2097152,
            "devices":[{"chardev":"dax0.1",
            "size":4292870144}]},
            "name":"ns_1",
            "numa_node":0},
            {"dev":"namespace0.2",
            "mode":"devdax",
            "map":"mem",
            "size":4292870144,
            "uuid":"2ff41eba-db9c-4bb9-a959-31d992568a3e",
            "raw_uuid":"0b61823b-5668-4856-842d-c644dae83410",
            "daxregion":{"id":0, "size":4292870144, "align":2097152,
            "devices":[{"chardev":"dax0.2",
            "size":4292870144}]},
            "name":"ns_2",
            "numa_node":0}]'''

        self.useFixture(fixtures.MockPatch(
            'nova.privsep.libvirt.cleanup_vpmem'))
        self.useFixture(fixtures.MockPatch(
            'nova.privsep.libvirt.get_pmem_namespaces',
            return_value=self.fake_pmem_namespaces))
        self.useFixture(fake_imagebackend.ImageBackendFixture())
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_local_gb_info',
            return_value={'total': 128,
                          'used': 44,
                          'free': 84}))
        self.mock_conn = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.host.Host._get_new_connection')).mock

    def _get_connection(self, host_info, hostname=None):
        fake_connection = fakelibvirt.Connection(
            'qemu:///system',
            version=self.FAKE_LIBVIRT_VERSION,
            hv_version=self.FAKE_QEMU_VERSION,
            host_info=host_info,
            hostname=hostname)
        return fake_connection

    def _start_compute_service(self, hostname):
        fake_connection = self._get_connection(
            # Need a host to support creating more servers with vpmems
            host_info=fakelibvirt.HostInfo(cpu_nodes=2, cpu_sockets=1,
                                           cpu_cores=2, cpu_threads=2,
                                           kB_mem=15740000),
            hostname=hostname)
        self.mock_conn.return_value = fake_connection
        compute = self._start_compute(host=hostname)

        # Ensure populating the existing pmems correctly.
        vpmems = compute.driver._vpmems_by_name
        expected_vpmems = {
            'ns_0': objects.LibvirtVPMEMDevice(
                label='4GB', name='ns_0', devpath='/dev/dax0.0',
                size=4292870144, align=2097152),
            'ns_1': objects.LibvirtVPMEMDevice(
                label='SMALL', name='ns_1', devpath='/dev/dax0.1',
                size=4292870144, align=2097152),
            'ns_2': objects.LibvirtVPMEMDevice(
                label='SMALL', name='ns_2', devpath='/dev/dax0.2',
                size=4292870144, align=2097152)}
        self.assertDictEqual(expected_vpmems, vpmems)

        # Ensure reporting vpmems resources correctly
        rp_uuid = self._get_provider_uuid_by_host(compute.host)
        inventory = self._get_provider_inventory(rp_uuid)
        self.assertEqual(1, inventory['CUSTOM_PMEM_NAMESPACE_4GB']['total'])
        self.assertEqual(2, inventory['CUSTOM_PMEM_NAMESPACE_SMALL']['total'])

        return compute

    def _create_server(self, flavor_id, hostname, expected_state):
        return super(VPMEMTestBase, self)._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            flavor_id=flavor_id,
            networks='none',
            az='nova:%s' % hostname,
            expected_state=expected_state)

    def _delete_server(self, server):
        self.api.delete_server(server['id'])

    def _check_vpmem_allocations(self, vpmem_allocs, server_id, cn_uuid):
        cn_allocs = self._get_allocations_by_server_uuid(
            server_id)[cn_uuid]['resources']
        for rc, amount in vpmem_allocs.items():
            self.assertEqual(amount, cn_allocs[rc])


class VPMEMTests(VPMEMTestBase):

    def setUp(self):
        super(VPMEMTests, self).setUp()
        extra_spec = {"hw:pmem": "SMALL"}
        self.flavor = self._create_flavor(extra_spec=extra_spec)

    def test_create_servers_with_vpmem(self):
        # Start one compute service
        self.compute1 = self._start_compute_service('host1')
        cn1_uuid = self._get_provider_uuid_by_host(self.compute1.host)

        # Boot two servers with pmem
        server1 = self._create_server(self.flavor, self.compute1.host,
                                      expected_state='ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server1['id'], cn1_uuid)

        server2 = self._create_server(self.flavor, self.compute1.host,
                                      expected_state='ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server2['id'], cn1_uuid)

        # 'SMALL' VPMEM resource has used up
        server3 = self._create_server(self.flavor, self.compute1.host,
                                      expected_state='ERROR')

        # Delete server2, one 'SMALL' VPMEM will be released
        self._delete_server(server2)
        self._wait_until_deleted(server2)
        server3 = self._create_server(self.flavor, self.compute1.host,
                                      expected_state='ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server3['id'], cn1_uuid)


class VPMEMResizeTests(VPMEMTestBase):

    def setUp(self):
        super(VPMEMResizeTests, self).setUp()

        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_instance_disk_info',
             return_value=[]))
        self.useFixture(fixtures.MockPatch('os.rename'))

        extra_spec = {"hw:pmem": "SMALL"}
        self.flavor1 = self._create_flavor(extra_spec=extra_spec)
        extra_spec = {"hw:pmem": "4GB,SMALL"}
        self.flavor2 = self._create_flavor(extra_spec=extra_spec)

    def _resize_server(self, server, flavor):
        resize_req = {
            'resize': {
                'flavorRef': flavor
            }
        }
        self.api.api_post('/servers/%s/action' % server['id'],
                          resize_req)

    def _confirm_resize(self, server):
        confirm_resize_req = {'confirmResize': None}
        self.api.api_post('/servers/%s/action' % server['id'],
                          confirm_resize_req)

    def _revert_resize(self, server):
        revert_resize_req = {'revertResize': None}
        self.api.api_post('/servers/%s/action' % server['id'],
                          revert_resize_req)

    def test_resize(self):
        self.flags(allow_resize_to_same_host=False)
        # Start two compute nodes
        self.compute1 = self._start_compute_service('host1')
        self.compute2 = self._start_compute_service('host2')
        cn1_uuid = self._get_provider_uuid_by_host(self.compute1.host)
        cn2_uuid = self._get_provider_uuid_by_host(self.compute2.host)

        # Boot one server with pmem, then resize the server
        server = self._create_server(self.flavor1, self.compute1.host,
                                     expected_state='ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn1_uuid)

        # Revert resize
        self._resize_server(server, self.flavor2)
        self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_4GB': 1,
                                       'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn2_uuid)
        self._revert_resize(server)
        self._wait_for_state_change(server, 'ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn1_uuid)

        # Confirm resize
        self._resize_server(server, self.flavor2)
        self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_4GB': 1,
                                       'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn2_uuid)
        self._confirm_resize(server)
        self._wait_for_state_change(server, 'ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_4GB': 1,
                                       'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn2_uuid)

    def test_resize_same_host(self):
        self.flags(allow_resize_to_same_host=True)
        # Start one compute nodes
        self.compute1 = self._start_compute_service('host1')
        cn1_uuid = self._get_provider_uuid_by_host(self.compute1.host)

        # Boot one server with pmem, then resize the server
        server = self._create_server(self.flavor1, self.compute1.host,
                                     expected_state='ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn1_uuid)

        # Revert resize
        self._resize_server(server, self.flavor2)
        self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_4GB': 1,
                                       'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn1_uuid)
        self._revert_resize(server)
        self._wait_for_state_change(server, 'ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn1_uuid)

        # Confirm resize
        self._resize_server(server, self.flavor2)
        self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_4GB': 1,
                                       'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn1_uuid)
        self._confirm_resize(server)
        self._wait_for_state_change(server, 'ACTIVE')
        self._check_vpmem_allocations({'CUSTOM_PMEM_NAMESPACE_4GB': 1,
                                       'CUSTOM_PMEM_NAMESPACE_SMALL': 1},
                                      server['id'], cn1_uuid)
