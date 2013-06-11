#    Copyright 2012 IBM Corp.
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

"""Tests for the conductor service."""

import mox

from nova.api.ec2 import ec2utils
from nova.compute import flavors
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conductor
from nova.conductor import api as conductor_api
from nova.conductor import manager as conductor_manager
from nova.conductor import rpcapi as conductor_rpcapi
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception as exc
from nova import notifications
from nova.openstack.common import jsonutils
from nova.openstack.common.notifier import api as notifier_api
from nova.openstack.common.notifier import test_notifier
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common import timeutils
from nova import quota
from nova import test


FAKE_IMAGE_REF = 'fake-image-ref'


class FakeContext(context.RequestContext):
    def elevated(self):
        """Return a consistent elevated context so we can detect it."""
        if not hasattr(self, '_elevated'):
            self._elevated = super(FakeContext, self).elevated()
        return self._elevated


class _BaseTestCase(object):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
        self.db = None
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = FakeContext(self.user_id, self.project_id)

        notifier_api._reset_drivers()
        self.addCleanup(notifier_api._reset_drivers)
        self.flags(notification_driver=[test_notifier.__name__])
        test_notifier.NOTIFICATIONS = []

    def stub_out_client_exceptions(self):
        def passthru(exceptions, func, *args, **kwargs):
            return func(*args, **kwargs)

        self.stubs.Set(rpc_common, 'catch_client_exception', passthru)

    def _create_fake_instance(self, params=None, type_name='m1.tiny'):
        if not params:
            params = {}

        inst = {}
        inst['vm_state'] = vm_states.ACTIVE
        inst['image_ref'] = FAKE_IMAGE_REF
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['host'] = 'fake_host'
        type_id = flavors.get_instance_type_by_name(type_name)['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['memory_mb'] = 0
        inst['vcpus'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst['architecture'] = 'x86_64'
        inst['os_type'] = 'Linux'
        inst['availability_zone'] = 'fake-az'
        inst.update(params)
        return db.instance_create(self.context, inst)

    def _do_update(self, instance_uuid, **updates):
        return self.conductor.instance_update(self.context, instance_uuid,
                                              updates)

    def test_instance_update(self):
        instance = self._create_fake_instance()
        new_inst = self._do_update(instance['uuid'],
                                   vm_state=vm_states.STOPPED)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.STOPPED)
        self.assertEqual(new_inst['vm_state'], instance['vm_state'])

    def test_action_event_start(self):
        self.mox.StubOutWithMock(db, 'action_event_start')
        db.action_event_start(self.context, mox.IgnoreArg())
        self.mox.ReplayAll()
        self.conductor.action_event_start(self.context, {})

    def test_action_event_finish(self):
        self.mox.StubOutWithMock(db, 'action_event_finish')
        db.action_event_finish(self.context, mox.IgnoreArg())
        self.mox.ReplayAll()
        self.conductor.action_event_finish(self.context, {})

    def test_instance_update_invalid_key(self):
        # NOTE(danms): the real DB API call ignores invalid keys
        if self.db == None:
            self.stub_out_client_exceptions()
            self.assertRaises(KeyError,
                              self._do_update, 'any-uuid', foobar=1)

    def test_migration_get(self):
        migration = db.migration_create(self.context.elevated(),
                {'instance_uuid': 'fake-uuid',
                 'status': 'migrating'})
        self.assertEqual(jsonutils.to_primitive(migration),
                         self.conductor.migration_get(self.context,
                                                      migration['id']))

    def test_migration_get_unconfirmed_by_dest_compute(self):
        self.mox.StubOutWithMock(db,
                                 'migration_get_unconfirmed_by_dest_compute')
        db.migration_get_unconfirmed_by_dest_compute(self.context,
                                                     'fake-window',
                                                     'fake-host')
        self.mox.ReplayAll()
        self.conductor.migration_get_unconfirmed_by_dest_compute(self.context,
                                                                 'fake-window',
                                                                 'fake-host')

    def test_migration_get_in_progress_by_host_and_node(self):
        self.mox.StubOutWithMock(db,
                                 'migration_get_in_progress_by_host_and_node')
        db.migration_get_in_progress_by_host_and_node(
            self.context, 'fake-host', 'fake-node').AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.migration_get_in_progress_by_host_and_node(
            self.context, 'fake-host', 'fake-node')
        self.assertEqual(result, 'fake-result')

    def test_migration_create(self):
        inst = {'uuid': 'fake-uuid',
                'host': 'fake-host',
                'node': 'fake-node'}
        self.mox.StubOutWithMock(db, 'migration_create')
        db.migration_create(self.context.elevated(),
                            {'instance_uuid': inst['uuid'],
                             'source_compute': inst['host'],
                             'source_node': inst['node'],
                             'fake-key': 'fake-value'}).AndReturn('result')
        self.mox.ReplayAll()
        result = self.conductor.migration_create(self.context, inst,
                                                 {'fake-key': 'fake-value'})
        self.assertEqual(result, 'result')

    def test_migration_update(self):
        migration = db.migration_create(self.context.elevated(),
                {'instance_uuid': 'fake-uuid',
                 'status': 'migrating'})
        migration_p = jsonutils.to_primitive(migration)
        migration = self.conductor.migration_update(self.context, migration_p,
                                                    'finished')
        self.assertEqual(migration['status'], 'finished')

    def test_instance_get_by_uuid(self):
        orig_instance = self._create_fake_instance()
        copy_instance = self.conductor.instance_get_by_uuid(
            self.context, orig_instance['uuid'])
        self.assertEqual(orig_instance['name'],
                         copy_instance['name'])

    def _setup_aggregate_with_host(self):
        aggregate_ref = db.aggregate_create(self.context.elevated(),
                {'name': 'foo'}, metadata={'availability_zone': 'foo'})

        self.conductor.aggregate_host_add(self.context, aggregate_ref, 'bar')

        aggregate_ref = db.aggregate_get(self.context.elevated(),
                                         aggregate_ref['id'])

        return aggregate_ref

    def test_aggregate_host_add(self):
        aggregate_ref = self._setup_aggregate_with_host()

        self.assertTrue(any([host == 'bar'
                             for host in aggregate_ref['hosts']]))

        db.aggregate_delete(self.context.elevated(), aggregate_ref['id'])

    def test_aggregate_host_delete(self):
        aggregate_ref = self._setup_aggregate_with_host()

        self.conductor.aggregate_host_delete(self.context, aggregate_ref,
                'bar')

        aggregate_ref = db.aggregate_get(self.context.elevated(),
                aggregate_ref['id'])

        self.assertFalse(any([host == 'bar'
                              for host in aggregate_ref['hosts']]))

        db.aggregate_delete(self.context.elevated(), aggregate_ref['id'])

    def test_aggregate_get(self):
        aggregate_ref = self._setup_aggregate_with_host()
        aggregate = self.conductor.aggregate_get(self.context,
                                                 aggregate_ref['id'])
        self.assertEqual(jsonutils.to_primitive(aggregate_ref), aggregate)
        db.aggregate_delete(self.context.elevated(), aggregate_ref['id'])

    def test_aggregate_get_by_host(self):
        self._setup_aggregate_with_host()
        aggregates = self.conductor.aggregate_get_by_host(self.context, 'bar')
        self.assertEqual(aggregates[0]['availability_zone'], 'foo')

    def test_aggregate_metadata_add(self):
        aggregate = {'name': 'fake aggregate', 'id': 'fake-id'}
        metadata = {'foo': 'bar'}
        self.mox.StubOutWithMock(db, 'aggregate_metadata_add')
        db.aggregate_metadata_add(
            mox.IgnoreArg(), aggregate['id'], metadata, False).AndReturn(
                metadata)
        self.mox.ReplayAll()
        result = self.conductor.aggregate_metadata_add(self.context,
                                                       aggregate,
                                                       metadata)
        self.assertEqual(result, metadata)

    def test_aggregate_metadata_delete(self):
        aggregate = {'name': 'fake aggregate', 'id': 'fake-id'}
        self.mox.StubOutWithMock(db, 'aggregate_metadata_delete')
        db.aggregate_metadata_delete(mox.IgnoreArg(), aggregate['id'], 'fake')
        self.mox.ReplayAll()
        result = self.conductor.aggregate_metadata_delete(self.context,
                                                       aggregate,
                                                       'fake')

    def test_aggregate_metadata_get_by_host(self):
        self.mox.StubOutWithMock(db, 'aggregate_metadata_get_by_host')
        db.aggregate_metadata_get_by_host(self.context, 'host',
                                          'key').AndReturn('result')
        self.mox.ReplayAll()
        result = self.conductor.aggregate_metadata_get_by_host(self.context,
                                                               'host', 'key')
        self.assertEqual(result, 'result')

    def test_bw_usage_update(self):
        self.mox.StubOutWithMock(db, 'bw_usage_update')
        self.mox.StubOutWithMock(db, 'bw_usage_get')

        update_args = (self.context, 'uuid', 'mac', 0, 10, 20, 5, 10, 20)
        get_args = (self.context, 'uuid', 0, 'mac')

        db.bw_usage_update(*update_args)
        db.bw_usage_get(*get_args).AndReturn('foo')

        self.mox.ReplayAll()
        result = self.conductor.bw_usage_update(*update_args)
        self.assertEqual(result, 'foo')

    def test_security_group_get_by_instance(self):
        fake_instance = {'id': 'fake-instance'}
        self.mox.StubOutWithMock(db, 'security_group_get_by_instance')
        db.security_group_get_by_instance(
            self.context, fake_instance['id']).AndReturn('it worked')
        self.mox.ReplayAll()
        result = self.conductor.security_group_get_by_instance(self.context,
                                                               fake_instance)
        self.assertEqual(result, 'it worked')

    def test_security_group_rule_get_by_security_group(self):
        fake_secgroup = {'id': 'fake-secgroup'}
        self.mox.StubOutWithMock(db,
                                 'security_group_rule_get_by_security_group')
        db.security_group_rule_get_by_security_group(
            self.context, fake_secgroup['id']).AndReturn('it worked')
        self.mox.ReplayAll()
        result = self.conductor.security_group_rule_get_by_security_group(
            self.context, fake_secgroup)
        self.assertEqual(result, 'it worked')

    def test_provider_fw_rule_get_all(self):
        fake_rules = ['a', 'b', 'c']
        self.mox.StubOutWithMock(db, 'provider_fw_rule_get_all')
        db.provider_fw_rule_get_all(self.context).AndReturn(fake_rules)
        self.mox.ReplayAll()
        result = self.conductor.provider_fw_rule_get_all(self.context)
        self.assertEqual(result, fake_rules)

    def test_agent_build_get_by_triple(self):
        self.mox.StubOutWithMock(db, 'agent_build_get_by_triple')
        db.agent_build_get_by_triple(self.context, 'fake-hv', 'fake-os',
                                     'fake-arch').AndReturn('it worked')
        self.mox.ReplayAll()
        result = self.conductor.agent_build_get_by_triple(self.context,
                                                          'fake-hv',
                                                          'fake-os',
                                                          'fake-arch')
        self.assertEqual(result, 'it worked')

    def test_block_device_mapping_get_all_by_instance(self):
        fake_inst = {'uuid': 'fake-uuid'}
        self.mox.StubOutWithMock(db,
                                 'block_device_mapping_get_all_by_instance')
        db.block_device_mapping_get_all_by_instance(
            self.context, fake_inst['uuid']).AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.block_device_mapping_get_all_by_instance(
            self.context, fake_inst, legacy=False)
        self.assertEqual(result, 'fake-result')

    def test_instance_get_active_by_window_joined(self):
        self.mox.StubOutWithMock(db, 'instance_get_active_by_window_joined')
        db.instance_get_active_by_window_joined(self.context, 'fake-begin',
                                                'fake-end', 'fake-proj',
                                                'fake-host')
        self.mox.ReplayAll()
        self.conductor.instance_get_active_by_window_joined(
            self.context, 'fake-begin', 'fake-end', 'fake-proj', 'fake-host')

    def test_instance_destroy(self):
        self.mox.StubOutWithMock(db, 'instance_destroy')
        db.instance_destroy(self.context, 'fake-uuid')
        self.mox.ReplayAll()
        self.conductor.instance_destroy(self.context, {'uuid': 'fake-uuid'})

    def test_instance_info_cache_delete(self):
        self.mox.StubOutWithMock(db, 'instance_info_cache_delete')
        db.instance_info_cache_delete(self.context, 'fake-uuid')
        self.mox.ReplayAll()
        self.conductor.instance_info_cache_delete(self.context,
                                                  {'uuid': 'fake-uuid'})

    def test_instance_info_cache_update(self):
        fake_values = {'key1': 'val1', 'key2': 'val2'}
        fake_instance = {'uuid': 'fake-uuid'}
        self.mox.StubOutWithMock(db, 'instance_info_cache_update')
        db.instance_info_cache_update(self.context, 'fake-uuid',
                                      fake_values)
        self.mox.ReplayAll()
        self.conductor.instance_info_cache_update(self.context,
                                                  fake_instance,
                                                  fake_values)

    def test_instance_type_get(self):
        self.mox.StubOutWithMock(db, 'instance_type_get')
        db.instance_type_get(self.context, 'fake-id').AndReturn('fake-type')
        self.mox.ReplayAll()
        result = self.conductor.instance_type_get(self.context, 'fake-id')
        self.assertEqual(result, 'fake-type')

    def test_vol_get_usage_by_time(self):
        self.mox.StubOutWithMock(db, 'vol_get_usage_by_time')
        db.vol_get_usage_by_time(self.context, 'fake-time').AndReturn(
            'fake-usage')
        self.mox.ReplayAll()
        result = self.conductor.vol_get_usage_by_time(self.context,
                                                      'fake-time')
        self.assertEqual(result, 'fake-usage')

    def test_vol_usage_update(self):
        # the vol_usage_update method sends the volume usage notifications
        # as well as updating the database
        self.mox.StubOutWithMock(db, 'vol_usage_update')
        inst = self._create_fake_instance({
                'project_id': 'fake-project_id',
                'user_id': 'fake-user_id',
                })
        fake_usage = {'tot_last_refreshed': 20,
                      'curr_last_refreshed': 10,
                      'volume_id': 'fake-vol',
                      'instance_uuid': inst['uuid'],
                      'project_id': 'fake-project_id',
                      'user_id': 'fake-user_id',
                      'availability_zone': 'fake-az',
                      'tot_reads': 11,
                      'curr_reads': 22,
                      'tot_read_bytes': 33,
                      'curr_read_bytes': 44,
                      'tot_writes': 55,
                      'curr_writes': 66,
                      'tot_write_bytes': 77,
                      'curr_write_bytes': 88}
        db.vol_usage_update(self.context, 'fake-vol', 'rd-req', 'rd-bytes',
                            'wr-req', 'wr-bytes', inst['uuid'],
                            'fake-project_id', 'fake-user_id', 'fake-az',
                            'fake-refr', 'fake-bool', mox.IgnoreArg()).\
                            AndReturn(fake_usage)
        self.mox.ReplayAll()
        self.conductor.vol_usage_update(self.context, 'fake-vol', 'rd-req',
                                        'rd-bytes', 'wr-req', 'wr-bytes',
                                        inst, 'fake-refr', 'fake-bool')

        self.assertEquals(len(test_notifier.NOTIFICATIONS), 1)
        msg = test_notifier.NOTIFICATIONS[0]
        payload = msg['payload']
        self.assertEquals(payload['instance_id'], inst['uuid'])
        self.assertEquals(payload['user_id'], 'fake-user_id')
        self.assertEquals(payload['tenant_id'], 'fake-project_id')
        self.assertEquals(payload['reads'], 33)
        self.assertEquals(payload['read_bytes'], 77)
        self.assertEquals(payload['writes'], 121)
        self.assertEquals(payload['write_bytes'], 165)
        self.assertEquals(payload['availability_zone'], 'fake-az')

    def test_compute_node_create(self):
        self.mox.StubOutWithMock(db, 'compute_node_create')
        db.compute_node_create(self.context, 'fake-values').AndReturn(
            'fake-result')
        self.mox.ReplayAll()
        result = self.conductor.compute_node_create(self.context,
                                                    'fake-values')
        self.assertEqual(result, 'fake-result')

    def test_compute_node_update(self):
        node = {'id': 'fake-id'}
        self.mox.StubOutWithMock(db, 'compute_node_update')
        db.compute_node_update(self.context, node['id'], 'fake-values',
                               False).AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.compute_node_update(self.context, node,
                                                    'fake-values', False)
        self.assertEqual(result, 'fake-result')

    def test_compute_node_delete(self):
        node = {'id': 'fake-id'}
        self.mox.StubOutWithMock(db, 'compute_node_delete')
        db.compute_node_delete(self.context, node['id']).AndReturn(None)
        self.mox.ReplayAll()
        result = self.conductor.compute_node_delete(self.context, node)
        self.assertEqual(result, None)

    def test_instance_fault_create(self):
        self.mox.StubOutWithMock(db, 'instance_fault_create')
        db.instance_fault_create(self.context, 'fake-values').AndReturn(
            'fake-result')
        self.mox.ReplayAll()
        result = self.conductor.instance_fault_create(self.context,
                                                      'fake-values')
        self.assertEqual(result, 'fake-result')

    def test_task_log_get(self):
        self.mox.StubOutWithMock(db, 'task_log_get')
        db.task_log_get(self.context, 'task', 'begin', 'end', 'host',
                        'state').AndReturn('result')
        self.mox.ReplayAll()
        result = self.conductor.task_log_get(self.context, 'task', 'begin',
                                             'end', 'host', 'state')
        self.assertEqual(result, 'result')

    def test_task_log_get_with_no_state(self):
        self.mox.StubOutWithMock(db, 'task_log_get')
        db.task_log_get(self.context, 'task', 'begin', 'end',
                        'host', None).AndReturn('result')
        self.mox.ReplayAll()
        result = self.conductor.task_log_get(self.context, 'task', 'begin',
                                             'end', 'host')
        self.assertEqual(result, 'result')

    def test_task_log_begin_task(self):
        self.mox.StubOutWithMock(db, 'task_log_begin_task')
        db.task_log_begin_task(self.context.elevated(), 'task', 'begin',
                               'end', 'host', 'items',
                               'message').AndReturn('result')
        self.mox.ReplayAll()
        result = self.conductor.task_log_begin_task(
            self.context, 'task', 'begin', 'end', 'host', 'items', 'message')
        self.assertEqual(result, 'result')

    def test_task_log_end_task(self):
        self.mox.StubOutWithMock(db, 'task_log_end_task')
        db.task_log_end_task(self.context.elevated(), 'task', 'begin', 'end',
                             'host', 'errors', 'message').AndReturn('result')
        self.mox.ReplayAll()
        result = self.conductor.task_log_end_task(
            self.context, 'task', 'begin', 'end', 'host', 'errors', 'message')
        self.assertEqual(result, 'result')

    def test_notify_usage_exists(self):
        info = {
            'audit_period_beginning': 'start',
            'audit_period_ending': 'end',
            'bandwidth': 'bw_usage',
            'image_meta': {},
            'extra': 'info',
            }
        instance = {
            'system_metadata': [],
            }

        self.mox.StubOutWithMock(notifications, 'audit_period_bounds')
        self.mox.StubOutWithMock(notifications, 'bandwidth_usage')
        self.mox.StubOutWithMock(compute_utils, 'notify_about_instance_usage')

        notifications.audit_period_bounds(False).AndReturn(('start', 'end'))
        notifications.bandwidth_usage(instance, 'start', True).AndReturn(
            'bw_usage')
        compute_utils.notify_about_instance_usage(self.context, instance,
                                                  'exists',
                                                  system_metadata={},
                                                  extra_usage_info=info)

        self.mox.ReplayAll()

        self.conductor.notify_usage_exists(self.context, instance,
                                           system_metadata={},
                                           extra_usage_info=dict(extra='info'))

    def test_security_groups_trigger_members_refresh(self):
        self.mox.StubOutWithMock(self.conductor_manager.security_group_api,
                                 'trigger_members_refresh')
        self.conductor_manager.security_group_api.trigger_members_refresh(
            self.context, [1, 2, 3])
        self.mox.ReplayAll()
        self.conductor.security_groups_trigger_members_refresh(self.context,
                                                               [1, 2, 3])

    def test_network_migrate_instance_start(self):
        self.mox.StubOutWithMock(self.conductor_manager.network_api,
                                 'migrate_instance_start')
        self.conductor_manager.network_api.migrate_instance_start(self.context,
                                                                  'instance',
                                                                  'migration')
        self.mox.ReplayAll()
        self.conductor.network_migrate_instance_start(self.context,
                                                      'instance',
                                                      'migration')

    def test_network_migrate_instance_finish(self):
        self.mox.StubOutWithMock(self.conductor_manager.network_api,
                                 'migrate_instance_finish')
        self.conductor_manager.network_api.migrate_instance_finish(
            self.context, 'instance', 'migration')
        self.mox.ReplayAll()
        self.conductor.network_migrate_instance_finish(self.context,
                                                       'instance',
                                                       'migration')

    def test_quota_commit(self):
        self.mox.StubOutWithMock(quota.QUOTAS, 'commit')
        quota.QUOTAS.commit(self.context, 'reservations', project_id=None)
        quota.QUOTAS.commit(self.context, 'reservations', project_id='proj')
        self.mox.ReplayAll()
        self.conductor.quota_commit(self.context, 'reservations')
        self.conductor.quota_commit(self.context, 'reservations', 'proj')

    def test_quota_rollback(self):
        self.mox.StubOutWithMock(quota.QUOTAS, 'rollback')
        quota.QUOTAS.rollback(self.context, 'reservations', project_id=None)
        quota.QUOTAS.rollback(self.context, 'reservations', project_id='proj')
        self.mox.ReplayAll()
        self.conductor.quota_rollback(self.context, 'reservations')
        self.conductor.quota_rollback(self.context, 'reservations', 'proj')

    def test_get_ec2_ids(self):
        expected = {
            'instance-id': 'ec2-inst-id',
            'ami-id': 'ec2-ami-id',
            'kernel-id': 'ami-kernel-ec2-kernelid',
            'ramdisk-id': 'ami-ramdisk-ec2-ramdiskid',
            }
        inst = {
            'uuid': 'fake-uuid',
            'kernel_id': 'ec2-kernelid',
            'ramdisk_id': 'ec2-ramdiskid',
            'image_ref': 'fake-image',
            }
        self.mox.StubOutWithMock(ec2utils, 'id_to_ec2_inst_id')
        self.mox.StubOutWithMock(ec2utils, 'glance_id_to_ec2_id')
        self.mox.StubOutWithMock(ec2utils, 'image_type')

        ec2utils.id_to_ec2_inst_id(inst['uuid']).AndReturn(
            expected['instance-id'])
        ec2utils.glance_id_to_ec2_id(self.context,
                                     inst['image_ref']).AndReturn(
            expected['ami-id'])
        for image_type in ['kernel', 'ramdisk']:
            image_id = inst['%s_id' % image_type]
            ec2utils.image_type(image_type).AndReturn('ami-' + image_type)
            ec2utils.glance_id_to_ec2_id(self.context, image_id,
                                         'ami-' + image_type).AndReturn(
                'ami-%s-ec2-%sid' % (image_type, image_type))

        self.mox.ReplayAll()
        result = self.conductor.get_ec2_ids(self.context, inst)
        self.assertEqual(result, expected)

    def test_compute_stop(self):
        self.mox.StubOutWithMock(self.conductor_manager.compute_api, 'stop')
        self.conductor_manager.compute_api.stop(self.context, 'instance', True)
        self.mox.ReplayAll()
        self.conductor.compute_stop(self.context, 'instance')

    def test_compute_confirm_resize(self):
        self.mox.StubOutWithMock(self.conductor_manager.compute_api,
                                 'confirm_resize')
        self.conductor_manager.compute_api.confirm_resize(self.context,
                                                          'instance',
                                                          'migration')
        self.mox.ReplayAll()
        self.conductor.compute_confirm_resize(self.context, 'instance',
                                              'migration')

    def test_compute_unrescue(self):
        self.mox.StubOutWithMock(self.conductor_manager.compute_api,
                                 'unrescue')
        self.conductor_manager.compute_api.unrescue(self.context, 'instance')
        self.mox.ReplayAll()
        self.conductor.compute_unrescue(self.context, 'instance')


class ConductorTestCase(_BaseTestCase, test.TestCase):
    """Conductor Manager Tests."""
    def setUp(self):
        super(ConductorTestCase, self).setUp()
        self.conductor = conductor_manager.ConductorManager()
        self.conductor_manager = self.conductor

    def test_block_device_mapping_update_or_create(self):
        fake_bdm = {'id': 'fake-id'}
        self.mox.StubOutWithMock(db, 'block_device_mapping_create')
        self.mox.StubOutWithMock(db, 'block_device_mapping_update')
        self.mox.StubOutWithMock(db, 'block_device_mapping_update_or_create')
        db.block_device_mapping_create(self.context, fake_bdm)
        db.block_device_mapping_update(self.context, fake_bdm['id'], fake_bdm)
        db.block_device_mapping_update_or_create(self.context, fake_bdm)
        self.mox.ReplayAll()
        self.conductor.block_device_mapping_update_or_create(self.context,
                                                             fake_bdm,
                                                             create=True)
        self.conductor.block_device_mapping_update_or_create(self.context,
                                                             fake_bdm,
                                                             create=False)
        self.conductor.block_device_mapping_update_or_create(self.context,
                                                             fake_bdm)

    def test_block_device_mapping_destroy(self):
        fake_bdm = {'id': 'fake-bdm'}
        fake_bdm2 = {'id': 'fake-bdm-2'}
        fake_inst = {'uuid': 'fake-uuid'}
        self.mox.StubOutWithMock(db, 'block_device_mapping_destroy')
        self.mox.StubOutWithMock(
            db, 'block_device_mapping_destroy_by_instance_and_device')
        self.mox.StubOutWithMock(
            db, 'block_device_mapping_destroy_by_instance_and_volume')
        db.block_device_mapping_destroy(self.context, 'fake-bdm')
        db.block_device_mapping_destroy(self.context, 'fake-bdm-2')
        db.block_device_mapping_destroy_by_instance_and_device(self.context,
                                                               'fake-uuid',
                                                               'fake-device')
        db.block_device_mapping_destroy_by_instance_and_volume(self.context,
                                                               'fake-uuid',
                                                               'fake-volume')
        self.mox.ReplayAll()
        self.conductor.block_device_mapping_destroy(self.context,
                                                    [fake_bdm,
                                                     fake_bdm2])
        self.conductor.block_device_mapping_destroy(self.context,
                                                    instance=fake_inst,
                                                    device_name='fake-device')
        self.conductor.block_device_mapping_destroy(self.context,
                                                    instance=fake_inst,
                                                    volume_id='fake-volume')

    def test_instance_get_all_by_filters(self):
        filters = {'foo': 'bar'}
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')
        db.instance_get_all_by_filters(self.context, filters,
                                       'fake-key', 'fake-sort',
                                       columns_to_join=None)
        self.mox.ReplayAll()
        self.conductor.instance_get_all_by_filters(self.context, filters,
                                                   'fake-key', 'fake-sort')

    def test_instance_get_all_by_host(self):
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host_and_node')
        db.instance_get_all_by_host(self.context.elevated(),
                                    'host', None).AndReturn('result')
        db.instance_get_all_by_host_and_node(self.context.elevated(), 'host',
                                             'node').AndReturn('result')
        self.mox.ReplayAll()
        result = self.conductor.instance_get_all_by_host(self.context, 'host')
        self.assertEqual(result, 'result')
        result = self.conductor.instance_get_all_by_host(self.context, 'host',
                                                         'node')
        self.assertEqual(result, 'result')

    def _test_stubbed(self, name, dbargs, condargs,
                      db_result_listified=False, db_exception=None):

        self.mox.StubOutWithMock(db, name)
        if db_exception:
            getattr(db, name)(self.context, *dbargs).AndRaise(db_exception)
            getattr(db, name)(self.context, *dbargs).AndRaise(db_exception)
        else:
            getattr(db, name)(self.context, *dbargs).AndReturn('fake-result')
        self.mox.ReplayAll()
        if db_exception:
            self.assertRaises(rpc_common.ClientException,
                              self.conductor.service_get_all_by,
                              self.context, **condargs)

            self.stub_out_client_exceptions()

            self.assertRaises(db_exception.__class__,
                              self.conductor.service_get_all_by,
                              self.context, **condargs)
        else:
            result = self.conductor.service_get_all_by(self.context,
                                                       **condargs)
            if db_result_listified:
                self.assertEqual(['fake-result'], result)
            else:
                self.assertEqual('fake-result', result)

    def test_service_get_all(self):
        self._test_stubbed('service_get_all', (), {})

    def test_service_get_by_host_and_topic(self):
        self._test_stubbed('service_get_by_host_and_topic',
                           ('host', 'topic'),
                           dict(topic='topic', host='host'))

    def test_service_get_all_by_topic(self):
        self._test_stubbed('service_get_all_by_topic',
                           ('topic',),
                           dict(topic='topic'))

    def test_service_get_all_by_host(self):
        self._test_stubbed('service_get_all_by_host',
                           ('host',),
                           dict(host='host'))

    def test_service_get_by_compute_host(self):
        self._test_stubbed('service_get_by_compute_host',
                           ('host',),
                           dict(topic='compute', host='host'),
                           db_result_listified=True)

    def test_service_get_by_args(self):
        self._test_stubbed('service_get_by_args',
                           ('host', 'binary'),
                           dict(host='host', binary='binary'))

    def test_service_get_by_compute_host_not_found(self):
        self._test_stubbed('service_get_by_compute_host',
                           ('host',),
                           dict(topic='compute', host='host'),
                           db_exception=exc.ComputeHostNotFound(host='host'))

    def test_service_get_by_args_not_found(self):
        self._test_stubbed('service_get_by_args',
                           ('host', 'binary'),
                           dict(host='host', binary='binary'),
                           db_exception=exc.HostBinaryNotFound(binary='binary',
                                                               host='host'))

    def test_security_groups_trigger_handler(self):
        self.mox.StubOutWithMock(self.conductor_manager.security_group_api,
                                 'trigger_handler')
        self.conductor_manager.security_group_api.trigger_handler('event',
                                                                  self.context,
                                                                  'args')
        self.mox.ReplayAll()
        self.conductor.security_groups_trigger_handler(self.context,
                                                       'event', ['args'])


class ConductorRPCAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor RPC API Tests."""
    def setUp(self):
        super(ConductorRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor_manager = self.conductor_service.manager
        self.conductor = conductor_rpcapi.ConductorAPI()

    def test_block_device_mapping_update_or_create(self):
        fake_bdm = {'id': 'fake-id'}
        self.mox.StubOutWithMock(db, 'block_device_mapping_create')
        self.mox.StubOutWithMock(db, 'block_device_mapping_update')
        self.mox.StubOutWithMock(db, 'block_device_mapping_update_or_create')
        db.block_device_mapping_create(self.context, fake_bdm)
        db.block_device_mapping_update(self.context, fake_bdm['id'], fake_bdm)
        db.block_device_mapping_update_or_create(self.context, fake_bdm)
        self.mox.ReplayAll()
        self.conductor.block_device_mapping_update_or_create(self.context,
                                                             fake_bdm,
                                                             create=True)
        self.conductor.block_device_mapping_update_or_create(self.context,
                                                             fake_bdm,
                                                             create=False)
        self.conductor.block_device_mapping_update_or_create(self.context,
                                                             fake_bdm)

    def test_block_device_mapping_destroy(self):
        fake_bdm = {'id': 'fake-bdm'}
        fake_inst = {'uuid': 'fake-uuid'}
        self.mox.StubOutWithMock(db, 'block_device_mapping_destroy')
        self.mox.StubOutWithMock(
            db, 'block_device_mapping_destroy_by_instance_and_device')
        self.mox.StubOutWithMock(
            db, 'block_device_mapping_destroy_by_instance_and_volume')
        db.block_device_mapping_destroy(self.context, 'fake-bdm')
        db.block_device_mapping_destroy_by_instance_and_device(self.context,
                                                               'fake-uuid',
                                                               'fake-device')
        db.block_device_mapping_destroy_by_instance_and_volume(self.context,
                                                               'fake-uuid',
                                                               'fake-volume')
        self.mox.ReplayAll()
        self.conductor.block_device_mapping_destroy(self.context,
                                                    bdms=[fake_bdm])
        self.conductor.block_device_mapping_destroy(self.context,
                                                    instance=fake_inst,
                                                    device_name='fake-device')
        self.conductor.block_device_mapping_destroy(self.context,
                                                    instance=fake_inst,
                                                    volume_id='fake-volume')

    def test_instance_get_all_by_filters(self):
        filters = {'foo': 'bar'}
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')
        db.instance_get_all_by_filters(self.context, filters,
                                       'fake-key', 'fake-sort',
                                       columns_to_join=None)
        self.mox.ReplayAll()
        self.conductor.instance_get_all_by_filters(self.context, filters,
                                                   'fake-key', 'fake-sort')

    def _test_stubbed(self, name, dbargs, condargs,
                      db_result_listified=False, db_exception=None):
        self.mox.StubOutWithMock(db, name)
        if db_exception:
            getattr(db, name)(self.context, *dbargs).AndRaise(db_exception)
        else:
            getattr(db, name)(self.context, *dbargs).AndReturn('fake-result')
        self.mox.ReplayAll()
        if db_exception:
            self.assertRaises(db_exception.__class__,
                              self.conductor.service_get_all_by,
                              self.context, **condargs)
        else:
            result = self.conductor.service_get_all_by(self.context,
                                                       **condargs)
            if db_result_listified:
                self.assertEqual(['fake-result'], result)
            else:
                self.assertEqual('fake-result', result)

    def test_service_get_all(self):
        self._test_stubbed('service_get_all', (), {})

    def test_service_get_by_host_and_topic(self):
        self._test_stubbed('service_get_by_host_and_topic',
                           ('host', 'topic'),
                           dict(topic='topic', host='host'))

    def test_service_get_all_by_topic(self):
        self._test_stubbed('service_get_all_by_topic',
                           ('topic',),
                           dict(topic='topic'))

    def test_service_get_all_by_host(self):
        self._test_stubbed('service_get_all_by_host',
                           ('host',),
                           dict(host='host'))

    def test_service_get_by_compute_host(self):
        self._test_stubbed('service_get_by_compute_host',
                           ('host',),
                           dict(topic='compute', host='host'),
                           db_result_listified=True)

    def test_service_get_by_args(self):
        self._test_stubbed('service_get_by_args',
                           ('host', 'binary'),
                           dict(host='host', binary='binary'))

    def test_service_get_by_compute_host_not_found(self):
        self._test_stubbed('service_get_by_compute_host',
                           ('host',),
                           dict(topic='compute', host='host'),
                           db_exception=exc.ComputeHostNotFound(host='host'))

    def test_service_get_by_args_not_found(self):
        self._test_stubbed('service_get_by_args',
                           ('host', 'binary'),
                           dict(host='host', binary='binary'),
                           db_exception=exc.HostBinaryNotFound(binary='binary',
                                                               host='host'))

    def test_security_groups_trigger_handler(self):
        self.mox.StubOutWithMock(self.conductor_manager.security_group_api,
                                 'trigger_handler')
        self.conductor_manager.security_group_api.trigger_handler('event',
                                                                  self.context,
                                                                  'arg')
        self.mox.ReplayAll()
        self.conductor.security_groups_trigger_handler(self.context,
                                                       'event', ['arg'])


class ConductorAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor API Tests."""
    def setUp(self):
        super(ConductorAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_api.API()
        self.conductor_manager = self.conductor_service.manager
        self.db = None

    def _do_update(self, instance_uuid, **updates):
        # NOTE(danms): the public API takes actual keyword arguments,
        # so override the base class here to make the call correctly
        return self.conductor.instance_update(self.context, instance_uuid,
                                              **updates)

    def test_bw_usage_get(self):
        self.mox.StubOutWithMock(db, 'bw_usage_update')
        self.mox.StubOutWithMock(db, 'bw_usage_get')

        get_args = (self.context, 'uuid', 0, 'mac')

        db.bw_usage_get(*get_args).AndReturn('foo')

        self.mox.ReplayAll()
        result = self.conductor.bw_usage_get(*get_args)
        self.assertEqual(result, 'foo')

    def test_block_device_mapping_update_or_create(self):
        self.mox.StubOutWithMock(db, 'block_device_mapping_create')
        self.mox.StubOutWithMock(db, 'block_device_mapping_update')
        self.mox.StubOutWithMock(db, 'block_device_mapping_update_or_create')
        db.block_device_mapping_create(self.context, 'fake-bdm')
        db.block_device_mapping_update(self.context,
                                       'fake-id', {'id': 'fake-id'})
        db.block_device_mapping_update_or_create(self.context, 'fake-bdm')

        self.mox.ReplayAll()
        self.conductor.block_device_mapping_create(self.context, 'fake-bdm')
        self.conductor.block_device_mapping_update(self.context, 'fake-id', {})
        self.conductor.block_device_mapping_update_or_create(self.context,
                                                             'fake-bdm')

    def test_block_device_mapping_destroy(self):
        fake_bdm = {'id': 'fake-bdm'}
        fake_inst = {'uuid': 'fake-uuid'}
        self.mox.StubOutWithMock(db, 'block_device_mapping_destroy')
        self.mox.StubOutWithMock(
            db, 'block_device_mapping_destroy_by_instance_and_device')
        self.mox.StubOutWithMock(
            db, 'block_device_mapping_destroy_by_instance_and_volume')
        db.block_device_mapping_destroy(self.context, 'fake-bdm')
        db.block_device_mapping_destroy_by_instance_and_device(self.context,
                                                               'fake-uuid',
                                                               'fake-device')
        db.block_device_mapping_destroy_by_instance_and_volume(self.context,
                                                               'fake-uuid',
                                                               'fake-volume')
        self.mox.ReplayAll()
        self.conductor.block_device_mapping_destroy(self.context, [fake_bdm])
        self.conductor.block_device_mapping_destroy_by_instance_and_device(
            self.context, fake_inst, 'fake-device')
        self.conductor.block_device_mapping_destroy_by_instance_and_volume(
            self.context, fake_inst, 'fake-volume')

    def _test_stubbed(self, name, *args, **kwargs):
        if args and isinstance(args[0], FakeContext):
            ctxt = args[0]
            args = args[1:]
        else:
            ctxt = self.context
        db_exception = kwargs.get('db_exception')
        self.mox.StubOutWithMock(db, name)
        if db_exception:
            getattr(db, name)(ctxt, *args).AndRaise(db_exception)
        else:
            getattr(db, name)(ctxt, *args).AndReturn('fake-result')
        if name == 'service_destroy':
            # TODO(russellb) This is a hack ... SetUp() starts the conductor()
            # service.  There is a cleanup step that runs after this test which
            # also deletes the associated service record. This involves a call
            # to db.service_destroy(), which we have stubbed out.
            db.service_destroy(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        if db_exception:
            self.assertRaises(db_exception.__class__,
                              getattr(self.conductor, name),
                              self.context, *args)
        else:
            result = getattr(self.conductor, name)(self.context, *args)
            self.assertEqual(
                result, 'fake-result' if kwargs.get('returns', True) else None)

    def test_service_get_all(self):
        self._test_stubbed('service_get_all')

    def test_service_get_by_host_and_topic(self):
        self._test_stubbed('service_get_by_host_and_topic', 'host', 'topic')

    def test_service_get_all_by_topic(self):
        self._test_stubbed('service_get_all_by_topic', 'topic')

    def test_service_get_all_by_host(self):
        self._test_stubbed('service_get_all_by_host', 'host')

    def test_service_get_by_compute_host(self):
        self._test_stubbed('service_get_by_compute_host', 'host')

    def test_service_get_by_args(self):
        self._test_stubbed('service_get_by_args', 'host', 'binary')

    def test_service_get_by_compute_host_not_found(self):
        self._test_stubbed('service_get_by_compute_host', 'host',
                           db_exception=exc.ComputeHostNotFound(host='host'))

    def test_service_get_by_args_not_found(self):
        self._test_stubbed('service_get_by_args', 'host', 'binary',
                           db_exception=exc.HostBinaryNotFound(binary='binary',
                                                               host='host'))

    def test_service_create(self):
        self._test_stubbed('service_create', {})

    def test_service_destroy(self):
        self._test_stubbed('service_destroy', '', returns=False)

    def test_service_update(self):
        ctxt = self.context
        self.mox.StubOutWithMock(db, 'service_update')
        db.service_update(ctxt, '', {}).AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.service_update(self.context, {'id': ''}, {})
        self.assertEqual(result, 'fake-result')

    def test_instance_get_all_by_host_and_node(self):
        self._test_stubbed('instance_get_all_by_host_and_node',
                           self.context.elevated(), 'host', 'node')

    def test_instance_get_all_by_host(self):
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host_and_node')
        db.instance_get_all_by_host(self.context.elevated(), 'host',
                                    None).AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.instance_get_all_by_host(self.context,
                                                         'host')
        self.assertEqual(result, 'fake-result')

    def test_wait_until_ready(self):
        timeouts = []
        calls = dict(count=0)

        def fake_ping(context, message, timeout):
            timeouts.append(timeout)
            calls['count'] += 1
            if calls['count'] < 15:
                raise rpc_common.Timeout("fake")

        self.stubs.Set(self.conductor.base_rpcapi, 'ping', fake_ping)

        self.conductor.wait_until_ready(self.context)

        self.assertEqual(timeouts.count(10), 10)
        self.assertTrue(None in timeouts)

    def test_security_groups_trigger_handler(self):
        self.mox.StubOutWithMock(self.conductor_manager.security_group_api,
                                 'trigger_handler')
        self.conductor_manager.security_group_api.trigger_handler('event',
                                                                  self.context,
                                                                  'arg')
        self.mox.ReplayAll()
        self.conductor.security_groups_trigger_handler(self.context,
                                                       'event', 'arg')


class ConductorLocalAPITestCase(ConductorAPITestCase):
    """Conductor LocalAPI Tests."""
    def setUp(self):
        super(ConductorLocalAPITestCase, self).setUp()
        self.conductor = conductor_api.LocalAPI()
        self.conductor_manager = self.conductor._manager._target
        self.db = db

    def test_client_exceptions(self):
        instance = self._create_fake_instance()
        # NOTE(danms): The LocalAPI should not raise exceptions wrapped
        # in ClientException. KeyError should be raised if an invalid
        # update key is passed, so use that to validate.
        self.assertRaises(KeyError,
                          self._do_update, instance['uuid'], foo='bar')

    def test_wait_until_ready(self):
        # Override test in ConductorAPITestCase
        pass


class ConductorImportTest(test.TestCase):
    def test_import_conductor_local(self):
        self.flags(use_local=True, group='conductor')
        self.assertTrue(isinstance(conductor.API(),
                                   conductor_api.LocalAPI))
        self.assertTrue(isinstance(conductor.ComputeTaskAPI(),
                                   conductor_api.LocalComputeTaskAPI))

    def test_import_conductor_rpc(self):
        self.flags(use_local=False, group='conductor')
        self.assertTrue(isinstance(conductor.API(),
                                   conductor_api.API))
        self.assertTrue(isinstance(conductor.ComputeTaskAPI(),
                                   conductor_api.ComputeTaskAPI))

    def test_import_conductor_override_to_local(self):
        self.flags(use_local=False, group='conductor')
        self.assertTrue(isinstance(conductor.API(use_local=True),
                                   conductor_api.LocalAPI))
        self.assertTrue(isinstance(conductor.ComputeTaskAPI(use_local=True),
                                   conductor_api.LocalComputeTaskAPI))


class ConductorPolicyTest(test.TestCase):
    def test_all_allowed_keys(self):

        def fake_db_instance_update(self, *args, **kwargs):
            return None, None
        self.stubs.Set(db, 'instance_update_and_get_original',
                       fake_db_instance_update)

        ctxt = context.RequestContext('fake-user', 'fake-project')
        conductor = conductor_api.LocalAPI()
        updates = {}
        for key in conductor_manager.allowed_updates:
            if key in conductor_manager.datetime_fields:
                updates[key] = timeutils.utcnow()
            else:
                updates[key] = 'foo'
        conductor.instance_update(ctxt, 'fake-instance', **updates)

    def test_allowed_keys_are_real(self):
        instance = models.Instance()
        keys = list(conductor_manager.allowed_updates)

        # NOTE(danms): expected_task_state is a parameter that gets
        # passed to the db layer, but is not actually an instance attribute
        del keys[keys.index('expected_task_state')]

        for key in keys:
            self.assertTrue(hasattr(instance, key))


class _BaseTaskTestCase(object):
    def setUp(self):
        super(_BaseTaskTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = FakeContext(self.user_id, self.project_id)

    def test_migrate_server(self):
        self.mox.StubOutWithMock(self.conductor_manager.scheduler_rpcapi,
                                 'live_migration')
        self.conductor_manager.scheduler_rpcapi.live_migration(self.context,
            'block_migration', 'disk_over_commit', 'instance', 'destination')
        self.mox.ReplayAll()
        self.conductor.migrate_server(self.context, 'instance',
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')

    def test_migrate_server_fails_with_non_live(self):
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, None, None, False, False, None, None, None)

    def test_migrate_server_fails_with_rebuild(self):
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, None, None, True, True, None, None, None)

    def test_migrate_server_fails_with_flavor(self):
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, None, None, True, False, "dummy", None, None)

    def test_build_instances(self):
        instance_type = flavors.get_default_instance_type()
        system_metadata = flavors.save_instance_type_info({}, instance_type)
        # NOTE(alaski): instance_type -> system_metadata -> instance_type loses
        # some data (extra_specs) so we need both for testing.
        instance_type_extract = flavors.extract_instance_type(
                {'system_metadata': system_metadata})
        self.mox.StubOutWithMock(self.conductor_manager.scheduler_rpcapi,
                                 'run_instance')
        self.conductor_manager.scheduler_rpcapi.run_instance(self.context,
                request_spec={
                    'image': {'fake_data': 'should_pass_silently'},
                    'instance_properties': {'system_metadata': system_metadata,
                                            'uuid': 'fakeuuid'},
                    'instance_type': instance_type_extract,
                    'instance_uuids': ['fakeuuid', 'fakeuuid2'],
                    'block_device_mapping': 'block_device_mapping',
                    'security_group': 'security_groups'},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks='requested_networks', is_first_time=True,
                filter_properties={})
        self.mox.ReplayAll()
        self.conductor.build_instances(self.context,
                instances=[{'uuid': 'fakeuuid',
                            'system_metadata': system_metadata},
                           {'uuid': 'fakeuuid2'}],
                image={'fake_data': 'should_pass_silently'},
                filter_properties={},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks='requested_networks',
                security_groups='security_groups',
                block_device_mapping='block_device_mapping')


class ConductorTaskTestCase(_BaseTaskTestCase, test.TestCase):
    """ComputeTaskManager Tests."""
    def setUp(self):
        super(ConductorTaskTestCase, self).setUp()
        self.conductor = conductor_manager.ComputeTaskManager()
        self.conductor_manager = self.conductor


class ConductorTaskRPCAPITestCase(_BaseTaskTestCase, test.TestCase):
    """Conductor compute_task RPC namespace Tests."""
    def setUp(self):
        super(ConductorTaskRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_rpcapi.ComputeTaskAPI()
        service_manager = self.conductor_service.manager
        self.conductor_manager = service_manager.compute_task_mgr


class ConductorTaskAPITestCase(_BaseTaskTestCase, test.TestCase):
    """Compute task API Tests."""
    def setUp(self):
        super(ConductorTaskAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_api.ComputeTaskAPI()
        service_manager = self.conductor_service.manager
        self.conductor_manager = service_manager.compute_task_mgr


class ConductorLocalComputeTaskAPITestCase(ConductorTaskAPITestCase):
    """Conductor LocalComputeTaskAPI Tests."""
    def setUp(self):
        super(ConductorLocalComputeTaskAPITestCase, self).setUp()
        self.conductor = conductor_api.LocalComputeTaskAPI()
        self.conductor_manager = self.conductor._manager._target
