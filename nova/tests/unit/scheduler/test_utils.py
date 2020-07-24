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

import ddt
import mock
import os_resource_classes as orc
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
import six

from nova import context as nova_context
from nova import exception
from nova import objects
from nova.scheduler.client import report
from nova.scheduler import utils
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.scheduler import fakes


class FakeResourceRequest(object):
    """A fake of ``nova.scheduler.utils.ResourceRequest``.

    Allows us to assert that various properties of a real ResourceRequest
    object are set as we'd like them to be.
    """

    def __init__(self):
        self._rg_by_id = {}
        self._group_policy = None
        self._limit = 1000


class TestUtilsBase(test.NoDBTestCase):
    def setUp(self):
        super(TestUtilsBase, self).setUp()
        self.context = nova_context.get_admin_context()
        self.mock_host_manager = mock.Mock()

    def assertResourceRequestsEqual(self, expected, observed):
        self.assertEqual(expected._limit, observed._limit)
        self.assertEqual(expected._group_policy, observed._group_policy)
        ex_by_id = expected._rg_by_id
        ob_by_id = observed._rg_by_id
        self.assertEqual(set(ex_by_id), set(ob_by_id))
        for ident in ex_by_id:
            self.assertEqual(vars(ex_by_id[ident]), vars(ob_by_id[ident]))


