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

"""Tests for the conductor service"""

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

    def test_instance_get_all_by_host(self):
        orig_instance = jsonutils.to_primitive(self._create_fake_instance())
        all_instances = self.conductor.instance_get_all_by_host(
            self.context, orig_instance['host'])
        self.assertEqual(orig_instance['name'],
                         all_instances[0]['name'])

    def _setup_aggregate_with_host(self):
        aggregate_ref = db.aggregate_create(self.context.elevated(),
                {'name': 'foo', 'availability_zone': 'foo'})

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


class ConductorTestCase(_BaseTestCase, test.TestCase):
    """Conductor Manager Tests"""
    def setUp(self):
        super(ConductorTestCase, self).setUp()
        self.conductor = conductor_manager.ConductorManager()
        self.stub_out_client_exceptions()


class ConductorRPCAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor RPC API Tests"""
    def setUp(self):
        super(ConductorRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_rpcapi.ConductorAPI()


class ConductorAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor API Tests"""
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


class ConductorLocalAPITestCase(ConductorAPITestCase):
    """Conductor LocalAPI Tests"""
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
