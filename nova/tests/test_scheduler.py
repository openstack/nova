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

from nova import context
from nova import db
from nova import flags
from nova import service
from nova import test
from nova import rpc
from nova import utils
from nova.auth import manager as auth_manager
from nova.scheduler import manager
from nova.scheduler import driver


FLAGS = flags.FLAGS
flags.DECLARE('max_cores', 'nova.scheduler.simple')


class TestDriver(driver.Scheduler):
    """Scheduler Driver for Tests"""
    def schedule(context, topic, *args, **kwargs):
        return 'fallback_host'

    def schedule_named_method(context, topic, num):
        return 'named_host'


class SchedulerTestCase(test.TestCase):
    """Test case for scheduler"""
    def setUp(self):
        super(SchedulerTestCase, self).setUp()
        self.flags(scheduler_driver='nova.tests.test_scheduler.TestDriver')

    def test_fallback(self):
        scheduler = manager.SchedulerManager()
        self.mox.StubOutWithMock(rpc, 'cast', use_mock_anything=True)
        ctxt = context.get_admin_context()
        rpc.cast(ctxt,
                 'topic.fallback_host',
                 {'method': 'noexist',
                  'args': {'num': 7}})
        self.mox.ReplayAll()
        scheduler.noexist(ctxt, 'topic', num=7)

    def test_named_method(self):
        scheduler = manager.SchedulerManager()
        self.mox.StubOutWithMock(rpc, 'cast', use_mock_anything=True)
        ctxt = context.get_admin_context()
        rpc.cast(ctxt,
                 'topic.named_host',
                 {'method': 'named_method',
                  'args': {'num': 7}})
        self.mox.ReplayAll()
        scheduler.named_method(ctxt, 'topic', num=7)


class SimpleDriverTestCase(test.TestCase):
    """Test case for simple driver"""
    def setUp(self):
        super(SimpleDriverTestCase, self).setUp()
        self.flags(connection_type='fake',
                   max_cores=4,
                   max_gigabytes=4,
                   network_manager='nova.network.manager.FlatManager',
                   volume_driver='nova.volume.driver.FakeISCSIDriver',
                   scheduler_driver='nova.scheduler.simple.SimpleScheduler')
        self.scheduler = manager.SchedulerManager()
        self.manager = auth_manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake')
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.context = context.get_admin_context()

    def tearDown(self):
        self.manager.delete_user(self.user)
        self.manager.delete_project(self.project)

    def _create_instance(self):
        """Create a test instance"""
        inst = {}
        inst['image_id'] = 'ami-test'
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user.id
        inst['project_id'] = self.project.id
        inst['instance_type'] = 'm1.tiny'
        inst['mac_address'] = utils.generate_mac()
        inst['ami_launch_index'] = 0
        inst['vcpus'] = 1
        return db.instance_create(self.context, inst)['id']

    def _create_volume(self):
        """Create a test volume"""
        vol = {}
        vol['image_id'] = 'ami-test'
        vol['reservation_id'] = 'r-fakeres'
        vol['size'] = 1
        return db.volume_create(self.context, vol)['id']

    def test_hosts_are_up(self):
        """Ensures driver can find the hosts that are up"""
        # NOTE(vish): constructing service without create method
        #             because we are going to use it without queue
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        compute2 = service.Service('host2',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute2.start()
        hosts = self.scheduler.driver.hosts_up(self.context, 'compute')
        self.assertEqual(len(hosts), 2)
        compute1.kill()
        compute2.kill()

    def test_least_busy_host_gets_instance(self):
        """Ensures the host with less cores gets the next one"""
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        compute2 = service.Service('host2',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute2.start()
        instance_id1 = self._create_instance()
        compute1.run_instance(self.context, instance_id1)
        instance_id2 = self._create_instance()
        host = self.scheduler.driver.schedule_run_instance(self.context,
                                                           instance_id2)
        self.assertEqual(host, 'host2')
        compute1.terminate_instance(self.context, instance_id1)
        db.instance_destroy(self.context, instance_id2)
        compute1.kill()
        compute2.kill()

    def test_too_many_cores(self):
        """Ensures we don't go over max cores"""
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        compute2 = service.Service('host2',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute2.start()
        instance_ids1 = []
        instance_ids2 = []
        for index in xrange(FLAGS.max_cores):
            instance_id = self._create_instance()
            compute1.run_instance(self.context, instance_id)
            instance_ids1.append(instance_id)
            instance_id = self._create_instance()
            compute2.run_instance(self.context, instance_id)
            instance_ids2.append(instance_id)
        instance_id = self._create_instance()
        self.assertRaises(driver.NoValidHost,
                          self.scheduler.driver.schedule_run_instance,
                          self.context,
                          instance_id)
        for instance_id in instance_ids1:
            compute1.terminate_instance(self.context, instance_id)
        for instance_id in instance_ids2:
            compute2.terminate_instance(self.context, instance_id)
        compute1.kill()
        compute2.kill()

    def test_least_busy_host_gets_volume(self):
        """Ensures the host with less gigabytes gets the next one"""
        volume1 = service.Service('host1',
                                   'nova-volume',
                                   'volume',
                                   FLAGS.volume_manager)
        volume1.start()
        volume2 = service.Service('host2',
                                   'nova-volume',
                                   'volume',
                                   FLAGS.volume_manager)
        volume2.start()
        volume_id1 = self._create_volume()
        volume1.create_volume(self.context, volume_id1)
        volume_id2 = self._create_volume()
        host = self.scheduler.driver.schedule_create_volume(self.context,
                                                            volume_id2)
        self.assertEqual(host, 'host2')
        volume1.delete_volume(self.context, volume_id1)
        db.volume_destroy(self.context, volume_id2)
        volume1.kill()
        volume2.kill()

    def test_too_many_gigabytes(self):
        """Ensures we don't go over max gigabytes"""
        volume1 = service.Service('host1',
                                   'nova-volume',
                                   'volume',
                                   FLAGS.volume_manager)
        volume1.start()
        volume2 = service.Service('host2',
                                   'nova-volume',
                                   'volume',
                                   FLAGS.volume_manager)
        volume2.start()
        volume_ids1 = []
        volume_ids2 = []
        for index in xrange(FLAGS.max_gigabytes):
            volume_id = self._create_volume()
            volume1.create_volume(self.context, volume_id)
            volume_ids1.append(volume_id)
            volume_id = self._create_volume()
            volume2.create_volume(self.context, volume_id)
            volume_ids2.append(volume_id)
        volume_id = self._create_volume()
        self.assertRaises(driver.NoValidHost,
                          self.scheduler.driver.schedule_create_volume,
                          self.context,
                          volume_id)
        for volume_id in volume_ids1:
            volume1.delete_volume(self.context, volume_id)
        for volume_id in volume_ids2:
            volume2.delete_volume(self.context, volume_id)
        volume1.kill()
        volume2.kill()
