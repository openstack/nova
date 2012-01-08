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
from nova.scheduler.simple import SimpleScheduler
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states

FLAGS = flags.FLAGS
flags.DECLARE('max_cores', 'nova.scheduler.simple')
flags.DECLARE('stub_network', 'nova.compute.manager')
flags.DECLARE('instances_path', 'nova.compute.manager')


FAKE_UUID_NOT_FOUND = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def _create_instance_dict(**kwargs):
    """Create a dictionary for a test instance"""
    inst = {}
    # NOTE(jk0): If an integer is passed as the image_ref, the image
    # service will use the default image service (in this case, the fake).
    inst['image_ref'] = kwargs.get('image_ref',
                                   'cedef40a-ed67-4d10-800e-17455edce175')
    inst['reservation_id'] = 'r-fakeres'
    inst['user_id'] = kwargs.get('user_id', 'admin')
    inst['project_id'] = kwargs.get('project_id', 'fake')
    inst['instance_type_id'] = '1'
    if 'host' in kwargs:
        inst['host'] = kwargs.get('host')
    inst['vcpus'] = kwargs.get('vcpus', 1)
    inst['memory_mb'] = kwargs.get('memory_mb', 20)
    inst['local_gb'] = kwargs.get('local_gb', 30)
    inst['vm_state'] = kwargs.get('vm_state', vm_states.ACTIVE)
    inst['power_state'] = kwargs.get('power_state', power_state.RUNNING)
    inst['task_state'] = kwargs.get('task_state', None)
    inst['availability_zone'] = kwargs.get('availability_zone', None)
    inst['ami_launch_index'] = 0
    inst['launched_on'] = kwargs.get('launched_on', 'dummy')
    return inst


def _create_volume():
    """Create a test volume"""
    vol = {}
    vol['size'] = 1
    vol['availability_zone'] = 'nova'
    ctxt = context.get_admin_context()
    return db.volume_create(ctxt, vol)['id']


def _create_instance(**kwargs):
    """Create a test instance"""
    ctxt = context.get_admin_context()
    return db.instance_create(ctxt, _create_instance_dict(**kwargs))


def _create_instance_from_spec(spec):
    return _create_instance(**spec['instance_properties'])


def _create_request_spec(**kwargs):
    return dict(instance_properties=_create_instance_dict(**kwargs))


def _fake_cast_to_compute_host(context, host, method, **kwargs):
    global _picked_host
    _picked_host = host


def _fake_cast_to_volume_host(context, host, method, **kwargs):
    global _picked_host
    _picked_host = host


def _fake_create_instance_db_entry(simple_self, context, request_spec):
    instance = _create_instance_from_spec(request_spec)
    global instance_uuids
    instance_uuids.append(instance['uuid'])
    request_spec['instance_properties']['uuid'] = instance['uuid']
    return instance


class FakeContext(context.RequestContext):
    def __init__(self, *args, **kwargs):
        super(FakeContext, self).__init__('user', 'project', **kwargs)


class TestDriver(driver.Scheduler):
    """Scheduler Driver for Tests"""
    def schedule(self, context, topic, method, *args, **kwargs):
        host = 'fallback_host'
        driver.cast_to_host(context, topic, host, method, **kwargs)

    def schedule_named_method(self, context, num=None):
        topic = 'topic'
        host = 'named_host'
        method = 'named_method'
        driver.cast_to_host(context, topic, host, method, num=num)

    def schedule_failing_method(self, context, instance_id):
        raise exception.NoValidHost(reason="")


