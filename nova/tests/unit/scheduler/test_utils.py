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

import ddt
import os_resource_classes as orc
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import flavors
from nova import context as nova_context
from nova import exception
from nova.network import neutron
from nova import objects
from nova.scheduler.client import report
from nova.scheduler import utils
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_flavor
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

    def test_build_request_spec_without_image(self):
        instance = {'uuid': uuids.instance}
        flavor = objects.Flavor(**test_flavor.fake_flavor)

        with mock.patch.object(flavors, 'extract_flavor') as mock_extract:
            mock_extract.return_value = flavor
            request_spec = utils.build_request_spec(None, [instance])
            mock_extract.assert_called_once_with({'uuid': uuids.instance})
        self.assertEqual({}, request_spec['image'])

    def test_build_request_spec_with_object(self):
        flavor = objects.Flavor()
        instance = fake_instance.fake_instance_obj(self.context)

        with mock.patch.object(instance, 'get_flavor') as mock_get:
            mock_get.return_value = flavor
            request_spec = utils.build_request_spec(None, [instance])
            mock_get.assert_called_once_with()
        self.assertIsInstance(request_spec['instance_properties'], dict)

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

    def test_resources_from_request_spec_with_same_subtree(self):
        """Tests that there same_subtree query params are added to the
        GET /allocation_candidates query string based on the request spec
        """
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=15, ephemeral_gb=0, swap=0)
        req_lvl_params = objects.RequestLevelParams(
            same_subtree=[['group1', 'group2'], ['group3', 'group4']])
        request_spec = objects.RequestSpec(
            flavor=flavor, request_level_params=req_lvl_params)

        resources = utils.resources_from_request_spec(
            self.context, request_spec, self.mock_host_manager)

        self.assertEqual(
            'limit=1000&'
            'resources=DISK_GB%3A15%2CMEMORY_MB%3A1024%2CVCPU%3A1&'
            'same_subtree=group1%2Cgroup2&'
            'same_subtree=group3%2Cgroup4',
            resources.to_querystring()
        )

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

    def test_resource_request_from_request_spec(self):
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
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_extra_specs(self):
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
        rr = utils.ResourceRequest.from_request_spec(rs)
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

    def _test_resource_request_from_rs_with_legacy_extra_specs(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'hw:cpu_policy': 'dedicated',
                'hw:cpu_thread_policy': 'isolate',
                'hw:emulator_threads_policy': 'isolate',
            })

        return objects.RequestSpec(flavor=flavor, is_bfv=False)

    def test_resource_request_from_request_spec_with_legacy_extra_specs(self):
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
        rs = self._test_resource_request_from_rs_with_legacy_extra_specs()
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)
        self.assertTrue(rr.cpu_pinning_requested)

    def test_resource_request_from_rs_with_legacy_extra_specs_no_translate(
        self
    ):
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
        rs = self._test_resource_request_from_rs_with_legacy_extra_specs()
        rr = utils.ResourceRequest.from_request_spec(
            rs, enable_pinning_translate=False)
        self.assertResourceRequestsEqual(expected, rr)
        self.assertFalse(rr.cpu_pinning_requested)

    def test_resource_request_from_request_spec_with_image_props(self):
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
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def _test_resource_request_from_rs_with_legacy_image_props(self):
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

    def test_resource_request_from_request_spec_with_legacy_image_props(self):
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
        rs = self._test_resource_request_from_rs_with_legacy_image_props()
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)
        self.assertTrue(rr.cpu_pinning_requested)

    def test_resource_request_from_rs_with_legacy_image_props_no_translate(
        self
    ):
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
        rs = self._test_resource_request_from_rs_with_legacy_image_props()
        rr = utils.ResourceRequest.from_request_spec(
            rs, enable_pinning_translate=False)
        self.assertResourceRequestsEqual(expected, rr)
        self.assertFalse(rr.cpu_pinning_requested)

    def _test_resource_request_from_request_spec_with_mixed_cpus(
        self, extra_specs
    ):
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
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_mixed_cpus_dedicated(
        self
    ):
        """Ensure the mixed instance, which is generated through
        'hw:cpu_dedicated_mask' extra spec, properly requests the PCPU, VCPU,
        MEMORY_MB and DISK_GB resources.
        """
        extra_specs = {
            'hw:cpu_policy': 'mixed',
            'hw:cpu_dedicated_mask': '2,3'
        }
        self._test_resource_request_from_request_spec_with_mixed_cpus(
            extra_specs)

    def test_resource_request_from_request_spec_with_mixed_cpus_realtime(self):
        """Ensure the mixed instance, which is generated through real-time CPU
        interface, properly requests the PCPU, VCPU, MEMORY_BM and DISK_GB
        resources.
        """
        extra_specs = {
            'hw:cpu_policy': 'mixed',
            "hw:cpu_realtime": "yes",
            "hw:cpu_realtime_mask": '2,3'
        }
        self._test_resource_request_from_request_spec_with_mixed_cpus(
            extra_specs)

    def _test_resource_request_from_request_spec_with_mixed_cpus_iso_emu(
        self, extra_specs
    ):
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
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_rswith_mixed_cpus_iso_emu_realtime(self):
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
        self._test_resource_request_from_request_spec_with_mixed_cpus_iso_emu(
            extra_specs)

    def test_resource_request_from_rs_with_mixed_cpus_iso_emu_dedicated(self):
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
        self._test_resource_request_from_request_spec_with_mixed_cpus_iso_emu(
            extra_specs)

    def test_resource_request_from_request_spec_is_bfv(self):
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
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_vpmems(self):
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
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_pci_numa_policy(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'hw:pci_numa_affinity_policy': 'socket'},
        )
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            required_traits={'COMPUTE_SOCKET_PCI_NUMA_AFFINITY'},
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_stateless_firmware(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
        )
        image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_firmware_type = 'uefi',
                hw_firmware_stateless = True
            )
        )
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            required_traits={'COMPUTE_SECURITY_STATELESS_FIRMWARE'},
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, image=image, is_bfv=False)
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_secure_boot(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'os:secure_boot': 'required'},
        )
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            required_traits={'COMPUTE_SECURITY_UEFI_SECURE_BOOT'},
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_vtpm_version_only(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'hw:tpm_version': '1.2'},
        )
        image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                hw_tpm_version='1.2',
            )
        )
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            required_traits={
                'COMPUTE_SECURITY_TPM_1_2',
                'COMPUTE_SECURITY_TPM_TIS',
            },
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, image=image, is_bfv=False)
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_vtpm_1_2(self):
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
            required_traits={
                'COMPUTE_SECURITY_TPM_1_2',
                'COMPUTE_SECURITY_TPM_TIS',
            },
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, image=image, is_bfv=False)
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_vtpm_2_0(self):
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
            required_traits={
                'COMPUTE_SECURITY_TPM_2_0',
                'COMPUTE_SECURITY_TPM_CRB',
            },
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, image=image, is_bfv=False)
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_maxphysaddr_passthrough(
        self
    ):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'hw:maxphysaddr_mode': 'passthrough'}
        )
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            required_traits={'COMPUTE_ADDRESS_SPACE_PASSTHROUGH'},
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_spec_with_maxphysaddr_emulate(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'hw:maxphysaddr_mode': 'emulate',
                         'hw_maxphysaddr_bits': 42},
        )
        expected = FakeResourceRequest()
        expected._rg_by_id[None] = objects.RequestGroup(
            use_same_provider=False,
            required_traits={'COMPUTE_ADDRESS_SPACE_EMULATED'},
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        rr = utils.ResourceRequest.from_request_spec(rs)
        self.assertResourceRequestsEqual(expected, rr)

    def test_resource_request_from_request_groups(self):
        rgs = objects.RequestGroup.from_extended_port_request(
            self.context,
            port_resource_request={
                "request_groups": [
                    {
                        "id": "group1",
                        "resources": {
                            "NET_BW_IGR_KILOBIT_PER_SEC": 1000,
                            "NET_BW_EGR_KILOBIT_PER_SEC": 1000},
                        "required": ["CUSTOM_PHYSNET_2",
                                     "CUSTOM_VNIC_TYPE_NORMAL"]
                    },
                    {
                        "id": "group2",
                        "resources": {
                            "NET_PACKET_RATE_KILOPACKET_PER_SEC": 100,
                        },
                        "required": ["CUSTOM_VNIC_TYPE_NORMAL"],
                    }
                ],
            }
        )
        req_lvl_params = objects.RequestLevelParams(
            root_required={"CUSTOM_BLUE"},
            root_forbidden={"CUSTOM_DIRTY"},
            same_subtree=[["group1", "group2"]],
        )

        rr = utils.ResourceRequest.from_request_groups(
            rgs, req_lvl_params, 'none')

        self.assertEqual(
            'group_policy=none&'
            'limit=1000&'
            'requiredgroup1='
                'CUSTOM_PHYSNET_2%2C'
                'CUSTOM_VNIC_TYPE_NORMAL&'
            'requiredgroup2='
                'CUSTOM_VNIC_TYPE_NORMAL&'
            'resourcesgroup1='
                'NET_BW_EGR_KILOBIT_PER_SEC%3A1000%2C'
                'NET_BW_IGR_KILOBIT_PER_SEC%3A1000&'
            'resourcesgroup2='
                'NET_PACKET_RATE_KILOPACKET_PER_SEC%3A100&'
            'root_required=CUSTOM_BLUE%2C%21CUSTOM_DIRTY&'
            'same_subtree=group1%2Cgroup2',
            rr.to_querystring())

    def test_resource_request_add_group_inserts_the_group(self):
        flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0)
        rs = objects.RequestSpec(flavor=flavor, is_bfv=False)
        req = utils.ResourceRequest.from_request_spec(rs)
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
        req = utils.ResourceRequest.from_request_spec(rs)
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
                'provider %s' % source_node.uuid, str(ex))

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

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    @mock.patch('nova.rpc.LegacyValidatingNotifier')
    @mock.patch('nova.compute.utils.add_instance_fault_from_exc')
    @mock.patch.object(objects.Instance, 'save')
    def _test_set_vm_state_and_notify(
        self, mock_save, mock_add, mock_notifier, mock_notify_task,
        request_spec, payload_request_spec,
    ):
        expected_uuid = uuids.instance
        updates = dict(vm_state='fake-vm-state')
        service = 'fake-service'
        method = 'fake-method'
        exc_info = 'exc_info'

        payload = dict(request_spec=payload_request_spec,
                       instance_properties=payload_request_spec.get(
                           'instance_properties', {}),
                       instance_id=expected_uuid,
                       state='fake-vm-state',
                       method=method,
                       reason=exc_info)
        event_type = '%s.%s' % (service, method)

        utils.set_vm_state_and_notify(
            self.context, expected_uuid, service, method, updates, exc_info,
            request_spec)
        mock_save.assert_called_once_with()
        mock_add.assert_called_once_with(
            self.context, mock.ANY, exc_info, mock.ANY)
        self.assertIsInstance(mock_add.call_args[0][1], objects.Instance)
        self.assertIsInstance(mock_add.call_args[0][3], tuple)
        mock_notifier.return_value.error.assert_called_once_with(
            self.context, event_type, payload)
        mock_notify_task.assert_called_once_with(
            self.context, method, expected_uuid,
            payload_request_spec, updates['vm_state'],
            exc_info)

    def test_set_vm_state_and_notify_request_spec_dict(self):
        """Tests passing a legacy dict format request spec to
        set_vm_state_and_notify.
        """
        request_spec = dict(instance_properties=dict(uuid=uuids.instance))
        # The request_spec in the notification payload should be unchanged.
        self._test_set_vm_state_and_notify(
            request_spec=request_spec, payload_request_spec=request_spec)

    def test_set_vm_state_and_notify_request_spec_object(self):
        """Tests passing a RequestSpec object to set_vm_state_and_notify."""
        request_spec = objects.RequestSpec.from_primitives(
            self.context, dict(instance_properties=dict(uuid=uuids.instance)),
            filter_properties=dict())
        # The request_spec in the notification payload should be converted
        # to the legacy format.
        self._test_set_vm_state_and_notify(
            request_spec=request_spec,
            payload_request_spec=request_spec.to_legacy_request_spec_dict())

    def test_set_vm_state_and_notify_request_spec_none(self):
        """Tests passing None for the request_spec to set_vm_state_and_notify.
        """
        # The request_spec in the notification payload should be changed to
        # just an empty dict.
        self._test_set_vm_state_and_notify(
            request_spec=None, payload_request_spec={})

    def test_build_filter_properties(self):
        sched_hints = {'hint': ['over-there']}
        forced_host = 'forced-host1'
        forced_node = 'forced-node1'
        flavor = objects.Flavor()
        filt_props = utils.build_filter_properties(sched_hints,
                forced_host, forced_node, flavor)
        self.assertEqual(sched_hints, filt_props['scheduler_hints'])
        self.assertEqual([forced_host], filt_props['force_hosts'])
        self.assertEqual([forced_node], filt_props['force_nodes'])
        self.assertEqual(flavor, filt_props['instance_type'])

    def test_build_filter_properties_no_forced_host_no_force_node(self):
        sched_hints = {'hint': ['over-there']}
        forced_host = None
        forced_node = None
        flavor = objects.Flavor()
        filt_props = utils.build_filter_properties(
            sched_hints, forced_host, forced_node, flavor)
        self.assertEqual(sched_hints, filt_props['scheduler_hints'])
        self.assertEqual(flavor, filt_props['instance_type'])
        self.assertNotIn('forced_host', filt_props)
        self.assertNotIn('forced_node', filt_props)

    def _test_populate_filter_props(
        self, with_retry=True, force_hosts=None, force_nodes=None,
        no_limits=None,
    ):
        if force_hosts is None:
            force_hosts = []
        if force_nodes is None:
            force_nodes = []
        if with_retry:
            if (
                (len(force_hosts) == 1 and len(force_nodes) <= 1) or
                (len(force_nodes) == 1 and len(force_hosts) <= 1)
            ):
                filter_properties = dict(force_hosts=force_hosts,
                                         force_nodes=force_nodes)
            elif len(force_hosts) > 1 or len(force_nodes) > 1:
                filter_properties = dict(retry=dict(hosts=[]),
                                         force_hosts=force_hosts,
                                         force_nodes=force_nodes)
            else:
                filter_properties = dict(retry=dict(hosts=[]))
        else:
            filter_properties = dict()

        if no_limits:
            fake_limits = None
        else:
            fake_limits = objects.SchedulerLimits(
                vcpu=1, disk_gb=2, memory_mb=3, numa_topology=None)

        selection = objects.Selection(
            service_host="fake-host", nodename="fake-node", limits=fake_limits)

        utils.populate_filter_properties(filter_properties, selection)

        enable_retry_force_hosts = not force_hosts or len(force_hosts) > 1
        enable_retry_force_nodes = not force_nodes or len(force_nodes) > 1
        if with_retry or enable_retry_force_hosts or enable_retry_force_nodes:
            # So we can check for 2 hosts
            utils.populate_filter_properties(filter_properties, selection)

        if force_hosts:
            expected_limits = None
        elif no_limits:
            expected_limits = {}
        elif isinstance(fake_limits, objects.SchedulerLimits):
            expected_limits = fake_limits.to_dict()
        else:
            expected_limits = fake_limits
        self.assertEqual(expected_limits, filter_properties.get('limits'))

        if (
            with_retry and enable_retry_force_hosts and
            enable_retry_force_nodes
        ):
            self.assertEqual(
                [['fake-host', 'fake-node'], ['fake-host', 'fake-node']],
                filter_properties['retry']['hosts'])
        else:
            self.assertNotIn('retry', filter_properties)

    def test_populate_filter_props(self):
        self._test_populate_filter_props()

    def test_populate_filter_props_no_retry(self):
        self._test_populate_filter_props(with_retry=False)

    def test_populate_filter_props_force_hosts_no_retry(self):
        self._test_populate_filter_props(force_hosts=['force-host'])

    def test_populate_filter_props_force_nodes_no_retry(self):
        self._test_populate_filter_props(force_nodes=['force-node'])

    def test_populate_filter_props_multi_force_hosts_with_retry(self):
        self._test_populate_filter_props(force_hosts=['force-host1',
                                                      'force-host2'])

    def test_populate_filter_props_multi_force_nodes_with_retry(self):
        self._test_populate_filter_props(force_nodes=['force-node1',
                                                      'force-node2'])

    def test_populate_filter_props_no_limits(self):
        self._test_populate_filter_props(no_limits=True)

    def test_populate_retry_exception_at_max_attempts(self):
        self.flags(max_attempts=2, group='scheduler')
        msg = 'The exception text was preserved!'
        filter_properties = dict(retry=dict(num_attempts=2, hosts=[],
                                            exc_reason=[msg]))
        nvh = self.assertRaises(
            exception.MaxRetriesExceeded, utils.populate_retry,
            filter_properties, uuids.instance)
        # make sure 'msg' is a substring of the complete exception text
        self.assertIn(msg, str(nvh))

    def _check_parse_options(self, opts, sep, converter, expected):
        good = utils.parse_options(opts, sep=sep, converter=converter)
        for item in expected:
            self.assertIn(item, good)

    def test_parse_options(self):
        # check normal
        self._check_parse_options(
            ['foo=1', 'bar=-2.1'], '=', float, [('foo', 1.0), ('bar', -2.1)])
        # check convert error
        self._check_parse_options(
            ['foo=a1', 'bar=-2.1'], '=', float, [('bar', -2.1)])
        # check separator missing
        self._check_parse_options(
            ['foo', 'bar=-2.1'], '=', float, [('bar', -2.1)])
        # check key missing
        self._check_parse_options(
            ['=5', 'bar=-2.1'], '=', float, [('bar', -2.1)])

    def test_validate_filters_configured(self):
        self.flags(
            enabled_filters='FakeFilter1,FakeFilter2',
            group='filter_scheduler')
        self.assertTrue(utils.validate_filter('FakeFilter1'))
        self.assertTrue(utils.validate_filter('FakeFilter2'))
        self.assertFalse(utils.validate_filter('FakeFilter3'))

    def test_validate_weighers_configured(self):
        self.flags(weight_classes=[
            'ServerGroupSoftAntiAffinityWeigher', 'FakeFilter1'],
            group='filter_scheduler')

        self.assertTrue(utils.validate_weigher(
            'ServerGroupSoftAntiAffinityWeigher'))
        self.assertTrue(utils.validate_weigher('FakeFilter1'))
        self.assertFalse(utils.validate_weigher(
            'ServerGroupSoftAffinityWeigher'))

    def test_validate_weighers_configured_all_weighers(self):
        self.assertTrue(utils.validate_weigher(
            'ServerGroupSoftAffinityWeigher'))
        self.assertTrue(utils.validate_weigher(
            'ServerGroupSoftAntiAffinityWeigher'))

    def _create_server_group(self, policy='anti-affinity'):
        instance = fake_instance.fake_instance_obj(self.context,
                params={'host': 'hostA'})

        group = objects.InstanceGroup()
        group.name = 'pele'
        group.uuid = uuids.fake
        group.members = [instance.uuid]
        group.policy = policy
        return group

    def _get_group_details(self, group, policy=None):
        group_hosts = ['hostB']

        with test.nested(
            mock.patch.object(objects.InstanceGroup, 'get_by_instance_uuid',
                              return_value=group),
            mock.patch.object(objects.InstanceGroup, 'get_hosts',
                              return_value=['hostA']),
        ) as (get_group, get_hosts):
            utils._SUPPORTS_ANTI_AFFINITY = None
            utils._SUPPORTS_AFFINITY = None
            group_info = utils._get_group_details(
                self.context, 'fake_uuid', group_hosts)
            self.assertEqual(
                (set(['hostA', 'hostB']), policy, group.members),
                group_info)

    def test_get_group_details(self):
        for policy in ['affinity', 'anti-affinity',
                       'soft-affinity', 'soft-anti-affinity']:
            group = self._create_server_group(policy)
            self._get_group_details(group, policy=policy)

    def test_get_group_details_with_no_instance_uuid(self):
        group_info = utils._get_group_details(self.context, None)
        self.assertIsNone(group_info)

    def _get_group_details_with_filter_not_configured(self, policy):
        self.flags(enabled_filters=['fake'], group='filter_scheduler')
        self.flags(weight_classes=['fake'], group='filter_scheduler')

        instance = fake_instance.fake_instance_obj(
            self.context, params={'host': 'hostA'})

        group = objects.InstanceGroup()
        group.uuid = uuids.fake
        group.members = [instance.uuid]
        group.policy = policy

        with test.nested(
            mock.patch.object(objects.InstanceGroup, 'get_by_instance_uuid',
                              return_value=group),
        ) as (get_group,):
            utils._SUPPORTS_ANTI_AFFINITY = None
            utils._SUPPORTS_AFFINITY = None
            utils._SUPPORTS_SOFT_AFFINITY = None
            utils._SUPPORTS_SOFT_ANTI_AFFINITY = None
            self.assertRaises(exception.UnsupportedPolicyException,
                              utils._get_group_details,
                              self.context, uuids.instance)

    def test_get_group_details_with_filter_not_configured(self):
        policies = ['anti-affinity', 'affinity',
                    'soft-affinity', 'soft-anti-affinity']
        for policy in policies:
            self._get_group_details_with_filter_not_configured(policy)

    @mock.patch.object(utils, '_get_group_details')
    def test_setup_instance_group_in_request_spec(self, mock_ggd):
        mock_ggd.return_value = utils.GroupDetails(
            hosts=set(['hostA', 'hostB']), policy='policy',
            members=['instance1'])
        spec = objects.RequestSpec(instance_uuid=uuids.instance)
        spec.instance_group = objects.InstanceGroup(hosts=['hostC'])

        utils.setup_instance_group(self.context, spec)

        mock_ggd.assert_called_once_with(self.context, uuids.instance,
                                         ['hostC'])
        # Given it returns a list from a set, make sure it's sorted.
        self.assertEqual(['hostA', 'hostB'], sorted(spec.instance_group.hosts))
        self.assertEqual('policy', spec.instance_group.policy)
        self.assertEqual(['instance1'], spec.instance_group.members)

    @mock.patch.object(utils, '_get_group_details')
    def test_setup_instance_group_with_no_group(self, mock_ggd):
        mock_ggd.return_value = None
        spec = objects.RequestSpec(instance_uuid=uuids.instance)
        spec.instance_group = objects.InstanceGroup(hosts=['hostC'])

        utils.setup_instance_group(self.context, spec)

        mock_ggd.assert_called_once_with(self.context, uuids.instance,
                                         ['hostC'])
        # Make sure the field isn't touched by the caller.
        self.assertFalse(spec.instance_group.obj_attr_is_set('policies'))
        self.assertEqual(['hostC'], spec.instance_group.hosts)

    @mock.patch.object(utils, '_get_group_details')
    def test_setup_instance_group_with_filter_not_configured(self, mock_ggd):
        mock_ggd.side_effect = exception.NoValidHost(reason='whatever')
        spec = {'instance_properties': {'uuid': uuids.instance}}
        spec = objects.RequestSpec(instance_uuid=uuids.instance)
        spec.instance_group = objects.InstanceGroup(hosts=['hostC'])
        self.assertRaises(
            exception.NoValidHost,
            utils.setup_instance_group,
            self.context, spec)

    @mock.patch('nova.network.neutron.API.get_segment_ids_for_network')
    def test_get_aggregates_for_routed_network(self, mock_get_segment_ids):
        mock_get_segment_ids.return_value = [uuids.segment1, uuids.segment2]
        report_client = report.SchedulerReportClient()
        network_api = neutron.API()

        def fake_get_provider_aggregates(context, segment_id):
            agg = uuids.agg1 if segment_id == uuids.segment1 else uuids.agg2
            agg_info = report.AggInfo(aggregates=[agg], generation=1)
            return agg_info

        with mock.patch.object(
            report_client, '_get_provider_aggregates',
            side_effect=fake_get_provider_aggregates,
        ) as mock_get_aggs:
            res = utils.get_aggregates_for_routed_network(
                self.context, network_api, report_client, uuids.network1)

        self.assertEqual([uuids.agg1, uuids.agg2], res)
        mock_get_segment_ids.assert_called_once_with(
            self.context, uuids.network1)
        mock_get_aggs.assert_has_calls(
            [mock.call(self.context, uuids.segment1),
             mock.call(self.context, uuids.segment2)])

    @mock.patch('nova.network.neutron.API.get_segment_ids_for_network')
    def test_get_aggregates_for_routed_network_none(
        self, mock_get_segment_ids,
    ):
        mock_get_segment_ids.return_value = []
        report_client = report.SchedulerReportClient()
        network_api = neutron.API()
        self.assertEqual(
            [],
            utils.get_aggregates_for_routed_network(
                self.context, network_api, report_client, uuids.network1))

    @mock.patch('nova.network.neutron.API.get_segment_ids_for_network')
    def test_get_aggregates_for_routed_network_fails(
        self, mock_get_segment_ids,
    ):
        mock_get_segment_ids.return_value = [uuids.segment1]
        report_client = report.SchedulerReportClient()
        network_api = neutron.API()

        # We could fail on some placement issue...
        with mock.patch.object(
            report_client, '_get_provider_aggregates', return_value=None,
        ):
            self.assertRaises(
                exception.InvalidRoutedNetworkConfiguration,
                utils.get_aggregates_for_routed_network,
                self.context, network_api, report_client, uuids.network1)

        # ... but we also want to fail if we can't find the related aggregate
        agg_info = report.AggInfo(aggregates=set(), generation=1)
        with mock.patch.object(
            report_client, '_get_provider_aggregates', return_value=agg_info,
        ):
            self.assertRaises(
                exception.InvalidRoutedNetworkConfiguration,
                utils.get_aggregates_for_routed_network,
                self.context, network_api, report_client, uuids.network1)

    @mock.patch('nova.network.neutron.API.get_segment_id_for_subnet')
    def test_get_aggregates_for_routed_subnet(self, mock_get_segment_ids):
        mock_get_segment_ids.return_value = uuids.segment1
        report_client = report.SchedulerReportClient()
        network_api = neutron.API()
        agg_info = report.AggInfo(aggregates=[uuids.agg1], generation=1)

        with mock.patch.object(
            report_client, '_get_provider_aggregates', return_value=agg_info,
        ) as mock_get_aggs:
            res = utils.get_aggregates_for_routed_subnet(
                self.context, network_api, report_client,
                uuids.subnet1)
        self.assertEqual([uuids.agg1], res)
        mock_get_segment_ids.assert_called_once_with(
            self.context, uuids.subnet1)
        mock_get_aggs.assert_called_once_with(self.context, uuids.segment1)

    @mock.patch('nova.network.neutron.API.get_segment_id_for_subnet')
    def test_get_aggregates_for_routed_subnet_none(self, mock_get_segment_ids):
        mock_get_segment_ids.return_value = None
        report_client = report.SchedulerReportClient()
        network_api = neutron.API()
        self.assertEqual(
            [],
            utils.get_aggregates_for_routed_subnet(
                self.context, network_api, report_client, uuids.subnet1))

    @mock.patch('nova.network.neutron.API.get_segment_id_for_subnet')
    def test_get_aggregates_for_routed_subnet_fails(
        self, mock_get_segment_ids,
    ):
        mock_get_segment_ids.return_value = uuids.segment1
        report_client = report.SchedulerReportClient()
        network_api = neutron.API()

        # We could fail on some placement issue...
        with mock.patch.object(
            report_client, '_get_provider_aggregates', return_value=None,
        ):
            self.assertRaises(
                exception.InvalidRoutedNetworkConfiguration,
                utils.get_aggregates_for_routed_subnet,
                self.context, network_api, report_client, uuids.subnet1)

        # ... but we also want to fail if we can't find the related aggregate
        agg_info = report.AggInfo(aggregates=set(), generation=1)
        with mock.patch.object(report_client, '_get_provider_aggregates',
                return_value=agg_info):
            self.assertRaises(
                exception.InvalidRoutedNetworkConfiguration,
                utils.get_aggregates_for_routed_subnet,
                self.context, network_api, report_client, uuids.subnet1)

    def test_get_weight_multiplier(self):
        host_attr = {
            'vcpus_total': 4, 'vcpus_used': 6, 'cpu_allocation_ratio': 1.0,
        }
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
        return utils.ResourceRequest.from_request_spec(reqspec)

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
            utils.ResourceRequest.from_request_spec, reqspec
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
