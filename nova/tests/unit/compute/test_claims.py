# Copyright (c) 2012 OpenStack Foundation
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

"""Tests for resource tracker claims."""

import uuid

import mock

from nova.compute import claims
from nova import context
from nova import exception
from nova import objects
from nova.pci import manager as pci_manager
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.pci import fakes as pci_fakes

_NODENAME = 'fake-node'


class FakeResourceHandler(object):
    test_called = False
    usage_is_instance = False

    def test_resources(self, usage, limits):
        self.test_called = True
        self.usage_is_itype = usage.get('name') == 'fakeitype'
        return []


class DummyTracker(object):
    icalled = False
    rcalled = False

    def __init__(self):
        self.new_pci_tracker()

    def abort_instance_claim(self, *args, **kwargs):
        self.icalled = True

    def drop_move_claim(self, *args, **kwargs):
        self.rcalled = True

    def new_pci_tracker(self):
        ctxt = context.RequestContext('testuser', 'testproject')
        self.pci_tracker = pci_manager.PciDevTracker(ctxt)


class ClaimTestCase(test.NoDBTestCase):

    def setUp(self):
        super(ClaimTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.instance = None
        self.resources = self._fake_resources()
        self.tracker = DummyTracker()
        self.empty_requests = objects.InstancePCIRequests(
            requests=[]
        )

    def _claim(self, limits=None, requests=None, **kwargs):
        numa_topology = kwargs.pop('numa_topology', None)
        instance = self._fake_instance(**kwargs)
        instance.flavor = self._fake_instance_type(**kwargs)
        if numa_topology:
            db_numa_topology = {
                    'id': 1, 'created_at': None, 'updated_at': None,
                    'deleted_at': None, 'deleted': None,
                    'instance_uuid': instance.uuid,
                    'numa_topology': numa_topology._to_json(),
                    'pci_requests': (requests or self.empty_requests).to_json()
                }
        else:
            db_numa_topology = None

        requests = requests or self.empty_requests

        @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid',
                    return_value=db_numa_topology)
        def get_claim(mock_extra_get):
            return claims.Claim(self.context, instance, _NODENAME,
                                self.tracker, self.resources, requests,
                                limits=limits)
        return get_claim()

    def _fake_instance(self, **kwargs):
        instance = {
            'uuid': str(uuid.uuid1()),
            'memory_mb': 1024,
            'root_gb': 10,
            'ephemeral_gb': 5,
            'vcpus': 1,
            'system_metadata': {},
            'numa_topology': None
        }
        instance.update(**kwargs)
        return fake_instance.fake_instance_obj(self.context, **instance)

    def _fake_instance_type(self, **kwargs):
        instance_type = {
            'id': 1,
            'name': 'fakeitype',
            'memory_mb': 1024,
            'vcpus': 1,
            'root_gb': 10,
            'ephemeral_gb': 5
        }
        instance_type.update(**kwargs)
        return objects.Flavor(**instance_type)

    def _fake_resources(self, values=None):
        resources = {
            'memory_mb': 2048,
            'memory_mb_used': 0,
            'free_ram_mb': 2048,
            'local_gb': 20,
            'local_gb_used': 0,
            'free_disk_gb': 20,
            'vcpus': 2,
            'vcpus_used': 0,
            'numa_topology': objects.NUMATopology(cells=[
                objects.NUMACell(
                    id=1,
                    cpuset=set([1, 2]),
                    pcpuset=set(),
                    memory=512,
                    memory_usage=0, cpu_usage=0,
                    mempages=[],
                    siblings=[set([1]), set([2])],
                    pinned_cpus=set()),
                objects.NUMACell(
                    id=2,
                    cpuset=set([3, 4]),
                    pcpuset=set(),
                    memory=512,
                    memory_usage=0,
                    cpu_usage=0,
                    mempages=[],
                    siblings=[set([3]), set([4])],
                    pinned_cpus=set())]
                )._to_json()
        }
        if values:
            resources.update(values)
        return objects.ComputeNode(**resources)

    @mock.patch('nova.pci.stats.PciDeviceStats.support_requests',
                return_value=True)
    def test_pci_pass(self, mock_pci_supports_requests):
        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': 'v', 'product_id': 'p'}])
        requests = objects.InstancePCIRequests(requests=[request])
        self._claim(requests=requests)
        mock_pci_supports_requests.assert_called_once_with([request])

    @mock.patch('nova.pci.stats.PciDeviceStats.support_requests',
                return_value=False)
    def test_pci_fail(self, mock_pci_supports_requests):
        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': 'v', 'product_id': 'p'}])
        requests = objects.InstancePCIRequests(requests=[request])
        self.assertRaisesRegex(
            exception.ComputeResourcesUnavailable,
            'Claim pci failed.',
            self._claim, requests=requests)
        mock_pci_supports_requests.assert_called_once_with([request])

    @mock.patch('nova.pci.stats.PciDeviceStats.support_requests')
    def test_pci_pass_no_requests(self, mock_pci_supports_requests):
        self._claim()
        self.assertFalse(mock_pci_supports_requests.called)

    def test_numa_topology_no_limit(self):
        huge_instance = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    id=1, cpuset=set([1, 2]), memory=512)])
        self._claim(numa_topology=huge_instance)

    def test_numa_topology_fails(self):
        huge_instance = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    id=1, cpuset=set([1, 2, 3, 4, 5]), memory=2048)])
        limit_topo = objects.NUMATopologyLimits(
            cpu_allocation_ratio=1, ram_allocation_ratio=1)
        self.assertRaises(exception.ComputeResourcesUnavailable,
                          self._claim,
                          limits={'numa_topology': limit_topo},
                          numa_topology=huge_instance)

    def test_numa_topology_passes(self):
        huge_instance = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    id=1, cpuset=set([1, 2]), memory=512)])
        limit_topo = objects.NUMATopologyLimits(
            cpu_allocation_ratio=1, ram_allocation_ratio=1)
        self._claim(limits={'numa_topology': limit_topo},
                    numa_topology=huge_instance)

    @pci_fakes.patch_pci_whitelist
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_numa_topology_with_pci(self, mock_get_by_instance):
        dev_dict = {
            'compute_node_id': 1,
            'address': 'a',
            'product_id': 'p',
            'vendor_id': 'v',
            'numa_node': 1,
            'dev_type': 'type-PCI',
            'parent_addr': 'a1',
            'status': 'available'}
        self.tracker.new_pci_tracker()
        self.tracker.pci_tracker._set_hvdevs([dev_dict])
        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': 'v', 'product_id': 'p'}])
        requests = objects.InstancePCIRequests(requests=[request])
        mock_get_by_instance.return_value = requests

        huge_instance = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    id=1, cpuset=set([1, 2]), memory=512)])

        self._claim(requests=requests, numa_topology=huge_instance)

    @pci_fakes.patch_pci_whitelist
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_numa_topology_with_pci_fail(self, mock_get_by_instance):
        dev_dict = {
            'compute_node_id': 1,
            'address': 'a',
            'product_id': 'p',
            'vendor_id': 'v',
            'numa_node': 1,
            'dev_type': 'type-PCI',
            'parent_addr': 'a1',
            'status': 'available'}
        dev_dict2 = {
            'compute_node_id': 1,
            'address': 'a',
            'product_id': 'p',
            'vendor_id': 'v',
            'numa_node': 2,
            'dev_type': 'type-PCI',
            'parent_addr': 'a1',
            'status': 'available'}
        self.tracker.new_pci_tracker()
        self.tracker.pci_tracker._set_hvdevs([dev_dict, dev_dict2])

        request = objects.InstancePCIRequest(count=2,
            spec=[{'vendor_id': 'v', 'product_id': 'p'}])
        requests = objects.InstancePCIRequests(requests=[request])
        mock_get_by_instance.return_value = requests

        huge_instance = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    id=1, cpuset=set([1, 2]), memory=512)])

        self.assertRaises(exception.ComputeResourcesUnavailable,
                          self._claim,
                          requests=requests,
                          numa_topology=huge_instance)

    @pci_fakes.patch_pci_whitelist
    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance')
    def test_numa_topology_with_pci_no_numa_info(self, mock_get_by_instance):
        dev_dict = {
            'compute_node_id': 1,
            'address': 'a',
            'product_id': 'p',
            'vendor_id': 'v',
            'numa_node': None,
            'dev_type': 'type-PCI',
            'parent_addr': 'a1',
            'status': 'available'}
        self.tracker.new_pci_tracker()
        self.tracker.pci_tracker._set_hvdevs([dev_dict])

        request = objects.InstancePCIRequest(count=1,
            spec=[{'vendor_id': 'v', 'product_id': 'p'}])
        requests = objects.InstancePCIRequests(requests=[request])
        mock_get_by_instance.return_value = requests

        huge_instance = objects.InstanceNUMATopology(
                cells=[objects.InstanceNUMACell(
                    id=1, cpuset=set([1, 2]), memory=512)])

        self._claim(requests=requests, numa_topology=huge_instance)

    def test_abort(self):
        claim = self._abort()
        self.assertTrue(claim.tracker.icalled)

    def _abort(self):
        claim = None
        try:
            with self._claim(memory_mb=4096) as claim:
                raise test.TestingException("abort")
        except test.TestingException:
            pass

        return claim


