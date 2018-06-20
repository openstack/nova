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

from nova.api.openstack.placement import lib as plib
from nova import context as nova_context
from nova import exception
from nova import objects
from nova.scheduler.client import report
from nova.scheduler import utils
from nova import test
from nova.tests.unit import fake_instance
from nova.tests import uuidsentinel as uuids


class TestUtils(test.NoDBTestCase):

    def setUp(self):
        super(TestUtils, self).setUp()
        self.context = nova_context.get_admin_context()

    def assertResourceRequestsEqual(self, expected, observed):
        self.assertEqual(expected._limit, observed._limit)
        self.assertEqual(expected._group_policy, observed._group_policy)
        ex_by_id = expected._rg_by_id
        ob_by_id = observed._rg_by_id
        self.assertEqual(set(ex_by_id), set(ob_by_id))
        for ident in ex_by_id:
            self.assertEqual(vars(ex_by_id[ident]), vars(ob_by_id[ident]))

    @staticmethod
    def _get_image_with_traits():
        image_prop = {
            'properties': {
                'trait:CUSTOM_IMAGE_TRAIT1': 'required',
                'trait:CUSTOM_IMAGE_TRAIT2': 'required',
            },
            'id': 'c8b1790e-a07d-4971-b137-44f2432936cd'
        }
        image = objects.ImageMeta.from_dict(image_prop)
        return image

    def _test_resources_from_request_spec(self, expected, flavor,
                                          image=objects.ImageMeta()):
        fake_spec = objects.RequestSpec(flavor=flavor, image=image)
        resources = utils.resources_from_request_spec(fake_spec)
        self.assertResourceRequestsEqual(expected, resources)
        return resources

    def test_resources_from_request_spec_flavor_only(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0)
        expected_resources = utils.ResourceRequest()
        expected_resources._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            }
        )
        self._test_resources_from_request_spec(expected_resources, flavor)

    def test_resources_from_request_spec_flavor_and_image_traits(self):
        image = self._get_image_with_traits()
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={
                                    'trait:CUSTOM_FLAVOR_TRAIT': 'required',
                                    'trait:CUSTOM_IMAGE_TRAIT2': 'required'})
        expected_resources = utils.ResourceRequest()
        expected_resources._rg_by_id[None] = plib.RequestGroup(
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

    def test_resources_from_request_spec_with_no_disk(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=0,
                                ephemeral_gb=0,
                                swap=0)
        expected_resources = utils.ResourceRequest()
        expected_resources._rg_by_id[None] = plib.RequestGroup(
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
        expected_resources = utils.ResourceRequest()
        expected_resources._rg_by_id[None] = plib.RequestGroup(
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
        expected_resources = utils.ResourceRequest()
        expected_resources._rg_by_id[None] = plib.RequestGroup(
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
        expected_resources = utils.ResourceRequest()
        expected_resources._rg_by_id[None] = plib.RequestGroup(
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
        expected_resources = utils.ResourceRequest()
        expected_resources._rg_by_id[None] = plib.RequestGroup(
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
        with mock.patch("nova.scheduler.utils.LOG.warning") as mock_log:
            utils.resources_from_request_spec(fake_spec)
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
        expected_resources = utils.ResourceRequest()
        expected_resources._group_policy = 'none'
        expected_resources._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            resources={
                'DISK_GB': 10,
                'CUSTOM_THING': 123,
            }
        )
        expected_resources._rg_by_id['1'] = plib.RequestGroup(
            resources={
                'VGPU': 1,
                'VGPU_DISPLAY_HEAD': 2,
            }
        )
        expected_resources._rg_by_id['3'] = plib.RequestGroup(
            resources={
                'VCPU': 2,
            },
            required_traits={
                'CUSTOM_GOLD',
                'CUSTOM_SILVER',
            }
        )
        expected_resources._rg_by_id['24'] = plib.RequestGroup(
            resources={
                'SRIOV_NET_VF': 2,
            },
        )
        expected_resources._rg_by_id['42'] = plib.RequestGroup(
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

    def test_resources_from_request_spec_aggregates(self):
        destination = objects.Destination()
        flavor = objects.Flavor(vcpus=1, memory_mb=1024,
                                root_gb=1, ephemeral_gb=0,
                                swap=0)
        reqspec = objects.RequestSpec(flavor=flavor,
                                      requested_destination=destination)

        destination.require_aggregates(['foo', 'bar'])
        req = utils.resources_from_request_spec(reqspec)
        self.assertEqual([('foo', 'bar',)],
                         req.get_request_group(None).member_of)

        destination.require_aggregates(['baz'])
        req = utils.resources_from_request_spec(reqspec)
        self.assertEqual([('foo', 'bar'), ('baz',)],
                         req.get_request_group(None).member_of)

        # Test stringification
        self.assertEqual(
            'RequestGroup(use_same_provider=False, '
            'resources={DISK_GB:1, MEMORY_MB:1024, VCPU:1}, '
            'traits=[], '
            'aggregates=[[baz], [foo, bar]])',
            str(req))

    def test_resources_from_request_spec_no_aggregates(self):
        flavor = objects.Flavor(vcpus=1, memory_mb=1024,
                                root_gb=1, ephemeral_gb=0,
                                swap=0)
        reqspec = objects.RequestSpec(flavor=flavor)

        req = utils.resources_from_request_spec(reqspec)
        self.assertEqual([], req.get_request_group(None).member_of)

        reqspec.requested_destination = None
        req = utils.resources_from_request_spec(reqspec)
        self.assertEqual([], req.get_request_group(None).member_of)

        reqspec.requested_destination = objects.Destination()
        req = utils.resources_from_request_spec(reqspec)
        self.assertEqual([], req.get_request_group(None).member_of)

        reqspec.requested_destination.aggregates = None
        req = utils.resources_from_request_spec(reqspec)
        self.assertEqual([], req.get_request_group(None).member_of)

    @mock.patch("nova.scheduler.utils.ResourceRequest.from_extra_specs")
    def test_process_extra_specs_granular_called(self, mock_proc):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0,
                                extra_specs={"resources:CUSTOM_TEST_CLASS": 1})
        fake_spec = objects.RequestSpec(flavor=flavor)
        utils.resources_from_request_spec(fake_spec)
        mock_proc.assert_called_once()

    @mock.patch("nova.scheduler.utils.ResourceRequest.from_extra_specs")
    def test_process_extra_specs_granular_not_called(self, mock_proc):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=10,
                                ephemeral_gb=5,
                                swap=0)
        fake_spec = objects.RequestSpec(flavor=flavor)
        utils.resources_from_request_spec(fake_spec)
        mock_proc.assert_not_called()

    def test_process_missing_extra_specs_value(self):
        flavor = objects.Flavor(
                vcpus=1,
                memory_mb=1024,
                root_gb=10,
                ephemeral_gb=5,
                swap=0,
                extra_specs={"resources:CUSTOM_TEST_CLASS": ""})
        fake_spec = objects.RequestSpec(flavor=flavor)
        utils.resources_from_request_spec(fake_spec)

    def test_process_no_force_hosts_or_force_nodes(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        expected = utils.ResourceRequest()
        expected._rg_by_id[None] = plib.RequestGroup(
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
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        fake_spec = objects.RequestSpec(flavor=flavor, force_nodes=['test'])
        expected = utils.ResourceRequest()
        expected._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        expected._limit = None
        resources = utils.resources_from_request_spec(fake_spec)
        self.assertResourceRequestsEqual(expected, resources)
        expected_querystring = (
            'resources=DISK_GB%3A15%2CMEMORY_MB%3A1024%2CVCPU%3A1'
        )
        self.assertEqual(expected_querystring, resources.to_querystring())

    def test_process_use_force_hosts(self):
        flavor = objects.Flavor(vcpus=1,
                                memory_mb=1024,
                                root_gb=15,
                                ephemeral_gb=0,
                                swap=0)
        fake_spec = objects.RequestSpec(flavor=flavor, force_hosts=['test'])
        expected = utils.ResourceRequest()
        expected._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 1,
                'MEMORY_MB': 1024,
                'DISK_GB': 15,
            },
        )
        expected._limit = None
        resources = utils.resources_from_request_spec(fake_spec)
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

    def test_resource_request_from_extra_specs(self):
        extra_specs = {
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
            'resources_5:SRIOV_NET_VF': '7',
            'traitFoo:HW_NIC_ACCEL_SSL': 'required',
            # Solo resource, no corresponding traits
            'resources3:DISK_GB': '5',
            'group_policy': 'isolate',
        }
        # Build up a ResourceRequest from the inside to compare against.
        expected = utils.ResourceRequest()
        expected._group_policy = 'isolate'
        expected._rg_by_id[None] = plib.RequestGroup(
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
        expected._rg_by_id['1'] = plib.RequestGroup(
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
        expected._rg_by_id['2'] = plib.RequestGroup(
            resources={
                'SRIOV_NET_VF': 1,
                'IPV4_ADDRESS': 2,
            },
            required_traits={
                'CUSTOM_PHYSNET_NET2',
                'HW_NIC_ACCEL_SSL',
            }
        )
        expected._rg_by_id['3'] = plib.RequestGroup(
            resources={
                'DISK_GB': 5,
            }
        )

        rr = utils.ResourceRequest.from_extra_specs(extra_specs)
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

        # Test stringification
        self.assertEqual(
            'RequestGroup(use_same_provider=False, '
            'resources={MEMORY_MB:2048, VCPU:2}, '
            'traits=[CUSTOM_MAGIC, HW_CPU_X86_AVX, !CUSTOM_BRONZE], '
            'aggregates=[]), '
            'RequestGroup(use_same_provider=True, '
            'resources={DISK_GB:5}, '
            'traits=[], '
            'aggregates=[]), '
            'RequestGroup(use_same_provider=True, '
            'resources={IPV4_ADDRESS:1, SRIOV_NET_VF:1}, '
            'traits=[CUSTOM_PHYSNET_NET1, !CUSTOM_PHYSNET_NET2], '
            'aggregates=[]), '
            'RequestGroup(use_same_provider=True, '
            'resources={IPV4_ADDRESS:2, SRIOV_NET_VF:1}, '
            'traits=[CUSTOM_PHYSNET_NET2, HW_NIC_ACCEL_SSL], '
            'aggregates=[])',
            str(rr))

    def test_resource_request_from_extra_specs_append_request(self):
        extra_specs = {
            'resources:VCPU': '2',
            'resources:MEMORY_MB': '2048',
            'trait:HW_CPU_X86_AVX': 'required',
        }
        existing_req = utils.ResourceRequest()
        existing_req._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            required_traits={
                'CUSTOM_MAGIC',
            }
        )
        # Build up a ResourceRequest from the inside to compare against.
        expected = utils.ResourceRequest()
        expected._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 2,
                'MEMORY_MB': 2048,
            },
            required_traits={
                # In addition to traits from extra spec, we get traits from a
                # previous existing resource request
                'HW_CPU_X86_AVX',
                'CUSTOM_MAGIC',
            }
        )
        self.assertResourceRequestsEqual(
            expected, utils.ResourceRequest.from_extra_specs(extra_specs,
                                                             req=existing_req))

    def test_resource_request_from_image_props(self):
        props = {'trait:CUSTOM_TRUSTED': 'required'}
        image_meta_props = objects.ImageMetaProps.from_dict(props)

        # Build up a ResourceRequest from the inside to compare against.
        expected = utils.ResourceRequest()
        expected._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            required_traits={
                'CUSTOM_TRUSTED',
            }
        )
        self.assertResourceRequestsEqual(
            expected, utils.ResourceRequest.from_image_props(image_meta_props))

    def test_resource_request_from_image_props_append_request(self):
        props = {'trait:CUSTOM_MAGIC': 'required'}
        image_meta_props = objects.ImageMetaProps.from_dict(props)

        existing_req = utils.ResourceRequest()
        existing_req._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 2,
                'MEMORY_MB': 2048,
            },
            required_traits={
                'HW_CPU_X86_AVX',
            }
        )
        # Build up a ResourceRequest from the inside to compare against.
        expected = utils.ResourceRequest()
        expected._rg_by_id[None] = plib.RequestGroup(
            use_same_provider=False,
            resources={
                'VCPU': 2,
                'MEMORY_MB': 2048,
            },
            required_traits={
                # In addition to information already contained in the existing
                # resource request, we add the traits from image properties
                'HW_CPU_X86_AVX',
                'CUSTOM_MAGIC',
            }
        )
        self.assertResourceRequestsEqual(
            expected, utils.ResourceRequest.from_image_props(image_meta_props,
                                                             req=existing_req))

    def test_merge_resources(self):
        resources = {
            'VCPU': 1, 'MEMORY_MB': 1024,
        }
        new_resources = {
            'VCPU': 2, 'MEMORY_MB': 2048, 'CUSTOM_FOO': 1,
        }
        doubled = {
            'VCPU': 3, 'MEMORY_MB': 3072, 'CUSTOM_FOO': 1,
        }
        saved_orig = dict(resources)
        utils.merge_resources(resources, new_resources)
        # Check to see that we've doubled our resources
        self.assertEqual(doubled, resources)
        # and then removed those doubled resources
        utils.merge_resources(resources, saved_orig, -1)
        self.assertEqual(new_resources, resources)

    def test_merge_resources_zero(self):
        """Test 0 value resources are ignored."""
        resources = {
            'VCPU': 1, 'MEMORY_MB': 1024,
        }
        new_resources = {
            'VCPU': 2, 'MEMORY_MB': 2048, 'DISK_GB': 0,
        }
        # The result should not include the zero valued resource.
        doubled = {
            'VCPU': 3, 'MEMORY_MB': 3072,
        }
        utils.merge_resources(resources, new_resources)
        self.assertEqual(doubled, resources)

    def test_merge_resources_original_zeroes(self):
        """Confirm that merging that result in a zero in the original
        excludes the zeroed resource class.
        """
        resources = {
            'VCPU': 3, 'MEMORY_MB': 1023, 'DISK_GB': 1,
        }
        new_resources = {
            'VCPU': 1, 'MEMORY_MB': 512, 'DISK_GB': 1,
        }
        merged = {
            'VCPU': 2, 'MEMORY_MB': 511,
        }
        utils.merge_resources(resources, new_resources, -1)
        self.assertEqual(merged, resources)

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
                           'get_allocations_for_consumer_by_provider',
                           return_value={})
        @mock.patch.object(reportclient,
                           'claim_resources',
                           new_callable=mock.NonCallableMock)
        def test(mock_claim, mock_get_allocs):
            utils.claim_resources_on_destination(
                self.context, reportclient, instance, source_node, dest_node)
            mock_get_allocs.assert_called_once_with(
                self.context, uuids.source_node, instance.uuid)

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
            'VCPU': instance.vcpus,
            'MEMORY_MB': instance.memory_mb,
            # This would really include ephemeral and swap too but we're lazy.
            'DISK_GB': instance.root_gb
        }
        dest_alloc_request = {
            'allocations': {
                uuids.dest_node: {
                    'resources': source_res_allocs
                }
            }
        }

        @mock.patch.object(reportclient,
                           'get_allocations_for_consumer_by_provider',
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
                self.context, uuids.source_node, instance.uuid)
            mock_claim.assert_called_once_with(
                self.context, instance.uuid, dest_alloc_request,
                instance.project_id, instance.user_id,
                allocation_request_version='1.12')

        test()

    def test_claim_resources_on_destination(self):
        """Happy path test where everything is successful."""
        reportclient = report.SchedulerReportClient()
        instance = fake_instance.fake_instance_obj(self.context)
        source_node = objects.ComputeNode(
            uuid=uuids.source_node, host=instance.host)
        dest_node = objects.ComputeNode(uuid=uuids.dest_node, host='dest-host')
        source_res_allocs = {
            'VCPU': instance.vcpus,
            'MEMORY_MB': instance.memory_mb,
            # This would really include ephemeral and swap too but we're lazy.
            'DISK_GB': instance.root_gb
        }
        dest_alloc_request = {
            'allocations': {
                uuids.dest_node: {
                    'resources': source_res_allocs
                }
            }
        }

        @mock.patch.object(reportclient,
                           'get_allocations_for_consumer_by_provider')
        @mock.patch.object(reportclient,
                           'claim_resources', return_value=True)
        def test(mock_claim, mock_get_allocs):
            utils.claim_resources_on_destination(
                self.context, reportclient, instance, source_node, dest_node,
                source_res_allocs)
            self.assertFalse(mock_get_allocs.called)
            mock_claim.assert_called_once_with(
                self.context, instance.uuid, dest_alloc_request,
                instance.project_id, instance.user_id,
                allocation_request_version='1.12')

        test()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    @mock.patch('nova.scheduler.utils.request_is_rebuild')
    def test_claim_resources(self, mock_is_rebuild, mock_client):
        """Tests that when claim_resources() is called, that we appropriately
        call the placement client to claim resources for the instance.
        """
        mock_is_rebuild.return_value = False
        ctx = mock.Mock(user_id=uuids.user_id)
        spec_obj = mock.Mock(project_id=uuids.project_id)
        instance_uuid = uuids.instance
        alloc_req = mock.sentinel.alloc_req
        mock_client.claim_resources.return_value = True

        res = utils.claim_resources(ctx, mock_client, spec_obj, instance_uuid,
                alloc_req)

        mock_client.claim_resources.assert_called_once_with(
            ctx, uuids.instance, mock.sentinel.alloc_req, uuids.project_id,
            uuids.user_id, allocation_request_version=None)
        self.assertTrue(res)

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient')
    @mock.patch('nova.scheduler.utils.request_is_rebuild')
    def test_claim_resouces_for_policy_check(self, mock_is_rebuild,
            mock_client):
        mock_is_rebuild.return_value = True
        ctx = mock.Mock(user_id=uuids.user_id)
        res = utils.claim_resources(ctx, None, mock.sentinel.spec_obj,
                mock.sentinel.instance_uuid, [])
        self.assertTrue(res)
        mock_is_rebuild.assert_called_once_with(mock.sentinel.spec_obj)
        self.assertFalse(mock_client.claim_resources.called)
