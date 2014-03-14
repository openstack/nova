#    Copyright 2012 IBM Corp.
#    Copyright 2013 Red Hat, Inc.
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

import contextlib
import mock
import mox
from oslo import messaging

from nova.api.ec2 import ec2utils
from nova.compute import flavors
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import conductor
from nova.conductor import api as conductor_api
from nova.conductor import manager as conductor_manager
from nova.conductor import rpcapi as conductor_rpcapi
from nova.conductor.tasks import live_migrate
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception as exc
from nova import notifications
from nova.objects import base as obj_base
from nova.objects import fields
from nova.objects import instance as instance_obj
from nova.objects import migration as migration_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova import quota
from nova import rpc
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests import cast_as_call
from nova.tests.compute import test_compute
from nova.tests import fake_instance
from nova.tests import fake_instance_actions
from nova.tests import fake_notifier
from nova.tests.objects import test_migration
from nova import utils


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

        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

        def fake_deserialize_context(serializer, ctxt_dict):
            self.assertEqual(self.context.user_id, ctxt_dict['user_id'])
            self.assertEqual(self.context.project_id, ctxt_dict['project_id'])
            return self.context

        self.stubs.Set(rpc.RequestContextSerializer, 'deserialize_context',
                       fake_deserialize_context)

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
        type_id = flavors.get_flavor_by_name(type_name)['id']
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
            self.conductor = utils.ExceptionHelper(self.conductor)
            self.assertRaises(KeyError,
                              self._do_update, 'any-uuid', foobar=1)

    def test_migration_get_in_progress_by_host_and_node(self):
        self.mox.StubOutWithMock(db,
                                 'migration_get_in_progress_by_host_and_node')
        db.migration_get_in_progress_by_host_and_node(
            self.context, 'fake-host', 'fake-node').AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.migration_get_in_progress_by_host_and_node(
            self.context, 'fake-host', 'fake-node')
        self.assertEqual(result, 'fake-result')

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

        db.bw_usage_update(*update_args, update_cells=True)
        db.bw_usage_get(*get_args).AndReturn('foo')

        self.mox.ReplayAll()
        result = self.conductor.bw_usage_update(*update_args)
        self.assertEqual(result, 'foo')

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
        db.instance_destroy(self.context, 'fake-uuid').AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.instance_destroy(self.context,
                                                 {'uuid': 'fake-uuid'})
        self.assertEqual(result, 'fake-result')

    def test_instance_info_cache_delete(self):
        self.mox.StubOutWithMock(db, 'instance_info_cache_delete')
        db.instance_info_cache_delete(self.context, 'fake-uuid')
        self.mox.ReplayAll()
        self.conductor.instance_info_cache_delete(self.context,
                                                  {'uuid': 'fake-uuid'})

    def test_vol_get_usage_by_time(self):
        self.mox.StubOutWithMock(db, 'vol_get_usage_by_time')
        db.vol_get_usage_by_time(self.context, 'fake-time').AndReturn(
            'fake-usage')
        self.mox.ReplayAll()
        result = self.conductor.vol_get_usage_by_time(self.context,
                                                      'fake-time')
        self.assertEqual(result, 'fake-usage')

    def test_vol_usage_update(self):
        self.mox.StubOutWithMock(db, 'vol_usage_update')
        self.mox.StubOutWithMock(compute_utils, 'usage_volume_info')

        fake_inst = {'uuid': 'fake-uuid',
                     'project_id': 'fake-project',
                     'user_id': 'fake-user',
                     'availability_zone': 'fake-az',
                     }

        db.vol_usage_update(self.context, 'fake-vol', 22, 33, 44, 55,
                            fake_inst['uuid'],
                            fake_inst['project_id'],
                            fake_inst['user_id'],
                            fake_inst['availability_zone'],
                            False).AndReturn('fake-usage')
        compute_utils.usage_volume_info('fake-usage').AndReturn('fake-info')

        self.mox.ReplayAll()

        self.conductor.vol_usage_update(self.context, 'fake-vol',
                                        22, 33, 44, 55, fake_inst,
                                        'fake-update-time', False)

        self.assertEqual(1, len(fake_notifier.NOTIFICATIONS))
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual('conductor.%s' % self.conductor_manager.host,
                         msg.publisher_id)
        self.assertEqual('volume.usage', msg.event_type)
        self.assertEqual('INFO', msg.priority)
        self.assertEqual('fake-info', msg.payload)

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
        db.compute_node_update(self.context, node['id'], {'fake': 'values'}).\
                               AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.compute_node_update(self.context, node,
                                                    {'fake': 'values'}, False)
        self.assertEqual(result, 'fake-result')

    def test_compute_node_update_with_non_json_stats(self):
        node = {'id': 'fake-id'}
        fake_input = {'stats': {'a': 'b'}}
        fake_vals = {'stats': jsonutils.dumps(fake_input['stats'])}
        self.mox.StubOutWithMock(db, 'compute_node_update')
        db.compute_node_update(self.context, node['id'], fake_vals
                               ).AndReturn('fake-result')
        self.mox.ReplayAll()
        self.conductor.compute_node_update(self.context, node,
                                           fake_input, False)

    def test_compute_node_delete(self):
        node = {'id': 'fake-id'}
        self.mox.StubOutWithMock(db, 'compute_node_delete')
        db.compute_node_delete(self.context, node['id']).AndReturn(None)
        self.mox.ReplayAll()
        result = self.conductor.compute_node_delete(self.context, node)
        self.assertIsNone(result)

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
        notifier = self.conductor_manager.notifier
        compute_utils.notify_about_instance_usage(notifier,
                                                  self.context, instance,
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
        quota.QUOTAS.commit(self.context, 'reservations', project_id=None,
                            user_id=None)
        quota.QUOTAS.commit(self.context, 'reservations', project_id='proj',
                            user_id='user')
        self.mox.ReplayAll()
        self.conductor.quota_commit(self.context, 'reservations')
        self.conductor.quota_commit(self.context, 'reservations', 'proj',
                                    'user')

    def test_quota_rollback(self):
        self.mox.StubOutWithMock(quota.QUOTAS, 'rollback')
        quota.QUOTAS.rollback(self.context, 'reservations', project_id=None,
                              user_id=None)
        quota.QUOTAS.rollback(self.context, 'reservations', project_id='proj',
                              user_id='user')
        self.mox.ReplayAll()
        self.conductor.quota_rollback(self.context, 'reservations')
        self.conductor.quota_rollback(self.context, 'reservations', 'proj',
                                      'user')

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

    def test_instance_info_cache_update(self):
        fake_values = {'key1': 'val1', 'key2': 'val2'}
        fake_inst = {'uuid': 'fake-uuid'}
        self.mox.StubOutWithMock(db, 'instance_info_cache_update')
        db.instance_info_cache_update(self.context, 'fake-uuid',
                                      fake_values)
        self.mox.ReplayAll()
        self.conductor.instance_info_cache_update(self.context,
                                                  fake_inst,
                                                  fake_values)

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

    def test_compute_confirm_resize(self):
        self.mox.StubOutWithMock(self.conductor_manager.compute_api,
                                 'confirm_resize')
        self.conductor_manager.compute_api.confirm_resize(
                self.context, 'instance', migration='migration')
        self.mox.ReplayAll()
        self.conductor.compute_confirm_resize(self.context, 'instance',
                                              'migration')

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

    def test_block_device_mapping_update_or_create(self):
        fake_bdm = {'id': 'fake-id', 'device_name': 'foo'}
        fake_bdm2 = {'id': 'fake-id', 'device_name': 'foo2'}
        cells_rpcapi = self.conductor.cells_rpcapi
        self.mox.StubOutWithMock(db, 'block_device_mapping_create')
        self.mox.StubOutWithMock(db, 'block_device_mapping_update')
        self.mox.StubOutWithMock(db, 'block_device_mapping_update_or_create')
        self.mox.StubOutWithMock(cells_rpcapi,
                                 'bdm_update_or_create_at_top')
        db.block_device_mapping_create(self.context,
                                       fake_bdm).AndReturn(fake_bdm2)
        cells_rpcapi.bdm_update_or_create_at_top(self.context, fake_bdm2,
                                                 create=True)
        db.block_device_mapping_update(self.context, fake_bdm['id'],
                                       fake_bdm).AndReturn(fake_bdm2)
        cells_rpcapi.bdm_update_or_create_at_top(self.context,
                                                 fake_bdm2,
                                                 create=False)
        db.block_device_mapping_update_or_create(
                self.context, fake_bdm).AndReturn(fake_bdm2)
        cells_rpcapi.bdm_update_or_create_at_top(self.context,
                                                 fake_bdm2,
                                                 create=None)
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
        fake_bdm = {'id': 'fake-bdm',
                    'instance_uuid': 'fake-uuid',
                    'device_name': 'fake-device1',
                    'volume_id': 'fake-vol-id1'}
        fake_bdm2 = {'id': 'fake-bdm-2',
                     'instance_uuid': 'fake-uuid2',
                     'device_name': '',
                     'volume_id': 'fake-vol-id2'}
        fake_inst = {'uuid': 'fake-uuid'}

        cells_rpcapi = self.conductor.cells_rpcapi

        self.mox.StubOutWithMock(db, 'block_device_mapping_destroy')
        self.mox.StubOutWithMock(
            db, 'block_device_mapping_destroy_by_instance_and_device')
        self.mox.StubOutWithMock(
            db, 'block_device_mapping_destroy_by_instance_and_volume')
        self.mox.StubOutWithMock(cells_rpcapi, 'bdm_destroy_at_top')

        db.block_device_mapping_destroy(self.context, 'fake-bdm')
        cells_rpcapi.bdm_destroy_at_top(self.context,
                                        fake_bdm['instance_uuid'],
                                        device_name=fake_bdm['device_name'])
        db.block_device_mapping_destroy(self.context, 'fake-bdm-2')
        cells_rpcapi.bdm_destroy_at_top(self.context,
                                        fake_bdm2['instance_uuid'],
                                        volume_id=fake_bdm2['volume_id'])
        db.block_device_mapping_destroy_by_instance_and_device(self.context,
                                                               'fake-uuid',
                                                               'fake-device')
        cells_rpcapi.bdm_destroy_at_top(self.context, fake_inst['uuid'],
                                        device_name='fake-device')
        db.block_device_mapping_destroy_by_instance_and_volume(self.context,
                                                               'fake-uuid',
                                                               'fake-volume')
        cells_rpcapi.bdm_destroy_at_top(self.context, fake_inst['uuid'],
                                        volume_id='fake-volume')

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
                                       columns_to_join=None, use_slave=False)
        self.mox.ReplayAll()
        self.conductor.instance_get_all_by_filters(self.context, filters,
                                                   'fake-key', 'fake-sort')

    def test_instance_get_all_by_filters_use_slave(self):
        filters = {'foo': 'bar'}
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')
        db.instance_get_all_by_filters(self.context, filters,
                                       'fake-key', 'fake-sort',
                                       columns_to_join=None, use_slave=True)
        self.mox.ReplayAll()
        self.conductor.instance_get_all_by_filters(self.context, filters,
                                                   'fake-key', 'fake-sort',
                                                   use_slave=True)

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
            self.assertRaises(messaging.ExpectedException,
                              self.conductor.service_get_all_by,
                              self.context, **condargs)

            self.conductor = utils.ExceptionHelper(self.conductor)

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

    def test_compute_confirm_resize_with_objects(self):
        # use an instance object rather than a dict
        instance = self._create_fake_instance()
        inst_obj = instance_obj.Instance._from_db_object(
                        self.context, instance_obj.Instance(), instance)
        migration = test_migration.fake_db_migration()
        mig_obj = migration_obj.Migration._from_db_object(
                self.context.elevated(), migration_obj.Migration(),
                migration)
        self.mox.StubOutWithMock(self.conductor_manager.compute_api,
                                 'confirm_resize')
        self.conductor_manager.compute_api.confirm_resize(
                        self.context, inst_obj, migration=mig_obj)
        self.mox.ReplayAll()
        self.conductor.compute_confirm_resize(self.context, inst_obj,
                                              mig_obj)

    def _test_object_action(self, is_classmethod, raise_exception):
        class TestObject(obj_base.NovaObject):
            def foo(self, context, raise_exception=False):
                if raise_exception:
                    raise Exception('test')
                else:
                    return 'test'

            @classmethod
            def bar(cls, context, raise_exception=False):
                if raise_exception:
                    raise Exception('test')
                else:
                    return 'test'

        obj = TestObject()
        if is_classmethod:
            result = self.conductor.object_class_action(
                self.context, TestObject.obj_name(), 'bar', '1.0',
                tuple(), {'raise_exception': raise_exception})
        else:
            updates, result = self.conductor.object_action(
                self.context, obj, 'foo', tuple(),
                {'raise_exception': raise_exception})
        self.assertEqual('test', result)

    def test_object_action(self):
        self._test_object_action(False, False)

    def test_object_action_on_raise(self):
        self.assertRaises(messaging.ExpectedException,
                          self._test_object_action, False, True)

    def test_object_class_action(self):
        self._test_object_action(True, False)

    def test_object_class_action_on_raise(self):
        self.assertRaises(messaging.ExpectedException,
                          self._test_object_action, True, True)

    def test_object_action_copies_object(self):
        class TestObject(obj_base.NovaObject):
            fields = {'dict': fields.DictOfStringsField()}

            def touch_dict(self, context):
                self.dict['foo'] = 'bar'
                self.obj_reset_changes()

        obj = TestObject()
        obj.dict = {}
        obj.obj_reset_changes()
        updates, result = self.conductor.object_action(
            self.context, obj, 'touch_dict', tuple(), {})
        # NOTE(danms): If conductor did not properly copy the object, then
        # the new and reference copies of the nested dict object will be
        # the same, and thus 'dict' will not be reported as changed
        self.assertIn('dict', updates)
        self.assertEqual({'foo': 'bar'}, updates['dict'])

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
        self.conductor.aggregate_metadata_delete(self.context, aggregate,
                                                 'fake')

    def test_security_group_get_by_instance(self):
        fake_inst = {'uuid': 'fake-instance'}
        self.mox.StubOutWithMock(db, 'security_group_get_by_instance')
        db.security_group_get_by_instance(
            self.context, fake_inst['uuid']).AndReturn('it worked')
        self.mox.ReplayAll()
        result = self.conductor.security_group_get_by_instance(self.context,
                                                               fake_inst)
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
        fake_bdm = {'id': 'fake-bdm',
                    'instance_uuid': 'fake-uuid',
                    'device_name': 'fake-device1',
                    'volume_id': 'fake-vol-id1'}
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
                                       columns_to_join=None, use_slave=False)
        self.mox.ReplayAll()
        self.conductor.instance_get_all_by_filters(self.context, filters,
                                                   'fake-key', 'fake-sort')

    def test_instance_get_all_by_filters_use_slave(self):
        filters = {'foo': 'bar'}
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')
        db.instance_get_all_by_filters(self.context, filters,
                                       'fake-key', 'fake-sort',
                                       columns_to_join=None, use_slave=True)
        self.mox.ReplayAll()
        self.conductor.instance_get_all_by_filters(self.context, filters,
                                                   'fake-key', 'fake-sort',
                                                   use_slave=True)

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
        fake_bdm = {'id': 'fake-bdm',
                    'instance_uuid': 'fake-uuid',
                    'device_name': 'fake-device1',
                    'volume_id': 'fake-vol-id1'}
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
                raise messaging.MessagingTimeout("fake")

        self.stubs.Set(self.conductor.base_rpcapi, 'ping', fake_ping)

        self.conductor.wait_until_ready(self.context)

        self.assertEqual(timeouts.count(10), 10)
        self.assertIn(None, timeouts)

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
        self.assertIsInstance(conductor.API(), conductor_api.LocalAPI)
        self.assertIsInstance(conductor.ComputeTaskAPI(),
                              conductor_api.LocalComputeTaskAPI)

    def test_import_conductor_rpc(self):
        self.flags(use_local=False, group='conductor')
        self.assertIsInstance(conductor.API(), conductor_api.API)
        self.assertIsInstance(conductor.ComputeTaskAPI(),
                              conductor_api.ComputeTaskAPI)

    def test_import_conductor_override_to_local(self):
        self.flags(use_local=False, group='conductor')
        self.assertIsInstance(conductor.API(use_local=True),
                              conductor_api.LocalAPI)
        self.assertIsInstance(conductor.ComputeTaskAPI(use_local=True),
                              conductor_api.LocalComputeTaskAPI)


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
        fake_instance_actions.stub_out_action_events(self.stubs)

        def fake_deserialize_context(serializer, ctxt_dict):
            self.assertEqual(self.context.user_id, ctxt_dict['user_id'])
            self.assertEqual(self.context.project_id, ctxt_dict['project_id'])
            return self.context

        self.stubs.Set(rpc.RequestContextSerializer, 'deserialize_context',
                       fake_deserialize_context)

    def test_live_migrate(self):
        inst = fake_instance.fake_db_instance()
        inst_obj = instance_obj.Instance._from_db_object(
            self.context, instance_obj.Instance(), inst, [])

        self.mox.StubOutWithMock(live_migrate, 'execute')
        live_migrate.execute(self.context,
                             mox.IsA(instance_obj.Instance),
                             'destination',
                             'block_migration',
                             'disk_over_commit')
        self.mox.ReplayAll()

        if isinstance(self.conductor, (conductor_api.ComputeTaskAPI,
                                       conductor_api.LocalComputeTaskAPI)):
            # The API method is actually 'live_migrate_instance'.  It gets
            # converted into 'migrate_server' when doing RPC.
            self.conductor.live_migrate_instance(self.context, inst_obj,
                'destination', 'block_migration', 'disk_over_commit')
        else:
            self.conductor.migrate_server(self.context, inst_obj,
                {'host': 'destination'}, True, False, None,
                 'block_migration', 'disk_over_commit')

    def test_cold_migrate(self):
        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(
                self.conductor_manager.compute_rpcapi, 'prep_resize')
        self.mox.StubOutWithMock(self.conductor_manager.scheduler_rpcapi,
                                 'select_destinations')
        inst = fake_instance.fake_db_instance(image_ref='image_ref')
        inst_obj = instance_obj.Instance._from_db_object(
            self.context, instance_obj.Instance(), inst, [])
        flavor = flavors.get_default_flavor()
        flavor['extra_specs'] = 'extra_specs'
        request_spec = {'instance_type': flavor}
        compute_utils.get_image_metadata(
            self.context, self.conductor_manager.image_service,
            'image_ref', mox.IsA(instance_obj.Instance)).AndReturn('image')

        scheduler_utils.build_request_spec(
            self.context, 'image',
            [mox.IsA(instance_obj.Instance)],
            instance_type=flavor).AndReturn(request_spec)

        hosts = [dict(host='host1', nodename=None, limits={})]
        self.conductor_manager.scheduler_rpcapi.select_destinations(
            self.context, request_spec, {}).AndReturn(hosts)

        filter_properties = {'limits': {}}

        self.conductor_manager.compute_rpcapi.prep_resize(
            self.context, 'image', mox.IsA(instance_obj.Instance),
            mox.IsA(dict), 'host1', [], request_spec=request_spec,
            filter_properties=filter_properties, node=None)

        self.mox.ReplayAll()

        scheduler_hint = {'filter_properties': {}}

        if isinstance(self.conductor, (conductor_api.ComputeTaskAPI,
                                       conductor_api.LocalComputeTaskAPI)):
            # The API method is actually 'resize_instance'.  It gets
            # converted into 'migrate_server' when doing RPC.
            self.conductor.resize_instance(
                self.context, inst_obj, {}, scheduler_hint, flavor, [])
        else:
            self.conductor.migrate_server(
                self.context, inst_obj, scheduler_hint,
                False, False, flavor, None, None, [])

    def test_build_instances(self):
        instance_type = flavors.get_default_flavor()
        system_metadata = flavors.save_flavor_info({}, instance_type)
        # NOTE(alaski): instance_type -> system_metadata -> instance_type
        # loses some data (extra_specs).  This build process is using
        # scheduler/utils:build_request_spec() which extracts flavor from
        # system_metadata and will re-query the DB for extra_specs.. so
        # we need to test this properly
        expected_instance_type = flavors.extract_flavor(
                {'system_metadata': system_metadata})
        expected_instance_type['extra_specs'] = 'fake-specs'

        self.mox.StubOutWithMock(db, 'flavor_extra_specs_get')
        self.mox.StubOutWithMock(self.conductor_manager.scheduler_rpcapi,
                                 'run_instance')

        db.flavor_extra_specs_get(
                self.context,
                instance_type['flavorid']).AndReturn('fake-specs')
        self.conductor_manager.scheduler_rpcapi.run_instance(self.context,
                request_spec={
                    'image': {'fake_data': 'should_pass_silently'},
                    'instance_properties': {'system_metadata': system_metadata,
                                            'uuid': 'fakeuuid'},
                    'instance_type': expected_instance_type,
                    'instance_uuids': ['fakeuuid', 'fakeuuid2'],
                    'block_device_mapping': 'block_device_mapping',
                    'security_group': 'security_groups',
                    'num_instances': 2},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks='requested_networks', is_first_time=True,
                filter_properties={}, legacy_bdm_in_spec=False)
        self.mox.ReplayAll()

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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
                block_device_mapping='block_device_mapping',
                legacy_bdm=False)

    def test_unshelve_instance_on_host(self):
        db_instance = jsonutils.to_primitive(self._create_fake_instance())
        instance = instance_obj.Instance.get_by_uuid(self.context,
                db_instance['uuid'], expected_attrs=['system_metadata'])
        instance.vm_state = vm_states.SHELVED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'start_instance')
        self.mox.StubOutWithMock(self.conductor_manager, '_delete_image')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        self.conductor_manager.compute_rpcapi.start_instance(self.context,
                instance)
        self.conductor_manager._delete_image(self.context,
                'fake_image_id')
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

    def test_unshelve_instance_schedule_and_rebuild(self):
        db_instance = jsonutils.to_primitive(self._create_fake_instance())
        instance = instance_obj.Instance.get_by_uuid(self.context,
                db_instance['uuid'], expected_attrs=['system_metadata'])
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        filter_properties = {}
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager, '_get_image')
        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        self.conductor_manager._get_image(self.context,
                'fake_image_id').AndReturn('fake_image')
        self.conductor_manager._schedule_instances(self.context,
                'fake_image', filter_properties, instance).AndReturn(
                        [{'host': 'fake_host',
                          'nodename': 'fake_node',
                          'limits': {}}])
        self.conductor_manager.compute_rpcapi.unshelve_instance(self.context,
                instance, 'fake_host', image='fake_image',
                filter_properties={'limits': {}}, node='fake_node')
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

    def test_unshelve_instance_schedule_and_rebuild_novalid_host(self):
        db_instance = jsonutils.to_primitive(self._create_fake_instance())
        instance = instance_obj.Instance.get_by_uuid(self.context,
                db_instance['uuid'], expected_attrs=['system_metadata'])
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        system_metadata = instance.system_metadata

        def fake_schedule_instances(context, image, filter_properties,
                                    *instances):
            raise exc.NoValidHost(reason='')

        with contextlib.nested(
            mock.patch.object(self.conductor_manager, '_get_image',
                              return_value='fake_image'),
            mock.patch.object(self.conductor_manager, '_schedule_instances',
                              fake_schedule_instances)
        ) as (_get_image, _schedule_instances):
            system_metadata['shelved_at'] = timeutils.utcnow()
            system_metadata['shelved_image_id'] = 'fake_image_id'
            system_metadata['shelved_host'] = 'fake-mini'
            self.conductor_manager.unshelve_instance(self.context, instance)
            _get_image.assert_has_calls([mock.call(self.context,
                                      system_metadata['shelved_image_id'])])
            self.assertEqual(vm_states.SHELVED_OFFLOADED, instance.vm_state)

    def test_unshelve_instance_schedule_and_rebuild_volume_backed(self):
        db_instance = jsonutils.to_primitive(self._create_fake_instance())
        instance = instance_obj.Instance.get_by_uuid(self.context,
                db_instance['uuid'], expected_attrs=['system_metadata'])
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        filter_properties = {}
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager, '_get_image')
        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        self.conductor_manager._get_image(self.context,
                'fake_image_id').AndReturn(None)
        self.conductor_manager._schedule_instances(self.context,
                None, filter_properties, instance).AndReturn(
                        [{'host': 'fake_host',
                          'nodename': 'fake_node',
                          'limits': {}}])
        self.conductor_manager.compute_rpcapi.unshelve_instance(self.context,
                instance, 'fake_host', image=None,
                filter_properties={'limits': {}}, node='fake_node')
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)


