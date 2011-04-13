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
from nova import utils
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
        max_flavorid = session.query(models.InstanceTypes).\
                                     order_by("flavorid desc").\
                                     first()
        max_id = session.query(models.InstanceTypes).\
                                     order_by("id desc").\
                                     first()
        self.flavorid = max_flavorid["flavorid"] + 1
        self.id = max_id["id"] + 1
        self.name = str(int(time.time()))

    def test_instance_type_create_then_delete(self):
        """Ensure instance types can be created"""
        starting_inst_list = instance_types.get_all_types()
        instance_types.create(self.name, 256, 1, 120, self.flavorid)
        new = instance_types.get_all_types()
        self.assertNotEqual(len(starting_inst_list),
                            len(new),
                            'instance type was not created')
        instance_types.destroy(self.name)
        self.assertEqual(1,
                    instance_types.get_instance_type(self.id)["deleted"])
        self.assertEqual(starting_inst_list, instance_types.get_all_types())
        instance_types.purge(self.name)
        self.assertEqual(len(starting_inst_list),
                         len(instance_types.get_all_types()),
                         'instance type not purged')

    def test_get_all_instance_types(self):
        """Ensures that all instance types can be retrieved"""
        session = get_session()
        total_instance_types = session.query(models.InstanceTypes).\
                                            count()
        inst_types = instance_types.get_all_types()
        self.assertEqual(total_instance_types, len(inst_types))

    def test_invalid_create_args_should_fail(self):
        """Ensures that instance type creation fails with invalid args"""
        self.assertRaises(
                exception.InvalidInputException,
                instance_types.create, self.name, 0, 1, 120, self.flavorid)
        self.assertRaises(
                exception.InvalidInputException,
                instance_types.create, self.name, 256, -1, 120, self.flavorid)
        self.assertRaises(
                exception.InvalidInputException,
                instance_types.create, self.name, 256, 1, "aa", self.flavorid)

    def test_non_existant_inst_type_shouldnt_delete(self):
        """Ensures that instance type creation fails with invalid args"""
        self.assertRaises(exception.ApiError,
                          instance_types.destroy, "sfsfsdfdfs")

    def test_repeated_inst_types_should_raise_api_error(self):
        """Ensures that instance duplicates raises ApiError"""
        new_name = self.name + "dup"
        instance_types.create(new_name, 256, 1, 120, self.flavorid + 1)
        instance_types.destroy(new_name)
        self.assertRaises(
                exception.ApiError,
                instance_types.create, new_name, 256, 1, 120, self.flavorid)
