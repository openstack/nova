# Copyright 2011 Ken Pepple
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
"""
Unit Tests for flavors code
"""
from nova.compute import flavors
from nova import context
from nova.db import api as db
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova import test


class InstanceTypeTestCase(test.TestCase):
    """Test cases for flavor  code."""
    def test_will_not_get_instance_by_unknown_flavor_id(self):
        # Ensure get by flavor raises error with wrong flavorid.
        self.assertRaises(exception.FlavorNotFound,
                          flavors.get_flavor_by_flavor_id,
                          'unknown_flavor')

    def test_will_get_instance_by_flavor_id(self):
        default_instance_type = objects.Flavor.get_by_name(
            context.get_admin_context(), 'm1.small')
        flavorid = default_instance_type.flavorid
        fetched = flavors.get_flavor_by_flavor_id(flavorid)
        self.assertIsInstance(fetched, objects.Flavor)
        self.assertEqual(default_instance_type.flavorid, fetched.flavorid)


class InstanceTypeToolsTest(test.TestCase):

    def setUp(self):
        super(InstanceTypeToolsTest, self).setUp()
        self.context = context.get_admin_context()

    def _dict_to_metadata(self, data):
        return [{'key': key, 'value': value} for key, value in data.items()]

    def _test_extract_flavor(self, prefix):
        instance_type = objects.Flavor.get_by_name(self.context, 'm1.small')
        instance_type_p = obj_base.obj_to_primitive(instance_type)

        metadata = {}
        flavors.save_flavor_info(metadata, instance_type, prefix)
        instance = {'system_metadata': self._dict_to_metadata(metadata)}
        _instance_type = flavors.extract_flavor(instance, prefix)
        _instance_type_p = obj_base.obj_to_primitive(_instance_type)

        props = flavors.system_metadata_flavor_props.keys()
        for key in list(instance_type_p.keys()):
            if key not in props:
                del instance_type_p[key]

        self.assertEqual(instance_type_p, _instance_type_p)

    def test_extract_flavor(self):
        self._test_extract_flavor('')

    def test_extract_flavor_no_sysmeta(self):
        instance = {}
        prefix = ''
        result = flavors.extract_flavor(instance, prefix)

        self.assertIsNone(result)

    def test_extract_flavor_prefix(self):
        self._test_extract_flavor('foo_')

    def test_save_flavor_info(self):
        instance_type = objects.Flavor.get_by_name(self.context, 'm1.small')

        example = {}
        example_prefix = {}

        for key in flavors.system_metadata_flavor_props.keys():
            example['instance_type_%s' % key] = instance_type[key]
            example_prefix['fooinstance_type_%s' % key] = instance_type[key]

        metadata = {}
        flavors.save_flavor_info(metadata, instance_type)
        self.assertEqual(example, metadata)

        metadata = {}
        flavors.save_flavor_info(metadata, instance_type, 'foo')
        self.assertEqual(example_prefix, metadata)

    def test_flavor_numa_extras_are_saved(self):
        instance_type = objects.Flavor.get_by_name(self.context, 'm1.small')
        instance_type['extra_specs'] = {
            'hw:numa_mem.0': '123',
            'hw:numa_cpus.0': '456',
            'hw:numa_mem.1': '789',
            'hw:numa_cpus.1': 'ABC',
            'foo': 'bar',
        }
        sysmeta = flavors.save_flavor_info({}, instance_type)
        _instance_type = flavors.extract_flavor({'system_metadata': sysmeta})
        expected_extra_specs = {
            'hw:numa_mem.0': '123',
            'hw:numa_cpus.0': '456',
            'hw:numa_mem.1': '789',
            'hw:numa_cpus.1': 'ABC',
        }
        self.assertEqual(expected_extra_specs, _instance_type['extra_specs'])


