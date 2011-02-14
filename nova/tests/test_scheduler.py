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

import datetime
import mox

from mox import IgnoreArg
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import service
from nova import test
from nova import rpc
from nova import utils
from nova.auth import manager as auth_manager
from nova.scheduler import manager
from nova.scheduler import driver
from nova.compute import power_state
from nova.db.sqlalchemy import models


FLAGS = flags.FLAGS
flags.DECLARE('max_cores', 'nova.scheduler.simple')
flags.DECLARE('stub_network', 'nova.compute.manager')
flags.DECLARE('instances_path', 'nova.compute.manager')


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

    def test_show_host_resource_host_not_exit(self):
        """
        A testcase of driver.has_enough_resource
        given host does not exists.
        """
        scheduler = manager.SchedulerManager()
        dest = 'dummydest'
        ctxt = context.get_admin_context()

        self.mox.StubOutWithMock(manager, 'db', use_mock_anything=True)
        manager.db.service_get_all_compute_sorted(mox.IgnoreArg()).\
                                      AndReturn([])

        self.mox.ReplayAll()
        result = scheduler.show_host_resource(ctxt, dest)
        # ret should be dict
        keys = ['ret', 'msg']
        c1 = list(set(result.keys())) == list(set(keys))
        c2 = not result['ret']
        c3 = result['msg'].find('No such Host or not compute node') <= 0
        self.assertTrue(c1 and c2 and c3)
        self.mox.UnsetStubs()

    def test_show_host_resource_no_project(self):
        """
        A testcase of driver.show_host_resource
        no instance stays on the given host
        """
        scheduler = manager.SchedulerManager()
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        r0 = {'vcpus': 16, 'memory_mb': 32, 'local_gb': 100,
             'vcpus_used': 16, 'memory_mb_used': 32, 'local_gb_used': 10}
        service_ref = {'id': 1, 'host': dest}
        service_ref.update(r0)

        self.mox.StubOutWithMock(manager, 'db', use_mock_anything=True)
        manager.db.service_get_all_compute_sorted(mox.IgnoreArg()).\
                                      AndReturn([(service_ref, 0)])
        manager.db.instance_get_all_by_host(mox.IgnoreArg(), dest).\
                                      AndReturn([])

        self.mox.ReplayAll()
        result = scheduler.show_host_resource(ctxt, dest)
        # ret should be dict
        keys = ['ret', 'phy_resource', 'usage']
        c1 = list(set(result.keys())) == list(set(keys))
        c2 = result['ret']
        c3 = result['phy_resource'] == r0
        c4 = result['usage'] == {}
        self.assertTrue(c1 and c2 and c3 and c4)
        self.mox.UnsetStubs()

    def test_show_host_resource_works_correctly(self):
        """
        A testcase of driver.show_host_resource
        to make sure everything finished with no error.
        """
        scheduler = manager.SchedulerManager()
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        r0 = {'vcpus': 16, 'memory_mb': 32, 'local_gb': 100,
             'vcpus_used': 16, 'memory_mb_used': 32, 'local_gb_used': 10}
        r1 = {'vcpus': 10, 'memory_mb': 4, 'local_gb': 20}
        r2 = {'vcpus': 10, 'memory_mb': 20, 'local_gb': 30}
        service_ref = {'id': 1, 'host': dest}
        service_ref.update(r0)
        instance_ref2 = {'id': 2, 'project_id': 'p-01', 'host': 'dummy'}
        instance_ref2.update(r1)
        instance_ref3 = {'id': 3, 'project_id': 'p-02', 'host': 'dummy'}
        instance_ref3.update(r2)

        self.mox.StubOutWithMock(manager, 'db', use_mock_anything=True)
        manager.db.service_get_all_compute_sorted(mox.IgnoreArg()).\
                                      AndReturn([(service_ref, 0)])
        manager.db.instance_get_all_by_host(mox.IgnoreArg(), dest).\
                          AndReturn([instance_ref2, instance_ref3])
        for p in ['p-01', 'p-02']:
            manager.db.instance_get_vcpu_sum_by_host_and_project(
                                ctxt, dest, p).AndReturn(r2['vcpus'])
            manager.db.instance_get_memory_sum_by_host_and_project(
                            ctxt, dest, p).AndReturn(r2['memory_mb'])
            manager.db.instance_get_disk_sum_by_host_and_project(
                            ctxt, dest, p).AndReturn(r2['local_gb'])

        self.mox.ReplayAll()
        result = scheduler.show_host_resource(ctxt, dest)
        # ret should be dict
        keys = ['ret', 'phy_resource', 'usage']
        c1 = list(set(result.keys())) == list(set(keys))
        c2 = result['ret']
        c3 = result['phy_resource'] == r0
        c4 = result['usage'].keys() == ['p-01', 'p-02']
        c5 = result['usage']['p-01'] == r2
        c6 = result['usage']['p-02'] == r2
        self.assertTrue(c1 and c2 and c3 and c4 and c5 and c6)
        self.mox.UnsetStubs()


