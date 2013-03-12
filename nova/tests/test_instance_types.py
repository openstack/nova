# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
Unit Tests for instance types code
"""
import time

from nova.compute import instance_types
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova.openstack.common.db.sqlalchemy import session as sql_session
from nova.openstack.common import log as logging
from nova import test

LOG = logging.getLogger(__name__)


class InstanceTypeTestCase(test.TestCase):
    """Test cases for instance type code."""
    def _generate_name(self):
        """return a name not in the DB."""
        nonexistent_flavor = str(int(time.time()))
        flavors = instance_types.get_all_types()
        while nonexistent_flavor in flavors:
            nonexistent_flavor += "z"
        else:
            return nonexistent_flavor

    def _generate_flavorid(self):
        """return a flavorid not in the DB."""
        nonexistent_flavor = 2700
        flavor_ids = [value["id"] for key, value in
                      instance_types.get_all_types().iteritems()]
        while nonexistent_flavor in flavor_ids:
            nonexistent_flavor += 1
        else:
            return nonexistent_flavor

    def _existing_flavor(self):
        """return first instance type name."""
        return instance_types.get_all_types().keys()[0]

    def test_instance_type_create(self):
        # Ensure instance types can be created.
        name = 'Instance create test'
        flavor_id = '512'

        original_list = instance_types.get_all_types()

        # create new type and make sure values stick
        inst_type = instance_types.create(name, 256, 1, 120,
                                          flavorid=flavor_id)
        self.assertEqual(inst_type['flavorid'], flavor_id)
        self.assertEqual(inst_type['name'], name)
        self.assertEqual(inst_type['memory_mb'], 256)
        self.assertEqual(inst_type['vcpus'], 1)
        self.assertEqual(inst_type['root_gb'], 120)
        self.assertEqual(inst_type['ephemeral_gb'], 0)
        self.assertEqual(inst_type['swap'], 0)
        self.assertEqual(inst_type['rxtx_factor'], 1.0)

        # make sure new type shows up in list
        new_list = instance_types.get_all_types()
        self.assertNotEqual(len(original_list), len(new_list),
                            'instance type was not created')

    def test_instance_type_create_then_delete(self):
        # Ensure instance types can be created.
        name = 'Small Flavor'
        flavorid = 'flavor1'

        original_list = instance_types.get_all_types()

        # create new type and make sure values stick
        inst_type = instance_types.create(name, 256, 1, 120, 100, flavorid)
        inst_type_id = inst_type['id']
        self.assertEqual(inst_type['flavorid'], flavorid)
        self.assertEqual(inst_type['name'], name)
        self.assertEqual(inst_type['memory_mb'], 256)
        self.assertEqual(inst_type['vcpus'], 1)
        self.assertEqual(inst_type['root_gb'], 120)
        self.assertEqual(inst_type['ephemeral_gb'], 100)
        self.assertEqual(inst_type['swap'], 0)
        self.assertEqual(inst_type['rxtx_factor'], 1.0)

        # make sure new type shows up in list
        new_list = instance_types.get_all_types()
        self.assertNotEqual(len(original_list), len(new_list),
                            'instance type was not created')

        instance_types.destroy(name)
        self.assertRaises(exception.InstanceTypeNotFound,
                          instance_types.get_instance_type, inst_type_id)

        # deleted instance should not be in list anymoer
        new_list = instance_types.get_all_types()
        self.assertEqual(original_list, new_list)

    def test_instance_type_create_without_flavorid(self):
        name = 'Small Flavor'
        inst_type = instance_types.create(name, 256, 1, 120, 100)
        self.assertNotEqual(inst_type['flavorid'], None)
        self.assertEqual(inst_type['name'], name)
        self.assertEqual(inst_type['memory_mb'], 256)
        self.assertEqual(inst_type['vcpus'], 1)
        self.assertEqual(inst_type['root_gb'], 120)
        self.assertEqual(inst_type['ephemeral_gb'], 100)
        self.assertEqual(inst_type['swap'], 0)
        self.assertEqual(inst_type['rxtx_factor'], 1.0)

    def test_instance_type_create_with_empty_flavorid(self):
        # Ensure that auto-generated uuid is assigned.
        name = 'Empty String ID Flavor'
        flavorid = ''
        inst_type = instance_types.create(name, 256, 1, 120, 100, flavorid)
        self.assertEqual(len(inst_type['flavorid']), 36)
        self.assertEqual(inst_type['name'], name)
        self.assertEqual(inst_type['memory_mb'], 256)
        self.assertEqual(inst_type['vcpus'], 1)
        self.assertEqual(inst_type['root_gb'], 120)
        self.assertEqual(inst_type['ephemeral_gb'], 100)
        self.assertEqual(inst_type['swap'], 0)
        self.assertEqual(inst_type['rxtx_factor'], 1.0)

    def test_instance_type_create_with_custom_rxtx_factor(self):
        name = 'Custom RXTX Factor'
        inst_type = instance_types.create(name, 256, 1, 120, 100,
                                          rxtx_factor=9.9)
        self.assertNotEqual(inst_type['flavorid'], None)
        self.assertEqual(inst_type['name'], name)
        self.assertEqual(inst_type['memory_mb'], 256)
        self.assertEqual(inst_type['vcpus'], 1)
        self.assertEqual(inst_type['root_gb'], 120)
        self.assertEqual(inst_type['ephemeral_gb'], 100)
        self.assertEqual(inst_type['swap'], 0)
        self.assertEqual(inst_type['rxtx_factor'], 9.9)

    def test_instance_type_create_with_special_characters(self):
        # Ensure instance types raises InvalidInput for invalid characters.
        name = "foo.bar!@#$%^-test_name"
        flavorid = "flavor1"
        self.assertRaises(exception.InvalidInput, instance_types.create,
                name, 256, 1, 120, 100, flavorid)

    def test_instance_type_create_with_long_flavor_name(self):
        # Flavor name with 255 characters or less is valid.
        name = 'a' * 255
        inst_type = instance_types.create(name, 64, 1, 120, flavorid=11)
        self.assertEqual(inst_type['name'], name)

        # Flavor name which is more than 255 characters will cause error.
        name = 'a' * 256
        self.assertRaises(exception.InvalidInput, instance_types.create,
                          name, 64, 1, 120, flavorid=11)

    def test_add_instance_type_access(self):
        user_id = 'fake'
        project_id = 'fake'
        ctxt = context.RequestContext(user_id, project_id, is_admin=True)
        flavor_id = 'flavor1'
        type_ref = instance_types.create('some flavor', 256, 1, 120, 100,
                                          flavorid=flavor_id)
        access_ref = instance_types.add_instance_type_access(flavor_id,
                                                             project_id,
                                                             ctxt=ctxt)
        self.assertEqual(access_ref["project_id"], project_id)
        self.assertEqual(access_ref["instance_type_id"], type_ref["id"])

    def test_add_instance_type_access_already_exists(self):
        user_id = 'fake'
        project_id = 'fake'
        ctxt = context.RequestContext(user_id, project_id, is_admin=True)
        flavor_id = 'flavor1'
        type_ref = instance_types.create('some flavor', 256, 1, 120, 100,
                                          flavorid=flavor_id)
        access_ref = instance_types.add_instance_type_access(flavor_id,
                                                             project_id,
                                                             ctxt=ctxt)
        self.assertRaises(exception.FlavorAccessExists,
                          instance_types.add_instance_type_access,
                          flavor_id, project_id, ctxt)

    def test_add_instance_type_access_invalid_flavor(self):
        user_id = 'fake'
        project_id = 'fake'
        ctxt = context.RequestContext(user_id, project_id, is_admin=True)
        flavor_id = 'no_such_flavor'
        self.assertRaises(exception.FlavorNotFound,
                          instance_types.add_instance_type_access,
                          flavor_id, project_id, ctxt)

    def test_remove_instance_type_access(self):
        user_id = 'fake'
        project_id = 'fake'
        ctxt = context.RequestContext(user_id, project_id, is_admin=True)
        flavor_id = 'flavor1'
        it = instance_types
        type_ref = it.create('some flavor', 256, 1, 120, 100,
                                          flavorid=flavor_id)
        access_ref = it.add_instance_type_access(flavor_id, project_id, ctxt)
        it.remove_instance_type_access(flavor_id, project_id, ctxt)

        projects = it.get_instance_type_access_by_flavor_id(flavor_id, ctxt)
        self.assertEqual([], projects)

    def test_remove_instance_type_access_doesnt_exists(self):
        user_id = 'fake'
        project_id = 'fake'
        ctxt = context.RequestContext(user_id, project_id, is_admin=True)
        flavor_id = 'flavor1'
        type_ref = instance_types.create('some flavor', 256, 1, 120, 100,
                                          flavorid=flavor_id)
        self.assertRaises(exception.FlavorAccessNotFound,
                          instance_types.remove_instance_type_access,
                          flavor_id, project_id, ctxt=ctxt)

    def test_get_all_instance_types(self):
        # Ensures that all instance types can be retrieved.
        session = sql_session.get_session()
        total_instance_types = session.query(models.InstanceTypes).count()
        inst_types = instance_types.get_all_types()
        self.assertEqual(total_instance_types, len(inst_types))

    def test_invalid_create_args_should_fail(self):
        # Ensures that instance type creation fails with invalid args.
        invalid_sigs = [
            (('Zero memory', 0, 1, 10, 20, 'flavor1'), {}),
            (('Negative memory', -256, 1, 10, 20, 'flavor1'), {}),
            (('Non-integer memory', 'asdf', 1, 10, 20, 'flavor1'), {}),

            (('Zero vcpus', 256, 0, 10, 20, 'flavor1'), {}),
            (('Negative vcpus', 256, -1, 10, 20, 'flavor1'), {}),
            (('Non-integer vcpus', 256, 'a', 10, 20, 'flavor1'), {}),

            (('Negative storage', 256, 1, -1, 20, 'flavor1'), {}),
            (('Non-integer storage', 256, 1, 'a', 20, 'flavor1'), {}),

            (('Negative swap', 256, 1, 10, 20, 'flavor1'), {'swap': -1}),
            (('Non-integer swap', 256, 1, 10, 20, 'flavor1'), {'swap': -1}),

            (('Negative rxtx_factor', 256, 1, 10, 20, 'f1'),
                 {'rxtx_factor': -1}),
            (('Non-integer rxtx_factor', 256, 1, 10, 20, 'f1'),
                 {'rxtx_factor': "d"}),
        ]

        for (args, kwargs) in invalid_sigs:
            self.assertRaises(exception.InvalidInput,
                              instance_types.create, *args, **kwargs)

    def test_non_existent_inst_type_shouldnt_delete(self):
        # Ensures that instance type creation fails with invalid args.
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                          instance_types.destroy,
                          'unknown_flavor')

    def test_duplicate_names_fail(self):
        # Ensures that name duplicates raise InstanceTypeCreateFailed.
        name = 'some_name'
        instance_types.create(name, 256, 1, 120, 200, 'flavor1')
        self.assertRaises(exception.InstanceTypeExists,
                          instance_types.create,
                          name, 256, 1, 120, 200, 'flavor2')

    def test_duplicate_flavorids_fail(self):
        # Ensures that flavorid duplicates raise InstanceTypeCreateFailed.
        flavorid = 'flavor1'
        instance_types.create('name one', 256, 1, 120, 200, flavorid)
        self.assertRaises(exception.InstanceTypeIdExists,
                          instance_types.create,
                          'name two', 256, 1, 120, 200, flavorid)

    def test_will_not_destroy_with_no_name(self):
        # Ensure destroy said path of no name raises error.
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                          instance_types.destroy, None)

    def test_will_not_get_bad_default_instance_type(self):
        # ensures error raised on bad default instance type.
        self.flags(default_instance_type='unknown_flavor')
        self.assertRaises(exception.InstanceTypeNotFound,
                          instance_types.get_default_instance_type)

    def test_will_get_instance_type_by_id(self):
        default_instance_type = instance_types.get_default_instance_type()
        instance_type_id = default_instance_type['id']
        fetched = instance_types.get_instance_type(instance_type_id)
        self.assertEqual(default_instance_type, fetched)

    def test_will_not_get_instance_type_by_unknown_id(self):
        # Ensure get by name returns default flavor with no name.
        self.assertRaises(exception.InstanceTypeNotFound,
                         instance_types.get_instance_type, 10000)

    def test_will_not_get_instance_type_with_bad_id(self):
        # Ensure get by name returns default flavor with bad name.
        self.assertRaises(exception.InstanceTypeNotFound,
                          instance_types.get_instance_type, 'asdf')

    def test_instance_type_get_by_None_name_returns_default(self):
        # Ensure get by name returns default flavor with no name.
        default = instance_types.get_default_instance_type()
        actual = instance_types.get_instance_type_by_name(None)
        self.assertEqual(default, actual)

    def test_will_not_get_instance_type_with_bad_name(self):
        # Ensure get by name returns default flavor with bad name.
        self.assertRaises(exception.InstanceTypeNotFound,
                          instance_types.get_instance_type_by_name, 10000)

    def test_will_not_get_instance_by_unknown_flavor_id(self):
        # Ensure get by flavor raises error with wrong flavorid.
        self.assertRaises(exception.FlavorNotFound,
                          instance_types.get_instance_type_by_flavor_id,
                          'unknown_flavor')

    def test_will_get_instance_by_flavor_id(self):
        default_instance_type = instance_types.get_default_instance_type()
        flavorid = default_instance_type['flavorid']
        fetched = instance_types.get_instance_type_by_flavor_id(flavorid)
        self.assertEqual(default_instance_type, fetched)

    def test_can_read_deleted_types_using_flavor_id(self):
        # Ensure deleted instance types can be read when querying flavor_id.
        inst_type_name = "test"
        inst_type_flavor_id = "test1"

        inst_type = instance_types.create(inst_type_name, 256, 1, 120, 100,
                inst_type_flavor_id)
        self.assertEqual(inst_type_name, inst_type["name"])

        # NOTE(jk0): The deleted flavor will show up here because the context
        # in get_instance_type_by_flavor_id() is set to use read_deleted by
        # default.
        instance_types.destroy(inst_type["name"])
        deleted_inst_type = instance_types.get_instance_type_by_flavor_id(
                inst_type_flavor_id)
        self.assertEqual(inst_type_name, deleted_inst_type["name"])

    def test_read_deleted_false_converting_flavorid(self):
        """
        Ensure deleted instance types are not returned when not needed (for
        example when creating a server and attempting to translate from
        flavorid to instance_type_id.
        """
        instance_types.create("instance_type1", 256, 1, 120, 100, "test1")
        instance_types.destroy("instance_type1")
        instance_types.create("instance_type1_redo", 256, 1, 120, 100, "test1")

        instance_type = instance_types.get_instance_type_by_flavor_id(
                "test1", read_deleted="no")
        self.assertEqual("instance_type1_redo", instance_type["name"])


class InstanceTypeToolsTest(test.TestCase):
    def _dict_to_metadata(self, data):
        return [{'key': key, 'value': value} for key, value in data.items()]

    def _test_extract_instance_type(self, prefix):
        instance_type = instance_types.get_default_instance_type()

        metadata = {}
        instance_types.save_instance_type_info(metadata, instance_type,
                                               prefix)
        instance = {'system_metadata': self._dict_to_metadata(metadata)}
        _instance_type = instance_types.extract_instance_type(instance, prefix)

        props = instance_types.system_metadata_instance_type_props.keys()
        for key in instance_type.keys():
            if key not in props:
                del instance_type[key]

        self.assertEqual(instance_type, _instance_type)

    def test_extract_instance_type(self):
        self._test_extract_instance_type('')

    def test_extract_instance_type_prefix(self):
        self._test_extract_instance_type('foo_')

    def test_save_instance_type_info(self):
        instance_type = instance_types.get_default_instance_type()

        example = {}
        example_prefix = {}

        for key in instance_types.system_metadata_instance_type_props.keys():
            example['instance_type_%s' % key] = instance_type[key]
            example_prefix['fooinstance_type_%s' % key] = instance_type[key]

        metadata = {}
        instance_types.save_instance_type_info(metadata, instance_type)
        self.assertEqual(example, metadata)

        metadata = {}
        instance_types.save_instance_type_info(metadata, instance_type, 'foo')
        self.assertEqual(example_prefix, metadata)

    def test_delete_instance_type_info(self):
        instance_type = instance_types.get_default_instance_type()
        metadata = {}
        instance_types.save_instance_type_info(metadata, instance_type)
        instance_types.save_instance_type_info(metadata, instance_type, '_')
        instance_types.delete_instance_type_info(metadata, '', '_')
        self.assertEqual(metadata, {})


class InstanceTypeFilteringTest(test.TestCase):
    """Test cases for the filter option available for instance_type_get_all."""
    def setUp(self):
        super(InstanceTypeFilteringTest, self).setUp()
        self.context = context.get_admin_context()

    def assertFilterResults(self, filters, expected):
        inst_types = db.instance_type_get_all(
                self.context, filters=filters)
        inst_names = [i['name'] for i in inst_types]
        self.assertEqual(inst_names, expected)

    def test_no_filters(self):
        filters = None
        expected = ['m1.large', 'm1.medium', 'm1.small', 'm1.tiny',
                    'm1.xlarge']
        self.assertFilterResults(filters, expected)

    def test_min_memory_mb_filter(self):
        # Exclude tiny instance which is 512 MB.
        filters = dict(min_memory_mb=513)
        expected = ['m1.large', 'm1.medium', 'm1.small', 'm1.xlarge']
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
