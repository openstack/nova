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
Tests For Compute
"""

from nova import compute
from nova.compute import instance_types
from nova.compute import manager as compute_manager
from nova.compute import power_state
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova import flags
import nova.image.fake
from nova import log as logging
from nova import rpc
from nova import test
from nova import utils
from nova.notifier import test_notifier

LOG = logging.getLogger('nova.tests.compute')
FLAGS = flags.FLAGS
flags.DECLARE('stub_network', 'nova.compute.manager')
flags.DECLARE('live_migration_retry_count', 'nova.compute.manager')


class FakeTime(object):
    def __init__(self):
        self.counter = 0

    def sleep(self, t):
        self.counter += t


def nop_report_driver_status(self):
    pass


class ComputeTestCase(test.TestCase):
    """Test case for compute"""
    def setUp(self):
        super(ComputeTestCase, self).setUp()
        self.flags(connection_type='fake',
                   stub_network=True,
                   notification_driver='nova.notifier.test_notifier',
                   network_manager='nova.network.manager.FlatManager')
        self.compute = utils.import_object(FLAGS.compute_manager)
        self.compute_api = compute.API()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)
        test_notifier.NOTIFICATIONS = []

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(nova.image.fake._FakeImageService, 'show', fake_show)

    def _create_instance(self, params={}):
        """Create a test instance"""
        inst = {}
        inst['image_ref'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst.update(params)
        return db.instance_create(self.context, inst)['id']

    def _create_instance_type(self, params={}):
        """Create a test instance"""
        context = self.context.elevated()
        inst = {}
        inst['name'] = 'm1.small'
        inst['memory_mb'] = '1024'
        inst['vcpus'] = '1'
        inst['local_gb'] = '20'
        inst['flavorid'] = '1'
        inst['swap'] = '2048'
        inst['rxtx_quota'] = 100
        inst['rxtx_cap'] = 200
        inst.update(params)
        return db.instance_type_create(context, inst)['id']

    def _create_group(self):
        values = {'name': 'testgroup',
                  'description': 'testgroup',
                  'user_id': self.user_id,
                  'project_id': self.project_id}
        return db.security_group_create(self.context, values)

    def _get_dummy_instance(self):
        """Get mock-return-value instance object
           Use this when any testcase executed later than test_run_terminate
        """
        vol1 = models.Volume()
        vol1['id'] = 1
        vol2 = models.Volume()
        vol2['id'] = 2
        instance_ref = models.Instance()
        instance_ref['id'] = 1
        instance_ref['volumes'] = [vol1, vol2]
        instance_ref['hostname'] = 'hostname-1'
        instance_ref['host'] = 'dummy'
        return instance_ref

    def test_create_instance_defaults_display_name(self):
        """Verify that an instance cannot be created without a display_name."""
        cases = [dict(), dict(display_name=None)]
        for instance in cases:
            ref = self.compute_api.create(self.context,
                instance_types.get_default_instance_type(), None, **instance)
            try:
                self.assertNotEqual(ref[0]['display_name'], None)
            finally:
                db.instance_destroy(self.context, ref[0]['id'])

    def test_create_instance_associates_security_groups(self):
        """Make sure create associates security groups"""
        group = self._create_group()
        ref = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None,
                security_group=['testgroup'])
        try:
            self.assertEqual(len(db.security_group_get_by_instance(
                             self.context, ref[0]['id'])), 1)
            group = db.security_group_get(self.context, group['id'])
            self.assert_(len(group.instances) == 1)
        finally:
            db.security_group_destroy(self.context, group['id'])
            db.instance_destroy(self.context, ref[0]['id'])

    def test_default_hostname_generator(self):
        cases = [(None, 'server_1'), ('Hello, Server!', 'hello_server'),
                 ('<}\x1fh\x10e\x08l\x02l\x05o\x12!{>', 'hello')]
        for display_name, hostname in cases:
            ref = self.compute_api.create(self.context,
                instance_types.get_default_instance_type(), None,
                display_name=display_name)
            try:
                self.assertEqual(ref[0]['hostname'], hostname)
            finally:
                db.instance_destroy(self.context, ref[0]['id'])

    def test_destroy_instance_disassociates_security_groups(self):
        """Make sure destroying disassociates security groups"""
        group = self._create_group()

        ref = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None,
                security_group=['testgroup'])
        try:
            db.instance_destroy(self.context, ref[0]['id'])
            group = db.security_group_get(self.context, group['id'])
            self.assert_(len(group.instances) == 0)
        finally:
            db.security_group_destroy(self.context, group['id'])

    def test_destroy_security_group_disassociates_instances(self):
        """Make sure destroying security groups disassociates instances"""
        group = self._create_group()

        ref = self.compute_api.create(
                self.context,
                instance_type=instance_types.get_default_instance_type(),
                image_href=None,
                security_group=['testgroup'])

        try:
            db.security_group_destroy(self.context, group['id'])
            group = db.security_group_get(context.get_admin_context(
                                          read_deleted=True), group['id'])
            self.assert_(len(group.instances) == 0)
        finally:
            db.instance_destroy(self.context, ref[0]['id'])

    def test_run_terminate(self):
        """Make sure it is possible to  run and terminate instance"""
        instance_id = self._create_instance()

        self.compute.run_instance(self.context, instance_id)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        self.compute.terminate_instance(self.context, instance_id)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("After terminating instances: %s"), instances)
        self.assertEqual(len(instances), 0)

    def test_run_terminate_timestamps(self):
        """Make sure timestamps are set for launched and destroyed"""
        instance_id = self._create_instance()
        instance_ref = db.instance_get(self.context, instance_id)
        self.assertEqual(instance_ref['launched_at'], None)
        self.assertEqual(instance_ref['deleted_at'], None)
        launch = utils.utcnow()
        self.compute.run_instance(self.context, instance_id)
        instance_ref = db.instance_get(self.context, instance_id)
        self.assert_(instance_ref['launched_at'] > launch)
        self.assertEqual(instance_ref['deleted_at'], None)
        terminate = utils.utcnow()
        self.compute.terminate_instance(self.context, instance_id)
        self.context = self.context.elevated(True)
        instance_ref = db.instance_get(self.context, instance_id)
        self.assert_(instance_ref['launched_at'] < terminate)
        self.assert_(instance_ref['deleted_at'] > terminate)

    def test_stop(self):
        """Ensure instance can be stopped"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.compute.stop_instance(self.context, instance_id)
        self.compute.terminate_instance(self.context, instance_id)

    def test_start(self):
        """Ensure instance can be started"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.compute.stop_instance(self.context, instance_id)
        self.compute.start_instance(self.context, instance_id)
        self.compute.terminate_instance(self.context, instance_id)

    def test_pause(self):
        """Ensure instance can be paused"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.compute.pause_instance(self.context, instance_id)
        self.compute.unpause_instance(self.context, instance_id)
        self.compute.terminate_instance(self.context, instance_id)

    def test_suspend(self):
        """ensure instance can be suspended"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.compute.suspend_instance(self.context, instance_id)
        self.compute.resume_instance(self.context, instance_id)
        self.compute.terminate_instance(self.context, instance_id)

    def test_reboot(self):
        """Ensure instance can be rebooted"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.compute.reboot_instance(self.context, instance_id)
        self.compute.terminate_instance(self.context, instance_id)

    def test_set_admin_password(self):
        """Ensure instance can have its admin password set"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.compute.set_admin_password(self.context, instance_id)
        self.compute.terminate_instance(self.context, instance_id)

    def test_inject_file(self):
        """Ensure we can write a file to an instance"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.compute.inject_file(self.context, instance_id, "/tmp/test",
                "File Contents")
        self.compute.terminate_instance(self.context, instance_id)

    def test_agent_update(self):
        """Ensure instance can have its agent updated"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.compute.agent_update(self.context, instance_id,
                'http://127.0.0.1/agent', '00112233445566778899aabbccddeeff')
        self.compute.terminate_instance(self.context, instance_id)

    def test_snapshot(self):
        """Ensure instance can be snapshotted"""
        instance_id = self._create_instance()
        name = "myfakesnapshot"
        self.compute.run_instance(self.context, instance_id)
        self.compute.snapshot_instance(self.context, instance_id, name)
        self.compute.terminate_instance(self.context, instance_id)

    def test_console_output(self):
        """Make sure we can get console output from instance"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)

        console = self.compute.get_console_output(self.context,
                                                        instance_id)
        self.assert_(console)
        self.compute.terminate_instance(self.context, instance_id)

    def test_ajax_console(self):
        """Make sure we can get console output from instance"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)

        console = self.compute.get_ajax_console(self.context,
                                                instance_id)
        self.assert_(set(['token', 'host', 'port']).issubset(console.keys()))
        self.compute.terminate_instance(self.context, instance_id)

    def test_vnc_console(self):
        """Make sure we can a vnc console for an instance."""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)

        console = self.compute.get_vnc_console(self.context,
                                               instance_id)
        self.assert_(console)
        self.compute.terminate_instance(self.context, instance_id)

    def test_run_instance_usage_notification(self):
        """Ensure run instance generates apropriate usage notification"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.create')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance_id)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertEquals(payload['image_ref'], '1')
        self.compute.terminate_instance(self.context, instance_id)

    def test_terminate_usage_notification(self):
        """Ensure terminate_instance generates apropriate usage notification"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        test_notifier.NOTIFICATIONS = []
        self.compute.terminate_instance(self.context, instance_id)

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.delete')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance_id)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertEquals(payload['image_ref'], '1')

    def test_run_instance_existing(self):
        """Ensure failure when running an instance that already exists"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        self.assertRaises(exception.Error,
                          self.compute.run_instance,
                          self.context,
                          instance_id)
        self.compute.terminate_instance(self.context, instance_id)

    def test_lock(self):
        """ensure locked instance cannot be changed"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)

        non_admin_context = context.RequestContext(None, None, False, False)

        # decorator should return False (fail) with locked nonadmin context
        self.compute.lock_instance(self.context, instance_id)
        ret_val = self.compute.reboot_instance(non_admin_context, instance_id)
        self.assertEqual(ret_val, False)

        # decorator should return None (success) with unlocked nonadmin context
        self.compute.unlock_instance(self.context, instance_id)
        ret_val = self.compute.reboot_instance(non_admin_context, instance_id)
        self.assertEqual(ret_val, None)

        self.compute.terminate_instance(self.context, instance_id)

    def test_finish_resize(self):
        """Contrived test to ensure finish_resize doesn't raise anything"""

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', fake)
        self.stubs.Set(self.compute.network_api, 'get_instance_nw_info', fake)
        context = self.context.elevated()
        instance_id = self._create_instance()
        instance_ref = db.instance_get(context, instance_id)
        self.compute.prep_resize(context, instance_ref['uuid'], 1)
        migration_ref = db.migration_get_by_instance_and_status(context,
                instance_ref['uuid'], 'pre-migrating')
        try:
            self.compute.finish_resize(context, instance_ref['uuid'],
                    int(migration_ref['id']), {})
        except KeyError, e:
            # Only catch key errors. We want other reasons for the test to
            # fail to actually error out so we don't obscure anything
            self.fail()

        self.compute.terminate_instance(self.context, instance_id)

    def test_resize_instance_notification(self):
        """Ensure notifications on instance migrate/resize"""
        instance_id = self._create_instance()
        context = self.context.elevated()
        inst_ref = db.instance_get(context, instance_id)

        self.compute.run_instance(self.context, instance_id)
        test_notifier.NOTIFICATIONS = []

        db.instance_update(self.context, instance_id, {'host': 'foo'})
        self.compute.prep_resize(context, inst_ref['uuid'], 1)
        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEquals(msg['priority'], 'INFO')
        self.assertEquals(msg['event_type'], 'compute.instance.resize.prep')
        payload = msg['payload']
        self.assertEquals(payload['tenant_id'], self.project_id)
        self.assertEquals(payload['user_id'], self.user_id)
        self.assertEquals(payload['instance_id'], instance_id)
        self.assertEquals(payload['instance_type'], 'm1.tiny')
        type_id = instance_types.get_instance_type_by_name('m1.tiny')['id']
        self.assertEquals(str(payload['instance_type_id']), str(type_id))
        self.assertTrue('display_name' in payload)
        self.assertTrue('created_at' in payload)
        self.assertTrue('launched_at' in payload)
        self.assertEquals(payload['image_ref'], '1')
        self.compute.terminate_instance(context, instance_id)

    def test_resize_instance(self):
        """Ensure instance can be migrated/resized"""
        instance_id = self._create_instance()
        context = self.context.elevated()
        inst_ref = db.instance_get(context, instance_id)

        self.compute.run_instance(self.context, instance_id)
        db.instance_update(self.context, inst_ref['uuid'],
                           {'host': 'foo'})
        self.compute.prep_resize(context, inst_ref['uuid'], 1)
        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')
        self.compute.resize_instance(context, inst_ref['uuid'],
                migration_ref['id'])
        self.compute.terminate_instance(context, instance_id)

    def test_resize_invalid_flavor_fails(self):
        """Ensure invalid flavors raise"""
        instance_id = self._create_instance()
        context = self.context.elevated()
        self.compute.run_instance(self.context, instance_id)

        self.assertRaises(exception.NotFound, self.compute_api.resize,
                context, instance_id, 200)

        self.compute.terminate_instance(context, instance_id)

    def test_resize_down_fails(self):
        """Ensure resizing down raises and fails"""
        context = self.context.elevated()
        instance_id = self._create_instance()

        self.compute.run_instance(self.context, instance_id)
        inst_type = instance_types.get_instance_type_by_name('m1.xlarge')
        db.instance_update(self.context, instance_id,
                {'instance_type_id': inst_type['id']})

        self.assertRaises(exception.CannotResizeToSmallerSize,
                          self.compute_api.resize, context, instance_id, 1)

        self.compute.terminate_instance(context, instance_id)

    def test_resize_same_size_fails(self):
        """Ensure invalid flavors raise"""
        context = self.context.elevated()
        instance_id = self._create_instance()

        self.compute.run_instance(self.context, instance_id)

        self.assertRaises(exception.CannotResizeToSameSize,
                          self.compute_api.resize, context, instance_id, 1)

        self.compute.terminate_instance(context, instance_id)

    def test_finish_revert_resize(self):
        """Ensure that the flavor is reverted to the original on revert"""
        context = self.context.elevated()
        instance_id = self._create_instance()

        def fake(*args, **kwargs):
            pass

        self.stubs.Set(self.compute.driver, 'finish_migration', fake)
        self.stubs.Set(self.compute.driver, 'revert_migration', fake)
        self.stubs.Set(self.compute.network_api, 'get_instance_nw_info', fake)

        self.compute.run_instance(self.context, instance_id)

        # Confirm the instance size before the resize starts
        inst_ref = db.instance_get(context, instance_id)
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], 1)

        db.instance_update(self.context, instance_id, {'host': 'foo'})

        new_instance_type_ref = db.instance_type_get_by_flavor_id(context, 3)
        self.compute.prep_resize(context, inst_ref['uuid'],
                                 new_instance_type_ref['id'])

        migration_ref = db.migration_get_by_instance_and_status(context,
                inst_ref['uuid'], 'pre-migrating')

        self.compute.resize_instance(context, inst_ref['uuid'],
                migration_ref['id'])
        self.compute.finish_resize(context, inst_ref['uuid'],
                    int(migration_ref['id']), {})

        # Prove that the instance size is now the new size
        inst_ref = db.instance_get(context, instance_id)
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], 3)

        # Finally, revert and confirm the old flavor has been applied
        self.compute.revert_resize(context, inst_ref['uuid'],
                migration_ref['id'])
        self.compute.finish_revert_resize(context, inst_ref['uuid'],
                migration_ref['id'])

        inst_ref = db.instance_get(context, instance_id)
        instance_type_ref = db.instance_type_get(context,
                inst_ref['instance_type_id'])
        self.assertEqual(instance_type_ref['flavorid'], 1)

        self.compute.terminate_instance(context, instance_id)

    def test_get_by_flavor_id(self):
        type = instance_types.get_instance_type_by_flavor_id(1)
        self.assertEqual(type['name'], 'm1.tiny')

    def test_resize_same_source_fails(self):
        """Ensure instance fails to migrate when source and destination are
        the same host"""
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        inst_ref = db.instance_get(self.context, instance_id)
        self.assertRaises(exception.Error, self.compute.prep_resize,
                self.context, inst_ref['uuid'], 1)
        self.compute.terminate_instance(self.context, instance_id)

    def test_migrate(self):
        context = self.context.elevated()
        instance_id = self._create_instance()
        self.compute.run_instance(self.context, instance_id)
        # Migrate simply calls resize() without a flavor_id.
        self.compute_api.resize(context, instance_id, None)
        self.compute.terminate_instance(context, instance_id)

    def _setup_other_managers(self):
        self.volume_manager = utils.import_object(FLAGS.volume_manager)
        self.network_manager = utils.import_object(FLAGS.network_manager)
        self.compute_driver = utils.import_object(FLAGS.compute_driver)

    def test_pre_live_migration_instance_has_no_fixed_ip(self):
        """Confirm raising exception if instance doesn't have fixed_ip."""
        instance_ref = self._get_dummy_instance()
        c = context.get_admin_context()
        i_id = instance_ref['id']

        dbmock = self.mox.CreateMock(db)
        dbmock.instance_get(c, i_id).AndReturn(instance_ref)
        dbmock.instance_get_fixed_addresses(c, i_id).AndReturn(None)

        self.compute.db = dbmock
        self.mox.ReplayAll()
        self.assertRaises(exception.NotFound,
                          self.compute.pre_live_migration,
                          c, instance_ref['id'], time=FakeTime())

    def test_pre_live_migration_instance_has_volume(self):
        """Confirm setup_compute_volume is called when volume is mounted."""
        i_ref = self._get_dummy_instance()
        c = context.get_admin_context()

        self._setup_other_managers()
        dbmock = self.mox.CreateMock(db)
        volmock = self.mox.CreateMock(self.volume_manager)
        drivermock = self.mox.CreateMock(self.compute_driver)

        dbmock.instance_get(c, i_ref['id']).AndReturn(i_ref)
        dbmock.instance_get_fixed_addresses(c, i_ref['id']).AndReturn('dummy')
        for i in range(len(i_ref['volumes'])):
            vid = i_ref['volumes'][i]['id']
            volmock.setup_compute_volume(c, vid).InAnyOrder('g1')
        drivermock.plug_vifs(i_ref, [])
        drivermock.ensure_filtering_rules_for_instance(i_ref)

        self.compute.db = dbmock
        self.compute.volume_manager = volmock
        self.compute.driver = drivermock

        self.mox.ReplayAll()
        ret = self.compute.pre_live_migration(c, i_ref['id'])
        self.assertEqual(ret, None)

    def test_pre_live_migration_instance_has_no_volume(self):
        """Confirm log meg when instance doesn't mount any volumes."""
        i_ref = self._get_dummy_instance()
        i_ref['volumes'] = []
        c = context.get_admin_context()

        self._setup_other_managers()
        dbmock = self.mox.CreateMock(db)
        drivermock = self.mox.CreateMock(self.compute_driver)

        dbmock.instance_get(c, i_ref['id']).AndReturn(i_ref)
        dbmock.instance_get_fixed_addresses(c, i_ref['id']).AndReturn('dummy')
        self.mox.StubOutWithMock(compute_manager.LOG, 'info')
        compute_manager.LOG.info(_("%s has no volume."), i_ref['hostname'])
        drivermock.plug_vifs(i_ref, [])
        drivermock.ensure_filtering_rules_for_instance(i_ref)

        self.compute.db = dbmock
        self.compute.driver = drivermock

        self.mox.ReplayAll()
        ret = self.compute.pre_live_migration(c, i_ref['id'], time=FakeTime())
        self.assertEqual(ret, None)

    def test_pre_live_migration_setup_compute_node_fail(self):
        """Confirm operation setup_compute_network() fails.

        It retries and raise exception when timeout exceeded.

        """

        i_ref = self._get_dummy_instance()
        c = context.get_admin_context()

        self._setup_other_managers()
        dbmock = self.mox.CreateMock(db)
        netmock = self.mox.CreateMock(self.network_manager)
        volmock = self.mox.CreateMock(self.volume_manager)
        drivermock = self.mox.CreateMock(self.compute_driver)

        dbmock.instance_get(c, i_ref['id']).AndReturn(i_ref)
        dbmock.instance_get_fixed_addresses(c, i_ref['id']).AndReturn('dummy')
        for i in range(len(i_ref['volumes'])):
            volmock.setup_compute_volume(c, i_ref['volumes'][i]['id'])
        for i in range(FLAGS.live_migration_retry_count):
            drivermock.plug_vifs(i_ref, []).\
                AndRaise(exception.ProcessExecutionError())

        self.compute.db = dbmock
        self.compute.network_manager = netmock
        self.compute.volume_manager = volmock
        self.compute.driver = drivermock

        self.mox.ReplayAll()
        self.assertRaises(exception.ProcessExecutionError,
                          self.compute.pre_live_migration,
                          c, i_ref['id'], time=FakeTime())

    def test_live_migration_works_correctly_with_volume(self):
        """Confirm check_for_export to confirm volume health check."""
        i_ref = self._get_dummy_instance()
        c = context.get_admin_context()
        topic = db.queue_get_for(c, FLAGS.compute_topic, i_ref['host'])

        dbmock = self.mox.CreateMock(db)
        dbmock.instance_get(c, i_ref['id']).AndReturn(i_ref)
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, FLAGS.volume_topic, {"method": "check_for_export",
                                         "args": {'instance_id': i_ref['id']}})
        dbmock.queue_get_for(c, FLAGS.compute_topic, i_ref['host']).\
                             AndReturn(topic)
        rpc.call(c, topic, {"method": "pre_live_migration",
                            "args": {'instance_id': i_ref['id']}})
        self.mox.StubOutWithMock(self.compute.driver, 'live_migration')
        self.compute.driver.live_migration(c, i_ref, i_ref['host'],
                                  self.compute.post_live_migration,
                                  self.compute.recover_live_migration)

        self.compute.db = dbmock
        self.mox.ReplayAll()
        ret = self.compute.live_migration(c, i_ref['id'], i_ref['host'])
        self.assertEqual(ret, None)

    def test_live_migration_dest_raises_exception(self):
        """Confirm exception when pre_live_migration fails."""
        i_ref = self._get_dummy_instance()
        c = context.get_admin_context()
        topic = db.queue_get_for(c, FLAGS.compute_topic, i_ref['host'])

        dbmock = self.mox.CreateMock(db)
        dbmock.instance_get(c, i_ref['id']).AndReturn(i_ref)
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, FLAGS.volume_topic, {"method": "check_for_export",
                                         "args": {'instance_id': i_ref['id']}})
        dbmock.queue_get_for(c, FLAGS.compute_topic, i_ref['host']).\
                             AndReturn(topic)
        rpc.call(c, topic, {"method": "pre_live_migration",
                            "args": {'instance_id': i_ref['id']}}).\
                            AndRaise(rpc.RemoteError('', '', ''))
        dbmock.instance_update(c, i_ref['id'], {'state_description': 'running',
                                                'state': power_state.RUNNING,
                                                'host': i_ref['host']})
        for v in i_ref['volumes']:
            dbmock.volume_update(c, v['id'], {'status': 'in-use'})

        self.compute.db = dbmock
        self.mox.ReplayAll()
        self.assertRaises(rpc.RemoteError,
                          self.compute.live_migration,
                          c, i_ref['id'], i_ref['host'])

    def test_live_migration_dest_raises_exception_no_volume(self):
        """Same as above test(input pattern is different) """
        i_ref = self._get_dummy_instance()
        i_ref['volumes'] = []
        c = context.get_admin_context()
        topic = db.queue_get_for(c, FLAGS.compute_topic, i_ref['host'])

        dbmock = self.mox.CreateMock(db)
        dbmock.instance_get(c, i_ref['id']).AndReturn(i_ref)
        dbmock.queue_get_for(c, FLAGS.compute_topic, i_ref['host']).\
                             AndReturn(topic)
        self.mox.StubOutWithMock(rpc, 'call')
        rpc.call(c, topic, {"method": "pre_live_migration",
                            "args": {'instance_id': i_ref['id']}}).\
                            AndRaise(rpc.RemoteError('', '', ''))
        dbmock.instance_update(c, i_ref['id'], {'state_description': 'running',
                                                'state': power_state.RUNNING,
                                                'host': i_ref['host']})

        self.compute.db = dbmock
        self.mox.ReplayAll()
        self.assertRaises(rpc.RemoteError,
                          self.compute.live_migration,
                          c, i_ref['id'], i_ref['host'])

    def test_live_migration_works_correctly_no_volume(self):
        """Confirm live_migration() works as expected correctly."""
        i_ref = self._get_dummy_instance()
        i_ref['volumes'] = []
        c = context.get_admin_context()
        topic = db.queue_get_for(c, FLAGS.compute_topic, i_ref['host'])

        dbmock = self.mox.CreateMock(db)
        dbmock.instance_get(c, i_ref['id']).AndReturn(i_ref)
        self.mox.StubOutWithMock(rpc, 'call')
        dbmock.queue_get_for(c, FLAGS.compute_topic, i_ref['host']).\
                             AndReturn(topic)
        rpc.call(c, topic, {"method": "pre_live_migration",
                            "args": {'instance_id': i_ref['id']}})
        self.mox.StubOutWithMock(self.compute.driver, 'live_migration')
        self.compute.driver.live_migration(c, i_ref, i_ref['host'],
                                  self.compute.post_live_migration,
                                  self.compute.recover_live_migration)

        self.compute.db = dbmock
        self.mox.ReplayAll()
        ret = self.compute.live_migration(c, i_ref['id'], i_ref['host'])
        self.assertEqual(ret, None)

    def test_post_live_migration_working_correctly(self):
        """Confirm post_live_migration() works as expected correctly."""
        dest = 'desthost'
        flo_addr = '1.2.1.2'

        # Preparing datas
        c = context.get_admin_context()
        instance_id = self._create_instance()
        i_ref = db.instance_get(c, instance_id)
        db.instance_update(c, i_ref['id'], {'state_description': 'migrating',
                                            'state': power_state.PAUSED})
        v_ref = db.volume_create(c, {'size': 1, 'instance_id': instance_id})
        fix_addr = db.fixed_ip_create(c, {'address': '1.1.1.1',
                                          'instance_id': instance_id})
        fix_ref = db.fixed_ip_get_by_address(c, fix_addr)
        flo_ref = db.floating_ip_create(c, {'address': flo_addr,
                                        'fixed_ip_id': fix_ref['id']})
        # reload is necessary before setting mocks
        i_ref = db.instance_get(c, instance_id)

        # Preparing mocks
        self.mox.StubOutWithMock(self.compute.volume_manager,
                                 'remove_compute_volume')
        for v in i_ref['volumes']:
            self.compute.volume_manager.remove_compute_volume(c, v['id'])
        self.mox.StubOutWithMock(self.compute.driver, 'unfilter_instance')
        self.compute.driver.unfilter_instance(i_ref, [])

        # executing
        self.mox.ReplayAll()
        ret = self.compute.post_live_migration(c, i_ref, dest)

        # make sure every data is rewritten to dest
        i_ref = db.instance_get(c, i_ref['id'])
        c1 = (i_ref['host'] == dest)
        flo_refs = db.floating_ip_get_all_by_host(c, dest)
        c2 = (len(flo_refs) != 0 and flo_refs[0]['address'] == flo_addr)

        # post operaton
        self.assertTrue(c1 and c2)
        db.instance_destroy(c, instance_id)
        db.volume_destroy(c, v_ref['id'])
        db.floating_ip_destroy(c, flo_addr)

    def test_run_kill_vm(self):
        """Detect when a vm is terminated behind the scenes"""
        self.stubs.Set(compute_manager.ComputeManager,
                '_report_driver_status', nop_report_driver_status)

        instance_id = self._create_instance()

        self.compute.run_instance(self.context, instance_id)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("Running instances: %s"), instances)
        self.assertEqual(len(instances), 1)

        instance_name = instances[0].name
        self.compute.driver.test_remove_vm(instance_name)

        # Force the compute manager to do its periodic poll
        error_list = self.compute.periodic_tasks(context.get_admin_context())
        self.assertFalse(error_list)

        instances = db.instance_get_all(context.get_admin_context())
        LOG.info(_("After force-killing instances: %s"), instances)
        self.assertEqual(len(instances), 1)
        self.assertEqual(power_state.SHUTOFF, instances[0]['state'])

    @staticmethod
    def _parse_db_block_device_mapping(bdm_ref):
        attr_list = ('delete_on_termination', 'device_name', 'no_device',
                     'virtual_name', 'volume_id', 'volume_size', 'snapshot_id')
        bdm = {}
        for attr in attr_list:
            val = bdm_ref.get(attr, None)
            if val:
                bdm[attr] = val

        return bdm

    def test_update_block_device_mapping(self):
        instance_id = self._create_instance()
        mappings = [
                {'virtual': 'ami', 'device': 'sda1'},
                {'virtual': 'root', 'device': '/dev/sda1'},

                {'virtual': 'swap', 'device': 'sdb1'},
                {'virtual': 'swap', 'device': 'sdb2'},
                {'virtual': 'swap', 'device': 'sdb3'},
                {'virtual': 'swap', 'device': 'sdb4'},

                {'virtual': 'ephemeral0', 'device': 'sdc1'},
                {'virtual': 'ephemeral1', 'device': 'sdc2'},
                {'virtual': 'ephemeral2', 'device': 'sdc3'}]
        block_device_mapping = [
                # root
                {'device_name': '/dev/sda1',
                 'snapshot_id': 0x12345678,
                 'delete_on_termination': False},


                # overwrite swap
                {'device_name': '/dev/sdb2',
                 'snapshot_id': 0x23456789,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdb3',
                 'snapshot_id': 0x3456789A},
                {'device_name': '/dev/sdb4',
                 'no_device': True},

                # overwrite ephemeral
                {'device_name': '/dev/sdc2',
                 'snapshot_id': 0x456789AB,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdc3',
                 'snapshot_id': 0x56789ABC},
                {'device_name': '/dev/sdc4',
                 'no_device': True},

                # volume
                {'device_name': '/dev/sdd1',
                 'snapshot_id': 0x87654321,
                 'delete_on_termination': False},
                {'device_name': '/dev/sdd2',
                 'snapshot_id': 0x98765432},
                {'device_name': '/dev/sdd3',
                 'snapshot_id': 0xA9875463},
                {'device_name': '/dev/sdd4',
                 'no_device': True}]

        self.compute_api._update_image_block_device_mapping(
            self.context, instance_id, mappings)

        bdms = [self._parse_db_block_device_mapping(bdm_ref)
                for bdm_ref in db.block_device_mapping_get_all_by_instance(
                    self.context, instance_id)]
        expected_result = [
            {'virtual_name': 'swap', 'device_name': '/dev/sdb1'},
            {'virtual_name': 'swap', 'device_name': '/dev/sdb2'},
            {'virtual_name': 'swap', 'device_name': '/dev/sdb3'},
            {'virtual_name': 'swap', 'device_name': '/dev/sdb4'},
            {'virtual_name': 'ephemeral0', 'device_name': '/dev/sdc1'},
            {'virtual_name': 'ephemeral1', 'device_name': '/dev/sdc2'},
            {'virtual_name': 'ephemeral2', 'device_name': '/dev/sdc3'}]
        bdms.sort()
        expected_result.sort()
        self.assertDictListMatch(bdms, expected_result)

        self.compute_api._update_block_device_mapping(
            self.context, instance_id, block_device_mapping)
        bdms = [self._parse_db_block_device_mapping(bdm_ref)
                for bdm_ref in db.block_device_mapping_get_all_by_instance(
                    self.context, instance_id)]
        expected_result = [
            {'snapshot_id': 0x12345678, 'device_name': '/dev/sda1'},

            {'virtual_name': 'swap', 'device_name': '/dev/sdb1'},
            {'snapshot_id': 0x23456789, 'device_name': '/dev/sdb2'},
            {'snapshot_id': 0x3456789A, 'device_name': '/dev/sdb3'},
            {'no_device': True, 'device_name': '/dev/sdb4'},

            {'virtual_name': 'ephemeral0', 'device_name': '/dev/sdc1'},
            {'snapshot_id': 0x456789AB, 'device_name': '/dev/sdc2'},
            {'snapshot_id': 0x56789ABC, 'device_name': '/dev/sdc3'},
            {'no_device': True, 'device_name': '/dev/sdc4'},

            {'snapshot_id': 0x87654321, 'device_name': '/dev/sdd1'},
            {'snapshot_id': 0x98765432, 'device_name': '/dev/sdd2'},
            {'snapshot_id': 0xA9875463, 'device_name': '/dev/sdd3'},
            {'no_device': True, 'device_name': '/dev/sdd4'}]
        bdms.sort()
        expected_result.sort()
        self.assertDictListMatch(bdms, expected_result)

        for bdm in db.block_device_mapping_get_all_by_instance(
            self.context, instance_id):
            db.block_device_mapping_destroy(self.context, bdm['id'])
        self.compute.terminate_instance(self.context, instance_id)
