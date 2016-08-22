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

from nova import context
from nova import objects
from nova.objects import pci_device_pool
from nova.scheduler.client import report
from nova import test


class SchedulerReportClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerReportClientTestCase, self).setUp()
        self.context = context.get_admin_context()

        self.flags(use_local=True, group='conductor')

        self.client = report.SchedulerReportClient()

    @mock.patch.object(objects.ComputeNode, 'save')
    def test_update_resource_stats_saves(self, mock_save):
        cn = objects.ComputeNode(context=self.context)
        cn.host = 'fakehost'
        cn.hypervisor_hostname = 'fakenode'
        cn.pci_device_pools = pci_device_pool.from_pci_stats(
            [{"vendor_id": "foo",
              "product_id": "foo",
              "count": 1,
              "a": "b"}])
        self.client.update_resource_stats(cn)
        mock_save.assert_called_once_with()
