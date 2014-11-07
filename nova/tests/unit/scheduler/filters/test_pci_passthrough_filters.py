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

from nova import objects
from nova.scheduler.filters import pci_passthrough_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestPCIPassthroughFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestPCIPassthroughFilter, self).setUp()
        self.filt_cls = pci_passthrough_filter.PciPassthroughFilter()

    def test_pci_passthrough_pass(self):
        pci_stats_mock = mock.MagicMock()
        pci_stats_mock.support_requests.return_value = True
        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': '8086'}])
        requests = objects.InstancePCIRequests(requests=[request])
        filter_properties = {'pci_requests': requests}
        host = fakes.FakeHostState(
            'host1', 'node1',
            attribute_dict={'pci_stats': pci_stats_mock})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))
        pci_stats_mock.support_requests.assert_called_once_with(
            requests.requests)

    def test_pci_passthrough_fail(self):
        pci_stats_mock = mock.MagicMock()
        pci_stats_mock.support_requests.return_value = False
        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': '8086'}])
        requests = objects.InstancePCIRequests(requests=[request])
        filter_properties = {'pci_requests': requests}
        host = fakes.FakeHostState(
            'host1', 'node1',
            attribute_dict={'pci_stats': pci_stats_mock})
        self.assertFalse(self.filt_cls.host_passes(host, filter_properties))
        pci_stats_mock.support_requests.assert_called_once_with(
            requests.requests)

    def test_pci_passthrough_no_pci_request(self):
        filter_properties = {}
        host = fakes.FakeHostState('h1', 'n1', {})
        self.assertTrue(self.filt_cls.host_passes(host, filter_properties))

    def test_pci_passthrough_compute_stats(self):
        requests = [{'count': 1, 'spec': [{'vendor_id': '8086'}]}]
        filter_properties = {'pci_requests': requests}
        host = fakes.FakeHostState(
            'host1', 'node1',
            attribute_dict={})
        self.assertRaises(AttributeError, self.filt_cls.host_passes,
                          host, filter_properties)
