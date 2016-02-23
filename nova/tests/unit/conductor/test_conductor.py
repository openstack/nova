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

import copy
import uuid

import mock
from mox3 import mox
import oslo_messaging as messaging
from oslo_utils import timeutils
import six

from nova.compute import flavors
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import vm_states
from nova import conductor
from nova.conductor import api as conductor_api
from nova.conductor import manager as conductor_manager
from nova.conductor import rpcapi as conductor_rpcapi
from nova.conductor.tasks import live_migrate
from nova.conductor.tasks import migrate
from nova import context
from nova import db
from nova import exception as exc
from nova.image import api as image_api
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova import rpc
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests import fixtures
from nova.tests.unit import cast_as_call
from nova.tests.unit.compute import test_compute
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_notifier
from nova.tests.unit import fake_request_spec
from nova.tests.unit import fake_server_actions
from nova.tests.unit import fake_utils
from nova import utils


class FakeContext(context.RequestContext):
    def elevated(self):
        """Return a consistent elevated context so we can detect it."""
        if not hasattr(self, '_elevated'):
            self._elevated = super(FakeContext, self).elevated()
        return self._elevated


class _BaseTestCase(object):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
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

        fake_utils.stub_out_utils_spawn_n(self.stubs)


class ConductorTestCase(_BaseTestCase, test.TestCase):
    """Conductor Manager Tests."""
    def setUp(self):
        super(ConductorTestCase, self).setUp()
        self.conductor = conductor_manager.ConductorManager()
        self.conductor_manager = self.conductor

    def _test_object_action(self, is_classmethod, raise_exception):
        class TestObject(obj_base.NovaObject):
            def foo(self, raise_exception=False):
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

        obj_base.NovaObjectRegistry.register(TestObject)

        obj = TestObject()
        # NOTE(danms): After a trip over RPC, any tuple will be a list,
        # so use a list here to make sure we can handle it
        fake_args = []
        if is_classmethod:
            versions = {'TestObject': '1.0'}
            result = self.conductor.object_class_action_versions(
                self.context, TestObject.obj_name(), 'bar', versions,
                fake_args, {'raise_exception': raise_exception})
        else:
            updates, result = self.conductor.object_action(
                self.context, obj, 'foo', fake_args,
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

            def touch_dict(self):
                self.dict['foo'] = 'bar'
                self.obj_reset_changes()

        obj_base.NovaObjectRegistry.register(TestObject)

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

    def test_object_class_action_versions(self):
        @obj_base.NovaObjectRegistry.register
        class TestObject(obj_base.NovaObject):
            VERSION = '1.10'

            @classmethod
            def foo(cls, context):
                return cls()

        versions = {
            'TestObject': '1.2',
            'OtherObj': '1.0',
        }
        with mock.patch.object(self.conductor_manager,
                               '_object_dispatch') as m:
            m.return_value = TestObject()
            m.return_value.obj_to_primitive = mock.MagicMock()
            self.conductor.object_class_action_versions(
                self.context, TestObject.obj_name(), 'foo', versions,
                tuple(), {})
            m.return_value.obj_to_primitive.assert_called_once_with(
                target_version='1.2', version_manifest=versions)

    def test_reset(self):
        with mock.patch.object(objects.Service, 'clear_min_version_cache'
                               ) as mock_clear_cache:
            self.conductor.reset()
            mock_clear_cache.assert_called_once_with()

    def test_provider_fw_rule_get_all(self):
        result = self.conductor.provider_fw_rule_get_all(self.context)
        self.assertEqual([], result)


class ConductorRPCAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor RPC API Tests."""
    def setUp(self):
        super(ConductorRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor_manager = self.conductor_service.manager
        self.conductor = conductor_rpcapi.ConductorAPI()


class ConductorAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor API Tests."""
    def setUp(self):
        super(ConductorAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_api.API()
        self.conductor_manager = self.conductor_service.manager

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

    @mock.patch('oslo_versionedobjects.base.obj_tree_get_versions')
    def test_object_backport_redirect(self, mock_ovo):
        mock_ovo.return_value = mock.sentinel.obj_versions
        mock_objinst = mock.Mock()

        with mock.patch.object(self.conductor,
                               'object_backport_versions') as mock_call:
            self.conductor.object_backport(mock.sentinel.ctxt,
                                           mock_objinst,
                                           mock.sentinel.target_version)
            mock_call.assert_called_once_with(mock.sentinel.ctxt,
                                              mock_objinst,
                                              mock.sentinel.obj_versions)


class ConductorLocalAPITestCase(ConductorAPITestCase):
    """Conductor LocalAPI Tests."""
    def setUp(self):
        super(ConductorLocalAPITestCase, self).setUp()
        self.conductor = conductor_api.LocalAPI()
        self.conductor_manager = self.conductor._manager._target

    def test_wait_until_ready(self):
        # Override test in ConductorAPITestCase
        pass


class ConductorImportTest(test.NoDBTestCase):
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


class _BaseTaskTestCase(object):
    def setUp(self):
        super(_BaseTaskTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = FakeContext(self.user_id, self.project_id)
        fake_server_actions.stub_out_action_events(self.stubs)

        def fake_deserialize_context(serializer, ctxt_dict):
            self.assertEqual(self.context.user_id, ctxt_dict['user_id'])
            self.assertEqual(self.context.project_id, ctxt_dict['project_id'])
            return self.context

        self.stubs.Set(rpc.RequestContextSerializer, 'deserialize_context',
                       fake_deserialize_context)

        self.useFixture(fixtures.SpawnIsSynchronousFixture())

    def _prepare_rebuild_args(self, update_args=None):
        # Args that don't get passed in to the method but do get passed to RPC
        migration = update_args and update_args.pop('migration', None)
        node = update_args and update_args.pop('node', None)
        limits = update_args and update_args.pop('limits', None)

        rebuild_args = {'new_pass': 'admin_password',
                        'injected_files': 'files_to_inject',
                        'image_ref': 'image_ref',
                        'orig_image_ref': 'orig_image_ref',
                        'orig_sys_metadata': 'orig_sys_meta',
                        'bdms': {},
                        'recreate': False,
                        'on_shared_storage': False,
                        'preserve_ephemeral': False,
                        'host': 'compute-host',
                        'request_spec': None}
        if update_args:
            rebuild_args.update(update_args)
        compute_rebuild_args = copy.deepcopy(rebuild_args)
        compute_rebuild_args['migration'] = migration
        compute_rebuild_args['node'] = node
        compute_rebuild_args['limits'] = limits

        # Args that are passed in to the method but don't get passed to RPC
        compute_rebuild_args.pop('request_spec')

        return rebuild_args, compute_rebuild_args

    @mock.patch('nova.objects.Migration')
    def test_live_migrate(self, migobj):
        inst = fake_instance.fake_db_instance()
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), inst, [])

        migration = migobj()
        self.mox.StubOutWithMock(live_migrate.LiveMigrationTask, 'execute')
        task = self.conductor_manager._build_live_migrate_task(
            self.context, inst_obj, 'destination', 'block_migration',
            'disk_over_commit', migration)
        task.execute()
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

        self.assertEqual('accepted', migration.status)
        self.assertEqual('destination', migration.dest_compute)
        self.assertEqual(inst_obj.host, migration.source_compute)

    def _test_cold_migrate(self, clean_shutdown=True):
        self.mox.StubOutWithMock(utils, 'get_image_from_system_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(migrate.MigrationTask, 'execute')
        inst = fake_instance.fake_db_instance(image_ref='image_ref')
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), inst, [])
        inst_obj.system_metadata = {'image_hw_disk_bus': 'scsi'}
        flavor = flavors.get_default_flavor()
        flavor.extra_specs = {'extra_specs': 'fake'}
        filter_properties = {'limits': {},
                             'retry': {'num_attempts': 1,
                                       'hosts': [['host1', None]]}}
        request_spec = {'instance_type': obj_base.obj_to_primitive(flavor),
                        'instance_properties': {}}
        utils.get_image_from_system_metadata(
            inst_obj.system_metadata).AndReturn('image')

        scheduler_utils.build_request_spec(
            self.context, 'image',
            [mox.IsA(objects.Instance)],
            instance_type=mox.IsA(objects.Flavor)).AndReturn(request_spec)
        task = self.conductor_manager._build_cold_migrate_task(
            self.context, inst_obj, flavor, filter_properties,
            request_spec, [], clean_shutdown=clean_shutdown)
        task.execute()
        self.mox.ReplayAll()

        scheduler_hint = {'filter_properties': {}}

        if isinstance(self.conductor, (conductor_api.ComputeTaskAPI,
                                       conductor_api.LocalComputeTaskAPI)):
            # The API method is actually 'resize_instance'.  It gets
            # converted into 'migrate_server' when doing RPC.
            self.conductor.resize_instance(
                self.context, inst_obj, {}, scheduler_hint, flavor, [],
                clean_shutdown)
        else:
            self.conductor.migrate_server(
                self.context, inst_obj, scheduler_hint,
                False, False, flavor, None, None, [],
                clean_shutdown)

    def test_cold_migrate(self):
        self._test_cold_migrate()

    def test_cold_migrate_forced_shutdown(self):
        self._test_cold_migrate(clean_shutdown=False)

    @mock.patch('nova.objects.Instance.refresh')
    def test_build_instances(self, mock_refresh):
        instance_type = flavors.get_default_flavor()
        instances = [objects.Instance(context=self.context,
                                      id=i,
                                      uuid=uuid.uuid4(),
                                      flavor=instance_type) for i in range(2)]
        instance_type_p = obj_base.obj_to_primitive(instance_type)
        instance_properties = obj_base.obj_to_primitive(instances[0])
        instance_properties['system_metadata'] = flavors.save_flavor_info(
            {}, instance_type)

        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(db,
                                 'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                                 'build_and_run_instance')

        spec = {'image': {'fake_data': 'should_pass_silently'},
                'instance_properties': instance_properties,
                'instance_type': instance_type_p,
                'num_instances': 2}
        filter_properties = {'retry': {'num_attempts': 1, 'hosts': []}}
        self.conductor_manager._schedule_instances(self.context,
                spec, filter_properties).AndReturn(
                        [{'host': 'host1', 'nodename': 'node1', 'limits': []},
                         {'host': 'host2', 'nodename': 'node2', 'limits': []}])
        db.block_device_mapping_get_all_by_instance(self.context,
                instances[0].uuid).AndReturn([])
        self.conductor_manager.compute_rpcapi.build_and_run_instance(
                self.context,
                instance=mox.IgnoreArg(),
                host='host1',
                image={'fake_data': 'should_pass_silently'},
                request_spec={
                    'image': {'fake_data': 'should_pass_silently'},
                    'instance_properties': instance_properties,
                    'instance_type': instance_type_p,
                    'num_instances': 2},
                filter_properties={'retry': {'num_attempts': 1,
                                             'hosts': [['host1', 'node1']]},
                                   'limits': []},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=mox.IgnoreArg(),
                node='node1', limits=[])
        db.block_device_mapping_get_all_by_instance(self.context,
                instances[1].uuid).AndReturn([])
        self.conductor_manager.compute_rpcapi.build_and_run_instance(
                self.context,
                instance=mox.IgnoreArg(),
                host='host2',
                image={'fake_data': 'should_pass_silently'},
                request_spec={
                    'image': {'fake_data': 'should_pass_silently'},
                    'instance_properties': instance_properties,
                    'instance_type': instance_type_p,
                    'num_instances': 2},
                filter_properties={'limits': [],
                                   'retry': {'num_attempts': 1,
                                             'hosts': [['host2', 'node2']]}},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=mox.IgnoreArg(),
                node='node2', limits=[])
        self.mox.ReplayAll()

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.conductor.build_instances(self.context,
                instances=instances,
                image={'fake_data': 'should_pass_silently'},
                filter_properties={},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping='block_device_mapping',
                legacy_bdm=False)

    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_cleanup_allocated_networks')
    def test_build_instances_scheduler_failure(
            self, cleanup_mock, sd_mock, state_mock,
            sig_mock, bs_mock):
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}
        exception = exc.NoValidHost(reason='fake-reason')

        bs_mock.return_value = spec
        sd_mock.side_effect = exception
        updates = {'vm_state': vm_states.ERROR, 'task_state': None}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.conductor.build_instances(
            self.context,
            instances=instances,
            image=image,
            filter_properties={},
            admin_password='admin_password',
            injected_files='injected_files',
            requested_networks=None,
            security_groups='security_groups',
            block_device_mapping='block_device_mapping',
            legacy_bdm=False)

        set_state_calls = []
        cleanup_network_calls = []
        for instance in instances:
            set_state_calls.append(mock.call(
                self.context, instance.uuid, 'compute_task', 'build_instances',
                updates, exception, spec))
            cleanup_network_calls.append(mock.call(
                self.context, mock.ANY, None))
        state_mock.assert_has_calls(set_state_calls)
        cleanup_mock.assert_has_calls(cleanup_network_calls)

    def test_build_instances_retry_exceeded(self):
        instances = [fake_instance.fake_instance_obj(self.context)]
        image = {'fake-data': 'should_pass_silently'}
        filter_properties = {'retry': {'num_attempts': 10, 'hosts': []}}
        updates = {'vm_state': vm_states.ERROR, 'task_state': None}

        @mock.patch.object(conductor_manager.ComputeTaskManager,
                           '_cleanup_allocated_networks')
        @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
        @mock.patch.object(scheduler_utils, 'populate_retry')
        def _test(populate_retry,
                  set_vm_state_and_notify, cleanup_mock):
            # build_instances() is a cast, we need to wait for it to
            # complete
            self.useFixture(cast_as_call.CastAsCall(self.stubs))

            populate_retry.side_effect = exc.MaxRetriesExceeded(
                reason="Too many try")

            self.conductor.build_instances(
                self.context,
                instances=instances,
                image=image,
                filter_properties=filter_properties,
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping='block_device_mapping',
                legacy_bdm=False)

            populate_retry.assert_called_once_with(
                filter_properties, instances[0].uuid)
            set_vm_state_and_notify.assert_called_once_with(
                self.context, instances[0].uuid, 'compute_task',
                'build_instances', updates, mock.ANY, {})
            cleanup_mock.assert_called_once_with(self.context, mock.ANY, None)

        _test()

    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_cleanup_allocated_networks')
    def test_build_instances_scheduler_group_failure(
            self, cleanup_mock, state_mock, sig_mock, bs_mock):
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}

        bs_mock.return_value = spec
        exception = exc.UnsupportedPolicyException(reason='fake-reason')
        sig_mock.side_effect = exception

        updates = {'vm_state': vm_states.ERROR, 'task_state': None}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.conductor.build_instances(
                          context=self.context,
                          instances=instances,
                          image=image,
                          filter_properties={},
                          admin_password='admin_password',
                          injected_files='injected_files',
                          requested_networks=None,
                          security_groups='security_groups',
                          block_device_mapping='block_device_mapping',
                          legacy_bdm=False)
        set_state_calls = []
        cleanup_network_calls = []
        for instance in instances:
            set_state_calls.append(mock.call(
                self.context, instance.uuid, 'build_instances', updates,
                exception, spec))
            cleanup_network_calls.append(mock.call(
                self.context, mock.ANY, None))
        state_mock.assert_has_calls(set_state_calls)
        cleanup_mock.assert_has_calls(cleanup_network_calls)

    def test_unshelve_instance_on_host(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'start_instance')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        self.conductor_manager.compute_rpcapi.start_instance(self.context,
                instance)
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

    def test_unshelve_offload_instance_on_host_with_request_spec(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'

        fake_spec = fake_request_spec.fake_spec_obj()
        # FIXME(sbauza): Modify the fake RequestSpec object to either add a
        # non-empty SchedulerRetries object or nullify the field
        fake_spec.retry = None
        # FIXME(sbauza): Modify the fake RequestSpec object to either add a
        # non-empty SchedulerLimits object or nullify the field
        fake_spec.limits = None
        # FIXME(sbauza): Modify the fake RequestSpec object to either add a
        # non-empty InstanceGroup object or nullify the field
        fake_spec.instance_group = None

        filter_properties = fake_spec.to_legacy_filter_properties_dict()
        request_spec = fake_spec.to_legacy_request_spec_dict()

        host = {'host': 'host1', 'nodename': 'node1', 'limits': []}

        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                           'unshelve_instance')
        @mock.patch.object(self.conductor_manager, '_schedule_instances')
        def do_test(sched_instances, unshelve_instance):
            sched_instances.return_value = [host]
            self.conductor_manager.unshelve_instance(self.context, instance,
                                                     fake_spec)
            scheduler_utils.populate_retry(filter_properties, instance.uuid)
            scheduler_utils.populate_filter_properties(filter_properties, host)
            sched_instances.assert_called_once_with(self.context, request_spec,
                                                    filter_properties)
            unshelve_instance.assert_called_once_with(
                self.context, instance, host['host'], image=mock.ANY,
                filter_properties=filter_properties, node=host['nodename']
            )

        do_test()

    def test_unshelve_offloaded_instance_glance_image_not_found(self):
        shelved_image_id = "image_not_found"

        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager.image_api, 'get')

        e = exc.ImageNotFound(image_id=shelved_image_id)
        self.conductor_manager.image_api.get(
            self.context, shelved_image_id, show_deleted=False).AndRaise(e)
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_host'] = 'fake-mini'
        system_metadata['shelved_image_id'] = shelved_image_id

        self.assertRaises(
            exc.UnshelveException,
            self.conductor_manager.unshelve_instance,
            self.context, instance)
        self.assertEqual(instance.vm_state, vm_states.ERROR)

    def test_unshelve_offloaded_instance_image_id_is_none(self):

        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        # 'shelved_image_id' is None for volumebacked instance
        instance.system_metadata['shelved_image_id'] = None

        with test.nested(
            mock.patch.object(self.conductor_manager,
                              '_schedule_instances'),
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'unshelve_instance'),
        ) as (schedule_mock, unshelve_mock):
            schedule_mock.return_value = [{'host': 'fake_host',
                                           'nodename': 'fake_node',
                                           'limits': {}}]
            self.conductor_manager.unshelve_instance(self.context, instance)
            self.assertEqual(1, unshelve_mock.call_count)

    def test_unshelve_instance_schedule_and_rebuild(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        filter_properties = {'retry': {'num_attempts': 1,
                                       'hosts': []}}
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager.image_api, 'get')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        self.conductor_manager.image_api.get(self.context,
                'fake_image_id', show_deleted=False).AndReturn('fake_image')
        scheduler_utils.build_request_spec(self.context, 'fake_image',
                mox.IgnoreArg()).AndReturn('req_spec')
        self.conductor_manager._schedule_instances(self.context,
                'req_spec', filter_properties).AndReturn(
                        [{'host': 'fake_host',
                          'nodename': 'fake_node',
                          'limits': {}}])
        self.conductor_manager.compute_rpcapi.unshelve_instance(self.context,
                instance, 'fake_host', image='fake_image',
                filter_properties={'limits': {},
                                   'retry': {'num_attempts': 1,
                                             'hosts': [['fake_host',
                                                        'fake_node']]}},
                                    node='fake_node')
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

    def test_unshelve_instance_schedule_and_rebuild_novalid_host(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        system_metadata = instance.system_metadata

        def fake_schedule_instances(context, image, filter_properties,
                                    *instances):
            raise exc.NoValidHost(reason='')

        with test.nested(
            mock.patch.object(self.conductor_manager.image_api, 'get',
                              return_value='fake_image'),
            mock.patch.object(self.conductor_manager, '_schedule_instances',
                              fake_schedule_instances)
        ) as (_get_image, _schedule_instances):
            system_metadata['shelved_at'] = timeutils.utcnow()
            system_metadata['shelved_image_id'] = 'fake_image_id'
            system_metadata['shelved_host'] = 'fake-mini'
            self.conductor_manager.unshelve_instance(self.context, instance)
            _get_image.assert_has_calls([mock.call(self.context,
                                      system_metadata['shelved_image_id'],
                                      show_deleted=False)])
            self.assertEqual(vm_states.SHELVED_OFFLOADED, instance.vm_state)

    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances',
                       side_effect=messaging.MessagingTimeout())
    @mock.patch.object(image_api.API, 'get', return_value='fake_image')
    def test_unshelve_instance_schedule_and_rebuild_messaging_exception(
            self, mock_get_image, mock_schedule_instances):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.assertRaises(messaging.MessagingTimeout,
                          self.conductor_manager.unshelve_instance,
                          self.context, instance)
        mock_get_image.assert_has_calls([mock.call(self.context,
                                        system_metadata['shelved_image_id'],
                                        show_deleted=False)])
        self.assertEqual(vm_states.SHELVED_OFFLOADED, instance.vm_state)
        self.assertIsNone(instance.task_state)

    def test_unshelve_instance_schedule_and_rebuild_volume_backed(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        filter_properties = {'retry': {'num_attempts': 1,
                                       'hosts': []}}
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        scheduler_utils.build_request_spec(self.context, None,
                mox.IgnoreArg()).AndReturn('req_spec')
        self.conductor_manager._schedule_instances(self.context,
                'req_spec', filter_properties).AndReturn(
                        [{'host': 'fake_host',
                          'nodename': 'fake_node',
                          'limits': {}}])
        self.conductor_manager.compute_rpcapi.unshelve_instance(self.context,
                instance, 'fake_host', image=None,
                filter_properties={'limits': {},
                                   'retry': {'num_attempts': 1,
                                             'hosts': [['fake_host',
                                                        'fake_node']]}},
                node='fake_node')
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

    def test_rebuild_instance(self):
        inst_obj = self._create_fake_instance_obj()
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': inst_obj.host})

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations')
        ) as (rebuild_mock, select_dest_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            self.assertFalse(select_dest_mock.called)
            rebuild_mock.assert_called_once_with(self.context,
                               instance=inst_obj,
                               **compute_args)

    def test_rebuild_instance_with_scheduler(self):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        expected_host = 'thebesthost'
        expected_node = 'thebestnode'
        expected_limits = 'fake-limits'
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': None, 'node': expected_node, 'limits': expected_limits})
        request_spec = {}
        filter_properties = {'ignore_hosts': [(inst_obj.host)]}
        fake_spec = objects.RequestSpec()
        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(objects.RequestSpec, 'from_primitives',
                              return_value=fake_spec),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations',
                              return_value=[{'host': expected_host,
                                             'nodename': expected_node,
                                             'limits': expected_limits}]),
            mock.patch('nova.scheduler.utils.build_request_spec',
                       return_value=request_spec)
        ) as (rebuild_mock, sig_mock, fp_mock, select_dest_mock, bs_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            fp_mock.assert_called_once_with(self.context, request_spec,
                                            filter_properties)
            select_dest_mock.assert_called_once_with(self.context, fake_spec)
            compute_args['host'] = expected_host
            rebuild_mock.assert_called_once_with(self.context,
                                            instance=inst_obj,
                                            **compute_args)
        self.assertEqual('compute.instance.rebuild.scheduled',
                         fake_notifier.NOTIFICATIONS[0].event_type)

    def test_rebuild_instance_with_scheduler_no_host(self):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        rebuild_args, _ = self._prepare_rebuild_args({'host': None})
        request_spec = {}
        filter_properties = {'ignore_hosts': [(inst_obj.host)]}
        fake_spec = objects.RequestSpec()

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(objects.RequestSpec, 'from_primitives',
                              return_value=fake_spec),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations',
                              side_effect=exc.NoValidHost(reason='')),
            mock.patch('nova.scheduler.utils.build_request_spec',
                       return_value=request_spec)
        ) as (rebuild_mock, sig_mock, fp_mock, select_dest_mock, bs_mock):
            self.assertRaises(exc.NoValidHost,
                              self.conductor_manager.rebuild_instance,
                              context=self.context, instance=inst_obj,
                              **rebuild_args)
            fp_mock.assert_called_once_with(self.context, request_spec,
                                            filter_properties)
            select_dest_mock.assert_called_once_with(self.context, fake_spec)
            self.assertFalse(rebuild_mock.called)

    @mock.patch.object(conductor_manager.compute_rpcapi.ComputeAPI,
                       'rebuild_instance')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(conductor_manager.scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch('nova.scheduler.utils.build_request_spec')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_rebuild_instance_with_scheduler_group_failure(self,
                                                           state_mock,
                                                           bs_mock,
                                                           select_dest_mock,
                                                           sig_mock,
                                                           rebuild_mock):
        inst_obj = self._create_fake_instance_obj()
        rebuild_args, _ = self._prepare_rebuild_args({'host': None})
        request_spec = {}
        bs_mock.return_value = request_spec

        exception = exc.UnsupportedPolicyException(reason='')
        sig_mock.side_effect = exception

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.assertRaises(exc.UnsupportedPolicyException,
                          self.conductor.rebuild_instance,
                          self.context,
                          inst_obj,
                          **rebuild_args)
        updates = {'vm_state': vm_states.ACTIVE, 'task_state': None}
        state_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                           'rebuild_server', updates,
                                           exception, request_spec)
        self.assertFalse(select_dest_mock.called)
        self.assertFalse(rebuild_mock.called)

    def test_rebuild_instance_evacuate_migration_record(self):
        inst_obj = self._create_fake_instance_obj()
        migration = objects.Migration(context=self.context,
                                      source_compute=inst_obj.host,
                                      source_node=inst_obj.node,
                                      instance_uuid=inst_obj.uuid,
                                      status='accepted',
                                      migration_type='evacuation')
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': inst_obj.host, 'migration': migration})

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations'),
            mock.patch.object(objects.Migration, 'get_by_instance_and_status',
                              return_value=migration)
        ) as (rebuild_mock, select_dest_mock, get_migration_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            self.assertFalse(select_dest_mock.called)
            rebuild_mock.assert_called_once_with(self.context,
                               instance=inst_obj,
                               **compute_args)

    def test_rebuild_instance_with_request_spec(self):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        expected_host = 'thebesthost'
        expected_node = 'thebestnode'
        expected_limits = 'fake-limits'
        request_spec = {}
        filter_properties = {'ignore_hosts': [(inst_obj.host)]}
        fake_spec = objects.RequestSpec(ignore_hosts=[])
        augmented_spec = objects.RequestSpec(ignore_hosts=[inst_obj.host])
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': None, 'node': expected_node, 'limits': expected_limits,
             'request_spec': fake_spec})
        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(objects.RequestSpec, 'from_primitives',
                              return_value=augmented_spec),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations',
                              return_value=[{'host': expected_host,
                                             'nodename': expected_node,
                                             'limits': expected_limits}]),
            mock.patch.object(fake_spec, 'to_legacy_request_spec_dict',
                       return_value=request_spec),
            mock.patch.object(fake_spec, 'to_legacy_filter_properties_dict',
                       return_value=filter_properties),
        ) as (rebuild_mock, sig_mock, fp_mock, select_dest_mock, to_reqspec,
              to_filtprops):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            to_reqspec.assert_called_once_with()
            to_filtprops.assert_called_once_with()
            fp_mock.assert_called_once_with(self.context, request_spec,
                                            filter_properties)
            select_dest_mock.assert_called_once_with(self.context,
                                                     augmented_spec)
            compute_args['host'] = expected_host
            rebuild_mock.assert_called_once_with(self.context,
                                            instance=inst_obj,
                                            **compute_args)
        self.assertEqual('compute.instance.rebuild.scheduled',
                         fake_notifier.NOTIFICATIONS[0].event_type)


