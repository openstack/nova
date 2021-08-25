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

from unittest import mock

from nova.scheduler.mixins import HypervisorSizeMixin
from nova import test
from nova.tests.unit.scheduler import fakes
from oslo_utils.fixture import uuidsentinel


@mock.patch('nova.scheduler.client.report.'
            'SchedulerReportClient._get_inventory')
class TestHypervisorSizeMixin(test.NoDBTestCase):

    def setUp(self):
        super(TestHypervisorSizeMixin, self).setUp()
        self.filt_cls = HypervisorSizeMixin()
        self.hv_size = 1234
        self.filt_cls._HV_SIZE_CACHE.cache = {}

    def test_host_without_inventory(self, mock_inv):
        mock_inv.return_value = {}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.assertIsNone(self.filt_cls._get_hv_size(host))

    def test_host_with_placement_error(self, mock_inv):
        mock_inv.return_value = None
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.assertIsNone(self.filt_cls._get_hv_size(host))

    def test_host_with_empty_inventory(self, mock_inv):
        mock_inv.return_value = {'inventories': {}}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.assertIsNone(self.filt_cls._get_hv_size(host))

    def test_get_hv_size_with_cache(self, mock_inv):
        mock_inv.return_value = {}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.filt_cls._HV_SIZE_CACHE.set(host.uuid, 1234)
        self.assertEqual(self.filt_cls._get_hv_size(host), 1234)

    def test_get_hv_size_cache_timeout(self, mock_inv):
        """oslo.cache will return a NO_VALUE if the cache-entry wasn't valid
        anymore. The same is returned if nothing is in the cache.
        """
        mock_inv.return_value = {'inventories': {'MEMORY_MB':
                                                    {'max_unit': 23}}}
        host = fakes.FakeHostState('host1', 'compute',
                {'free_ram_mb': self.hv_size,
                 'total_usable_ram_mb': self.hv_size,
                 'uuid': uuidsentinel.host1})
        self.assertEqual(self.filt_cls._get_hv_size(host), 23)