class SchedulerTestCase(test.TestCase):
    """Test case for scheduler"""
    def setUp(self):
        super(SchedulerTestCase, self).setUp()
        driver = 'nova.tests.scheduler.test_scheduler.TestDriver'
        self.flags(scheduler_driver=driver)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(SchedulerTestCase, self).tearDown()

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

    def test_fallback(self):
        scheduler = manager.SchedulerManager()
        self.mox.StubOutWithMock(rpc, 'cast', use_mock_anything=True)
        ctxt = context.get_admin_context()
        rpc.cast(ctxt,
                 'fake_topic.fallback_host',
                 {'method': 'noexist',
                  'args': {'num': 7}})
        self.mox.ReplayAll()
        scheduler.noexist(ctxt, 'fake_topic', num=7)

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

    def _assert_state(self, state_dict):
        """assert the instance is in the state defined by state_dict"""
        instances = db.instance_get_all(context.get_admin_context())
        self.assertEqual(len(instances), 1)

        if 'vm_state' in state_dict:
            self.assertEqual(state_dict['vm_state'], instances[0]['vm_state'])
        if 'task_state' in state_dict:
            self.assertEqual(state_dict['task_state'],
                             instances[0]['task_state'])
        if 'power_state' in state_dict:
            self.assertEqual(state_dict['power_state'],
                             instances[0]['power_state'])

    def test_no_valid_host_exception_on_start(self):
        """check the vm goes to ERROR state if the scheduler fails.

        If the scheduler driver cannot allocate a host for the VM during
        start_instance, it will raise a NoValidHost exception. In this
        scenario, we have to make sure that the VM state is set to ERROR.
        """
        def NoValidHost_raiser(context, topic, *args, **kwargs):
            raise exception.NoValidHost(_("Test NoValidHost exception"))
        scheduler = manager.SchedulerManager()
        ins_ref = _create_instance(task_state=task_states.STARTING,
                                   vm_state=vm_states.STOPPED)
        self.stubs.Set(TestDriver, 'schedule', NoValidHost_raiser)
        ctxt = context.get_admin_context()
        scheduler.start_instance(ctxt, 'topic', instance_id=ins_ref['id'])
        # assert that the instance goes to ERROR state
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.STARTING})

    def test_no_valid_host_exception_on_run_with_id(self):
        """check the vm goes to ERROR state if run_instance fails"""

        def NoValidHost_raiser(context, topic, *args, **kwargs):
            raise exception.NoValidHost(_("Test NoValidHost exception"))
        scheduler = manager.SchedulerManager()
        ins_ref = _create_instance(task_state=task_states.STARTING,
                                   vm_state=vm_states.STOPPED)
        self.stubs.Set(TestDriver, 'schedule', NoValidHost_raiser)
        ctxt = context.get_admin_context()
        request_spec = {'instance_properties': {'uuid': ins_ref['uuid']}}
        scheduler.run_instance(ctxt, 'topic', request_spec=request_spec)
        # assert that the instance goes to ERROR state
        self._assert_state({'vm_state': vm_states.ERROR,
                            'task_state': task_states.STARTING})

    def test_no_valid_host_exception_on_run_without_id(self):
        """check error handler doesn't raise if instance wasn't created"""

        def NoValidHost_raiser(context, topic, *args, **kwargs):
            raise exception.NoValidHost(_("Test NoValidHost exception"))
        scheduler = manager.SchedulerManager()
        self.stubs.Set(TestDriver, 'schedule', NoValidHost_raiser)
        ctxt = context.get_admin_context()
        request_spec = {'instance_properties': {}}
        scheduler.run_instance(ctxt, 'topic', request_spec=request_spec)
        # No error

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
        i_ref1 = _create_instance(project_id='p-01', host=s_ref['host'])
        i_ref2 = _create_instance(project_id='p-02', vcpus=3,
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


class SimpleDriverTestCase(test.TestCase):
    """Test case for simple driver"""
    def setUp(self):
        super(SimpleDriverTestCase, self).setUp()
        simple_scheduler = 'nova.scheduler.simple.SimpleScheduler'
        self.flags(connection_type='fake',
                stub_network=True,
                max_cores=4,
                max_gigabytes=4,
                network_manager='nova.network.manager.FlatManager',
                volume_driver='nova.volume.driver.FakeISCSIDriver',
                scheduler_driver='nova.scheduler.multi.MultiScheduler',
                compute_scheduler_driver=simple_scheduler,
                volume_scheduler_driver=simple_scheduler)
        self.scheduler = manager.SchedulerManager()
        self.context = context.get_admin_context()

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

    def test_regular_user_can_schedule(self):
        """Ensures a non-admin can run an instance"""
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        _create_instance()
        ctxt = context.RequestContext('fake', 'fake', is_admin=False)
        global instance_uuids
        instance_uuids = []
        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)
        request_spec = _create_request_spec()
        self.scheduler.driver.schedule_run_instance(ctxt, request_spec)
        compute1.kill()

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

        global instance_uuids
        instance_uuids = []
        instance = _create_instance()
        instance_uuids.append(instance['uuid'])
        compute1.run_instance(self.context, instance_uuids[0])

        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec()
        instances = self.scheduler.driver.schedule_run_instance(
                self.context, request_spec)

        self.assertEqual(_picked_host, 'host2')
        self.assertEqual(len(instance_uuids), 2)
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0].get('_is_precooked', False), False)

        compute1.terminate_instance(self.context, instance_uuids[0])
        compute2.terminate_instance(self.context, instance_uuids[1])
        compute1.kill()
        compute2.kill()

    def test_specific_host_gets_instance_no_queue(self):
        """Ensures if you set zone:host it launches on that host"""
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

        global instance_uuids
        instance_uuids = []
        instance = _create_instance()
        instance_uuids.append(instance['uuid'])
        compute1.run_instance(self.context, instance_uuids[0])

        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec(availability_zone='nova:host1')
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host1')
        self.assertEqual(len(instance_uuids), 2)

        compute1.terminate_instance(self.context, instance_uuids[0])
        compute1.terminate_instance(self.context, instance_uuids[1])
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

        global instance_uuids
        instance_uuids = []
        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec(availability_zone='nova:host1')
        self.assertRaises(exception.WillNotSchedule,
                          self.scheduler.driver.schedule_run_instance,
                          self.context,
                          request_spec)
        compute1.kill()

    def test_will_schedule_on_disabled_host_if_specified_no_queue(self):
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        s1 = db.service_get_by_args(self.context, 'host1', 'nova-compute')
        db.service_update(self.context, s1['id'], {'disabled': True})

        global instance_uuids
        instance_uuids = []
        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec(availability_zone='nova:host1')
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host1')
        self.assertEqual(len(instance_uuids), 1)
        compute1.terminate_instance(self.context, instance_uuids[0])
        compute1.kill()

    def test_specific_zone_gets_instance_no_queue(self):
        """Ensures if you set availability_zone it launches on that zone"""
        self.flags(node_availability_zone='zone1')
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        self.flags(node_availability_zone='zone2')
        compute2 = service.Service('host2',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute2.start()

        global instance_uuids
        instance_uuids = []
        instance = _create_instance()
        instance_uuids.append(instance['uuid'])
        compute1.run_instance(self.context, instance_uuids[0])

        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec(availability_zone='zone1')
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host1')
        self.assertEqual(len(instance_uuids), 2)

        compute1.terminate_instance(self.context, instance_uuids[0])
        compute1.terminate_instance(self.context, instance_uuids[1])
        compute1.kill()
        compute2.kill()

    def test_bad_instance_zone_fails(self):
        self.flags(node_availability_zone='zone1')
        compute1 = service.Service('host1',
                                   'nova-compute',
                                   'compute',
                                   FLAGS.compute_manager)
        compute1.start()
        request_spec = _create_request_spec(availability_zone='zone2')
        try:
            self.assertRaises(exception.NoValidHost,
                              self.scheduler.driver.schedule_run_instance,
                              self.context,
                              request_spec)
        finally:
            compute1.kill()

    def test_bad_volume_zone_fails(self):
        self.flags(node_availability_zone='zone1')
        volume1 = service.Service('host1',
                                  'nova-volume',
                                  'volume',
                                   FLAGS.volume_manager)
        volume1.start()
        # uses 'nova' for zone
        volume_id = _create_volume()
        try:
            self.assertRaises(exception.NoValidHost,
                              self.scheduler.driver.schedule_create_volume,
                              self.context,
                              volume_id)
        finally:
            db.volume_destroy(self.context, volume_id)
            volume1.kill()

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
        instance_uuids1 = []
        instance_uuids2 = []
        for index in xrange(FLAGS.max_cores):
            instance = _create_instance()
            compute1.run_instance(self.context, instance['uuid'])
            instance_uuids1.append(instance['uuid'])
            instance = _create_instance()
            compute2.run_instance(self.context, instance['uuid'])
            instance_uuids2.append(instance['uuid'])
        request_spec = _create_request_spec()
        self.assertRaises(exception.NoValidHost,
                          self.scheduler.driver.schedule_run_instance,
                          self.context,
                          request_spec)
        for instance_uuid in instance_uuids1:
            compute1.terminate_instance(self.context, instance_uuid)
        for instance_uuid in instance_uuids2:
            compute2.terminate_instance(self.context, instance_uuid)
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

        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_volume_host', _fake_cast_to_volume_host)

        volume2.start()
        volume_id1 = _create_volume()
        volume1.create_volume(self.context, volume_id1)
        volume_id2 = _create_volume()
        self.scheduler.driver.schedule_create_volume(self.context,
                volume_id2)
        self.assertEqual(_picked_host, 'host2')
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
        """Ensures the host with less cores gets the next one w/ Simple"""
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')

        global instance_uuids
        instance_uuids = []
        instance = _create_instance()
        instance_uuids.append(instance['uuid'])
        compute1.run_instance(self.context, instance_uuids[0])

        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec()
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host2')
        self.assertEqual(len(instance_uuids), 2)

        compute1.terminate_instance(self.context, instance_uuids[0])
        compute2.terminate_instance(self.context, instance_uuids[1])
        compute1.kill()
        compute2.kill()

    def test_specific_host_gets_instance(self):
        """Ensures if you set availability_zone it launches on that zone"""
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')

        global instance_uuids
        instance_uuids = []
        instance = _create_instance()
        instance_uuids.append(instance['uuid'])
        compute1.run_instance(self.context, instance_uuids[0])

        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec(availability_zone='nova:host1')
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host1')
        self.assertEqual(len(instance_uuids), 2)

        compute1.terminate_instance(self.context, instance_uuids[0])
        compute1.terminate_instance(self.context, instance_uuids[1])
        compute1.kill()
        compute2.kill()

    def test_wont_schedule_if_specified_host_is_down(self):
        compute1 = self.start_service('compute', host='host1')
        s1 = db.service_get_by_args(self.context, 'host1', 'nova-compute')
        now = utils.utcnow()
        delta = datetime.timedelta(seconds=FLAGS.service_down_time * 2)
        past = now - delta
        db.service_update(self.context, s1['id'], {'updated_at': past})
        request_spec = _create_request_spec(availability_zone='nova:host1')
        self.assertRaises(exception.WillNotSchedule,
                          self.scheduler.driver.schedule_run_instance,
                          self.context,
                          request_spec)
        compute1.kill()

    def test_will_schedule_on_disabled_host_if_specified(self):
        compute1 = self.start_service('compute', host='host1')
        s1 = db.service_get_by_args(self.context, 'host1', 'nova-compute')
        db.service_update(self.context, s1['id'], {'disabled': True})

        global instance_uuids
        instance_uuids = []
        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec(availability_zone='nova:host1')
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host1')
        self.assertEqual(len(instance_uuids), 1)
        compute1.terminate_instance(self.context, instance_uuids[0])
        compute1.kill()

    def test_isolation_of_images(self):
        self.flags(isolated_images=['hotmess'], isolated_hosts=['host1'])
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')
        instance = _create_instance()
        compute1.run_instance(self.context, instance['uuid'])
        global instance_uuids
        instance_uuids = []
        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)
        request_spec = _create_request_spec(image_ref='hotmess')
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host1')
        self.assertEqual(len(instance_uuids), 1)
        compute1.terminate_instance(self.context, instance['uuid'])
        compute1.terminate_instance(self.context, instance_uuids[0])
        compute1.kill()
        compute2.kill()

    def test_non_isolation_of_not_isolated_images(self):
        self.flags(isolated_images=['hotmess'], isolated_hosts=['host1'])
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')
        instance = _create_instance()
        compute2.run_instance(self.context, instance['uuid'])
        global instance_uuids
        instance_uuids = []
        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)
        request_spec = _create_request_spec()
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host2')
        self.assertEqual(len(instance_uuids), 1)
        compute2.terminate_instance(self.context, instance['uuid'])
        compute2.terminate_instance(self.context, instance_uuids[0])
        compute1.kill()
        compute2.kill()

    def test_isolated_images_are_resource_bound(self):
        """Ensures we don't go over max cores"""
        self.flags(isolated_images=['hotmess'], isolated_hosts=['host1'])
        compute1 = self.start_service('compute', host='host1')
        instance_uuids1 = []
        for index in xrange(FLAGS.max_cores):
            instance = _create_instance()
            compute1.run_instance(self.context, instance['uuid'])
            instance_uuids1.append(instance['uuid'])

        def _create_instance_db_entry(simple_self, context, request_spec):
            self.fail(_("Shouldn't try to create DB entry when at "
                    "max cores"))
        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _create_instance_db_entry)

        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec()

        self.assertRaises(exception.NoValidHost,
                          self.scheduler.driver.schedule_run_instance,
                          self.context,
                          request_spec)
        for instance_uuid in instance_uuids1:
            compute1.terminate_instance(self.context, instance_uuid)
        compute1.kill()

    def test_isolated_images_disable_resource_checking(self):
        self.flags(isolated_images=['hotmess'], isolated_hosts=['host1'],
                   skip_isolated_core_check=True)
        compute1 = self.start_service('compute', host='host1')
        global instance_uuids
        instance_uuids = []
        for index in xrange(FLAGS.max_cores):
            instance = _create_instance()
            compute1.run_instance(self.context, instance['uuid'])
            instance_uuids.append(instance['uuid'])

        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _fake_create_instance_db_entry)
        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)
        request_spec = _create_request_spec(image_ref='hotmess')
        self.scheduler.driver.schedule_run_instance(self.context, request_spec)
        self.assertEqual(_picked_host, 'host1')
        self.assertEqual(len(instance_uuids), FLAGS.max_cores + 1)
        for instance_uuid in instance_uuids:
            compute1.terminate_instance(self.context, instance_uuid)
        compute1.kill()

    def test_too_many_cores(self):
        """Ensures we don't go over max cores"""
        compute1 = self.start_service('compute', host='host1')
        compute2 = self.start_service('compute', host='host2')
        instance_uuids1 = []
        instance_uuids2 = []
        for index in xrange(FLAGS.max_cores):
            instance = _create_instance()
            compute1.run_instance(self.context, instance['uuid'])
            instance_uuids1.append(instance['uuid'])
            instance = _create_instance()
            compute2.run_instance(self.context, instance['uuid'])
            instance_uuids2.append(instance['uuid'])

        def _create_instance_db_entry(simple_self, context, request_spec):
            self.fail(_("Shouldn't try to create DB entry when at "
                    "max cores"))
        self.stubs.Set(SimpleScheduler,
                'create_instance_db_entry', _create_instance_db_entry)

        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_compute_host', _fake_cast_to_compute_host)

        request_spec = _create_request_spec()

        self.assertRaises(exception.NoValidHost,
                          self.scheduler.driver.schedule_run_instance,
                          self.context,
                          request_spec)
        for instance_uuid in instance_uuids1:
            compute1.terminate_instance(self.context, instance_uuid)
        for instance_uuid in instance_uuids2:
            compute2.terminate_instance(self.context, instance_uuid)
        compute1.kill()
        compute2.kill()

    def test_least_busy_host_gets_volume(self):
        """Ensures the host with less gigabytes gets the next one"""
        volume1 = self.start_service('volume', host='host1')
        volume2 = self.start_service('volume', host='host2')

        global _picked_host
        _picked_host = None
        self.stubs.Set(driver,
                'cast_to_volume_host', _fake_cast_to_volume_host)

        volume_id1 = _create_volume()
        volume1.create_volume(self.context, volume_id1)
        volume_id2 = _create_volume()
        self.scheduler.driver.schedule_create_volume(self.context,
                volume_id2)
        self.assertEqual(_picked_host, 'host2')
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
            volume_id = _create_volume()
            volume1.create_volume(self.context, volume_id)
            volume_ids1.append(volume_id)
            volume_id = _create_volume()
            volume2.create_volume(self.context, volume_id)
            volume_ids2.append(volume_id)
        volume_id = _create_volume()
        self.assertRaises(exception.NoValidHost,
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
        """schedule_live_migration() works correctly as expected.

        Also, checks instance state is changed from 'running' -> 'migrating'.

        """

        instance_id = _create_instance(host='dummy')['id']
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

        instance_id = _create_instance(
                power_state=power_state.NOSTATE)['id']
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

        instance_id = _create_instance()['id']
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
        instance_id = _create_instance()['id']
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
        instance_id = _create_instance()['id']
        i_ref = db.instance_get(self.context, instance_id)
        s_ref = self._create_compute_service(host=i_ref['host'])

        ret = self.scheduler.driver._live_migration_src_check(self.context,
                                                              i_ref)

        self.assertTrue(ret is None)
        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_dest_check_not_alive(self):
        """Confirms exception raises in case dest host does not exist."""
        instance_id = _create_instance()['id']
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
        """Confirms exception raises in case dest and src is same host."""
        instance_id = _create_instance()['id']
        i_ref = db.instance_get(self.context, instance_id)
        s_ref = self._create_compute_service(host=i_ref['host'])

        self.assertRaises(exception.UnableToMigrateToSelf,
                          self.scheduler.driver._live_migration_dest_check,
                          self.context, i_ref, i_ref['host'], False)

        db.instance_destroy(self.context, instance_id)
        db.service_destroy(self.context, s_ref['id'])

    def test_live_migration_dest_check_service_lack_memory(self):
        """Confirms exception raises when dest doesn't have enough memory."""
        instance_id = _create_instance()['id']
        instance_id2 = _create_instance(host='somewhere',
                memory_mb=12)['id']
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
        instance_id = _create_instance()['id']
        instance_id2 = _create_instance(host='somewhere',
                local_gb=70)['id']
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
        instance_id = _create_instance()['id']
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
        instance_id = _create_instance()['id']
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
        instance_id = _create_instance(host='dummy')['id']
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
        instance_id = _create_instance(host='dummy')['id']
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
        """Raise exception when original host doesn't have compatible cpu."""

        dest = 'dummydest'
        instance_id = _create_instance(host='dummy')['id']
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
            AndRaise(rpc.RemoteError(exception.InvalidCPUInfo,
                                     exception.InvalidCPUInfo(reason='fake')))

        self.mox.ReplayAll()
        try:
            driver._live_migration_common_check(self.context,
                                                               i_ref,
                                                               dest,
                                                               False)
        except rpc.RemoteError, e:
            c = (e.exc_type == exception.InvalidCPUInfo)

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
    def __init__(self, id, api_url, username, password, name='child'):
        self.id = id
        self.api_url = api_url
        self.username = username
        self.password = password
        self.name = name


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

    def _call_child_zones(self, context, zones, function):
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

        self.stubs.Set(db, 'zone_get_all', zone_get_all)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid)
        self.flags(enable_zone_routing=True)

    def tearDown(self):
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
        result = decorator.unmarshall_result([])
        self.assertEquals(decorator.unmarshall_result([]), None)
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
            def __init__(self, username, password, method, api_url,
                         token=None, region_name=None):
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
            do_get(None, FakeContext(), FAKE_UUID)
            self.fail("Should have got redirect exception.")
        except api.RedirectResult, e:
            self.assertTrue(isinstance(e.results, exception.ZoneRequestError))

    def test_one_zone_down_got_instance(self):

        def _fake_issue_novaclient_command(nova, zone, *args, **kwargs):
            class FakeServer(object):
                def __init__(self):
                    self.id = FAKE_UUID
                    self.test = '1234'
            return FakeServer()

        class FakeNovaClientWithFailure(object):
            def __init__(self, username, password, method, api_url,
                         token=None, region_name=None):
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
            do_get(None, FakeContext(), FAKE_UUID)
        except api.RedirectResult, e:
            results = e.results
            self.assertIn('server', results)
            self.assertEqual(results['server']['id'], FAKE_UUID)
            self.assertEqual(results['server']['test'], '1234')
        except Exception, e:
            self.fail(_("RedirectResult should have been raised: %s" % e))
        else:
            self.fail(_("RedirectResult should have been raised"))

    def test_zones_up_no_instances(self):

        def _fake_issue_novaclient_command(nova, zone, *args, **kwargs):
            return None

        class FakeNovaClientNoFailure(object):
            def __init__(self, username, password, method, api_url,
                         token=None, region_name=None):
                pass

            def authenticate(self):
                return

        self.stubs.Set(api, '_issue_novaclient_command',
                _fake_issue_novaclient_command)
        self.stubs.Set(api.novaclient, 'Client', FakeNovaClientNoFailure)

        @api.reroute_compute("get")
        def do_get(self, context, uuid):
            pass

        try:
            do_get(None, FakeContext(), FAKE_UUID)
            self.fail("Expected redirect exception")
        except api.RedirectResult, e:
            self.assertEquals(e.results, None)


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
        try:
            api._issue_novaclient_command(FakeNovaClient(
                FakeEmptyServerCollection()), zone, "servers", "get", 100)
            self.fail("Expected NotFound exception")
        except novaclient_exceptions.NotFound, e:
            pass

        try:
            api._issue_novaclient_command(FakeNovaClient(
                FakeEmptyServerCollection()), zone, "servers", "any", "name")
            self.fail("Expected NotFound exception")
        except novaclient_exceptions.NotFound, e:
            pass


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
        self.stubs.Set(db, 'zone_get_all', zone_get_all)
        self.stubs.Set(novaclient, 'Client', FakeNovaClientZones)

    def tearDown(self):
        super(CallZoneMethodTest, self).tearDown()

    def test_call_zone_method(self):
        context = FakeContext()
        method = 'do_something'
        results = api.call_zone_method(context, method)
        self.assertEqual(len(results), 2)
        self.assertIn((1, 42), results)
        self.assertIn((2, 42), results)

    def test_call_zone_method_not_present(self):
        context = FakeContext()
        method = 'not_present'
        self.assertRaises(AttributeError, api.call_zone_method,
                          context, method)

    def test_call_zone_method_generates_exception(self):
        context = FakeContext()
        method = 'raises_exception'
        self.assertRaises(Exception, api.call_zone_method, context, method)
