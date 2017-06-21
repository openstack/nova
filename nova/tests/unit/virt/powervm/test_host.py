# Copyright 2016 IBM Corp.
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
#

import mock
from pypowervm.wrappers import managed_system as pvm_ms

from nova import test
from nova.virt.powervm import host as pvm_host


class TestPowerVMHost(test.NoDBTestCase):
    def test_host_resources(self):
        # Create objects to test with
        ms_wrapper = mock.create_autospec(pvm_ms.System, spec_set=True)
        asio = mock.create_autospec(pvm_ms.ASIOConfig, spec_set=True)
        ms_wrapper.configure_mock(
            proc_units_configurable=500,
            proc_units_avail=500,
            memory_configurable=5242880,
            memory_free=5242752,
            memory_region_size='big',
            asio_config=asio)
        self.flags(host='the_hostname')

        # Run the actual test
        stats = pvm_host.build_host_resource_from_ms(ms_wrapper)
        self.assertIsNotNone(stats)

        # Check for the presence of fields
        fields = (('vcpus', 500), ('vcpus_used', 0),
                  ('memory_mb', 5242880), ('memory_mb_used', 128),
                  'hypervisor_type', 'hypervisor_version',
                  ('hypervisor_hostname', 'the_hostname'), 'cpu_info',
                  'supported_instances', 'stats')
        for fld in fields:
            if isinstance(fld, tuple):
                value = stats.get(fld[0], None)
                self.assertEqual(value, fld[1])
            else:
                value = stats.get(fld, None)
                self.assertIsNotNone(value)
        # Check for individual stats
        hstats = (('proc_units', '500.00'), ('proc_units_used', '0.00'))
        for stat in hstats:
            if isinstance(stat, tuple):
                value = stats['stats'].get(stat[0], None)
                self.assertEqual(value, stat[1])
            else:
                value = stats['stats'].get(stat, None)
                self.assertIsNotNone(value)
