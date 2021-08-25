# Copyright (c) 2021 SAP SE
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
import time

import mock

import nova.conf
from nova.scheduler.filters import bigvm_filter
from nova import test
from nova.tests.unit.scheduler import fakes
from oslo_utils.fixture import uuidsentinel

CONF = nova.conf.CONF


@mock.patch('nova.scheduler.client.report.'
            'SchedulerReportClient._get_inventory')
class TestBigVmBaseFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestBigVmBaseFilter, self).setUp()
        self.filt_cls = bigvm_filter.BigVmBaseFilter()
        self.hv_size = CONF.bigvm_mb + 1024

    def test_big_vm_host_without_inventory(self, mock_inv):
        mock_inv.return_value = {}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.assertIsNone(self.filt_cls._get_hv_size(host))

    def test_big_vm_host_with_placement_error(self, mock_inv):
        mock_inv.return_value = None
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.assertIsNone(self.filt_cls._get_hv_size(host))

    def test_big_vm_host_with_empty_inventory(self, mock_inv):
        mock_inv.return_value = {'inventories': {}}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.assertIsNone(self.filt_cls._get_hv_size(host))

    def test_big_vm_get_hv_size_with_cache(self, mock_inv):
        mock_inv.return_value = {}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE = {
            host.uuid: 1234,
            'last_modified': time.time()
        }
        self.assertEqual(self.filt_cls._get_hv_size(host), 1234)

    def test_big_vm_get_hv_size_cache_timeout(self, mock_inv):
        mock_inv.return_value = {'inventories': {'MEMORY_MB':
                                                    {'max_unit': 23}}}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        mod = time.time() - self.filt_cls._HV_SIZE_CACHE_RETENTION_TIME
        self.filt_cls._HV_SIZE_CACHE = {
            host.uuid: 1234,
            'last_modified': mod
        }
        self.assertEqual(self.filt_cls._get_hv_size(host), 23)
