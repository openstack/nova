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

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova.compute import instance_types
from nova.db.sqlalchemy.session import get_session
from nova.db.sqlalchemy import models

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.compute')


class InstanceTypeTestCase(test.TestCase):
    """Test cases for instance type code"""
    def setUp(self):
        super(InstanceTypeTestCase, self).setUp()
        session = get_session()

    def _generate_name(self):
        """return a name not in the DB"""
        nonexistent_flavor = str(int(time.time()))
        flavors = instance_types.get_all_types()
        while nonexistent_flavor in flavors:
            nonexistent_flavor += "z"
        else:
            return nonexistent_flavor

    def _generate_flavorid(self):
        """return a flavorid not in the DB"""
        nonexistent_flavor = 2700
        flavor_ids = [value["id"] for key, value in\
                    instance_types.get_all_types().iteritems()]
        while nonexistent_flavor in flavor_ids:
            nonexistent_flavor += 1
        else:
            return nonexistent_flavor

    def _existing_flavor(self):
        """return first instance type name"""
        return instance_types.get_all_types().keys()[0]

    def test_instance_type_create_then_delete(self):
        """Ensure instance types can be created"""
        name = 'Small Flavor'
        flavorid = 'flavor1'

        original_list = instance_types.get_all_types()

        # create new type and make sure values stick
        inst_type = instance_types.create(name, 256, 1, 120, flavorid)
        inst_type_id = inst_type['id']
        self.assertEqual(inst_type['flavorid'], flavorid)
        self.assertEqual(inst_type['name'], name)
        self.assertEqual(inst_type['memory_mb'], 256)
        self.assertEqual(inst_type['vcpus'], 1)
        self.assertEqual(inst_type['local_gb'], 120)
        self.assertEqual(inst_type['swap'], 0)
        self.assertEqual(inst_type['rxtx_factor'], 1)

        # make sure new type shows up in list
        new_list = instance_types.get_all_types()
        self.assertNotEqual(len(original_list), len(new_list),
                            'instance type was not created')

        # destroy instance and make sure deleted flag is set to True
        instance_types.destroy(name)
        inst_type = instance_types.get_instance_type(inst_type_id)
        self.assertEqual(1, inst_type["deleted"])

        # deleted instance should not be in list anymoer
        new_list = instance_types.get_all_types()
        self.assertEqual(original_list, new_list)

        # ensure instances are gone after purge
        instance_types.purge(name)
        new_list = instance_types.get_all_types()
        self.assertEqual(original_list, new_list,
                         'instance type not purged')

    def test_get_all_instance_types(self):
        """Ensures that all instance types can be retrieved"""
        session = get_session()
        total_instance_types = session.query(models.InstanceTypes).count()
        inst_types = instance_types.get_all_types()
        self.assertEqual(total_instance_types, len(inst_types))

    def test_invalid_create_args_should_fail(self):
        """Ensures that instance type creation fails with invalid args"""
        invalid_sigs = [
            (('Zero memory', 0, 1, 10, 'flavor1'), {}),
            (('Negative memory', -256, 1, 10, 'flavor1'), {}),
            (('Non-integer memory', 'asdf', 1, 10, 'flavor1'), {}),

            (('Zero vcpus', 256, 0, 10, 'flavor1'), {}),
            (('Negative vcpus', 256, -1, 10, 'flavor1'), {}),
            (('Non-integer vcpus', 256, 'a', 10, 'flavor1'), {}),

            (('Negative storage', 256, 1, -1, 'flavor1'), {}),
            (('Non-integer storage', 256, 1, 'a', 'flavor1'), {}),

            (('Negative swap', 256, 1, 10, 'flavor1'), {'swap': -1}),
            (('Non-integer swap', 256, 1, 10, 'flavor1'), {'swap': -1}),

            (('Negative rxtx_factor', 256, 1, 10, 'f1'), {'rxtx_factor': -1}),
            (('Non-integer rxtx_factor', 256, 1, 10, 'f1'),
                 {'rxtx_factor': "d"}),
        ]

        for (args, kwargs) in invalid_sigs:
            self.assertRaises(exception.InvalidInput,
                              instance_types.create, *args, **kwargs)

    def test_non_existent_inst_type_shouldnt_delete(self):
        """Ensures that instance type creation fails with invalid args"""
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                          instance_types.destroy,
                          'unknown_flavor')

    def test_duplicate_names_fail(self):
        """Ensures that name duplicates raise ApiError"""
        name = 'some_name'
        instance_types.create(name, 256, 1, 120, 'flavor1')
        self.assertRaises(exception.ApiError,
                          instance_types.create,
                          name, "256", 1, 120, 'flavor2')

    def test_duplicate_flavorids_fail(self):
        """Ensures that flavorid duplicates raise ApiError"""
        flavorid = 'flavor1'
        instance_types.create('name one', 256, 1, 120, flavorid)
        self.assertRaises(exception.ApiError,
                          instance_types.create,
                          'name two', 256, 1, 120, flavorid)

    def test_will_not_destroy_with_no_name(self):
        """Ensure destroy sad path of no name raises error"""
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                          instance_types.destroy, None)

    def test_will_not_purge_without_name(self):
        """Ensure purge without a name raises error"""
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                          instance_types.purge, None)

    def test_will_not_purge_with_wrong_name(self):
        """Ensure purge without correct name raises error"""
        self.assertRaises(exception.InstanceTypeNotFound,
                          instance_types.purge,
                          'unknown_flavor')

    def test_will_not_get_bad_default_instance_type(self):
        """ensures error raised on bad default instance type"""
        FLAGS.default_instance_type = 'unknown_flavor'
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                          instance_types.get_default_instance_type)

    def test_will_get_instance_type_by_id(self):
        default_instance_type = instance_types.get_default_instance_type()
        instance_type_id = default_instance_type['id']
        fetched = instance_types.get_instance_type(instance_type_id)
        self.assertEqual(default_instance_type, fetched)

    def test_will_not_get_instance_type_by_unknown_id(self):
        """Ensure get by name returns default flavor with no name"""
        self.assertRaises(exception.InstanceTypeNotFound,
                         instance_types.get_instance_type, 10000)

    def test_will_not_get_instance_type_with_bad_id(self):
        """Ensure get by name returns default flavor with bad name"""
        self.assertRaises(exception.InstanceTypeNotFound,
                          instance_types.get_instance_type, 'asdf')

    def test_instance_type_get_by_None_name_returns_default(self):
        """Ensure get by name returns default flavor with no name"""
        default = instance_types.get_default_instance_type()
        actual = instance_types.get_instance_type_by_name(None)
        self.assertEqual(default, actual)

    def test_will_not_get_instance_type_with_bad_name(self):
        """Ensure get by name returns default flavor with bad name"""
        self.assertRaises(exception.InstanceTypeNotFoundByName,
                          instance_types.get_instance_type_by_name, 10000)

    def test_will_not_get_instance_by_unknown_flavor_id(self):
        """Ensure get by flavor raises error with wrong flavorid"""
        self.assertRaises(exception.FlavorNotFound,
                          instance_types.get_instance_type_by_flavor_id,
                          'unknown_flavor')

    def test_will_get_instance_by_flavor_id(self):
        default_instance_type = instance_types.get_default_instance_type()
        flavorid = default_instance_type['flavorid']
        fetched = instance_types.get_instance_type_by_flavor_id(flavorid)
        self.assertEqual(default_instance_type, fetched)


class InstanceTypeFilteringTest(test.TestCase):
    """Test cases for the filter option available for instance_type_get_all"""
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
        """Exclude tiny instance which is 512 MB"""
        filters = dict(min_memory_mb=513)
        expected = ['m1.large', 'm1.medium', 'm1.small', 'm1.xlarge']
        self.assertFilterResults(filters, expected)

    def test_min_local_gb_filter(self):
        """Exclude everything but large and xlarge which have >= 80 GB"""
        filters = dict(min_local_gb=80)
        expected = ['m1.large', 'm1.xlarge']
        self.assertFilterResults(filters, expected)

    def test_min_memory_mb_AND_local_gb_filter(self):
        """Exclude everything but large and xlarge which have >= 80 GB"""
        filters = dict(min_memory_mb=16384, min_local_gb=80)
        expected = ['m1.xlarge']
        self.assertFilterResults(filters, expected)