class ConductorTaskTestCase(_BaseTaskTestCase, test_compute.BaseTestCase):
    """ComputeTaskManager Tests."""
    def setUp(self):
        super(ConductorTaskTestCase, self).setUp()
        self.conductor = conductor_manager.ComputeTaskManager()
        self.conductor_manager = self.conductor

    def test_reset(self):
        with mock.patch('nova.compute.rpcapi.ComputeAPI') as mock_rpc:
            old_rpcapi = self.conductor_manager.compute_rpcapi
            self.conductor_manager.reset()
            mock_rpc.assert_called_once_with()
            self.assertNotEqual(old_rpcapi,
                                self.conductor_manager.compute_rpcapi)

    def test_migrate_server_fails_with_rebuild(self):
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, None, None, True, True, None, None, None)

    def test_migrate_server_fails_with_flavor(self):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, None, None, True, False, flavor, None, None)

    def _build_request_spec(self, instance):
        return {
            'instance_properties': {
                'uuid': instance['uuid'], },
        }

    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(live_migrate.LiveMigrationTask, 'execute')
    def _test_migrate_server_deals_with_expected_exceptions(self, ex,
        mock_execute, mock_set):
        instance = fake_instance.fake_db_instance(uuid='uuid',
                                                  vm_state=vm_states.ACTIVE)
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance, [])
        mock_execute.side_effect = ex
        self.conductor = utils.ExceptionHelper(self.conductor)

        self.assertRaises(type(ex),
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')

        mock_set.assert_called_once_with(self.context,
                inst_obj.uuid,
                'compute_task', 'migrate_server',
                {'vm_state': vm_states.ACTIVE,
                 'task_state': None,
                 'expected_task_state': task_states.MIGRATING},
                ex, self._build_request_spec(inst_obj))

    def test_migrate_server_deals_with_invalidcpuinfo_exception(self):
        instance = fake_instance.fake_db_instance(uuid='uuid',
                                                  vm_state=vm_states.ACTIVE)
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance, [])
        self.mox.StubOutWithMock(live_migrate.LiveMigrationTask, 'execute')
        self.mox.StubOutWithMock(scheduler_utils,
                'set_vm_state_and_notify')

        ex = exc.InvalidCPUInfo(reason="invalid cpu info.")

        task = self.conductor._build_live_migrate_task(
            self.context, inst_obj, 'destination', 'block_migration',
            'disk_over_commit', mox.IsA(objects.Migration))
        task.execute().AndRaise(ex)

        scheduler_utils.set_vm_state_and_notify(self.context,
                inst_obj.uuid,
                'compute_task', 'migrate_server',
                {'vm_state': vm_states.ACTIVE,
                 'task_state': None,
                 'expected_task_state': task_states.MIGRATING},
                ex, self._build_request_spec(inst_obj))
        self.mox.ReplayAll()

        self.conductor = utils.ExceptionHelper(self.conductor)

        self.assertRaises(exc.InvalidCPUInfo,
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')

    def test_migrate_server_deals_with_expected_exception(self):
        exs = [exc.InstanceInvalidState(instance_uuid="fake", attr='',
                                        state='', method=''),
               exc.DestinationHypervisorTooOld(),
               exc.HypervisorUnavailable(host='dummy'),
               exc.LiveMigrationWithOldNovaNotSafe(server='dummy'),
               exc.MigrationPreCheckError(reason='dummy'),
               exc.InvalidSharedStorage(path='dummy', reason='dummy'),
               exc.NoValidHost(reason='dummy'),
               exc.ComputeServiceUnavailable(host='dummy'),
               exc.InvalidHypervisorType(),
               exc.InvalidCPUInfo(reason='dummy'),
               exc.UnableToMigrateToSelf(instance_id='dummy', host='dummy'),
               exc.InvalidLocalStorage(path='dummy', reason='dummy'),
               exc.MigrationSchedulerRPCError(reason='dummy')]
        for ex in exs:
            self._test_migrate_server_deals_with_expected_exceptions(ex)

    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(live_migrate.LiveMigrationTask, 'execute')
    def test_migrate_server_deals_with_unexpected_exceptions(self,
            mock_live_migrate, mock_set_state):
        expected_ex = IOError('fake error')
        mock_live_migrate.side_effect = expected_ex
        instance = fake_instance.fake_db_instance()
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance, [])
        ex = self.assertRaises(exc.MigrationError,
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')
        request_spec = {'instance_properties': {
                'uuid': instance['uuid'], },
        }
        mock_set_state.assert_called_once_with(self.context,
                        instance['uuid'],
                        'compute_task', 'migrate_server',
                        dict(vm_state=vm_states.ERROR,
                             task_state=inst_obj.task_state,
                             expected_task_state=task_states.MIGRATING,),
                        expected_ex, request_spec)
        self.assertEqual(ex.kwargs['reason'], six.text_type(expected_ex))

    def test_set_vm_state_and_notify(self):
        self.mox.StubOutWithMock(scheduler_utils,
                                 'set_vm_state_and_notify')
        scheduler_utils.set_vm_state_and_notify(
                self.context, 1, 'compute_task', 'method', 'updates',
                'ex', 'request_spec')

        self.mox.ReplayAll()

        self.conductor._set_vm_state_and_notify(
                self.context, 1, 'method', 'updates', 'ex', 'request_spec')

    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(objects.Quotas, 'from_reservations')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    def test_cold_migrate_no_valid_host_back_in_active_state(
            self, rollback_mock, notify_mock, select_dest_mock, quotas_mock,
            metadata_mock, spec_fp_mock, sig_mock, brs_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            instance_type_id=flavor['id'],
            vm_state=vm_states.ACTIVE,
            system_metadata={},
            uuid='fake',
            user_id='fake')
        request_spec = dict(instance_type=dict(extra_specs=dict()),
                            instance_properties=dict())
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        image = 'fake-image'
        fake_spec = objects.RequestSpec()
        metadata_mock.return_value = image
        brs_mock.return_value = request_spec
        spec_fp_mock.return_value = fake_spec
        exc_info = exc.NoValidHost(reason="")
        select_dest_mock.side_effect = exc_info
        updates = {'vm_state': vm_states.ACTIVE,
                   'task_state': None}
        self.assertRaises(exc.NoValidHost,
                          self.conductor._cold_migrate,
                          self.context, inst_obj,
                          flavor, filter_props, [resvs],
                          clean_shutdown=True)
        metadata_mock.assert_called_with({})
        brs_mock.assert_called_once_with(self.context, image,
                                         [inst_obj],
                                         instance_type=flavor)
        quotas_mock.assert_called_once_with(self.context, [resvs],
                                            instance=inst_obj)
        sig_mock.assert_called_once_with(self.context, request_spec,
                                         filter_props)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                              'migrate_server', updates,
                                              exc_info, request_spec)
        rollback_mock.assert_called_once_with()

    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(objects.Quotas, 'from_reservations')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    def test_cold_migrate_no_valid_host_back_in_stopped_state(
            self, rollback_mock, notify_mock, select_dest_mock, quotas_mock,
            metadata_mock, spec_fp_mock, sig_mock, brs_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid='fake',
            user_id='fake')
        image = 'fake-image'
        request_spec = dict(instance_type=dict(extra_specs=dict()),
                            instance_properties=dict(),
                            image=image)
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        fake_spec = objects.RequestSpec()

        metadata_mock.return_value = image
        brs_mock.return_value = request_spec
        spec_fp_mock.return_value = fake_spec
        exc_info = exc.NoValidHost(reason="")
        select_dest_mock.side_effect = exc_info
        updates = {'vm_state': vm_states.STOPPED,
                   'task_state': None}
        self.assertRaises(exc.NoValidHost,
                           self.conductor._cold_migrate,
                           self.context, inst_obj,
                           flavor, filter_props, [resvs],
                           clean_shutdown=True)
        metadata_mock.assert_called_with({})
        brs_mock.assert_called_once_with(self.context, image,
                                                     [inst_obj],
                                                     instance_type=flavor)
        quotas_mock.assert_called_once_with(self.context, [resvs],
                                            instance=inst_obj)
        sig_mock.assert_called_once_with(self.context, request_spec,
                                         filter_props)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exc_info, request_spec)
        rollback_mock.assert_called_once_with()

    def test_cold_migrate_no_valid_host_error_msg(self):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid='fake',
            user_id='fake')
        request_spec = dict(instance_type=dict(extra_specs=dict()),
                            instance_properties=dict())
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        image = 'fake-image'

        with test.nested(
            mock.patch.object(utils, 'get_image_from_system_metadata',
                              return_value=image),
            mock.patch.object(scheduler_utils, 'build_request_spec',
                              return_value=request_spec),
            mock.patch.object(self.conductor, '_set_vm_state_and_notify'),
            mock.patch.object(migrate.MigrationTask,
                              'execute',
                              side_effect=exc.NoValidHost(reason="")),
            mock.patch.object(migrate.MigrationTask, 'rollback')
        ) as (image_mock, brs_mock, set_vm_mock, task_execute_mock,
              task_rollback_mock):
            nvh = self.assertRaises(exc.NoValidHost,
                                    self.conductor._cold_migrate, self.context,
                                    inst_obj, flavor, filter_props, [resvs],
                                    clean_shutdown=True)
            self.assertIn('cold migrate', nvh.message)

    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch('nova.scheduler.utils.build_request_spec')
    @mock.patch.object(migrate.MigrationTask, 'execute')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_cold_migrate_no_valid_host_in_group(self,
                                                 set_vm_mock,
                                                 task_rollback_mock,
                                                 task_exec_mock,
                                                 brs_mock,
                                                 image_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid='fake',
            user_id='fake')
        request_spec = dict(instance_type=dict(extra_specs=dict()),
                            instance_properties=dict())
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        image = 'fake-image'
        exception = exc.UnsupportedPolicyException(reason='')

        image_mock.return_value = image
        brs_mock.return_value = request_spec
        task_exec_mock.side_effect = exception

        self.assertRaises(exc.UnsupportedPolicyException,
                          self.conductor._cold_migrate, self.context,
                          inst_obj, flavor, filter_props, [resvs],
                          clean_shutdown=True)

        updates = {'vm_state': vm_states.STOPPED, 'task_state': None}
        set_vm_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exception, request_spec)

    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(objects.Quotas, 'from_reservations')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def test_cold_migrate_exception_host_in_error_state_and_raise(
            self, prep_resize_mock, rollback_mock, notify_mock,
            select_dest_mock, quotas_mock, metadata_mock, spec_fp_mock,
            sig_mock, brs_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid='fake',
            user_id='fake')
        image = 'fake-image'
        request_spec = dict(instance_type=dict(),
                            instance_properties=dict(),
                            image=image)
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        fake_spec = objects.RequestSpec()

        hosts = [dict(host='host1', nodename=None, limits={})]
        metadata_mock.return_value = image
        brs_mock.return_value = request_spec
        spec_fp_mock.return_value = fake_spec
        exc_info = test.TestingException('something happened')
        select_dest_mock.return_value = hosts

        updates = {'vm_state': vm_states.STOPPED,
                   'task_state': None}
        prep_resize_mock.side_effect = exc_info
        self.assertRaises(test.TestingException,
                          self.conductor._cold_migrate,
                          self.context, inst_obj, flavor,
                          filter_props, [resvs],
                          clean_shutdown=True)

        metadata_mock.assert_called_with({})
        brs_mock.assert_called_once_with(self.context, image,
                                                     [inst_obj],
                                                     instance_type=flavor)
        quotas_mock.assert_called_once_with(self.context, [resvs],
                                            instance=inst_obj)
        sig_mock.assert_called_once_with(self.context, request_spec,
                                         filter_props)
        select_dest_mock.assert_called_once_with(
            self.context, fake_spec)
        prep_resize_mock.assert_called_once_with(
            self.context, image, inst_obj, flavor,
            hosts[0]['host'], [resvs],
            request_spec=request_spec,
            filter_properties=filter_props,
            node=hosts[0]['nodename'], clean_shutdown=True)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exc_info, request_spec)
        rollback_mock.assert_called_once_with()

    def test_resize_no_valid_host_error_msg(self):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        flavor_new = flavors.get_flavor_by_name('m1.small')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid='fake',
            user_id='fake')

        request_spec = dict(instance_type=dict(extra_specs=dict()),
                            instance_properties=dict())
        filter_props = dict(context=None)
        resvs = 'fake-resvs'
        image = 'fake-image'

        with test.nested(
            mock.patch.object(utils, 'get_image_from_system_metadata',
                              return_value=image),
            mock.patch.object(scheduler_utils, 'build_request_spec',
                              return_value=request_spec),
            mock.patch.object(self.conductor, '_set_vm_state_and_notify'),
            mock.patch.object(migrate.MigrationTask,
                              'execute',
                              side_effect=exc.NoValidHost(reason="")),
            mock.patch.object(migrate.MigrationTask, 'rollback')
        ) as (image_mock, brs_mock, vm_st_mock, task_execute_mock,
              task_rb_mock):
            nvh = self.assertRaises(exc.NoValidHost,
                                    self.conductor._cold_migrate, self.context,
                                    inst_obj, flavor_new, filter_props,
                                    [resvs], clean_shutdown=True)
            self.assertIn('resize', nvh.message)

    def test_build_instances_instance_not_found(self):
        instances = [fake_instance.fake_instance_obj(self.context)
                for i in range(2)]
        self.mox.StubOutWithMock(instances[0], 'refresh')
        self.mox.StubOutWithMock(instances[1], 'refresh')
        image = {'fake-data': 'should_pass_silently'}
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance')

        scheduler_utils.build_request_spec(self.context, image,
                mox.IgnoreArg()).AndReturn(spec)
        filter_properties = {'retry': {'num_attempts': 1, 'hosts': []}}
        self.conductor_manager._schedule_instances(self.context,
                spec, filter_properties).AndReturn(
                        [{'host': 'host1', 'nodename': 'node1', 'limits': []},
                         {'host': 'host2', 'nodename': 'node2', 'limits': []}])
        instances[0].refresh().AndRaise(
                exc.InstanceNotFound(instance_id=instances[0].uuid))
        instances[1].refresh()
        self.conductor_manager.compute_rpcapi.build_and_run_instance(
                self.context, instance=instances[1], host='host2',
                image={'fake-data': 'should_pass_silently'}, request_spec=spec,
                filter_properties={'limits': [],
                                   'retry': {'num_attempts': 1,
                                             'hosts': [['host2',
                                                        'node2']]}},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=mox.IsA(objects.BlockDeviceMappingList),
                node='node2', limits=[])
        self.mox.ReplayAll()

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.conductor.build_instances(self.context,
                instances=instances,
                image=image,
                filter_properties={},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping='block_device_mapping',
                legacy_bdm=False)

    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_utils, 'build_request_spec')
    def test_build_instances_info_cache_not_found(self, build_request_spec,
                                                  setup_instance_group):
        instances = [fake_instance.fake_instance_obj(self.context)
                for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}
        destinations = [{'host': 'host1', 'nodename': 'node1', 'limits': []},
                {'host': 'host2', 'nodename': 'node2', 'limits': []}]
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}
        build_request_spec.return_value = spec
        with test.nested(
                mock.patch.object(instances[0], 'refresh',
                    side_effect=exc.InstanceInfoCacheNotFound(
                        instance_uuid=instances[0].uuid)),
                mock.patch.object(instances[1], 'refresh'),
                mock.patch.object(objects.RequestSpec, 'from_primitives'),
                mock.patch.object(self.conductor_manager.scheduler_client,
                    'select_destinations', return_value=destinations),
                mock.patch.object(self.conductor_manager.compute_rpcapi,
                    'build_and_run_instance')
                ) as (inst1_refresh, inst2_refresh, from_primitives,
                        select_destinations,
                        build_and_run_instance):

            # build_instances() is a cast, we need to wait for it to complete
            self.useFixture(cast_as_call.CastAsCall(self.stubs))

            self.conductor.build_instances(self.context,
                    instances=instances,
                    image=image,
                    filter_properties={},
                    admin_password='admin_password',
                    injected_files='injected_files',
                    requested_networks=None,
                    security_groups='security_groups',
                    block_device_mapping='block_device_mapping',
                    legacy_bdm=False)

            # NOTE(sbauza): Due to populate_retry() later in the code,
            # filter_properties is dynamically modified
            setup_instance_group.assert_called_once_with(
                self.context, spec, {'retry': {'num_attempts': 1,
                                               'hosts': []}})
            build_and_run_instance.assert_called_once_with(self.context,
                    instance=instances[1], host='host2', image={'fake-data':
                        'should_pass_silently'}, request_spec=spec,
                    filter_properties={'limits': [],
                                       'retry': {'num_attempts': 1,
                                                 'hosts': [['host2',
                                                            'node2']]}},
                    admin_password='admin_password',
                    injected_files='injected_files',
                    requested_networks=None,
                    security_groups='security_groups',
                    block_device_mapping=mock.ANY,
                    node='node2', limits=[])


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
