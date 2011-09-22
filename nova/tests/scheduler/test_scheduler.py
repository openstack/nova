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
import stubout

from novaclient import v1_1 as novaclient
from novaclient import exceptions as novaclient_exceptions

from mox import IgnoreArg
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import service
from nova import test
from nova import rpc
from nova import utils
from nova.scheduler import api
from nova.scheduler import driver
from nova.scheduler import manager
from nova.scheduler import multi
from nova.compute import power_state
from nova.compute import vm_states


FLAGS = flags.FLAGS
flags.DECLARE('max_cores', 'nova.scheduler.simple')
flags.DECLARE('stub_network', 'nova.compute.manager')
flags.DECLARE('instances_path', 'nova.compute.manager')


FAKE_UUID_NOT_FOUND = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


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
        driver = 'nova.tests.scheduler.test_scheduler.TestDriver'
        self.flags(scheduler_driver=driver)

    def _create_compute_service(self):
        """Create compute-manager(ComputeNode and Service record)."""
        ctxt = context.get_admin_context()
        dic = {'host': 'dummy', 'binary': 'nova-compute', 'topic': 'compute',
               'report_count': 0, 'availability_zone': 'dummyzone'}
        s_ref = db.service_create(ctxt, dic)

        dic = {'service_id': s_ref['id'],
               'vcpus': 16, 'memory_mb': 32, 'local_gb': 100,
               'vcpus_used': 16, 'memory_mb_used': 32, 'local_gb_used': 10,
               'hypervisor_type': 'qemu', 'hypervisor_version': 12003,
               'cpu_info': ''}
        db.compute_node_create(ctxt, dic)

        return db.service_get(ctxt, s_ref['id'])

    def _create_instance(self, **kwargs):
        """Create a test instance"""
        ctxt = context.get_admin_context()
        inst = {}
        inst['user_id'] = 'admin'
        inst['project_id'] = kwargs.get('project_id', 'fake')
        inst['host'] = kwargs.get('host', 'dummy')
        inst['vcpus'] = kwargs.get('vcpus', 1)
        inst['memory_mb'] = kwargs.get('memory_mb', 10)
        inst['local_gb'] = kwargs.get('local_gb', 20)
        inst['vm_state'] = kwargs.get('vm_state', vm_states.ACTIVE)
        inst['power_state'] = kwargs.get('power_state', power_state.RUNNING)
        inst['task_state'] = kwargs.get('task_state', None)
        return db.instance_create(ctxt, inst)

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

    def test_show_host_resources_host_not_exit(self):
        """A host given as an argument does not exists."""

        scheduler = manager.SchedulerManager()
        dest = 'dummydest'
        ctxt = context.get_admin_context()

        self.assertRaises(exception.NotFound, scheduler.show_host_resources,
                          ctxt, dest)
        #TODO(bcwaldon): reimplement this functionality
        #c1 = (e.message.find(_("does not exist or is not a "
        #                       "compute node.")) >= 0)

    def _dic_is_equal(self, dic1, dic2, keys=None):
        """Compares 2 dictionary contents(Helper method)"""
        if not keys:
            keys = ['vcpus', 'memory_mb', 'local_gb',
                    'vcpus_used', 'memory_mb_used', 'local_gb_used']

        for key in keys:
            if not (dic1[key] == dic2[key]):
                return False
        return True

    def test_show_host_resources_no_project(self):
        """No instance are running on the given host."""

        scheduler = manager.SchedulerManager()
        ctxt = context.get_admin_context()
        s_ref = self._create_compute_service()

        result = scheduler.show_host_resources(ctxt, s_ref['host'])

        # result checking
        c1 = ('resource' in result and 'usage' in result)
        compute_node = s_ref['compute_node'][0]
        c2 = self._dic_is_equal(result['resource'], compute_node)
        c3 = result['usage'] == {}
        self.assertTrue(c1 and c2 and c3)
        db.service_destroy(ctxt, s_ref['id'])

    def test_show_host_resources_works_correctly(self):
        """Show_host_resources() works correctly as expected."""

        scheduler = manager.SchedulerManager()
        ctxt = context.get_admin_context()
        s_ref = self._create_compute_service()
        i_ref1 = self._create_instance(project_id='p-01', host=s_ref['host'])
        i_ref2 = self._create_instance(project_id='p-02', vcpus=3,
                                       host=s_ref['host'])

        result = scheduler.show_host_resources(ctxt, s_ref['host'])

        c1 = ('resource' in result and 'usage' in result)
        compute_node = s_ref['compute_node'][0]
        c2 = self._dic_is_equal(result['resource'], compute_node)
        c3 = result['usage'].keys() == ['p-01', 'p-02']
        keys = ['vcpus', 'memory_mb', 'local_gb']
        c4 = self._dic_is_equal(result['usage']['p-01'], i_ref1, keys)
        c5 = self._dic_is_equal(result['usage']['p-02'], i_ref2, keys)
        self.assertTrue(c1 and c2 and c3 and c4 and c5)

        db.service_destroy(ctxt, s_ref['id'])
        db.instance_destroy(ctxt, i_ref1['id'])
        db.instance_destroy(ctxt, i_ref2['id'])


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
        service.created_at = utils.utcnow()
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
        self.context = context.get_admin_context()
        self.user_id = 'fake'
        self.project_id = 'fake'

    def _create_instance(self, **kwargs):
        """Create a test instance"""
        inst = {}
        # NOTE(jk0): If an integer is passed as the image_ref, the image
        # service will use the default image service (in this case, the fake).
        inst['image_ref'] = '1'
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['instance_type_id'] = '1'
        inst['vcpus'] = kwargs.get('vcpus', 1)
        inst['ami_launch_index'] = 0
        inst['availability_zone'] = kwargs.get('availability_zone', None)
        inst['host'] = kwargs.get('host', 'dummy')
        inst['memory_mb'] = kwargs.get('memory_mb', 20)
        inst['local_gb'] = kwargs.get('local_gb', 30)
        inst['launched_on'] = kwargs.get('launghed_on', 'dummy')
        inst['vm_state'] = kwargs.get('vm_state', vm_states.ACTIVE)
        inst['task_state'] = kwargs.get('task_state', None)
        inst['power_state'] = kwargs.get('power_state', power_state.RUNNING)
        return db.instance_create(self.context, inst)['id']

    def _create_volume(self):
        """Create a test volume"""
        vol = {}
        vol['size'] = 1
        vol['availability_zone'] = 'test'
        return db.volume_create(self.context, vol)['id']

    def _create_compute_service(self, **kwargs):
        """Create a compute service."""

        dic = {'binary': 'nova-compute', 'topic': 'compute',
               'report_count': 0, 'availability_zone': 'dummyzone'}
        dic['host'] = kwargs.get('host', 'dummy')
        s_ref = db.service_create(self.context, dic)
        if 'created_at' in kwargs.keys() or 'updated_at' in kwargs.keys():
            t = utils.utcnow() - datetime.timedelta(0)
            dic['created_at'] = kwargs.get('created_at', t)
            dic['updated_at'] = kwargs.get('updated_at', t)
            db.service_update(self.context, s_ref['id'], dic)

        dic = {'service_id': s_ref['id'],
               'vcpus': 16, 'memory_mb': 32, 'local_gb': 100,
               'vcpus_used': 16, 'local_gb_used': 10,
               'hypervisor_type': 'qemu', 'hypervisor_version': 12003,
               'cpu_info': ''}
        dic['memory_mb_used'] = kwargs.get('memory_mb_used', 32)
        dic['hypervisor_type'] = kwargs.get('hypervisor_type', 'qemu')
        dic['hypervisor_version'] = kwargs.get('hypervisor_version', 12003)
        db.compute_node_create(self.context, dic)
        return db.service_get(self.context, s_ref['id'])

    def test_doesnt_report_disabled_hosts_as_up_no_queue(self):
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

    def test_reports_enabled_hosts_as_up_no_queue(self):
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

    def test_least_busy_host_gets_instance_no_queue(self):
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

    def test_specific_host_gets_instance_no_queue(self):
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

    def test_wont_schedule_if_specified_host_is_down_no_queue(self):
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        s1 = db.service_get_by_args(self.context, 'host1', 'nova-compute')
        now = utils.utcnow()
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

    def test_will_schedule_on_disabled_host_if_specified_no_queue(self):
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

    def test_too_many_cores_no_queue(self):
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

    def test_least_busy_host_gets_volume_no_queue(self):
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

    def test_doesnt_report_disabled_hosts_as_up2(self):
        """Ensures driver doesn't find hosts before they are enabled"""
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')
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
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')
        hosts = self.scheduler.driver.hosts_up(self.context, 'compute')
        self.assertEqual(2, len(hosts))
        compute1.kill()
        compute2.kill()

    def test_least_busy_host_gets_instance(self):
        """Ensures the host with less cores gets the next one"""
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')
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
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')
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
        compute1 = self.start_service('compute', host='host1')
        s1 = db.service_get_by_args(self.context, 'host1', 'nova-compute')
        now = utils.utcnow()
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
        compute1 = self.start_service('compute', host='host1')
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
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')
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
        db.instance_destroy(self.context, instance_id)
        for instance_id in instance_ids1:
            compute1.terminate_instance(self.context, instance_id)
        for instance_id in instance_ids2:
            compute2.terminate_instance(self.context, instance_id)
        compute1.kill()
        compute2.kill()

    def test_least_busy_host_gets_volume(self):
        """Ensures the host with less gigabytes gets the next one"""
        volume1 = self.start_service('volume', host='host1')
        volume2 = self.start_service('volume', host='host2')
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
        volume1 = self.start_service('volume', host='host1')
        volume2 = self.start_service('volume', host='host2')
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

    def test_scheduler_live_migration_with_volume(self):
        """scheduler_live_migration() works correctly as expected.

        Also, checks instance state is changed from 'running' -> 'migrating'.

        """

        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)
        dic = {'instance_id': instance_id, 'size': 1}
        v_ref = db.volume_create(self.context, dic)

        # cannot check 2nd argument b/c the addresses of instance object
        # is different.
        driver_i = self.scheduler.driver
        nocare = mox.IgnoreArg()
        self.mox.StubOutWithMock(driver_i, '_live_migration_src_check')
        self.mox.StubOutWithMock(driver_i, '_live_migration_dest_check')
        self.mox.StubOutWithMock(driver_i, '_live_migration_common_check')
        driver_i._live_migration_src_check(nocare, nocare)
        driver_i._live_migration_dest_check(nocare, nocare,
                                            i_ref['host'], False)
        driver_i._live_migration_common_check(nocare, nocare,
                                              i_ref['host'], False)
        self.mox.StubOutWithMock(rpc, 'cast', use_mock_anything=True)
        kwargs = {'instance_id': instance_id, 'dest': i_ref['host'],
                  'block_migration': False}
        rpc.cast(self.context,
                 db.queue_get_for(nocare, FLAGS.compute_topic, i_ref['host']),
                 {"method": 'live_migration', "args": kwargs})

        self.mox.ReplayAll()
        self.scheduler.live_migration(self.context, FLAGS.compute_topic,
                                      instance_id=instance_id,
                                      dest=i_ref['host'],
                                      block_migration=False)

        i_ref = db.instance_get(self.context, instance_id)
        self.assertTrue(i_ref['vm_state'] == vm_states.MIGRATING)
        db.instance_destroy(self.context, instance_id)
        db.volume_destroy(self.context, v_ref['id'])

    def test_live_migration_src_check_instance_not_running(self):
        """The instance given by instance_id is not running."""

        instance_id = self._create_instance(power_state=power_state.NOSTATE)
        i_ref = db.instance_get(self.context, instance_id)

        try:
            self.scheduler.driver._live_migration_src_check(self.context,
                                                            i_ref)
        except exception.Invalid, e:
            c = (e.message.find('is not running') > 0)

        self.assertTrue(c)
        db.instance_destroy(self.context, instance_id)

    def test_live_migration_src_check_volume_node_not_alive(self):
        """Raise exception when volume node is not alive."""

        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)
        dic = {'instance_id': instance_id, 'size': 1}
        v_ref = db.volume_create(self.context, {'instance_id': instance_id,
                                                'size': 1})
        t1 = utils.utcnow() - datetime.timedelta(1)
        dic = {'created_at': t1, 'updated_at': t1, 'binary': 'nova-volume',
               'topic': 'volume', 'report_count': 0}
        s_ref = db.service_create(self.context, dic)

        self.assertRaises(exception.VolumeServiceUnavailable,
                          self.scheduler.driver.schedule_live_migration,
                          self.context, instance_id, i_ref['host'])

        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])
        db.volume_destroy(self.context, v_ref['id'])

    def test_live_migration_src_check_compute_node_not_alive(self):
        """Confirms src-compute node is alive."""
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)
        t = utils.utcnow() - datetime.timedelta(10)
        s_ref = self._create_compute_service(created_at=t, updated_at=t,
                                             host=i_ref['host'])

        self.assertRaises(exception.ComputeServiceUnavailable,
                          self.scheduler.driver._live_migration_src_check,
                          self.context, i_ref)

        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_src_check_works_correctly(self):
        """Confirms this method finishes with no error."""
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)
        s_ref = self._create_compute_service(host=i_ref['host'])

        ret = self.scheduler.driver._live_migration_src_check(self.context,
                                                              i_ref)

        self.assertTrue(ret is None)
        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_dest_check_not_alive(self):
        """Confirms exception raises in case dest host does not exist."""
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)
        t = utils.utcnow() - datetime.timedelta(10)
        s_ref = self._create_compute_service(created_at=t, updated_at=t,
                                             host=i_ref['host'])

        self.assertRaises(exception.ComputeServiceUnavailable,
                          self.scheduler.driver._live_migration_dest_check,
                          self.context, i_ref, i_ref['host'], False)

        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_dest_check_service_same_host(self):
        """Confirms exceptioin raises in case dest and src is same host."""
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)
        s_ref = self._create_compute_service(host=i_ref['host'])

        self.assertRaises(exception.UnableToMigrateToSelf,
                          self.scheduler.driver._live_migration_dest_check,
                          self.context, i_ref, i_ref['host'], False)

        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_dest_check_service_lack_memory(self):
        """Confirms exception raises when dest doesn't have enough memory."""
        instance_id = self._create_instance()
        instance_id2 = self._create_instance(host='somewhere',
                                             memory_mb=12)
        i_ref = db.instance_get(self.context, instance_id)
        s_ref = self._create_compute_service(host='somewhere')

        self.assertRaises(exception.MigrationError,
                          self.scheduler.driver._live_migration_dest_check,
                          self.context, i_ref, 'somewhere', False)

        db.instance_destroy(self.context, instance_id)
        db.instance_destroy(self.context, instance_id2)
        db.service_destroy(self.context, s_ref['id'])

    def test_block_migration_dest_check_service_lack_disk(self):
        """Confirms exception raises when dest doesn't have enough disk."""
        instance_id = self._create_instance()
        instance_id2 = self._create_instance(host='somewhere',
                                             local_gb=70)
        i_ref = db.instance_get(self.context, instance_id)
        s_ref = self._create_compute_service(host='somewhere')

        self.assertRaises(exception.MigrationError,
                          self.scheduler.driver._live_migration_dest_check,
                          self.context, i_ref, 'somewhere', True)

        db.instance_destroy(self.context, instance_id)
        db.instance_destroy(self.context, instance_id2)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_dest_check_service_works_correctly(self):
        """Confirms method finishes with no error."""
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)
        s_ref = self._create_compute_service(host='somewhere',
                                             memory_mb_used=5)

        ret = self.scheduler.driver._live_migration_dest_check(self.context,
                                                             i_ref,
                                                             'somewhere',
                                                             False)
        self.assertTrue(ret is None)
        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_common_check_service_orig_not_exists(self):
        """Destination host does not exist."""

        dest = 'dummydest'
        # mocks for live_migration_common_check()
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)
        t1 = utils.utcnow() - datetime.timedelta(10)
        s_ref = self._create_compute_service(created_at=t1, updated_at=t1,
                                             host=dest)

        # mocks for mounted_on_same_shared_storage()
        fpath = '/test/20110127120000'
        self.mox.StubOutWithMock(driver, 'rpc', use_mock_anything=True)
        topic = FLAGS.compute_topic
        driver.rpc.call(mox.IgnoreArg(),
            db.queue_get_for(self.context, topic, dest),
            {"method": 'create_shared_storage_test_file'}).AndReturn(fpath)
        driver.rpc.call(mox.IgnoreArg(),
            db.queue_get_for(mox.IgnoreArg(), topic, i_ref['host']),
            {"method": 'check_shared_storage_test_file',
             "args": {'filename': fpath}})
        driver.rpc.call(mox.IgnoreArg(),
            db.queue_get_for(mox.IgnoreArg(), topic, dest),
            {"method": 'cleanup_shared_storage_test_file',
             "args": {'filename': fpath}})

        self.mox.ReplayAll()
        #self.assertRaises(exception.SourceHostUnavailable,
        self.assertRaises(exception.FileNotFound,
                          self.scheduler.driver._live_migration_common_check,
                          self.context, i_ref, dest, False)

        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_common_check_service_different_hypervisor(self):
        """Original host and dest host has different hypervisor type."""
        dest = 'dummydest'
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)

        # compute service for destination
        s_ref = self._create_compute_service(host=i_ref['host'])
        # compute service for original host
        s_ref2 = self._create_compute_service(host=dest, hypervisor_type='xen')

        # mocks
        driver = self.scheduler.driver
        self.mox.StubOutWithMock(driver, 'mounted_on_same_shared_storage')
        driver.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidHypervisorType,
                          self.scheduler.driver._live_migration_common_check,
                          self.context, i_ref, dest, False)

        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])
        db.service_destroy(self.context, s_ref2['id'])

    def test_live_migration_common_check_service_different_version(self):
        """Original host and dest host has different hypervisor version."""
        dest = 'dummydest'
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)

        # compute service for destination
        s_ref = self._create_compute_service(host=i_ref['host'])
        # compute service for original host
        s_ref2 = self._create_compute_service(host=dest,
                                              hypervisor_version=12002)

        # mocks
        driver = self.scheduler.driver
        self.mox.StubOutWithMock(driver, 'mounted_on_same_shared_storage')
        driver.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)

        self.mox.ReplayAll()
        self.assertRaises(exception.DestinationHypervisorTooOld,
                          self.scheduler.driver._live_migration_common_check,
                          self.context, i_ref, dest, False)

        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])
        db.service_destroy(self.context, s_ref2['id'])

    def test_live_migration_common_check_checking_cpuinfo_fail(self):
        """Raise excetion when original host doen't have compatible cpu."""

        dest = 'dummydest'
        instance_id = self._create_instance()
        i_ref = db.instance_get(self.context, instance_id)

        # compute service for destination
        s_ref = self._create_compute_service(host=i_ref['host'])
        # compute service for original host
        s_ref2 = self._create_compute_service(host=dest)

        # mocks
        driver = self.scheduler.driver
        self.mox.StubOutWithMock(driver, 'mounted_on_same_shared_storage')
        driver.mounted_on_same_shared_storage(mox.IgnoreArg(), i_ref, dest)
        self.mox.StubOutWithMock(rpc, 'call', use_mock_anything=True)
        rpc.call(mox.IgnoreArg(), mox.IgnoreArg(),
            {"method": 'compare_cpu',
            "args": {'cpu_info': s_ref2['compute_node'][0]['cpu_info']}}).\
             AndRaise(rpc.RemoteError("doesn't have compatibility to", "", ""))

        self.mox.ReplayAll()
        try:
            self.scheduler.driver._live_migration_common_check(self.context,
                                                               i_ref,
                                                               dest,
                                                               False)
        except rpc.RemoteError, e:
            c = (e.message.find(_("doesn't have compatibility to")) >= 0)

        self.assertTrue(c)
        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])
        db.service_destroy(self.context, s_ref2['id'])


