# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
# Administrator of the National Aeronautics and Space Administration.
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

"""
Tests For Console proxy.
"""

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import test
from nova import utils

FLAGS = flags.FLAGS
flags.DECLARE('console_driver', 'nova.console.manager')


class ConsoleTestCase(test.TestCase):
    """Test case for console proxy"""
    def setUp(self):
        super(ConsoleTestCase, self).setUp()
        self.flags(console_driver='nova.console.fake.FakeConsoleProxy',
                   stub_compute=True)
        self.console = utils.import_object(FLAGS.console_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.host = 'test_compute_host'

    def _create_instance(self):
        """Create a test instance"""
        inst = {}
        #inst['host'] = self.host
        #inst['name'] = 'instance-1234'
        inst['image_id'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['instance_type_id'] = 1
        inst['ami_launch_index'] = 0
        return db.instance_create(self.context, inst)['id']

    def test_get_pool_for_instance_host(self):
        pool = self.console.get_pool_for_instance_host(self.context, self.host)
        self.assertEqual(pool['compute_host'], self.host)

    def test_get_pool_creates_new_pool_if_needed(self):
        self.assertRaises(exception.NotFound,
                          db.console_pool_get_by_host_type,
                          self.context,
                          self.host,
                          self.console.host,
                          self.console.driver.console_type)
        pool = self.console.get_pool_for_instance_host(self.context,
                                                       self.host)
        pool2 = db.console_pool_get_by_host_type(self.context,
                              self.host,
                              self.console.host,
                              self.console.driver.console_type)
        self.assertEqual(pool['id'], pool2['id'])

    def test_get_pool_does_not_create_new_pool_if_exists(self):
        pool_info = {'address': '127.0.0.1',
                     'username': 'test',
                     'password': '1234pass',
                     'host': self.console.host,
                     'console_type': self.console.driver.console_type,
                     'compute_host': 'sometesthostname'}
        new_pool = db.console_pool_create(self.context, pool_info)
        pool = self.console.get_pool_for_instance_host(self.context,
                                                       'sometesthostname')
        self.assertEqual(pool['id'], new_pool['id'])

    def test_add_console(self):
        instance_id = self._create_instance()
        self.console.add_console(self.context, instance_id)
        instance = db.instance_get(self.context, instance_id)
        pool = db.console_pool_get_by_host_type(self.context,
                                                instance['host'],
                                                self.console.host,
                                            self.console.driver.console_type)

        console_instances = [con['instance_id'] for con in pool.consoles]
        self.assert_(instance_id in console_instances)
        db.instance_destroy(self.context, instance_id)

    def test_add_console_does_not_duplicate(self):
        instance_id = self._create_instance()
        cons1 = self.console.add_console(self.context, instance_id)
        cons2 = self.console.add_console(self.context, instance_id)
        self.assertEqual(cons1, cons2)
        db.instance_destroy(self.context, instance_id)

    def test_remove_console(self):
        instance_id = self._create_instance()
        console_id = self.console.add_console(self.context, instance_id)
        self.console.remove_console(self.context, console_id)

        self.assertRaises(exception.NotFound,
                          db.console_get,
                          self.context,
                          console_id)
        db.instance_destroy(self.context, instance_id)