@ddt.ddt
class TestUtils(TestUtilsBase):

    def _test_resources_from_request_spec(self, expected, flavor, image=None):
        if image is None:
            image = objects.ImageMeta(properties=objects.ImageMetaProps())
        fake_spec = objects.RequestSpec(flavor=flavor, image=image)
        resources = utils.resources_from_request_spec(
            self.context, fake_spec, self.mock_host_manager)
        self.assertResourceRequestsEqual(expected, resources)
        return resources

    def test_resources_from_request_spec_flavor_only(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0)
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor)

    def test_resources_from_request_spec_flavor_req_traits(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'trait:CUSTOM_FLAVOR_TRAIT': 'required'})
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            required_traits=set(['CUSTOM_FLAVOR_TRAIT'])
        )
        resources = self._test_resources_from_request_spec(
            expected_resources, flavor)
        expected_result = set(['CUSTOM_FLAVOR_TRAIT'])
        self.assertEqual(expected_result, resources.all_required_traits)

    def test_resources_from_request_spec_flavor_and_image_traits(self):
        image = objects.ImageMeta.from_dict({
            'properties': {
                'trait:CUSTOM_IMAGE_TRAIT1': 'required',
                'trait:CUSTOM_IMAGE_TRAIT2': 'required',
            },
            'id': 'c8b1790e-a07d-4971-b137-44f2432936cd',
        })
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={
                                    'trait:CUSTOM_FLAVOR_TRAIT': 'required',
                                    'trait:CUSTOM_IMAGE_TRAIT2': 'required'})
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            required_traits={
                # trait:CUSTOM_IMAGE_TRAIT2 is defined in both extra_specs and
                # image metadata. We get a union of both.
                'CUSTOM_IMAGE_TRAIT1',
                'CUSTOM_IMAGE_TRAIT2',
                'CUSTOM_FLAVOR_TRAIT',
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor,
                                               image)

    def test_resources_from_request_spec_flavor_forbidden_trait(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={
                                    'trait:CUSTOM_FLAVOR_TRAIT': 'forbidden'})
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            forbidden_traits={
                'CUSTOM_FLAVOR_TRAIT',
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor)

    def test_resources_from_request_spec_with_no_disk(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=0,
                                ephemeral_gb=0,
                                swap=0)
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor)

    def test_get_resources_from_request_spec_custom_resource_class(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={"resources:CUSTOM_TEST_CLASS": 1})
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 15,
                "CUSTOM_TEST_CLASS": 1,
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor)

    def test_get_resources_from_request_spec_override_flavor_amounts(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={
                                    "resources:VCPU": 99,
                                    "resources:MEMORY_MB": 99,
                                    "resources:DISK_GB": 99})
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                "VCPU": 99,
                "MEMORY_MB": 99,
                "DISK_GB": 99,
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor)

    def test_get_resources_from_request_spec_remove_flavor_amounts(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={
                                    "resources:VCPU": 0,
                                    "resources:DISK_GB": 0})
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                "MEMORY_MB": 1024,
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor)

    def test_get_resources_from_request_spec_vgpu(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=0,
                                swap=0,
                                extra_specs={
                                    "resources:VGPU": 1,
                                    "resources:VGPU_DISPLAY_HEAD": 1})
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                "VCPU": 1,
                "MEMORY_MB": 1024,
                "DISK_GB": 10,
                "VGPU": 1,
                "VGPU_DISPLAY_HEAD": 1,
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor)

    def test_get_resources_from_request_spec_bad_std_resource_class(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={
                                    "resources:DOESNT_EXIST": 0})
        fake_spec = objects.RequestSpec(flavor=flavor)
        with mock.patch("nova.objects.request_spec.LOG.warning") as mock_log:
            utils.resources_from_request_spec(
                self.context, fake_spec, self.mock_host_manager)
            mock_log.assert_called_once()
            args = mock_log.call_args[0]
            self.assertEqual(args[0], "Received an invalid ResourceClass "
                    "'%(key)s' in extra_specs.")
            self.assertEqual(args[1], {"key": "DOESNT_EXIST"})

    def test_get_resources_from_request_spec_granular(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=0, swap=0,
            extra_specs={'resources1:VGPU': '1',
                         'resources1:VGPU_DISPLAY_HEAD': '2',
                         # Replace
                         'resources3:VCPU': '2',
                         # Stay separate (don't sum)
                         'resources42:SRIOV_NET_VF': '1',
                         'resources24:SRIOV_NET_VF': '2',
                         # Ignore
                         'some:bogus': 'value',
                         # Custom in the unnumbered group (merge with DISK_GB)
                         'resources:CUSTOM_THING': '123',
                         # Traits make it through
                         'trait3:CUSTOM_SILVER': 'required',
                         'trait3:CUSTOM_GOLD': 'required',
                         # Delete standard
                         'resources86:MEMORY_MB': '0',
                         # Standard and custom zeroes don't make it through
                         'resources:IPV4_ADDRESS': '0',
                         'resources:CUSTOM_FOO': '0',
                         # Bogus values don't make it through
                         'resources1:MEMORY_MB': 'bogus',
                         'group_policy': 'none'})
        expected_resources = FakeResourceRequest()
        expected_resources._group_policy = 'none'
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'DISK_GB': 10,
                'CUSTOM_THING': 123,
            }
        )
        expected_resources._rg_by_id['1'] = objects.RequestGroup(
            requester_id='1',
            resources={
                'VGPU': 1,
                'VGPU_DISPLAY_HEAD': 2,
            }
        )
        expected_resources._rg_by_id['3'] = objects.RequestGroup(
            requester_id='3',
            resources={
                'VCPU': 2,
            },
            required_traits={
                'CUSTOM_GOLD',
                'CUSTOM_SILVER',
            }
        )
        expected_resources._rg_by_id['24'] = objects.RequestGroup(
            requester_id='24',
            resources={
                'SRIOV_NET_VF': 2,
            },
        )
        expected_resources._rg_by_id['42'] = objects.RequestGroup(
            requester_id='42',
            resources={
                'SRIOV_NET_VF': 1,
            }
        )

        rr = self._test_resources_from_request_spec(expected_resources, flavor)
        expected_querystring = (
            'group_policy=none&'
            'limit=1000&'
            'required3=CUSTOM_GOLD%2CCUSTOM_SILVER&'
            'resources=CUSTOM_THING%3A123%2CDISK_GB%3A10&'
            'resources1=VGPU%3A1%2CVGPU_DISPLAY_HEAD%3A2&'
            'resources24=SRIOV_NET_VF%3A2&'
            'resources3=VCPU%3A2&'
            'resources42=SRIOV_NET_VF%3A1'
        )
        self.assertEqual(expected_querystring, rr.to_querystring())

    def test_all_required_traits(self):
        flavor = objects.Flavor(vcpus=1,
                        memory_mb=1024,
                        root_gb=10,
                        ephemeral_gb=5,
                        swap=0,
                        extra_specs={
                            'trait:HW_CPU_X86_SSE': 'required',
                            'trait:HW_CPU_X86_AVX': 'required',
                            'trait:HW_CPU_X86_AVX2': 'forbidden'})
        expected_resources = FakeResourceRequest()
        expected_resources._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            required_traits={
                'HW_CPU_X86_SSE',
                'HW_CPU_X86_AVX'
            },
            forbidden_traits={
                'HW_CPU_X86_AVX2'
            }
        )
        resource = self._test_resources_from_request_spec(expected_resources,
                                                          flavor)
        expected_result = {'HW_CPU_X86_SSE', 'HW_CPU_X86_AVX'}
        self.assertEqual(expected_result,
                         resource.all_required_traits)

    def test_resources_from_request_spec_aggregates(self):
        destination = objects.Destination()
        flavor = objects.Flavor(vcpus=1, memory_mb=1024,
                                root_gb=1, ephemeral_gb=0,
                                swap=0)
        reqspec = objects.RequestSpec(flavor=flavor,
                                      requested_destination=destination)

        destination.require_aggregates(['foo', 'bar'])
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual([['foo', 'bar']],
                         req.get_request_group(None).aggregates)

        destination.require_aggregates(['baz'])
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual([['foo', 'bar'], ['baz']],
                         req.get_request_group(None).aggregates)

    def test_resources_from_request_spec_no_aggregates(self):
        flavor = objects.Flavor(vcpus=1, memory_mb=1024,
                                root_gb=1, ephemeral_gb=0,
                                swap=0)
        reqspec = objects.RequestSpec(flavor=flavor)

        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual([], req.get_request_group(None).aggregates)

        reqspec.requested_destination = None
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual([], req.get_request_group(None).aggregates)

        reqspec.requested_destination = objects.Destination()
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual([], req.get_request_group(None).aggregates)

        reqspec.requested_destination.aggregates = None
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual([], req.get_request_group(None).aggregates)

    def test_resources_from_request_spec_forbidden_aggregates(self):
        flavor = objects.Flavor(vcpus=1, memory_mb=1024,
                                root_gb=1, ephemeral_gb=0,
                                swap=0)
        reqspec = objects.RequestSpec(
            flavor=flavor,
            requested_destination=objects.Destination(
                forbidden_aggregates=set(['foo', 'bar'])))

        req = utils.resources_from_request_spec(self.context, reqspec,
                                                self.mock_host_manager)
        self.assertEqual(set(['foo', 'bar']),
                         req.get_request_group(None).forbidden_aggregates)

    def test_resources_from_request_spec_no_forbidden_aggregates(self):
        flavor = objects.Flavor(vcpus=1, memory_mb=1024,
                                root_gb=1, ephemeral_gb=0,
                                swap=0)
        reqspec = objects.RequestSpec(flavor=flavor)

        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual(set([]), req.get_request_group(None).
                         forbidden_aggregates)

        reqspec.requested_destination = None
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual(set([]), req.get_request_group(None).
                         forbidden_aggregates)

        reqspec.requested_destination = objects.Destination()
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual(set([]), req.get_request_group(None).
                         forbidden_aggregates)

        reqspec.requested_destination.forbidden_aggregates = None
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual(set([]), req.get_request_group(None).
                         forbidden_aggregates)

    def test_process_extra_specs_granular_called(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={"resources:CUSTOM_TEST_CLASS": 1})
        fake_spec = objects.RequestSpec(flavor=flavor)
        # just call this to make sure things don't explode
        utils.resources_from_request_spec(
            self.context, fake_spec, self.mock_host_manager)

    def test_process_extra_specs_granular_not_called(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0)
        fake_spec = objects.RequestSpec(flavor=flavor)
        # just call this to make sure things don't explode
        utils.resources_from_request_spec(
            self.context, fake_spec, self.mock_host_manager)

    def test_process_missing_extra_specs_value(self):
        flavor = objects.Flavor(
                vcpus=1,
                memory_mb=1024,
                root_gb=10,
                ephemeral_gb=5,
                swap=0,
                extra_specs={"resources:CUSTOM_TEST_CLASS": ""})
        fake_spec = objects.RequestSpec(flavor=flavor)
        # just call this to make sure things don't explode
        utils.resources_from_request_spec(
                self.context, fake_spec, self.mock_host_manager)

    def test_process_no_force_hosts_or_force_nodes(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rr = self._test_resources_from_request_spec(expected, flavor)
        expected_querystring = (
            'limit=1000&'
            'resources=DISK_GB%3A15%2CMEMORY_MB%3A1024%2CVCPU%3A1'
        )
        self.assertEqual(expected_querystring, rr.to_querystring())

    def test_process_use_force_nodes(self):
        fake_nodes = objects.ComputeNodeList(objects=[
            objects.ComputeNode(host='fake-host',
                                uuid='12345678-1234-1234-1234-123456789012',
                                hypervisor_hostname='test')])
        self.mock_host_manager.get_compute_nodes_by_host_or_node.\
            return_value = fake_nodes
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        fake_spec = objects.RequestSpec(flavor=flavor, force_nodes=['test'])
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            in_tree='12345678-1234-1234-1234-123456789012',
        )
        resources = utils.resources_from_request_spec(
                self.context, fake_spec, self.mock_host_manager)
        self.assertResourceRequestsEqual(expected, resources)
        expected_querystring = (
            'in_tree=12345678-1234-1234-1234-123456789012&'
            'limit=1000&resources=DISK_GB%3A15%2CMEMORY_MB%3A1024%2CVCPU%3A1')
        self.assertEqual(expected_querystring, resources.to_querystring())
        self.mock_host_manager.get_compute_nodes_by_host_or_node.\
            assert_called_once_with(self.context, None, 'test', cell=None)

    def test_process_use_force_hosts(self):
        fake_nodes = objects.ComputeNodeList(objects=[
            objects.ComputeNode(host='test',
                                uuid='12345678-1234-1234-1234-123456789012')
            ])
        self.mock_host_manager.get_compute_nodes_by_host_or_node.\
            return_value = fake_nodes
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        fake_spec = objects.RequestSpec(flavor=flavor, force_hosts=['test'])
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            in_tree='12345678-1234-1234-1234-123456789012',
        )
        resources = utils.resources_from_request_spec(
                self.context, fake_spec, self.mock_host_manager)
        self.assertResourceRequestsEqual(expected, resources)
        expected_querystring = (
            'in_tree=12345678-1234-1234-1234-123456789012&'
            'limit=1000&resources=DISK_GB%3A15%2CMEMORY_MB%3A1024%2CVCPU%3A1')
        self.assertEqual(expected_querystring, resources.to_querystring())
        self.mock_host_manager.get_compute_nodes_by_host_or_node.\
            assert_called_once_with(self.context, 'test', None, cell=None)

    def test_process_use_force_hosts_multinodes_found(self):
        fake_nodes = objects.ComputeNodeList(objects=[
            objects.ComputeNode(host='test',
                                uuid='12345678-1234-1234-1234-123456789012'),
            objects.ComputeNode(host='test',
                                uuid='87654321-4321-4321-4321-210987654321'),
            ])
        self.mock_host_manager.get_compute_nodes_by_host_or_node.\
            return_value = fake_nodes
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        fake_spec = objects.RequestSpec(flavor=flavor, force_hosts=['test'])
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        # Validate that the limit is unset
        expected._limit = None

        resources = utils.resources_from_request_spec(
                self.context, fake_spec, self.mock_host_manager)
        self.assertResourceRequestsEqual(expected, resources)
        # Validate that the limit is unset
        expected_querystring = (
            'resources=DISK_GB%3A15%2CMEMORY_MB%3A1024%2CVCPU%3A1')
        self.assertEqual(expected_querystring, resources.to_querystring())
        self.mock_host_manager.get_compute_nodes_by_host_or_node.\
            assert_called_once_with(self.context, 'test', None, cell=None)

    def test_process_use_requested_destination(self):
        fake_cell = objects.CellMapping(uuid=uuids.cell1, name='foo')
        destination = objects.Destination(
            host='fake-host', node='fake-node', cell=fake_cell)
        fake_nodes = objects.ComputeNodeList(objects=[
            objects.ComputeNode(host='fake-host',
                                uuid='12345678-1234-1234-1234-123456789012',
                                hypervisor_hostname='fake-node')
            ])
        self.mock_host_manager.get_compute_nodes_by_host_or_node.\
            return_value = fake_nodes
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        fake_spec = objects.RequestSpec(
            flavor=flavor, requested_destination=destination)
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            in_tree='12345678-1234-1234-1234-123456789012',
        )
        resources = utils.resources_from_request_spec(
                self.context, fake_spec, self.mock_host_manager)
        self.assertResourceRequestsEqual(expected, resources)
        expected_querystring = (
            'in_tree=12345678-1234-1234-1234-123456789012&'
            'limit=1000&resources=DISK_GB%3A15%2CMEMORY_MB%3A1024%2CVCPU%3A1')
        self.assertEqual(expected_querystring, resources.to_querystring())
        self.mock_host_manager.get_compute_nodes_by_host_or_node.\
            assert_called_once_with(
                self.context, 'fake-host', 'fake-node', cell=fake_cell)

    def test_resources_from_request_spec_having_requested_resources(self):
        flavor = objects.Flavor(
                vcpus=1,
                memory_mb=1024,
                root_gb=10,
                ephemeral_gb=5,
                swap=0)
        rg1 = objects.RequestGroup(
            resources={'CUSTOM_FOO': 1}, requester_id='The-first-group')

        # Leave requester_id out to trigger ValueError
        rg2 = objects.RequestGroup(required_traits={'CUSTOM_BAR'})

        reqspec = objects.RequestSpec(flavor=flavor,
                                      requested_resources=[rg1, rg2])

        self.assertRaises(
            ValueError,
            utils.resources_from_request_spec,
            self.context, reqspec, self.mock_host_manager)

        # Set conflicting requester_id
        rg2.requester_id = 'The-first-group'
        self.assertRaises(
            exception.RequestGroupSuffixConflict,
            utils.resources_from_request_spec,
            self.context, reqspec, self.mock_host_manager)

        # Good path: nonempty non-conflicting requester_id
        rg2.requester_id = 'The-second-group'

        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual({'MEMORY_MB': 1024, 'DISK_GB': 15, 'VCPU': 1},
                         req.get_request_group(None).resources)
        self.assertIs(rg1, req.get_request_group('The-first-group'))
        self.assertIs(rg2, req.get_request_group('The-second-group'))
        # Make sure those ended up as suffixes correctly
        qs = req.to_querystring()
        self.assertIn('resourcesThe-first-group=CUSTOM_FOO%3A1', qs)
        self.assertIn('requiredThe-second-group=CUSTOM_BAR', qs)

    def test_resources_from_request_spec_requested_resources_unfilled(self):
        flavor = objects.Flavor(
                vcpus=1,
                memory_mb=1024,
                root_gb=10,
                ephemeral_gb=5,
                swap=0)
        reqspec = objects.RequestSpec(flavor=flavor)
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual({'MEMORY_MB': 1024, 'DISK_GB': 15, 'VCPU': 1},
                         req.get_request_group(None).resources)
        self.assertEqual(1, len(list(req._rg_by_id)))

        reqspec = objects.RequestSpec(flavor=flavor, requested_resources=[])
        req = utils.resources_from_request_spec(
                self.context, reqspec, self.mock_host_manager)
        self.assertEqual({'MEMORY_MB': 1024, 'DISK_GB': 15, 'VCPU': 1},
                         req.get_request_group(None).resources)
        self.assertEqual(1, len(list(req._rg_by_id)))

    @ddt.data(
        # Test single hint that we are checking for.
        {'group': [uuids.fake]},
        # Test hint we care about and some other random hint.
        {'same_host': [uuids.fake], 'fake-hint': ['fake-value']},
        # Test multiple hints we are checking for.
        {'same_host': [uuids.server1], 'different_host': [uuids.server2]})
    def test_resources_from_request_spec_no_limit_based_on_hint(self, hints):
        """Tests that there is no limit applied to the
        GET /allocation_candidates query string if a given scheduler hint
        is in the request spec.
        """
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        fake_spec = objects.RequestSpec(
            flavor=flavor, scheduler_hints=hints)
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        expected._limit = None
        resources = utils.resources_from_request_spec(
            self.context, fake_spec, self.mock_host_manager)
        self.assertResourceRequestsEqual(expected, resources)
        expected_querystring = (
            'resources=DISK_GB%3A15%2CMEMORY_MB%3A1024%2CVCPU%3A1'
        )
        self.assertEqual(expected_querystring, resources.to_querystring())

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=False)
    def test_resources_from_flavor_no_bfv(self, mock_is_bfv):
        flavor = objects.Flavor(vcpus=1, memory_mb=1024, root_gb=10,
                                ephemeral_gb=5, swap=1024,
                                extra_specs={})
        instance = objects.Instance()
        expected = {
            'VCPU': 1,
            'MEMORY_MB': 1024,
            'DISK_GB': 16,
        }
        actual = utils.resources_from_flavor(instance, flavor)
        self.assertEqual(expected, actual)

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                return_value=True)
    def test_resources_from_flavor_bfv(self, mock_is_bfv):
        flavor = objects.Flavor(vcpus=1, memory_mb=1024, root_gb=10,
                                ephemeral_gb=5, swap=1024,
                                extra_specs={})
        instance = objects.Instance()
        expected = {
            'VCPU': 1,
            'MEMORY_MB': 1024,
            'DISK_GB': 6,  # No root disk...
        }
        actual = utils.resources_from_flavor(instance, flavor)
        self.assertEqual(expected, actual)

    @mock.patch('nova.compute.utils.is_volume_backed_instance',
                new=mock.Mock(return_value=False))
    def test_resources_from_flavor_with_override(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=1024,
            extra_specs={
                # Replace
                'resources:VCPU': '2',
                # Sum up
                'resources42:SRIOV_NET_VF': '1',
                'resources24:SRIOV_NET_VF': '2',
                # Ignore
                'some:bogus': 'value',
                # Custom
                'resources:CUSTOM_THING': '123',
                # Ignore
                'trait:CUSTOM_GOLD': 'required',
                # Delete standard
                'resources86:MEMORY_MB': 0,
                # Standard and custom zeroes don't make it through
                'resources:IPV4_ADDRESS': 0,
                'resources:CUSTOM_FOO': 0,
                'group_policy': 'none'})
        instance = objects.Instance()
        expected = {
            'VCPU': 2,
            'DISK_GB': 16,
            'CUSTOM_THING': 123,
            'SRIOV_NET_VF': 3,
        }
        actual = utils.resources_from_flavor(instance, flavor)
        self.assertEqual(expected, actual)

    def test_resource_request_init(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0)

        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_init_with_extra_specs(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'resources:VCPU': '2',
                'resources:MEMORY_MB': '2048',
                'trait:HW_CPU_X86_AVX': 'required',
                # Key skipped because no colons
                'nocolons': '42',
                'trait:CUSTOM_MAGIC': 'required',
                'trait:CUSTOM_BRONZE': 'forbidden',
                # Resource skipped because invalid resource class name
                'resources86:CUTSOM_MISSPELLED': '86',
                'resources1:SRIOV_NET_VF': '1',
                # Resource skipped because non-int-able value
                'resources86:CUSTOM_FOO': 'seven',
                # Resource skipped because negative value
                'resources86:CUSTOM_NEGATIVE': '-7',
                'resources1:IPV4_ADDRESS': '1',
                # Trait skipped because unsupported value
                'trait86:CUSTOM_GOLD': 'preferred',
                'trait1:CUSTOM_PHYSNET_NET1': 'required',
                'trait1:CUSTOM_PHYSNET_NET2': 'forbidden',
                'resources2:SRIOV_NET_VF': '1',
                'resources2:IPV4_ADDRESS': '2',
                'trait2:CUSTOM_PHYSNET_NET2': 'required',
                'trait2:HW_NIC_ACCEL_SSL': 'required',
                # Groupings that don't quite match the patterns are ignored
                'resources_*5:SRIOV_NET_VF': '7',
                'traitFoo$:HW_NIC_ACCEL_SSL': 'required',
                # Solo resource, no corresponding traits
                'resources3:DISK_GB': '5',
                'group_policy': 'isolate',
            })

        expected = FakeResourceRequest()
        expected._group_policy = 'isolate'
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 2,
                'MEMORY_MB': 2048,
            },
            required_traits={
                'HW_CPU_X86_AVX',
                'CUSTOM_MAGIC',
            },
            forbidden_traits={
                'CUSTOM_BRONZE',
            },
        )
        expected._rg_by_id['1'] = objects.RequestGroup(
            requester_id='1',
            resources={
                'SRIOV_NET_VF': 1,
                'IPV4_ADDRESS': 1,
            },
            required_traits={
                'CUSTOM_PHYSNET_NET1',
            },
            forbidden_traits={
                'CUSTOM_PHYSNET_NET2',
            },
        )
        expected._rg_by_id['2'] = objects.RequestGroup(
            requester_id='2',
            resources={
                'SRIOV_NET_VF': 1,
                'IPV4_ADDRESS': 2,
            },
            required_traits={
                'CUSTOM_PHYSNET_NET2',
                'HW_NIC_ACCEL_SSL',
            }
        )
        expected._rg_by_id['3'] = objects.RequestGroup(
            requester_id='3',
            resources={
                'DISK_GB': 5,
            }
        )

        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)
        expected_querystring = (
            'group_policy=isolate&'
            'limit=1000&'
            'required=CUSTOM_MAGIC%2CHW_CPU_X86_AVX%2C%21CUSTOM_BRONZE&'
            'required1=CUSTOM_PHYSNET_NET1%2C%21CUSTOM_PHYSNET_NET2&'
            'required2=CUSTOM_PHYSNET_NET2%2CHW_NIC_ACCEL_SSL&'
            'resources=MEMORY_MB%3A2048%2CVCPU%3A2&'
            'resources1=IPV4_ADDRESS%3A1%2CSRIOV_NET_VF%3A1&'
            'resources2=IPV4_ADDRESS%3A2%2CSRIOV_NET_VF%3A1&'
            'resources3=DISK_GB%3A5'
        )
        self.assertEqual(expected_querystring, rr.to_querystring())

    def _test_resource_request_init_with_legacy_extra_specs(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'hw:cpu_policy': 'dedicated',
                'hw:cpu_thread_policy': 'isolate',
                'hw:emulator_threads_policy': 'isolate',
            })

        return objects.RequestSpec(flavor=flavor, is_bfv=False)

    def test_resource_request_init_with_legacy_extra_specs(self):
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                # we should have two PCPUs, one due to hw:cpu_policy and the
                # other due to hw:cpu_thread_policy
                'PCPU': 2,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            forbidden_traits={
                # we should forbid hyperthreading due to hw:cpu_thread_policy
                'HW_CPU_HYPERTHREADING',
            },
        )
        rs = self._test_resource_request_init_with_legacy_extra_specs()
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)
        self.assertTrue(rr.cpu_pinning_requested)

    def test_resource_request_init_with_legacy_extra_specs_no_translate(self):
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                # we should have a VCPU despite hw:cpu_policy because
                # enable_pinning_translate=False
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            # we should not require hyperthreading despite hw:cpu_thread_policy
            # because enable_pinning_translate=False
            forbidden_traits=set(),
        )
        rs = self._test_resource_request_init_with_legacy_extra_specs()
        rr = utils.ResourceRequest(rs, enable_pinning_translate=False)
        self.assertResourceRequestsEqual(expected, rr)
        self.assertFalse(rr.cpu_pinning_requested)

    def test_resource_request_init_with_image_props(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0)
        image = objects.ImageMeta.from_dict({
            'properties': {
                'trait:CUSTOM_TRUSTED': 'required',
            },
            'id': 'c8b1790e-a07d-4971-b137-44f2432936cd'
        })

        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            required_traits={
                'CUSTOM_TRUSTED',
            }
        )
        rs = objects.RequestSpec(flavor=flavor, image=image, is_bfv=False)
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def _test_resource_request_init_with_legacy_image_props(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0)
        image = objects.ImageMeta.from_dict({
            'properties': {
                'hw_cpu_policy': 'dedicated',
                'hw_cpu_thread_policy': 'require',
            },
            'id': 'c8b1790e-a07d-4971-b137-44f2432936cd',
        })
        return objects.RequestSpec(flavor=flavor, image=image, is_bfv=False)

    def test_resource_request_init_with_legacy_image_props(self):
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                # we should have a PCPU due to hw_cpu_policy
                'PCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            required_traits={
                # we should require hyperthreading due to hw_cpu_thread_policy
                'HW_CPU_HYPERTHREADING',
            },
        )
        rs = self._test_resource_request_init_with_legacy_image_props()
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)
        self.assertTrue(rr.cpu_pinning_requested)

    def test_resource_request_init_with_legacy_image_props_no_translate(self):
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                # we should have a VCPU despite hw_cpu_policy because
                # enable_pinning_translate=False
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            # we should not require hyperthreading despite hw_cpu_thread_policy
            # because enable_pinning_translate=False
            required_traits=set(),
        )
        rs = self._test_resource_request_init_with_legacy_image_props()
        rr = utils.ResourceRequest(rs, enable_pinning_translate=False)
        self.assertResourceRequestsEqual(expected, rr)
        self.assertFalse(rr.cpu_pinning_requested)

    def _test_resource_request_init_with_mixed_cpus(self, extra_specs):
        flavor = objects.Flavor(
            vcpus=4, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs=extra_specs)
        rs = objects.RequestSpec(flavor=flavor)
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'PCPU': 2,
                'VCPU': 2,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            required_traits=set(),
        )
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_init_with_mixed_cpus_dedicated(self):
        """Ensure the mixed instance, which is generated through
        'hw:cpu_dedicated_mask' extra spec, properly requests the PCPU, VCPU,
        MEMORY_MB and DISK_GB resources.
        """
        extra_specs = {
            'hw:cpu_policy': 'mixed',
            'hw:cpu_dedicated_mask': '2,3'
        }
        self._test_resource_request_init_with_mixed_cpus(extra_specs)

    def test_resource_request_init_with_mixed_cpus_realtime(self):
        """Ensure the mixed instance, which is generated through real-time CPU
        interface, properly requests the PCPU, VCPU, MEMORY_BM and DISK_GB
        resources.
        """
        extra_specs = {
            'hw:cpu_policy': 'mixed',
            "hw:cpu_realtime": "yes",
            "hw:cpu_realtime_mask": '2,3'
        }
        self._test_resource_request_init_with_mixed_cpus(extra_specs)

    def _test_resource_request_init_with_mixed_cpus_iso_emu(self, extra_specs):
        flavor = objects.Flavor(
            vcpus=4, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs=extra_specs)
        rs = objects.RequestSpec(flavor=flavor)
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                # An extra PCPU resource is requested due to 'ISOLATE' emulator
                # thread policy.
                'PCPU': 3,
                'VCPU': 2,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
            required_traits=set(),
        )
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_init_with_mixed_cpus_iso_emu_realtime(self):
        """Ensure the mixed instance, which is generated through the
        'hw:cpu_dedicated_mask' extra spec, specs, properly requests the PCPU,
        VCPU, MEMORY_MB, DISK_GB resources, ensure an extra PCPU resource is
        requested due to a ISOLATE emulator thread policy.
        """
        extra_specs = {
            'hw:cpu_policy': 'mixed',
            'hw:cpu_dedicated_mask': '2,3',
            'hw:emulator_threads_policy': 'isolate',
        }
        self._test_resource_request_init_with_mixed_cpus_iso_emu(extra_specs)

    def test_resource_request_init_with_mixed_cpus_iso_emu_dedicated(self):
        """Ensure the mixed instance, which is generated through realtime extra
        specs, properly requests the PCPU, VCPU, MEMORY_MB, DISK_GB resources,
        ensure an extra PCPU resource is requested due to a ISOLATE emulator
        thread policy.
        """
        extra_specs = {
            'hw:cpu_policy': 'mixed',
            "hw:cpu_realtime": "yes",
            "hw:cpu_realtime_mask": '2,3',
            'hw:emulator_threads_policy': 'isolate',
        }
        self._test_resource_request_init_with_mixed_cpus_iso_emu(extra_specs)

    def test_resource_request_init_is_bfv(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=1555)

        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                # this should only include the ephemeral and swap disk, and the
                # latter should be converted from MB to GB and rounded up
                'DISK_GB': 7,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, is_bfv=True)
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_with_vpmems(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'hw:pmem': '4GB, 4GB,SMALL'})

        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
                'CUSTOM_PMEM_NAMESPACE_4GB': 2,
                'CUSTOM_PMEM_NAMESPACE_SMALL': 1
            },
        )
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_with_vtpm_1_2(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'hw:tpm_version': '1.2', 'hw:tpm_model': 'tpm-tis'},
        )
        image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_tpm_version='1.2',
                hw_tpm_model='tpm-tis',
            )
        )
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            required_traits={'COMPUTE_SECURITY_TPM_1_2'},
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, image=image, is_bfv=False)
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_with_vtpm_2_0(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'hw:tpm_version': '2.0', 'hw:tpm_model': 'tpm-crb'},
        )
        image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_tpm_version='2.0',
                hw_tpm_model='tpm-crb',
            )
        )
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            required_traits={'COMPUTE_SECURITY_TPM_2_0'},
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, image=image, is_bfv=False)
        rr = utils.ResourceRequest(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_add_group_inserts_the_group(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0)
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        req = utils.ResourceRequest(rs)
        rg1 = objects.RequestGroup(requester_id='foo',
                                   required_traits={'CUSTOM_FOO'})
        req._add_request_group(rg1)
        rg2 = objects.RequestGroup(requester_id='bar',
                                   forbidden_traits={'CUSTOM_BAR'})
        req._add_request_group(rg2)
        self.assertIs(rg1, req.get_request_group('foo'))
        self.assertIs(rg2, req.get_request_group('bar'))

    def test_empty_groups_forbidden(self):
        """Not allowed to add premade RequestGroup without resources/traits/
        aggregates.
        """
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0)
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        req = utils.ResourceRequest(rs)
        rg = objects.RequestGroup(requester_id='foo')
        self.assertRaises(ValueError, req._add_request_group, rg)

    def test_claim_resources_on_destination_no_source_allocations(self):
        """Tests the negative scenario where the instance does not have
        allocations in Placement on the source compute node so no claim is
        attempted on the destination compute node.
        """
        reportclient = report.SchedulerReportClient()
        instance = fake_instance.fake_instance_obj(self.context)
        source_node = objects.ComputeNode(
            uuid=uuids.source_node, host=instance.host)
        dest_node = objects.ComputeNode(uuid=uuids.dest_node, host='dest-host')

        @mock.patch.object(reportclient,
                           'get_allocs_for_consumer',
                           return_value={})
        @mock.patch.object(reportclient,
                           'claim_resources',
                           new_callable=mock.NonCallableMock)
        def test(mock_claim, mock_get_allocs):
            ex = self.assertRaises(
                exception.ConsumerAllocationRetrievalFailed,
                utils.claim_resources_on_destination,
                self.context, reportclient, instance, source_node, dest_node)
            mock_get_allocs.assert_called_once_with(
                self.context, instance.uuid)
            self.assertIn(
                'Expected to find allocations for source node resource '
                'provider %s' % source_node.uuid, six.text_type(ex))

        test()

    def test_claim_resources_on_destination_claim_fails(self):
        """Tests the negative scenario where the resource allocation claim
        on the destination compute node fails, resulting in an error.
        """
        reportclient = report.SchedulerReportClient()
        instance = fake_instance.fake_instance_obj(self.context)
        source_node = objects.ComputeNode(
            uuid=uuids.source_node, host=instance.host)
        dest_node = objects.ComputeNode(uuid=uuids.dest_node, host='dest-host')
        source_res_allocs = {
            'allocations': {
                uuids.source_node: {
                    'resources': {
                        'VCPU': instance.vcpus,
                        'MEMORY_MB': instance.memory_mb,
                        # This would really include ephemeral and swap too but
                        # we're lazy.
                        'DISK_GB': instance.root_gb
                    }
                }
            },
            'consumer_generation': 1,
            'project_id': uuids.project_id,
            'user_id': uuids.user_id
        }
        dest_alloc_request = {
            'allocations': {
                uuids.dest_node: {
                    'resources': {
                        'VCPU': instance.vcpus,
                        'MEMORY_MB': instance.memory_mb,
                        'DISK_GB': instance.root_gb
                    }
                }
            },
        }

        @mock.patch.object(reportclient,
                           'get_allocs_for_consumer',
                           return_value=source_res_allocs)
        @mock.patch.object(reportclient,
                           'claim_resources', return_value=False)
        def test(mock_claim, mock_get_allocs):
            # NOTE(danms): Don't pass source_node_allocations here to test
            # that they are fetched if needed.
            self.assertRaises(exception.NoValidHost,
                              utils.claim_resources_on_destination,
                              self.context, reportclient, instance,
                              source_node, dest_node)
            mock_get_allocs.assert_called_once_with(
                self.context, instance.uuid)
            mock_claim.assert_called_once_with(
                self.context, instance.uuid, dest_alloc_request,
                instance.project_id, instance.user_id,
                allocation_request_version='1.28', consumer_generation=1)

        test()

    def test_claim_resources_on_destination(self):
        """Happy path test where everything is successful."""
        reportclient = report.SchedulerReportClient()
        instance = fake_instance.fake_instance_obj(self.context)
        source_node = objects.ComputeNode(
            uuid=uuids.source_node, host=instance.host)
        dest_node = objects.ComputeNode(uuid=uuids.dest_node, host='dest-host')
        source_res_allocs = {
            uuids.source_node: {
                'resources': {
                    'VCPU': instance.vcpus,
                    'MEMORY_MB': instance.memory_mb,
                    # This would really include ephemeral and swap too but
                    # we're lazy.
                    'DISK_GB': instance.root_gb
                }
            }
        }
        dest_alloc_request = {
            'allocations': {
                uuids.dest_node: {
                    'resources': {
                        'VCPU': instance.vcpus,
                        'MEMORY_MB': instance.memory_mb,
                        'DISK_GB': instance.root_gb
                    }
                }
            },
        }

        @mock.patch.object(reportclient,
                           'get_allocs_for_consumer')
        @mock.patch.object(reportclient,
                           'claim_resources', return_value=True)
        def test(mock_claim, mock_get_allocs):
            utils.claim_resources_on_destination(
                self.context, reportclient, instance, source_node, dest_node,
                source_res_allocs, consumer_generation=None)
            self.assertFalse(mock_get_allocs.called)
            mock_claim.assert_called_once_with(
                self.context, instance.uuid, dest_alloc_request,
                instance.project_id, instance.user_id,
                allocation_request_version='1.28', consumer_generation=None)

        test()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    @mock.patch('nova.scheduler.utils.request_is_rebuild')
    def test_claim_resources(self, mock_is_rebuild, mock_client):
        """Tests that when claim_resources() is called, that we appropriately
        call the placement client to claim resources for the instance.
        """
        mock_is_rebuild.return_value = False
        ctx = nova_context.RequestContext(user_id=uuids.user_id)
        spec_obj = objects.RequestSpec(project_id=uuids.project_id)
        instance_uuid = uuids.instance
        alloc_req = mock.sentinel.alloc_req
        mock_client.claim_resources.return_value = True

        res = utils.claim_resources(ctx, mock_client, spec_obj, instance_uuid,
                alloc_req)

        mock_client.claim_resources.assert_called_once_with(
            ctx, uuids.instance, mock.sentinel.alloc_req, uuids.project_id,
            uuids.user_id, allocation_request_version=None,
            consumer_generation=None)
        self.assertTrue(res)

        # Now do it again but with RequestSpec.user_id set.
        spec_obj.user_id = uuids.spec_user_id
        mock_client.reset_mock()
        utils.claim_resources(ctx, mock_client, spec_obj, instance_uuid,
                              alloc_req)
        mock_client.claim_resources.assert_called_once_with(
            ctx, uuids.instance, mock.sentinel.alloc_req, uuids.project_id,
            uuids.spec_user_id, allocation_request_version=None,
            consumer_generation=None)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    @mock.patch('nova.scheduler.utils.request_is_rebuild')
    def test_claim_resources_for_policy_check(self, mock_is_rebuild,
            mock_client):
        mock_is_rebuild.return_value = True
        ctx = mock.Mock(user_id=uuids.user_id)
        res = utils.claim_resources(ctx, None, mock.sentinel.spec_obj,
                mock.sentinel.instance_uuid, [])
        self.assertTrue(res)
        mock_is_rebuild.assert_called_once_with(mock.sentinel.spec_obj)
        self.assertFalse(mock_client.claim_resources.called)

    def test_get_weight_multiplier(self):
        host_attr = {'vcpus_total': 4, 'vcpus_used': 6,
                     'cpu_allocation_ratio': 1.0}
        host1 = fakes.FakeHostState('fake-host', 'node', host_attr)

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'cpu_weight_multiplier': 'invalid'},
            )]
        # Get value from default given value if the agg meta is invalid.
        self.assertEqual(
            1.0,
            utils.get_weight_multiplier(host1, 'cpu_weight_multiplier', 1.0)
        )

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'cpu_weight_multiplier': '1.9'},
            )]
        # Get value from aggregate metadata
        self.assertEqual(
            1.9,
            utils.get_weight_multiplier(host1, 'cpu_weight_multiplier', 1.0)
        )

        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'cpu_weight_multiplier': '1.9'}),
            objects.Aggregate(
                id=2,
                name='foo',
                hosts=['fake-host'],
                metadata={'cpu_weight_multiplier': '1.8'}),
        ]
        # Get min value from aggregate metadata
        self.assertEqual(
            1.8,
            utils.get_weight_multiplier(host1, 'cpu_weight_multiplier', 1.0)
        )

    def _set_up_and_fill_provider_mapping(self, requested_resources):
        request_spec = objects.RequestSpec()
        request_spec.requested_resources = requested_resources
        allocs = {
            uuids.rp_uuid1: {
                'resources': {
                    'NET_BW_EGR_KILOBIT_PER_SEC': 1,
                }
            },
            uuids.rp_uuid2: {
                'resources': {
                    'NET_BW_INGR_KILOBIT_PER_SEC': 1,
                }
            }
        }
        mappings = {
            uuids.port_id1: [uuids.rp_uuid2],
            uuids.port_id2: [uuids.rp_uuid1],
        }
        allocation_req = {'allocations': allocs, 'mappings': mappings}
        selection = objects.Selection(
            allocation_request=jsonutils.dumps(allocation_req))

        # Unmapped initially
        for rg in requested_resources:
            self.assertEqual([], rg.provider_uuids)

        utils.fill_provider_mapping(request_spec, selection)

    def test_fill_provider_mapping(self):
        rg1 = objects.RequestGroup(requester_id=uuids.port_id1)
        rg2 = objects.RequestGroup(requester_id=uuids.port_id2)
        self._set_up_and_fill_provider_mapping([rg1, rg2])

        # Validate the mappings
        self.assertEqual([uuids.rp_uuid2], rg1.provider_uuids)
        self.assertEqual([uuids.rp_uuid1], rg2.provider_uuids)

    def test_fill_provider_mapping_no_op(self):
        # This just proves that having 'mappings' in the allocation request
        # doesn't break anything.
        self._set_up_and_fill_provider_mapping([])

    @mock.patch.object(objects.RequestSpec,
                       'map_requested_resources_to_providers')
    def test_fill_provider_mapping_based_on_allocation_returns_early(
            self, mock_map):
        context = nova_context.RequestContext()
        request_spec = objects.RequestSpec()
        # set up the request that there is nothing to do
        request_spec.requested_resources = []
        report_client = mock.sentinel.report_client
        allocation = mock.sentinel.allocation

        utils.fill_provider_mapping_based_on_allocation(
            context, report_client, request_spec, allocation)

        mock_map.assert_not_called()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    @mock.patch.object(objects.RequestSpec,
                       'map_requested_resources_to_providers')
    def test_fill_provider_mapping_based_on_allocation(
            self, mock_map, mock_report_client):
        context = nova_context.RequestContext()
        request_spec = objects.RequestSpec()
        # set up the request that there is nothing to do
        request_spec.requested_resources = [objects.RequestGroup()]
        allocation = {
            uuids.rp_uuid: {
                'resources': {
                    'NET_BW_EGR_KILOBIT_PER_SEC': 1,
                }
            }
        }
        traits = ['CUSTOM_PHYSNET1', 'CUSTOM_VNIC_TYPE_NORMAL']
        mock_report_client.get_provider_traits.return_value = report.TraitInfo(
            traits=['CUSTOM_PHYSNET1', 'CUSTOM_VNIC_TYPE_NORMAL'],
            generation=0)

        utils.fill_provider_mapping_based_on_allocation(
            context, mock_report_client, request_spec, allocation)

        mock_map.assert_called_once_with(allocation, {uuids.rp_uuid: traits})