class MultiDriverTestCase(SimpleDriverTestCase):
    """Test case for multi driver."""

    def setUp(self):
        super(MultiDriverTestCase, self).setUp()
        self.flags(connection_type='fake',
                   stub_network=True,
                   max_cores=4,
                   max_gigabytes=4,
                   network_manager='nova.network.manager.FlatManager',
                   volume_driver='nova.volume.driver.FakeISCSIDriver',
                   compute_scheduler_driver=('nova.scheduler.simple'
                                             '.SimpleScheduler'),
                   volume_scheduler_driver=('nova.scheduler.simple'
                                            '.SimpleScheduler'),
                   scheduler_driver='nova.scheduler.multi.MultiScheduler')
        self.scheduler = manager.SchedulerManager()


class FakeZone(object):
    def __init__(self, id, api_url, username, password):
        self.id = id
        self.api_url = api_url
        self.username = username
        self.password = password


ZONE_API_URL1 = "http://1.example.com"
ZONE_API_URL2 = "http://2.example.com"


def zone_get_all(context):
    return [
                FakeZone(1, ZONE_API_URL1, 'bob', 'xxx'),
                FakeZone(2, ZONE_API_URL2, 'bob', 'xxx'),
           ]


def fake_instance_get_by_uuid(context, uuid):
    if FAKE_UUID_NOT_FOUND:
        raise exception.InstanceNotFound(instance_id=uuid)
    else:
        return {'id': 1}


