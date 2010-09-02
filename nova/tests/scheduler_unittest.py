# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
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
Tests For Scheduler
"""
import logging

from twisted.internet import defer

from nova import db
from nova import flags
from nova import service
from nova import test
from nova import utils
from nova.auth import manager as auth_manager
from nova.scheduler import manager
from nova.scheduler import driver


FLAGS = flags.FLAGS
flags.DECLARE('max_instances', 'nova.scheduler.simple')


class SchedulerTestCase(test.TrialTestCase):
    """Test case for scheduler"""
    def setUp(self):  # pylint: disable-msg=C0103
        super(SchedulerTestCase, self).setUp()
        self.flags(connection_type='fake',
                   max_instances=4,
                   scheduler_driver='nova.scheduler.simple.SimpleScheduler')
        self.scheduler = manager.SchedulerManager()
        self.context = None
        self.manager = auth_manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake')
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.context = None

    def tearDown(self):  # pylint: disable-msg=C0103
        self.manager.delete_user(self.user)
        self.manager.delete_project(self.project)

    def _create_instance(self):
        """Create a test instance"""
        inst = {}
        inst['image_id'] = 'ami-test'
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user.id
        inst['project_id'] = self.project.id
        inst['instance_type'] = 'm1.tiny'
        inst['mac_address'] = utils.generate_mac()
        inst['ami_launch_index'] = 0
        return db.instance_create(self.context, inst)

    def test_hosts_are_up(self):
        # NOTE(vish): constructing service without create method
        #             because we are going to use it without queue
        service1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        service2 = service.Service('host2',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        hosts = self.scheduler.driver.hosts_up(self.context, 'compute')
        self.assertEqual(len(hosts), 0)
        service1.report_state()
        service2.report_state()
        hosts = self.scheduler.driver.hosts_up(self.context, 'compute')
        self.assertEqual(len(hosts), 2)

    def test_least_busy_host_gets_instance(self):
        service1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        service2 = service.Service('host2',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        service1.report_state()
        service2.report_state()
        instance_id = self._create_instance()
        service1.run_instance(self.context, instance_id)
        host = self.scheduler.driver.pick_compute_host(self.context,
                                                       instance_id)
        self.assertEqual(host, 'host2')
        service1.terminate_instance(self.context, instance_id)

    def test_too_many_instances(self):
        service1 = service.Service('host',
                                  'nova-compute',
                                  'compute',
                                  FLAGS.compute_manager)
        instance_ids = []
        for index in xrange(FLAGS.max_instances):
            instance_id = self._create_instance()
            service1.run_instance(self.context, instance_id)
            instance_ids.append(instance_id)
        instance_id = self._create_instance()
        self.assertRaises(driver.NoValidHost,
                          self.scheduler.driver.pick_compute_host,
                          self.context,
                          instance_id)
        for instance_id in instance_ids:
            service1.terminate_instance(self.context, instance_id)