class MoveClaimTestCase(ClaimTestCase):

    def _claim(self, limits=None, requests=None,
               image_meta=None, **kwargs):
        instance_type = self._fake_instance_type(**kwargs)
        numa_topology = kwargs.pop('numa_topology', None)
        image_meta = image_meta or {}
        self.instance = self._fake_instance(**kwargs)
        self.instance.numa_topology = None
        if numa_topology:
            self.db_numa_topology = {
                    'id': 1, 'created_at': None, 'updated_at': None,
                    'deleted_at': None, 'deleted': None,
                    'instance_uuid': self.instance.uuid,
                    'numa_topology': numa_topology._to_json(),
                    'pci_requests': (requests or self.empty_requests).to_json()
                }
        else:
            self.db_numa_topology = None

        requests = requests or self.empty_requests

        @mock.patch('nova.virt.hardware.numa_get_constraints',
                    return_value=numa_topology)
        @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid',
                    return_value=self.db_numa_topology)
        def get_claim(mock_extra_get, mock_numa_get):
            return claims.MoveClaim(
                self.context, self.instance, _NODENAME, instance_type,
                image_meta, self.tracker, self.resources, requests,
                objects.Migration(migration_type='migration'), limits=limits)
        return get_claim()

    @mock.patch('nova.objects.Instance.drop_migration_context')
    def test_abort(self, mock_drop):
        claim = self._abort()
        self.assertTrue(claim.tracker.rcalled)
        mock_drop.assert_called_once_with()

    def test_image_meta(self):
        claim = self._claim()
        self.assertIsInstance(claim.image_meta, objects.ImageMeta)

    def test_image_meta_object_passed(self):
        image_meta = objects.ImageMeta()
        claim = self._claim(image_meta=image_meta)
        self.assertIsInstance(claim.image_meta, objects.ImageMeta)


