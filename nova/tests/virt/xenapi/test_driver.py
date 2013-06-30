# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Rackspace Hosting
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


import math

from nova.tests.virt.xenapi import stubs
from nova.virt import fake
from nova.virt import xenapi


class XenAPIDriverTestCase(stubs.XenAPITestBase):
    """Unit tests for Driver operations."""

    def host_stats(self, refresh=True):
        return {'host_memory_total': 3 * 1024 * 1024,
                'host_memory_free_computed': 2 * 1024 * 1024,
                'disk_total': 4 * 1024 * 1024 * 1024,
                'disk_used': 5 * 1024 * 1024 * 1024,
                'host_hostname': 'somename',
                'supported_instances': 'x86_64',
                'host_cpu_info': {'cpu_count': 50}}

    def test_available_resource(self):
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)

        driver = xenapi.XenAPIDriver(fake.FakeVirtAPI(), False)
        driver._session.product_version = (6, 8, 2)

        self.stubs.Set(driver, 'get_host_stats', self.host_stats)

        resources = driver.get_available_resource(None)
        self.assertEqual(6008002, resources['hypervisor_version'])
        self.assertEqual(0, resources['vcpus'])
        self.assertEqual(3, resources['memory_mb'])
        self.assertEqual(4, resources['local_gb'])
        self.assertEqual(0, resources['vcpus_used'])
        self.assertEqual(3 - 2, resources['memory_mb_used'])
        self.assertEqual(5, resources['local_gb_used'])
        self.assertEqual('xen', resources['hypervisor_type'])
        self.assertEqual('somename', resources['hypervisor_hostname'])
        self.assertEqual(50, resources['cpu_info'])

    def test_overhead(self):
        self.flags(xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass')
        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        driver = xenapi.XenAPIDriver(fake.FakeVirtAPI(), False)
        instance = {'memory_mb': 30720}

        # expected memory overhead per:
        # https://wiki.openstack.org/wiki/XenServer/Overhead
        expected = math.ceil(251.832)
        overhead = driver.estimate_instance_overhead(instance)
        self.assertEqual(expected, overhead['memory_mb'])
