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

from oslo_utils.fixture import uuidsentinel as uuids

from nova import objects
from nova.pci import stats
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
        spec_obj = objects.RequestSpec(pci_requests=requests)
        host = fakes.FakeHostState(
            "host1",
            "node1",
            attribute_dict={
                "pci_stats": pci_stats_mock,
                "allocation_candidates": [{"mappings": {}}],
            },
        )
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))
        pci_stats_mock.support_requests.assert_called_once_with(
            requests.requests, provider_mapping={})

    def test_pci_passthrough_fail(self):
        pci_stats_mock = mock.MagicMock()
        pci_stats_mock.support_requests.return_value = False
        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': '8086'}])
        requests = objects.InstancePCIRequests(requests=[request])
        spec_obj = objects.RequestSpec(pci_requests=requests)
        host = fakes.FakeHostState(
            "host1",
            "node1",
            attribute_dict={
                "pci_stats": pci_stats_mock,
                "allocation_candidates": [{"mappings": {}}],
            },
        )
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
        pci_stats_mock.support_requests.assert_called_once_with(
            requests.requests, provider_mapping={})

    def test_pci_passthrough_no_pci_request(self):
        spec_obj = objects.RequestSpec(pci_requests=None)
        host = fakes.FakeHostState('h1', 'n1', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_pci_passthrough_empty_pci_request_obj(self):
        requests = objects.InstancePCIRequests(requests=[])
        spec_obj = objects.RequestSpec(pci_requests=requests)
        host = fakes.FakeHostState('h1', 'n1', {})
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_pci_passthrough_no_pci_stats(self):
        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': '8086'}])
        requests = objects.InstancePCIRequests(requests=[request])
        spec_obj = objects.RequestSpec(pci_requests=requests)
        host = fakes.FakeHostState('host1', 'node1',
            attribute_dict={
                'pci_stats': stats.PciDeviceStats(objects.NUMATopology())})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_pci_passthrough_with_pci_stats_none(self):
        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': '8086'}])
        requests = objects.InstancePCIRequests(requests=[request])
        spec_obj = objects.RequestSpec(pci_requests=requests)
        host = fakes.FakeHostState('host1', 'node1',
            attribute_dict={'pci_stats': None})
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

    def test_filters_candidates(self):
        pci_stats_mock = mock.MagicMock()
        # simulate that only the second allocation candidate fits
        pci_stats_mock.support_requests.side_effect = [False, True, False]
        request = objects.InstancePCIRequest(
            count=1,
            spec=[{"vendor_id": "8086"}],
            request_id=uuids.req1,
        )
        requests = objects.InstancePCIRequests(requests=[request])
        spec_obj = objects.RequestSpec(pci_requests=requests)
        host = fakes.FakeHostState(
            "host1",
            "node1",
            attribute_dict={
                "pci_stats": pci_stats_mock,
                # simulate the placement returned 3 possible candidates
                "allocation_candidates": [
                    {"mappings": {f"{uuids.req1}-0": ["candidate_rp_1"]}},
                    {"mappings": {f"{uuids.req1}-0": ["candidate_rp_2"]}},
                    {"mappings": {f"{uuids.req1}-0": ["candidate_rp_3"]}},
                ],
            },
        )

        # run the filter and expect that it passes the host as there is at
        # least one viable candidate
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

        # also assert that the filter checked all three candidates
        pci_stats_mock.support_requests.assert_has_calls(
            [
                mock.call(
                    requests.requests,
                    provider_mapping={f"{uuids.req1}-0": ["candidate_rp_1"]},
                ),
                mock.call(
                    requests.requests,
                    provider_mapping={f"{uuids.req1}-0": ["candidate_rp_2"]},
                ),
                mock.call(
                    requests.requests,
                    provider_mapping={f"{uuids.req1}-0": ["candidate_rp_3"]},
                ),
            ]
        )
        # and also it reduced the candidates in the host state to the only
        # matching one
        self.assertEqual(1, len(host.allocation_candidates))
        self.assertEqual(
            {"mappings": {f"{uuids.req1}-0": ["candidate_rp_2"]}},
            host.allocation_candidates[0],
        )

    def test_filter_fails_if_no_matching_candidate_left(self):
        pci_stats_mock = mock.MagicMock()
        # simulate that the only candidate we have does not match
        pci_stats_mock.support_requests.side_effect = [False]
        request = objects.InstancePCIRequest(
            count=1,
            spec=[{"vendor_id": "8086"}],
            request_id=uuids.req1,
        )
        requests = objects.InstancePCIRequests(requests=[request])
        spec_obj = objects.RequestSpec(pci_requests=requests)
        host = fakes.FakeHostState(
            "host1",
            "node1",
            attribute_dict={
                "pci_stats": pci_stats_mock,
                # simulate the placement returned 3 possible candidates
                "allocation_candidates": [
                    {"mappings": {f"{uuids.req1}-0": ["candidate_rp_1"]}},
                ],
            },
        )

        # run the filter and expect that it fails the host as there is no
        # viable candidate left
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))

        # also assert that the filter checked our candidate
        pci_stats_mock.support_requests.assert_called_once_with(
            requests.requests,
            provider_mapping={f"{uuids.req1}-0": ["candidate_rp_1"]},
        )
        # and also it made the candidates list empty in the host state
        self.assertEqual(0, len(host.allocation_candidates))