class TestEncryptedMemoryTranslation(TestUtilsBase):
    flavor_name = 'm1.test'
    image_name = 'cirros'

    def _get_request_spec(self, extra_specs, image):
        flavor = objects.Flavor(name=self.flavor_name,
                                vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs=extra_specs)

        # NOTE(aspiers): RequestSpec.flavor is not nullable, but
        # RequestSpec.image is.
        reqspec = objects.RequestSpec(flavor=flavor)

        if image:
            reqspec.image = image

        return reqspec

    def _get_resource_request(self, extra_specs, image):
        reqspec = self._get_request_spec(extra_specs, image)
        return utils.ResourceRequest(reqspec)

    def _get_expected_resource_request(self, mem_encryption_context):
        expected_resources = {
            'VCPU': 1,
            'MEMORY_MB': 1024,
            'DISK_GB': 15,
        }
        if mem_encryption_context:
            expected_resources[orc.MEM_ENCRYPTION_CONTEXT] = 1

        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            resources=expected_resources)
        return expected

    def _test_encrypted_memory_support_not_required(self, extra_specs,
                                                    image=None):
        resreq = self._get_resource_request(extra_specs, image)
        expected = self._get_expected_resource_request(False)

        self.assertResourceRequestsEqual(expected, resreq)

    def test_encrypted_memory_support_empty_extra_specs(self):
        self._test_encrypted_memory_support_not_required(extra_specs={})

    def test_encrypted_memory_support_false_extra_spec(self):
        for extra_spec in ('0', 'false', 'False'):
            self._test_encrypted_memory_support_not_required(
                extra_specs={'hw:mem_encryption': extra_spec})

    def test_encrypted_memory_support_empty_image_props(self):
        self._test_encrypted_memory_support_not_required(
            extra_specs={},
            image=objects.ImageMeta(properties=objects.ImageMetaProps()))

    def test_encrypted_memory_support_false_image_prop(self):
        for image_prop in ('0', 'false', 'False'):
            self._test_encrypted_memory_support_not_required(
                extra_specs={},
                image=objects.ImageMeta(
                    properties=objects.ImageMetaProps(
                        hw_mem_encryption=image_prop))
            )

    def test_encrypted_memory_support_both_false(self):
        for extra_spec in ('0', 'false', 'False'):
            for image_prop in ('0', 'false', 'False'):
                self._test_encrypted_memory_support_not_required(
                    extra_specs={'hw:mem_encryption': extra_spec},
                    image=objects.ImageMeta(
                        properties=objects.ImageMetaProps(
                            hw_mem_encryption=image_prop))
                )

    def _test_encrypted_memory_support_conflict(self, extra_spec,
                                                image_prop_in,
                                                image_prop_out):
        # NOTE(aspiers): hw_mem_encryption image property is a
        # FlexibleBooleanField, so the result should always be coerced
        # to a boolean.
        self.assertIsInstance(image_prop_out, bool)

        image = objects.ImageMeta(
            name=self.image_name,
            properties=objects.ImageMetaProps(
                hw_mem_encryption=image_prop_in)
        )

        reqspec = self._get_request_spec(
            extra_specs={'hw:mem_encryption': extra_spec},
            image=image)

        # Sanity check that our test request spec has an extra_specs
        # dict, which is needed in order for there to be a conflict.
        self.assertIn('flavor', reqspec)
        self.assertIn('extra_specs', reqspec.flavor)

        error = (
            "Flavor %(flavor_name)s has hw:mem_encryption extra spec "
            "explicitly set to %(flavor_val)s, conflicting with "
            "image %(image_name)s which has hw_mem_encryption property "
            "explicitly set to %(image_val)s"
        )
        exc = self.assertRaises(
            exception.FlavorImageConflict,
            utils.ResourceRequest, reqspec
        )
        error_data = {
            'flavor_name': self.flavor_name,
            'flavor_val': extra_spec,
            'image_name': self.image_name,
            'image_val': image_prop_out,
        }
        self.assertEqual(error % error_data, str(exc))

    def test_encrypted_memory_support_conflict1(self):
        for extra_spec in ('0', 'false', 'False'):
            for image_prop_in in ('1', 'true', 'True'):
                self._test_encrypted_memory_support_conflict(
                    extra_spec, image_prop_in, True
                )

    def test_encrypted_memory_support_conflict2(self):
        for extra_spec in ('1', 'true', 'True'):
            for image_prop_in in ('0', 'false', 'False'):
                self._test_encrypted_memory_support_conflict(
                    extra_spec, image_prop_in, False
                )

    @mock.patch.object(utils, 'LOG')
    def _test_encrypted_memory_support_required(self, requesters, extra_specs,
                                                mock_log, image=None):
        resreq = self._get_resource_request(extra_specs, image)
        expected = self._get_expected_resource_request(True)

        self.assertResourceRequestsEqual(expected, resreq)
        mock_log.debug.assert_has_calls([
            mock.call('Added %s=1 to requested resources',
                      orc.MEM_ENCRYPTION_CONTEXT)
        ])

    def test_encrypted_memory_support_extra_spec(self):
        for extra_spec in ('1', 'true', 'True'):
            self._test_encrypted_memory_support_required(
                'hw:mem_encryption extra spec',
                {'hw:mem_encryption': extra_spec},
                image=objects.ImageMeta(
                    id='005249be-3c2f-4351-9df7-29bb13c21b14',
                    properties=objects.ImageMetaProps(
                        hw_machine_type='q35',
                        hw_firmware_type='uefi'))
            )

    def test_encrypted_memory_support_image_prop(self):
        for image_prop in ('1', 'true', 'True'):
            self._test_encrypted_memory_support_required(
                'hw_mem_encryption image property',
                {},
                image=objects.ImageMeta(
                    id='005249be-3c2f-4351-9df7-29bb13c21b14',
                    name=self.image_name,
                    properties=objects.ImageMetaProps(
                        hw_machine_type='q35',
                        hw_firmware_type='uefi',
                        hw_mem_encryption=image_prop))
            )

    def test_encrypted_memory_support_both_required(self):
        for extra_spec in ('1', 'true', 'True'):
            for image_prop in ('1', 'true', 'True'):
                self._test_encrypted_memory_support_required(
                    'hw:mem_encryption extra spec and '
                    'hw_mem_encryption image property',
                    {'hw:mem_encryption': extra_spec},
                    image=objects.ImageMeta(
                        id='005249be-3c2f-4351-9df7-29bb13c21b14',
                        name=self.image_name,
                        properties=objects.ImageMetaProps(
                            hw_machine_type='q35',
                            hw_firmware_type='uefi',
                            hw_mem_encryption=image_prop))
                )