class ZoneSchedulerTestCase(test.TestCase):
    """Test case for zone scheduler"""
    def setUp(self):
        super(ZoneSchedulerTestCase, self).setUp()
        self.flags(scheduler_driver='nova.scheduler.zone.ZoneScheduler')

    def _create_service_model(self, **kwargs):
        service = db.sqlalchemy.models.Service()
        service.host = kwargs['host']
        service.disabled = False
        service.deleted = False
        service.report_count = 0
        service.binary = 'nova-compute'
        service.topic = 'compute'
        service.id = kwargs['id']
        service.availability_zone = kwargs['zone']
        service.created_at = datetime.datetime.utcnow()
        return service

    def test_with_two_zones(self):
        scheduler = manager.SchedulerManager()
        ctxt = context.get_admin_context()
        service_list = [self._create_service_model(id=1,
                                                   host='host1',
                                                   zone='zone1'),
                        self._create_service_model(id=2,
                                                   host='host2',
                                                   zone='zone2'),
                        self._create_service_model(id=3,
                                                   host='host3',
                                                   zone='zone2'),
                        self._create_service_model(id=4,
                                                   host='host4',
                                                   zone='zone2'),
                        self._create_service_model(id=5,
                                                   host='host5',
                                                   zone='zone2')]
        self.mox.StubOutWithMock(db, 'service_get_all_by_topic')
        arg = IgnoreArg()
        db.service_get_all_by_topic(arg, arg).AndReturn(service_list)
        self.mox.StubOutWithMock(rpc, 'cast', use_mock_anything=True)
        rpc.cast(ctxt,
                 'compute.host1',
                 {'method': 'run_instance',
                  'args': {'instance_id': 'i-ffffffff',
                           'availability_zone': 'zone1'}})
        self.mox.ReplayAll()
        scheduler.run_instance(ctxt,
                               'compute',
                               instance_id='i-ffffffff',
                               availability_zone='zone1')