class InstanceTypeFilteringTest(test.TestCase):
    """Test cases for the filter option available for instance_type_get_all."""
    def setUp(self):
        super(InstanceTypeFilteringTest, self).setUp()
        self.context = context.get_admin_context()

    def assertFilterResults(self, filters, expected):
        inst_types = objects.FlavorList.get_all(
                self.context, filters=filters)
        inst_names = [i.name for i in inst_types]
        self.assertEqual(inst_names, expected)

    def test_no_filters(self):
        filters = None
        expected = ['m1.tiny', 'm1.small', 'm1.medium', 'm1.large',
                    'm1.xlarge', 'm1.tiny.specs']
        self.assertFilterResults(filters, expected)

    def test_min_memory_mb_filter(self):
        # Exclude tiny instance which is 512 MB.
        filters = dict(min_memory_mb=513)
        expected = ['m1.small', 'm1.medium', 'm1.large', 'm1.xlarge']
        self.assertFilterResults(filters, expected)

    def test_min_root_gb_filter(self):
        # Exclude everything but large and xlarge which have >= 80 GB.
        filters = dict(min_root_gb=80)
        expected = ['m1.large', 'm1.xlarge']
        self.assertFilterResults(filters, expected)

    def test_min_memory_mb_AND_root_gb_filter(self):
        # Exclude everything but large and xlarge which have >= 80 GB.
        filters = dict(min_memory_mb=16384, min_root_gb=80)
        expected = ['m1.xlarge']
        self.assertFilterResults(filters, expected)


