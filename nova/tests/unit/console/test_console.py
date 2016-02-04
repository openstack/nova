# Copyright (c) 2010 OpenStack Foundation
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

"""Tests For Console proxy."""

import mock
from oslo_config import cfg
from oslo_utils import importutils

from nova.compute import rpcapi as compute_rpcapi
from nova.console import api as console_api
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova import test

CONF = cfg.CONF
CONF.import_opt('console_manager', 'nova.service')
CONF.import_opt('console_driver', 'nova.console.manager')


class ConsoleTestCase(test.TestCase):
    """Test case for console proxy manager."""
    def setUp(self):
        super(ConsoleTestCase, self).setUp()
        self.flags(console_driver='nova.console.fake.FakeConsoleProxy',
                   stub_compute=True)
        self.console = importutils.import_object(CONF.console_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        self.host = 'test_compute_host'

    def test_reset(self):
        with mock.patch('nova.compute.rpcapi.ComputeAPI') as mock_rpc:
            old_rpcapi = self.console.compute_rpcapi
            self.console.reset()
            mock_rpc.assert_called_once_with()
            self.assertNotEqual(old_rpcapi,
                                self.console.compute_rpcapi)

    def _create_instance(self):
        """Create a test instance."""
        inst = {}
        inst['image_id'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['instance_type_id'] = 1
        inst['ami_launch_index'] = 0
        return db.instance_create(self.context, inst)

    def test_get_pool_for_instance_host(self):
        pool = self.console._get_pool_for_instance_host(self.context,
                self.host)
        self.assertEqual(pool['compute_host'], self.host)

    def test_get_pool_creates_new_pool_if_needed(self):
        self.assertRaises(exception.NotFound,
                          db.console_pool_get_by_host_type,
                          self.context,
                          self.host,
                          self.console.host,
                          self.console.driver.console_type)
        pool = self.console._get_pool_for_instance_host(self.context,
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
        pool = self.console._get_pool_for_instance_host(self.context,
                                                       'sometesthostname')
        self.assertEqual(pool['id'], new_pool['id'])

    def test_add_console(self):
        instance = self._create_instance()
        self.console.add_console(self.context, instance['id'])
        instance = db.instance_get(self.context, instance['id'])
        pool = db.console_pool_get_by_host_type(self.context,
                instance['host'], self.console.host,
                self.console.driver.console_type)

        console_instances = [con['instance_uuid'] for con in pool['consoles']]
        self.assertIn(instance['uuid'], console_instances)
        db.instance_destroy(self.context, instance['uuid'])

    def test_add_console_does_not_duplicate(self):
        instance = self._create_instance()
        cons1 = self.console.add_console(self.context, instance['id'])
        cons2 = self.console.add_console(self.context, instance['id'])
        self.assertEqual(cons1, cons2)
        db.instance_destroy(self.context, instance['uuid'])

    def test_remove_console(self):
        instance = self._create_instance()
        console_id = self.console.add_console(self.context, instance['id'])
        self.console.remove_console(self.context, console_id)

        self.assertRaises(exception.NotFound,
                          db.console_get,
                          self.context,
                          console_id)
        db.instance_destroy(self.context, instance['uuid'])


class ConsoleAPITestCase(test.NoDBTestCase):
    """Test case for console API."""
    def setUp(self):
        super(ConsoleAPITestCase, self).setUp()

        self.context = context.RequestContext('fake', 'fake')
        self.console_api = console_api.API()
        self.fake_uuid = '00000000-aaaa-bbbb-cccc-000000000000'
        self.fake_instance = {
            'id': 1,
            'uuid': self.fake_uuid,
            'host': 'fake_host'
        }
        self.fake_console = {
            'pool': {'host': 'fake_host'},
            'id': 'fake_id'
        }

        def _fake_db_console_get(_ctxt, _console_uuid, _instance_uuid):
            return self.fake_console
        self.stub_out('nova.db.console_get', _fake_db_console_get)

        def _fake_db_console_get_all_by_instance(_ctxt, _instance_uuid,
                                                 columns_to_join):
            return [self.fake_console]
        self.stub_out('nova.db.console_get_all_by_instance',
                       _fake_db_console_get_all_by_instance)

    def test_get_consoles(self):
        console = self.console_api.get_consoles(self.context, self.fake_uuid)
        self.assertEqual(console, [self.fake_console])

    def test_get_console(self):
        console = self.console_api.get_console(self.context, self.fake_uuid,
                                               'fake_id')
        self.assertEqual(console, self.fake_console)

    @mock.patch('nova.console.rpcapi.ConsoleAPI.remove_console')
    def test_delete_console(self, mock_remove):
        self.console_api.delete_console(self.context, self.fake_uuid,
                                        'fake_id')
        mock_remove.assert_called_once_with(self.context, 'fake_id')

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'get_console_topic',
                       return_value='compute.fake_host')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_create_console(self, mock_get_instance_by_uuid,
                            mock_get_console_topic):
        mock_get_instance_by_uuid.return_value = objects.Instance(
            **self.fake_instance)
        self.console_api.create_console(self.context, self.fake_uuid)
        mock_get_console_topic.assert_called_once_with(self.context,
                                                       'fake_host')
