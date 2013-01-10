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

from nova.compute import instance_types
from nova.compute import vm_states
from nova import conductor
from nova.conductor import api as conductor_api
from nova.conductor import manager as conductor_manager
from nova.conductor import rpcapi as conductor_rpcapi
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception as exc
from nova.openstack.common import jsonutils
from nova.openstack.common.rpc import common as rpc_common
from nova.openstack.common import timeutils
from nova import test


FAKE_IMAGE_REF = 'fake-image-ref'


class _BaseTestCase(object):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
        self.db = None
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)

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
        inst['launch_time'] = '10'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['host'] = 'fake_host'
        type_id = instance_types.get_instance_type_by_name(type_name)['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['memory_mb'] = 0
        inst['vcpus'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst['architecture'] = 'x86_64'
        inst['os_type'] = 'Linux'
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

    def test_get_backdoor_port(self):
        backdoor_port = 59697

        def fake_get_backdoor_port(self, context):
            return backdoor_port

        if isinstance(self.conductor, conductor_api.API):
            self.stubs.Set(conductor_manager.ConductorManager,
                          'get_backdoor_port', fake_get_backdoor_port)
            port = self.conductor.get_backdoor_port(self.context, 'fake_host')
        elif isinstance(self.conductor, conductor_api.LocalAPI):
            try:
                self.conductor.get_backdoor_port(self.context, 'fake_host')
            except exc.InvalidRequest:
                port = backdoor_port
        else:
            if isinstance(self.conductor, conductor_rpcapi.ConductorAPI):
                self.stubs.Set(conductor_manager.ConductorManager,
                              'get_backdoor_port', fake_get_backdoor_port)
            self.conductor.backdoor_port = backdoor_port
            port = self.conductor.get_backdoor_port(self.context)

        self.assertEqual(port, backdoor_port)

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
            self.context, fake_inst)
        self.assertEqual(result, 'fake-result')

    def test_instance_get_all_hung_in_rebooting(self):
        self.mox.StubOutWithMock(db, 'instance_get_all_hung_in_rebooting')
        db.instance_get_all_hung_in_rebooting(self.context, 123)
        self.mox.ReplayAll()
        self.conductor.instance_get_all_hung_in_rebooting(self.context, 123)

    def test_instance_get_active_by_window(self):
        self.mox.StubOutWithMock(db, 'instance_get_active_by_window_joined')
        db.instance_get_active_by_window_joined(self.context, 'fake-begin',
                                                'fake-end', 'fake-proj',
                                                'fake-host')
        self.mox.ReplayAll()
        self.conductor.instance_get_active_by_window(self.context,
                                                     'fake-begin', 'fake-end',
                                                     'fake-proj', 'fake-host')

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
        self.mox.StubOutWithMock(db, 'vol_usage_update')
        db.vol_usage_update(self.context, 'fake-vol', 'rd-req', 'rd-bytes',
                            'wr-req', 'wr-bytes', 'fake-id', 'fake-refr',
                            'fake-bool')
        self.mox.ReplayAll()
        self.conductor.vol_usage_update(self.context, 'fake-vol', 'rd-req',
                                        'rd-bytes', 'wr-req', 'wr-bytes',
                                        {'uuid': 'fake-id'}, 'fake-refr',
                                        'fake-bool')

    def test_ping(self):
        result = self.conductor.ping(self.context, 'foo')
        self.assertEqual(result, {'service': 'conductor', 'arg': 'foo'})


class ConductorTestCase(_BaseTestCase, test.TestCase):
    """Conductor Manager Tests."""
    def setUp(self):
        super(ConductorTestCase, self).setUp()
        self.conductor = conductor_manager.ConductorManager()
        self.stub_out_client_exceptions()

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
                                       'fake-key', 'fake-sort')
        self.mox.ReplayAll()
        self.conductor.instance_get_all_by_filters(self.context, filters,
                                                   'fake-key', 'fake-sort')

    def _test_stubbed(self, name, dbargs, condargs):
        self.mox.StubOutWithMock(db, name)
        getattr(db, name)(self.context, *dbargs).AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.service_get_all_by(self.context, **condargs)
        self.assertEqual(result, 'fake-result')

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

    def test_service_get_all_compute_by_host(self):
        self._test_stubbed('service_get_all_compute_by_host',
                           ('host',),
                           dict(topic='compute', host='host'))


class ConductorRPCAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor RPC API Tests."""
    def setUp(self):
        super(ConductorRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
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
                                       'fake-key', 'fake-sort')
        self.mox.ReplayAll()
        self.conductor.instance_get_all_by_filters(self.context, filters,
                                                   'fake-key', 'fake-sort')

    def _test_stubbed(self, name, dbargs, condargs):
        self.mox.StubOutWithMock(db, name)
        getattr(db, name)(self.context, *dbargs).AndReturn('fake-result')
        self.mox.ReplayAll()
        result = self.conductor.service_get_all_by(self.context, **condargs)
        self.assertEqual(result, 'fake-result')

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

    def test_service_get_all_compute_by_host(self):
        self._test_stubbed('service_get_all_compute_by_host',
                           ('host',),
                           dict(topic='compute', host='host'))


class ConductorAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor API Tests."""
    def setUp(self):
        super(ConductorAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_api.API()
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

    def test_instance_get_all(self):
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')
        db.instance_get_all(self.context)
        db.instance_get_all_by_host(self.context.elevated(), 'fake-host')
        db.instance_get_all_by_filters(self.context, {'name': 'fake-inst'},
                                       'updated_at', 'asc')
        self.mox.ReplayAll()
        self.conductor.instance_get_all(self.context)
        self.conductor.instance_get_all_by_host(self.context, 'fake-host')
        self.conductor.instance_get_all_by_filters(self.context,
                                                   {'name': 'fake-inst'},
                                                   'updated_at', 'asc')

    def _test_stubbed(self, name, *args):
        self.mox.StubOutWithMock(db, name)
        getattr(db, name)(self.context, *args).AndReturn('fake-result')
        self.mox.ReplayAll()
        result = getattr(self.conductor, name)(self.context, *args)
        self.assertEqual(result, 'fake-result')

    def test_service_get_all(self):
        self._test_stubbed('service_get_all')

    def test_service_get_by_host_and_topic(self):
        self._test_stubbed('service_get_by_host_and_topic', 'host', 'topic')

    def test_service_get_all_by_topic(self):
        self._test_stubbed('service_get_all_by_topic', 'topic')

    def test_service_get_all_by_host(self):
        self._test_stubbed('service_get_all_by_host', 'host')

    def test_service_get_all_compute_by_host(self):
        self._test_stubbed('service_get_all_compute_by_host', 'host')


class ConductorLocalAPITestCase(ConductorAPITestCase):
    """Conductor LocalAPI Tests."""
    def setUp(self):
        super(ConductorLocalAPITestCase, self).setUp()
        self.conductor = conductor_api.LocalAPI()
        self.db = db
        self.stub_out_client_exceptions()

    def test_client_exceptions(self):
        instance = self._create_fake_instance()
        # NOTE(danms): The LocalAPI should not raise exceptions wrapped
        # in ClientException. KeyError should be raised if an invalid
        # update key is passed, so use that to validate.
        self.assertRaises(KeyError,
                          self._do_update, instance['uuid'], foo='bar')


class ConductorImportTest(test.TestCase):
    def test_import_conductor_local(self):
        self.flags(use_local=True, group='conductor')
        self.assertTrue(isinstance(conductor.API(),
                                   conductor_api.LocalAPI))

    def test_import_conductor_rpc(self):
        self.flags(use_local=False, group='conductor')
        self.assertTrue(isinstance(conductor.API(),
                                   conductor_api.API))


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