class ConductorTaskTestCase(_BaseTaskTestCase, test_compute.BaseTestCase):
    """ComputeTaskManager Tests."""
    def setUp(self):
        super(ConductorTaskTestCase, self).setUp()
        self.conductor = conductor_manager.ComputeTaskManager()
        self.conductor_manager = self.conductor

    def test_migrate_server_fails_with_rebuild(self):
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, None, None, True, True, None, None, None)

    def test_migrate_server_fails_with_flavor(self):
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, None, None, True, False, "dummy", None, None)

    def _build_request_spec(self, instance):
        return {
            'instance_properties': {
                'uuid': instance['uuid'], },
        }

    def test_migrate_server_deals_with_expected_exceptions(self):
        instance = fake_instance.fake_db_instance(uuid='uuid',
                                                  vm_state=vm_states.ACTIVE)
        inst_obj = instance_obj.Instance._from_db_object(
            self.context, instance_obj.Instance(), instance, [])
        self.mox.StubOutWithMock(live_migrate, 'execute')
        self.mox.StubOutWithMock(scheduler_utils,
                'set_vm_state_and_notify')

        ex = exc.DestinationHypervisorTooOld()
        live_migrate.execute(self.context, mox.IsA(instance_obj.Instance),
                             'destination', 'block_migration',
                             'disk_over_commit').AndRaise(ex)

        scheduler_utils.set_vm_state_and_notify(self.context,
                'compute_task', 'migrate_server',
                {'vm_state': vm_states.ACTIVE,
                 'task_state': None,
                 'expected_task_state': task_states.MIGRATING},
                ex, self._build_request_spec(inst_obj),
                self.conductor_manager.db)
        self.mox.ReplayAll()

        self.conductor = utils.ExceptionHelper(self.conductor)

        self.assertRaises(exc.DestinationHypervisorTooOld,
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')

    def test_migrate_server_deals_with_unexpected_exceptions(self):
        instance = fake_instance.fake_db_instance()
        inst_obj = instance_obj.Instance._from_db_object(
            self.context, instance_obj.Instance(), instance, [])
        self.mox.StubOutWithMock(live_migrate, 'execute')
        self.mox.StubOutWithMock(scheduler_utils,
                'set_vm_state_and_notify')

        ex = IOError()
        live_migrate.execute(self.context, mox.IsA(instance_obj.Instance),
                             'destination', 'block_migration',
                             'disk_over_commit').AndRaise(ex)
        self.mox.ReplayAll()

        self.conductor = utils.ExceptionHelper(self.conductor)

        self.assertRaises(exc.MigrationError,
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')

    def test_set_vm_state_and_notify(self):
        self.mox.StubOutWithMock(scheduler_utils,
                                 'set_vm_state_and_notify')
        scheduler_utils.set_vm_state_and_notify(
                self.context, 'compute_task', 'method', 'updates',
                'ex', 'request_spec', self.conductor.db)

        self.mox.ReplayAll()

        self.conductor._set_vm_state_and_notify(
                self.context, 'method', 'updates', 'ex', 'request_spec')

    def test_cold_migrate_no_valid_host_back_in_active_state(self):
        inst = fake_instance.fake_db_instance(image_ref='fake-image_ref')
        inst_obj = instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), inst,
                expected_attrs=[])
        request_spec = dict(instance_type=dict(extra_specs=dict()))
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        image = 'fake-image'

        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor.scheduler_rpcapi,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.conductor,
                                 '_set_vm_state_and_notify')
        self.mox.StubOutWithMock(self.conductor.quotas, 'rollback')

        compute_utils.get_image_metadata(
            self.context, self.conductor_manager.image_service,
            'fake-image_ref', mox.IsA(instance_obj.Instance)).AndReturn(image)

        scheduler_utils.build_request_spec(
                self.context, image, [inst_obj],
                instance_type='flavor').AndReturn(request_spec)

        exc_info = exc.NoValidHost(reason="")

        self.conductor.scheduler_rpcapi.select_destinations(
                self.context, request_spec,
                filter_props).AndRaise(exc_info)

        updates = {'vm_state': vm_states.ACTIVE,
                   'task_state': None}

        self.conductor._set_vm_state_and_notify(self.context,
                                                'migrate_server',
                                                updates, exc_info,
                                                request_spec)
        self.conductor.quotas.rollback(self.context, resvs)

        self.mox.ReplayAll()

        self.conductor._cold_migrate(self.context, inst_obj,
                                     'flavor', filter_props, resvs)

    def test_cold_migrate_no_valid_host_back_in_stopped_state(self):
        inst = fake_instance.fake_db_instance(image_ref='fake-image_ref',
                                              vm_state=vm_states.STOPPED)
        inst_obj = instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), inst,
                expected_attrs=[])
        request_spec = dict(instance_type=dict(extra_specs=dict()))
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        image = 'fake-image'

        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor.scheduler_rpcapi,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.conductor,
                                 '_set_vm_state_and_notify')
        self.mox.StubOutWithMock(self.conductor.quotas, 'rollback')

        compute_utils.get_image_metadata(
            self.context, self.conductor_manager.image_service,
            'fake-image_ref', mox.IsA(instance_obj.Instance)).AndReturn(image)

        scheduler_utils.build_request_spec(
                self.context, image, [inst_obj],
                instance_type='flavor').AndReturn(request_spec)

        exc_info = exc.NoValidHost(reason="")

        self.conductor.scheduler_rpcapi.select_destinations(
                self.context, request_spec,
                filter_props).AndRaise(exc_info)

        updates = {'vm_state': vm_states.STOPPED,
                   'task_state': None}

        self.conductor._set_vm_state_and_notify(self.context,
                                                'migrate_server',
                                                updates, exc_info,
                                                request_spec)
        self.conductor.quotas.rollback(self.context, resvs)

        self.mox.ReplayAll()

        self.conductor._cold_migrate(self.context, inst_obj,
                                     'flavor', filter_props, resvs)

    def test_cold_migrate_exception_host_in_error_state_and_raise(self):
        inst = fake_instance.fake_db_instance(image_ref='fake-image_ref',
                                              vm_state=vm_states.STOPPED)
        inst_obj = instance_obj.Instance._from_db_object(
                self.context, instance_obj.Instance(), inst,
                expected_attrs=[])
        request_spec = dict(instance_type=dict(extra_specs=dict()))
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        image = 'fake-image'
        hosts = [dict(host='host1', nodename=None, limits={})]

        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor.scheduler_rpcapi,
                                 'select_destinations')
        self.mox.StubOutWithMock(scheduler_utils,
                                 'populate_filter_properties')
        self.mox.StubOutWithMock(self.conductor.compute_rpcapi,
                                 'prep_resize')
        self.mox.StubOutWithMock(self.conductor,
                                 '_set_vm_state_and_notify')
        self.mox.StubOutWithMock(self.conductor.quotas, 'rollback')

        compute_utils.get_image_metadata(
            self.context, self.conductor_manager.image_service,
            'fake-image_ref', mox.IsA(instance_obj.Instance)).AndReturn(image)

        scheduler_utils.build_request_spec(
                self.context, image, [inst_obj],
                instance_type='flavor').AndReturn(request_spec)

        self.conductor.scheduler_rpcapi.select_destinations(
                self.context, request_spec, filter_props).AndReturn(hosts)

        scheduler_utils.populate_filter_properties(filter_props,
                                                   hosts[0])

        # context popped
        expected_filter_props = dict()
        # extra_specs popped
        expected_request_spec = dict(instance_type=dict())

        exc_info = test.TestingException('something happened')

        self.conductor.compute_rpcapi.prep_resize(
                self.context, image, inst_obj,
                'flavor', hosts[0]['host'], resvs,
                request_spec=expected_request_spec,
                filter_properties=expected_filter_props,
                node=hosts[0]['nodename']).AndRaise(exc_info)

        updates = {'vm_state': vm_states.STOPPED,
                   'task_state': None}

        self.conductor._set_vm_state_and_notify(self.context,
                                                'migrate_server',
                                                updates, exc_info,
                                                expected_request_spec)
        self.conductor.quotas.rollback(self.context, resvs)

        self.mox.ReplayAll()

        self.assertRaises(test.TestingException,
                          self.conductor._cold_migrate,
                          self.context, inst_obj, 'flavor',
                          filter_props, resvs)


class ConductorTaskRPCAPITestCase(_BaseTaskTestCase,
        test_compute.BaseTestCase):
    """Conductor compute_task RPC namespace Tests."""
    def setUp(self):
        super(ConductorTaskRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_rpcapi.ComputeTaskAPI()
        service_manager = self.conductor_service.manager
        self.conductor_manager = service_manager.compute_task_mgr


class ConductorTaskAPITestCase(_BaseTaskTestCase, test_compute.BaseTestCase):
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