class FakeRerouteCompute(api.reroute_compute):
    def __init__(self, method_name, id_to_return=1):
        super(FakeRerouteCompute, self).__init__(method_name)
        self.id_to_return = id_to_return

    def _call_child_zones(self, zones, function):
        return []

    def get_collection_context_and_id(self, args, kwargs):
        return ("servers", None, self.id_to_return)

    def unmarshall_result(self, zone_responses):
        return dict(magic="found me")


def go_boom(self, context, instance):
    raise exception.InstanceNotFound(instance_id=instance)


def found_instance(self, context, instance):
    return dict(name='myserver')


class FakeResource(object):
    def __init__(self, attribute_dict):
        for k, v in attribute_dict.iteritems():
            setattr(self, k, v)

    def pause(self):
        pass


class ZoneRedirectTest(test.TestCase):
    def setUp(self):
        super(ZoneRedirectTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()

        self.stubs.Set(db, 'zone_get_all', zone_get_all)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid)
        self.flags(enable_zone_routing=True)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(ZoneRedirectTest, self).tearDown()

    def test_trap_found_locally(self):
        decorator = FakeRerouteCompute("foo")
        try:
            result = decorator(found_instance)(None, None, 1)
        except api.RedirectResult, e:
            self.fail(_("Successful database hit should succeed"))

    def test_trap_not_found_locally_id_passed(self):
        """When an integer ID is not found locally, we cannot reroute to
        another zone, so just return InstanceNotFound exception
        """
        decorator = FakeRerouteCompute("foo")
        self.assertRaises(exception.InstanceNotFound,
            decorator(go_boom), None, None, 1)

    def test_trap_not_found_locally_uuid_passed(self):
        """When a UUID is found, if the item isn't found locally, we should
        try to reroute to a child zone to see if they have it
        """
        decorator = FakeRerouteCompute("foo", id_to_return=FAKE_UUID_NOT_FOUND)
        try:
            result = decorator(go_boom)(None, None, 1)
            self.fail(_("Should have rerouted."))
        except api.RedirectResult, e:
            self.assertEquals(e.results['magic'], 'found me')

    def test_routing_flags(self):
        self.flags(enable_zone_routing=False)
        decorator = FakeRerouteCompute("foo")
        self.assertRaises(exception.InstanceNotFound, decorator(go_boom),
                          None, None, 1)

    def test_get_collection_context_and_id(self):
        decorator = api.reroute_compute("foo")
        self.assertEquals(decorator.get_collection_context_and_id(
            (None, 10, 20), {}), ("servers", 10, 20))
        self.assertEquals(decorator.get_collection_context_and_id(
            (None, 11,), dict(instance_id=21)), ("servers", 11, 21))
        self.assertEquals(decorator.get_collection_context_and_id(
            (None,), dict(context=12, instance_id=22)), ("servers", 12, 22))

    def test_unmarshal_single_server(self):
        decorator = api.reroute_compute("foo")
        decorator.item_uuid = 'fake_uuid'
        self.assertRaises(exception.InstanceNotFound,
                decorator.unmarshall_result, [])
        self.assertEquals(decorator.unmarshall_result(
                [FakeResource(dict(a=1, b=2)), ]),
                dict(server=dict(a=1, b=2)))
        self.assertEquals(decorator.unmarshall_result(
                [FakeResource(dict(a=1, _b=2)), ]),
                dict(server=dict(a=1,)))
        self.assertEquals(decorator.unmarshall_result(
                [FakeResource(dict(a=1, manager=2)), ]),
                dict(server=dict(a=1,)))
        self.assertEquals(decorator.unmarshall_result(
                [FakeResource(dict(_a=1, manager=2)), ]),
                dict(server={}))

    def test_one_zone_down_no_instances(self):

        def _fake_issue_novaclient_command(nova, zone, *args, **kwargs):
            return None

        class FakeNovaClientWithFailure(object):
            def __init__(self, username, password, method, api_url):
                self.api_url = api_url

            def authenticate(self):
                if self.api_url == ZONE_API_URL2:
                    raise novaclient_exceptions.BadRequest('foo')

        self.stubs.Set(api, '_issue_novaclient_command',
                _fake_issue_novaclient_command)
        self.stubs.Set(api.novaclient, 'Client', FakeNovaClientWithFailure)

        @api.reroute_compute("get")
        def do_get(self, context, uuid):
            pass

        self.assertRaises(exception.ZoneRequestError,
                do_get, None, {}, FAKE_UUID)

    def test_one_zone_down_got_instance(self):

        def _fake_issue_novaclient_command(nova, zone, *args, **kwargs):
            class FakeServer(object):
                def __init__(self):
                    self.id = FAKE_UUID
                    self.test = '1234'
            return FakeServer()

        class FakeNovaClientWithFailure(object):
            def __init__(self, username, password, method, api_url):
                self.api_url = api_url

            def authenticate(self):
                if self.api_url == ZONE_API_URL2:
                    raise novaclient_exceptions.BadRequest('foo')

        self.stubs.Set(api, '_issue_novaclient_command',
                _fake_issue_novaclient_command)
        self.stubs.Set(api.novaclient, 'Client', FakeNovaClientWithFailure)

        @api.reroute_compute("get")
        def do_get(self, context, uuid):
            pass

        try:
            do_get(None, {}, FAKE_UUID)
        except api.RedirectResult, e:
            results = e.results
            self.assertIn('server', results)
            self.assertEqual(results['server']['id'], FAKE_UUID)
            self.assertEqual(results['server']['test'], '1234')
        except Exception, e:
            self.fail(_("RedirectResult should have been raised"))
        else:
            self.fail(_("RedirectResult should have been raised"))

    def test_zones_up_no_instances(self):

        def _fake_issue_novaclient_command(nova, zone, *args, **kwargs):
            return None

        class FakeNovaClientNoFailure(object):
            def __init__(self, username, password, method, api_url):
                pass

            def authenticate(self):
                return

        self.stubs.Set(api, '_issue_novaclient_command',
                _fake_issue_novaclient_command)
        self.stubs.Set(api.novaclient, 'Client', FakeNovaClientNoFailure)

        @api.reroute_compute("get")
        def do_get(self, context, uuid):
            pass

        self.assertRaises(exception.InstanceNotFound,
                do_get, None, {}, FAKE_UUID)