class CreateInstanceTypeTest(test.TestCase):

    def assertInvalidInput(self, *create_args, **create_kwargs):
        self.assertRaises(exception.InvalidInput, flavors.create,
                          *create_args, **create_kwargs)

    def test_memory_must_be_positive_db_integer(self):
        self.assertInvalidInput('flavor1', 'foo', 1, 120)
        self.assertInvalidInput('flavor1', -1, 1, 120)
        self.assertInvalidInput('flavor1', 0, 1, 120)
        self.assertInvalidInput('flavor1', db.MAX_INT + 1, 1, 120)
        flavors.create('flavor1', 1, 1, 120)

    def test_vcpus_must_be_positive_db_integer(self):
        self.assertInvalidInput('flavor`', 64, 'foo', 120)
        self.assertInvalidInput('flavor1', 64, -1, 120)
        self.assertInvalidInput('flavor1', 64, 0, 120)
        self.assertInvalidInput('flavor1', 64, db.MAX_INT + 1, 120)
        flavors.create('flavor1', 64, 1, 120)

    def test_root_gb_must_be_nonnegative_db_integer(self):
        self.assertInvalidInput('flavor1', 64, 1, 'foo')
        self.assertInvalidInput('flavor1', 64, 1, -1)
        self.assertInvalidInput('flavor1', 64, 1, db.MAX_INT + 1)
        flavors.create('flavor1', 64, 1, 0)
        flavors.create('flavor2', 64, 1, 120)

    def test_ephemeral_gb_must_be_nonnegative_db_integer(self):
        self.assertInvalidInput('flavor1', 64, 1, 120, ephemeral_gb='foo')
        self.assertInvalidInput('flavor1', 64, 1, 120, ephemeral_gb=-1)
        self.assertInvalidInput('flavor1', 64, 1, 120,
                                ephemeral_gb=db.MAX_INT + 1)
        flavors.create('flavor1', 64, 1, 120, ephemeral_gb=0)
        flavors.create('flavor2', 64, 1, 120, ephemeral_gb=120)

    def test_swap_must_be_nonnegative_db_integer(self):
        self.assertInvalidInput('flavor1', 64, 1, 120, swap='foo')
        self.assertInvalidInput('flavor1', 64, 1, 120, swap=-1)
        self.assertInvalidInput('flavor1', 64, 1, 120,
                                swap=db.MAX_INT + 1)
        flavors.create('flavor1', 64, 1, 120, swap=0)
        flavors.create('flavor2', 64, 1, 120, swap=1)

    def test_rxtx_factor_must_be_positive_float(self):
        self.assertInvalidInput('flavor1', 64, 1, 120, rxtx_factor='foo')
        self.assertInvalidInput('flavor1', 64, 1, 120, rxtx_factor=-1.0)
        self.assertInvalidInput('flavor1', 64, 1, 120, rxtx_factor=0.0)

        flavor = flavors.create('flavor1', 64, 1, 120, rxtx_factor=1.0)
        self.assertEqual(1.0, flavor.rxtx_factor)

        flavor = flavors.create('flavor2', 64, 1, 120, rxtx_factor=1.1)
        self.assertEqual(1.1, flavor.rxtx_factor)

    def test_rxtx_factor_must_be_within_sql_float_range(self):
        # We do * 10 since this is an approximation and we need to make sure
        # the difference is noticeble.
        over_rxtx_factor = db.SQL_SP_FLOAT_MAX * 10

        self.assertInvalidInput('flavor1', 64, 1, 120,
                                rxtx_factor=over_rxtx_factor)

        flavor = flavors.create('flavor2', 64, 1, 120,
                                rxtx_factor=db.SQL_SP_FLOAT_MAX)
        self.assertEqual(db.SQL_SP_FLOAT_MAX, flavor.rxtx_factor)

    def test_is_public_must_be_valid_bool_string(self):
        self.assertInvalidInput('flavor1', 64, 1, 120, is_public='foo')

        flavors.create('flavor1', 64, 1, 120, is_public='TRUE')
        flavors.create('flavor2', 64, 1, 120, is_public='False')
        flavors.create('flavor3', 64, 1, 120, is_public='Yes')
        flavors.create('flavor4', 64, 1, 120, is_public='No')
        flavors.create('flavor5', 64, 1, 120, is_public='Y')
        flavors.create('flavor6', 64, 1, 120, is_public='N')
        flavors.create('flavor7', 64, 1, 120, is_public='1')
        flavors.create('flavor8', 64, 1, 120, is_public='0')
        flavors.create('flavor9', 64, 1, 120, is_public='true')

    def test_flavorid_populated(self):
        flavor1 = flavors.create('flavor1', 64, 1, 120)
        self.assertIsNotNone(flavor1.flavorid)

        flavor2 = flavors.create('flavor2', 64, 1, 120, flavorid='')
        self.assertIsNotNone(flavor2.flavorid)

        flavor3 = flavors.create('flavor3', 64, 1, 120, flavorid='foo')
        self.assertEqual('foo', flavor3.flavorid)

    def test_default_values(self):
        flavor1 = flavors.create('flavor1', 64, 1, 120)

        self.assertIsNotNone(flavor1.flavorid)
        self.assertEqual(flavor1.ephemeral_gb, 0)
        self.assertEqual(flavor1.swap, 0)
        self.assertEqual(flavor1.rxtx_factor, 1.0)

    def test_basic_create(self):
        # Ensure instance types can be created.
        ctxt = context.get_admin_context()
        original_list = objects.FlavorList.get_all(ctxt)

        # Create new type and make sure values stick
        flavor = flavors.create('flavor', 64, 1, 120)
        self.assertEqual(flavor.name, 'flavor')
        self.assertEqual(flavor.memory_mb, 64)
        self.assertEqual(flavor.vcpus, 1)
        self.assertEqual(flavor.root_gb, 120)

        # Ensure new type shows up in list
        new_list = objects.FlavorList.get_all(ctxt)
        self.assertNotEqual(len(original_list), len(new_list),
                            'flavor was not created')

    def test_create_then_delete(self):
        ctxt = context.get_admin_context()
        original_list = objects.FlavorList.get_all(ctxt)

        flavor = flavors.create('flavor', 64, 1, 120)

        # Ensure new type shows up in list
        new_list = objects.FlavorList.get_all(ctxt)
        self.assertNotEqual(len(original_list), len(new_list),
                            'instance type was not created')

        flavor.destroy()
        self.assertRaises(exception.FlavorNotFound,
                          objects.Flavor.get_by_name, ctxt, flavor.name)

        # Deleted instance should not be in list anymore
        new_list = objects.FlavorList.get_all(ctxt)
        self.assertEqual(len(original_list), len(new_list))
        for i, f in enumerate(original_list):
            self.assertIsInstance(f, objects.Flavor)
            self.assertEqual(f.flavorid, new_list[i].flavorid)

    def test_duplicate_names_fail(self):
        # Ensures that name duplicates raise FlavorExists
        flavors.create('flavor', 256, 1, 120, 200, 'flavor1')
        self.assertRaises(exception.FlavorExists,
                          flavors.create,
                          'flavor', 64, 1, 120)

    def test_duplicate_flavorids_fail(self):
        # Ensures that flavorid duplicates raise FlavorExists
        flavors.create('flavor1', 64, 1, 120, flavorid='flavorid')
        self.assertRaises(exception.FlavorIdExists,
                          flavors.create,
                          'flavor2', 64, 1, 120, flavorid='flavorid')