class LiveMigrationClaimTestCase(ClaimTestCase):

    def test_live_migration_claim_bad_pci_request(self):
        instance_type = self._fake_instance_type()
        instance = self._fake_instance()
        instance.numa_topology = None
        self.assertRaisesRegex(
            exception.ComputeResourcesUnavailable,
            'PCI requests are not supported',
            claims.MoveClaim, self.context, instance, _NODENAME, instance_type,
            {}, self.tracker, self.resources,
            objects.InstancePCIRequests(requests=[
                objects.InstancePCIRequest(alias_name='fake-alias')]),
            objects.Migration(migration_type='live-migration'), None)

    def test_live_migration_page_size(self):
        instance_type = self._fake_instance_type()
        instance = self._fake_instance()
        instance.numa_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=1, cpuset=set([1, 2]),
                                            memory=512, pagesize=2)])
        claimed_numa_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=1, cpuset=set([1, 2]),
                                            memory=512, pagesize=1)])
        with mock.patch('nova.virt.hardware.numa_fit_instance_to_host',
                        return_value=claimed_numa_topology):
            self.assertRaisesRegex(
                exception.ComputeResourcesUnavailable,
                'Requested page size is different',
                claims.MoveClaim, self.context, instance, _NODENAME,
                instance_type, {}, self.tracker, self.resources,
                self.empty_requests,
                objects.Migration(migration_type='live-migration'), None)

    def test_claim_fails_page_size_not_called(self):
        instance_type = self._fake_instance_type()
        instance = self._fake_instance()
        # This topology cannot fit in self.resources (see _fake_resources())
        numa_topology = objects.InstanceNUMATopology(
            cells=[objects.InstanceNUMACell(id=1, cpuset=set([1, 2, 3]),
                                            memory=1024)])
        with test.nested(
            mock.patch('nova.virt.hardware.numa_get_constraints',
                        return_value=numa_topology),
            mock.patch(
                'nova.compute.claims.MoveClaim._test_live_migration_page_size'
        )) as (mock_test_numa, mock_test_page_size):
            self.assertRaisesRegex(
                exception.ComputeResourcesUnavailable,
                'Requested instance NUMA topology',
                claims.MoveClaim, self.context, instance, _NODENAME,
                instance_type, {}, self.tracker, self.resources,
                self.empty_requests,
                objects.Migration(migration_type='live-migration'), None)
            mock_test_page_size.assert_not_called()

    def test_live_migration_no_instance_numa_topology(self):
        instance_type = self._fake_instance_type()
        instance = self._fake_instance()
        instance.numa_topology = None
        claims.MoveClaim(
            self.context, instance, _NODENAME, instance_type, {}, self.tracker,
            self.resources, self.empty_requests,
            objects.Migration(migration_type='live-migration'), None)