class FakeServerCollection(object):
    def get(self, instance_id):
        return FakeResource(dict(a=10, b=20))

    def find(self, name):
        return FakeResource(dict(a=11, b=22))


class FakeEmptyServerCollection(object):
    def get(self, f):
        raise novaclient_exceptions.NotFound(1)

    def find(self, name):
        raise novaclient_exceptions.NotFound(2)


class FakeNovaClient(object):
    def __init__(self, collection, *args, **kwargs):
        self.servers = collection


class DynamicNovaClientTest(test.TestCase):
    def test_issue_novaclient_command_found(self):
        zone = FakeZone(1, 'http://example.com', 'bob', 'xxx')
        self.assertEquals(api._issue_novaclient_command(
                    FakeNovaClient(FakeServerCollection()),
                    zone, "servers", "get", 100).a, 10)

        self.assertEquals(api._issue_novaclient_command(
                    FakeNovaClient(FakeServerCollection()),
                    zone, "servers", "find", name="test").b, 22)

        self.assertEquals(api._issue_novaclient_command(
                    FakeNovaClient(FakeServerCollection()),
                    zone, "servers", "pause", 100), None)

    def test_issue_novaclient_command_not_found(self):
        zone = FakeZone(1, 'http://example.com', 'bob', 'xxx')
        self.assertEquals(api._issue_novaclient_command(
                    FakeNovaClient(FakeEmptyServerCollection()),
                    zone, "servers", "get", 100), None)

        self.assertEquals(api._issue_novaclient_command(
                    FakeNovaClient(FakeEmptyServerCollection()),
                    zone, "servers", "find", name="test"), None)

        self.assertEquals(api._issue_novaclient_command(
                    FakeNovaClient(FakeEmptyServerCollection()),
                    zone, "servers", "any", "name"), None)


class FakeZonesProxy(object):
    def do_something(self, *args, **kwargs):
        return 42

    def raises_exception(self, *args, **kwargs):
        raise Exception('testing')


class FakeNovaClientZones(object):
    def __init__(self, *args, **kwargs):
        self.zones = FakeZonesProxy()

    def authenticate(self):
        pass


class CallZoneMethodTest(test.TestCase):
    def setUp(self):
        super(CallZoneMethodTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.stubs.Set(db, 'zone_get_all', zone_get_all)
        self.stubs.Set(novaclient, 'Client', FakeNovaClientZones)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(CallZoneMethodTest, self).tearDown()

    def test_call_zone_method(self):
        context = {}
        method = 'do_something'
        results = api.call_zone_method(context, method)
        self.assertEqual(len(results), 2)
        self.assertIn((1, 42), results)
        self.assertIn((2, 42), results)

    def test_call_zone_method_not_present(self):
        context = {}
        method = 'not_present'
        self.assertRaises(AttributeError, api.call_zone_method,
                          context, method)

    def test_call_zone_method_generates_exception(self):
        context = {}
        method = 'raises_exception'
        self.assertRaises(Exception, api.call_zone_method, context, method)