class TestResourcesFromRequestGroupDefaultPolicy(test.NoDBTestCase):
    """These test cases assert what happens when the group policy is missing
    from the flavor but more than one numbered request group is requested from
    various sources. Note that while image can provide required traits for the
    resource request those traits are always added to the unnumbered group so
    image cannot be a source of additional numbered groups.
    """

    def setUp(self):
        super(TestResourcesFromRequestGroupDefaultPolicy, self).setUp()
        self.context = nova_context.get_admin_context()
        self.port_group1 = objects.RequestGroup.from_port_request(
            self.context, uuids.port1,
            port_resource_request={
                "resources": {
                    "NET_BW_IGR_KILOBIT_PER_SEC": 1000,
                    "NET_BW_EGR_KILOBIT_PER_SEC": 1000},
                "required": ["CUSTOM_PHYSNET_2",
                             "CUSTOM_VNIC_TYPE_NORMAL"]
            })
        self.port_group2 = objects.RequestGroup.from_port_request(
            self.context, uuids.port2,
            port_resource_request={
                "resources": {
                    "NET_BW_IGR_KILOBIT_PER_SEC": 2000,
                    "NET_BW_EGR_KILOBIT_PER_SEC": 2000},
                "required": ["CUSTOM_PHYSNET_3",
                             "CUSTOM_VNIC_TYPE_DIRECT"]
            })
        self.image = objects.ImageMeta(properties=objects.ImageMetaProps())

    def test_one_group_from_flavor_dont_warn(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'resources1:CUSTOM_BAR': '2',
            })
        request_spec = objects.RequestSpec(
            flavor=flavor, image=self.image, requested_resources=[])

        rr = utils.resources_from_request_spec(
            self.context, request_spec, host_manager=mock.Mock())

        log = self.stdlog.logger.output
        self.assertNotIn(
            "There is more than one numbered request group in the allocation "
            "candidate query but the flavor did not specify any group policy.",
            log)
        self.assertNotIn(
            "To avoid the placement failure nova defaults the group policy to "
            "'none'.",
            log)
        self.assertIsNone(rr.group_policy)
        self.assertNotIn('group_policy=none', rr.to_querystring())

    def test_one_group_from_port_dont_warn(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={})
        request_spec = objects.RequestSpec(
            flavor=flavor, image=self.image,
            requested_resources=[self.port_group1])

        rr = utils.resources_from_request_spec(
            self.context, request_spec, host_manager=mock.Mock())

        log = self.stdlog.logger.output
        self.assertNotIn(
            "There is more than one numbered request group in the allocation "
            "candidate query but the flavor did not specify any group policy.",
            log)
        self.assertNotIn(
            "To avoid the placement failure nova defaults the group policy to "
            "'none'.",
            log)
        self.assertIsNone(rr.group_policy)
        self.assertNotIn('group_policy=none', rr.to_querystring())

    def test_two_groups_from_flavor_only_warns(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'resources1:CUSTOM_BAR': '2',
                'resources2:CUSTOM_FOO': '1'
            })
        request_spec = objects.RequestSpec(
            flavor=flavor, image=self.image, requested_resources=[])

        rr = utils.resources_from_request_spec(
            self.context, request_spec, host_manager=mock.Mock())

        log = self.stdlog.logger.output
        self.assertIn(
            "There is more than one numbered request group in the allocation "
            "candidate query but the flavor did not specify any group policy.",
            log)
        self.assertNotIn(
            "To avoid the placement failure nova defaults the group policy to "
            "'none'.",
            log)
        self.assertIsNone(rr.group_policy)
        self.assertNotIn('group_policy', rr.to_querystring())

    def test_one_group_from_flavor_one_from_port_policy_defaulted(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'resources1:CUSTOM_BAR': '2',
            })
        request_spec = objects.RequestSpec(
            flavor=flavor, image=self.image,
            requested_resources=[self.port_group1])

        rr = utils.resources_from_request_spec(
            self.context, request_spec, host_manager=mock.Mock())

        log = self.stdlog.logger.output
        self.assertIn(
            "There is more than one numbered request group in the allocation "
            "candidate query but the flavor did not specify any group policy.",
            log)
        self.assertIn(
            "To avoid the placement failure nova defaults the group policy to "
            "'none'.",
            log)
        self.assertEqual('none', rr.group_policy)
        self.assertIn('group_policy=none', rr.to_querystring())

    def test_two_groups_from_ports_policy_defaulted(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={})
        request_spec = objects.RequestSpec(
            flavor=flavor, image=self.image,
            requested_resources=[self.port_group1, self.port_group2])

        rr = utils.resources_from_request_spec(
            self.context, request_spec, host_manager=mock.Mock())

        log = self.stdlog.logger.output
        self.assertIn(
            "There is more than one numbered request group in the allocation "
            "candidate query but the flavor did not specify any group policy.",
            log)
        self.assertIn(
            "To avoid the placement failure nova defaults the group policy to "
            "'none'.",
            log)
        self.assertEqual('none', rr.group_policy)
        self.assertIn('group_policy=none', rr.to_querystring())