class SimpleDriverTestCase(test.TestCase):
    """Test case for simple driver"""
    def setUp(self):
        super(SimpleDriverTestCase, self).setUp()
        self.flags(connection_type='fake',
                   stub_network=True,
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

    def _create_instance(self, **kwargs):
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
        inst['availability_zone'] = kwargs.get('availability_zone', None)
        return db.instance_create(self.context, inst)['id']

    def _create_volume(self):
        """Create a test volume"""
        vol = {}
        vol['image_id'] = 'ami-test'
        vol['reservation_id'] = 'r-fakeres'
        vol['size'] = 1
        vol['availability_zone'] = 'test'
        return db.volume_create(self.context, vol)['id']

    def test_doesnt_report_disabled_hosts_as_up(self):
        """Ensures driver doesn't find hosts before they are enabled"""
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
        s1 = db.service_get_by_args(self.context, 'host1', 'nova-compute')
        s2 = db.service_get_by_args(self.context, 'host2', 'nova-compute')
        db.service_update(self.context, s1['id'], {'disabled': True})
        db.service_update(self.context, s2['id'], {'disabled': True})
        hosts = self.scheduler.driver.hosts_up(self.context, 'compute')
        self.assertEqual(0, len(hosts))
        compute1.kill()
        compute2.kill()

    def test_reports_enabled_hosts_as_up(self):
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
        self.assertEqual(2, len(hosts))
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

    def test_specific_host_gets_instance(self):
        """Ensures if you set availability_zone it launches on that zone"""
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
        instance_id2 = self._create_instance(availability_zone='nova:host1')
        host = self.scheduler.driver.schedule_run_instance(self.context,
                                                           instance_id2)
        self.assertEqual('host1', host)
        compute1.terminate_instance(self.context, instance_id1)
        db.instance_destroy(self.context, instance_id2)
        compute1.kill()
        compute2.kill()

    def test_wont_sechedule_if_specified_host_is_down(self):
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        s1 = db.service_get_by_args(self.context, 'host1', 'nova-compute')
        now = datetime.datetime.utcnow()
        delta = datetime.timedelta(seconds=FLAGS.service_down_time * 2)
        past = now - delta
        db.service_update(self.context, s1['id'], {'updated_at': past})
        instance_id2 = self._create_instance(availability_zone='nova:host1')
        self.assertRaises(driver.WillNotSchedule,
                          self.scheduler.driver.schedule_run_instance,
                          self.context,
                          instance_id2)
        db.instance_destroy(self.context, instance_id2)
        compute1.kill()

    def test_will_schedule_on_disabled_host_if_specified(self):
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        s1 = db.service_get_by_args(self.context, 'host1', 'nova-compute')
        db.service_update(self.context, s1['id'], {'disabled': True})
        instance_id2 = self._create_instance(availability_zone='nova:host1')
        host = self.scheduler.driver.schedule_run_instance(self.context,
                                                           instance_id2)
        self.assertEqual('host1', host)
        db.instance_destroy(self.context, instance_id2)
        compute1.kill()

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

    def test_scheduler_live_migraiton_with_volume(self):
        """
        driver.scheduler_live_migration finishes successfully
        (volumes are attached to instances)
        This testcase make sure schedule_live_migration
        changes instance state from 'running' -> 'migrating'
        """
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-00000001', 'host': 'dummy',
                 'volumes': [{'id': 1}, {'id': 2}]}
        dest = 'dummydest'

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        # must be IgnoreArg() because scheduler changes ctxt's memory address
        driver.db.instance_get(mox.IgnoreArg(), i_ref['id']).AndReturn(i_ref)

        self.mox.StubOutWithMock(driver_i, '_live_migration_src_check')
        driver_i._live_migration_src_check(mox.IgnoreArg(), i_ref)
        self.mox.StubOutWithMock(driver_i, '_live_migration_dest_check')
        driver_i._live_migration_dest_check(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(driver_i, '_live_migration_common_check')
        driver_i._live_migration_common_check(mox.IgnoreArg(), i_ref, dest)
        driver.db.instance_set_state(mox.IgnoreArg(), i_ref['id'],
                                     power_state.PAUSED, 'migrating')
        for v in i_ref['volumes']:
            driver.db.volume_update(mox.IgnoreArg(), v['id'],
                                   {'status': 'migrating'})
        self.mox.StubOutWithMock(rpc, 'cast', use_mock_anything=True)
        kwargs = {'instance_id': i_ref['id'], 'dest': dest}
        rpc.cast(ctxt, db.queue_get_for(ctxt, topic, i_ref['host']),
                 {"method": 'live_migration', "args": kwargs})

        self.mox.ReplayAll()
        self.scheduler.live_migration(ctxt, topic,
                                      instance_id=i_ref['id'], dest=dest)
        self.mox.UnsetStubs()

    def test_scheduler_live_migraiton_no_volume(self):
        """
        driver.scheduler_live_migration finishes successfully
        (volumes are attached to instances)
        This testcase make sure schedule_live_migration
        changes instance state from 'running' -> 'migrating'
        """
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy', 'volumes': []}
        dest = 'dummydest'

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        # must be IgnoreArg() because scheduler changes ctxt's memory address
        driver.db.instance_get(mox.IgnoreArg(), i_ref['id']).AndReturn(i_ref)
        self.mox.StubOutWithMock(driver_i, '_live_migration_src_check')
        driver_i._live_migration_src_check(mox.IgnoreArg(), i_ref)
        self.mox.StubOutWithMock(driver_i, '_live_migration_dest_check')
        driver_i._live_migration_dest_check(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(driver_i, '_live_migration_common_check')
        driver_i._live_migration_common_check(mox.IgnoreArg(), i_ref, dest)
        driver.db.instance_set_state(mox.IgnoreArg(), i_ref['id'],
                                     power_state.PAUSED, 'migrating')
        self.mox.StubOutWithMock(rpc, 'cast', use_mock_anything=True)
        kwargs = {'instance_id': i_ref['id'], 'dest': dest}
        rpc.cast(ctxt, db.queue_get_for(ctxt, topic, i_ref['host']),
                 {"method": 'live_migration', "args": kwargs})

        self.mox.ReplayAll()
        self.scheduler.live_migration(ctxt, topic,
                                 instance_id=i_ref['id'], dest=dest)
        self.mox.UnsetStubs()

    def test_live_migraiton_src_check_instance_not_running(self):
        """
        A testcase of driver._live_migration_src_check.
        The instance given by instance_id is not running.
        """
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        dest = 'dummydest'
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy',
                 'volumes': [], 'state_description': 'migrating',
                 'state': power_state.RUNNING}

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_src_check(ctxt, i_ref)
        except exception.Invalid, e:
            self.assertTrue(e.message.find('is not running') > 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_src_check_volume_node_not_alive(self):
        """
        A testcase of driver._live_migration_src_check.
        Volume node is not alive if any volumes are attached to
        the given instance.
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy',
                 'volumes': [{'id': 1}, {'id': 2}],
                 'state_description': 'running', 'state': power_state.RUNNING}

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_topic(mox.IgnoreArg(), 'volume').\
                                           AndReturn([])

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_src_check(ctxt, i_ref)
        except exception.Invalid, e:
            self.assertTrue(e.message.find('volume node is not alive') >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_src_check_volume_node_not_alive(self):
        """
        A testcase of driver._live_migration_src_check.
        The testcase make sure src-compute node is alive.
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy', 'volumes': [],
                 'state_description': 'running', 'state': power_state.RUNNING}

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_topic(mox.IgnoreArg(), 'compute').\
                                           AndReturn([])

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_src_check(ctxt, i_ref)
        except exception.Invalid, e:
            self.assertTrue(e.message.find('is not alive') >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_src_check_works_correctly(self):
        """
        A testcase of driver._live_migration_src_check.
        The testcase make sure everything finished with no error.
        """
        driver_i = self.scheduler.driver
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy', 'volumes': [],
                 'state_description': 'running', 'state': power_state.RUNNING}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('host', i_ref['host'])

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_topic(mox.IgnoreArg(), 'compute').\
                                           AndReturn([service_ref])
        self.mox.StubOutWithMock(driver_i, 'service_is_up')
        driver_i.service_is_up(service_ref).AndReturn(True)

        self.mox.ReplayAll()
        ret = driver_i._live_migration_src_check(ctxt, i_ref)
        self.assertTrue(ret == None)
        self.mox.UnsetStubs()

    def test_live_migraiton_dest_check_service_not_exists(self):
        """
        A testcase of driver._live_migration_dst_check.
        Destination host does not exist.
        """
        driver_i = self.scheduler.driver
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('host', i_ref['host'])

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([])

        self.mox.ReplayAll()
        try:
            driver_i._live_migration_dest_check(ctxt, i_ref, dest)
        except exception.Invalid, e:
            self.assertTrue(e.message.find('does not exists') >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_dest_check_service_isnot_compute(self):
        """
        A testcase of driver._live_migration_dst_check.
        Destination host does not provide compute.
        """
        driver_i = self.scheduler.driver
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('host', i_ref['host'])
        service_ref.__setitem__('topic', 'api')

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])

        self.mox.ReplayAll()
        try:
            driver_i._live_migration_dest_check(ctxt, i_ref, dest)
        except exception.Invalid, e:
            self.assertTrue(e.message.find('must be compute node') >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_dest_check_service_not_alive(self):
        """
        A testcase of driver._live_migration_dst_check.
        Destination host compute service is not alive.
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('host', i_ref['host'])
        service_ref.__setitem__('topic', 'compute')

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])
        self.mox.StubOutWithMock(self.scheduler.driver, 'service_is_up')
        self.scheduler.driver.service_is_up(service_ref).AndReturn(False)

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_dest_check(ctxt, i_ref, dest)
        except exception.Invalid, e:
            self.assertTrue(e.message.find('is not alive') >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_dest_check_service_same_host(self):
        """
        A testcase of driver._live_migration_dst_check.
        Destination host is same as src host.
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummydest'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('host', i_ref['host'])
        service_ref.__setitem__('topic', 'compute')

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])
        self.mox.StubOutWithMock(self.scheduler.driver, 'service_is_up')
        self.scheduler.driver.service_is_up(service_ref).AndReturn(True)

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_dest_check(ctxt, i_ref, dest)
        except exception.Invalid, e:
            msg = 'is running now. choose other host'
            self.assertTrue(e.message.find(msg) >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_dest_check_service_works_correctly(self):
        """
        A testcase of driver._live_migration_dst_check.
        The testcase make sure everything finished with no error.
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummydest'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('host', i_ref['host'])
        service_ref.__setitem__('topic', 'compute')

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])
        self.mox.StubOutWithMock(self.scheduler.driver, 'service_is_up')
        self.scheduler.driver.service_is_up(service_ref).AndReturn(True)
        self.mox.StubOutWithMock(self.scheduler.driver, 'has_enough_resource')
        self.scheduler.driver.has_enough_resource(mox.IgnoreArg(), i_ref, dest)

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_dest_check(ctxt, i_ref, dest)
        except exception.Invalid, e:
            msg = 'is running now. choose other host'
            self.assertTrue(e.message.find(msg) >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_common_check_service_dest_not_exists(self):
        """
        A testcase of driver._live_migration_common_check.
        Destination host does not exist.
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy'}
        driver_i = self.scheduler.driver

        self.mox.StubOutWithMock(driver_i, 'mounted_on_same_shared_storage')
        driver_i.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([])

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_common_check(ctxt,
                                                               i_ref,
                                                               dest)
        except exception.Invalid, e:
            self.assertTrue(e.message.find('does not exists') >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_common_check_service_orig_not_exists(self):
        """
        A testcase of driver._live_migration_common_check.
        Original host(an instance launched on) does not exist.
        """
        dest = 'dummydest'
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01',
                 'host': 'dummy', 'launched_on': 'h1'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('topic', 'compute')
        service_ref.__setitem__('host', i_ref['host'])

        self.mox.StubOutWithMock(driver_i, 'mounted_on_same_shared_storage')
        driver_i.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])
        driver.db.service_get_all_by_host(mox.IgnoreArg(),
                                          i_ref['launched_on']).\
                                          AndReturn([])

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_common_check(ctxt,
                                                               i_ref,
                                                               dest)
        except exception.Invalid, e:
            msg = 'where instance was launched at) does not exists'
            self.assertTrue(e.message.find(msg) >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_common_check_service_different_hypervisor(self):
        """
        A testcase of driver._live_migration_common_check.
        Original host and dest host has different hypervisor type.
        """
        dest = 'dummydest'
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01',
                 'host': 'dummy', 'launched_on': 'h1'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('topic', 'compute')
        service_ref.__setitem__('hypervisor_type', 'kvm')
        service_ref2 = models.Service()
        service_ref2.__setitem__('id', 2)
        service_ref2.__setitem__('hypervisor_type', 'xen')

        self.mox.StubOutWithMock(driver_i, 'mounted_on_same_shared_storage')
        driver_i.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])
        driver.db.service_get_all_by_host(mox.IgnoreArg(),
                                          i_ref['launched_on']).\
                                          AndReturn([service_ref2])

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_common_check(ctxt,
                                                               i_ref,
                                                               dest)
        except exception.Invalid, e:
            msg = 'Different hypervisor type'
            self.assertTrue(e.message.find(msg) >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_common_check_service_different_version(self):
        """
        A testcase of driver._live_migration_common_check.
        Original host and dest host has different hypervisor version.
        """
        dest = 'dummydest'
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01',
                 'host': 'dummy', 'launched_on': 'h1'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('topic', 'compute')
        service_ref.__setitem__('hypervisor_version', 12000)
        service_ref2 = models.Service()
        service_ref2.__setitem__('id', 2)
        service_ref2.__setitem__('hypervisor_version', 12001)

        self.mox.StubOutWithMock(driver_i, 'mounted_on_same_shared_storage')
        driver_i.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])
        driver.db.service_get_all_by_host(mox.IgnoreArg(),
                                          i_ref['launched_on']).\
                                          AndReturn([service_ref2])

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_common_check(ctxt,
                                                               i_ref,
                                                               dest)
        except exception.Invalid, e:
            msg = 'Older hypervisor version'
            self.assertTrue(e.message.find(msg) >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_common_check_service_checking_cpuinfo_fail(self):
        """
        A testcase of driver._live_migration_common_check.
        Original host and dest host has different hypervisor version.
        """
        dest = 'dummydest'
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01',
                 'host': 'dummy', 'launched_on': 'h1'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('topic', 'compute')
        service_ref.__setitem__('hypervisor_version', 12000)
        service_ref2 = models.Service()
        service_ref2.__setitem__('id', 2)
        service_ref2.__setitem__('hypervisor_version', 12000)
        service_ref2.__setitem__('cpuinfo', '<cpu>info</cpu>')

        self.mox.StubOutWithMock(driver_i, 'mounted_on_same_shared_storage')
        driver_i.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])
        driver.db.service_get_all_by_host(mox.IgnoreArg(),
                                          i_ref['launched_on']).\
                                          AndReturn([service_ref2])
        driver.db.queue_get_for(mox.IgnoreArg(), FLAGS.compute_topic, dest)
        self.mox.StubOutWithMock(driver, 'rpc', use_mock_anything=True)
        driver.rpc.call(mox.IgnoreArg(), mox.IgnoreArg(),
            {"method": 'compare_cpu',
            "args": {'cpu_info': service_ref2['cpu_info']}}).\
             AndRaise(rpc.RemoteError('doesnt have compatibility to', '', ''))

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_common_check(ctxt,
                                                               i_ref,
                                                               dest)
        except rpc.RemoteError, e:
            msg = 'doesnt have compatibility to'
            self.assertTrue(e.message.find(msg) >= 0)
        self.mox.UnsetStubs()

    def test_live_migraiton_common_check_service_works_correctly(self):
        """
        A testcase of driver._live_migration_common_check.
        The testcase make sure everything finished with no error.
        """
        dest = 'dummydest'
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        i_ref = {'id': 1, 'hostname': 'i-01',
                 'host': 'dummy', 'launched_on': 'h1'}
        service_ref = models.Service()
        service_ref.__setitem__('id', 1)
        service_ref.__setitem__('topic', 'compute')
        service_ref.__setitem__('hypervisor_version', 12000)
        service_ref2 = models.Service()
        service_ref2.__setitem__('id', 2)
        service_ref2.__setitem__('hypervisor_version', 12000)
        service_ref2.__setitem__('cpuinfo', '<cpu>info</cpu>')

        self.mox.StubOutWithMock(driver_i, 'mounted_on_same_shared_storage')
        driver_i.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])
        driver.db.service_get_all_by_host(mox.IgnoreArg(),
                                          i_ref['launched_on']).\
                                          AndReturn([service_ref2])
        driver.db.queue_get_for(mox.IgnoreArg(), FLAGS.compute_topic, dest)
        self.mox.StubOutWithMock(driver, 'rpc', use_mock_anything=True)
        driver.rpc.call(mox.IgnoreArg(), mox.IgnoreArg(),
            {"method": 'compare_cpu',
            "args": {'cpu_info': service_ref2['cpu_info']}})

        self.mox.ReplayAll()
        ret = self.scheduler.driver._live_migration_common_check(ctxt,
                                                                 i_ref,
                                                                 dest)
        self.assertTrue(ret == None)
        self.mox.UnsetStubs()

    def test_has_enough_resource_lack_resource_memory(self):
        """
        A testcase of driver.has_enough_resource.
        Lack of memory_mb.(boundary check)
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        service_ref = {'id': 1,  'memory_mb': 32,
                       'memory_mb_used': 12, 'local_gb': 100}
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy',
                     'vcpus': 5, 'memory_mb': 20, 'local_gb': 10}

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])

        self.mox.ReplayAll()
        try:
            self.scheduler.driver.has_enough_resource(ctxt, i_ref, dest)
        except exception.NotEmpty, e:
            msg = 'is not capable to migrate'
            self.assertTrue(e.message.find(msg) >= 0)
        self.mox.UnsetStubs()
        self.mox.UnsetStubs()

    def test_has_enough_resource_works_correctly(self):
        """
        A testcase of driver.has_enough_resource
        to make sure everything finished with no error.
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        service_ref = {'id': 1, 'memory_mb': 120, 'memory_mb_used': 32}
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy',
                  'vcpus': 5, 'memory_mb': 8, 'local_gb': 10}

        self.mox.StubOutWithMock(driver, 'db', use_mock_anything=True)
        driver.db.service_get_all_by_host(mox.IgnoreArg(), dest).\
                                           AndReturn([service_ref])

        self.mox.ReplayAll()
        ret = self.scheduler.driver.has_enough_resource(ctxt, i_ref, dest)
        self.assertTrue(ret == None)
        self.mox.UnsetStubs()

    def test_mounted_on_same_shared_storage_cannot_make_tmpfile(self):
        """
        A testcase of driver.mounted_on_same_shared_storage
        checks log message when dest host cannot make tmpfile.
        """
        dest = 'dummydest'
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        fpath = '/test/20110127120000'
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy'}

        self.mox.StubOutWithMock(driver, 'rpc', use_mock_anything=True)
        driver.rpc.call(mox.IgnoreArg(),
            db.queue_get_for(ctxt, FLAGS.compute_topic, dest),
            {"method": 'mktmpfile'}).AndRaise(rpc.RemoteError('', '', ''))
        self.mox.StubOutWithMock(driver.logging, 'error')
        msg = _("Cannot create tmpfile at %s to confirm shared storage.")
        driver.logging.error(msg % FLAGS.instances_path)

        self.mox.ReplayAll()
        self.assertRaises(rpc.RemoteError,
                          driver_i.mounted_on_same_shared_storage,
                          ctxt, i_ref, dest)
        self.mox.UnsetStubs()

    def test_mounted_on_same_shared_storage_cannot_comfirm_tmpfile(self):
        """
        A testcase of driver.mounted_on_same_shared_storage
        checks log message when src host cannot comfirm tmpfile.
        """
        dest = 'dummydest'
        driver_i = self.scheduler.driver
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        fpath = '/test/20110127120000'
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy'}

        self.mox.StubOutWithMock(driver, 'rpc', use_mock_anything=True)
        driver.rpc.call(mox.IgnoreArg(),
            db.queue_get_for(ctxt, FLAGS.compute_topic, dest),
            {"method": 'mktmpfile'}).AndReturn(fpath)
        driver.rpc.call(mox.IgnoreArg(),
            db.queue_get_for(ctxt, FLAGS.compute_topic, i_ref['host']),
            {"method": 'confirm_tmpfile', "args": {'path': fpath}}).\
            AndRaise(rpc.RemoteError('', '', ''))
        self.mox.StubOutWithMock(driver.logging, 'error')
        msg = _("Cannot create tmpfile at %s to confirm shared storage.")
        driver.logging.error(msg % FLAGS.instances_path)

        self.mox.ReplayAll()
        self.assertRaises(rpc.RemoteError,
                          driver_i.mounted_on_same_shared_storage,
                          ctxt, i_ref, dest)
        self.mox.UnsetStubs()

    def test_mounted_on_same_shared_storage_works_correctly(self):
        """
        A testcase of driver.mounted_on_same_shared_storage
        to make sure everything finished with no error.
        """
        dest = 'dummydest'
        ctxt = context.get_admin_context()
        topic = FLAGS.compute_topic
        fpath = '/test/20110127120000'
        i_ref = {'id': 1, 'hostname': 'i-01', 'host': 'dummy'}

        self.mox.StubOutWithMock(driver, 'rpc', use_mock_anything=True)
        driver.rpc.call(mox.IgnoreArg(),
            db.queue_get_for(mox.IgnoreArg(), FLAGS.compute_topic, dest),
            {"method": 'mktmpfile'}).AndReturn(fpath)
        driver.rpc.call(mox.IgnoreArg(),
                        db.queue_get_for(mox.IgnoreArg(),
                                         FLAGS.compute_topic,
                                         i_ref['host']),
                        {"method": 'confirm_tmpfile', "args": {'path': fpath}})

        self.mox.ReplayAll()
        ret = self.scheduler.driver.mounted_on_same_shared_storage(ctxt,
                                                                   i_ref,
                                                                   dest)
        self.assertTrue(ret == None)
        self.mox.UnsetStubs()
